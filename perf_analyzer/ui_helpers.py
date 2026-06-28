from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .charts import apply_chart_export_theme, figure_to_html_bytes
from .utils import safe_filename


def safe_option_index(options: list[str], preferred: str | None, default: int = 0) -> int:
    if preferred in options:
        return options.index(preferred)
    return default if options else 0


def sanitize_select_state(key: str, options: list[str]) -> None:
    if key in st.session_state and st.session_state[key] not in options:
        del st.session_state[key]


def sanitize_multiselect_state(key: str, options: list[str], default: list[str] | None = None) -> None:
    if key not in st.session_state:
        return
    selected = st.session_state[key]
    if not isinstance(selected, list):
        del st.session_state[key]
        return
    valid = [item for item in selected if item in options]
    fallback = [item for item in (default or []) if item in options]
    if not valid and fallback:
        st.session_state[key] = fallback
        return
    if valid != selected:
        st.session_state[key] = valid


def reset_state_keys(keys: list[str]) -> None:
    for key in keys:
        if key in st.session_state:
            del st.session_state[key]


def sync_filter_context(
    analysis_mode: str,
    sources: list[str],
    scenes: list[str],
    metric_keys: list[str],
) -> None:
    signature = (analysis_mode, tuple(sources), tuple(scenes), tuple(metric_keys))
    if st.session_state.get("filter_context_signature") == signature:
        return
    reset_state_keys(
        [
            "selected_sources",
            "selected_scenes",
            "selected_trend_metrics",
            "distribution_metric",
            "control_chart_metric",
            "control_chart_scene",
            "efficiency_metric",
            "efficiency_scatter_y",
            "sampling_interval_scene",
            "version_compare_metric",
            "version_compare_baseline_source",
            "baseline_growth_baseline",
            "baseline_growth_metric",
        ]
    )
    st.session_state["filter_context_signature"] = signature


def render_plotly_chart(fig: go.Figure, filename: str, *, height: int | None = None) -> None:
    if height is not None:
        fig.update_layout(height=height)
    apply_chart_export_theme(fig)
    st.plotly_chart(fig, use_container_width=True, theme=None)
    st.download_button(
        "下载图表 HTML",
        figure_to_html_bytes(fig),
        file_name=f"{safe_filename(filename)}.html",
        mime="text/html",
        key=f"download_chart_{safe_filename(filename)}",
        help="导出当前交互图表，适合离线查看或放入报告附件。",
    )


def render_system_info(system_info: pd.DataFrame) -> None:
    st.subheader("系统信息")
    if system_info.empty:
        st.info("未读取到系统信息 sheet。")
        return
    st.dataframe(system_info, use_container_width=True, hide_index=True)


def with_display_label(data: pd.DataFrame) -> pd.DataFrame:
    result = data.copy()
    if result["source"].nunique() > 1:
        result["display_scene"] = result["source"].astype(str) + " / " + result["scene"].astype(str)
    else:
        result["display_scene"] = result["scene"].astype(str)
    return result
