from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


OUTPUT = Path("data/sample_resource_consumption.xlsx")


def make_scenario(
    name: str,
    start: str,
    minutes: int,
    cpu_base: float,
    memory_base: float,
    memory_growth: float,
    io_base: float,
    seed: int,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    points = minutes * 6
    timestamp = pd.date_range(start=start, periods=points, freq="10s")
    x = np.linspace(0, 1, points)

    cpu = (
        cpu_base
        + 8 * np.sin(np.linspace(0, 8 * np.pi, points))
        + rng.normal(0, 5, points)
    )
    spike_count = max(2, points // 80)
    spike_idx = rng.choice(points, size=spike_count, replace=False)
    cpu[spike_idx] += rng.uniform(18, 38, spike_count)
    cpu = np.clip(cpu, 1, 100)

    total_memory = np.full(points, 16384)
    memory = memory_base + memory_growth * x + rng.normal(0, 45, points)
    memory += np.maximum(0, np.sin(np.linspace(0, 5 * np.pi, points))) * 80
    memory = np.clip(memory, 80, total_memory * 0.9)
    memory_pct = memory / total_memory * 100

    threads = np.round(42 + cpu_base / 4 + 5 * x + rng.normal(0, 2, points)).astype(int)
    handles = np.round(680 + memory / 3 + rng.normal(0, 35, points)).astype(int)
    io = np.clip(io_base + rng.gamma(2.0, 0.35, points), 0, None)
    io[spike_idx] += rng.uniform(2, 8, spike_count)

    return pd.DataFrame(
        {
            "时间戳": timestamp,
            "CPU%": np.round(cpu, 2),
            "内存占用（MB）": np.round(memory, 2),
            "系统总内存": total_memory,
            "内存占用百分比": np.round(memory_pct, 2),
            "线程": threads,
            "句柄": handles,
            "io": np.round(io, 2),
            "场景": name,
        }
    )


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    system_info = pd.DataFrame(
        {
            "项目": [
                "应用名称",
                "版本",
                "测试设备",
                "操作系统",
                "CPU",
                "系统内存",
                "采样间隔",
                "说明",
            ],
            "值": [
                "DemoApp",
                "1.8.0",
                "Perf Lab PC",
                "Windows 11 23H2",
                "8C/16T",
                "16 GB",
                "10 秒",
                "自动生成的资源消耗示例数据",
            ],
        }
    )

    scenarios = [
        make_scenario("冷启动", "2026-06-13 09:00:00", 18, 32, 720, 260, 1.2, 7),
        make_scenario("首页浏览", "2026-06-13 10:00:00", 45, 24, 980, 180, 0.8, 13),
        make_scenario("大数据导入", "2026-06-13 11:00:00", 55, 58, 1350, 980, 4.5, 29),
        make_scenario("后台空闲", "2026-06-13 13:00:00", 60, 9, 860, 60, 0.25, 41),
    ]

    with pd.ExcelWriter(OUTPUT, engine="openpyxl") as writer:
        system_info.to_excel(writer, sheet_name="系统信息", index=False)
        for scenario in scenarios:
            sheet_name = str(scenario["场景"].iloc[0])
            scenario.drop(columns=["场景"]).to_excel(writer, sheet_name=sheet_name, index=False)

    print(f"created {OUTPUT}")


if __name__ == "__main__":
    main()
