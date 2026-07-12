from __future__ import annotations

import numpy as np
import pandas as pd

from .alerts import (
    format_duration,
    format_peak_offset,
    format_value,
    max_continuous_alert_minutes,
    metric_alert_bounds,
    metric_alert_mask,
    metric_alert_rule_text,
)
from .models import Metric
from .stats import coefficient_of_variation, iqr, percentile, percentile_95


def _compute_metric_stats(
    values: pd.Series,
    group: pd.DataFrame | None = None,
    metric_key: str = "",
) -> dict[str, float]:
    """Compute standard metric statistics: mean, max, p90, p95, p99, std, iqr, cv, slope."""
    result: dict[str, float] = {}
    result["mean"] = float(values.mean())
    result["max"] = float(values.max())
    result["p90"] = float(percentile(values, 0.90))
    result["p95"] = float(percentile_95(values))
    result["p99"] = float(percentile(values, 0.99))
    result["std"] = float(values.std(ddof=0))
    result["iqr"] = float(iqr(values))
    result["cv"] = float(coefficient_of_variation(values))
    if group is not None and metric_key:
        slope, _ = linear_slope_per_minute(group, metric_key)
        result["slope"] = float(slope) if not pd.isna(slope) else np.nan
    else:
        result["slope"] = np.nan
    return result


def summarize(
    data: pd.DataFrame,
    thresholds: dict[str, float],
    metrics: list[Metric],
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> pd.DataFrame:
    # 汇总统计只依赖 metrics 列表，因此核心指标和动态扩展指标走同一套计算逻辑。
    rows = []
    group_cols = ["source", "scene"] if data["source"].nunique() > 1 else ["scene"]
    for group_key, group in data.groupby(group_cols, sort=False):
        if len(group_cols) == 2:
            source, scene = group_key
        else:
            source, scene = "", group_key
            if isinstance(scene, tuple):
                scene = scene[0]
        row = {"场景": scene, "样本数": len(group)}
        if source:
            row["数据源"] = source
        if group["timestamp"].notna().any():
            duration = group["timestamp"].max() - group["timestamp"].min()
            row["时长"] = str(duration).split(".")[0]
        else:
            row["时长"] = "-"

        for metric in metrics:
            values = group[metric.key].dropna()
            if values.empty:
                continue
            stats = _compute_metric_stats(values, group, metric.key)
            row[f"{metric.label}均值"] = stats["mean"]
            row[f"{metric.label}峰值"] = stats["max"]
            row[f"{metric.label}P90"] = stats["p90"]
            row[f"{metric.label}P95"] = stats["p95"]
            row[f"{metric.label}P99"] = stats["p99"]
            row[f"{metric.label}标准差"] = stats["std"]
            row[f"{metric.label}IQR"] = stats["iqr"]
            row[f"{metric.label}变异系数(%)"] = stats["cv"]
            row[f"{metric.label}趋势斜率/分钟"] = stats["slope"]
            row[f"{metric.label}峰值发生在"] = format_peak_offset(group, metric.key)
            if metric.key in thresholds or any(bound is not None for bound in metric_alert_bounds(threshold_bounds, metric)):
                mask = metric_alert_mask(values, metric, thresholds, threshold_bounds)
                row[f"{metric.label}超阈次数"] = int(mask.sum())
                row[f"{metric.label}超阈占比(%)"] = float(mask.mean() * 100)
                row[f"{metric.label}正常区间/阈值"] = metric_alert_rule_text(metric, thresholds, threshold_bounds)
                max_minutes = max_continuous_alert_minutes(group, metric, thresholds, threshold_bounds, precomputed_mask=mask)
                row[f"{metric.label}最大连续超阈"] = format_duration(max_minutes)
        rows.append(row)
    return pd.DataFrame(rows)


def metric_stats(data: pd.DataFrame, group_cols: list[str], metrics: list[Metric]) -> pd.DataFrame:
    rows = []
    for group_key, group in data.groupby(group_cols, sort=False):
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        row = dict(zip(group_cols, group_key, strict=False))
        for metric in metrics:
            values = group[metric.key].dropna()
            if values.empty:
                continue
            stats = _compute_metric_stats(values, group, metric.key)
            row[f"{metric.key}_mean"] = stats["mean"]
            row[f"{metric.key}_max"] = stats["max"]
            row[f"{metric.key}_p90"] = stats["p90"]
            row[f"{metric.key}_p95"] = stats["p95"]
            row[f"{metric.key}_p99"] = stats["p99"]
            row[f"{metric.key}_std"] = stats["std"]
            row[f"{metric.key}_iqr"] = stats["iqr"]
            row[f"{metric.key}_cv"] = stats["cv"]
            row[f"{metric.key}_slope"] = stats["slope"]
        rows.append(row)
    return pd.DataFrame(rows)


def apply_stable_window(data: pd.DataFrame, warmup_minutes: float) -> pd.DataFrame:
    # 稳定区间按“数据源 + 场景”分别裁剪，避免某个场景的起始时间影响其他场景。
    if warmup_minutes <= 0 or data.empty:
        return data
    frames = []
    for _, group in data.groupby(["source", "scene"], sort=False):
        group = group.sort_values("timestamp").copy()
        start = group["timestamp"].min()
        frames.append(group[group["timestamp"] >= start + pd.Timedelta(minutes=warmup_minutes)])
    return pd.concat(frames, ignore_index=True) if frames else data.iloc[0:0].copy()


def apply_advanced_filters(
    data: pd.DataFrame,
    time_range: tuple[pd.Timestamp, pd.Timestamp] | None = None,
    metric_conditions: list[tuple[str, str, float]] | None = None,
    metric_condition_logic: str = "AND",
    categorical_filters: dict[str, list[str]] | None = None,
    downsample_every_n: int | None = None,
) -> pd.DataFrame:
    """Apply time range, metric conditions, categorical filters, and downsampling.

    Args:
        data: Input DataFrame (already filtered by source + scene)
        time_range: (start, end) inclusive time range, or None for all
        metric_conditions: List of (metric_key, operator, value) tuples
        metric_condition_logic: "AND" (all must match) or "OR" (any must match)
        categorical_filters: Dict of {column_name: [allowed_values]}
        downsample_every_n: If set, take every Nth row per (source, scene) group

    Returns:
        Filtered DataFrame
    """
    result = data.copy()

    # Time range filter
    if time_range is not None and "timestamp" in result:
        start, end = time_range
        if pd.notna(start) and pd.notna(end):
            result = result[(result["timestamp"] >= start) & (result["timestamp"] <= end)]

    # Metric condition filter
    if metric_conditions:
        valid_conditions = [(key, op, val) for key, op, val in metric_conditions if key in result.columns]
        if valid_conditions:
            masks = []
            for key, op, val in valid_conditions:
                series = pd.to_numeric(result[key], errors="coerce")
                if op == ">":
                    masks.append(series > val)
                elif op == ">=":
                    masks.append(series >= val)
                elif op == "<":
                    masks.append(series < val)
                elif op == "<=":
                    masks.append(series <= val)
                elif op == "==":
                    masks.append(series == val)
                elif op == "!=":
                    masks.append(series != val)
            if metric_condition_logic == "AND":
                combined = pd.Series(True, index=result.index)
                for mask in masks:
                    combined = combined & mask.fillna(False)
            else:
                combined = pd.Series(False, index=result.index)
                for mask in masks:
                    combined = combined | mask.fillna(False)
            result = result[combined]

    # Categorical column filter
    if categorical_filters:
        for column, allowed_values in categorical_filters.items():
            if column in result.columns and allowed_values:
                result = result[result[column].isin(allowed_values)]

    # Downsampling (every Nth row per source+scene group)
    if downsample_every_n is not None and downsample_every_n > 1:
        frames = []
        for _, group in result.groupby(["source", "scene"], sort=False):
            frames.append(group.iloc[::downsample_every_n])
        result = pd.concat(frames, ignore_index=True) if frames else result.iloc[0:0].copy()

    return result


def linear_slope_per_minute(group: pd.DataFrame, metric_key: str) -> tuple[float, float]:
    values = group[["timestamp", metric_key]].dropna().sort_values("timestamp")
    if len(values) < 3:
        return np.nan, np.nan
    elapsed = (values["timestamp"] - values["timestamp"].min()).dt.total_seconds() / 60
    y = values[metric_key].astype(float)
    if elapsed.nunique() < 2:
        return np.nan, np.nan
    slope, intercept = np.polyfit(elapsed, y, 1)
    predicted = slope * elapsed + intercept
    ss_res = float(np.sum((y - predicted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot else np.nan
    return float(slope), r2


def leak_analysis(data: pd.DataFrame, slope_threshold: float) -> pd.DataFrame:
    rows = []
    for (source, scene), group in data.groupby(["source", "scene"], sort=False):
        slope, r2 = linear_slope_per_minute(group, "memory_mb")
        start_memory = group.sort_values("timestamp")["memory_mb"].dropna().head(1)
        end_memory = group.sort_values("timestamp")["memory_mb"].dropna().tail(1)
        growth = np.nan
        if not start_memory.empty and not end_memory.empty:
            growth = float(end_memory.iloc[0] - start_memory.iloc[0])
        if pd.isna(slope):
            risk = "数据不足"
        elif slope >= slope_threshold and (pd.isna(r2) or r2 >= 0.35):
            risk = "疑似泄漏"
        elif slope > 0:
            risk = "轻微增长"
        else:
            risk = "无明显增长"
        rows.append(
            {
                "数据源": source,
                "场景": scene,
                "内存斜率(MB/分钟)": slope,
                "R2": r2,
                "首尾增长(MB)": growth,
                "判断": risk,
            }
        )
    return pd.DataFrame(rows)


def trend_analysis(data: pd.DataFrame, metrics: list[Metric]) -> pd.DataFrame:
    rows = []
    for (source, scene), group in data.groupby(["source", "scene"], sort=False):
        sorted_group = group.sort_values("timestamp")
        for metric in metrics:
            if metric.key not in sorted_group or sorted_group[metric.key].dropna().empty:
                continue
            slope, r2 = linear_slope_per_minute(sorted_group, metric.key)
            values = sorted_group[metric.key].dropna()
            growth = np.nan
            if len(values) >= 2:
                growth = float(values.iloc[-1] - values.iloc[0])
            if pd.isna(slope):
                direction = "数据不足"
            elif abs(slope) < 1e-9:
                direction = "基本稳定"
            elif slope > 0:
                direction = "上升"
            else:
                direction = "下降"
            rows.append(
                {
                    "数据源": source,
                    "场景": scene,
                    "指标": metric.label,
                    "趋势斜率/分钟": slope,
                    "R2": r2,
                    "首尾变化": growth,
                    "趋势": direction,
                }
            )
    return pd.DataFrame(rows)


def alert_continuity_summary(
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
            has_rule = metric.key in thresholds or any(bound is not None for bound in metric_alert_bounds(threshold_bounds, metric))
            if not has_rule:
                continue
            values = group[metric.key].dropna()
            if values.empty:
                continue
            mask = metric_alert_mask(values, metric, thresholds, threshold_bounds)
            alert_count = int(mask.sum())
            if alert_count == 0:
                continue
            max_minutes = max_continuous_alert_minutes(group, metric, thresholds, threshold_bounds)
            rows.append(
                {
                    "数据源": source,
                    "场景": scene,
                    "指标": metric.label,
                    "正常区间/阈值": metric_alert_rule_text(metric, thresholds, threshold_bounds),
                    "超阈次数": alert_count,
                    "超阈占比(%)": float(mask.mean() * 100),
                    "最大连续超阈": format_duration(max_minutes),
                    "最大连续超阈(分钟)": max_minutes,
                }
            )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(["超阈占比(%)", "最大连续超阈(分钟)"], ascending=False)


def first_available_metric(data: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    for key in candidates:
        if key in data and data[key].dropna().any():
            return key
    return None


def safe_ratio(numerator: float, denominator: float) -> float:
    if pd.isna(numerator) or pd.isna(denominator) or denominator == 0:
        return np.nan
    return float(numerator / denominator)


def resource_efficiency_analysis(data: pd.DataFrame) -> pd.DataFrame:
    throughput_key = first_available_metric(data, ("qps", "tps", "task_count", "request_count"))
    rows = []
    for (source, scene), group in data.groupby(["source", "scene"], sort=False):
        throughput = group[throughput_key].mean() if throughput_key else np.nan
        throughput_label = {
            "qps": "QPS",
            "tps": "TPS",
            "task_count": "任务数",
            "request_count": "请求数",
        }.get(throughput_key or "", "-")
        concurrency = group["concurrency"].mean() if "concurrency" in group else np.nan
        cpu_p95 = percentile_95(group["cpu_percent"]) if "cpu_percent" in group else np.nan
        memory_peak = group["memory_mb"].max() if "memory_mb" in group else np.nan
        io_p95 = percentile_95(group["io"]) if "io" in group else np.nan
        response_p95 = percentile_95(group["response_time_ms"]) if "response_time_ms" in group else np.nan
        fps_p95 = percentile_95(group["fps"]) if "fps" in group else np.nan
        gc_time_p95 = percentile_95(group["gc_time_ms"]) if "gc_time_ms" in group else np.nan
        network_total = np.nan
        if "network_up_kbps" in group or "network_down_kbps" in group:
            network_up = group["network_up_kbps"].mean() if "network_up_kbps" in group else 0
            network_down = group["network_down_kbps"].mean() if "network_down_kbps" in group else 0
            network_total = network_up + network_down
        disk_total = np.nan
        if "disk_read_mbps" in group or "disk_write_mbps" in group:
            disk_read = group["disk_read_mbps"].mean() if "disk_read_mbps" in group else 0
            disk_write = group["disk_write_mbps"].mean() if "disk_write_mbps" in group else 0
            disk_total = disk_read + disk_write

        request_count = group["request_count"].sum() if "request_count" in group else np.nan
        failed_requests = group["failed_requests"].sum() if "failed_requests" in group else np.nan
        error_count = group["error_count"].sum() if "error_count" in group else np.nan
        failure_rate = safe_ratio(failed_requests, request_count) * 100 if not pd.isna(failed_requests) else np.nan
        error_per_thousand = safe_ratio(error_count, request_count) * 1000 if not pd.isna(error_count) else np.nan

        rows.append(
            {
                "数据源": source,
                "场景": scene,
                "吞吐口径": throughput_label,
                "平均吞吐": throughput,
                "平均并发": concurrency,
                "CPU P95": cpu_p95,
                "内存峰值(MB)": memory_peak,
                "响应时间P95(ms)": response_p95,
                "FPS P95": fps_p95,
                "GC耗时P95(ms)": gc_time_p95,
                "CPU P95/吞吐": safe_ratio(cpu_p95, throughput),
                "内存峰值/并发(MB)": safe_ratio(memory_peak, concurrency),
                "IO P95/吞吐": safe_ratio(io_p95, throughput),
                "网络KBps/吞吐": safe_ratio(network_total, throughput),
                "磁盘MBps/吞吐": safe_ratio(disk_total, throughput),
                "失败率(%)": failure_rate,
                "每千请求错误数": error_per_thousand,
            }
        )
    return pd.DataFrame(rows)


def value_score(value: float, warning: float, critical: float, higher_is_worse: bool = True) -> int:
    if pd.isna(value):
        return 0
    if higher_is_worse:
        if value >= critical:
            return 2
        if value >= warning:
            return 1
    else:
        if value <= critical:
            return 2
        if value <= warning:
            return 1
    return 0


def score_to_level(score: int) -> str:
    if score >= 7:
        return "高风险"
    if score >= 3:
        return "中风险"
    return "低风险"


def scene_decision_analysis(
    data: pd.DataFrame,
    thresholds: dict[str, float],
    metrics: list[Metric],
    slope_threshold: float,
    threshold_bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> pd.DataFrame:
    alerts = alert_continuity_summary(data, thresholds, metrics, threshold_bounds)
    leaks = leak_analysis(data, slope_threshold)
    efficiency = resource_efficiency_analysis(data)
    rows = []
    for (source, scene), _group in data.groupby(["source", "scene"], sort=False):
        reasons = []
        score = 0

        scene_alerts = alerts[(alerts["数据源"] == source) & (alerts["场景"] == scene)] if not alerts.empty else pd.DataFrame()
        if not scene_alerts.empty:
            max_alert_ratio = float(scene_alerts["超阈占比(%)"].max())
            max_alert_minutes = float(scene_alerts["最大连续超阈(分钟)"].max())
            score += value_score(max_alert_ratio, 5, 20)
            score += value_score(max_alert_minutes, 1, 5)
            if max_alert_ratio >= 5:
                reasons.append(f"超阈占比最高 {max_alert_ratio:.1f}%")
            if max_alert_minutes >= 1:
                reasons.append(f"最长连续超阈 {format_duration(max_alert_minutes)}")
        else:
            max_alert_ratio = 0.0
            max_alert_minutes = 0.0

        leak_row = leaks[(leaks["数据源"] == source) & (leaks["场景"] == scene)] if not leaks.empty else pd.DataFrame()
        leak_result = leak_row["判断"].iloc[0] if not leak_row.empty else "数据不足"
        if leak_result == "疑似泄漏":
            score += 3
            reasons.append("疑似内存泄漏")
        elif leak_result == "轻微增长":
            score += 1

        efficiency_row = efficiency[(efficiency["数据源"] == source) & (efficiency["场景"] == scene)] if not efficiency.empty else pd.DataFrame()
        failure_rate = efficiency_row["失败率(%)"].iloc[0] if not efficiency_row.empty else np.nan
        response_p95 = efficiency_row["响应时间P95(ms)"].iloc[0] if not efficiency_row.empty else np.nan
        fps_p95 = efficiency_row["FPS P95"].iloc[0] if not efficiency_row.empty else np.nan
        error_per_thousand = efficiency_row["每千请求错误数"].iloc[0] if not efficiency_row.empty else np.nan

        score += value_score(failure_rate, 0.1, 1.0)
        score += value_score(error_per_thousand, 1.0, 10.0)
        score += value_score(response_p95, 500, 1000)
        score += value_score(fps_p95, 45, 30, higher_is_worse=False)
        if not pd.isna(failure_rate) and failure_rate >= 0.1:
            reasons.append(f"失败率 {failure_rate:.2f}%")
        if not pd.isna(response_p95) and response_p95 >= 500:
            reasons.append(f"响应时间P95 {response_p95:.0f}ms")
        if not pd.isna(fps_p95) and fps_p95 <= 45:
            reasons.append(f"FPS P95 {fps_p95:.1f}")

        rows.append(
            {
                "数据源": source,
                "场景": scene,
                "风险评分": score,
                "风险等级": score_to_level(score),
                "最大超阈占比(%)": max_alert_ratio,
                "最长连续超阈": format_duration(max_alert_minutes),
                "内存趋势": leak_result,
                "失败率(%)": failure_rate,
                "响应时间P95(ms)": response_p95,
                "FPS P95": fps_p95,
                "主要原因": "；".join(reasons) if reasons else "未见明显风险",
            }
        )
    return pd.DataFrame(rows).sort_values("风险评分", ascending=False) if rows else pd.DataFrame()


def release_gate_analysis(
    decisions: pd.DataFrame,
    max_allowed_level: str,
    fail_on_leak: bool,
    fail_on_any_alert: bool,
    fail_on_errors: bool,
) -> tuple[str, pd.DataFrame]:
    if decisions.empty:
        return "数据不足", pd.DataFrame()

    level_rank = {"低风险": 1, "中风险": 2, "高风险": 3}
    allowed_rank = level_rank[max_allowed_level]
    rows = []

    risky = decisions[decisions["风险等级"].map(level_rank).fillna(0) > allowed_rank]
    rows.append(
        {
            "规则": f"场景风险等级不高于{max_allowed_level}",
            "结果": "失败" if not risky.empty else "通过",
            "详情": "、".join(risky["场景"].astype(str).unique()) if not risky.empty else "全部场景满足",
        }
    )

    if fail_on_leak:
        leaks = decisions[decisions["内存趋势"] == "疑似泄漏"]
        rows.append(
            {
                "规则": "不允许疑似内存泄漏",
                "结果": "失败" if not leaks.empty else "通过",
                "详情": "、".join(leaks["场景"].astype(str).unique()) if not leaks.empty else "未发现疑似泄漏",
            }
        )

    if fail_on_any_alert:
        alerts = decisions[decisions["最大超阈占比(%)"] > 0]
        rows.append(
            {
                "规则": "不允许超阈采样点",
                "结果": "失败" if not alerts.empty else "通过",
                "详情": "、".join(alerts["场景"].astype(str).unique()) if not alerts.empty else "未发现超阈",
            }
        )

    if fail_on_errors:
        errors = decisions[decisions["失败率(%)"].fillna(0) > 0]
        rows.append(
            {
                "规则": "不允许请求失败",
                "结果": "失败" if not errors.empty else "通过",
                "详情": "、".join(errors["场景"].astype(str).unique()) if not errors.empty else "未发现失败请求",
            }
        )

    result = pd.DataFrame(rows)
    status = "不通过" if (result["结果"] == "失败").any() else "通过"
    return status, result


def capacity_estimation(
    data: pd.DataFrame,
    test_cpu_cores: int,
    target_cpu_utilization: float,
    target_throughputs: list[float],
    system_reserved_memory_gb: float,
) -> pd.DataFrame:
    efficiency = resource_efficiency_analysis(data)
    if efficiency.empty:
        return pd.DataFrame()

    cpu_cost = efficiency["CPU P95/吞吐"].replace([np.inf, -np.inf], np.nan).dropna()
    memory_cost = efficiency["内存峰值/并发(MB)"].replace([np.inf, -np.inf], np.nan).dropna()
    concurrency_per_throughput = safe_ratio(efficiency["平均并发"].sum(), efficiency["平均吞吐"].sum())
    cpu_cost_p95 = percentile_95(cpu_cost) if not cpu_cost.empty else np.nan
    memory_cost_p95 = percentile_95(memory_cost) if not memory_cost.empty else np.nan
    target_ratio = target_cpu_utilization / 100

    rows = []
    for throughput in target_throughputs:
        target_concurrency = throughput * concurrency_per_throughput if not pd.isna(concurrency_per_throughput) else np.nan
        cpu_percent_needed = cpu_cost_p95 * throughput if not pd.isna(cpu_cost_p95) else np.nan
        raw_cores = test_cpu_cores * (cpu_percent_needed / 100) / target_ratio if target_ratio and not pd.isna(cpu_percent_needed) else np.nan
        memory_gb = (memory_cost_p95 * target_concurrency / 1024 + system_reserved_memory_gb) if not pd.isna(memory_cost_p95) and not pd.isna(target_concurrency) else np.nan
        rows.append(
            {
                "目标吞吐": throughput,
                "估算并发": target_concurrency,
                "CPU需求(核)": raw_cores,
                "建议CPU核数": round_up_to_common_cores(raw_cores),
                "内存需求(GB)": memory_gb,
                "建议内存": f"{round_up_memory_gb(memory_gb)}GB" if not pd.isna(memory_gb) else "-",
                "估算依据": "按当前数据的 P95 单位资源成本线性外推",
            }
        )
    return pd.DataFrame(rows)


def stability_score_analysis(decisions: pd.DataFrame) -> pd.DataFrame:
    if decisions.empty:
        return pd.DataFrame()
    rows = []
    for _, row in decisions.iterrows():
        score = max(0, 100 - row["风险评分"] * 10)
        rows.append(
            {
                "数据源": row["数据源"],
                "场景": row["场景"],
                "稳定性评分": score,
                "等级": "优秀" if score >= 85 else "可接受" if score >= 70 else "需关注" if score >= 50 else "高风险",
                "扣分原因": row["主要原因"],
            }
        )
    return pd.DataFrame(rows).sort_values("稳定性评分")


def bottleneck_hints(data: pd.DataFrame, thresholds: dict[str, float], metrics: list[Metric]) -> pd.DataFrame:
    rows = []
    for (source, scene), group in data.groupby(["source", "scene"], sort=False):
        hints = []
        cpu_p95 = percentile_95(group["cpu_percent"]) if "cpu_percent" in group else np.nan
        memory_p95 = percentile_95(group["memory_percent"]) if "memory_percent" in group else np.nan
        io_p95 = percentile_95(group["io"]) if "io" in group else np.nan
        response_p95 = percentile_95(group["response_time_ms"]) if "response_time_ms" in group else np.nan
        failure_rate = np.nan
        if "failed_requests" in group and "request_count" in group:
            failure_rate = safe_ratio(group["failed_requests"].sum(), group["request_count"].sum()) * 100

        if not pd.isna(cpu_p95) and cpu_p95 >= thresholds.get("cpu_percent", 80) * 0.9:
            hints.append("CPU压力")
        if not pd.isna(memory_p95) and memory_p95 >= thresholds.get("memory_percent", 70) * 0.9:
            hints.append("内存压力")
        if not pd.isna(io_p95) and io_p95 >= thresholds.get("io", 8) * 0.9:
            hints.append("IO压力")
        if ("network_up_kbps" in group or "network_down_kbps" in group) and not pd.isna(response_p95) and response_p95 >= 500:
            network_total = (group["network_up_kbps"].mean() if "network_up_kbps" in group else 0) + (group["network_down_kbps"].mean() if "network_down_kbps" in group else 0)
            if network_total > 1024:
                hints.append("网络压力")
        if not pd.isna(failure_rate) and failure_rate > 0:
            hints.append("业务错误/重试")
        if not pd.isna(response_p95) and response_p95 >= 500 and not hints:
            hints.append("响应慢但资源瓶颈不明显")

        rows.append(
            {
                "数据源": source,
                "场景": scene,
                "瓶颈提示": "、".join(hints) if hints else "未见明显瓶颈",
                "CPU P95": cpu_p95,
                "内存占比P95": memory_p95,
                "IO P95": io_p95,
                "响应时间P95(ms)": response_p95,
                "失败率(%)": failure_rate,
            }
        )
    return pd.DataFrame(rows)


def version_regression_heatmap_data(
    stats: pd.DataFrame,
    metrics: list[Metric],
    baseline_source: str,
    stat_name: str,
) -> pd.DataFrame:
    rows = []
    for metric in metrics:
        column = f"{metric.key}_{stat_name}"
        if column not in stats:
            continue
        baseline = stats[stats["source"] == baseline_source][["scene", column]].rename(columns={column: "基准值"})
        current = stats[stats["source"] != baseline_source][["source", "scene", column]].rename(columns={column: "当前值"})
        merged = current.merge(baseline, on="scene", how="left")
        if merged.empty:
            continue
        merged["增长率(%)"] = np.where(
            merged["基准值"].isna() | (merged["基准值"] == 0),
            np.nan,
            (merged["当前值"] - merged["基准值"]) / merged["基准值"] * 100,
        )
        # 统一成“越大越退化”的口径，FPS/QPS 这类越低越差指标会反向。
        merged["退化幅度(%)"] = merged["增长率(%)"] if metric.higher_is_worse else -merged["增长率(%)"]
        for _, row in merged.iterrows():
            rows.append(
                {
                    "场景标识": f"{row['source']} / {row['scene']}",
                    "指标": metric.label,
                    "退化幅度(%)": row["退化幅度(%)"],
                    "增长率(%)": row["增长率(%)"],
                }
            )
    return pd.DataFrame(rows)


def risk_matrix_data(decisions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in decisions.iterrows():
        scene_id = f"{row['数据源']} / {row['场景']}"
        items = {
            "超阈占比": value_score(row.get("最大超阈占比(%)", np.nan), 5, 20),
            "连续超阈": 2 if row.get("最长连续超阈") not in ("-", "0秒", "0.0分钟") and row.get("最大超阈占比(%)", 0) > 0 else 0,
            "内存趋势": 2 if row.get("内存趋势") == "疑似泄漏" else 1 if row.get("内存趋势") == "轻微增长" else 0,
            "失败率": value_score(row.get("失败率(%)", np.nan), 0.1, 1.0),
            "响应时间": value_score(row.get("响应时间P95(ms)", np.nan), 500, 1000),
            "FPS": value_score(row.get("FPS P95", np.nan), 45, 30, higher_is_worse=False),
        }
        for item, score in items.items():
            rows.append({"场景标识": scene_id, "风险项": item, "风险分": score})
    return pd.DataFrame(rows)


def radar_profile_data(data: pd.DataFrame, decisions: pd.DataFrame, thresholds: dict[str, float]) -> pd.DataFrame:
    rows = []
    for _, decision in decisions.iterrows():
        source = decision["数据源"]
        scene = decision["场景"]
        group = data[(data["source"] == source) & (data["scene"] == scene)]
        if group.empty:
            continue

        cpu_p95 = percentile_95(group["cpu_percent"]) if "cpu_percent" in group else np.nan
        memory_pct_p95 = percentile_95(group["memory_percent"]) if "memory_percent" in group else np.nan
        io_p95 = percentile_95(group["io"]) if "io" in group else np.nan
        response_p95 = percentile_95(group["response_time_ms"]) if "response_time_ms" in group else np.nan
        fps_p95 = percentile_95(group["fps"]) if "fps" in group else np.nan
        failure_rate = decision.get("失败率(%)", np.nan)

        profile = {
            "CPU压力": min(100, safe_ratio(cpu_p95, thresholds.get("cpu_percent", 80)) * 100),
            "内存压力": min(100, safe_ratio(memory_pct_p95, thresholds.get("memory_percent", 70)) * 100),
            "IO压力": min(100, safe_ratio(io_p95, thresholds.get("io", 8)) * 100),
            "响应风险": min(100, safe_ratio(response_p95, 1000) * 100),
            "错误风险": min(100, safe_ratio(failure_rate, 1.0) * 100),
            "流畅风险": min(100, max(0, safe_ratio(60 - fps_p95, 30) * 100) if not pd.isna(fps_p95) else np.nan),
            "稳定风险": min(100, decision.get("风险评分", 0) * 10),
        }
        for dimension, value in profile.items():
            rows.append(
                {
                    "场景标识": f"{source} / {scene}",
                    "维度": dimension,
                    "风险分": 0 if pd.isna(value) else float(value),
                }
            )
    return pd.DataFrame(rows)


def round_up_to_common_cores(value: float) -> int:
    if pd.isna(value) or value <= 1:
        return 1
    common = [1, 2, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128]
    for cores in common:
        if value <= cores:
            return cores
    return int(np.ceil(value / 16) * 16)


def round_up_memory_gb(value: float) -> int:
    if pd.isna(value) or value <= 2:
        return 2
    common = [2, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256]
    for memory in common:
        if value <= memory:
            return memory
    return int(np.ceil(value / 64) * 64)


def configuration_recommendation(
    data: pd.DataFrame,
    test_cpu_cores: int,
    target_cpu_utilization: float,
    minimum_cpu_cores: int,
    system_reserved_memory_gb: float,
    minimum_memory_gb: int,
    minimum_free_disk_gb: int,
    recommendation_factor: float,
    slope_threshold: float,
) -> tuple[pd.DataFrame, list[str]]:
    # 配置建议需要明确语义，目前只使用 CPU / 内存 / IO / 线程 / 句柄这些核心指标。
    # 动态扩展指标会进入通用分析，但不会自动参与最低配置推导。
    cpu_p95 = percentile_95(data["cpu_percent"])
    cpu_peak = data["cpu_percent"].max()
    memory_p95_gb = percentile_95(data["memory_mb"]) / 1024
    memory_peak_gb = data["memory_mb"].max() / 1024
    io_p95 = percentile_95(data["io"])
    thread_peak = data["threads"].max()
    handle_peak = data["handles"].max()

    target_ratio = target_cpu_utilization / 100
    cpu_raw = test_cpu_cores * (cpu_p95 / 100) / target_ratio if target_ratio else np.nan
    minimum_cpu = max(minimum_cpu_cores, round_up_to_common_cores(cpu_raw))
    recommended_cpu = round_up_to_common_cores(minimum_cpu * recommendation_factor)

    memory_raw = memory_peak_gb + system_reserved_memory_gb
    minimum_memory = max(minimum_memory_gb, round_up_memory_gb(memory_raw))
    recommended_memory = round_up_memory_gb(minimum_memory * recommendation_factor)

    io_risk = "需要补充磁盘指标" if pd.isna(io_p95) else "关注高 IO 场景" if io_p95 >= 8 else "未见明显高 IO"
    leaks = leak_analysis(data, slope_threshold)
    leak_risk = "存在疑似泄漏" if not leaks[leaks["判断"] == "疑似泄漏"].empty else "未见明显泄漏"

    rows = [
        {
            "配置档位": "最低可运行",
            "CPU核数": minimum_cpu,
            "内存": f"{minimum_memory}GB",
            "磁盘": f"SSD，剩余空间不少于 {minimum_free_disk_gb}GB",
            "适用说明": "覆盖当前筛选场景，按P95 CPU和内存峰值加预留估算",
        },
        {
            "配置档位": "推荐配置",
            "CPU核数": recommended_cpu,
            "内存": f"{recommended_memory}GB",
            "磁盘": f"SSD，剩余空间不少于 {round_up_memory_gb(minimum_free_disk_gb * recommendation_factor)}GB",
            "适用说明": "在最低配置基础上增加安全余量，更适合日常稳定运行",
        },
    ]

    notes = [
        f"CPU估算：测试机 {test_cpu_cores} 核，当前筛选数据 CPU P95 为 {format_value(cpu_p95, '%')}，目标单机CPU利用率为 {target_cpu_utilization:.0f}%。",
        f"CPU原始需求 = 测试机核数 × CPU P95 / 目标利用率 = {test_cpu_cores} × {cpu_p95:.2f}% / {target_cpu_utilization:.0f}% = {cpu_raw:.2f} 核，再向上取常见核数档位。",
        f"内存估算：应用内存峰值 {memory_peak_gb:.2f}GB + 系统预留 {system_reserved_memory_gb:.2f}GB，再向上取常见内存档位。",
        f"当前CPU峰值为 {format_value(cpu_peak, '%')}；如果峰值持续时间较长，应优先参考峰值或P99，而不是P95。",
        f"线程峰值 {format_value(thread_peak, '个')}，句柄峰值 {format_value(handle_peak, '个')}，IO判断：{io_risk}。",
        f"长时间稳定性判断：{leak_risk}。如存在泄漏，最低配置结论应暂缓，先修复增长问题或限定连续运行时长。",
    ]
    return pd.DataFrame(rows), notes
