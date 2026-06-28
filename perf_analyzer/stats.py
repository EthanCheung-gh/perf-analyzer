from __future__ import annotations

import numpy as np
import pandas as pd


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
