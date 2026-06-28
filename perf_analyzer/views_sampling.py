from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from .config import config_ui_choice
from .stats import percentile
from .ui_helpers import render_plotly_chart, safe_option_index, sanitize_select_state, with_display_label


def build_sampling_interval_tables(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    filtered = with_display_label(data.copy())
    interval_frames = []
    summary_rows = []
    for (source, scene, display_scene), group in filtered.groupby(["source", "scene", "display_scene"], sort=False):
        series = group.sort_values("timestamp")[["timestamp"]].dropna().copy()
        if len(series) < 2:
            continue
        series["采样间隔(秒)"] = series["timestamp"].diff().dt.total_seconds()
        series = series.dropna()
        series = series[series["采样间隔(秒)"] >= 0]
        if series.empty:
            continue
        series["source"] = source
        series["scene"] = scene
        series["display_scene"] = display_scene
        interval_frames.append(series)
        values = series["采样间隔(秒)"]
        summary_rows.append(
            {
                "数据源": source,
                "场景": scene,
                "间隔样本数": len(values),
                "中位间隔(秒)": float(values.median()),
                "P95间隔(秒)": percentile(values, 0.95),
                "最大间隔(秒)": float(values.max()),
                "最小间隔(秒)": float(values.min()),
            }
        )
    interval_data = pd.concat(interval_frames, ignore_index=True) if interval_frames else pd.DataFrame()
    summary = pd.DataFrame(summary_rows).sort_values("P95间隔(秒)", ascending=False) if summary_rows else pd.DataFrame()
    return interval_data, summary


def build_sampling_interval_box(interval_data: pd.DataFrame) -> go.Figure:
    box = px.box(
        interval_data,
        x="display_scene",
        y="采样间隔(秒)",
        color="display_scene",
        points="outliers",
        labels={"display_scene": "场景"},
        title="采样间隔分布",
    )
    box.update_layout(height=360, showlegend=False, margin=dict(l=20, r=20, t=50, b=20))
    return box


def build_sampling_interval_line(interval_data: pd.DataFrame, line_scene: str) -> go.Figure:
    line_data = interval_data[interval_data["display_scene"] == line_scene]
    line = px.line(
        line_data,
        x="timestamp",
        y="采样间隔(秒)",
        markers=True,
        title=f"{line_scene} 采样间隔时间线",
    )
    line.update_layout(height=360, margin=dict(l=20, r=20, t=50, b=20))
    return line


def render_sampling_interval(data: pd.DataFrame, selected_scenes: list[str]) -> None:
    st.markdown("**采样间隔**")
    with st.expander("采样间隔口径", expanded=False):
        st.write("- 采样间隔由同一数据源/场景内相邻时间戳相减得到。")
        st.write("- 中位数代表典型采样频率，P95/最大值用于发现采集卡顿、丢点或上传中断。")
        st.write("- 该图只检查时间戳连续性，不判断指标值本身是否异常。")
    filtered = data[data["scene"].isin(selected_scenes)].copy()
    interval_data, summary = build_sampling_interval_tables(filtered)
    if interval_data.empty:
        st.info("当前数据不足以计算采样间隔。")
        return

    st.dataframe(summary, use_container_width=True, hide_index=True)

    box = build_sampling_interval_box(interval_data)
    render_plotly_chart(box, "采样间隔分布")

    line_scene_options = list(interval_data["display_scene"].drop_duplicates())
    sanitize_select_state("sampling_interval_scene", line_scene_options)
    imported_config = st.session_state.get("imported_config", {})
    line_scene_default = config_ui_choice(imported_config, "sampling_interval", "scene", line_scene_options, line_scene_options[0])
    line_scene = st.selectbox(
        "采样间隔时间线场景",
        line_scene_options,
        index=safe_option_index(line_scene_options, line_scene_default),
        key="sampling_interval_scene",
        help="选择一个场景查看采样间隔随时间的变化，尖峰通常表示采集延迟或缺口。",
    )
    line = build_sampling_interval_line(interval_data, line_scene)
    render_plotly_chart(line, f"采样间隔时间线_{line_scene}")
