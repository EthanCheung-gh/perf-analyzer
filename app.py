from __future__ import annotations

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


@st.cache_data(show_spinner=False)
def load_single_workbook(source_name: str, uploaded_file: bytes | None, field_alias_items: tuple[tuple[str, tuple[str, ...]], ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
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
            scenes.append(normalize_scene(raw, sheet_name, source_name, field_aliases))

    data = pd.concat(scenes, ignore_index=True) if scenes else pd.DataFrame()
    return system_info, data


def load_workbooks(files: tuple[tuple[str, bytes | None], ...], field_aliases: dict[str, tuple[str, ...]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    # 多文件上传时，每个 Excel 文件名作为 source，后续可用于版本/批次对比。
    systems = []
    frames = []
    field_alias_items = tuple(sorted(field_aliases.items()))
    for source_name, payload in files:
        system_info, data = load_single_workbook(source_name, payload, field_alias_items)
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
    conclusions = build_conclusions(data, thresholds, slope_threshold, metrics)
    lines = [
        "# 应用资源消耗分析报告",
        "",
        "## 测试结论",
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
        "- 内存斜率：按时间对内存占用做线性回归，单位 MB/分钟",
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

    metric_label = st.selectbox("对比指标", sorted(compare["指标"].unique()))
    stat = st.radio(
        "统计口径",
        ["均值", "峰值", "P90", "P95", "P99", "标准差", "IQR", "变异系数", "趋势斜率"],
        index=3,
        horizontal=True,
        key="comparison_stat",
    )
    chart_data = compare[(compare["指标"] == metric_label) & (compare["统计"] == stat)]
    fig = px.bar(chart_data, x="场景", y="值", color="场景", title=f"{metric_label}{stat}对比")
    fig.update_layout(height=360, showlegend=False, margin=dict(l=20, r=20, t=50, b=20))
    st.plotly_chart(fig, use_container_width=True)


def render_distribution(data: pd.DataFrame, selected_scenes: list[str], metrics: list[Metric]) -> None:
    st.subheader("分布与相关性")
    filtered = with_display_label(data[data["scene"].isin(selected_scenes)].copy())
    available = [metric for metric in metrics if metric.key in filtered and not filtered[metric.key].dropna().empty]
    if not available:
        st.info("没有可用于分布分析的指标。")
        return

    metric = st.selectbox("分布指标", available, format_func=lambda item: item.label)
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

    metric_column = st.selectbox("效率指标", available)
    chart_data = efficiency.copy()
    chart_data["场景标识"] = chart_data["数据源"].astype(str) + " / " + chart_data["场景"].astype(str)
    fig = px.bar(chart_data, x="场景标识", y=metric_column, color="数据源", title=f"{metric_column} 对比")
    fig.update_layout(height=380, margin=dict(l=20, r=20, t=50, b=20))
    st.plotly_chart(fig, use_container_width=True)


def render_alerts(data: pd.DataFrame, selected_scenes: list[str], thresholds: dict[str, float], metrics: list[Metric]) -> None:
    st.subheader("异常点")
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
    baseline = st.selectbox("基准场景", list(stats["display_scene"]))
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

    metric_label = st.selectbox("增长率图表指标", [metric.label for metric in metrics])
    chart_data = result[result["指标"] == metric_label]
    fig = px.bar(chart_data, x="场景", y="相对增长率(%)", color="场景", title=f"{metric_label}相对 {baseline} 的增长率")
    fig.add_hline(y=0, line_color="#666", line_width=1)
    fig.update_layout(height=360, showlegend=False, margin=dict(l=20, r=20, t=50, b=20))
    st.plotly_chart(fig, use_container_width=True)


def render_leak_detection(data: pd.DataFrame, selected_scenes: list[str], slope_threshold: float, metrics: list[Metric]) -> None:
    st.subheader("内存泄漏与趋势风险")
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
    metric = st.selectbox("版本对比指标", metrics, format_func=lambda item: item.label)
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
    )
    column = f"{metric.key}_{stat_name}"
    if column not in stats:
        st.info("当前指标没有可对比数据。")
        return
    sources = list(stats["source"].dropna().unique())
    baseline_source = st.selectbox("基准数据源", sources)
    regression_threshold = st.number_input("退化判定阈值(%)", min_value=0.0, value=15.0, step=5.0)

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

    long_data = stats[["source", "scene", column]].rename(columns={column: "值"})
    fig = px.bar(long_data, x="scene", y="值", color="source", barmode="group", title=f"不同数据源 {metric.label}{stat_labels[stat_name]} 对比")
    fig.update_layout(height=380, margin=dict(l=20, r=20, t=50, b=20))
    st.plotly_chart(fig, use_container_width=True)


def render_configuration_recommendation(data: pd.DataFrame, slope_threshold: float) -> tuple[pd.DataFrame, list[str]]:
    st.subheader("最低运行配置建议")
    st.caption("该结论基于当前筛选数据推导，适合做初步配置建议；正式发布最低配置前，仍建议在目标低配机器上实测验证。")

    col1, col2, col3 = st.columns(3)
    test_cpu_cores = col1.number_input("测试机CPU核数", min_value=1, value=8, step=1)
    target_cpu_utilization = col2.number_input("目标CPU利用率上限(%)", min_value=30.0, max_value=95.0, value=70.0, step=5.0)
    minimum_cpu_cores = col3.number_input("最低CPU核数下限", min_value=1, value=2, step=1)

    col4, col5, col6 = st.columns(3)
    system_reserved_memory_gb = col4.number_input("系统和后台预留内存(GB)", min_value=0.0, value=2.0, step=0.5)
    minimum_memory_gb = col5.number_input("最低内存下限(GB)", min_value=1, value=4, step=1)
    minimum_free_disk_gb = col6.number_input("最低磁盘剩余空间(GB)", min_value=1, value=10, step=1)

    recommendation_factor = st.slider("推荐配置安全系数", min_value=1.0, max_value=2.5, value=1.5, step=0.1)
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


def ensure_sample_file() -> None:
    if not SAMPLE_FILE.exists():
        st.error("未找到示例数据。请先运行 `python generate_sample_data.py`。")
        st.stop()


def main() -> None:
    st.set_page_config(page_title="应用资源消耗分析", page_icon="📈", layout="wide")
    st.title("应用资源消耗分析")

    with st.sidebar:
        st.header("数据源")
        uploaded_files = st.file_uploader("上传 Excel 文件", type=["xlsx", "xls"], accept_multiple_files=True)
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
                    st.text_input(label, value="", placeholder="例如：字段A,字段B")
                )
                for field, (label, _) in MAPPING_FIELDS.items()
            }

        slope_threshold = st.number_input("内存疑似泄漏斜率阈值(MB/分钟)", min_value=0.0, value=2.0, step=0.5)

        st.header("稳定区间")
        warmup_minutes = st.number_input("排除每个场景前 N 分钟", min_value=0.0, value=0.0, step=0.5)

    if use_sample:
        files = (("示例数据", None),)
    else:
        files = tuple((file.name, file.getvalue()) for file in uploaded_files)

    # 加载 Excel 后先得到完整原始采样数据，再按稳定区间做分析视图。
    system_info, raw_data = load_workbooks(files, field_aliases)
    data = apply_stable_window(raw_data, warmup_minutes)
    if data.empty:
        st.warning("未读取到场景数据。请确认第一个 sheet 为系统信息，其余 sheet 分别为轻载、重载等场景采样数据。")
        render_system_info(system_info)
        return

    sources = list(data["source"].dropna().unique())
    scenes = list(data["scene"].dropna().unique())
    # 指标发现发生在数据加载之后：核心指标优先，其他数值列自动变成动态扩展指标。
    metrics = discover_metrics(data)
    with st.sidebar:
        st.header("阈值")
        st.caption("核心指标使用内置默认阈值；动态扩展指标默认使用当前数据 P95，可按需要调整。")
        thresholds = {}
        configured_metrics = []
        for metric in metrics:
            direction = st.selectbox(
                f"{metric.label} 告警方向",
                ["越高越差", "越低越差"],
                index=0 if metric.higher_is_worse else 1,
                key=f"direction_{metric.key}",
            )
            configured_metric = replace(metric, higher_is_worse=direction == "越高越差")
            configured_metrics.append(configured_metric)
            thresholds[metric.key] = st.number_input(
                configured_metric.threshold_label,
                min_value=0.0,
                value=float(configured_metric.default_threshold),
                step=1.0,
                key=f"threshold_{metric.key}",
            )
        metrics = configured_metrics

        st.header("筛选")
        selected_sources = st.multiselect("数据源", sources, default=sources)
        selected_scenes = st.multiselect("场景", scenes, default=scenes)
        available_metrics = [metric for metric in metrics if metric.key in data and not data[metric.key].dropna().empty]
        selected_metrics = st.multiselect(
            "趋势指标",
            [metric.key for metric in available_metrics],
            default=[metric.key for metric in available_metrics[:3]],
            format_func=lambda key: metric_by_key(metrics, key).label,
        )

    filtered_data = data[data["source"].isin(selected_sources) & data["scene"].isin(selected_scenes)].copy()
    if filtered_data.empty:
        st.warning("当前筛选条件下没有数据。")
        return

    config_table = pd.DataFrame()
    config_notes: list[str] = []

    tabs = st.tabs(["概览", "趋势", "对比", "配置建议", "基准增长", "泄漏检测", "版本对比", "效率", "分布", "异常", "报告", "系统信息", "原始数据"])
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
        render_distribution(filtered_data, selected_scenes, metrics)
    with tabs[9]:
        render_alerts(filtered_data, selected_scenes, thresholds, metrics)
    with tabs[10]:
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
    with tabs[11]:
        selected_system = system_info[system_info["数据源"].isin(selected_sources)] if "数据源" in system_info else system_info
        render_system_info(selected_system)
    with tabs[12]:
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
