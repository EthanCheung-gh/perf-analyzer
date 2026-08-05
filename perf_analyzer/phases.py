from __future__ import annotations

import pandas as pd

from .alerts import format_duration
from .stats import percentile_95


def _single_phase(
    source: str,
    scene: str,
    metric_key: str,
    timestamps: pd.Series,
    values: pd.Series,
) -> pd.DataFrame:
    n = len(values)
    if n == 0:
        return pd.DataFrame()
    duration_minutes = float((timestamps.iloc[-1] - timestamps.iloc[0]).total_seconds() / 60)
    return pd.DataFrame(
        [
            {
                "数据源": source,
                "场景": scene,
                "阶段序号": 1,
                "标签": "单一阶段",
                "开始时间": timestamps.iloc[0],
                "结束时间": timestamps.iloc[-1],
                "持续时长": format_duration(duration_minutes),
                "指标": metric_key,
                "均值": float(values.mean()),
                "峰值": float(values.max()),
                "P95": percentile_95(values),
            }
        ]
    )


def detect_phases(
    data: pd.DataFrame,
    source: str,
    scene: str,
    metric_key: str = "cpu_percent",
    window: int | None = None,
    min_phase_minutes: float = 1.0,
) -> pd.DataFrame:
    """自动检测单个数据源+场景的指标序列阶段（预热/稳定/压力）。

    算法（无外部依赖）：
    1. 滚动均值平滑（窗口默认 max(3, min(n//10, 30))）；
    2. 用窗口跨度变化量（shift 差值）计算水平跳变强度；
    3. 超过阈值且在 ±(窗口一半) 邻域内是局部最大值的点为候选切分点，
       间隔小于 min_phase_minutes 的合并（保留变化量最大的）；
    4. 由切分点构建阶段段，计算每段均值/峰值/P95/时长；
    5. 标签：段均值 <= 场景均值×0.5 → 低负载；>= 场景均值×1.5 → 压力；否则稳定；
       首段且均值低于场景均值时标记为预热。

    Returns:
        列：数据源, 场景, 阶段序号, 标签, 开始时间, 结束时间, 持续时长, 指标, 均值, 峰值, P95
    """
    group = data[(data["source"] == source) & (data["scene"] == scene)]
    if group.empty or "timestamp" not in group or metric_key not in group:
        return pd.DataFrame()
    series = group[["timestamp", metric_key]].dropna().sort_values("timestamp").reset_index(drop=True)
    if series.empty:
        return pd.DataFrame()
    values = series[metric_key].astype(float)
    timestamps = series["timestamp"]
    n = len(values)
    if n < 6:
        return _single_phase(source, scene, metric_key, timestamps, values)

    if window is None:
        window = max(3, min(n // 10, 30))
    window = max(2, int(window))
    rolling = values.rolling(window, center=True, min_periods=2).mean()
    # 用“窗口跨度变化量”而非单步差分：过渡期累积变化大、平稳期接近 0，更容易分离
    # shift 取窗口的 1/4，避免变化信号足迹过宽导致平稳期占比太小
    shift = max(1, int(window // 4))
    change = rolling.shift(-shift) - rolling.shift(shift)
    abs_change = change.abs()
    change_values = abs_change.dropna()
    if change_values.empty:
        return _single_phase(source, scene, metric_key, timestamps, values)
    change_max = float(change_values.max())
    change_floor = float(change_values.quantile(0.25)) if len(change_values) else 0.0
    # 没有明显的水平跳变（变化量峰值不超过 25 分位噪声底的 5 倍）时不做切分，
    # 避免把平滑渐变/线性爬升误切成多段
    if change_max <= 0 or change_max < 5.0 * max(change_floor, 1e-9):
        return _single_phase(source, scene, metric_key, timestamps, values)
    # 阈值取变化峰值的 30%：既能捕获不同幅度的水平跳变，又能过滤平稳期噪声
    change_threshold = 0.3 * change_max
    if pd.isna(change_threshold) or change_threshold <= 0:
        return _single_phase(source, scene, metric_key, timestamps, values)

    # 候选切分点：超过阈值且在 ±(窗口一半) 邻域内是局部最大值，
    # 保证每个过渡区最多只取一个变化最剧烈的切分点
    half = max(2, int(window // 2))
    candidates = []
    for i in range(n):
        if pd.isna(abs_change.iloc[i]) or abs_change.iloc[i] <= change_threshold:
            continue
        window_start = max(0, i - half)
        window_end = min(n, i + half + 1)
        if abs_change.iloc[i] == abs_change.iloc[window_start:window_end].max():
            candidates.append(i)
    if not candidates:
        return _single_phase(source, scene, metric_key, timestamps, values)

    # 合并过近的候选切分点，保留变化量最大的那个
    merged: list[int] = []
    for i in candidates:
        if merged and (timestamps.iloc[i] - timestamps.iloc[merged[-1]]).total_seconds() / 60 < min_phase_minutes:
            if abs_change.iloc[i] > abs_change.iloc[merged[-1]]:
                merged[-1] = i
        else:
            merged.append(i)

    # 构建边界并剔除过近边界，保证每段不小于 min_phase_minutes
    boundaries = [0] + sorted(merged) + [n - 1]
    final: list[int] = []
    for b in boundaries:
        if final and (timestamps.iloc[b] - timestamps.iloc[final[-1]]).total_seconds() / 60 < min_phase_minutes:
            continue
        final.append(b)
    if final[-1] != n - 1:
        final.append(n - 1)

    scene_mean = float(values.mean())
    segments: list[dict] = []
    for phase_no, (start_idx, end_idx) in enumerate(zip(final[:-1], final[1:]), start=1):
        seg_values = values.iloc[start_idx : end_idx + 1]
        seg_mean = float(seg_values.mean())
        if seg_mean <= scene_mean * 0.5:
            label = "低负载"
        elif seg_mean >= scene_mean * 1.5:
            label = "压力"
        else:
            label = "稳定"
        if phase_no == 1 and seg_mean < scene_mean:
            label = "预热" if label == "低负载" else "预热/稳定"
        segments.append(
            {
                "数据源": source,
                "场景": scene,
                "标签": label,
                "开始时间": timestamps.iloc[start_idx],
                "结束时间": timestamps.iloc[end_idx],
                "均值": seg_mean,
                "峰值": float(seg_values.max()),
                "P95": percentile_95(seg_values),
            }
        )

    # 合并相邻同标签的碎片段（例如 压力/稳定/稳定 -> 压力/稳定）
    merged_segments: list[dict] = []
    for segment in segments:
        if merged_segments and merged_segments[-1]["标签"] == segment["标签"]:
            merged_segments[-1]["结束时间"] = segment["结束时间"]
            merged_segments[-1]["均值"] = (merged_segments[-1]["均值"] + segment["均值"]) / 2
            merged_segments[-1]["峰值"] = max(merged_segments[-1]["峰值"], segment["峰值"])
        else:
            merged_segments.append(dict(segment))
    rows = []
    for phase_no, segment in enumerate(merged_segments, start=1):
        duration_minutes = float((segment["结束时间"] - segment["开始时间"]).total_seconds() / 60)
        rows.append(
            {
                "数据源": segment["数据源"],
                "场景": segment["场景"],
                "阶段序号": phase_no,
                "标签": segment["标签"],
                "开始时间": segment["开始时间"],
                "结束时间": segment["结束时间"],
                "持续时长": format_duration(duration_minutes),
                "指标": metric_key,
                "均值": segment["均值"],
                "峰值": segment["峰值"],
                "P95": segment["P95"],
            }
        )
    return pd.DataFrame(rows)


def phase_overlay_figure(
    data: pd.DataFrame,
    source: str,
    scene: str,
    metric_key: str,
    fig,
    min_phase_minutes: float = 1.0,
):
    """在已有 Plotly Figure 上叠加阶段着色区域与边界线，返回 (图, 阶段表)。"""
    phases = detect_phases(data, source, scene, metric_key, min_phase_minutes=min_phase_minutes)
    if phases.empty:
        return fig, phases
    color_map = {"预热": "rgba(74,144,226,0.12)", "低负载": "rgba(74,144,226,0.12)", "稳定": "rgba(22,163,74,0.10)", "压力": "rgba(220,38,38,0.14)", "预热/稳定": "rgba(74,144,226,0.10)", "单一阶段": "rgba(128,128,128,0.08)"}
    for _, phase in phases.iterrows():
        start = phase["开始时间"]
        end = phase["结束时间"]
        color = color_map.get(phase["标签"], "rgba(128,128,128,0.10)")
        fig.add_vrect(x0=start, x1=end, fillcolor=color, line_width=0, layer="below")
        fig.add_vline(x=start, line_dash="dot", line_color="#888", line_width=1)
    return fig, phases
