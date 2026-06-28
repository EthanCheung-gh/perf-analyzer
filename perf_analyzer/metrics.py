from __future__ import annotations

import pandas as pd

from .constants import META_COLUMNS, STANDARD_METRICS
from .models import Metric
from .stats import percentile_95
from .utils import dynamic_metric_label


def discover_metrics(data: pd.DataFrame) -> list[Metric]:
    """根据当前数据生成指标列表：核心指标优先，其余数值列作为动态扩展指标。"""
    metrics: list[Metric] = []
    for metric in STANDARD_METRICS:
        if metric.key in data.columns and data[metric.key].notna().any():
            metrics.append(metric)

    existing = {metric.key for metric in metrics}
    for column in data.columns:
        if column in existing or column in META_COLUMNS or column == "total_memory_mb":
            continue
        if pd.api.types.is_numeric_dtype(data[column]) and data[column].notna().any():
            label = dynamic_metric_label(column) if column.startswith("extra::") else column
            default_threshold = percentile_95(data[column])
            if pd.isna(default_threshold):
                default_threshold = 0.0
            metrics.append(Metric(column, label, "", f"{label} 告警阈值", float(default_threshold)))
    return metrics


def metric_by_key(metrics: list[Metric], key: str) -> Metric:
    return next(metric for metric in metrics if metric.key == key)
