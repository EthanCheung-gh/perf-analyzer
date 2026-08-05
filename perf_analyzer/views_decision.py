from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from .analysis import (
    capacity_estimation,
    compute_decision_bundle,
    release_gate_analysis,
    resource_efficiency_analysis,
    workload_efficiency_bucket_summary,
    workload_efficiency_buckets,
)
from .config import config_ui_bool, config_ui_choice, config_ui_float, config_ui_int, config_ui_value
from .models import Metric
from .ui_helpers import render_plotly_chart, safe_option_index, sanitize_select_state


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

    st.markdown("**分钟级归一化（瞬时成本）**")
    buckets = workload_efficiency_buckets(filtered)
    if buckets.empty:
        st.info("缺少吞吐字段（QPS/TPS/任务数/请求数），无法做分钟级归一化。")
        return
    with st.expander("口径说明", expanded=False):
        st.write("- 场景级平均成本会掩盖负载波动：瞬时成本按分钟分桶计算，能看出高负载时段单位成本是否恶化。")
        st.write("- 瞬时成本 P95 明显高于中位值时，说明部分时段资源效率较差。")
    bucket_summary = workload_efficiency_bucket_summary(buckets)
    st.dataframe(bucket_summary, use_container_width=True, hide_index=True)

    bucket_chart_data = buckets.copy()
    bucket_chart_data["场景标识"] = bucket_chart_data["数据源"].astype(str) + " / " + bucket_chart_data["场景"].astype(str)
    bucket_cost_options = [column for column in ["CPU成本", "内存/并发(MB)"] if column in bucket_chart_data and bucket_chart_data[column].notna().any()]
    if bucket_cost_options:
        sanitize_select_state("efficiency_bucket_cost", bucket_cost_options)
        bucket_cost_default = config_ui_choice(imported_config, "efficiency", "bucket_cost", bucket_cost_options, bucket_cost_options[0])
        bucket_cost = st.selectbox(
            "瞬时成本指标",
            bucket_cost_options,
            index=safe_option_index(bucket_cost_options, bucket_cost_default),
            key="efficiency_bucket_cost",
            help="CPU成本 = 分桶平均CPU / 分桶平均吞吐；内存/并发 = 分桶内存峰值 / 分桶平均并发。",
        )
        cost_fig = px.line(
            bucket_chart_data.dropna(subset=[bucket_cost]),
            x="时间桶",
            y=bucket_cost,
            color="场景标识",
            markers=True,
            title=f"{bucket_cost} 时间线",
        )
        cost_fig.update_layout(height=420, margin=dict(l=20, r=20, t=50, b=20))
        render_plotly_chart(cost_fig, f"分钟级归一化_{bucket_cost}")


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

    bundle = compute_decision_bundle(filtered, thresholds, metrics, slope_threshold, threshold_bounds)
    decisions = bundle.decisions
    st.markdown("**场景风险评级**")
    if decisions.empty:
        st.info("没有可用于风险评级的数据。")
        return
    st.dataframe(decisions, use_container_width=True, hide_index=True)

    matrix = bundle.matrix
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

    radar_data = bundle.radar
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
    stability = bundle.stability
    st.dataframe(stability, use_container_width=True, hide_index=True)

    st.markdown("**瓶颈提示**")
    bottlenecks = bundle.bottlenecks
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
