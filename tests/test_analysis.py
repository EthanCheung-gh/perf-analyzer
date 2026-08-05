from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from perf_analyzer.analysis import (
    apply_advanced_filters,
    apply_stable_window,
    bottleneck_hints,
    capacity_estimation,
    compute_decision_bundle,
    configuration_recommendation,
    leak_analysis,
    metric_stats,
    release_gate_analysis,
    resource_efficiency_analysis,
    scene_decision_analysis,
    summarize,
    trend_analysis,
    workload_efficiency_bucket_summary,
    workload_efficiency_buckets,
)
from perf_analyzer.models import Metric
from perf_analyzer.rules import RiskRules


def test_summarize_columns_and_rows(sample_df, metrics):
    summary = summarize(sample_df, {}, metrics)
    # 2 数据源 × 2 场景
    assert len(summary) == 4
    assert "场景" in summary.columns
    assert "样本数" in summary.columns
    assert any(column.endswith("P95") for column in summary.columns)


def test_summarize_alert_columns(sample_df, metrics):
    thresholds = {"cpu_percent": 40.0}
    summary = summarize(sample_df, thresholds, metrics)
    assert "CPU超阈次数" in summary.columns
    assert "CPU超阈占比(%)" in summary.columns


def test_stable_window_cuts_first_minutes(sample_df):
    warmup = 10.0
    result = apply_stable_window(sample_df, warmup)
    assert len(result) < len(sample_df)
    for (source, scene), group in result.groupby(["source", "scene"]):
        start = group["timestamp"].min()
        raw_start = sample_df[(sample_df["source"] == source) & (sample_df["scene"] == scene)]["timestamp"].min()
        assert start >= raw_start + pd.Timedelta(minutes=warmup)


def test_advanced_filters_time_range(sample_df):
    start = sample_df["timestamp"].min()
    end = start + pd.Timedelta(minutes=30)
    result = apply_advanced_filters(sample_df, time_range=(start, end))
    assert result["timestamp"].max() <= end
    assert len(result) < len(sample_df)


def test_advanced_filters_metric_condition(sample_df):
    result = apply_advanced_filters(
        sample_df,
        metric_conditions=[("cpu_percent", ">", 50.0)],
        metric_condition_logic="AND",
    )
    assert (result["cpu_percent"] > 50.0).all()


def test_advanced_filters_downsample(sample_df):
    result = apply_advanced_filters(sample_df, downsample_every_n=2)
    # 每 2 个点保留 1 个
    assert len(result) <= (len(sample_df) + 1) // 2 + 2


def test_leak_analysis_detects_leak(leak_df):
    result = leak_analysis(leak_df, slope_threshold=2.0)
    assert len(result) == 1
    assert result.iloc[0]["判断"] in ("疑似泄漏", "轻微增长")
    assert result.iloc[0]["内存斜率(MB/分钟)"] > 2.0


def test_leak_analysis_no_leak(sample_df):
    result = leak_analysis(sample_df, slope_threshold=2.0)
    # 随机波动数据不应判为疑似泄漏
    assert (result["判断"] != "疑似泄漏").all()


def test_trend_analysis_direction(leak_df, metrics):
    cpu_metric = Metric("cpu_percent", "CPU", "%", "CPU 告警阈值", 80.0)
    result = trend_analysis(leak_df, [cpu_metric])
    memory_row = result[result["指标"] == "CPU"]
    assert len(memory_row) == 1
    assert memory_row.iloc[0]["趋势"] in ("上升", "基本稳定", "下降")


def test_resource_efficiency_ratio(sample_df):
    efficiency = resource_efficiency_analysis(sample_df)
    assert not efficiency.empty
    row = efficiency.iloc[0]
    group = sample_df[(sample_df["source"] == row["数据源"]) & (sample_df["scene"] == row["场景"])]
    cpu_p95 = group["cpu_percent"].quantile(0.95)
    throughput = group["qps"].mean()
    expected = cpu_p95 / throughput
    assert abs(row["CPU P95/吞吐"] - expected) < 1e-6


def test_scene_decision_rules_configurable(threshold_df, metrics):
    thresholds = {"cpu_percent": 80.0}
    default_rules = RiskRules()
    strict_rules = RiskRules(response_ms_critical=2000.0, response_ms_warning=1800.0)
    default_decisions = scene_decision_analysis(threshold_df, thresholds, metrics, 2.0, rules=default_rules)
    strict_decisions = scene_decision_analysis(threshold_df, thresholds, metrics, 2.0, rules=strict_rules)
    assert len(default_decisions) == 1
    assert len(strict_decisions) == 1
    assert default_decisions.iloc[0]["风险评分"] > strict_decisions.iloc[0]["风险评分"]


def test_compute_decision_bundle(threshold_df, metrics):
    thresholds = {"cpu_percent": 80.0}
    bundle = compute_decision_bundle(threshold_df, thresholds, metrics, 2.0)
    assert not bundle.decisions.empty
    assert not bundle.stability.empty
    assert not bundle.bottlenecks.empty
    assert not bundle.matrix.empty
    assert not bundle.radar.empty


def test_release_gate_fail_on_high_risk():
    decisions = pd.DataFrame(
        {
            "数据源": ["s1"],
            "场景": ["sc1"],
            "风险等级": ["高风险"],
            "内存趋势": ["无明显增长"],
            "最大超阈占比(%)": [0.0],
            "失败率(%)": [0.0],
        }
    )
    status, rules = release_gate_analysis(decisions, "低风险", fail_on_leak=True, fail_on_any_alert=False, fail_on_errors=False)
    assert status == "不通过"
    assert (rules["结果"] == "失败").any()


def test_capacity_estimation(sample_df):
    capacity = capacity_estimation(sample_df, test_cpu_cores=8, target_cpu_utilization=70.0, target_throughputs=[50, 100], system_reserved_memory_gb=2.0)
    assert not capacity.empty
    assert len(capacity) == 2
    assert "建议CPU核数" in capacity.columns


def test_configuration_recommendation(sample_df):
    table, notes = configuration_recommendation(
        sample_df,
        test_cpu_cores=8,
        target_cpu_utilization=70.0,
        minimum_cpu_cores=2,
        system_reserved_memory_gb=2.0,
        minimum_memory_gb=4,
        minimum_free_disk_gb=10,
        recommendation_factor=1.5,
        slope_threshold=2.0,
    )
    assert len(table) == 2
    assert set(table["配置档位"]) == {"最低可运行", "推荐配置"}
    assert len(notes) >= 4


def test_bottleneck_hints(sample_df, metrics):
    thresholds = {"cpu_percent": 80.0, "memory_percent": 70.0, "io": 8.0}
    hints = bottleneck_hints(sample_df, thresholds, metrics)
    assert len(hints) == 4


def test_workload_efficiency_buckets(sample_df):
    buckets = workload_efficiency_buckets(sample_df)
    assert not buckets.empty
    assert "CPU成本" in buckets.columns
    # CPU成本 = 平均CPU / 平均吞吐
    row = buckets.iloc[0]
    assert abs(row["CPU成本"] - row["平均CPU"] / row["平均吞吐"]) < 1e-6
    summary = workload_efficiency_bucket_summary(buckets)
    assert len(summary) == 4
    assert "瞬时成本P95" in summary.columns


def test_workload_efficiency_buckets_zero_throughput_skipped():
    data = pd.DataFrame(
        {
            "source": ["s1", "s1", "s1"],
            "scene": ["sc1", "sc1", "sc1"],
            "timestamp": pd.date_range("2026-01-01", periods=3, freq="min"),
            "cpu_percent": [10.0, 10.0, 10.0],
            "qps": [0.0, 100.0, 0.0],
        }
    )
    buckets = workload_efficiency_buckets(data)
    assert not buckets.empty
    # 吞吐为 0 的桶成本为 NaN，不参与后续计算
    assert buckets.loc[buckets["平均吞吐"] == 0, "CPU成本"].isna().all()
    assert buckets.loc[buckets["平均吞吐"] > 0, "CPU成本"].notna().all()


def test_metric_stats_groups(sample_df, metrics):
    stats = metric_stats(sample_df, ["source", "scene"], metrics)
    assert len(stats) == 4
    assert "cpu_percent_p95" in stats.columns
