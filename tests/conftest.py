from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from perf_analyzer.metrics import discover_metrics


def _make_series(
    n: int = 120,
    start: str = "2026-01-01",
    freq: str = "min",
    sources: tuple[str, ...] = ("A", "B"),
    scenes: tuple[str, ...] = ("轻载", "重载"),
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start, periods=n, freq=freq)
    rows = []
    for source in sources:
        for scene in scenes:
            cpu = 30 + rng.normal(0, 8, n)
            memory = 800 + rng.normal(0, 40, n)
            qps = 100 + rng.normal(0, 10, n)
            threads = 60 + rng.integers(-5, 6, n)
            io = rng.uniform(0, 6, n)
            handles = 1000 + rng.integers(-20, 20, n)
            concurrency = 50 + rng.integers(-3, 4, n)
            response = 200 + rng.normal(0, 50, n)
            fps = 58 + rng.normal(0, 2, n)
            failed = np.where(rng.random(n) < 0.02, 1, 0)
            requests = rng.integers(90, 110, n)
            for i in range(n):
                rows.append(
                    {
                        "source": source,
                        "scene": scene,
                        "timestamp": ts[i],
                        "cpu_percent": cpu[i],
                        "memory_mb": memory[i],
                        "threads": threads[i],
                        "io": io[i],
                        "handles": handles[i],
                        "qps": qps[i],
                        "concurrency": concurrency[i],
                        "response_time_ms": response[i],
                        "fps": fps[i],
                        "request_count": requests[i],
                        "failed_requests": failed[i],
                    }
                )
    return pd.DataFrame(rows)


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return _make_series()


@pytest.fixture
def leak_df() -> pd.DataFrame:
    """内存以约 +3MB/分钟 线性增长，用于泄漏检测测试。"""
    n = 180
    ts = pd.date_range("2026-01-01", periods=n, freq="min")
    rng = np.random.default_rng(1)
    memory = 800 + np.arange(n) * 3.0 + rng.normal(0, 8, n)
    cpu = 40 + rng.normal(0, 5, n)
    return pd.DataFrame(
        {"source": "s1", "scene": "sc1", "timestamp": ts, "memory_mb": memory, "cpu_percent": cpu}
    )


@pytest.fixture
def phase_df() -> pd.DataFrame:
    """低负载(10) → 压力(70) → 稳定(40) 三段合成序列。"""
    n = 90
    ts = pd.date_range("2026-01-01", periods=n, freq="min")
    cpu = np.concatenate([np.full(30, 10.0), np.full(30, 70.0), np.full(30, 40.0)])
    cpu = cpu + np.random.default_rng(1).normal(0, 1.5, n)
    return pd.DataFrame({"source": "s1", "scene": "sc1", "timestamp": ts, "cpu_percent": cpu})


@pytest.fixture
def version_df() -> pd.DataFrame:
    """数据源 A 的 CPU 明显高于 B，用于显著性检验。"""
    n = 60
    ts = pd.date_range("2026-01-01", periods=n, freq="min")
    rng = np.random.default_rng(5)
    frames = []
    for source, base in (("A", 70.0), ("B", 40.0)):
        frames.append(
            pd.DataFrame(
                {
                    "source": source,
                    "scene": "重载",
                    "timestamp": ts,
                    "cpu_percent": base + rng.normal(0, 3, n),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


@pytest.fixture
def threshold_df() -> pd.DataFrame:
    """响应时间偏高的数据，用于验证决策规则的阈值可配置性。"""
    n = 90
    ts = pd.date_range("2026-01-01", periods=n, freq="min")
    rng = np.random.default_rng(9)
    return pd.DataFrame(
        {
            "source": "s1",
            "scene": "sc1",
            "timestamp": ts,
            "cpu_percent": 30 + rng.normal(0, 4, n),
            "memory_mb": 800 + rng.normal(0, 20, n),
            "response_time_ms": 1200 + rng.normal(0, 80, n),
            "qps": 100 + rng.normal(0, 5, n),
            "request_count": rng.integers(90, 110, n),
            "failed_requests": np.zeros(n),
        }
    )


@pytest.fixture
def metrics(sample_df):
    return discover_metrics(sample_df)
