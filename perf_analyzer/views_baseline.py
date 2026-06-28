from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from .analysis import leak_analysis, metric_stats, trend_analysis, version_regression_heatmap_data
from .config import config_ui_choice, config_ui_float
from .metrics import metric_by_key
from .models import Metric
from .ui_helpers import render_plotly_chart, safe_option_index, sanitize_select_state, with_display_label


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
