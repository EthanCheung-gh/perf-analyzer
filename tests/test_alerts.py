from __future__ import annotations

import numpy as np
import pandas as pd

from perf_analyzer.alerts import (
    alert_mask,
    alert_segments,
    format_duration,
    format_peak_offset,
    interval_alert_mask,
    max_continuous_alert_minutes,
    metric_alert_mask,
)
from perf_analyzer.models import Metric

CPU = Metric("cpu_percent", "CPU", "%", "CPU 告警阈值", 80.0)


def _group(ts, values, scene="sc1"):
    return pd.DataFrame({"source": "s1", "scene": scene, "timestamp": pd.to_datetime(ts), "cpu_percent": values})


def test_alert_mask_higher_is_worse():
    series = pd.Series([10.0, 90.0, 50.0])
    mask = alert_mask(series, 80.0, higher_is_worse=True)
    assert list(mask) == [False, True, False]


def test_alert_mask_lower_is_worse():
    series = pd.Series([10.0, 90.0, 50.0])
    mask = alert_mask(series, 45.0, higher_is_worse=False)
    assert list(mask) == [True, False, False]


def test_interval_alert_mask():
    series = pd.Series([5.0, 50.0, 95.0])
    mask = interval_alert_mask(series, 10.0, 90.0)
    assert list(mask) == [True, False, True]


def test_metric_alert_mask_bounds_priority():
    series = pd.Series([5.0, 50.0, 95.0])
    mask = metric_alert_mask(series, CPU, {"cpu_percent": 80.0}, {"cpu_percent": (10.0, 90.0)})
    assert list(mask) == [True, False, True]


def test_alert_segments_two_runs():
    ts = pd.date_range("2026-01-01", periods=20, freq="min")
    values = [30.0] * 4 + [95.0] * 4 + [30.0] * 6 + [95.0] * 4 + [30.0] * 2
    data = _group(ts, values)
    segments = alert_segments(data, {"cpu_percent": 80.0}, [CPU])
    assert len(segments) == 2
    assert segments["异常点数"].tolist() == [4, 4]


def test_alert_segments_runs_separated_by_gap():
    # 1 分钟采样间隔下，两段异常之间至少间隔 2 分钟，超过 1.5×采样间隔，不会合并
    ts = pd.date_range("2026-01-01", periods=12, freq="min")
    values = [30.0, 95.0, 95.0, 30.0, 95.0, 95.0, 95.0, 30.0, 30.0, 30.0, 30.0, 30.0]
    data = _group(ts, values)
    segments = alert_segments(data, {"cpu_percent": 80.0}, [CPU])
    assert len(segments) == 2
    assert sorted(segments["异常点数"].tolist()) == [2, 3]


def test_max_continuous_alert_minutes():
    ts = pd.date_range("2026-01-01", periods=8, freq="min")
    values = [30.0, 95.0, 95.0, 95.0, 30.0, 30.0, 95.0, 95.0]
    data = _group(ts, values)
    minutes = max_continuous_alert_minutes(data, CPU, {"cpu_percent": 80.0})
    assert minutes >= 3.0
    assert minutes < 5.0


def test_format_duration():
    assert format_duration(0.5) == "30秒"
    assert format_duration(90.0) == "1小时30分钟"
    assert format_duration(5.0) == "5.0分钟"
    assert format_duration(float("nan")) == "-"


def test_format_peak_offset():
    ts = pd.date_range("2026-01-01", periods=5, freq="min")
    values = [10.0, 20.0, 90.0, 30.0, 40.0]
    data = _group(ts, values)
    assert format_peak_offset(data, "cpu_percent") == "2.0分钟"
