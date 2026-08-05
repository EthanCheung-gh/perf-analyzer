from __future__ import annotations

from dataclasses import dataclass, fields, replace

import numpy as np


def _optional_float(value: object) -> float | None:
    """解析配置里的数字字段；无法解析时返回 None。"""
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


@dataclass(frozen=True)
class RiskRules:
    """决策分析（风险评分）使用的可配置阈值，全部字段都有默认值。

    数值口径与历史实现保持一致，集中在这里后可通过 JSON 配置覆盖。
    """

    # 超阈占比(%)：场景内超阈采样点比例达到该值开始加分
    alert_ratio_warning: float = 5.0
    alert_ratio_critical: float = 20.0
    # 最长连续超阈(分钟)
    alert_minutes_warning: float = 1.0
    alert_minutes_critical: float = 5.0
    # 失败率(%)
    failure_rate_warning: float = 0.1
    failure_rate_critical: float = 1.0
    # 每千请求错误数
    error_per_thousand_warning: float = 1.0
    error_per_thousand_critical: float = 10.0
    # 响应时间 P95(ms)
    response_ms_warning: float = 500.0
    response_ms_critical: float = 1000.0
    # FPS P95
    fps_warning: float = 45.0
    fps_critical: float = 30.0
    # 内存趋势加分
    leak_score: float = 3.0
    minor_leak_score: float = 1.0


def default_risk_rules() -> RiskRules:
    return RiskRules()


def risk_rules_from_config(config: dict) -> RiskRules:
    """从导入的分析配置里读取 analysis.risk_rules，缺失字段使用默认值。"""
    rules = default_risk_rules()
    if not config:
        return rules
    analysis = config.get("analysis", {})
    entry = analysis.get("risk_rules", {}) if isinstance(analysis, dict) else {}
    if not isinstance(entry, dict):
        return rules
    values = {field.name: _optional_float(entry.get(field.name)) for field in fields(rules)}
    overrides = {key: value for key, value in values.items() if value is not None}
    return replace(rules, **overrides) if overrides else rules


def risk_rules_to_dict(rules: RiskRules) -> dict[str, float]:
    return {field.name: getattr(rules, field.name) for field in fields(rules)}


# 瓶颈提示使用的展示级常量（不做 UI 配置，收敛在这里便于维护口径）
BOTTLENECK_CPU_FACTOR = 0.9
BOTTLENECK_MEMORY_FACTOR = 0.9
BOTTLENECK_IO_FACTOR = 0.9
BOTTLENECK_RESPONSE_MS = 500.0
BOTTLENECK_NETWORK_KBPS = 1024.0

# 风险雷达图使用的展示级常量
RADAR_RESPONSE_MS = 1000.0
RADAR_FAILURE_RATE = 1.0
RADAR_FPS_TARGET = 60.0
RADAR_FPS_SLACK = 30.0
