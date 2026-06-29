from __future__ import annotations

import pandas as pd
import streamlit as st

from .alerts import format_value, metric_alert_mask
from .analysis import alert_continuity_summary, summarize
from .models import Metric


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
