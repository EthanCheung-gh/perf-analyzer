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
    load_factor = np.clip(cpu / 100, 0.05, 1)
    qps = np.clip((100 - cpu_base) * 0.8 + rng.normal(0, 4, points) - load_factor * 12, 1, None)
    if "导入" in name:
        qps = np.clip(18 + rng.normal(0, 3, points), 1, None)
    if "空闲" in name:
        qps = np.clip(3 + rng.normal(0, 0.8, points), 0.2, None)
    concurrency = np.clip(np.round(qps * rng.uniform(1.8, 3.5) + rng.normal(0, 3, points)), 1, None).astype(int)
    response_time = np.clip(80 + cpu * 5 + io * 20 + rng.normal(0, 35, points), 30, None)
    error_count = rng.poisson(np.clip((response_time - 350) / 500, 0, 2))
    fps = np.clip(62 - cpu * 0.18 - rng.normal(0, 2, points), 18, 60)
    jank_count = rng.poisson(np.clip((45 - fps) / 12, 0, 3))
    gc_count = rng.poisson(np.clip(memory / 900, 0.2, 5))
    gc_time = np.clip(gc_count * rng.uniform(8, 22, points) + rng.normal(0, 3, points), 0, None)
    heap = np.clip(memory * rng.uniform(0.42, 0.58, points), 40, None)
    network_down = np.clip(qps * rng.uniform(18, 45, points) + rng.normal(0, 20, points), 0, None)
    network_up = np.clip(qps * rng.uniform(4, 14, points) + rng.normal(0, 8, points), 0, None)
    request_count = np.round(qps * 10).astype(int)
    failed_requests = np.minimum(error_count, request_count)
    retry_count = rng.poisson(np.clip(failed_requests * 0.6, 0, 3))
    disk_read = np.clip(io * rng.uniform(2.5, 7.5, points), 0, None)
    disk_write = np.clip(io * rng.uniform(1.2, 4.5, points), 0, None)
    iops = np.clip((disk_read + disk_write) * rng.uniform(12, 28, points), 0, None)
    io_wait = np.clip(io * rng.uniform(2.0, 8.0, points) + rng.normal(0, 3, points), 0, None)

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
            "QPS": np.round(qps, 2),
            "并发数": concurrency,
            "响应时间(ms)": np.round(response_time, 2),
            "错误数": error_count,
            "FPS": np.round(fps, 2),
            "卡顿次数": jank_count,
            "GC次数": gc_count,
            "GC耗时(ms)": np.round(gc_time, 2),
            "堆内存(MB)": np.round(heap, 2),
            "网络上行(KB/s)": np.round(network_up, 2),
            "网络下行(KB/s)": np.round(network_down, 2),
            "请求数": request_count,
            "失败请求数": failed_requests,
            "重试次数": retry_count,
            "磁盘读(MB/s)": np.round(disk_read, 2),
            "磁盘写(MB/s)": np.round(disk_write, 2),
            "IOPS": np.round(iops, 0),
            "IO等待(ms)": np.round(io_wait, 2),
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
