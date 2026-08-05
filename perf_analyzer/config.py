from __future__ import annotations

import json
from dataclasses import replace

import numpy as np

from .constants import (
    CONFIG_ANALYSIS_KEYS,
    CONFIG_METRIC_KEYS,
    CONFIG_TOP_LEVEL_KEYS,
    CONFIG_UI_SECTIONS,
    GENERIC_MODE,
    PERFORMANCE_MODE,
)
from .models import Metric
from .rules import RiskRules, default_risk_rules, risk_rules_to_dict
from .utils import dynamic_metric_label, parse_aliases


def optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def normalize_config_direction(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("higher", "high", "up", "越高越差", "高", "true"):
        return True
    if text in ("lower", "low", "down", "越低越差", "低", "false"):
        return False
    return default


def validate_config(config: dict, metrics: list[Metric] | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not config:
        return errors, warnings
    if not isinstance(config, dict):
        return ["配置根节点必须是 JSON 对象。"], warnings

    unknown_top = sorted(set(config) - CONFIG_TOP_LEVEL_KEYS)
    if unknown_top:
        warnings.append(f"未知顶层字段将被忽略：{', '.join(unknown_top)}。")

    fields = config.get("fields", {})
    if fields and not isinstance(fields, dict):
        errors.append("fields 必须是对象，值可以是字符串或字符串数组。")
    elif isinstance(fields, dict):
        for field, aliases in fields.items():
            if not isinstance(aliases, (str, list, tuple)):
                warnings.append(f"fields.{field} 不是字符串或数组，已忽略。")

    analysis = config.get("analysis", {})
    if analysis and not isinstance(analysis, dict):
        errors.append("analysis 必须是对象。")
    elif isinstance(analysis, dict):
        unknown_analysis = sorted(set(analysis) - CONFIG_ANALYSIS_KEYS)
        if unknown_analysis:
            warnings.append(f"analysis 中未知字段将被忽略：{', '.join(unknown_analysis)}。")
        mode = str(config.get("mode", analysis.get("mode", ""))).strip().lower()
        if mode and mode not in ("performance", "generic_timeseries", "generic", "应用性能", "通用时序"):
            warnings.append("mode 未识别，将按应用性能模式处理。")
        for key in ("memory_leak_slope_threshold", "warmup_minutes"):
            if key in analysis and optional_float(analysis.get(key)) is None:
                warnings.append(f"analysis.{key} 不是数字，将使用默认值。")
        risk_rules = analysis.get("risk_rules")
        if risk_rules is not None and not isinstance(risk_rules, dict):
            warnings.append("analysis.risk_rules 必须是对象，已忽略，使用默认规则。")
        elif isinstance(risk_rules, dict):
            known_rule_fields = {field.name for field in RiskRules.__dataclass_fields__.values()}
            unknown_rule_fields = sorted(set(risk_rules) - known_rule_fields)
            if unknown_rule_fields:
                warnings.append(f"analysis.risk_rules 中未知字段将被忽略：{', '.join(unknown_rule_fields)}。")
            for key in sorted(set(risk_rules) & known_rule_fields):
                if optional_float(risk_rules.get(key)) is None:
                    warnings.append(f"analysis.risk_rules.{key} 不是数字，将使用默认值。")

    ui = config.get("ui", {})
    if ui and not isinstance(ui, dict):
        warnings.append("ui 必须是对象，已忽略。")
    elif isinstance(ui, dict):
        unknown_ui = sorted(set(ui) - CONFIG_UI_SECTIONS)
        if unknown_ui:
            warnings.append(f"ui 中未知配置段将被忽略：{', '.join(unknown_ui)}。")

    metric_configs = config.get("metrics", {})
    if metric_configs and not isinstance(metric_configs, dict):
        errors.append("metrics 必须是对象。")
        return errors, warnings
    if not isinstance(metric_configs, dict):
        return errors, warnings

    known_metric_keys: set[str] = set()
    if metrics is not None:
        for metric in metrics:
            known_metric_keys.update({metric.key, metric.label})
            if metric.key.startswith("extra::"):
                known_metric_keys.add(dynamic_metric_label(metric.key))

    for metric_name, entry in metric_configs.items():
        if not isinstance(entry, dict):
            warnings.append(f"metrics.{metric_name} 必须是对象，已忽略。")
            continue
        unknown_metric_keys = sorted(set(entry) - CONFIG_METRIC_KEYS)
        if unknown_metric_keys:
            warnings.append(f"metrics.{metric_name} 中未知字段将被忽略：{', '.join(unknown_metric_keys)}。")
        direction = entry.get("direction")
        if direction is not None and normalize_config_direction(direction, True) == normalize_config_direction("__invalid__", True):
            text = str(direction).strip().lower()
            if text not in ("higher", "high", "up", "越高越差", "高", "true", "lower", "low", "down", "越低越差", "低", "false"):
                warnings.append(f"metrics.{metric_name}.direction 未识别，将使用默认方向。")
        for key in ("threshold", "lower_threshold", "upper_threshold", "lower", "upper", "min_threshold", "max_threshold"):
            if key in entry and optional_float(entry.get(key)) is None:
                warnings.append(f"metrics.{metric_name}.{key} 不是数字，已忽略。")
        lower = optional_float(entry.get("lower_threshold", entry.get("lower", entry.get("min_threshold"))))
        upper = optional_float(entry.get("upper_threshold", entry.get("upper", entry.get("max_threshold"))))
        if lower is not None and upper is not None and lower > upper:
            warnings.append(f"metrics.{metric_name} 的 lower_threshold 大于 upper_threshold，页面会自动交换。")
        if metrics is not None and metric_name not in known_metric_keys:
            warnings.append(f"metrics.{metric_name} 当前数据未命中，会被忽略。")
    return errors, warnings


def config_field_aliases(config: dict, field: str) -> tuple[str, ...]:
    fields = config.get("fields", {})
    value = fields.get(field, ())
    if isinstance(value, str):
        return parse_aliases(value)
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def config_analysis_value(config: dict, key: str, default: float) -> float:
    analysis = config.get("analysis", {})
    value = analysis.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def config_analysis_text(config: dict, key: str, default: str) -> str:
    analysis = config.get("analysis", {})
    value = analysis.get(key, default)
    return str(value).strip() if str(value).strip() else default


def config_analysis_mode(config: dict) -> str:
    value = config.get("mode", config.get("analysis", {}).get("mode", PERFORMANCE_MODE))
    return GENERIC_MODE if str(value).strip().lower() in ("generic", "generic_timeseries", "通用时序") else PERFORMANCE_MODE


def config_ui_section(config: dict, section: str) -> dict:
    ui = config.get("ui", {})
    value = ui.get(section, {}) if isinstance(ui, dict) else {}
    return value if isinstance(value, dict) else {}


def config_ui_value(config: dict, section: str, key: str, default: object) -> object:
    return config_ui_section(config, section).get(key, default)


def config_ui_float(config: dict, section: str, key: str, default: float) -> float:
    value = config_ui_value(config, section, key, default)
    parsed = optional_float(value)
    return float(parsed) if parsed is not None else default


def config_ui_int(config: dict, section: str, key: str, default: int) -> int:
    value = config_ui_float(config, section, key, float(default))
    return int(value)


def config_ui_bool(config: dict, section: str, key: str, default: bool) -> bool:
    value = config_ui_value(config, section, key, default)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "y", "是", "启用"):
        return True
    if text in ("false", "0", "no", "n", "否", "关闭"):
        return False
    return default


def config_ui_choice(config: dict, section: str, key: str, options: list[str], default: str) -> str:
    value = str(config_ui_value(config, section, key, default))
    return value if value in options else default


def config_ui_list(config: dict, section: str, key: str, default: list[str]) -> list[str]:
    value = config_ui_value(config, section, key, default)
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return default


def metric_config_entry(config: dict, metric: Metric) -> dict:
    metric_configs = config.get("metrics", {})
    candidates = [metric.key, metric.label]
    if metric.key.startswith("extra::"):
        candidates.append(dynamic_metric_label(metric.key))
    for candidate in candidates:
        value = metric_configs.get(candidate)
        if isinstance(value, dict):
            return value
    return {}


def configured_metric_from_import(config: dict, metric: Metric) -> Metric:
    entry = metric_config_entry(config, metric)
    higher_is_worse = normalize_config_direction(entry.get("direction"), metric.higher_is_worse)
    label = str(entry.get("label", metric.label)).strip() or metric.label
    unit = str(entry.get("unit", metric.unit)).strip()
    threshold_label = str(entry.get("threshold_label", f"{label} 告警阈值")).strip()
    return replace(metric, label=label, unit=unit, threshold_label=threshold_label, higher_is_worse=higher_is_worse)


def threshold_from_import(config: dict, metric: Metric) -> float:
    entry = metric_config_entry(config, metric)
    value = entry.get("threshold", metric.default_threshold)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(metric.default_threshold)


def metric_bounds_from_import(config: dict, metric: Metric) -> tuple[float | None, float | None]:
    entry = metric_config_entry(config, metric)
    lower = optional_float(entry.get("lower_threshold", entry.get("lower", entry.get("min_threshold"))))
    upper = optional_float(entry.get("upper_threshold", entry.get("upper", entry.get("max_threshold"))))
    if lower is not None and upper is not None and lower > upper:
        lower, upper = upper, lower
    return lower, upper


def build_settings_config(
    field_aliases: dict[str, tuple[str, ...]],
    slope_threshold: float,
    warmup_minutes: float,
    metrics: list[Metric],
    thresholds: dict[str, float],
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
    analysis_mode: str = PERFORMANCE_MODE,
    group_label: str = "场景",
    ui_settings: dict | None = None,
    scales: dict[str, float] | None = None,
) -> dict:
    threshold_bounds = threshold_bounds or {}
    metric_settings = {}
    for metric in metrics:
        setting = {
            "label": metric.label,
            "unit": metric.unit,
            "threshold_label": metric.threshold_label,
            "threshold": thresholds.get(metric.key, metric.default_threshold),
            "direction": "higher" if metric.higher_is_worse else "lower",
        }
        scale = (scales or {}).get(metric.key)
        if scale is not None and scale != 1.0:
            setting["scale"] = scale
        lower, upper = threshold_bounds.get(metric.key, (None, None))
        if lower is not None:
            setting["lower_threshold"] = lower
        if upper is not None:
            setting["upper_threshold"] = upper
        metric_settings[metric.key] = setting
    return {
        "version": 1,
        "mode": "generic_timeseries" if analysis_mode == GENERIC_MODE else "performance",
        "fields": {field: list(aliases) for field, aliases in field_aliases.items() if aliases},
        "analysis": {
            "mode": "generic_timeseries" if analysis_mode == GENERIC_MODE else "performance",
            "group_label": group_label,
            "memory_leak_slope_threshold": slope_threshold,
            "warmup_minutes": warmup_minutes,
            "risk_rules": risk_rules_to_dict(default_risk_rules()),
        },
        "metrics": metric_settings,
        "ui": ui_settings or {},
    }


def build_config_template(
    field_aliases: dict[str, tuple[str, ...]],
    slope_threshold: float,
    warmup_minutes: float,
    metrics: list[Metric],
    thresholds: dict[str, float],
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
    analysis_mode: str = PERFORMANCE_MODE,
    group_label: str = "场景",
    ui_settings: dict | None = None,
    scales: dict[str, float] | None = None,
) -> dict:
    template = build_settings_config(
        field_aliases,
        slope_threshold,
        warmup_minutes,
        metrics,
        thresholds,
        threshold_bounds,
        analysis_mode,
        group_label,
        ui_settings,
        scales=scales,
    )
    template["_comment"] = {
        "purpose": "这是一份按当前上传数据生成的可编辑配置模板，保存后可在侧边栏重新导入。",
        "fields": "字段别名映射。key 是系统内部字段，value 是 Excel 中可能出现的表头别名列表。",
        "analysis": "分析模式、分组名称、预热裁剪和内存泄漏斜率阈值。",
        "metrics": "指标展示名、单位、阈值、告警方向和可选上下限。direction 可填 higher 或 lower。",
        "ui": "常用图表控件和筛选条件默认值。",
    }
    template["notes"] = [
        "动态指标也会写入 metrics；如果 Excel 表头变化，可按新的指标 key 或展示名调整配置。",
        "lower_threshold / upper_threshold 用于上下限区间和区间异常；不需要时可删除。",
        "threshold 用于单阈值异常；direction=higher 表示越高越差，direction=lower 表示越低越差。",
    ]
    for metric in metrics:
        entry = template["metrics"].setdefault(metric.key, {})
        entry.setdefault("_comment", f"{metric.label} 的阈值配置；unit 可留空，label 会影响界面展示。")
        lower, upper = (threshold_bounds or {}).get(metric.key, (None, None))
        if lower is None:
            entry.setdefault("lower_threshold", None)
        if upper is None:
            entry.setdefault("upper_threshold", None)
    return template


def config_to_json_bytes(config: dict) -> bytes:
    return json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8-sig")
