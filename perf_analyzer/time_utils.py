from __future__ import annotations

import numpy as np
import pandas as pd


def parse_timestamp_series(series: pd.Series) -> pd.Series:
    values = series.copy()
    if pd.api.types.is_datetime64_any_dtype(values):
        parsed = pd.to_datetime(values, errors="coerce")
    elif pd.api.types.is_numeric_dtype(values):
        numeric = pd.to_numeric(values, errors="coerce")
        sample = numeric.dropna().abs()
        if sample.empty:
            parsed = pd.to_datetime(values, errors="coerce")
        else:
            median = float(sample.median())
            if median >= 1e17:
                parsed = pd.to_datetime(numeric, unit="ns", errors="coerce")
            elif median >= 1e14:
                parsed = pd.to_datetime(numeric, unit="us", errors="coerce")
            elif median >= 1e11:
                parsed = pd.to_datetime(numeric, unit="ms", errors="coerce")
            elif median >= 1e9:
                parsed = pd.to_datetime(numeric, unit="s", errors="coerce")
            else:
                parsed = pd.to_datetime(numeric, unit="D", origin="1899-12-30", errors="coerce")
    else:
        text = values.astype("string").str.strip()
        text = text.mask(text.isin(["", "nan", "NaN", "None", "NaT"]))
        try:
            parsed = pd.to_datetime(text, errors="coerce", format="mixed")
        except ValueError:
            parsed = pd.to_datetime(text, errors="coerce")

    parsed = pd.Series(parsed, index=series.index)
    if pd.api.types.is_datetime64tz_dtype(parsed):
        parsed = parsed.dt.tz_convert(None)
    return parsed


def typical_sampling_seconds(group: pd.DataFrame) -> float | None:
    timestamps = group["timestamp"].dropna().sort_values()
    if len(timestamps) < 2:
        return None
    diffs = timestamps.diff().dropna().dt.total_seconds()
    diffs = diffs[diffs > 0]
    if diffs.empty:
        return None
    return float(diffs.median())


def rolling_points_for_group(group: pd.DataFrame, window_mode: str, point_window: int, time_window_seconds: float) -> int:
    if window_mode == "按采样点数":
        return max(2, int(point_window))
    sample_seconds = typical_sampling_seconds(group)
    if not sample_seconds or sample_seconds <= 0:
        return max(2, int(point_window))
    return max(2, int(np.ceil(float(time_window_seconds) / sample_seconds)))
