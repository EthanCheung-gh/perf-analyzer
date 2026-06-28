from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from .alerts import (
    alert_segments,
    metric_alert_bounds,
    metric_alert_deviation_percent,
    metric_alert_mask,
    metric_alert_rule_text,
)
from .config import config_ui_bool, config_ui_float, config_ui_list
from .metrics import metric_by_key
from .models import Metric
from .ui_helpers import (
    render_plotly_chart,
    sanitize_multiselect_state,
    sanitize_select_state,
    with_display_label,
)


def build_alerts_table(
    data: pd.DataFrame,
    metrics: list[Metric],
    thresholds: dict[str, float],
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> pd.DataFrame:
    alert_frames = []
    for metric in metrics:
        if metric.key not in data:
            continue
        mask = metric_alert_mask(data[metric.key], metric, thresholds, threshold_bounds)
        alert = data[mask][["timestamp", "source", "scene", metric.key]].copy()
        if alert.empty:
            continue
        alert["指标"] = metric.label
        alert["正常区间/阈值"] = metric_alert_rule_text(metric, thresholds, threshold_bounds)
        alert["值"] = alert[metric.key]
        lower, upper = metric_alert_bounds(threshold_bounds, metric)
        if lower is not None or upper is not None:
            alert["告警类型"] = "区间异常"
            if lower is not None:
                alert.loc[alert["值"] < lower, "告警类型"] = "低于下限"
            if upper is not None:
                alert.loc[alert["值"] > upper, "告警类型"] = "高于上限"
        else:
            alert["告警类型"] = "高于阈值" if metric.higher_is_worse else "低于阈值"
        alert["偏离阈值比例(%)"] = metric_alert_deviation_percent(alert["值"], metric, thresholds, threshold_bounds)
        alert_frames.append(alert[["timestamp", "source", "scene", "指标", "值", "正常区间/阈值", "告警类型", "偏离阈值比例(%)"]])
    return pd.concat(alert_frames, ignore_index=True).sort_values("timestamp") if alert_frames else pd.DataFrame()


def build_alert_timeline_figure(alerts: pd.DataFrame) -> go.Figure:
    timeline = with_display_label(alerts.rename(columns={"timestamp": "timestamp"}))
    timeline["偏离阈值比例(%)"] = timeline["偏离阈值比例(%)"].fillna(0)
    fig = px.scatter(
        timeline,
        x="timestamp",
        y="display_scene",
        color="指标",
        size="偏离阈值比例(%)",
        hover_data=["source", "scene", "值", "正常区间/阈值", "告警类型", "偏离阈值比例(%)"],
        labels={"timestamp": "时间", "display_scene": "场景", "偏离阈值比例(%)": "偏离阈值比例(%)"},
        title="异常时间轴",
    )
    fig.update_traces(marker=dict(sizemin=6))
    fig.update_layout(height=420, margin=dict(l=20, r=20, t=50, b=20))
    return fig


def render_alerts(
    data: pd.DataFrame,
    selected_scenes: list[str],
    thresholds: dict[str, float],
    metrics: list[Metric],
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> None:
    st.subheader("异常点")
    with st.expander("口径说明", expanded=False):
        st.write("- 未配置上下限时，异常点由侧边栏阈值和告警方向决定。")
        st.write("- 配置了 lower_threshold / upper_threshold 时，值低于下限或高于上限都算异常。")
    filtered = data[data["scene"].isin(selected_scenes)].copy()
    alerts = build_alerts_table(filtered, metrics, thresholds, threshold_bounds)
    if alerts.empty:
        st.success("当前阈值下没有异常点。")
        return

    segments = alert_segments(filtered, thresholds, metrics, threshold_bounds)
    if not segments.empty:
        st.markdown("**异常段摘要**")
        with st.expander("异常段口径", expanded=False):
            st.write("- 异常段把同一数据源、场景、指标下连续发生的异常点合并为一段。")
            st.write("- 相邻异常点之间的间隔不超过典型采样间隔的 1.5 倍时，会归为同一段。")
            st.write("- 持续时长会补上一个典型采样间隔，因此单点异常也会有约一个采样周期的持续时长。")
        display_segments = segments.drop(columns=["指标key", "持续时长(分钟)"], errors="ignore")
        st.dataframe(display_segments, use_container_width=True, hide_index=True)
        st.download_button(
            "下载异常段 CSV",
            segments.to_csv(index=False).encode("utf-8-sig"),
            file_name="resource_alert_segments.csv",
            mime="text/csv",
        )
        segment_chart = segments.head(20).copy()
        segment_chart["异常段标识"] = (
            segment_chart["数据源"].astype(str)
            + " / "
            + segment_chart["场景"].astype(str)
            + " / "
            + segment_chart["指标"].astype(str)
            + " #"
            + segment_chart["异常段"].astype(str)
        )
        fig_segments = px.bar(
            segment_chart.sort_values("持续时长(分钟)", ascending=True),
            x="持续时长(分钟)",
            y="异常段标识",
            color="告警类型",
            orientation="h",
            hover_data=["开始时间", "结束时间", "异常点数", "最小值", "最大值", "正常区间/阈值"],
            title="异常段持续时长 Top 20",
        )
        fig_segments.update_layout(height=max(360, 26 * len(segment_chart) + 120), margin=dict(l=20, r=20, t=50, b=20))
        render_plotly_chart(fig_segments, "异常段持续时长Top20")

        st.markdown("**异常段多指标联动图**")
        linked_segments = segments.copy()
        linked_segments["异常段标识"] = (
            linked_segments["数据源"].astype(str)
            + " / "
            + linked_segments["场景"].astype(str)
            + " / "
            + linked_segments["指标"].astype(str)
            + " #"
            + linked_segments["异常段"].astype(str)
            + " "
            + linked_segments["开始时间"].astype(str)
        )
        segment_options = list(linked_segments["异常段标识"])
        sanitize_select_state("alert_segment_detail", segment_options)
        selected_segment_id = st.selectbox(
            "查看异常段",
            segment_options,
            key="alert_segment_detail",
            help="选择一个异常段后，会展示该时间窗口内多个指标的同步变化。",
        )
        selected_segment = linked_segments[linked_segments["异常段标识"] == selected_segment_id].iloc[0]
        col1, col2, col3 = st.columns(3)
        imported_config = st.session_state.get("imported_config", {})
        before_minutes = col1.number_input(
            "前置窗口(分钟)",
            min_value=0.0,
            value=config_ui_float(imported_config, "alerts", "before_minutes", 5.0),
            step=1.0,
            key="alert_before_minutes",
            help="从异常开始时间向前扩展的观察窗口。",
        )
        after_minutes = col2.number_input(
            "后置窗口(分钟)",
            min_value=0.0,
            value=config_ui_float(imported_config, "alerts", "after_minutes", 5.0),
            step=1.0,
            key="alert_after_minutes",
            help="从异常结束时间向后扩展的观察窗口。",
        )
        normalize_linked = col3.checkbox(
            "标准化显示",
            value=config_ui_bool(imported_config, "alerts", "normalize_linked", True),
            key="alert_normalize_linked",
            help="把每个指标缩放到 0-1，便于不同单位的指标放在同一张图里比较形态。",
        )

        scene_window = filtered[
            (filtered["source"] == selected_segment["数据源"])
            & (filtered["scene"] == selected_segment["场景"])
            & (filtered["timestamp"] >= selected_segment["开始时间"] - pd.Timedelta(minutes=float(before_minutes)))
            & (filtered["timestamp"] <= selected_segment["结束时间"] + pd.Timedelta(minutes=float(after_minutes)))
        ].sort_values("timestamp")
        available_metric_keys = [metric.key for metric in metrics if metric.key in scene_window and scene_window[metric.key].notna().any()]
        metric_labels = {metric.key: metric.label for metric in metrics}
        default_linked_metrics = [selected_segment["指标key"]]
        configured_linked_metrics = config_ui_list(imported_config, "alerts", "linked_metrics", [])
        if configured_linked_metrics:
            default_linked_metrics = configured_linked_metrics
        for candidate in available_metric_keys:
            if candidate not in default_linked_metrics:
                default_linked_metrics.append(candidate)
            if len(default_linked_metrics) >= 4:
                break
        sanitize_multiselect_state("alert_linked_metrics", available_metric_keys)
        linked_metric_keys = st.multiselect(
            "联动指标",
            available_metric_keys,
            default=[key for key in default_linked_metrics if key in available_metric_keys],
            format_func=lambda key: metric_labels.get(key, key),
            key="alert_linked_metrics",
            help="选择要在异常段前后同窗查看的指标。建议 2-5 个，过多会降低可读性。",
        )
        if scene_window.empty or not linked_metric_keys:
            st.info("当前异常段窗口内没有可展示的联动指标。")
        else:
            linked_fig = go.Figure()
            for metric_key in linked_metric_keys:
                metric = metric_by_key(metrics, metric_key)
                values = scene_window[["timestamp", metric_key]].dropna()
                if values.empty:
                    continue
                y = values[metric_key].astype(float)
                y_label = metric.label
                if normalize_linked:
                    min_value = y.min()
                    max_value = y.max()
                    y = (y - min_value) / (max_value - min_value) if max_value != min_value else y * 0
                    y_label = f"{metric.label}(0-1)"
                linked_fig.add_trace(
                    go.Scatter(
                        x=values["timestamp"],
                        y=y,
                        mode="lines+markers",
                        name=y_label,
                    )
                )
            linked_fig.add_vrect(
                x0=selected_segment["开始时间"],
                x1=selected_segment["结束时间"],
                fillcolor="#d62728",
                opacity=0.12,
                line_width=0,
                annotation_text="异常段",
                annotation_position="top left",
            )
            linked_fig.update_layout(
                title=f"{selected_segment['数据源']} / {selected_segment['场景']} 异常段联动",
                xaxis_title="时间",
                yaxis_title="标准化值" if normalize_linked else "原始值",
                height=430,
                margin=dict(l=20, r=20, t=50, b=20),
            )
            render_plotly_chart(linked_fig, f"异常段联动_{selected_segment['数据源']}_{selected_segment['场景']}_{selected_segment['指标']}")

    with st.expander("异常时间轴口径", expanded=False):
        st.write("- 每个点是一条超阈采样记录，横轴是时间，纵轴是场景或数据源/场景。")
        st.write("- 颜色表示指标，点大小表示相对阈值的偏离程度；点越密集，说明异常越集中或持续。")
    fig = build_alert_timeline_figure(alerts)
    render_plotly_chart(fig, "异常时间轴")

    st.dataframe(alerts, use_container_width=True, hide_index=True)
    st.download_button(
        "下载异常点 CSV",
        alerts.to_csv(index=False).encode("utf-8-sig"),
        file_name="resource_alerts.csv",
        mime="text/csv",
    )
