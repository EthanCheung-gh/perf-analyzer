from __future__ import annotations

import pandas as pd
import streamlit as st

from .constants import GENERIC_MODE, GENERIC_SAMPLE_FILE, PERFORMANCE_MODE, SAMPLE_FILE
from .io import non_numeric_column_summary, read_single_workbook, timestamp_diagnostics


@st.cache_data(show_spinner=False)
def load_single_workbook(
    source_name: str,
    uploaded_file: bytes | None,
    field_alias_items: tuple[tuple[str, tuple[str, ...]], ...],
    analysis_mode: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sample_file = GENERIC_SAMPLE_FILE if analysis_mode == GENERIC_MODE else SAMPLE_FILE
    return read_single_workbook(source_name, uploaded_file, field_alias_items, analysis_mode, sample_file)


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


@st.cache_data(show_spinner=False)
def load_timestamp_diagnostics(
    files: tuple[tuple[str, bytes | None], ...],
    field_alias_items: tuple[tuple[str, tuple[str, ...]], ...],
    analysis_mode: str = PERFORMANCE_MODE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sample_file = GENERIC_SAMPLE_FILE if analysis_mode == GENERIC_MODE else SAMPLE_FILE
    return timestamp_diagnostics(files, field_alias_items, sample_file)


@st.cache_data(show_spinner=False)
def load_non_numeric_column_summary(
    files: tuple[tuple[str, bytes | None], ...],
    field_alias_items: tuple[tuple[str, tuple[str, ...]], ...],
    analysis_mode: str = PERFORMANCE_MODE,
) -> pd.DataFrame:
    sample_file = GENERIC_SAMPLE_FILE if analysis_mode == GENERIC_MODE else SAMPLE_FILE
    return non_numeric_column_summary(files, field_alias_items, sample_file)
