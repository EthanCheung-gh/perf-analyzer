from __future__ import annotations

import math

import numpy as np


def norm_cdf(x: float) -> float:
    """标准正态分布累积分布函数，使用 math.erf 实现，避免引入 scipy。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def rankdata(values: np.ndarray) -> np.ndarray:
    """返回平均秩（含并列修正），行为与 scipy.stats.rankdata 的 'average' 方法一致。"""
    values = np.asarray(values, dtype=float)
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    n = len(values)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        average_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = average_rank
        i = j + 1
    return ranks


def mann_whitney_u(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """双尾 Mann-Whitney U 检验（正态近似 + 并列修正），返回 (U, p_value)。

    样本量小于 3 时返回 (nan, nan)，由调用方标记为样本不足。
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    n1, n2 = len(a), len(b)
    if n1 < 3 or n2 < 3:
        return float("nan"), float("nan")

    combined = np.concatenate([a, b])
    ranks = rankdata(combined)
    n = n1 + n2
    r1 = float(ranks[:n1].sum())
    u1 = r1 - n1 * (n1 + 1) / 2.0
    u2 = n1 * n2 - u1
    u = min(u1, u2)

    # 并列修正
    unique, counts = np.unique(combined, return_counts=True)
    tie_adjustment = float(np.sum(counts**3 - counts))
    variance = (n1 * n2 / 12.0) * ((n + 1) - tie_adjustment / (n * (n - 1)))
    if variance <= 0:
        return u, 1.0
    mean = n1 * n2 / 2.0
    z = (u - mean) / math.sqrt(variance)
    p_value = 2.0 * (1.0 - norm_cdf(abs(z)))
    return u, float(p_value)


def cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    """合并标准差效应量 Cohen's d（a 相对 b 的均值差）。"""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return float("nan")
    var1 = float(np.var(a, ddof=1))
    var2 = float(np.var(b, ddof=1))
    pooled = math.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
    if pooled == 0:
        return 0.0
    return float((a.mean() - b.mean()) / pooled)


def difference_ci(a: np.ndarray, b: np.ndarray, n_boot: int = 1000, seed: int = 42) -> tuple[float, float]:
    """均值差 (mean(a) - mean(b)) 的 bootstrap 95% 置信区间。"""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if len(a) < 2 or len(b) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        sample_a = a[rng.integers(0, len(a), len(a))]
        sample_b = b[rng.integers(0, len(b), len(b))]
        diffs[i] = sample_a.mean() - sample_b.mean()
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def significance_test(
    a: np.ndarray,
    b: np.ndarray,
    p_threshold: float = 0.05,
    effect_threshold: float = 0.2,
) -> dict:
    """对两组样本做显著性检验，返回判定结果。

    Args:
        a: 当前版本/数据源样本
        b: 基准版本/数据源样本
        p_threshold: P 值阈值，低于该值认为分布差异统计显著
        effect_threshold: |Cohen's d| 阈值，低于该值认为效应量过小

    Returns:
        dict: {n1, n2, u, p_value, cohens_d, ci_low, ci_high,
               significant, direction, verdict}
        direction: "higher" / "lower" / "unknown"，表示 a 相对 b 的方向
        verdict: "显著" / "不显著" / "样本不足"
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a_clean = a[~np.isnan(a)]
    b_clean = b[~np.isnan(b)]
    n1, n2 = len(a_clean), len(b_clean)

    if n1 < 3 or n2 < 3:
        return {
            "n1": n1,
            "n2": n2,
            "u": float("nan"),
            "p_value": float("nan"),
            "cohens_d": float("nan"),
            "ci_low": float("nan"),
            "ci_high": float("nan"),
            "significant": False,
            "direction": "unknown",
            "verdict": "样本不足",
        }

    u, p_value = mann_whitney_u(a_clean, b_clean)
    d = cohens_d(a_clean, b_clean)
    ci_low, ci_high = difference_ci(a_clean, b_clean)
    mean_diff = float(a_clean.mean() - b_clean.mean())
    direction = "higher" if mean_diff > 0 else "lower" if mean_diff < 0 else "unknown"
    significant = bool(p_value < p_threshold and abs(d) >= effect_threshold)
    verdict = "显著" if significant else "不显著"
    return {
        "n1": n1,
        "n2": n2,
        "u": u,
        "p_value": p_value,
        "cohens_d": d,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "significant": significant,
        "direction": direction,
        "verdict": verdict,
    }
