from __future__ import annotations

import numpy as np

from perf_analyzer.significance import cohens_d, mann_whitney_u, rankdata, significance_test


def test_rankdata_ties():
    result = rankdata(np.array([1.0, 2.0, 2.0, 3.0]))
    assert np.allclose(result, [1.0, 2.5, 2.5, 4.0])


def test_rankdata_all_ties():
    result = rankdata(np.array([5.0, 5.0, 5.0]))
    assert np.allclose(result, [2.0, 2.0, 2.0])


def test_mann_whitney_equal_samples_p_large():
    rng = np.random.default_rng(1)
    a = rng.normal(50.0, 5.0, 60)
    b = rng.normal(50.0, 5.0, 60)
    u, p = mann_whitney_u(a, b)
    assert p > 0.01


def test_mann_whitney_clear_separation_p_small():
    a = np.array([10.1, 10.5, 10.3, 10.8, 10.2, 10.6, 10.4, 10.7, 10.9, 10.0] * 4)
    b = np.array([9.1, 9.5, 9.3, 9.8, 9.2, 9.6, 9.4, 9.7, 9.9, 9.0] * 4)
    u, p = mann_whitney_u(a, b)
    assert p < 0.01


def test_mann_whitney_insufficient_samples():
    u, p = mann_whitney_u(np.array([1.0, 2.0]), np.array([3.0, 4.0]))
    assert np.isnan(u) and np.isnan(p)


def test_cohens_d_sign():
    a = np.array([10.0, 11.0, 10.5, 10.8, 10.2])
    b = np.array([8.0, 9.0, 8.5, 8.8, 8.2])
    d = cohens_d(a, b)
    assert d > 1.0  # 明显正向大效应


def test_significance_test_detects_separation(version_df):
    a = version_df[version_df["source"] == "A"]["cpu_percent"].to_numpy()
    b = version_df[version_df["source"] == "B"]["cpu_percent"].to_numpy()
    result = significance_test(a, b)
    assert result["significant"] is True
    assert result["verdict"] == "显著"
    assert result["direction"] == "higher"
    assert result["p_value"] < 0.05
    assert abs(result["cohens_d"]) > 0.2


def test_significance_test_insufficient_samples():
    result = significance_test(np.array([1.0, 2.0]), np.array([3.0, 4.0]))
    assert result["verdict"] == "样本不足"
    assert result["significant"] is False


def test_significance_test_noise_verdict(version_df):
    # 用同一分布的两组样本应判为不显著（或至少显著概率低）
    rng = np.random.default_rng(3)
    a = rng.normal(50.0, 4.0, 80)
    b = rng.normal(50.0, 4.0, 80)
    result = significance_test(a, b, p_threshold=0.01, effect_threshold=0.5)
    assert result["significant"] is False
