from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pandas as pd

from .constants import (
    CONCURRENCY_KEYS,
    CPU_KEYS,
    DISK_READ_KEYS,
    DISK_WRITE_KEYS,
    ERROR_COUNT_KEYS,
    FAILED_REQUEST_KEYS,
    FPS_KEYS,
    GC_COUNT_KEYS,
    GC_TIME_KEYS,
    GENERIC_MODE,
    HANDLE_KEYS,
    HEAP_KEYS,
    IO_KEYS,
    IOPS_KEYS,
    IO_WAIT_KEYS,
    JANK_COUNT_KEYS,
    MEMORY_KEYS,
    MEMORY_PERCENT_KEYS,
    NETWORK_DOWN_KEYS,
    NETWORK_UP_KEYS,
    QPS_KEYS,
    REQUEST_COUNT_KEYS,
    RESPONSE_TIME_KEYS,
    RETRY_COUNT_KEYS,
    TASK_COUNT_KEYS,
    THREAD_KEYS,
    TIME_KEYS,
    TOTAL_MEMORY_KEYS,
    TPS_KEYS,
)
from .time_utils import parse_timestamp_series
from .utils import dynamic_metric_key, find_column, is_numeric_like


def workbook_source(sample_file: Path, payload: bytes | None) -> str | BinaryIO:
    return str(sample_file) if payload is None else BytesIO(payload)


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
            normalized[target] = parse_timestamp_series(df[source])
        else:
            used_sources.add(source)
            normalized[target] = pd.to_numeric(df[source], errors="coerce")

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
        normalized["timestamp"] = parse_timestamp_series(df[timestamp_column])
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


def read_single_workbook(
    source_name: str,
    uploaded_file: bytes | None,
    field_alias_items: tuple[tuple[str, tuple[str, ...]], ...],
    analysis_mode: str,
    sample_file: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    field_aliases = dict(field_alias_items)
    workbook = pd.ExcelFile(workbook_source(sample_file, uploaded_file))
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


def timestamp_diagnostics(
    files: tuple[tuple[str, bytes | None], ...],
    field_alias_items: tuple[tuple[str, tuple[str, ...]], ...],
    sample_file: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    field_aliases = dict(field_alias_items)
    summary_rows = []
    failure_rows = []
    for source_name, payload in files:
        workbook = pd.ExcelFile(workbook_source(sample_file, payload))
        for sheet_name in workbook.sheet_names[1:]:
            raw = pd.read_excel(workbook, sheet_name=sheet_name)
            columns = [str(column) for column in raw.columns]
            timestamp_column = find_column(columns, TIME_KEYS, aliases=field_aliases.get("timestamp", ()))
            if timestamp_column is None:
                summary_rows.append(
                    {
                        "数据源": source_name,
                        "分组": sheet_name,
                        "时间列": "-",
                        "总行数": len(raw),
                        "非空时间值": 0,
                        "解析成功数": 0,
                        "解析失败数": len(raw),
                        "解析成功率(%)": 0.0 if len(raw) else np.nan,
                    }
                )
                continue
            parsed = parse_timestamp_series(raw[timestamp_column])
            raw_text = raw[timestamp_column].astype("string").str.strip()
            non_empty = raw_text.notna() & ~raw_text.isin(["", "nan", "NaN", "None", "NaT"])
            failed_mask = non_empty & parsed.isna()
            success_count = int((non_empty & parsed.notna()).sum())
            non_empty_count = int(non_empty.sum())
            failure_count = int(failed_mask.sum())
            success_rate = success_count / non_empty_count * 100 if non_empty_count else np.nan
            summary_rows.append(
                {
                    "数据源": source_name,
                    "分组": sheet_name,
                    "时间列": timestamp_column,
                    "总行数": len(raw),
                    "非空时间值": non_empty_count,
                    "解析成功数": success_count,
                    "解析失败数": failure_count,
                    "解析成功率(%)": success_rate,
                }
            )
            for index, value in raw.loc[failed_mask, timestamp_column].head(5).items():
                failure_rows.append(
                    {
                        "数据源": source_name,
                        "分组": sheet_name,
                        "行号": int(index) + 2,
                        "时间列": timestamp_column,
                        "原始值": str(value),
                    }
                )
    return pd.DataFrame(summary_rows), pd.DataFrame(failure_rows)


def non_numeric_column_summary(
    files: tuple[tuple[str, bytes | None], ...],
    field_alias_items: tuple[tuple[str, tuple[str, ...]], ...],
    sample_file: Path,
) -> pd.DataFrame:
    field_aliases = dict(field_alias_items)
    rows = []
    for source_name, payload in files:
        workbook = pd.ExcelFile(workbook_source(sample_file, payload))
        for sheet_name in workbook.sheet_names[1:]:
            raw = pd.read_excel(workbook, sheet_name=sheet_name)
            columns = [str(column) for column in raw.columns]
            timestamp_column = find_column(columns, TIME_KEYS, aliases=field_aliases.get("timestamp", ()))
            for column in columns:
                if column == timestamp_column:
                    continue
                if is_numeric_like(raw[column]):
                    continue
                non_empty = int(raw[column].notna().sum())
                if non_empty == 0:
                    continue
                rows.append(
                    {
                        "数据源": source_name,
                        "分组": sheet_name,
                        "列名": column,
                        "非空值": non_empty,
                        "示例值": ", ".join(raw[column].dropna().astype(str).head(3).tolist()),
                    }
                )
    return pd.DataFrame(rows)
