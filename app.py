from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from perf_analyzer.analysis import (
    alert_continuity_summary,
    apply_stable_window,
    bottleneck_hints,
    capacity_estimation,
    configuration_recommendation,
    leak_analysis,
    linear_slope_per_minute,
    metric_stats,
    radar_profile_data,
    release_gate_analysis,
    resource_efficiency_analysis,
    risk_matrix_data,
    scene_decision_analysis,
    stability_score_analysis,
    summarize,
    trend_analysis,
    version_regression_heatmap_data,
)
from perf_analyzer.alerts import (
    alert_segments,
    format_duration,
    format_peak_offset,
    format_value,
    max_continuous_alert_minutes,
    metric_alert_bounds,
    metric_alert_deviation_percent,
    metric_alert_mask,
    metric_alert_rule_text,
)
from perf_analyzer.config import (
    build_config_template,
    build_settings_config,
    config_analysis_mode,
    config_analysis_text,
    config_analysis_value,
    config_field_aliases,
    config_to_json_bytes,
    config_ui_bool,
    config_ui_choice,
    config_ui_float,
    config_ui_int,
    config_ui_list,
    configured_metric_from_import,
    metric_config_entry,
    metric_bounds_from_import,
    threshold_from_import,
    validate_config,
)
from perf_analyzer.constants import (
    ANALYSIS_MODES,
    GENERIC_MODE,
    GENERIC_SAMPLE_FILE,
    PERFORMANCE_MODE,
    SAMPLE_FILE,
)
from perf_analyzer.export import build_batch_export_zip as build_batch_export_zip_core
from perf_analyzer.export import dataframe_to_csv_bytes
from perf_analyzer.io import non_numeric_column_summary, read_single_workbook, timestamp_diagnostics
from perf_analyzer.metrics import discover_metrics, metric_by_key
from perf_analyzer.models import Metric
from perf_analyzer.quality import metric_quality_summary, sampling_gap_issue_summary, timestamp_quality_summary
from perf_analyzer.report import (
    build_conclusions,
    build_generic_conclusions,
    build_generic_report_markdown,
    build_report_html,
    build_report_markdown,
    dataframe_to_markdown,
)
from perf_analyzer.stats import coefficient_of_variation, iqr, percentile, percentile_95
from perf_analyzer.time_utils import rolling_points_for_group, typical_sampling_seconds
from perf_analyzer.ui_helpers import (
    render_plotly_chart,
    render_system_info,
    safe_option_index,
    sanitize_multiselect_state,
    sanitize_select_state,
    sync_filter_context,
    with_display_label,
)
from perf_analyzer.utils import (
    parse_aliases,
)


@st.cache_data(show_spinner=False)
def load_single_workbook(
    source_name: str,
    uploaded_file: bytes | None,
    field_alias_items: tuple[tuple[str, tuple[str, ...]], ...],
    analysis_mode: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sample_file = GENERIC_SAMPLE_FILE if analysis_mode == GENERIC_MODE else SAMPLE_FILE
    return read_single_workbook(source_name, uploaded_file, field_alias_items, analysis_mode, sample_file)


def load_workbooks(
    files: tuple[tuple[str, bytes | None], ...],
    field_aliases: dict[str, tuple[str, ...]],
    analysis_mode: str = PERFORMANCE_MODE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    # 多文件上传时，每个 Excel 文件名作为 source，后续可用于版本/批次对比。
    systems = []
    frames = []
    field_alias_items = tuple(sorted(field_aliases.items()))
    for source_name, payload in files:
        system_info, data = load_single_workbook(source_name, payload, field_alias_items, analysis_mode)
        if not system_info.empty:
            systems.append(system_info)
        if not data.empty:
            frames.append(data)
    system = pd.concat(systems, ignore_index=True) if systems else pd.DataFrame()
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return system, data


@st.cache_data(show_spinner=False)
def load_timestamp_diagnostics(
    files: tuple[tuple[str, bytes | None], ...],
    field_alias_items: tuple[tuple[str, tuple[str, ...]], ...],
    analysis_mode: str = PERFORMANCE_MODE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sample_file = GENERIC_SAMPLE_FILE if analysis_mode == GENERIC_MODE else SAMPLE_FILE
    return timestamp_diagnostics(files, field_alias_items, sample_file)


@st.cache_data(show_spinner=False)
def load_non_numeric_column_summary(
    files: tuple[tuple[str, bytes | None], ...],
    field_alias_items: tuple[tuple[str, tuple[str, ...]], ...],
    analysis_mode: str = PERFORMANCE_MODE,
) -> pd.DataFrame:
    sample_file = GENERIC_SAMPLE_FILE if analysis_mode == GENERIC_MODE else SAMPLE_FILE
    return non_numeric_column_summary(files, field_alias_items, sample_file)


def parse_json_config(uploaded_file: object | None) -> dict:
    if uploaded_file is None:
        return {}
    try:
        payload = uploaded_file.getvalue()
        return json.loads(payload.decode("utf-8-sig"))
    except Exception as exc:
        st.sidebar.warning(f"配置文件读取失败：{exc}")
        return {}


def render_config_validation(config: dict, metrics: list[Metric] | None = None) -> None:
    errors, warnings = validate_config(config, metrics)
    if not errors and not warnings:
        if config:
            st.sidebar.success("配置校验通过。")
        return
    with st.sidebar.expander("配置校验", expanded=bool(errors)):
        for error in errors:
            st.error(error)
        for warning in warnings:
            st.warning(warning)


def render_timestamp_diagnostics(raw_summary: pd.DataFrame, failures: pd.DataFrame, data: pd.DataFrame) -> None:
    quality = timestamp_quality_summary(data)
    has_parse_failures = not raw_summary.empty and int(raw_summary["解析失败数"].fillna(0).sum()) > 0
    has_quality_issues = (
        not quality.empty
        and (
            int(quality["重复时间戳"].fillna(0).sum()) > 0
            or int(quality["乱序次数"].fillna(0).sum()) > 0
            or int(quality["负采样间隔"].fillna(0).sum()) > 0
        )
    )
    expanded = bool(has_parse_failures or has_quality_issues)
    with st.expander("时间字段诊断", expanded=expanded):
        st.caption("用于确认时间列识别、解析成功率、毫秒精度、重复时间戳和采样顺序问题。")
        if raw_summary.empty:
            st.info("没有可展示的原始时间列诊断。")
        else:
            total_rows = int(raw_summary["总行数"].fillna(0).sum())
            total_non_empty = int(raw_summary["非空时间值"].fillna(0).sum())
            total_success = int(raw_summary["解析成功数"].fillna(0).sum())
            total_failed = int(raw_summary["解析失败数"].fillna(0).sum())
            success_rate = total_success / total_non_empty * 100 if total_non_empty else np.nan
            min_time = data["timestamp"].min() if "timestamp" in data and not data.empty else pd.NaT
            max_time = data["timestamp"].max() if "timestamp" in data and not data.empty else pd.NaT
            has_subsecond = (
                bool(((data["timestamp"].dropna().dt.microsecond != 0) | (data["timestamp"].dropna().dt.nanosecond != 0)).any())
                if "timestamp" in data and data["timestamp"].notna().any()
                else False
            )

            cols = st.columns(6)
            cols[0].metric("原始行数", f"{total_rows:,}")
            cols[1].metric("非空时间值", f"{total_non_empty:,}")
            cols[2].metric("解析成功率", "-" if pd.isna(success_rate) else f"{success_rate:.1f}%")
            cols[3].metric("解析失败", f"{total_failed:,}")
            cols[4].metric("毫秒/亚秒", "是" if has_subsecond else "否")
            cols[5].metric("有效分组", f"{data[['source', 'scene']].drop_duplicates().shape[0] if not data.empty else 0:,}")

            if pd.notna(min_time) and pd.notna(max_time):
                st.caption(f"时间范围：{min_time} 至 {max_time}，总跨度 {max_time - min_time}")
            st.markdown("**原始时间列解析摘要**")
            st.dataframe(raw_summary, use_container_width=True, hide_index=True)
            st.download_button(
                "下载时间解析摘要 CSV",
                raw_summary.to_csv(index=False).encode("utf-8-sig"),
                file_name="timestamp_parse_summary.csv",
                mime="text/csv",
            )

        if not failures.empty:
            st.markdown("**解析失败样本 Top5/分组**")
            st.dataframe(failures, use_container_width=True, hide_index=True)
            st.download_button(
                "下载时间解析失败样本 CSV",
                failures.to_csv(index=False).encode("utf-8-sig"),
                file_name="timestamp_parse_failures.csv",
                mime="text/csv",
            )

        if quality.empty:
            st.info("没有足够的有效时间点用于时间序列质量诊断。")
        else:
            st.markdown("**时间序列质量**")
            st.dataframe(quality, use_container_width=True, hide_index=True)
            st.download_button(
                "下载时间序列质量 CSV",
                quality.to_csv(index=False).encode("utf-8-sig"),
                file_name="timestamp_quality.csv",
                mime="text/csv",
            )


def render_data_quality(
    data: pd.DataFrame,
    metrics: list[Metric],
    non_numeric_columns: pd.DataFrame,
) -> None:
    st.subheader("数据质量")
    with st.expander("口径说明", expanded=False):
        st.write("- 时间质量用于发现重复时间戳、乱序时间和负采样间隔。")
        st.write("- 指标质量用于发现空值率高、全空、常量和疑似极端值的指标。")
        st.write("- 采样间隔突变按同一数据源/分组的中位采样间隔 3 倍作为参考阈值。")
        st.write("- 未识别非数值列不会进入指标分析，通常是备注、状态、标签等字段。")

    time_quality = timestamp_quality_summary(data)
    metric_quality = metric_quality_summary(data, metrics)
    interval_data, _ = build_sampling_interval_tables(data)
    gap_quality = sampling_gap_issue_summary(interval_data)

    duplicate_count = int(time_quality["重复时间戳"].fillna(0).sum()) if not time_quality.empty else 0
    disorder_count = int(time_quality["乱序次数"].fillna(0).sum()) if not time_quality.empty else 0
    high_null_count = int((metric_quality["空值率(%)"].fillna(0) >= 50).sum()) if not metric_quality.empty else 0
    constant_count = int((metric_quality["常量"] == "是").sum()) if not metric_quality.empty else 0
    gap_count = int(gap_quality["突变次数"].fillna(0).sum()) if not gap_quality.empty else 0

    cols = st.columns(5)
    cols[0].metric("重复时间戳", f"{duplicate_count:,}")
    cols[1].metric("乱序时间", f"{disorder_count:,}")
    cols[2].metric("高空值指标", f"{high_null_count:,}")
    cols[3].metric("常量指标", f"{constant_count:,}")
    cols[4].metric("采样突变", f"{gap_count:,}")

    if not time_quality.empty:
        st.markdown("**时间质量**")
        st.dataframe(time_quality, use_container_width=True, hide_index=True)
        st.download_button(
            "下载时间质量 CSV",
            dataframe_to_csv_bytes(time_quality),
            file_name="data_quality_timestamp.csv",
            mime="text/csv",
        )

    if not metric_quality.empty:
        st.markdown("**指标质量**")
        st.dataframe(metric_quality, use_container_width=True, hide_index=True)
        st.download_button(
            "下载指标质量 CSV",
            dataframe_to_csv_bytes(metric_quality),
            file_name="data_quality_metrics.csv",
            mime="text/csv",
        )

    if not gap_quality.empty:
        st.markdown("**采样间隔突变**")
        st.dataframe(gap_quality, use_container_width=True, hide_index=True)
        st.download_button(
            "下载采样突变 CSV",
            dataframe_to_csv_bytes(gap_quality),
            file_name="data_quality_sampling_gaps.csv",
            mime="text/csv",
        )

    if not non_numeric_columns.empty:
        st.markdown("**未识别非数值列**")
        st.dataframe(non_numeric_columns, use_container_width=True, hide_index=True)
        st.download_button(
            "下载未识别非数值列 CSV",
            dataframe_to_csv_bytes(non_numeric_columns),
            file_name="data_quality_non_numeric_columns.csv",
            mime="text/csv",
        )


def session_value(key: str, default: object) -> object:
    return st.session_state.get(key, default)


def build_ui_settings() -> dict:
    return {
        "trend": {
            "show_rolling": session_value("trend_show_rolling", True),
            "rolling_mode": session_value("trend_rolling_mode", "按采样点数"),
            "rolling_window": session_value("trend_rolling_window", 5),
            "rolling_time_seconds": session_value("trend_rolling_time_seconds", 300.0),
            "band_mode": session_value("trend_band_mode", "自动P5-P95"),
        },
        "alerts": {
            "before_minutes": session_value("alert_before_minutes", 5.0),
            "after_minutes": session_value("alert_after_minutes", 5.0),
            "normalize_linked": session_value("alert_normalize_linked", True),
            "linked_metrics": session_value("alert_linked_metrics", []),
        },
        "version_compare": {
            "stat": session_value("version_compare_stat", "p95"),
            "metric": session_value("version_compare_metric", ""),
            "baseline_source": session_value("version_compare_baseline_source", ""),
            "regression_threshold": session_value("version_regression_threshold", 15.0),
        },
        "baseline_growth": {
            "baseline": session_value("baseline_growth_baseline", ""),
            "stat": session_value("baseline_growth_stat", "p95"),
            "metric": session_value("baseline_growth_metric", ""),
        },
        "distribution": {
            "metric": session_value("distribution_metric", ""),
            "control_metric": session_value("control_chart_metric", ""),
            "control_scene": session_value("control_chart_scene", ""),
        },
        "efficiency": {
            "metric": session_value("efficiency_metric", ""),
            "scatter_y": session_value("efficiency_scatter_y", ""),
        },
        "sampling_interval": {
            "scene": session_value("sampling_interval_scene", ""),
        },
        "decision": {
            "max_allowed_level": session_value("decision_max_allowed_level", "中风险"),
            "fail_on_leak": session_value("decision_fail_on_leak", True),
            "fail_on_any_alert": session_value("decision_fail_on_any_alert", False),
            "fail_on_errors": session_value("decision_fail_on_errors", False),
        },
        "capacity": {
            "test_cpu_cores": session_value("capacity_test_cpu_cores", 8),
            "target_cpu_utilization": session_value("capacity_target_cpu_utilization", 70.0),
            "reserved_memory_gb": session_value("capacity_reserved_memory_gb", 2.0),
            "throughput_targets": session_value("capacity_throughput_targets", "50,100,200"),
        },
        "configuration_recommendation": {
            "test_cpu_cores": session_value("config_test_cpu_cores", 8),
            "target_cpu_utilization": session_value("config_target_cpu_utilization", 70.0),
            "minimum_cpu_cores": session_value("config_minimum_cpu_cores", 2),
            "system_reserved_memory_gb": session_value("config_reserved_memory_gb", 2.0),
            "minimum_memory_gb": session_value("config_minimum_memory_gb", 4),
            "minimum_free_disk_gb": session_value("config_minimum_free_disk_gb", 10),
            "recommendation_factor": session_value("config_recommendation_factor", 1.5),
        },
        "filters": {
            "selected_sources": session_value("selected_sources", []),
            "selected_groups": session_value("selected_scenes", []),
            "selected_trend_metrics": session_value("selected_trend_metrics", []),
        },
    }


def render_overview(
    data: pd.DataFrame,
    thresholds: dict[str, float],
    metrics: list[Metric],
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> None:
    st.subheader("概览")
    cols = st.columns(5)
    cols[0].metric("场景数", data["scene"].nunique())
    cols[1].metric("样本数", f"{len(data):,}")
    cols[2].metric("CPU峰值", format_value(data["cpu_percent"].max(), "%") if "cpu_percent" in data else "-")
    cols[3].metric("内存峰值", format_value(data["memory_mb"].max(), "MB") if "memory_mb" in data else "-")
    cols[4].metric("告警点", f"{count_alerts(data, thresholds, metrics, threshold_bounds):,}")

    summary = summarize(data, thresholds, metrics, threshold_bounds)
    st.dataframe(summary, use_container_width=True, hide_index=True)

    alert_summary = alert_continuity_summary(data, thresholds, metrics, threshold_bounds)
    if not alert_summary.empty:
        st.markdown("**告警持续性摘要**")
        st.dataframe(
            alert_summary.drop(columns=["最大连续超阈(分钟)"], errors="ignore"),
            use_container_width=True,
            hide_index=True,
        )


def count_alerts(
    data: pd.DataFrame,
    thresholds: dict[str, float],
    metrics: list[Metric],
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> int:
    total = 0
    for metric in metrics:
        if metric.key in data:
            total += int(metric_alert_mask(data[metric.key], metric, thresholds, threshold_bounds).sum())
    return total


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


def build_distribution_figure(filtered: pd.DataFrame, metric: Metric) -> go.Figure:
    fig = px.box(
        filtered,
        x="display_scene",
        y=metric.key,
        color="display_scene",
        points="outliers",
        labels={"display_scene": "场景", metric.key: metric.label},
        title=f"{metric.label}分布",
    )
    fig.update_layout(height=360, showlegend=False, margin=dict(l=20, r=20, t=50, b=20))
    return fig


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


def build_batch_export_zip(
    data: pd.DataFrame,
    selected_scenes: list[str],
    selected_metrics: list[str],
    thresholds: dict[str, float],
    threshold_bounds: dict[str, tuple[float | None, float | None]],
    metrics: list[Metric],
    analysis_mode: str,
    group_label: str,
    export_mode: str = "轻量模式",
    export_options: dict[str, object] | None = None,
) -> bytes:
    return build_batch_export_zip_core(
        data,
        selected_scenes,
        selected_metrics,
        thresholds,
        threshold_bounds,
        metrics,
        analysis_mode,
        group_label,
        build_alerts_table=build_alerts_table,
        build_sampling_interval_tables=build_sampling_interval_tables,
        build_trend_figure=build_trend_figure,
        build_distribution_figure=build_distribution_figure,
        build_alert_timeline_figure=build_alert_timeline_figure,
        build_sampling_interval_box=build_sampling_interval_box,
        build_sampling_interval_line=build_sampling_interval_line,
        export_mode=export_mode,
        export_options=export_options,
    )


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


def render_comparison(data: pd.DataFrame, selected_scenes: list[str], metrics: list[Metric]) -> None:
    st.subheader("场景对比")
    filtered = with_display_label(data[data["scene"].isin(selected_scenes)].copy())
    long_rows = []
    for scene, group in filtered.groupby("display_scene", sort=False):
        for metric in metrics:
            values = group[metric.key].dropna()
            if values.empty:
                continue
            long_rows.append({"场景": scene, "指标key": metric.key, "指标": metric.label, "统计": "均值", "值": values.mean()})
            long_rows.append({"场景": scene, "指标key": metric.key, "指标": metric.label, "统计": "峰值", "值": values.max()})
            long_rows.append({"场景": scene, "指标key": metric.key, "指标": metric.label, "统计": "P90", "值": percentile(values, 0.90)})
            long_rows.append({"场景": scene, "指标key": metric.key, "指标": metric.label, "统计": "P95", "值": percentile_95(values)})
            long_rows.append({"场景": scene, "指标key": metric.key, "指标": metric.label, "统计": "P99", "值": percentile(values, 0.99)})
            long_rows.append({"场景": scene, "指标key": metric.key, "指标": metric.label, "统计": "标准差", "值": values.std(ddof=0)})
            long_rows.append({"场景": scene, "指标key": metric.key, "指标": metric.label, "统计": "IQR", "值": iqr(values)})
            long_rows.append({"场景": scene, "指标key": metric.key, "指标": metric.label, "统计": "变异系数", "值": coefficient_of_variation(values)})
            long_rows.append({"场景": scene, "指标key": metric.key, "指标": metric.label, "统计": "趋势斜率", "值": linear_slope_per_minute(group, metric.key)[0]})

    compare = pd.DataFrame(long_rows)
    if compare.empty:
        st.info("没有可用于对比的数值指标。")
        return

    metric_options = list(compare["指标key"].drop_duplicates())
    metric_labels = compare.drop_duplicates("指标key").set_index("指标key")["指标"].to_dict()
    sanitize_select_state("comparison_metric", metric_options)
    metric_key = st.selectbox(
        "对比指标",
        metric_options,
        format_func=lambda key: metric_labels.get(key, key),
        key="comparison_metric",
        help="选择要横向比较的指标。核心指标和 Excel 中识别出的语义化/动态指标都会出现在这里。",
    )
    stat = st.radio(
        "统计口径",
        ["均值", "峰值", "P90", "P95", "P99", "标准差", "IQR", "变异系数", "趋势斜率"],
        index=3,
        horizontal=True,
        key="comparison_stat",
        help="均值看整体水平，P95/P99 看高水位和尾部风险，标准差/IQR/变异系数看波动，趋势斜率看是否随时间上升或下降。",
    )
    metric_label = metric_labels.get(metric_key, metric_key)
    chart_data = compare[(compare["指标key"] == metric_key) & (compare["统计"] == stat)]
    fig = px.bar(chart_data, x="场景", y="值", color="场景", title=f"{metric_label}{stat}对比")
    fig.update_layout(height=360, showlegend=False, margin=dict(l=20, r=20, t=50, b=20))
    render_plotly_chart(fig, f"对比_{metric_label}_{stat}")


def render_distribution(data: pd.DataFrame, selected_scenes: list[str], metrics: list[Metric]) -> None:
    st.subheader("分布与相关性")
    with st.expander("口径说明", expanded=False):
        st.write("- 箱线图适合观察指标分布、中位数、离群点和波动范围。")
        st.write("- 相关性热力图只表示线性相关，不代表因果关系。")
    filtered = with_display_label(data[data["scene"].isin(selected_scenes)].copy())
    available = [metric for metric in metrics if metric.key in filtered and not filtered[metric.key].dropna().empty]
    if not available:
        st.info("没有可用于分布分析的指标。")
        return

    metric_options = [metric.key for metric in available]
    metric_labels = {metric.key: metric.label for metric in available}
    imported_config = st.session_state.get("imported_config", {})
    sanitize_select_state("distribution_metric", metric_options)
    distribution_metric_default = config_ui_choice(imported_config, "distribution", "metric", metric_options, metric_options[0])
    metric_key = st.selectbox(
        "分布指标",
        metric_options,
        index=safe_option_index(metric_options, distribution_metric_default),
        format_func=lambda key: metric_labels.get(key, key),
        key="distribution_metric",
        help="箱线图用于观察该指标在不同场景中的分布、离群点和波动范围。",
    )
    metric = metric_by_key(available, metric_key)
    fig = build_distribution_figure(filtered, metric)
    render_plotly_chart(fig, f"分布_{metric.label}")

    numeric_cols = [metric.key for metric in available]
    corr = filtered[numeric_cols].corr(numeric_only=True)
    if not corr.empty:
        labels = {metric.key: metric.label for metric in metrics}
        corr = corr.rename(index=labels, columns=labels)
        heatmap = go.Figure(
            data=go.Heatmap(
                z=corr.values,
                x=corr.columns,
                y=corr.index,
                colorscale="RdBu",
                zmin=-1,
                zmax=1,
                colorbar=dict(title="相关系数"),
            )
        )
        heatmap.update_layout(title="指标相关性", height=420, margin=dict(l=20, r=20, t=50, b=20))
        render_plotly_chart(heatmap, "指标相关性")

    st.markdown("**控制图**")
    with st.expander("控制图口径", expanded=False):
        st.write("- 中心线为当前序列均值，UCL/LCL 为均值上下 3 倍标准差。")
        st.write("- 超出控制限表示统计波动异常，适合发现突发漂移、采集异常或工况突变。")
        st.write("- 控制图不是业务阈值；它回答的是“这段数据是否偏离自身历史波动范围”。")
    sanitize_select_state("control_chart_metric", metric_options)
    control_metric_default = config_ui_choice(imported_config, "distribution", "control_metric", metric_options, metric.key)
    control_metric_key = st.selectbox(
        "控制图指标",
        metric_options,
        index=safe_option_index(metric_options, control_metric_default),
        format_func=lambda key: metric_labels.get(key, key),
        key="control_chart_metric",
        help="选择要做统计过程控制的指标。建议选择连续采样、波动有业务意义的指标。",
    )
    control_metric = metric_by_key(available, control_metric_key)
    scene_options = list(filtered["display_scene"].drop_duplicates())
    sanitize_select_state("control_chart_scene", scene_options)
    control_scene_default = config_ui_choice(imported_config, "distribution", "control_scene", scene_options, scene_options[0])
    control_scene = st.selectbox(
        "控制图场景",
        scene_options,
        index=safe_option_index(scene_options, control_scene_default),
        key="control_chart_scene",
        help="控制图一次只展示一个场景或数据源，避免不同批次混在一起导致控制限失真。",
    )
    control_data = filtered[filtered["display_scene"] == control_scene].sort_values("timestamp")
    control_values = control_data[["timestamp", control_metric.key]].dropna()
    if len(control_values) < 3:
        st.info("控制图至少需要 3 个有效采样点。")
    else:
        mean_value = float(control_values[control_metric.key].mean())
        std_value = float(control_values[control_metric.key].std(ddof=0))
        ucl = mean_value + 3 * std_value
        lcl = mean_value - 3 * std_value
        out_mask = (control_values[control_metric.key] > ucl) | (control_values[control_metric.key] < lcl)
        control_fig = go.Figure()
        control_fig.add_trace(
            go.Scatter(
                x=control_values["timestamp"],
                y=control_values[control_metric.key],
                mode="lines+markers",
                name=control_metric.label,
                line=dict(color="#1f77b4"),
            )
        )
        if out_mask.any():
            outliers = control_values[out_mask]
            control_fig.add_trace(
                go.Scatter(
                    x=outliers["timestamp"],
                    y=outliers[control_metric.key],
                    mode="markers",
                    name="超控制限",
                    marker=dict(color="#d62728", size=9, symbol="x"),
                )
            )
        control_fig.add_hline(y=mean_value, line_color="#333", annotation_text="均值")
        control_fig.add_hline(y=ucl, line_dash="dash", line_color="#d62728", annotation_text="UCL")
        control_fig.add_hline(y=lcl, line_dash="dash", line_color="#d62728", annotation_text="LCL")
        control_fig.update_layout(
            title=f"{control_scene} / {control_metric.label} 控制图",
            height=420,
            margin=dict(l=20, r=20, t=50, b=20),
        )
        render_plotly_chart(control_fig, f"控制图_{control_scene}_{control_metric.label}")


def render_efficiency(data: pd.DataFrame, selected_scenes: list[str]) -> None:
    st.subheader("资源效率")
    with st.expander("口径说明", expanded=False):
        st.write("- 效率分析会优先用 QPS、TPS、任务数或请求数作为吞吐口径。")
        st.write("- CPU P95/吞吐越低，表示单位吞吐 CPU 成本越低。")
        st.write("- 内存峰值/并发越低，表示单位并发内存成本越低。")
    filtered = data[data["scene"].isin(selected_scenes)].copy()
    if filtered.empty:
        st.warning("当前筛选条件下没有数据。")
        return
    efficiency = resource_efficiency_analysis(filtered)
    if efficiency.empty:
        st.info("没有可用于资源效率分析的数据。")
        return

    st.caption("资源效率把 CPU、内存、IO、网络、磁盘等资源消耗归一化到吞吐或并发口径，适合判断版本是否真的变差。")
    st.dataframe(efficiency, use_container_width=True, hide_index=True)

    ratio_columns = [
        "CPU P95/吞吐",
        "内存峰值/并发(MB)",
        "IO P95/吞吐",
        "网络KBps/吞吐",
        "磁盘MBps/吞吐",
        "失败率(%)",
        "每千请求错误数",
    ]
    available = [column for column in ratio_columns if column in efficiency and efficiency[column].notna().any()]
    if not available:
        st.info("当前数据缺少吞吐、并发、请求数等字段，无法绘制效率指标。")
        return

    imported_config = st.session_state.get("imported_config", {})
    sanitize_select_state("efficiency_metric", available)
    efficiency_metric_default = config_ui_choice(imported_config, "efficiency", "metric", available, available[0])
    metric_column = st.selectbox(
        "效率指标",
        available,
        index=safe_option_index(available, efficiency_metric_default),
        key="efficiency_metric",
        help="效率指标会把资源消耗归一化到吞吐或并发口径，更适合判断资源上涨是否真的退化。",
    )
    chart_data = efficiency.copy()
    chart_data["场景标识"] = chart_data["数据源"].astype(str) + " / " + chart_data["场景"].astype(str)
    fig = px.bar(chart_data, x="场景标识", y=metric_column, color="数据源", title=f"{metric_column} 对比")
    fig.update_layout(height=380, margin=dict(l=20, r=20, t=50, b=20))
    render_plotly_chart(fig, f"资源效率_{metric_column}")

    st.markdown("**吞吐-资源散点图**")
    scatter_y_options = [
        column
        for column in ["CPU P95", "内存峰值(MB)", "响应时间P95(ms)", "FPS P95", "GC耗时P95(ms)", "失败率(%)"]
        if column in efficiency and efficiency[column].notna().any()
    ]
    if "平均吞吐" in efficiency and efficiency["平均吞吐"].notna().any() and scatter_y_options:
        sanitize_select_state("efficiency_scatter_y", scatter_y_options)
        scatter_y_default = config_ui_choice(imported_config, "efficiency", "scatter_y", scatter_y_options, scatter_y_options[0])
        scatter_y = st.selectbox(
            "散点图纵轴",
            scatter_y_options,
            index=safe_option_index(scatter_y_options, scatter_y_default),
            key="efficiency_scatter_y",
            help="横轴固定为平均吞吐。点越靠右表示吞吐越高，纵轴可切换 CPU、内存、响应时间等指标。",
        )
        scatter = px.scatter(
            chart_data,
            x="平均吞吐",
            y=scatter_y,
            size="内存峰值(MB)" if "内存峰值(MB)" in chart_data else None,
            color="数据源",
            hover_name="场景标识",
            labels={"平均吞吐": "平均吞吐", scatter_y: scatter_y},
            title=f"平均吞吐 vs {scatter_y}",
        )
        scatter.update_layout(height=420, margin=dict(l=20, r=20, t=50, b=20))
        render_plotly_chart(scatter, f"吞吐资源散点_{scatter_y}")


def render_decision(
    data: pd.DataFrame,
    selected_scenes: list[str],
    thresholds: dict[str, float],
    metrics: list[Metric],
    slope_threshold: float,
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> None:
    st.subheader("决策分析")
    filtered = data[data["scene"].isin(selected_scenes)].copy()
    if filtered.empty:
        st.warning("当前筛选条件下没有数据。")
        return

    with st.expander("口径说明", expanded=False):
        st.write("- 场景风险评级会综合超阈占比、最长连续超阈、内存趋势、失败率、响应时间和 FPS 等规则。")
        st.write("- 发布门禁用于把风险评级转换成通过/不通过，适合发版检查或测试准入。")
        st.write("- 容量估算是基于当前样本的单位资源成本做线性外推，正式配置结论仍需要目标机器实测。")

    decisions = scene_decision_analysis(filtered, thresholds, metrics, slope_threshold, threshold_bounds)
    st.markdown("**场景风险评级**")
    if decisions.empty:
        st.info("没有可用于风险评级的数据。")
        return
    st.dataframe(decisions, use_container_width=True, hide_index=True)

    matrix = risk_matrix_data(decisions)
    if not matrix.empty:
        st.markdown("**风险矩阵**")
        matrix_pivot = matrix.pivot(index="场景标识", columns="风险项", values="风险分").fillna(0)
        risk_fig = go.Figure(
            data=go.Heatmap(
                z=matrix_pivot.values,
                x=matrix_pivot.columns,
                y=matrix_pivot.index,
                zmin=0,
                zmax=2,
                colorscale=[[0, "#2ca02c"], [0.5, "#ffbf00"], [1, "#d62728"]],
                colorbar=dict(title="风险分", tickvals=[0, 1, 2], ticktext=["低", "中", "高"]),
                text=matrix_pivot.values,
                texttemplate="%{text:.0f}",
            )
        )
        risk_fig.update_layout(title="场景风险矩阵", height=360, margin=dict(l=20, r=20, t=50, b=20))
        render_plotly_chart(risk_fig, "场景风险矩阵")

    radar_data = radar_profile_data(filtered, decisions, thresholds)
    if not radar_data.empty:
        st.markdown("**风险雷达图**")
        scene_options = list(radar_data["场景标识"].drop_duplicates())
        selected_radar_scenes = st.multiselect(
            "雷达图场景",
            scene_options,
            default=scene_options[: min(3, len(scene_options))],
            help="选择要在雷达图中对比的场景。建议一次选择 1-3 个，避免图形过密。",
        )
        radar_fig = go.Figure()
        for scene_id in selected_radar_scenes:
            scene_profile = radar_data[radar_data["场景标识"] == scene_id]
            dimensions = list(scene_profile["维度"])
            values = list(scene_profile["风险分"])
            if dimensions:
                radar_fig.add_trace(
                    go.Scatterpolar(
                        r=[*values, values[0]],
                        theta=[*dimensions, dimensions[0]],
                        fill="toself",
                        name=scene_id,
                    )
                )
        radar_fig.update_layout(
            title="场景风险画像",
            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
            height=460,
            margin=dict(l=20, r=20, t=50, b=20),
        )
        render_plotly_chart(radar_fig, "场景风险雷达图")

    st.markdown("**发布门禁**")
    imported_config = st.session_state.get("imported_config", {})
    col1, col2, col3, col4 = st.columns(4)
    max_allowed_default = config_ui_choice(imported_config, "decision", "max_allowed_level", ["低风险", "中风险", "高风险"], "中风险")
    max_allowed_level = col1.selectbox(
        "允许最高风险等级",
        ["低风险", "中风险", "高风险"],
        index=["低风险", "中风险", "高风险"].index(max_allowed_default),
        key="decision_max_allowed_level",
        help="如果某个场景的风险等级高于这里选择的等级，发布门禁会判定失败。",
    )
    fail_on_leak = col2.checkbox(
        "疑似泄漏即失败",
        value=config_ui_bool(imported_config, "decision", "fail_on_leak", True),
        key="decision_fail_on_leak",
        help="勾选后，只要任意场景被内存趋势检测标记为疑似泄漏，发布门禁就失败。",
    )
    fail_on_any_alert = col3.checkbox(
        "任意超阈即失败",
        value=config_ui_bool(imported_config, "decision", "fail_on_any_alert", False),
        key="decision_fail_on_any_alert",
        help="勾选后，只要任意指标出现过超阈采样点，发布门禁就失败。适合严格准入场景。",
    )
    fail_on_errors = col4.checkbox(
        "请求失败即失败",
        value=config_ui_bool(imported_config, "decision", "fail_on_errors", False),
        key="decision_fail_on_errors",
        help="勾选后，只要请求失败率大于 0，发布门禁就失败。需要 Excel 中有请求数和失败请求数字段。",
    )
    gate_status, gate_rules = release_gate_analysis(decisions, max_allowed_level, fail_on_leak, fail_on_any_alert, fail_on_errors)
    st.metric("发布门禁", gate_status)
    st.dataframe(gate_rules, use_container_width=True, hide_index=True)

    st.markdown("**稳定性评分**")
    stability = stability_score_analysis(decisions)
    st.dataframe(stability, use_container_width=True, hide_index=True)

    st.markdown("**瓶颈提示**")
    bottlenecks = bottleneck_hints(filtered, thresholds, metrics)
    st.dataframe(bottlenecks, use_container_width=True, hide_index=True)

    st.markdown("**容量估算**")
    col5, col6, col7 = st.columns(3)
    test_cpu_cores = col5.number_input(
        "容量估算测试机CPU核数",
        min_value=1,
        value=config_ui_int(imported_config, "capacity", "test_cpu_cores", 8),
        step=1,
        key="capacity_test_cpu_cores",
        help="采集这批性能数据时测试机的逻辑 CPU 核数，用于把 CPU% 换算成核心需求。",
    )
    target_cpu_utilization = col6.number_input(
        "容量估算目标CPU上限(%)",
        min_value=30.0,
        max_value=95.0,
        value=config_ui_float(imported_config, "capacity", "target_cpu_utilization", 70.0),
        step=5.0,
        key="capacity_target_cpu_utilization",
        help="希望目标机器长期运行时 CPU 不超过的利用率。值越低，估算出的 CPU 核数越保守。",
    )
    reserved_memory = col7.number_input(
        "容量估算系统预留内存(GB)",
        min_value=0.0,
        value=config_ui_float(imported_config, "capacity", "reserved_memory_gb", 2.0),
        step=0.5,
        key="capacity_reserved_memory_gb",
        help="为操作系统、后台进程和运行时预留的内存，会叠加到应用内存需求上。",
    )
    throughput_text = st.text_input(
        "目标吞吐列表",
        value=str(config_ui_value(imported_config, "capacity", "throughput_targets", "50,100,200")),
        key="capacity_throughput_targets",
        help="多个目标吞吐用英文逗号分隔，口径沿用效率页自动识别的 QPS/TPS/任务数/请求数。",
    )
    try:
        targets = [float(item.strip()) for item in throughput_text.split(",") if item.strip()]
    except ValueError:
        st.warning("目标吞吐列表需要是数字，并用英文逗号分隔。")
        targets = []
    capacity = capacity_estimation(filtered, int(test_cpu_cores), float(target_cpu_utilization), targets, float(reserved_memory))
    if capacity.empty:
        st.info("缺少吞吐或并发字段，无法做容量估算。")
    else:
        st.dataframe(capacity, use_container_width=True, hide_index=True)
        curve = go.Figure()
        curve.add_trace(
            go.Scatter(
                x=capacity["目标吞吐"],
                y=capacity["建议CPU核数"],
                mode="lines+markers",
                name="建议CPU核数",
                line=dict(color="#1f77b4"),
            )
        )
        if "内存需求(GB)" in capacity and capacity["内存需求(GB)"].notna().any():
            curve.add_trace(
                go.Scatter(
                    x=capacity["目标吞吐"],
                    y=capacity["内存需求(GB)"],
                    mode="lines+markers",
                    name="内存需求(GB)",
                    yaxis="y2",
                    line=dict(color="#2ca02c"),
                )
            )
        curve.update_layout(
            title="容量曲线",
            xaxis=dict(title="目标吞吐"),
            yaxis=dict(title="建议CPU核数"),
            yaxis2=dict(title="内存需求(GB)", overlaying="y", side="right"),
            height=420,
            margin=dict(l=20, r=20, t=50, b=20),
        )
        render_plotly_chart(curve, "容量曲线")


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


def render_baseline_growth(data: pd.DataFrame, selected_scenes: list[str], metrics: list[Metric]) -> None:
    st.subheader("基准场景增长率")
    filtered = data[data["scene"].isin(selected_scenes)].copy()
    if filtered.empty:
        st.warning("当前筛选条件下没有数据。")
        return

    group_cols = ["source", "scene"] if filtered["source"].nunique() > 1 else ["scene"]
    stats = metric_stats(filtered, group_cols, metrics)
    if stats.empty:
        st.info("没有可用于基准对比的指标。")
        return

    stats = with_display_label(stats) if "source" in stats.columns else stats.assign(display_scene=stats["scene"])
    imported_config = st.session_state.get("imported_config", {})
    baseline_options = list(stats["display_scene"])
    sanitize_select_state("baseline_growth_baseline", baseline_options)
    baseline_default = config_ui_choice(imported_config, "baseline_growth", "baseline", baseline_options, baseline_options[0])
    baseline = st.selectbox(
        "基准场景",
        baseline_options,
        index=baseline_options.index(baseline_default),
        key="baseline_growth_baseline",
        help="选择一个场景作为对照组，其他场景会计算相对它的增长率。",
    )
    stat_labels = {
        "mean": "均值",
        "max": "峰值",
        "p90": "P90",
        "p95": "P95",
        "p99": "P99",
        "std": "标准差",
        "iqr": "IQR",
        "cv": "变异系数",
        "slope": "趋势斜率",
    }
    stat_name = st.radio(
        "统计口径",
        list(stat_labels),
        index=list(stat_labels).index(config_ui_choice(imported_config, "baseline_growth", "stat", list(stat_labels), "p95")),
        format_func=stat_labels.get,
        horizontal=True,
        key="baseline_growth_stat",
        help="选择用于计算增长率的统计口径。P95/P99 更适合观察高水位退化，均值更适合观察整体负载变化。",
    )
    baseline_row = stats[stats["display_scene"] == baseline].iloc[0]
    rows = []
    for _, row in stats.iterrows():
        for metric in metrics:
            column = f"{metric.key}_{stat_name}"
            if column not in row or pd.isna(row[column]):
                continue
            base_value = baseline_row.get(column, np.nan)
            growth = np.nan if pd.isna(base_value) or base_value == 0 else (row[column] - base_value) / base_value * 100
            rows.append(
                {
                    "场景": row["display_scene"],
                    "指标": metric.label,
                    "当前值": row[column],
                    "基准值": base_value,
                    "相对增长率(%)": growth,
                }
            )
    result = pd.DataFrame(rows)
    st.dataframe(result, use_container_width=True, hide_index=True)

    metric_options = [metric.key for metric in metrics if metric.key in data and not data[metric.key].dropna().empty]
    metric_labels = {metric.key: metric.label for metric in metrics}
    if not metric_options:
        st.info("没有可用于绘制增长率图表的指标。")
        return
    sanitize_select_state("baseline_growth_metric", metric_options)
    baseline_metric_default = config_ui_choice(imported_config, "baseline_growth", "metric", metric_options, metric_options[0] if metric_options else "")
    metric_key = st.selectbox(
        "增长率图表指标",
        metric_options,
        index=safe_option_index(metric_options, baseline_metric_default),
        format_func=lambda key: metric_labels.get(key, key),
        key="baseline_growth_metric",
        help="选择要绘制增长率柱状图的指标。",
    )
    metric_label = metric_labels.get(metric_key, metric_key)
    chart_data = result[result["指标"] == metric_label]
    fig = px.bar(chart_data, x="场景", y="相对增长率(%)", color="场景", title=f"{metric_label}相对 {baseline} 的增长率")
    fig.add_hline(y=0, line_color="#666", line_width=1)
    fig.update_layout(height=360, showlegend=False, margin=dict(l=20, r=20, t=50, b=20))
    render_plotly_chart(fig, f"基准增长_{metric_label}")


def render_leak_detection(data: pd.DataFrame, selected_scenes: list[str], slope_threshold: float, metrics: list[Metric]) -> None:
    st.subheader("内存泄漏与趋势风险")
    with st.expander("口径说明", expanded=False):
        st.write("- 内存泄漏检测使用内存占用对运行分钟数做线性回归。")
        st.write("- 趋势斜率表示每分钟增长多少指标值，R2 表示线性趋势拟合程度。")
        st.write("- 这是快速筛查，不替代代码级泄漏定位。")
    filtered = data[data["scene"].isin(selected_scenes)].copy()
    if filtered.empty:
        st.warning("当前筛选条件下没有数据。")
        return
    st.markdown("**内存泄漏趋势检测**")
    result = leak_analysis(filtered, slope_threshold)
    st.dataframe(result, use_container_width=True, hide_index=True)

    chart_data = result.dropna(subset=["内存斜率(MB/分钟)"])
    if not chart_data.empty:
        chart_data["场景标识"] = chart_data["数据源"].astype(str) + " / " + chart_data["场景"].astype(str)
        fig = px.bar(chart_data, x="场景标识", y="内存斜率(MB/分钟)", color="判断", title="内存线性增长斜率")
        fig.add_hline(y=slope_threshold, line_dash="dash", line_color="#d62728", annotation_text="疑似泄漏阈值")
        fig.update_layout(height=360, margin=dict(l=20, r=20, t=50, b=20))
        render_plotly_chart(fig, "内存线性增长斜率")

    st.markdown("**全指标趋势斜率**")
    trends = trend_analysis(filtered, metrics)
    if trends.empty:
        st.info("没有可用于趋势风险分析的指标。")
        return
    st.dataframe(trends, use_container_width=True, hide_index=True)


def render_version_compare(data: pd.DataFrame, selected_scenes: list[str], metrics: list[Metric]) -> None:
    st.subheader("多文件版本对比")
    filtered = data[data["scene"].isin(selected_scenes)].copy()
    if filtered["source"].nunique() < 2:
        st.info("上传两个或更多 Excel 文件后，可在这里按数据源对比不同版本。")
        return
    stats = metric_stats(filtered, ["source", "scene"], metrics)
    metric_options = [metric.key for metric in metrics if any(column.startswith(f"{metric.key}_") for column in stats.columns)]
    metric_labels = {metric.key: metric.label for metric in metrics}
    if not metric_options:
        st.info("当前数据没有可用于版本对比的指标。")
        return
    imported_config = st.session_state.get("imported_config", {})
    sanitize_select_state("version_compare_metric", metric_options)
    version_metric_default = config_ui_choice(imported_config, "version_compare", "metric", metric_options, metric_options[0])
    metric_key = st.selectbox(
        "版本对比指标",
        metric_options,
        index=safe_option_index(metric_options, version_metric_default),
        format_func=lambda key: metric_labels.get(key, key),
        key="version_compare_metric",
        help="选择要在不同 Excel 文件之间对比的指标。上传文件名会作为版本/批次标识。",
    )
    metric = metric_by_key(metrics, metric_key)
    stat_labels = {
        "mean": "均值",
        "max": "峰值",
        "p90": "P90",
        "p95": "P95",
        "p99": "P99",
        "std": "标准差",
        "iqr": "IQR",
        "cv": "变异系数",
        "slope": "趋势斜率",
    }
    stat_name = st.radio(
        "版本对比口径",
        list(stat_labels),
        index=list(stat_labels).index(config_ui_choice(imported_config, "version_compare", "stat", list(stat_labels), "p95")),
        format_func=stat_labels.get,
        horizontal=True,
        key="version_compare_stat",
        help="选择版本对比使用的统计口径。P95/P99 适合高水位，峰值适合极端风险，趋势斜率适合观察随时间爬升。",
    )
    column = f"{metric.key}_{stat_name}"
    if column not in stats:
        st.info("当前指标没有可对比数据。")
        return
    sources = list(stats["source"].dropna().unique())
    sanitize_select_state("version_compare_baseline_source", sources)
    baseline_source_default = config_ui_choice(imported_config, "version_compare", "baseline_source", sources, sources[0])
    baseline_source = st.selectbox(
        "基准数据源",
        sources,
        index=safe_option_index(sources, baseline_source_default),
        key="version_compare_baseline_source",
        help="选择作为基准版本或基准批次的数据源。其他数据源会和它逐场景比较。",
    )
    regression_threshold = st.number_input(
        "退化判定阈值(%)",
        min_value=0.0,
        value=config_ui_float(imported_config, "version_compare", "regression_threshold", 15.0),
        step=5.0,
        key="version_regression_threshold",
        help="相对基准的变化超过该比例时标记为退化。对于 FPS、QPS 等越低越差的指标，会按下降幅度判断。",
    )

    pivot = stats.pivot(index="scene", columns="source", values=column).reset_index()
    st.dataframe(pivot, use_container_width=True, hide_index=True)

    baseline_values = stats[stats["source"] == baseline_source][["scene", column]].rename(columns={column: "基准值"})
    regression = stats[stats["source"] != baseline_source][["source", "scene", column]].merge(baseline_values, on="scene", how="left")
    if not regression.empty:
        regression = regression.rename(columns={"source": "数据源", column: "当前值"})
        regression["基准数据源"] = baseline_source
        regression["增长率(%)"] = np.where(
            regression["基准值"].isna() | (regression["基准值"] == 0),
            np.nan,
            (regression["当前值"] - regression["基准值"]) / regression["基准值"] * 100,
        )
        if metric.higher_is_worse:
            regression["判断"] = np.where(regression["增长率(%)"] > regression_threshold, "退化", "通过")
        else:
            regression["判断"] = np.where(regression["增长率(%)"] < -regression_threshold, "退化", "通过")
        regression.loc[regression["增长率(%)"].isna(), "判断"] = "基准不足"
        st.markdown("**退化判定**")
        st.dataframe(
            regression[["scene", "基准数据源", "数据源", "基准值", "当前值", "增长率(%)", "判断"]].rename(columns={"scene": "场景"}),
            use_container_width=True,
            hide_index=True,
        )

    heatmap_data = version_regression_heatmap_data(stats, metrics, baseline_source, stat_name)
    if not heatmap_data.empty:
        st.markdown("**版本退化热力图**")
        heatmap_pivot = heatmap_data.pivot(index="场景标识", columns="指标", values="退化幅度(%)")
        heatmap = go.Figure(
            data=go.Heatmap(
                z=heatmap_pivot.values,
                x=heatmap_pivot.columns,
                y=heatmap_pivot.index,
                colorscale="RdYlGn_r",
                zmid=0,
                colorbar=dict(title="退化幅度(%)"),
                hovertemplate="场景=%{y}<br>指标=%{x}<br>退化幅度=%{z:.2f}%<extra></extra>",
            )
        )
        heatmap.update_layout(
            title=f"相对 {baseline_source} 的{stat_labels[stat_name]}退化幅度",
            height=max(360, 40 * len(heatmap_pivot.index) + 140),
            margin=dict(l=20, r=20, t=50, b=20),
        )
        render_plotly_chart(heatmap, "版本退化热力图")

    long_data = stats[["source", "scene", column]].rename(columns={column: "值"})
    fig = px.bar(long_data, x="scene", y="值", color="source", barmode="group", title=f"不同数据源 {metric.label}{stat_labels[stat_name]} 对比")
    fig.update_layout(height=380, margin=dict(l=20, r=20, t=50, b=20))
    render_plotly_chart(fig, f"版本对比_{metric.label}_{stat_labels[stat_name]}")


def render_configuration_recommendation(data: pd.DataFrame, slope_threshold: float) -> tuple[pd.DataFrame, list[str]]:
    st.subheader("最低运行配置建议")
    st.caption("该结论基于当前筛选数据推导，适合做初步配置建议；正式发布最低配置前，仍建议在目标低配机器上实测验证。")

    imported_config = st.session_state.get("imported_config", {})
    col1, col2, col3 = st.columns(3)
    test_cpu_cores = col1.number_input(
        "测试机CPU核数",
        min_value=1,
        value=config_ui_int(imported_config, "configuration_recommendation", "test_cpu_cores", 8),
        step=1,
        key="config_test_cpu_cores",
        help="采集性能数据时测试机的逻辑 CPU 核数，用于把 CPU P95 换算成目标机器核心需求。",
    )
    target_cpu_utilization = col2.number_input(
        "目标CPU利用率上限(%)",
        min_value=30.0,
        max_value=95.0,
        value=config_ui_float(imported_config, "configuration_recommendation", "target_cpu_utilization", 70.0),
        step=5.0,
        key="config_target_cpu_utilization",
        help="希望目标机器长期运行时 CPU 不超过的利用率。通常 70% 是比较通用的保守值。",
    )
    minimum_cpu_cores = col3.number_input(
        "最低CPU核数下限",
        min_value=1,
        value=config_ui_int(imported_config, "configuration_recommendation", "minimum_cpu_cores", 2),
        step=1,
        key="config_minimum_cpu_cores",
        help="无论公式估算结果多低，最低配置都不会低于这个核数。",
    )

    col4, col5, col6 = st.columns(3)
    system_reserved_memory_gb = col4.number_input(
        "系统和后台预留内存(GB)",
        min_value=0.0,
        value=config_ui_float(imported_config, "configuration_recommendation", "system_reserved_memory_gb", 2.0),
        step=0.5,
        key="config_reserved_memory_gb",
        help="为操作系统、后台服务、运行时和缓存预留的内存，会叠加到应用内存峰值上。",
    )
    minimum_memory_gb = col5.number_input(
        "最低内存下限(GB)",
        min_value=1,
        value=config_ui_int(imported_config, "configuration_recommendation", "minimum_memory_gb", 4),
        step=1,
        key="config_minimum_memory_gb",
        help="无论公式估算结果多低，最低配置都不会低于这个内存容量。",
    )
    minimum_free_disk_gb = col6.number_input(
        "最低磁盘剩余空间(GB)",
        min_value=1,
        value=config_ui_int(imported_config, "configuration_recommendation", "minimum_free_disk_gb", 10),
        step=1,
        key="config_minimum_free_disk_gb",
        help="给安装包、日志、缓存、临时文件和运行数据预留的最低剩余磁盘空间。",
    )

    recommendation_factor = st.slider(
        "推荐配置安全系数",
        min_value=1.0,
        max_value=2.5,
        value=config_ui_float(imported_config, "configuration_recommendation", "recommendation_factor", 1.5),
        step=0.1,
        key="config_recommendation_factor",
        help="推荐配置会在最低配置基础上乘以该系数。系数越高，余量越大。",
    )
    config_table, notes = configuration_recommendation(
        data,
        int(test_cpu_cores),
        float(target_cpu_utilization),
        int(minimum_cpu_cores),
        float(system_reserved_memory_gb),
        int(minimum_memory_gb),
        int(minimum_free_disk_gb),
        float(recommendation_factor),
        slope_threshold,
    )

    st.dataframe(config_table, use_container_width=True, hide_index=True)

    st.markdown("**推导说明**")
    for note in notes:
        st.write(f"- {note}")

    st.markdown("**是否需要更多数据指标**")
    st.write("- 如果要更准确估算 CPU 核数，最好补充每核 CPU 使用率、进程 CPU 时间、任务吞吐量、响应时间或队列长度。只有总 CPU% 时，只能按总体占用近似换算。")
    st.write("- 如果软件有并发、批处理或服务端请求，建议补充并发数、TPS/QPS、任务量、数据规模，才能把配置结论和业务容量绑定。")
    st.write("- 如果 IO 可能是瓶颈，建议补充磁盘读写吞吐、IOPS、IO 等待时间、网络吞吐和错误重试次数。")
    st.write("- 如果需要正式发布最低配置，建议在至少一台目标低配机器上跑关键场景和长稳场景验证。")
    return config_table, notes


def render_report(
    data: pd.DataFrame,
    thresholds: dict[str, float],
    slope_threshold: float,
    metrics: list[Metric],
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
    config_table: pd.DataFrame | None = None,
    config_notes: list[str] | None = None,
) -> None:
    st.subheader("测试结论与报告导出")
    conclusions = build_conclusions(data, thresholds, slope_threshold, metrics, threshold_bounds)
    for item in conclusions:
        st.write(f"- {item}")

    markdown_report = build_report_markdown(data, thresholds, slope_threshold, metrics, threshold_bounds, config_table, config_notes)
    html_report = build_report_html(markdown_report)
    st.download_button(
        "下载 Markdown 报告",
        markdown_report.encode("utf-8-sig"),
        file_name="resource_report.md",
        mime="text/markdown",
    )
    st.download_button(
        "下载 HTML 报告",
        html_report.encode("utf-8-sig"),
        file_name="resource_report.html",
        mime="text/html",
    )
    st.caption("需要 PDF 时，可打开 HTML 报告后使用浏览器打印为 PDF。")


def render_generic_report(
    data: pd.DataFrame,
    thresholds: dict[str, float],
    metrics: list[Metric],
    group_label: str,
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> None:
    st.subheader("分析报告导出")
    conclusions = build_generic_conclusions(data, thresholds, metrics, threshold_bounds)
    for item in conclusions:
        st.write(f"- {item}")

    markdown_report = build_generic_report_markdown(data, thresholds, metrics, group_label, threshold_bounds)
    html_report = build_report_html(markdown_report)
    st.download_button(
        "下载 Markdown 报告",
        markdown_report.encode("utf-8-sig"),
        file_name="timeseries_report.md",
        mime="text/markdown",
    )
    st.download_button(
        "下载 HTML 报告",
        html_report.encode("utf-8-sig"),
        file_name="timeseries_report.html",
        mime="text/html",
    )
    st.caption("需要 PDF 时，可打开 HTML 报告后使用浏览器打印为 PDF。")


def ensure_sample_file(path: Path) -> None:
    if not path.exists():
        st.error(f"未找到示例数据：{path}")
        st.stop()


def main() -> None:
    st.set_page_config(page_title="时序指标分析", page_icon="📈", layout="wide")

    with st.sidebar:
        st.header("数据源")
        uploaded_files = st.file_uploader(
            "上传 Excel 文件",
            type=["xlsx", "xls"],
            accept_multiple_files=True,
            help="可以一次上传多个 Excel。文件名会作为数据源名称，用于版本对比和多批次对比。",
        )
        settings_file = st.file_uploader(
            "导入分析配置",
            type=["json"],
            help="可选。导入字段别名、阈值、告警方向、泄漏阈值和稳定区间。配置只覆盖能匹配上的指标，其他指标继续使用自动默认值。",
        )
        imported_config = parse_json_config(settings_file)
        st.session_state["imported_config"] = imported_config
        if imported_config:
            st.caption("已加载分析配置；未匹配的指标会自动忽略。")
        default_mode = config_analysis_mode(imported_config)
        analysis_mode = st.selectbox(
            "分析模式",
            ANALYSIS_MODES,
            index=ANALYSIS_MODES.index(default_mode),
            help="应用性能模式会识别 CPU、内存、QPS 等性能语义；通用时序模式只识别时间戳和数值指标，适合温度、压力、质量测量等通用采样记录。",
        )
        group_label = st.text_input(
            "分组名称",
            value=config_analysis_text(imported_config, "group_label", "分组" if analysis_mode == GENERIC_MODE else "场景"),
            help="用于描述 Excel 中每个数据 sheet 的含义，例如场景、设备、工况、批次或实验组。",
        )

    page_title = "通用时序分析" if analysis_mode == GENERIC_MODE else "应用资源消耗分析"
    st.title(page_title)
    if analysis_mode == GENERIC_MODE:
        st.caption(f"当前模式：通用时序；每个数据 sheet 作为一个{group_label}分组。")
    use_sample = not uploaded_files
    sample_file = GENERIC_SAMPLE_FILE if analysis_mode == GENERIC_MODE else SAMPLE_FILE
    if use_sample:
        ensure_sample_file(sample_file)
        st.caption(f"当前使用示例数据：{sample_file}")
    else:
        st.caption(f"已上传 {len(uploaded_files)} 个 Excel 文件。")
    st.caption(f"读取规则：第一个 sheet 为元信息，其余 sheet 名作为{group_label}名。")

    with st.expander("自定义字段映射"):
        st.caption("多个别名用英文逗号分隔。系统会先匹配这里配置的字段名，再使用内置规则自动识别。")
        field_aliases = {
            field: parse_aliases(
                st.text_input(
                    label,
                    value=",".join(config_field_aliases(imported_config, field)),
                    placeholder="例如：字段A,字段B",
                    help=f"如果采集工具导出的 {label} 表头无法被自动识别，可以在这里填写额外别名，多个别名用英文逗号分隔。",
                )
            )
            for field, (label, _) in MAPPING_FIELDS.items()
        }

    slope_threshold = st.number_input(
        "内存疑似泄漏斜率阈值(MB/分钟)",
        min_value=0.0,
        value=config_analysis_value(imported_config, "memory_leak_slope_threshold", 2.0),
        step=0.5,
        help="性能模式用于内存泄漏检测；通用时序模式仅保存在导出配置中，不参与通用报告判断。",
    )

    st.header("稳定区间")
    warmup_minutes = st.number_input(
        "排除每个分组前 N 分钟",
        min_value=0.0,
        value=config_analysis_value(imported_config, "warmup_minutes", 0.0),
        step=0.5,
        help="用于排除启动预热、采集准备等早期尖峰。裁剪会按数据源 + 分组分别计算，不修改原始 Excel。",
    )

    if use_sample:
        files = (("示例数据", None),)
    else:
        files = tuple((file.name, file.getvalue()) for file in uploaded_files)

    # 加载 Excel 后先得到完整原始采样数据，再按稳定区间做分析视图。
    system_info, raw_data = load_workbooks(files, field_aliases, analysis_mode)
    timestamp_summary, timestamp_failures = load_timestamp_diagnostics(files, tuple(sorted(field_aliases.items())), analysis_mode)
    non_numeric_columns = load_non_numeric_column_summary(files, tuple(sorted(field_aliases.items())), analysis_mode)
    data = apply_stable_window(raw_data, warmup_minutes)
    render_timestamp_diagnostics(timestamp_summary, timestamp_failures, raw_data)
    if data.empty:
        st.warning("未读取到场景数据。请确认第一个 sheet 为系统信息，其余 sheet 分别为轻载、重载等场景采样数据。")
        render_system_info(system_info)
        return

    sources = list(data["source"].dropna().unique())
    scenes = list(data["scene"].dropna().unique())
    # 指标发现发生在数据加载之后：性能模式核心指标优先；通用模式中所有数值列都是动态指标。
    metrics = discover_metrics(data)
    render_config_validation(imported_config, metrics)
    with st.sidebar:
        st.header("阈值")
        st.caption("核心指标使用内置默认阈值；动态扩展指标默认使用当前数据 P95。可导入 JSON 配置覆盖阈值和方向。")
        thresholds = {}
        threshold_bounds = {}
        configured_metrics = []
        metric_config_count = sum(1 for metric in metrics if metric_config_entry(imported_config, metric))
        with st.expander("阈值配置", expanded=not imported_config):
            threshold_display = st.radio(
                "显示方式",
                ["配置命中指标", "全部指标"],
                index=0 if imported_config and metric_config_count else 1,
                horizontal=True,
                help="导入配置后可以只显示配置文件命中的指标；未显示的指标仍会使用导入值或自动默认值参与分析。",
            )
            if imported_config:
                st.caption(f"当前数据识别到 {len(metrics)} 个指标，配置命中 {metric_config_count} 个。")
            for metric in metrics:
                configured_metric = configured_metric_from_import(imported_config, metric)
                threshold_value = threshold_from_import(imported_config, metric)
                lower_bound, upper_bound = metric_bounds_from_import(imported_config, metric)
                show_metric_controls = threshold_display == "全部指标" or bool(metric_config_entry(imported_config, metric))
                if show_metric_controls:
                    direction = st.selectbox(
                        f"{metric.label} 告警方向",
                        ["越高越差", "越低越差"],
                        index=0 if configured_metric.higher_is_worse else 1,
                        key=f"direction_{metric.key}",
                        help="例如 CPU、内存、响应时间通常越高越差；FPS、成功率、QPS 在某些场景下可能越低越差。",
                    )
                    configured_metric = replace(configured_metric, higher_is_worse=direction == "越高越差")
                    threshold_value = st.number_input(
                        configured_metric.threshold_label,
                        min_value=0.0,
                        value=float(threshold_value),
                        step=1.0,
                        key=f"threshold_{metric.key}",
                        help="用于异常点、超阈次数、超阈占比、最大连续超阈和趋势图阈值线。不会修改原始数据。",
                    )
                configured_metrics.append(configured_metric)
                thresholds[metric.key] = threshold_value
                threshold_bounds[metric.key] = (lower_bound, upper_bound)
        metrics = configured_metrics

        st.header("筛选")
        default_sources = [source for source in config_ui_list(imported_config, "filters", "selected_sources", sources) if source in sources] or sources
        default_scenes = [scene for scene in config_ui_list(imported_config, "filters", "selected_groups", scenes) if scene in scenes] or scenes
        available_metrics = [metric for metric in metrics if metric.key in data and not data[metric.key].dropna().empty]
        available_metric_keys = [metric.key for metric in available_metrics]
        default_trend_metrics = [
            metric for metric in config_ui_list(imported_config, "filters", "selected_trend_metrics", available_metric_keys[:3]) if metric in available_metric_keys
        ] or available_metric_keys[:3]
        sync_filter_context(analysis_mode, sources, scenes, available_metric_keys)
        sanitize_multiselect_state("selected_sources", sources, default_sources)
        selected_sources_kwargs = {"default": default_sources} if "selected_sources" not in st.session_state else {}
        selected_sources = st.multiselect(
            "数据源",
            sources,
            key="selected_sources",
            help="选择要参与分析的数据源。多文件上传时，每个文件名就是一个数据源。",
            **selected_sources_kwargs,
        )
        sanitize_multiselect_state("selected_scenes", scenes, default_scenes)
        selected_scenes_kwargs = {"default": default_scenes} if "selected_scenes" not in st.session_state else {}
        selected_scenes = st.multiselect(
            group_label,
            scenes,
            key="selected_scenes",
            help=f"选择要参与分析的{group_label}。名称来自 Excel 的 sheet 名。",
            **selected_scenes_kwargs,
        )
        sanitize_multiselect_state("selected_trend_metrics", available_metric_keys, default_trend_metrics)
        selected_metrics_kwargs = {"default": default_trend_metrics} if "selected_trend_metrics" not in st.session_state else {}
        selected_metrics = st.multiselect(
            "趋势指标",
            available_metric_keys,
            key="selected_trend_metrics",
            format_func=lambda key: metric_by_key(metrics, key).label,
            help="选择趋势页要绘制的指标。这里不影响概览、报告和其他统计表。",
            **selected_metrics_kwargs,
        )

        current_config = build_settings_config(
            field_aliases,
            float(slope_threshold),
            float(warmup_minutes),
            metrics,
            thresholds,
            threshold_bounds,
            analysis_mode,
            group_label,
            build_ui_settings(),
        )
        st.download_button(
            "导出当前分析配置",
            config_to_json_bytes(current_config),
            file_name="perf_analyzer_config.json",
            mime="application/json",
            help="导出当前字段别名、分析参数、阈值、告警方向、筛选条件和图表/决策配置。下次可直接导入复用。",
        )
        template_config = build_config_template(
            field_aliases,
            float(slope_threshold),
            float(warmup_minutes),
            metrics,
            thresholds,
            threshold_bounds,
            analysis_mode,
            group_label,
            build_ui_settings(),
        )
        st.download_button(
            "下载配置模板 JSON",
            config_to_json_bytes(template_config),
            file_name="perf_analyzer_config_template.json",
            mime="application/json",
            help="生成一份带说明的可编辑模板，适合保存后手工调整字段、阈值、单位和图表默认项。",
        )

    filtered_data = data[data["source"].isin(selected_sources) & data["scene"].isin(selected_scenes)].copy()
    if filtered_data.empty:
        st.warning("当前筛选条件下没有数据。")
        return

    with st.sidebar:
        st.header("批量导出")
        batch_export_mode = st.radio(
            "图表 HTML 模式",
            ["轻量模式（共享Plotly）", "完整离线模式"],
            horizontal=False,
            help="轻量模式在 ZIP 中只放一份 Plotly JS，体积更小；完整离线模式每个 HTML 都可单独拎出来打开，但 ZIP 更大。",
        )
        with st.expander("导出范围", expanded=False):
            export_trend = st.checkbox("趋势图", value=True, key="batch_export_trend")
            export_distribution = st.checkbox("分布图", value=True, key="batch_export_distribution")
            export_alert_timeline = st.checkbox("异常时间轴", value=True, key="batch_export_alert_timeline")
            export_sampling_interval = st.checkbox("采样间隔图", value=True, key="batch_export_sampling_interval")
            max_distribution_metrics = st.number_input(
                "分布图最多指标数",
                min_value=1,
                max_value=50,
                value=5,
                step=1,
                key="batch_export_max_distribution_metrics",
                disabled=not export_distribution,
                help="分布图按当前指标顺序导出前 N 个有效指标，避免 ZIP 过大。",
            )
        st.download_button(
            "下载图表与表格 ZIP",
            build_batch_export_zip(
                filtered_data,
                selected_scenes,
                selected_metrics,
                thresholds,
                threshold_bounds,
                metrics,
                analysis_mode,
                group_label,
                batch_export_mode,
                {
                    "trend": export_trend,
                    "distribution": export_distribution,
                    "alert_timeline": export_alert_timeline,
                    "sampling_interval": export_sampling_interval,
                    "max_distribution_metrics": int(max_distribution_metrics),
                },
            ),
            file_name=f"perf_analyzer_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
            mime="application/zip",
            help="导出当前筛选条件下的核心图表 HTML、摘要表、异常表、异常段和采样间隔表。",
        )

    config_table = pd.DataFrame()
    config_notes: list[str] = []

    if analysis_mode == GENERIC_MODE:
        tabs = st.tabs(["概览", "趋势", "对比", "基准增长", "版本对比", "分布", "异常", "数据质量", "报告", "元信息", "原始数据"])
        with tabs[0]:
            render_overview(filtered_data, thresholds, metrics, threshold_bounds)
        with tabs[1]:
            render_trend(filtered_data, selected_scenes, selected_metrics, thresholds, threshold_bounds, metrics)
        with tabs[2]:
            render_comparison(filtered_data, selected_scenes, metrics)
        with tabs[3]:
            render_baseline_growth(filtered_data, selected_scenes, metrics)
        with tabs[4]:
            render_version_compare(filtered_data, selected_scenes, metrics)
        with tabs[5]:
            render_distribution(filtered_data, selected_scenes, metrics)
        with tabs[6]:
            render_alerts(filtered_data, selected_scenes, thresholds, metrics, threshold_bounds)
        with tabs[7]:
            render_data_quality(filtered_data, metrics, non_numeric_columns)
        with tabs[8]:
            render_generic_report(filtered_data, thresholds, metrics, group_label, threshold_bounds)
        with tabs[9]:
            selected_system = system_info[system_info["数据源"].isin(selected_sources)] if "数据源" in system_info else system_info
            render_system_info(selected_system)
        with tabs[10]:
            filtered = filtered_data.copy()
            render_sampling_interval(filtered, selected_scenes)
            st.dataframe(filtered, use_container_width=True, hide_index=True)
            st.download_button(
                "下载当前筛选数据 CSV",
                filtered.to_csv(index=False).encode("utf-8-sig"),
                file_name="timeseries_filtered.csv",
                mime="text/csv",
            )
    else:
        tabs = st.tabs(["概览", "趋势", "对比", "配置建议", "基准增长", "泄漏检测", "版本对比", "效率", "决策", "分布", "异常", "数据质量", "报告", "系统信息", "原始数据"])
        with tabs[0]:
            render_overview(filtered_data, thresholds, metrics, threshold_bounds)
        with tabs[1]:
            render_trend(filtered_data, selected_scenes, selected_metrics, thresholds, threshold_bounds, metrics)
        with tabs[2]:
            render_comparison(filtered_data, selected_scenes, metrics)
        with tabs[3]:
            config_table, config_notes = render_configuration_recommendation(filtered_data, slope_threshold)
        with tabs[4]:
            render_baseline_growth(filtered_data, selected_scenes, metrics)
        with tabs[5]:
            render_leak_detection(filtered_data, selected_scenes, slope_threshold, metrics)
        with tabs[6]:
            render_version_compare(filtered_data, selected_scenes, metrics)
        with tabs[7]:
            render_efficiency(filtered_data, selected_scenes)
        with tabs[8]:
            render_decision(filtered_data, selected_scenes, thresholds, metrics, slope_threshold, threshold_bounds)
        with tabs[9]:
            render_distribution(filtered_data, selected_scenes, metrics)
        with tabs[10]:
            render_alerts(filtered_data, selected_scenes, thresholds, metrics, threshold_bounds)
        with tabs[11]:
            render_data_quality(filtered_data, metrics, non_numeric_columns)
        with tabs[12]:
            if config_table.empty:
                config_table, config_notes = configuration_recommendation(
                    filtered_data,
                    test_cpu_cores=8,
                    target_cpu_utilization=70.0,
                    minimum_cpu_cores=2,
                    system_reserved_memory_gb=2.0,
                    minimum_memory_gb=4,
                    minimum_free_disk_gb=10,
                    recommendation_factor=1.5,
                    slope_threshold=slope_threshold,
                )
            render_report(filtered_data, thresholds, slope_threshold, metrics, threshold_bounds, config_table, config_notes)
        with tabs[13]:
            selected_system = system_info[system_info["数据源"].isin(selected_sources)] if "数据源" in system_info else system_info
            render_system_info(selected_system)
        with tabs[14]:
            filtered = filtered_data.copy()
            render_sampling_interval(filtered, selected_scenes)
            st.dataframe(filtered, use_container_width=True, hide_index=True)
            st.download_button(
                "下载当前筛选数据 CSV",
                filtered.to_csv(index=False).encode("utf-8-sig"),
                file_name="resource_metrics_filtered.csv",
                mime="text/csv",
            )


if __name__ == "__main__":
    main()
