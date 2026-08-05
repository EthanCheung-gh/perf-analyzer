from __future__ import annotations

import numpy as np
import pandas as pd

from perf_analyzer.phases import detect_phases


def _frame(cpu, n):
    ts = pd.date_range("2026-01-01", periods=n, freq="min")
    return pd.DataFrame({"source": "s1", "scene": "sc1", "timestamp": ts, "cpu_percent": cpu})


def test_three_phases_detected(phase_df):
    phases = detect_phases(phase_df, "s1", "sc1", "cpu_percent")
    assert len(phases) == 3
    assert list(phases["标签"]) == ["预热", "压力", "稳定"]


def test_two_phases_detected():
    n = 90
    cpu = np.concatenate([np.full(40, 80.0), np.full(50, 30.0)]) + np.random.default_rng(3).normal(0, 2, n)
    phases = detect_phases(_frame(cpu, n), "s1", "sc1", "cpu_percent")
    assert len(phases) == 2
    assert phases.iloc[0]["标签"] == "压力"
    assert phases.iloc[1]["标签"] == "稳定"


def test_flat_series_single_phase():
    n = 90
    cpu = np.full(n, 40.0)
    phases = detect_phases(_frame(cpu, n), "s1", "sc1", "cpu_percent")
    assert len(phases) == 1
    assert phases.iloc[0]["标签"] == "单一阶段"


def test_linear_ramp_single_phase():
    n = 90
    cpu = np.linspace(10, 60, n)
    phases = detect_phases(_frame(cpu, n), "s1", "sc1", "cpu_percent")
    assert len(phases) == 1


def test_empty_data_returns_empty():
    data = pd.DataFrame(columns=["source", "scene", "timestamp", "cpu_percent"])
    assert detect_phases(data, "s1", "sc1", "cpu_percent").empty


def test_phase_table_columns(phase_df):
    phases = detect_phases(phase_df, "s1", "sc1", "cpu_percent")
    expected = {"数据源", "场景", "阶段序号", "标签", "开始时间", "结束时间", "持续时长", "指标", "均值", "峰值", "P95"}
    assert expected.issubset(set(phases.columns))
