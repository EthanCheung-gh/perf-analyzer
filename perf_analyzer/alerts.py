from __future__ import annotations

import numpy as np
import pandas as pd

from .models import Metric


def alert_mask(series: pd.Series, threshold: float, higher_is_worse: bool) -> pd.Series:
    return series > threshold if higher_is_worse else series < threshold


def interval_alert_mask(series: pd.Series, lower: float | None, upper: float | None) -> pd.Series:
    mask = pd.Series(False, index=series.index)
    if lower is not None:
        mask = mask | (series < lower)
    if upper is not None:
        mask = mask | (series > upper)
    return mask


def metric_alert_bounds(threshold_bounds: dict[str, tuple[float | None, float | None]] | None, metric: Metric) -> tuple[float | None, float | None]:
    if not threshold_bounds:
        return None, None
    return threshold_bounds.get(metric.key, (None, None))


def metric_alert_mask(
    series: pd.Series,
    metric: Metric,
    thresholds: dict[str, float],
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> pd.Series:
    lower, upper = metric_alert_bounds(threshold_bounds, metric)
    if lower is not None or upper is not None:
        return interval_alert_mask(series, lower, upper)
    if metric.key not in thresholds:
        return pd.Series(False, index=series.index)
    return alert_mask(series, thresholds[metric.key], metric.higher_is_worse)


def format_value(value: float, unit: str = "") -> str:
    if pd.isna(value):
        return "-"
    if unit in ("个", ""):
        return f"{value:,.0f}{unit}"
    return f"{value:,.2f}{unit}"


def metric_alert_rule_text(
    metric: Metric,
    thresholds: dict[str, float],
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> str:
    lower, upper = metric_alert_bounds(threshold_bounds, metric)
    if lower is not None and upper is not None:
        return f"{format_value(lower, metric.unit)} - {format_value(upper, metric.unit)}"
    if lower is not None:
        return f">= {format_value(lower, metric.unit)}"
    if upper is not None:
        return f"<= {format_value(upper, metric.unit)}"
    threshold = thresholds.get(metric.key, metric.default_threshold)
    operator = "<=" if metric.higher_is_worse else ">="
    return f"{operator} {format_value(threshold, metric.unit)}"


def metric_alert_deviation_percent(
    values: pd.Series,
    metric: Metric,
    thresholds: dict[str, float],
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> pd.Series:
    lower, upper = metric_alert_bounds(threshold_bounds, metric)
    result = pd.Series(np.nan, index=values.index, dtype=float)
    if lower is not None:
        low_mask = values < lower
        denominator = abs(lower) if lower != 0 else np.nan
        result.loc[low_mask] = (lower - values.loc[low_mask]).abs() / denominator * 100
    if upper is not None:
        high_mask = values > upper
        denominator = abs(upper) if upper != 0 else np.nan
        result.loc[high_mask] = (values.loc[high_mask] - upper).abs() / denominator * 100
    if lower is None and upper is None and metric.key in thresholds:
        threshold = thresholds[metric.key]
        denominator = abs(threshold) if threshold != 0 else np.nan
        result = (values - threshold).abs() / denominator * 100
    return result


def format_duration(minutes: float) -> str:
    if pd.isna(minutes):
        return "-"
    if minutes < 1:
        return f"{minutes * 60:.0f}秒"
    hours = int(minutes // 60)
    remain = minutes % 60
    if hours:
        return f"{hours}小时{remain:.0f}分钟"
    return f"{remain:.1f}分钟"


def format_peak_offset(group: pd.DataFrame, metric_key: str) -> str:
    values = group[["timestamp", metric_key]].dropna()
    if values.empty:
        return "-"
    idx = values[metric_key].idxmax()
    start = group["timestamp"].dropna().min()
    peak_time = group.loc[idx, "timestamp"]
    if pd.isna(start) or pd.isna(peak_time):
        return "-"
    minutes = (peak_time - start).total_seconds() / 60
    return format_duration(minutes)


def max_continuous_alert_minutes(
    group: pd.DataFrame,
    metric: Metric,
    thresholds: dict[str, float],
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> float:
    values = group[["timestamp", metric.key]].dropna().sort_values("timestamp")
    if values.empty:
        return 0.0
    alerts = metric_alert_mask(values[metric.key], metric, thresholds, threshold_bounds).to_numpy()
    if not alerts.any():
        return 0.0

    timestamps = values["timestamp"].reset_index(drop=True)
    diffs = timestamps.diff().dropna().dt.total_seconds() / 60
    sample_minutes = float(diffs.median()) if not diffs.empty and diffs.median() > 0 else 0.0

    max_minutes = 0.0
    run_start: int | None = None
    for index, is_alert in enumerate(alerts):
        if is_alert and run_start is None:
            run_start = index
        if run_start is not None and (not is_alert or index == len(alerts) - 1):
            run_end = index if is_alert else index - 1
            span = (timestamps.iloc[run_end] - timestamps.iloc[run_start]).total_seconds() / 60
            max_minutes = max(max_minutes, span + sample_minutes)
            run_start = None
    return float(max_minutes)


def alert_segments(
    data: pd.DataFrame,
    thresholds: dict[str, float],
    metrics: list[Metric],
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> pd.DataFrame:
    rows = []
    for (source, scene), group in data.groupby(["source", "scene"], sort=False):
        for metric in metrics:
            if metric.key not in group:
                continue
            values = group[["timestamp", metric.key]].dropna().sort_values("timestamp").reset_index(drop=True)
            if values.empty:
                continue

            alert_series = metric_alert_mask(values[metric.key], metric, thresholds, threshold_bounds).reset_index(drop=True)
            if not alert_series.any():
                continue

            diffs = values["timestamp"].diff().dropna().dt.total_seconds() / 60
            sample_minutes = float(diffs.median()) if not diffs.empty and diffs.median() > 0 else 0.0
            max_gap_minutes = sample_minutes * 1.5 if sample_minutes > 0 else 0.0
            alert_indexes = [index for index, is_alert in enumerate(alert_series) if bool(is_alert)]

            segments: list[list[int]] = []
            current: list[int] = []
            previous_index: int | None = None
            for index in alert_indexes:
                if previous_index is None:
                    current = [index]
                else:
                    gap_minutes = (values.loc[index, "timestamp"] - values.loc[previous_index, "timestamp"]).total_seconds() / 60
                    if max_gap_minutes <= 0 or gap_minutes <= max_gap_minutes:
                        current.append(index)
                    else:
                        segments.append(current)
                        current = [index]
                previous_index = index
            if current:
                segments.append(current)

            lower, upper = metric_alert_bounds(threshold_bounds, metric)
            for sequence, indexes in enumerate(segments, start=1):
                segment = values.loc[indexes].copy()
                start_time = segment["timestamp"].iloc[0]
                end_time = segment["timestamp"].iloc[-1]
                duration_minutes = (end_time - start_time).total_seconds() / 60 + sample_minutes
                segment_values = segment[metric.key]
                if lower is not None or upper is not None:
                    high_count = int((segment_values > upper).sum()) if upper is not None else 0
                    low_count = int((segment_values < lower).sum()) if lower is not None else 0
                    if high_count and low_count:
                        alert_type = "上下限均触发"
                    elif high_count:
                        alert_type = "高于上限"
                    elif low_count:
                        alert_type = "低于下限"
                    else:
                        alert_type = "区间异常"
                else:
                    alert_type = "高于阈值" if metric.higher_is_worse else "低于阈值"
                rows.append(
                    {
                        "数据源": source,
                        "场景": scene,
                        "指标key": metric.key,
                        "指标": metric.label,
                        "异常段": sequence,
                        "开始时间": start_time,
                        "结束时间": end_time,
                        "持续时长": format_duration(duration_minutes),
                        "持续时长(分钟)": float(duration_minutes),
                        "异常点数": len(segment),
                        "最小值": float(segment_values.min()),
                        "最大值": float(segment_values.max()),
                        "均值": float(segment_values.mean()),
                        "正常区间/阈值": metric_alert_rule_text(metric, thresholds, threshold_bounds),
                        "告警类型": alert_type,
                    }
                )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(["持续时长(分钟)", "异常点数"], ascending=False)
