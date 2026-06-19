from __future__ import annotations

import json
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


SAMPLE_FILE = Path("data/sample_resource_consumption.xlsx")
PERFORMANCE_MODE = "应用性能"
GENERIC_MODE = "通用时序"
ANALYSIS_MODES = (PERFORMANCE_MODE, GENERIC_MODE)

TIME_KEYS = ("时间", "timestamp", "time", "date")
CPU_KEYS = ("cpu", "CPU")
MEMORY_KEYS = ("内存占用", "memory", "mem", "rss", "working")
TOTAL_MEMORY_KEYS = ("系统总内存", "total memory", "total_memory", "物理内存")
MEMORY_PERCENT_KEYS = ("内存占用百分比", "memory percent", "memory%", "mem%", "内存%")
THREAD_KEYS = ("线程", "thread")
HANDLE_KEYS = ("句柄", "handle")
IO_KEYS = ("io", "i/o", "读写", "磁盘")
QPS_KEYS = ("qps", "每秒请求", "请求吞吐")
TPS_KEYS = ("tps", "每秒事务", "事务吞吐")
TASK_COUNT_KEYS = ("任务数", "处理条数", "task", "processed", "records")
CONCURRENCY_KEYS = ("并发", "concurrency", "connections", "连接数", "用户数")
RESPONSE_TIME_KEYS = ("响应时间", "response", "latency", "耗时", "duration")
ERROR_COUNT_KEYS = ("错误数", "error", "失败数", "fail")
FPS_KEYS = ("fps", "帧率")
JANK_COUNT_KEYS = ("卡顿", "jank", "stutter")
GC_COUNT_KEYS = ("gc次数", "gc count", "gc_count")
GC_TIME_KEYS = ("gc耗时", "gc time", "gc_time")
HEAP_KEYS = ("堆内存", "heap")
NETWORK_UP_KEYS = ("网络上行", "上行", "upload", "network up", "tx")
NETWORK_DOWN_KEYS = ("网络下行", "下行", "download", "network down", "rx")
REQUEST_COUNT_KEYS = ("请求数", "request count", "requests")
FAILED_REQUEST_KEYS = ("失败请求", "failed request", "request fail")
RETRY_COUNT_KEYS = ("重试", "retry")
DISK_READ_KEYS = ("磁盘读", "disk read", "read mb")
DISK_WRITE_KEYS = ("磁盘写", "disk write", "write mb")
IOPS_KEYS = ("iops", "io次数")
IO_WAIT_KEYS = ("io等待", "io wait", "iowait")
MAPPING_FIELDS = {
    "timestamp": ("时间戳", TIME_KEYS),
    "cpu_percent": ("CPU%", CPU_KEYS),
    "memory_mb": ("内存占用（MB）", MEMORY_KEYS),
    "total_memory_mb": ("系统总内存", TOTAL_MEMORY_KEYS),
    "memory_percent": ("内存占用百分比", MEMORY_PERCENT_KEYS),
    "threads": ("线程", THREAD_KEYS),
    "handles": ("句柄", HANDLE_KEYS),
    "io": ("io", IO_KEYS),
    "qps": ("QPS", QPS_KEYS),
    "tps": ("TPS", TPS_KEYS),
    "task_count": ("任务数/处理条数", TASK_COUNT_KEYS),
    "concurrency": ("并发数/连接数", CONCURRENCY_KEYS),
    "response_time_ms": ("响应时间(ms)", RESPONSE_TIME_KEYS),
    "error_count": ("错误数", ERROR_COUNT_KEYS),
    "fps": ("FPS", FPS_KEYS),
    "jank_count": ("卡顿次数", JANK_COUNT_KEYS),
    "gc_count": ("GC次数", GC_COUNT_KEYS),
    "gc_time_ms": ("GC耗时(ms)", GC_TIME_KEYS),
    "heap_mb": ("堆内存(MB)", HEAP_KEYS),
    "network_up_kbps": ("网络上行(KB/s)", NETWORK_UP_KEYS),
    "network_down_kbps": ("网络下行(KB/s)", NETWORK_DOWN_KEYS),
    "request_count": ("请求数", REQUEST_COUNT_KEYS),
    "failed_requests": ("失败请求数", FAILED_REQUEST_KEYS),
    "retry_count": ("重试次数", RETRY_COUNT_KEYS),
    "disk_read_mbps": ("磁盘读(MB/s)", DISK_READ_KEYS),
    "disk_write_mbps": ("磁盘写(MB/s)", DISK_WRITE_KEYS),
    "iops": ("IOPS", IOPS_KEYS),
    "io_wait_ms": ("IO等待(ms)", IO_WAIT_KEYS),
}


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str
    threshold_label: str
    default_threshold: float
    higher_is_worse: bool = True


CORE_METRICS = [
    Metric("cpu_percent", "CPU", "%", "CPU 告警阈值", 80.0),
    Metric("memory_mb", "内存占用", "MB", "内存告警阈值", 2048.0),
    Metric("memory_percent", "内存占比", "%", "内存占比告警阈值", 70.0),
    Metric("threads", "线程", "个", "线程告警阈值", 120.0),
    Metric("handles", "句柄", "个", "句柄告警阈值", 1500.0),
    Metric("io", "IO", "", "IO 告警阈值", 8.0),
]
CORE_METRIC_KEYS = {metric.key for metric in CORE_METRICS}
SEMANTIC_METRICS = [
    Metric("qps", "QPS", "", "QPS 告警阈值", 10.0, higher_is_worse=False),
    Metric("tps", "TPS", "", "TPS 告警阈值", 10.0, higher_is_worse=False),
    Metric("task_count", "任务数", "个", "任务数告警阈值", 10.0, higher_is_worse=False),
    Metric("concurrency", "并发数", "个", "并发告警阈值", 100.0),
    Metric("response_time_ms", "响应时间", "ms", "响应时间告警阈值", 1000.0),
    Metric("error_count", "错误数", "个", "错误数告警阈值", 1.0),
    Metric("fps", "FPS", "", "FPS 告警阈值", 45.0, higher_is_worse=False),
    Metric("jank_count", "卡顿次数", "次", "卡顿次数告警阈值", 1.0),
    Metric("gc_count", "GC次数", "次", "GC次数告警阈值", 10.0),
    Metric("gc_time_ms", "GC耗时", "ms", "GC耗时告警阈值", 100.0),
    Metric("heap_mb", "堆内存", "MB", "堆内存告警阈值", 1024.0),
    Metric("network_up_kbps", "网络上行", "KB/s", "网络上行告警阈值", 1024.0),
    Metric("network_down_kbps", "网络下行", "KB/s", "网络下行告警阈值", 4096.0),
    Metric("request_count", "请求数", "个", "请求数告警阈值", 1000.0, higher_is_worse=False),
    Metric("failed_requests", "失败请求数", "个", "失败请求告警阈值", 1.0),
    Metric("retry_count", "重试次数", "次", "重试次数告警阈值", 1.0),
    Metric("disk_read_mbps", "磁盘读", "MB/s", "磁盘读告警阈值", 100.0),
    Metric("disk_write_mbps", "磁盘写", "MB/s", "磁盘写告警阈值", 100.0),
    Metric("iops", "IOPS", "", "IOPS 告警阈值", 1000.0),
    Metric("io_wait_ms", "IO等待", "ms", "IO等待告警阈值", 50.0),
]
STANDARD_METRICS = [*CORE_METRICS, *SEMANTIC_METRICS]
META_COLUMNS = {"timestamp", "source", "scene", "display_scene"}


def clean_name(value: object) -> str:
    return str(value).strip().replace("（", "(").replace("）", ")").lower()


def parse_aliases(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def is_numeric_like(series: pd.Series) -> bool:
    """判断一列是否适合作为动态指标：只要有一部分值能转成数字，就纳入分析。"""
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.notna().sum() > 0


def dynamic_metric_key(column: str) -> str:
    """为原始 Excel 扩展列生成内部字段名，避免和核心字段、元字段冲突。"""
    return f"extra::{column}"


def dynamic_metric_label(key: str) -> str:
    return key.removeprefix("extra::")


def find_column(
    columns: list[str],
    keys: tuple[str, ...],
    exclude: tuple[str, ...] = (),
    aliases: tuple[str, ...] = (),
) -> str | None:
    cleaned = {column: clean_name(column) for column in columns}
    for alias in aliases:
        alias_name = clean_name(alias)
        for column, name in cleaned.items():
            if name == alias_name:
                return column
    for column, name in cleaned.items():
        if exclude and any(clean_name(item) in name for item in exclude):
            continue
        if any(clean_name(key) in name for key in (*aliases, *keys)):
            return column
    return None


def normalize_scene(df: pd.DataFrame, scene_name: str, source_name: str, field_aliases: dict[str, tuple[str, ...]]) -> pd.DataFrame:
    # 每个场景 sheet 先做“标准字段映射”，把不同工具导出的表头统一成内部字段名。
    columns = [str(column) for column in df.columns]
    df = df.copy()
    df.columns = columns

    mapping = {
        "timestamp": find_column(columns, TIME_KEYS, aliases=field_aliases.get("timestamp", ())),
        "cpu_percent": find_column(columns, CPU_KEYS, aliases=field_aliases.get("cpu_percent", ())),
        "memory_mb": find_column(
            columns,
            MEMORY_KEYS,
            exclude=("%", "百分比", "percent", "total", "总"),
            aliases=field_aliases.get("memory_mb", ()),
        ),
        "total_memory_mb": find_column(columns, TOTAL_MEMORY_KEYS, aliases=field_aliases.get("total_memory_mb", ())),
        "memory_percent": find_column(columns, MEMORY_PERCENT_KEYS, aliases=field_aliases.get("memory_percent", ())),
        "threads": find_column(columns, THREAD_KEYS, aliases=field_aliases.get("threads", ())),
        "handles": find_column(columns, HANDLE_KEYS, aliases=field_aliases.get("handles", ())),
        "io": find_column(columns, IO_KEYS, aliases=field_aliases.get("io", ())),
        "qps": find_column(columns, QPS_KEYS, aliases=field_aliases.get("qps", ())),
        "tps": find_column(columns, TPS_KEYS, aliases=field_aliases.get("tps", ())),
        "task_count": find_column(columns, TASK_COUNT_KEYS, aliases=field_aliases.get("task_count", ())),
        "concurrency": find_column(columns, CONCURRENCY_KEYS, aliases=field_aliases.get("concurrency", ())),
        "response_time_ms": find_column(columns, RESPONSE_TIME_KEYS, aliases=field_aliases.get("response_time_ms", ())),
        "error_count": find_column(columns, ERROR_COUNT_KEYS, aliases=field_aliases.get("error_count", ())),
        "fps": find_column(columns, FPS_KEYS, aliases=field_aliases.get("fps", ())),
        "jank_count": find_column(columns, JANK_COUNT_KEYS, aliases=field_aliases.get("jank_count", ())),
        "gc_count": find_column(columns, GC_COUNT_KEYS, aliases=field_aliases.get("gc_count", ())),
        "gc_time_ms": find_column(columns, GC_TIME_KEYS, aliases=field_aliases.get("gc_time_ms", ())),
        "heap_mb": find_column(columns, HEAP_KEYS, aliases=field_aliases.get("heap_mb", ())),
        "network_up_kbps": find_column(columns, NETWORK_UP_KEYS, aliases=field_aliases.get("network_up_kbps", ())),
        "network_down_kbps": find_column(columns, NETWORK_DOWN_KEYS, aliases=field_aliases.get("network_down_kbps", ())),
        "request_count": find_column(columns, REQUEST_COUNT_KEYS, aliases=field_aliases.get("request_count", ())),
        "failed_requests": find_column(columns, FAILED_REQUEST_KEYS, aliases=field_aliases.get("failed_requests", ())),
        "retry_count": find_column(columns, RETRY_COUNT_KEYS, aliases=field_aliases.get("retry_count", ())),
        "disk_read_mbps": find_column(columns, DISK_READ_KEYS, aliases=field_aliases.get("disk_read_mbps", ())),
        "disk_write_mbps": find_column(columns, DISK_WRITE_KEYS, aliases=field_aliases.get("disk_write_mbps", ())),
        "iops": find_column(columns, IOPS_KEYS, aliases=field_aliases.get("iops", ())),
        "io_wait_ms": find_column(columns, IO_WAIT_KEYS, aliases=field_aliases.get("io_wait_ms", ())),
    }

    normalized = pd.DataFrame(index=df.index)
    used_sources = set()
    for target, source in mapping.items():
        if source is None:
            normalized[target] = np.nan
        elif target == "timestamp":
            used_sources.add(source)
            normalized[target] = pd.to_datetime(df[source], errors="coerce")
        else:
            used_sources.add(source)
            normalized[target] = pd.to_numeric(df[source], errors="coerce")

    # 除了内置核心指标外，保留场景 sheet 中其他数值列，作为动态扩展指标参与通用分析。
    for column in columns:
        if column in used_sources:
            continue
        if is_numeric_like(df[column]):
            normalized[dynamic_metric_key(column)] = pd.to_numeric(df[column], errors="coerce")

    if normalized["memory_percent"].isna().all() and not normalized["memory_mb"].isna().all():
        total_memory = normalized["total_memory_mb"].replace(0, np.nan)
        normalized["memory_percent"] = normalized["memory_mb"] / total_memory * 100

    normalized["scene"] = scene_name
    normalized["source"] = source_name
    normalized = normalized.dropna(subset=["timestamp"], how="all")
    return normalized


def normalize_generic_timeseries(df: pd.DataFrame, group_name: str, source_name: str, field_aliases: dict[str, tuple[str, ...]]) -> pd.DataFrame:
    columns = [str(column) for column in df.columns]
    df = df.copy()
    df.columns = columns

    timestamp_column = find_column(columns, TIME_KEYS, aliases=field_aliases.get("timestamp", ()))
    normalized = pd.DataFrame(index=df.index)
    if timestamp_column is None:
        normalized["timestamp"] = pd.NaT
        used_sources = set()
    else:
        normalized["timestamp"] = pd.to_datetime(df[timestamp_column], errors="coerce")
        used_sources = {timestamp_column}

    for column in columns:
        if column in used_sources:
            continue
        if is_numeric_like(df[column]):
            normalized[dynamic_metric_key(column)] = pd.to_numeric(df[column], errors="coerce")

    normalized["scene"] = group_name
    normalized["source"] = source_name
    normalized = normalized.dropna(subset=["timestamp"], how="all")
    return normalized


@st.cache_data(show_spinner=False)
def load_single_workbook(
    source_name: str,
    uploaded_file: bytes | None,
    field_alias_items: tuple[tuple[str, tuple[str, ...]], ...],
    analysis_mode: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    field_aliases = dict(field_alias_items)
    source: str | BinaryIO = str(SAMPLE_FILE) if uploaded_file is None else BytesIO(uploaded_file)
    workbook = pd.ExcelFile(source)
    if not workbook.sheet_names:
        return pd.DataFrame(), pd.DataFrame()

    system_info = pd.read_excel(workbook, sheet_name=workbook.sheet_names[0])
    system_info.insert(0, "数据源", source_name)
    scenes = []
    for sheet_name in workbook.sheet_names[1:]:
        raw = pd.read_excel(workbook, sheet_name=sheet_name)
        if not raw.empty:
            if analysis_mode == GENERIC_MODE:
                scenes.append(normalize_generic_timeseries(raw, sheet_name, source_name, field_aliases))
            else:
                scenes.append(normalize_scene(raw, sheet_name, source_name, field_aliases))

    data = pd.concat(scenes, ignore_index=True) if scenes else pd.DataFrame()
    return system_info, data


def load_workbooks(
    files: tuple[tuple[str, bytes | None], ...],
    field_aliases: dict[str, tuple[str, ...]],
    analysis_mode: str = PERFORMANCE_MODE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    # 多文件上传时，每个 Excel 文件名作为 source，后续可用于版本/批次对比。
    systems = []
    frames = []
    field_alias_items = tuple(sorted(field_aliases.items()))
    for source_name, payload in files:
        system_info, data = load_single_workbook(source_name, payload, field_alias_items, analysis_mode)
        if not system_info.empty:
            systems.append(system_info)
        if not data.empty:
            frames.append(data)
    system = pd.concat(systems, ignore_index=True) if systems else pd.DataFrame()
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return system, data


def percentile_95(series: pd.Series) -> float:
    return percentile(series, 0.95)


def percentile(series: pd.Series, quantile: float) -> float:
    values = series.dropna()
    return float(values.quantile(quantile)) if not values.empty else np.nan


def iqr(series: pd.Series) -> float:
    values = series.dropna()
    if values.empty:
        return np.nan
    return float(values.quantile(0.75) - values.quantile(0.25))


def coefficient_of_variation(series: pd.Series) -> float:
    values = series.dropna()
    if values.empty:
        return np.nan
    mean = values.mean()
    if mean == 0 or pd.isna(mean):
        return np.nan
    return float(values.std(ddof=0) / mean * 100)


def alert_mask(series: pd.Series, threshold: float, higher_is_worse: bool) -> pd.Series:
    return series > threshold if higher_is_worse else series < threshold


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


def max_continuous_alert_minutes(group: pd.DataFrame, metric: Metric, threshold: float) -> float:
    values = group[["timestamp", metric.key]].dropna().sort_values("timestamp")
    if values.empty:
        return 0.0
    alerts = alert_mask(values[metric.key], threshold, metric.higher_is_worse).to_numpy()
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


def format_value(value: float, unit: str = "") -> str:
    if pd.isna(value):
        return "-"
    if unit in ("个", ""):
        return f"{value:,.0f}{unit}"
    return f"{value:,.2f}{unit}"


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


def summarize(data: pd.DataFrame, thresholds: dict[str, float], metrics: list[Metric]) -> pd.DataFrame:
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
            row[f"{metric.label}均值"] = values.mean()
            row[f"{metric.label}峰值"] = values.max()
            row[f"{metric.label}P90"] = percentile(values, 0.90)
            row[f"{metric.label}P95"] = percentile_95(values)
            row[f"{metric.label}P99"] = percentile(values, 0.99)
            row[f"{metric.label}标准差"] = values.std(ddof=0)
            row[f"{metric.label}IQR"] = iqr(values)
            row[f"{metric.label}变异系数(%)"] = coefficient_of_variation(values)
            slope, _ = linear_slope_per_minute(group, metric.key)
            row[f"{metric.label}趋势斜率/分钟"] = slope
            row[f"{metric.label}峰值发生在"] = format_peak_offset(group, metric.key)
            if metric.key in thresholds:
                mask = alert_mask(values, thresholds[metric.key], metric.higher_is_worse)
                row[f"{metric.label}超阈次数"] = int(mask.sum())
                row[f"{metric.label}超阈占比(%)"] = float(mask.mean() * 100)
                max_minutes = max_continuous_alert_minutes(group, metric, thresholds[metric.key])
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
            row[f"{metric.key}_mean"] = values.mean()
            row[f"{metric.key}_max"] = values.max()
            row[f"{metric.key}_p90"] = percentile(values, 0.90)
            row[f"{metric.key}_p95"] = percentile_95(values)
            row[f"{metric.key}_p99"] = percentile(values, 0.99)
            row[f"{metric.key}_std"] = values.std(ddof=0)
            row[f"{metric.key}_iqr"] = iqr(values)
            row[f"{metric.key}_cv"] = coefficient_of_variation(values)
            row[f"{metric.key}_slope"] = linear_slope_per_minute(group, metric.key)[0]
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


def alert_continuity_summary(data: pd.DataFrame, thresholds: dict[str, float], metrics: list[Metric]) -> pd.DataFrame:
    rows = []
    for (source, scene), group in data.groupby(["source", "scene"], sort=False):
        for metric in metrics:
            if metric.key not in thresholds or metric.key not in group:
                continue
            values = group[metric.key].dropna()
            if values.empty:
                continue
            mask = alert_mask(values, thresholds[metric.key], metric.higher_is_worse)
            alert_count = int(mask.sum())
            if alert_count == 0:
                continue
            max_minutes = max_continuous_alert_minutes(group, metric, thresholds[metric.key])
            rows.append(
                {
                    "数据源": source,
                    "场景": scene,
                    "指标": metric.label,
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
) -> pd.DataFrame:
    alerts = alert_continuity_summary(data, thresholds, metrics)
    leaks = leak_analysis(data, slope_threshold)
    efficiency = resource_efficiency_analysis(data)
    rows = []
    for (source, scene), group in data.groupby(["source", "scene"], sort=False):
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
        error_per_thousand = efficiency_row["每千请求错误数"].iloc[0] if not efficiency_row.empty else np.nan
        response_p95 = efficiency_row["响应时间P95(ms)"].iloc[0] if not efficiency_row.empty else np.nan
        fps_p95 = efficiency_row["FPS P95"].iloc[0] if not efficiency_row.empty else np.nan

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


def build_conclusions(data: pd.DataFrame, thresholds: dict[str, float], slope_threshold: float, metrics: list[Metric]) -> list[str]:
    conclusions = []
    if data.empty:
        return ["未读取到可分析的场景数据。"]
    alerts = count_alerts(data, thresholds, metrics)
    if alerts:
        conclusions.append(f"当前阈值下共有 {alerts} 个超阈采样点，建议优先查看“异常”页定位时间和场景。")
        alert_summary = alert_continuity_summary(data, thresholds, metrics)
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


def build_generic_conclusions(data: pd.DataFrame, thresholds: dict[str, float], metrics: list[Metric]) -> list[str]:
    conclusions = []
    if data.empty:
        return ["未读取到可分析的时序数据。"]
    alerts = count_alerts(data, thresholds, metrics)
    if alerts:
        conclusions.append(f"当前阈值下共有 {alerts} 个超阈采样点，建议查看“异常”页定位时间和分组。")
        alert_summary = alert_continuity_summary(data, thresholds, metrics)
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
    config_table: pd.DataFrame | None = None,
    config_notes: list[str] | None = None,
) -> str:
    summary = summarize(data, thresholds, metrics)
    leaks = leak_analysis(data, slope_threshold)
    trends = trend_analysis(data, metrics)
    alert_summary = alert_continuity_summary(data, thresholds, metrics)
    efficiency = resource_efficiency_analysis(data)
    decisions = scene_decision_analysis(data, thresholds, metrics, slope_threshold)
    gate_status, gate_rules = release_gate_analysis(
        decisions,
        max_allowed_level="中风险",
        fail_on_leak=True,
        fail_on_any_alert=False,
        fail_on_errors=False,
    )
    stability = stability_score_analysis(decisions)
    bottlenecks = bottleneck_hints(data, thresholds, metrics)
    conclusions = build_conclusions(data, thresholds, slope_threshold, metrics)
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
        "- 超阈次数：指标值大于侧边栏阈值的采样点数量",
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


def build_generic_report_markdown(data: pd.DataFrame, thresholds: dict[str, float], metrics: list[Metric], group_label: str) -> str:
    summary = summarize(data, thresholds, metrics)
    trends = trend_analysis(data, metrics)
    alert_summary = alert_continuity_summary(data, thresholds, metrics)
    conclusions = build_generic_conclusions(data, thresholds, metrics)
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
        "## 全指标趋势斜率",
        "",
        dataframe_to_markdown(trends) if not trends.empty else "无趋势斜率数据。",
        "",
        "## 分析口径",
        "",
        f"- {group_label}：由 Excel sheet 名提供。",
        "- 均值 / 峰值 / P90 / P95 / P99：用于观察整体水平、高水位和尾部风险。",
        "- 超阈占比：超阈采样点数量 / 有效采样点数量。",
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


def parse_json_config(uploaded_file: object | None) -> dict:
    if uploaded_file is None:
        return {}
    try:
        payload = uploaded_file.getvalue()
        return json.loads(payload.decode("utf-8-sig"))
    except Exception as exc:
        st.sidebar.warning(f"配置文件读取失败：{exc}")
        return {}


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


def build_settings_config(
    field_aliases: dict[str, tuple[str, ...]],
    slope_threshold: float,
    warmup_minutes: float,
    metrics: list[Metric],
    thresholds: dict[str, float],
    analysis_mode: str = PERFORMANCE_MODE,
    group_label: str = "场景",
) -> dict:
    return {
        "version": 1,
        "mode": "generic_timeseries" if analysis_mode == GENERIC_MODE else "performance",
        "fields": {field: list(aliases) for field, aliases in field_aliases.items() if aliases},
        "analysis": {
            "mode": "generic_timeseries" if analysis_mode == GENERIC_MODE else "performance",
            "group_label": group_label,
            "memory_leak_slope_threshold": slope_threshold,
            "warmup_minutes": warmup_minutes,
        },
        "metrics": {
            metric.key: {
                "label": metric.label,
                "threshold": thresholds.get(metric.key, metric.default_threshold),
                "direction": "higher" if metric.higher_is_worse else "lower",
            }
            for metric in metrics
        },
    }


def config_to_json_bytes(config: dict) -> bytes:
    return json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8-sig")


def render_system_info(system_info: pd.DataFrame) -> None:
    st.subheader("系统信息")
    if system_info.empty:
        st.info("未读取到系统信息 sheet。")
        return
    st.dataframe(system_info, use_container_width=True, hide_index=True)


def render_overview(data: pd.DataFrame, thresholds: dict[str, float], metrics: list[Metric]) -> None:
    st.subheader("概览")
    cols = st.columns(5)
    cols[0].metric("场景数", data["scene"].nunique())
    cols[1].metric("样本数", f"{len(data):,}")
    cols[2].metric("CPU峰值", format_value(data["cpu_percent"].max(), "%") if "cpu_percent" in data else "-")
    cols[3].metric("内存峰值", format_value(data["memory_mb"].max(), "MB") if "memory_mb" in data else "-")
    cols[4].metric("告警点", f"{count_alerts(data, thresholds, metrics):,}")

    summary = summarize(data, thresholds, metrics)
    st.dataframe(summary, use_container_width=True, hide_index=True)

    alert_summary = alert_continuity_summary(data, thresholds, metrics)
    if not alert_summary.empty:
        st.markdown("**告警持续性摘要**")
        st.dataframe(
            alert_summary.drop(columns=["最大连续超阈(分钟)"], errors="ignore"),
            use_container_width=True,
            hide_index=True,
        )


def count_alerts(data: pd.DataFrame, thresholds: dict[str, float], metrics: list[Metric]) -> int:
    total = 0
    for metric in metrics:
        if metric.key in data and metric.key in thresholds:
            if metric.higher_is_worse:
                total += int((data[metric.key] > thresholds[metric.key]).sum())
            else:
                total += int((data[metric.key] < thresholds[metric.key]).sum())
    return total


def with_display_label(data: pd.DataFrame) -> pd.DataFrame:
    result = data.copy()
    if result["source"].nunique() > 1:
        result["display_scene"] = result["source"].astype(str) + " / " + result["scene"].astype(str)
    else:
        result["display_scene"] = result["scene"].astype(str)
    return result


def render_trend(data: pd.DataFrame, selected_scenes: list[str], selected_metrics: list[str], thresholds: dict[str, float], metrics: list[Metric]) -> None:
    st.subheader("趋势分析")
    with st.expander("口径说明", expanded=False):
        st.write("- 趋势图按采样时间绘制，适合观察尖峰、持续高水位和随时间爬升。")
        st.write("- 红色虚线是侧边栏配置的告警阈值。")
        st.write("- 多数据源上传时，同名场景会按“数据源 / 场景”区分。")
    filtered = data[data["scene"].isin(selected_scenes)].copy()
    if filtered.empty:
        st.warning("当前筛选条件下没有数据。")
        return
    filtered = with_display_label(filtered)

    for metric_key in selected_metrics:
        metric = metric_by_key(metrics, metric_key)
        if filtered[metric.key].dropna().empty:
            continue

        fig = px.line(
            filtered,
            x="timestamp",
            y=metric.key,
            color="display_scene",
            markers=False,
            labels={"timestamp": "时间", metric.key: f"{metric.label}({metric.unit})", "display_scene": "场景"},
            title=f"{metric.label}时间趋势",
        )
        if metric.key in thresholds:
            fig.add_hline(
                y=thresholds[metric.key],
                line_dash="dash",
                line_color="#d62728",
                annotation_text="阈值",
            )
        fig.update_layout(height=360, margin=dict(l=20, r=20, t=50, b=20))
        st.plotly_chart(fig, use_container_width=True)


def render_comparison(data: pd.DataFrame, selected_scenes: list[str], metrics: list[Metric]) -> None:
    st.subheader("场景对比")
    filtered = with_display_label(data[data["scene"].isin(selected_scenes)].copy())
    long_rows = []
    for scene, group in filtered.groupby("display_scene", sort=False):
        for metric in metrics:
            values = group[metric.key].dropna()
            if values.empty:
                continue
            long_rows.append({"场景": scene, "指标": metric.label, "统计": "均值", "值": values.mean()})
            long_rows.append({"场景": scene, "指标": metric.label, "统计": "峰值", "值": values.max()})
            long_rows.append({"场景": scene, "指标": metric.label, "统计": "P90", "值": percentile(values, 0.90)})
            long_rows.append({"场景": scene, "指标": metric.label, "统计": "P95", "值": percentile_95(values)})
            long_rows.append({"场景": scene, "指标": metric.label, "统计": "P99", "值": percentile(values, 0.99)})
            long_rows.append({"场景": scene, "指标": metric.label, "统计": "标准差", "值": values.std(ddof=0)})
            long_rows.append({"场景": scene, "指标": metric.label, "统计": "IQR", "值": iqr(values)})
            long_rows.append({"场景": scene, "指标": metric.label, "统计": "变异系数", "值": coefficient_of_variation(values)})
            long_rows.append({"场景": scene, "指标": metric.label, "统计": "趋势斜率", "值": linear_slope_per_minute(group, metric.key)[0]})

    compare = pd.DataFrame(long_rows)
    if compare.empty:
        st.info("没有可用于对比的数值指标。")
        return

    metric_label = st.selectbox(
        "对比指标",
        sorted(compare["指标"].unique()),
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
    chart_data = compare[(compare["指标"] == metric_label) & (compare["统计"] == stat)]
    fig = px.bar(chart_data, x="场景", y="值", color="场景", title=f"{metric_label}{stat}对比")
    fig.update_layout(height=360, showlegend=False, margin=dict(l=20, r=20, t=50, b=20))
    st.plotly_chart(fig, use_container_width=True)


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

    metric = st.selectbox(
        "分布指标",
        available,
        format_func=lambda item: item.label,
        help="箱线图用于观察该指标在不同场景中的分布、离群点和波动范围。",
    )
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
    st.plotly_chart(fig, use_container_width=True)

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
        st.plotly_chart(heatmap, use_container_width=True)


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

    metric_column = st.selectbox(
        "效率指标",
        available,
        help="效率指标会把资源消耗归一化到吞吐或并发口径，更适合判断资源上涨是否真的退化。",
    )
    chart_data = efficiency.copy()
    chart_data["场景标识"] = chart_data["数据源"].astype(str) + " / " + chart_data["场景"].astype(str)
    fig = px.bar(chart_data, x="场景标识", y=metric_column, color="数据源", title=f"{metric_column} 对比")
    fig.update_layout(height=380, margin=dict(l=20, r=20, t=50, b=20))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("**吞吐-资源散点图**")
    scatter_y_options = [
        column
        for column in ["CPU P95", "内存峰值(MB)", "响应时间P95(ms)", "FPS P95", "GC耗时P95(ms)", "失败率(%)"]
        if column in efficiency and efficiency[column].notna().any()
    ]
    if "平均吞吐" in efficiency and efficiency["平均吞吐"].notna().any() and scatter_y_options:
        scatter_y = st.selectbox(
            "散点图纵轴",
            scatter_y_options,
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
        st.plotly_chart(scatter, use_container_width=True)


def render_decision(data: pd.DataFrame, selected_scenes: list[str], thresholds: dict[str, float], metrics: list[Metric], slope_threshold: float) -> None:
    st.subheader("决策分析")
    filtered = data[data["scene"].isin(selected_scenes)].copy()
    if filtered.empty:
        st.warning("当前筛选条件下没有数据。")
        return

    with st.expander("口径说明", expanded=False):
        st.write("- 场景风险评级会综合超阈占比、最长连续超阈、内存趋势、失败率、响应时间和 FPS 等规则。")
        st.write("- 发布门禁用于把风险评级转换成通过/不通过，适合发版检查或测试准入。")
        st.write("- 容量估算是基于当前样本的单位资源成本做线性外推，正式配置结论仍需要目标机器实测。")

    decisions = scene_decision_analysis(filtered, thresholds, metrics, slope_threshold)
    st.markdown("**场景风险评级**")
    if decisions.empty:
        st.info("没有可用于风险评级的数据。")
        return
    st.dataframe(decisions, use_container_width=True, hide_index=True)

    matrix = risk_matrix_data(decisions)
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
        st.plotly_chart(risk_fig, use_container_width=True)

    radar_data = radar_profile_data(filtered, decisions, thresholds)
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
        st.plotly_chart(radar_fig, use_container_width=True)

    st.markdown("**发布门禁**")
    col1, col2, col3, col4 = st.columns(4)
    max_allowed_level = col1.selectbox(
        "允许最高风险等级",
        ["低风险", "中风险", "高风险"],
        index=1,
        help="如果某个场景的风险等级高于这里选择的等级，发布门禁会判定失败。",
    )
    fail_on_leak = col2.checkbox(
        "疑似泄漏即失败",
        value=True,
        help="勾选后，只要任意场景被内存趋势检测标记为疑似泄漏，发布门禁就失败。",
    )
    fail_on_any_alert = col3.checkbox(
        "任意超阈即失败",
        value=False,
        help="勾选后，只要任意指标出现过超阈采样点，发布门禁就失败。适合严格准入场景。",
    )
    fail_on_errors = col4.checkbox(
        "请求失败即失败",
        value=False,
        help="勾选后，只要请求失败率大于 0，发布门禁就失败。需要 Excel 中有请求数和失败请求数字段。",
    )
    gate_status, gate_rules = release_gate_analysis(decisions, max_allowed_level, fail_on_leak, fail_on_any_alert, fail_on_errors)
    st.metric("发布门禁", gate_status)
    st.dataframe(gate_rules, use_container_width=True, hide_index=True)

    st.markdown("**稳定性评分**")
    stability = stability_score_analysis(decisions)
    st.dataframe(stability, use_container_width=True, hide_index=True)

    st.markdown("**瓶颈提示**")
    bottlenecks = bottleneck_hints(filtered, thresholds, metrics)
    st.dataframe(bottlenecks, use_container_width=True, hide_index=True)

    st.markdown("**容量估算**")
    col5, col6, col7 = st.columns(3)
    test_cpu_cores = col5.number_input(
        "容量估算测试机CPU核数",
        min_value=1,
        value=8,
        step=1,
        help="采集这批性能数据时测试机的逻辑 CPU 核数，用于把 CPU% 换算成核心需求。",
    )
    target_cpu_utilization = col6.number_input(
        "容量估算目标CPU上限(%)",
        min_value=30.0,
        max_value=95.0,
        value=70.0,
        step=5.0,
        help="希望目标机器长期运行时 CPU 不超过的利用率。值越低，估算出的 CPU 核数越保守。",
    )
    reserved_memory = col7.number_input(
        "容量估算系统预留内存(GB)",
        min_value=0.0,
        value=2.0,
        step=0.5,
        help="为操作系统、后台进程和运行时预留的内存，会叠加到应用内存需求上。",
    )
    throughput_text = st.text_input("目标吞吐列表", value="50,100,200", help="多个目标吞吐用英文逗号分隔，口径沿用效率页自动识别的 QPS/TPS/任务数/请求数。")
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
        st.plotly_chart(curve, use_container_width=True)


def render_alerts(data: pd.DataFrame, selected_scenes: list[str], thresholds: dict[str, float], metrics: list[Metric]) -> None:
    st.subheader("异常点")
    with st.expander("口径说明", expanded=False):
        st.write("- 异常点由侧边栏阈值和告警方向决定。")
        st.write("- 对“越高越差”的指标，值大于阈值算异常；对“越低越差”的指标，值小于阈值算异常。")
    filtered = data[data["scene"].isin(selected_scenes)].copy()
    alert_frames = []
    for metric in metrics:
        if metric.key not in thresholds:
            continue
        mask = filtered[metric.key] > thresholds[metric.key] if metric.higher_is_worse else filtered[metric.key] < thresholds[metric.key]
        alert = filtered[mask][["timestamp", "source", "scene", metric.key]].copy()
        if alert.empty:
            continue
        alert["指标"] = metric.label
        alert["阈值"] = thresholds[metric.key]
        alert["值"] = alert[metric.key]
        alert_frames.append(alert[["timestamp", "source", "scene", "指标", "值", "阈值"]])

    if not alert_frames:
        st.success("当前阈值下没有异常点。")
        return

    alerts = pd.concat(alert_frames, ignore_index=True).sort_values("timestamp")
    st.dataframe(alerts, use_container_width=True, hide_index=True)
    st.download_button(
        "下载异常点 CSV",
        alerts.to_csv(index=False).encode("utf-8-sig"),
        file_name="resource_alerts.csv",
        mime="text/csv",
    )


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
    baseline = st.selectbox(
        "基准场景",
        list(stats["display_scene"]),
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
        index=3,
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

    metric_label = st.selectbox(
        "增长率图表指标",
        [metric.label for metric in metrics],
        help="选择要绘制增长率柱状图的指标。",
    )
    chart_data = result[result["指标"] == metric_label]
    fig = px.bar(chart_data, x="场景", y="相对增长率(%)", color="场景", title=f"{metric_label}相对 {baseline} 的增长率")
    fig.add_hline(y=0, line_color="#666", line_width=1)
    fig.update_layout(height=360, showlegend=False, margin=dict(l=20, r=20, t=50, b=20))
    st.plotly_chart(fig, use_container_width=True)


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
        st.plotly_chart(fig, use_container_width=True)

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
    metric = st.selectbox(
        "版本对比指标",
        metrics,
        format_func=lambda item: item.label,
        help="选择要在不同 Excel 文件之间对比的指标。上传文件名会作为版本/批次标识。",
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
        "版本对比口径",
        list(stat_labels),
        index=3,
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
    baseline_source = st.selectbox(
        "基准数据源",
        sources,
        help="选择作为基准版本或基准批次的数据源。其他数据源会和它逐场景比较。",
    )
    regression_threshold = st.number_input(
        "退化判定阈值(%)",
        min_value=0.0,
        value=15.0,
        step=5.0,
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
        st.plotly_chart(heatmap, use_container_width=True)

    long_data = stats[["source", "scene", column]].rename(columns={column: "值"})
    fig = px.bar(long_data, x="scene", y="值", color="source", barmode="group", title=f"不同数据源 {metric.label}{stat_labels[stat_name]} 对比")
    fig.update_layout(height=380, margin=dict(l=20, r=20, t=50, b=20))
    st.plotly_chart(fig, use_container_width=True)


def render_configuration_recommendation(data: pd.DataFrame, slope_threshold: float) -> tuple[pd.DataFrame, list[str]]:
    st.subheader("最低运行配置建议")
    st.caption("该结论基于当前筛选数据推导，适合做初步配置建议；正式发布最低配置前，仍建议在目标低配机器上实测验证。")

    col1, col2, col3 = st.columns(3)
    test_cpu_cores = col1.number_input(
        "测试机CPU核数",
        min_value=1,
        value=8,
        step=1,
        help="采集性能数据时测试机的逻辑 CPU 核数，用于把 CPU P95 换算成目标机器核心需求。",
    )
    target_cpu_utilization = col2.number_input(
        "目标CPU利用率上限(%)",
        min_value=30.0,
        max_value=95.0,
        value=70.0,
        step=5.0,
        help="希望目标机器长期运行时 CPU 不超过的利用率。通常 70% 是比较通用的保守值。",
    )
    minimum_cpu_cores = col3.number_input(
        "最低CPU核数下限",
        min_value=1,
        value=2,
        step=1,
        help="无论公式估算结果多低，最低配置都不会低于这个核数。",
    )

    col4, col5, col6 = st.columns(3)
    system_reserved_memory_gb = col4.number_input(
        "系统和后台预留内存(GB)",
        min_value=0.0,
        value=2.0,
        step=0.5,
        help="为操作系统、后台服务、运行时和缓存预留的内存，会叠加到应用内存峰值上。",
    )
    minimum_memory_gb = col5.number_input(
        "最低内存下限(GB)",
        min_value=1,
        value=4,
        step=1,
        help="无论公式估算结果多低，最低配置都不会低于这个内存容量。",
    )
    minimum_free_disk_gb = col6.number_input(
        "最低磁盘剩余空间(GB)",
        min_value=1,
        value=10,
        step=1,
        help="给安装包、日志、缓存、临时文件和运行数据预留的最低剩余磁盘空间。",
    )

    recommendation_factor = st.slider(
        "推荐配置安全系数",
        min_value=1.0,
        max_value=2.5,
        value=1.5,
        step=0.1,
        help="推荐配置会在最低配置基础上乘以该系数。系数越高，余量越大。",
    )
    config_table, notes = configuration_recommendation(
        data,
        int(test_cpu_cores),
        float(target_cpu_utilization),
        int(minimum_cpu_cores),
        float(system_reserved_memory_gb),
        int(minimum_memory_gb),
        int(minimum_free_disk_gb),
        float(recommendation_factor),
        slope_threshold,
    )

    st.dataframe(config_table, use_container_width=True, hide_index=True)

    st.markdown("**推导说明**")
    for note in notes:
        st.write(f"- {note}")

    st.markdown("**是否需要更多数据指标**")
    st.write("- 如果要更准确估算 CPU 核数，最好补充每核 CPU 使用率、进程 CPU 时间、任务吞吐量、响应时间或队列长度。只有总 CPU% 时，只能按总体占用近似换算。")
    st.write("- 如果软件有并发、批处理或服务端请求，建议补充并发数、TPS/QPS、任务量、数据规模，才能把配置结论和业务容量绑定。")
    st.write("- 如果 IO 可能是瓶颈，建议补充磁盘读写吞吐、IOPS、IO 等待时间、网络吞吐和错误重试次数。")
    st.write("- 如果需要正式发布最低配置，建议在至少一台目标低配机器上跑关键场景和长稳场景验证。")
    return config_table, notes


def render_report(
    data: pd.DataFrame,
    thresholds: dict[str, float],
    slope_threshold: float,
    metrics: list[Metric],
    config_table: pd.DataFrame | None = None,
    config_notes: list[str] | None = None,
) -> None:
    st.subheader("测试结论与报告导出")
    conclusions = build_conclusions(data, thresholds, slope_threshold, metrics)
    for item in conclusions:
        st.write(f"- {item}")

    markdown_report = build_report_markdown(data, thresholds, slope_threshold, metrics, config_table, config_notes)
    html_report = build_report_html(markdown_report)
    st.download_button(
        "下载 Markdown 报告",
        markdown_report.encode("utf-8-sig"),
        file_name="resource_report.md",
        mime="text/markdown",
    )
    st.download_button(
        "下载 HTML 报告",
        html_report.encode("utf-8-sig"),
        file_name="resource_report.html",
        mime="text/html",
    )
    st.caption("需要 PDF 时，可打开 HTML 报告后使用浏览器打印为 PDF。")


def render_generic_report(data: pd.DataFrame, thresholds: dict[str, float], metrics: list[Metric], group_label: str) -> None:
    st.subheader("分析报告导出")
    conclusions = build_generic_conclusions(data, thresholds, metrics)
    for item in conclusions:
        st.write(f"- {item}")

    markdown_report = build_generic_report_markdown(data, thresholds, metrics, group_label)
    html_report = build_report_html(markdown_report)
    st.download_button(
        "下载 Markdown 报告",
        markdown_report.encode("utf-8-sig"),
        file_name="timeseries_report.md",
        mime="text/markdown",
    )
    st.download_button(
        "下载 HTML 报告",
        html_report.encode("utf-8-sig"),
        file_name="timeseries_report.html",
        mime="text/html",
    )
    st.caption("需要 PDF 时，可打开 HTML 报告后使用浏览器打印为 PDF。")


def ensure_sample_file() -> None:
    if not SAMPLE_FILE.exists():
        st.error("未找到示例数据。请先运行 `python generate_sample_data.py`。")
        st.stop()


def main() -> None:
    st.set_page_config(page_title="应用资源消耗分析", page_icon="📈", layout="wide")
    st.title("应用资源消耗分析")

    with st.sidebar:
        st.header("数据源")
        uploaded_files = st.file_uploader(
            "上传 Excel 文件",
            type=["xlsx", "xls"],
            accept_multiple_files=True,
            help="可以一次上传多个 Excel。文件名会作为数据源名称，用于版本对比和多批次对比。",
        )
        settings_file = st.file_uploader(
            "导入分析配置",
            type=["json"],
            help="可选。导入字段别名、阈值、告警方向、泄漏阈值和稳定区间。配置只覆盖能匹配上的指标，其他指标继续使用自动默认值。",
        )
        imported_config = parse_json_config(settings_file)
        if imported_config:
            st.caption("已加载分析配置；未匹配的指标会自动忽略。")
        default_mode = config_analysis_mode(imported_config)
        analysis_mode = st.selectbox(
            "分析模式",
            ANALYSIS_MODES,
            index=ANALYSIS_MODES.index(default_mode),
            help="应用性能模式会识别 CPU、内存、QPS 等性能语义；通用时序模式只识别时间戳和数值指标，适合温度、压力、质量测量等通用采样记录。",
        )
        group_label = st.text_input(
            "分组名称",
            value=config_analysis_text(imported_config, "group_label", "分组" if analysis_mode == GENERIC_MODE else "场景"),
            help="用于描述 Excel 中每个数据 sheet 的含义，例如场景、设备、工况、批次或实验组。",
        )
        use_sample = not uploaded_files
        if use_sample:
            ensure_sample_file()
            st.caption(f"当前使用示例数据：{SAMPLE_FILE}")
        else:
            st.caption(f"已上传 {len(uploaded_files)} 个 Excel 文件。")
        st.caption("读取规则：第一个 sheet 为系统信息，其余 sheet 名作为场景名。")

        with st.expander("自定义字段映射"):
            st.caption("多个别名用英文逗号分隔。系统会先匹配这里配置的字段名，再使用内置规则自动识别。")
            field_aliases = {
                field: parse_aliases(
                    st.text_input(
                        label,
                        value=",".join(config_field_aliases(imported_config, field)),
                        placeholder="例如：字段A,字段B",
                        help=f"如果采集工具导出的 {label} 表头无法被自动识别，可以在这里填写额外别名，多个别名用英文逗号分隔。",
                    )
                )
                for field, (label, _) in MAPPING_FIELDS.items()
            }

        slope_threshold = st.number_input(
            "内存疑似泄漏斜率阈值(MB/分钟)",
            min_value=0.0,
            value=config_analysis_value(imported_config, "memory_leak_slope_threshold", 2.0),
            step=0.5,
            help="内存线性增长斜率达到该值，并且趋势较明显时，会标记为疑似泄漏。",
        )

        st.header("稳定区间")
        warmup_minutes = st.number_input(
            "排除每个场景前 N 分钟",
            min_value=0.0,
            value=config_analysis_value(imported_config, "warmup_minutes", 0.0),
            step=0.5,
            help="用于排除启动预热、缓存加载等早期尖峰。裁剪会按数据源 + 场景分别计算，不修改原始 Excel。",
        )

    if use_sample:
        files = (("示例数据", None),)
    else:
        files = tuple((file.name, file.getvalue()) for file in uploaded_files)

    # 加载 Excel 后先得到完整原始采样数据，再按稳定区间做分析视图。
    system_info, raw_data = load_workbooks(files, field_aliases, analysis_mode)
    data = apply_stable_window(raw_data, warmup_minutes)
    if data.empty:
        st.warning("未读取到场景数据。请确认第一个 sheet 为系统信息，其余 sheet 分别为轻载、重载等场景采样数据。")
        render_system_info(system_info)
        return

    sources = list(data["source"].dropna().unique())
    scenes = list(data["scene"].dropna().unique())
    # 指标发现发生在数据加载之后：性能模式核心指标优先；通用模式中所有数值列都是动态指标。
    metrics = discover_metrics(data)
    with st.sidebar:
        st.header("阈值")
        st.caption("核心指标使用内置默认阈值；动态扩展指标默认使用当前数据 P95。可导入 JSON 配置覆盖阈值和方向。")
        thresholds = {}
        configured_metrics = []
        metric_config_count = sum(1 for metric in metrics if metric_config_entry(imported_config, metric))
        with st.expander("阈值配置", expanded=not imported_config):
            threshold_display = st.radio(
                "显示方式",
                ["配置命中指标", "全部指标"],
                index=0 if imported_config and metric_config_count else 1,
                horizontal=True,
                help="导入配置后可以只显示配置文件命中的指标；未显示的指标仍会使用导入值或自动默认值参与分析。",
            )
            if imported_config:
                st.caption(f"当前数据识别到 {len(metrics)} 个指标，配置命中 {metric_config_count} 个。")
            for metric in metrics:
                configured_metric = configured_metric_from_import(imported_config, metric)
                threshold_value = threshold_from_import(imported_config, metric)
                show_metric_controls = threshold_display == "全部指标" or bool(metric_config_entry(imported_config, metric))
                if show_metric_controls:
                    direction = st.selectbox(
                        f"{metric.label} 告警方向",
                        ["越高越差", "越低越差"],
                        index=0 if configured_metric.higher_is_worse else 1,
                        key=f"direction_{metric.key}",
                        help="例如 CPU、内存、响应时间通常越高越差；FPS、成功率、QPS 在某些场景下可能越低越差。",
                    )
                    configured_metric = replace(configured_metric, higher_is_worse=direction == "越高越差")
                    threshold_value = st.number_input(
                        configured_metric.threshold_label,
                        min_value=0.0,
                        value=float(threshold_value),
                        step=1.0,
                        key=f"threshold_{metric.key}",
                        help="用于异常点、超阈次数、超阈占比、最大连续超阈和趋势图阈值线。不会修改原始数据。",
                    )
                configured_metrics.append(configured_metric)
                thresholds[metric.key] = threshold_value
        metrics = configured_metrics

        current_config = build_settings_config(field_aliases, float(slope_threshold), float(warmup_minutes), metrics, thresholds, analysis_mode, group_label)
        st.download_button(
            "导出当前分析配置",
            config_to_json_bytes(current_config),
            file_name="perf_analyzer_config.json",
            mime="application/json",
            help="导出当前字段别名、分析参数、阈值和告警方向。下次可直接导入复用；不同数据集只会应用能匹配上的指标。",
        )

        st.header("筛选")
        selected_sources = st.multiselect(
            "数据源",
            sources,
            default=sources,
            help="选择要参与分析的数据源。多文件上传时，每个文件名就是一个数据源。",
        )
        selected_scenes = st.multiselect(
            group_label,
            scenes,
            default=scenes,
            help=f"选择要参与分析的{group_label}。名称来自 Excel 的 sheet 名。",
        )
        available_metrics = [metric for metric in metrics if metric.key in data and not data[metric.key].dropna().empty]
        selected_metrics = st.multiselect(
            "趋势指标",
            [metric.key for metric in available_metrics],
            default=[metric.key for metric in available_metrics[:3]],
            format_func=lambda key: metric_by_key(metrics, key).label,
            help="选择趋势页要绘制的指标。这里不影响概览、报告和其他统计表。",
        )

    filtered_data = data[data["source"].isin(selected_sources) & data["scene"].isin(selected_scenes)].copy()
    if filtered_data.empty:
        st.warning("当前筛选条件下没有数据。")
        return

    config_table = pd.DataFrame()
    config_notes: list[str] = []

    if analysis_mode == GENERIC_MODE:
        tabs = st.tabs(["概览", "趋势", "对比", "基准增长", "版本对比", "分布", "异常", "报告", "元信息", "原始数据"])
        with tabs[0]:
            render_overview(filtered_data, thresholds, metrics)
        with tabs[1]:
            render_trend(filtered_data, selected_scenes, selected_metrics, thresholds, metrics)
        with tabs[2]:
            render_comparison(filtered_data, selected_scenes, metrics)
        with tabs[3]:
            render_baseline_growth(filtered_data, selected_scenes, metrics)
        with tabs[4]:
            render_version_compare(filtered_data, selected_scenes, metrics)
        with tabs[5]:
            render_distribution(filtered_data, selected_scenes, metrics)
        with tabs[6]:
            render_alerts(filtered_data, selected_scenes, thresholds, metrics)
        with tabs[7]:
            render_generic_report(filtered_data, thresholds, metrics, group_label)
        with tabs[8]:
            selected_system = system_info[system_info["数据源"].isin(selected_sources)] if "数据源" in system_info else system_info
            render_system_info(selected_system)
        with tabs[9]:
            filtered = filtered_data.copy()
            st.dataframe(filtered, use_container_width=True, hide_index=True)
            st.download_button(
                "下载当前筛选数据 CSV",
                filtered.to_csv(index=False).encode("utf-8-sig"),
                file_name="timeseries_filtered.csv",
                mime="text/csv",
            )
    else:
        tabs = st.tabs(["概览", "趋势", "对比", "配置建议", "基准增长", "泄漏检测", "版本对比", "效率", "决策", "分布", "异常", "报告", "系统信息", "原始数据"])
        with tabs[0]:
            render_overview(filtered_data, thresholds, metrics)
        with tabs[1]:
            render_trend(filtered_data, selected_scenes, selected_metrics, thresholds, metrics)
        with tabs[2]:
            render_comparison(filtered_data, selected_scenes, metrics)
        with tabs[3]:
            config_table, config_notes = render_configuration_recommendation(filtered_data, slope_threshold)
        with tabs[4]:
            render_baseline_growth(filtered_data, selected_scenes, metrics)
        with tabs[5]:
            render_leak_detection(filtered_data, selected_scenes, slope_threshold, metrics)
        with tabs[6]:
            render_version_compare(filtered_data, selected_scenes, metrics)
        with tabs[7]:
            render_efficiency(filtered_data, selected_scenes)
        with tabs[8]:
            render_decision(filtered_data, selected_scenes, thresholds, metrics, slope_threshold)
        with tabs[9]:
            render_distribution(filtered_data, selected_scenes, metrics)
        with tabs[10]:
            render_alerts(filtered_data, selected_scenes, thresholds, metrics)
        with tabs[11]:
            if config_table.empty:
                config_table, config_notes = configuration_recommendation(
                    filtered_data,
                    test_cpu_cores=8,
                    target_cpu_utilization=70.0,
                    minimum_cpu_cores=2,
                    system_reserved_memory_gb=2.0,
                    minimum_memory_gb=4,
                    minimum_free_disk_gb=10,
                    recommendation_factor=1.5,
                    slope_threshold=slope_threshold,
                )
            render_report(filtered_data, thresholds, slope_threshold, metrics, config_table, config_notes)
        with tabs[12]:
            selected_system = system_info[system_info["数据源"].isin(selected_sources)] if "数据源" in system_info else system_info
            render_system_info(selected_system)
        with tabs[13]:
            filtered = filtered_data.copy()
            st.dataframe(filtered, use_container_width=True, hide_index=True)
            st.download_button(
                "下载当前筛选数据 CSV",
                filtered.to_csv(index=False).encode("utf-8-sig"),
                file_name="resource_metrics_filtered.csv",
                mime="text/csv",
            )


if __name__ == "__main__":
    main()
