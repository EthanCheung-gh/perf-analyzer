from __future__ import annotations

import numpy as np
import pandas as pd

from .models import Metric
from .stats import percentile


def timestamp_quality_summary(data: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if data.empty or "timestamp" not in data:
        return pd.DataFrame()
    for (source, scene), group in data.groupby(["source", "scene"], sort=False):
        timestamps = group["timestamp"].dropna()
        diffs = timestamps.diff().dt.total_seconds() if len(timestamps) >= 2 else pd.Series(dtype=float)
        sorted_diffs = timestamps.sort_values().diff().dropna().dt.total_seconds() if len(timestamps) >= 2 else pd.Series(dtype=float)
        has_subsecond = bool(((timestamps.dt.microsecond != 0) | (timestamps.dt.nanosecond != 0)).any()) if not timestamps.empty else False
        rows.append(
            {
                "数据源": source,
                "分组": scene,
                "有效时间点": len(timestamps),
                "最小时间": timestamps.min() if not timestamps.empty else pd.NaT,
                "最大时间": timestamps.max() if not timestamps.empty else pd.NaT,
                "总时长": str(timestamps.max() - timestamps.min()) if len(timestamps) >= 2 else "-",
                "包含毫秒/亚秒": "是" if has_subsecond else "否",
                "重复时间戳": int(timestamps.duplicated().sum()),
                "乱序次数": int((diffs < 0).sum()) if not diffs.empty else 0,
                "负采样间隔": int((diffs < 0).sum()) if not diffs.empty else 0,
                "中位采样间隔(秒)": float(sorted_diffs[sorted_diffs > 0].median()) if (sorted_diffs > 0).any() else np.nan,
                "P95采样间隔(秒)": percentile(sorted_diffs[sorted_diffs > 0], 0.95) if (sorted_diffs > 0).any() else np.nan,
            }
        )
    return pd.DataFrame(rows)


def metric_quality_summary(data: pd.DataFrame, metrics: list[Metric]) -> pd.DataFrame:
    rows = []
    if data.empty:
        return pd.DataFrame()
    for metric in metrics:
        if metric.key not in data:
            continue
        series = data[metric.key]
        non_null = series.dropna()
        row = {
            "指标": metric.label,
            "指标key": metric.key,
            "样本数": len(series),
            "非空数": len(non_null),
            "空值率(%)": float(series.isna().mean() * 100) if len(series) else np.nan,
            "全空": "是" if non_null.empty else "否",
            "常量": "是" if len(non_null) > 0 and non_null.nunique(dropna=True) <= 1 else "否",
        }
        if not non_null.empty:
            q1 = percentile(non_null, 0.25)
            q3 = percentile(non_null, 0.75)
            spread = q3 - q1
            lower = q1 - 3 * spread
            upper = q3 + 3 * spread
            row.update(
                {
                    "最小值": float(non_null.min()),
                    "最大值": float(non_null.max()),
                    "均值": float(non_null.mean()),
                    "P95": percentile(non_null, 0.95),
                    "极值疑点数": int(((non_null < lower) | (non_null > upper)).sum()) if spread > 0 else 0,
                }
            )
        rows.append(row)
    return pd.DataFrame(rows)


def sampling_gap_issue_summary(interval_data: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if interval_data.empty:
        return pd.DataFrame()
    for (source, scene, display_scene), group in interval_data.groupby(["source", "scene", "display_scene"], sort=False):
        values = group["采样间隔(秒)"].dropna()
        positive = values[values > 0]
        if positive.empty:
            continue
        median = float(positive.median())
        threshold = median * 3
        gap_count = int((positive > threshold).sum()) if threshold > 0 else 0
        rows.append(
            {
                "数据源": source,
                "分组": scene,
                "显示分组": display_scene,
                "中位间隔(秒)": median,
                "间隔突变阈值(秒)": threshold,
                "突变次数": gap_count,
                "最大间隔(秒)": float(positive.max()),
            }
        )
    return pd.DataFrame(rows)
