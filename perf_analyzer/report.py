from __future__ import annotations

import pandas as pd

from .alerts import alert_segments, format_value, metric_alert_mask
from .analysis import (
    alert_continuity_summary,
    bottleneck_hints,
    leak_analysis,
    release_gate_analysis,
    resource_efficiency_analysis,
    scene_decision_analysis,
    stability_score_analysis,
    summarize,
    trend_analysis,
)
from .models import Metric


def _count_alerts(
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


def build_conclusions(
    data: pd.DataFrame,
    thresholds: dict[str, float],
    slope_threshold: float,
    metrics: list[Metric],
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> list[str]:
    conclusions = []
    if data.empty:
        return ["未读取到可分析的场景数据。"]
    alerts = _count_alerts(data, thresholds, metrics, threshold_bounds)
    if alerts:
        conclusions.append(f"当前阈值下共有 {alerts} 个超阈采样点，建议优先查看“异常”页定位时间和场景。")
        alert_summary = alert_continuity_summary(data, thresholds, metrics, threshold_bounds)
        if not alert_summary.empty:
            top_ratio = alert_summary.iloc[0]
            top_duration = alert_summary.sort_values("最大连续超阈(分钟)", ascending=False).iloc[0]
            conclusions.append(
                f"超阈占比最高的是 {top_ratio['数据源']} / {top_ratio['场景']} 的 {top_ratio['指标']}，"
                f"占比 {top_ratio['超阈占比(%)']:.2f}%。"
            )
            conclusions.append(
                f"最长连续超阈出现在 {top_duration['数据源']} / {top_duration['场景']} 的 {top_duration['指标']}，"
                f"持续 {top_duration['最大连续超阈']}。"
            )
    else:
        conclusions.append("当前阈值下未发现超阈采样点。")

    for metric in metrics:
        if data[metric.key].dropna().empty:
            continue
        idx = data[metric.key].idxmax()
        row = data.loc[idx]
        conclusions.append(
            f"{metric.label}峰值出现在 {row['source']} / {row['scene']}，峰值为 {format_value(row[metric.key], metric.unit)}。"
        )

    leaks = leak_analysis(data, slope_threshold)
    risky = leaks[leaks["判断"] == "疑似泄漏"]
    if not risky.empty:
        names = "、".join(f"{row['数据源']} / {row['场景']}" for _, row in risky.iterrows())
        conclusions.append(f"内存趋势检测发现疑似泄漏场景：{names}。")
    else:
        conclusions.append("内存趋势检测未发现明显泄漏场景。")
    return conclusions


def build_generic_conclusions(
    data: pd.DataFrame,
    thresholds: dict[str, float],
    metrics: list[Metric],
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> list[str]:
    conclusions = []
    if data.empty:
        return ["未读取到可分析的时序数据。"]
    alerts = _count_alerts(data, thresholds, metrics, threshold_bounds)
    if alerts:
        conclusions.append(f"当前阈值下共有 {alerts} 个超阈采样点，建议查看“异常”页定位时间和分组。")
        alert_summary = alert_continuity_summary(data, thresholds, metrics, threshold_bounds)
        if not alert_summary.empty:
            top_ratio = alert_summary.iloc[0]
            conclusions.append(
                f"超阈占比最高的是 {top_ratio['数据源']} / {top_ratio['场景']} 的 {top_ratio['指标']}，"
                f"占比 {top_ratio['超阈占比(%)']:.2f}%。"
            )
    else:
        conclusions.append("当前阈值下未发现超阈采样点。")

    for metric in metrics:
        if metric.key not in data or data[metric.key].dropna().empty:
            continue
        idx = data[metric.key].idxmax()
        row = data.loc[idx]
        conclusions.append(
            f"{metric.label}峰值出现在 {row['source']} / {row['scene']}，峰值为 {format_value(row[metric.key], metric.unit)}。"
        )
    return conclusions


def dataframe_to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    display = df.copy()
    for column in display.columns:
        if pd.api.types.is_float_dtype(display[column]):
            display[column] = display[column].map(lambda value: "" if pd.isna(value) else f"{value:.2f}")
        else:
            display[column] = display[column].map(lambda value: "" if pd.isna(value) else str(value))
    header = "| " + " | ".join(display.columns) + " |"
    separator = "| " + " | ".join("---" for _ in display.columns) + " |"
    rows = ["| " + " | ".join(row) + " |" for row in display.astype(str).to_numpy()]
    return "\n".join([header, separator, *rows])


def build_report_markdown(
    data: pd.DataFrame,
    thresholds: dict[str, float],
    slope_threshold: float,
    metrics: list[Metric],
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
    config_table: pd.DataFrame | None = None,
    config_notes: list[str] | None = None,
) -> str:
    summary = summarize(data, thresholds, metrics, threshold_bounds)
    leaks = leak_analysis(data, slope_threshold)
    trends = trend_analysis(data, metrics)
    alert_summary = alert_continuity_summary(data, thresholds, metrics, threshold_bounds)
    segments = alert_segments(data, thresholds, metrics, threshold_bounds)
    efficiency = resource_efficiency_analysis(data)
    decisions = scene_decision_analysis(data, thresholds, metrics, slope_threshold, threshold_bounds)
    gate_status, gate_rules = release_gate_analysis(
        decisions,
        max_allowed_level="中风险",
        fail_on_leak=True,
        fail_on_any_alert=False,
        fail_on_errors=False,
    )
    stability = stability_score_analysis(decisions)
    bottlenecks = bottleneck_hints(data, thresholds, metrics)
    conclusions = build_conclusions(data, thresholds, slope_threshold, metrics, threshold_bounds)
    lines = [
        "# 应用资源消耗分析报告",
        "",
        "## 测试结论",
        "",
        *[f"- {item}" for item in conclusions],
        f"- 发布门禁默认判断：{gate_status}。",
        "",
        "## 决策分析",
        "",
        dataframe_to_markdown(decisions) if not decisions.empty else "无场景风险评级数据。",
        "",
        "## 发布门禁",
        "",
        dataframe_to_markdown(gate_rules) if not gate_rules.empty else "无发布门禁数据。",
        "",
        "## 稳定性评分",
        "",
        dataframe_to_markdown(stability) if not stability.empty else "无稳定性评分数据。",
        "",
        "## 瓶颈提示",
        "",
        dataframe_to_markdown(bottlenecks) if not bottlenecks.empty else "无瓶颈提示数据。",
        "",
        "## 汇总数据",
        "",
        dataframe_to_markdown(summary) if not summary.empty else "无汇总数据。",
        "",
        "## 告警持续性",
        "",
        dataframe_to_markdown(alert_summary.drop(columns=["最大连续超阈(分钟)"], errors="ignore")) if not alert_summary.empty else "当前阈值下无超阈持续性数据。",
        "",
        "## 异常段",
        "",
        dataframe_to_markdown(segments.drop(columns=["指标key", "持续时长(分钟)"], errors="ignore")) if not segments.empty else "当前阈值下无异常段数据。",
        "",
        "## 内存趋势检测",
        "",
        dataframe_to_markdown(leaks) if not leaks.empty else "无内存趋势数据。",
        "",
        "## 全指标趋势斜率",
        "",
        dataframe_to_markdown(trends) if not trends.empty else "无趋势斜率数据。",
        "",
        "## 资源效率",
        "",
        dataframe_to_markdown(efficiency) if not efficiency.empty else "无资源效率数据。",
        "",
        "## 配置建议",
        "",
        dataframe_to_markdown(config_table) if config_table is not None and not config_table.empty else "未生成配置建议。",
        "",
        *[f"- {item}" for item in config_notes or []],
        "",
        "## 分析口径",
        "",
        "- 均值：场景内全部采样点平均值",
        "- 峰值：场景内最大采样值",
        "- P90 / P95 / P99：对应分位值，用于观察高水位和尾部风险",
        "- 超阈次数：按单阈值方向，或按 lower_threshold / upper_threshold 正常区间判断的异常采样点数量",
        "- 超阈占比：超阈采样点数量 / 有效采样点数量",
        "- 最大连续超阈：同一指标连续处于超阈状态的最长时间",
        "- 标准差 / IQR / 变异系数：用于观察资源波动性",
        "- 趋势斜率：按时间对指标做线性回归，单位为指标值/分钟",
        "- 资源效率：把 CPU、内存、IO、网络、磁盘等资源消耗按吞吐或并发归一化",
        "- 风险评分：综合超阈、连续超阈、泄漏、失败率、响应时间、FPS 等规则扣分",
        "- 发布门禁：按风险等级、泄漏、超阈、失败请求等规则判断是否通过",
        "- 内存斜率：按时间对内存占用做线性回归，单位 MB/分钟",
    ]
    return "\n".join(lines)


def build_generic_report_markdown(
    data: pd.DataFrame,
    thresholds: dict[str, float],
    metrics: list[Metric],
    group_label: str,
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> str:
    summary = summarize(data, thresholds, metrics, threshold_bounds)
    trends = trend_analysis(data, metrics)
    alert_summary = alert_continuity_summary(data, thresholds, metrics, threshold_bounds)
    segments = alert_segments(data, thresholds, metrics, threshold_bounds)
    conclusions = build_generic_conclusions(data, thresholds, metrics, threshold_bounds)
    lines = [
        "# 通用时序分析报告",
        "",
        "## 分析结论",
        "",
        *[f"- {item}" for item in conclusions],
        "",
        "## 汇总数据",
        "",
        dataframe_to_markdown(summary) if not summary.empty else "无汇总数据。",
        "",
        "## 告警持续性",
        "",
        dataframe_to_markdown(alert_summary.drop(columns=["最大连续超阈(分钟)"], errors="ignore")) if not alert_summary.empty else "当前阈值下无超阈持续性数据。",
        "",
        "## 异常段",
        "",
        dataframe_to_markdown(segments.drop(columns=["指标key", "持续时长(分钟)"], errors="ignore")) if not segments.empty else "当前阈值下无异常段数据。",
        "",
        "## 全指标趋势斜率",
        "",
        dataframe_to_markdown(trends) if not trends.empty else "无趋势斜率数据。",
        "",
        "## 分析口径",
        "",
        f"- {group_label}：由 Excel sheet 名提供。",
        "- 均值 / 峰值 / P90 / P95 / P99：用于观察整体水平、高水位和尾部风险。",
        "- 超阈占比：按单阈值方向，或按 lower_threshold / upper_threshold 正常区间判断的异常采样点数量 / 有效采样点数量。",
        "- 最大连续超阈：同一指标连续处于超阈状态的最长时间。",
        "- 趋势斜率：按时间对指标做线性回归，单位为指标值/分钟。",
    ]
    return "\n".join(lines)


def build_report_html(markdown_text: str) -> str:
    body = markdown_text
    replacements = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
    }
    for old, new in replacements.items():
        body = body.replace(old, new)
    body = body.replace("\n", "<br>\n")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>应用资源消耗分析报告</title>
  <style>
    body {{ font-family: Arial, "Microsoft YaHei", sans-serif; line-height: 1.6; margin: 40px; color: #222; }}
    code {{ background: #f3f4f6; padding: 2px 4px; }}
  </style>
</head>
<body>{body}</body>
</html>
"""
