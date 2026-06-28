from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from .analysis import linear_slope_per_minute
from .config import config_ui_choice
from .metrics import metric_by_key
from .models import Metric
from .stats import coefficient_of_variation, iqr, percentile, percentile_95
from .ui_helpers import render_plotly_chart, safe_option_index, sanitize_select_state, with_display_label


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
