from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from .config import validate_config
from .export import dataframe_to_csv_bytes
from .models import Metric
from .quality import metric_quality_summary, sampling_gap_issue_summary, timestamp_quality_summary
from .views_sampling import build_sampling_interval_tables


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
