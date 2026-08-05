from __future__ import annotations

import pandas as pd

from perf_analyzer.analysis import workload_efficiency_bucket_summary, workload_efficiency_buckets


def _bucket_df(n=10, start="2026-01-01", seed=11):
    rng = __import__("numpy").random.default_rng(seed)
    ts = pd.date_range(start, periods=n, freq="min")
    return pd.DataFrame(
        {
            "source": ["s1"] * n,
            "scene": ["sc1"] * n,
            "timestamp": ts,
            "cpu_percent": 30 + rng.normal(0, 5, n),
            "memory_mb": 800 + rng.normal(0, 20, n),
            "qps": 100 + rng.normal(0, 5, n),
            "concurrency": 50 + rng.integers(-2, 3, n),
        }
    )


def test_bucket_count_per_minute():
    data = _bucket_df(n=10)
    buckets = workload_efficiency_buckets(data)
    # 每分钟一个桶
    assert len(buckets) == 10
    assert buckets["时间桶"].nunique() == 10


def test_cpu_cost_ratio():
    data = _bucket_df(n=10)
    buckets = workload_efficiency_buckets(data)
    row = buckets.iloc[0]
    assert abs(row["CPU成本"] - row["平均CPU"] / row["平均吞吐"]) < 1e-6


def test_memory_per_concurrency():
    data = _bucket_df(n=10)
    buckets = workload_efficiency_buckets(data)
    assert "内存/并发(MB)" in buckets.columns
    row = buckets.iloc[0]
    assert abs(row["内存/并发(MB)"] - row["内存峰值"] / row["平均并发"]) < 1e-6


def test_throughput_key_auto_detection():
    # 没有 qps 但有 task_count
    data = _bucket_df(n=6)
    data = data.drop(columns=["qps"])
    data["task_count"] = 200.0
    buckets = workload_efficiency_buckets(data)
    assert "平均吞吐" in buckets.columns
    assert buckets["平均吞吐"].iloc[0] == 200.0


def test_summary_columns():
    data = _bucket_df(n=20)
    buckets = workload_efficiency_buckets(data)
    summary = workload_efficiency_bucket_summary(buckets)
    assert len(summary) == 1
    assert summary.iloc[0]["场景"] == "sc1"
    assert "瞬时成本P95" in summary.columns
    assert "瞬时成本中位" in summary.columns


def test_empty_data():
    assert workload_efficiency_buckets(pd.DataFrame()).empty
