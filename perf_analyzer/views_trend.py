from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from .config import config_ui_bool, config_ui_choice, config_ui_float, config_ui_int
from .metrics import metric_by_key
from .models import Metric
from .stats import percentile
from .time_utils import rolling_points_for_group
from .ui_helpers import render_plotly_chart, with_display_label


def add_trend_reference_layers(
    fig: go.Figure,
    filtered: pd.DataFrame,
    metric: Metric,
    thresholds: dict[str, float],
    threshold_bounds: dict[str, tuple[float | None, float | None]],
    band_mode: str,
) -> None:
    if band_mode != "关闭":
        lower: float | None = None
        upper: float | None = None
        band_label = ""
        if band_mode == "配置上下限":
            lower, upper = threshold_bounds.get(metric.key, (None, None))
            band_label = "配置区间"
        else:
            values = filtered[metric.key].dropna()
            lower = percentile(values, 0.05)
            upper = percentile(values, 0.95)
            band_label = "P5-P95"
        if lower is not None and upper is not None and not pd.isna(lower) and not pd.isna(upper):
            fig.add_hrect(
                y0=lower,
                y1=upper,
                fillcolor="#2ca02c",
                opacity=0.10,
                line_width=0,
                annotation_text=band_label,
                annotation_position="top left",
            )
        elif upper is not None and not pd.isna(upper):
            fig.add_hline(y=upper, line_dash="dot", line_color="#2ca02c", annotation_text=f"{band_label}上限")
        elif lower is not None and not pd.isna(lower):
            fig.add_hline(y=lower, line_dash="dot", line_color="#2ca02c", annotation_text=f"{band_label}下限")
    if metric.key in thresholds:
        fig.add_hline(
            y=thresholds[metric.key],
            line_dash="dash",
            line_color="#d62728",
            annotation_text="阈值",
        )


def build_trend_figure(
    filtered: pd.DataFrame,
    metric: Metric,
    thresholds: dict[str, float],
    threshold_bounds: dict[str, tuple[float | None, float | None]],
    band_mode: str = "自动P5-P95",
    show_rolling: bool = False,
    rolling_mode: str = "按采样点数",
    rolling_window: int = 5,
    rolling_time_seconds: float = 300.0,
) -> go.Figure:
    fig = px.line(
        filtered,
        x="timestamp",
        y=metric.key,
        color="display_scene",
        markers=False,
        labels={"timestamp": "时间", metric.key: f"{metric.label}({metric.unit})", "display_scene": "场景"},
        title=f"{metric.label}时间趋势",
    )
    add_trend_reference_layers(fig, filtered, metric, thresholds, threshold_bounds, band_mode)
    if show_rolling:
        for display_scene, group in filtered.groupby("display_scene", sort=False):
            rolling = group.sort_values("timestamp")[["timestamp", metric.key]].dropna()
            if rolling.empty:
                continue
            window_points = rolling_points_for_group(rolling, rolling_mode, int(rolling_window), float(rolling_time_seconds))
            rolling["rolling_mean"] = rolling[metric.key].rolling(window_points, min_periods=1).mean()
            fig.add_trace(
                go.Scatter(
                    x=rolling["timestamp"],
                    y=rolling["rolling_mean"],
                    mode="lines",
                    name=f"{display_scene} 滚动均值({window_points}点)",
                    line=dict(width=3, dash="dash"),
                )
            )
    fig.update_layout(height=360, margin=dict(l=20, r=20, t=50, b=20))
    return fig


def render_trend(
    data: pd.DataFrame,
    selected_scenes: list[str],
    selected_metrics: list[str],
    thresholds: dict[str, float],
    threshold_bounds: dict[str, tuple[float | None, float | None]],
    metrics: list[Metric],
) -> None:
    st.subheader("趋势分析")
    with st.expander("口径说明", expanded=False):
        st.write("- 趋势图按采样时间绘制，适合观察尖峰、持续高水位和随时间爬升。")
        st.write("- 红色虚线是侧边栏配置的告警阈值。")
        st.write("- 滚动均值用于过滤瞬时噪声；上下限区间带可来自导入配置，也可按当前数据 P5-P95 自动生成。")
        st.write("- 多数据源上传时，同名场景会按“数据源 / 场景”区分。")
    filtered = data[data["scene"].isin(selected_scenes)].copy()
    if filtered.empty:
        st.warning("当前筛选条件下没有数据。")
        return
    filtered = with_display_label(filtered)

    col1, col2, col3, col4 = st.columns(4)
    show_rolling = col1.checkbox(
        "显示滚动均值",
        value=config_ui_bool(st.session_state.get("imported_config", {}), "trend", "show_rolling", True),
        key="trend_show_rolling",
        help="按每个数据源/场景分别计算滚动平均，用于看清持续趋势，避免单个尖峰干扰判断。",
    )
    rolling_mode_default = config_ui_choice(
        st.session_state.get("imported_config", {}),
        "trend",
        "rolling_mode",
        ["按采样点数", "按时间窗口"],
        "按采样点数",
    )
    rolling_mode = col2.selectbox(
        "滚动窗口模式",
        ["按采样点数", "按时间窗口"],
        index=["按采样点数", "按时间窗口"].index(rolling_mode_default),
        key="trend_rolling_mode",
        disabled=not show_rolling,
        help="按采样点数适合固定频率数据；按时间窗口会根据每个场景的典型采样间隔自动换算点数。",
    )
    rolling_window = col3.number_input(
        "滚动窗口采样点数",
        min_value=2,
        max_value=200,
        value=config_ui_int(st.session_state.get("imported_config", {}), "trend", "rolling_window", 5),
        step=1,
        key="trend_rolling_window",
        disabled=not show_rolling or rolling_mode != "按采样点数",
        help="窗口越大越平滑，但也会弱化短时间波动。",
    )
    rolling_time_seconds = col3.number_input(
        "滚动时间窗口(秒)",
        min_value=0.1,
        value=config_ui_float(st.session_state.get("imported_config", {}), "trend", "rolling_time_seconds", 300.0),
        step=10.0,
        key="trend_rolling_time_seconds",
        disabled=not show_rolling or rolling_mode != "按时间窗口",
        help="按每个数据源/场景的中位采样间隔换算为采样点数，最小为 2 个点。",
    )
    default_band_mode = "配置上下限" if any(any(bound is not None for bound in bounds) for bounds in threshold_bounds.values()) else "自动P5-P95"
    default_band_mode = config_ui_choice(st.session_state.get("imported_config", {}), "trend", "band_mode", ["关闭", "配置上下限", "自动P5-P95"], default_band_mode)
    band_mode = col4.selectbox(
        "上下限区间带",
        ["关闭", "配置上下限", "自动P5-P95"],
        index=["关闭", "配置上下限", "自动P5-P95"].index(default_band_mode),
        key="trend_band_mode",
        help="配置上下限来自导入 JSON 的 lower_threshold / upper_threshold；自动 P5-P95 用当前筛选数据的分位区间做参考带。",
    )

    for metric_key in selected_metrics:
        metric = metric_by_key(metrics, metric_key)
        if filtered[metric.key].dropna().empty:
            continue
        fig = build_trend_figure(
            filtered,
            metric,
            thresholds,
            threshold_bounds,
            band_mode,
            bool(show_rolling),
            rolling_mode,
            int(rolling_window),
            float(rolling_time_seconds),
        )
        render_plotly_chart(fig, f"趋势_{metric.label}")
