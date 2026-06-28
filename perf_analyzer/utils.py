from __future__ import annotations

import re

import pandas as pd


def clean_name(value: object) -> str:
    return str(value).strip().replace("（", "(").replace("）", ")").lower()


def safe_filename(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", str(value).strip())
    return normalized.strip("_") or "chart"


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
