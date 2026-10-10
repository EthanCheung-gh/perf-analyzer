"""真实性能数据采集器：把 psutil 采样结果写成本工具可直接读取的 Excel。

结构约定（与 generate_sample_data.py / io.py 保持一致）：

- 第 1 个 sheet 为「系统信息」（展示用，不参与计算）；
- 之后每个 sheet 是一个采集场景，sheet 名即场景名；
- 表头使用 constants.MAPPING_FIELDS 的标准字段名，落到 Excel 后由页面自动识别。

业务口径字段（QPS、并发数、响应时间等）无法从进程外部采到，用 --metrics-file
挂接被测系统自己输出的 JSON / JSONL 快照，按同一套别名表映射进来。
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from .constants import (
    CONCURRENCY_KEYS,
    CPU_KEYS,
    DISK_READ_KEYS,
    DISK_WRITE_KEYS,
    ERROR_COUNT_KEYS,
    FAILED_REQUEST_KEYS,
    FPS_KEYS,
    GC_COUNT_KEYS,
    GC_TIME_KEYS,
    HANDLE_KEYS,
    HEAP_KEYS,
    IOPS_KEYS,
    IO_WAIT_KEYS,
    JANK_COUNT_KEYS,
    MEMORY_KEYS,
    MEMORY_PERCENT_KEYS,
    NETWORK_DOWN_KEYS,
    NETWORK_UP_KEYS,
    QPS_KEYS,
    REQUEST_COUNT_KEYS,
    RESPONSE_TIME_KEYS,
    RETRY_COUNT_KEYS,
    TASK_COUNT_KEYS,
    THREAD_KEYS,
    TPS_KEYS,
)
from .utils import clean_name, find_column, safe_filename

MB = 1024 * 1024
SYSTEM_INFO_SHEET = "系统信息"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# 采集器固定输出的标准列（顺序即 Excel 列序）。
FIXED_HEADERS = [
    "时间戳",
    "CPU%",
    "内存占用（MB）",
    "系统总内存",
    "内存占用百分比",
    "线程",
    "句柄",
    "io",
    "磁盘读(MB/s)",
    "磁盘写(MB/s)",
    "IOPS",
    "网络上行(KB/s)",
    "网络下行(KB/s)",
    "进程数",
    "上下文切换/秒",
]

# 只有 --metrics-file 里出现时才追加的语义化列。
BUSINESS_HEADERS = [
    "QPS",
    "TPS",
    "任务数",
    "并发数",
    "响应时间(ms)",
    "错误数",
    "FPS",
    "卡顿次数",
    "GC次数",
    "GC耗时(ms)",
    "堆内存(MB)",
    "请求数",
    "失败请求数",
    "重试次数",
    "IO等待(ms)",
]

# 表头 -> 别名表：直接复用页面识别用的常量，再补一批 JSON 快照常见的 snake_case 键，
# 保证「采集端字段名」和「页面识别规则」永远一致。
HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "CPU%": (*CPU_KEYS, "cpu_percent", "cpu_usage", "cpu_usage_percent"),
    "内存占用（MB）": (*MEMORY_KEYS, "memory_mb", "memory_used_mb", "rss_mb", "mem_mb"),
    "内存占用百分比": (*MEMORY_PERCENT_KEYS, "memory_percent", "memory_percentage", "mem_percent"),
    "线程": (*THREAD_KEYS, "threads", "thread_count", "num_threads"),
    "句柄": (*HANDLE_KEYS, "handles", "handle_count", "num_handles", "fds", "open_fds"),
    "QPS": (*QPS_KEYS, "qps"),
    "TPS": (*TPS_KEYS, "tps"),
    "任务数": (*TASK_COUNT_KEYS, "task_count", "tasks", "processed_count", "records"),
    "并发数": (*CONCURRENCY_KEYS, "concurrency", "concurrent_users", "connections", "users"),
    "响应时间(ms)": (*RESPONSE_TIME_KEYS, "response_time_ms", "response_time", "latency_ms", "latency", "duration_ms"),
    "错误数": (*ERROR_COUNT_KEYS, "error_count", "errors", "error_total"),
    "FPS": (*FPS_KEYS, "fps", "frame_rate"),
    "卡顿次数": (*JANK_COUNT_KEYS, "jank_count", "janks", "stutter_count"),
    "GC次数": (*GC_COUNT_KEYS, "gc_count", "gc_times"),
    "GC耗时(ms)": (*GC_TIME_KEYS, "gc_time_ms", "gc_time", "gc_cost_ms"),
    "堆内存(MB)": (*HEAP_KEYS, "heap_mb", "heap_memory_mb", "heap"),
    "网络上行(KB/s)": (*NETWORK_UP_KEYS, "network_up_kbps", "net_up_kbps", "upload_kbps", "tx_kbps"),
    "网络下行(KB/s)": (*NETWORK_DOWN_KEYS, "network_down_kbps", "net_down_kbps", "download_kbps", "rx_kbps"),
    "请求数": (*REQUEST_COUNT_KEYS, "request_count", "requests", "total_requests", "req_count"),
    "失败请求数": (*FAILED_REQUEST_KEYS, "failed_requests", "failed_request_count", "fail_requests", "failure_count"),
    "重试次数": (*RETRY_COUNT_KEYS, "retry_count", "retries", "retry_total"),
    "磁盘读(MB/s)": (*DISK_READ_KEYS, "disk_read_mbps", "disk_read", "read_mbps"),
    "磁盘写(MB/s)": (*DISK_WRITE_KEYS, "disk_write_mbps", "disk_write", "write_mbps"),
    "IOPS": (*IOPS_KEYS, "iops"),
    "IO等待(ms)": (*IO_WAIT_KEYS, "io_wait_ms", "iowait_ms"),
}

# 「内存占用（MB）」按页面同样的排除规则，避免被 memory_percent 之类抢走。
HEADER_EXCLUDE: dict[str, tuple[str, ...]] = {"内存占用（MB）": ("%", "百分比", "percent", "total", "总")}

# 页面核心列 io 的口径说明：磁盘读+写合计速率。
IO_NOTE = "io = 磁盘读+写合计速率(MB/s)，单位按采集工具口径解释"


def output_columns() -> list[str]:
    """采集器可能写入的全部列（固定列 + 语义化业务列）。"""
    return [*FIXED_HEADERS, *BUSINESS_HEADERS]


def build_system_info(
    app_name: str,
    app_version: str,
    device: str,
    sampling_interval: float,
    target_desc: str,
    extra: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """生成第 1 个 sheet：系统信息（展示用）。"""
    rows = {
        "项目": [
            "应用名称",
            "版本",
            "测试设备",
            "操作系统",
            "CPU",
            "系统内存",
            "采样间隔",
            "采集目标",
            "采集工具",
            "说明",
        ],
        "值": [
            app_name,
            app_version,
            device,
            describe_os(),
            describe_cpu(),
            describe_total_memory(),
            f"{sampling_interval:g} 秒",
            target_desc,
            "collect_performance_data.py (psutil)",
            IO_NOTE,
        ],
    }
    if extra:
        rows["项目"].extend(extra.keys())
        rows["值"].extend(extra.values())
    return pd.DataFrame(rows)


def map_metrics_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """把 JSON 快照里的键映射成标准表头；命中不了的键直接忽略。

    先精确匹配（整键相等），再做子串匹配（长别名优先），
    与页面 io.normalize_scene 的识别策略保持一致。
    """
    if not snapshot:
        return {}
    keys = [str(key) for key in snapshot.keys()]
    mapped: dict[str, Any] = {}
    for header, aliases in HEADER_ALIASES.items():
        column = find_column(keys, aliases, exclude=HEADER_EXCLUDE.get(header, ()))
        if column is not None:
            mapped[header] = snapshot[column]
    return mapped


def read_metrics_snapshot(path: str | Path) -> dict[str, Any]:
    """读取业务指标快照：.jsonl 取最后一行，.json 取对象本身或数组最后一个元素。"""
    file_path = Path(path)
    if not file_path.exists():
        return {}
    text = file_path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    try:
        if file_path.suffix.lower() in {".jsonl", ".ndjson"}:
            last = [line for line in text.splitlines() if line.strip()][-1]
            payload = json.loads(last)
        else:
            payload = json.loads(text)
            if isinstance(payload, list):
                payload = payload[-1] if payload else {}
        return payload if isinstance(payload, dict) else {}
    except (ValueError, json.JSONDecodeError):
        return {}


def new_sheet_name(existing: Sequence[str], base: str, max_length: int = 31) -> str:
    """sheet 名冲突时自动加 -2/-3 后缀，避免覆盖上一次采集的场景。"""
    name = safe_filename(base)[:max_length] or "场景"
    if name not in existing:
        return name
    index = 2
    while f"{name}-{index}" in existing:
        index += 1
    return f"{name}-{index}"[:max_length]


def build_frame(rows: Sequence[Mapping[str, Any]], business_headers: Sequence[str] = ()) -> pd.DataFrame:
    """把采样字典列表整理成列序固定的 DataFrame，空业务列补 NaN。"""
    columns = [*FIXED_HEADERS, *business_headers]
    frame = pd.DataFrame(list(rows), columns=columns)
    if not frame.empty:
        frame["时间戳"] = frame["时间戳"].astype(str)
    return frame


def write_workbook(
    path: str | Path,
    system_info: pd.DataFrame,
    scene_name: str,
    frame: pd.DataFrame,
    overwrite_sheet: bool = False,
) -> tuple[Path, str]:
    """写入 / 追加写入 Excel：首个 sheet 是系统信息，其余是场景 sheet。"""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if not file_path.exists():
        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            system_info.to_excel(writer, sheet_name=SYSTEM_INFO_SHEET, index=False)
            if not frame.empty:
                frame.to_excel(writer, sheet_name=scene_name, index=False)
        return file_path, scene_name

    from openpyxl import load_workbook

    with pd.ExcelWriter(file_path, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
        existing = set(load_workbook(file_path, read_only=True).sheetnames)
        if SYSTEM_INFO_SHEET not in existing:
            system_info.to_excel(writer, sheet_name=SYSTEM_INFO_SHEET, index=False)
            existing.add(SYSTEM_INFO_SHEET)
        target = scene_name if overwrite_sheet or scene_name not in existing else new_sheet_name(existing, scene_name)
        if not frame.empty:
            frame.to_excel(writer, sheet_name=target, index=False)
    return file_path, target


def describe_os() -> str:
    import platform

    return f"{platform.system()} {platform.release()} ({platform.machine()})"


def describe_cpu() -> str:
    """整机 CPU 的展示值，例如「8C/16T AMD Ryzen 7 255」。"""
    try:
        import psutil

        logical = psutil.cpu_count(logical=True)
        physical = psutil.cpu_count(logical=False)
        model = platform_cpu_model()
        cores = f"{physical}C/{logical}T" if physical else f"{logical}C/{logical}T"
        # 型号串可能带频率/显卡尾巴，取前两段即可
        short_model = " ".join(model.split()[:2]) if model else ""
        return " ".join(part for part in (cores, short_model) if part).strip()
    except Exception:  # pragma: no cover - 采集环境异常不该阻塞写表
        return "-"


def describe_total_memory() -> str:
    """整机内存的展示值：psutil.virtual_memory().total 是字节，按 GB 显示。"""
    try:
        import psutil

        total = psutil.virtual_memory().total
        return f"{total / 1024**3:.1f} GB"
    except Exception:  # pragma: no cover
        return "-"


def platform_cpu_model() -> str:
    try:
        import platform

        if platform.system() == "Linux":
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                if "model name" in line:
                    return line.split(":", 1)[1].strip()
            return ""
        return platform.processor() or ""
    except Exception:  # pragma: no cover
        return ""


def require_psutil() -> Any:
    try:
        import psutil
    except ImportError as error:  # pragma: no cover - 依赖缺失时给出可执行提示
        raise SystemExit(
            "缺少依赖 psutil，请先安装：python3 -m pip install psutil（或 pip install -r requirements.txt）"
        ) from error
    return psutil


class Sampler:
    """按固定间隔采样目标进程树 / 整机资源，并折算成工具可识别的列。"""

    def __init__(
        self,
        psutil: Any,
        processes: list[Any],
        interval: float,
        cpu_mode: str = "process",
        memory_mode: str = "rss",
        metrics_file: str | Path | None = None,
    ) -> None:
        self.psutil = psutil
        self.processes = [proc for proc in processes if proc.is_running()]
        self.interval = max(0.2, float(interval))
        self.cpu_mode = "machine" if not self.processes else cpu_mode
        self.memory_mode = memory_mode
        self.metrics_file = metrics_file
        self._disk_before: tuple[int, int, int, int] | None = None
        self._net_before: tuple[int, int] | None = None
        self._ctx_before: int | None = None
        self._prime()

    # ---- 内部工具 ----
    def _prime(self) -> None:
        """cpu_percent 首次调用只是建立基准，先空跑一次。"""
        for proc in self.processes:
            try:
                proc.cpu_percent(interval=None)
            except Exception:
                continue
        self.psutil.cpu_percent(interval=None)
        self._disk_before = self._disk_counters()
        self._net_before = self._net_counters()
        self._ctx_before = self._ctx_switches()

    def _disk_counters(self) -> tuple[int, int, int, int] | None:
        try:
            if self.processes:
                read_bytes = write_bytes = read_count = write_count = 0
                for proc in self.processes:
                    try:
                        counters = proc.io_counters()
                    except Exception:
                        continue
                    read_bytes += counters.read_bytes
                    write_bytes += counters.write_bytes
                    read_count += counters.read_count
                    write_count += counters.write_count
                return read_bytes, write_bytes, read_count, write_count
            counters = self.psutil.disk_io_counters()
            if counters is None:
                return None
            return counters.read_bytes, counters.write_bytes, counters.read_count, counters.write_count
        except Exception:
            return None

    def _net_counters(self) -> tuple[int, int] | None:
        try:
            counters = self.psutil.net_io_counters()
            return counters.bytes_sent, counters.bytes_recv
        except Exception:
            return None

    def _ctx_switches(self) -> int | None:
        try:
            stats = self.psutil.cpu_stats()
            return int(stats.ctx_switches)
        except Exception:
            return None

    def _system_threads(self) -> int | None:
        """整机口径：汇总全部进程的线程数（num_threads 在 /proc/<pid>/status 里，通常可读）。"""
        threads = 0
        try:
            processes = self.psutil.process_iter(["num_threads"])
        except Exception:
            return None
        for proc in processes:
            try:
                threads += int(proc.info.get("num_threads") or 0)
            except Exception:
                continue
        return threads or None

    def _system_handles(self) -> int | None:
        """整机口径的句柄数：优先取系统级已分配文件句柄（Linux /proc/sys/fs/file-nr）。

        拿不到系统级数据时，退化为累加可访问进程的 fd 数；全都不可访问才返回 None。
        """
        try:
            fields = Path("/proc/sys/fs/file-nr").read_text(encoding="utf-8").split()
            if fields:
                return int(fields[0])
        except Exception:
            pass
        total = 0
        readable = False
        try:
            processes = self.psutil.process_iter()
        except Exception:
            return None
        for proc in processes:
            try:
                total += int(proc.num_fds())
                readable = True
            except Exception:
                continue
        return total if readable else None

    @staticmethod
    def _rate(before: int | None, after: int | None, seconds: float) -> float | None:
        if before is None or after is None or after < before or seconds <= 0:
            return None
        return (after - before) / seconds

    # ---- 对外 ----
    def sample(self) -> dict[str, Any]:
        row: dict[str, Any] = {header: None for header in output_columns()}
        row["时间戳"] = datetime.now().strftime(TIMESTAMP_FORMAT)

        alive = [proc for proc in self.processes if proc.is_running()]
        self.processes = alive
        count = len(alive) if self.processes else 1

        if self.cpu_mode == "machine" or not self.processes:
            row["CPU%"] = round(float(self.psutil.cpu_percent(interval=None)), 2)
        else:
            values = []
            for proc in alive:
                try:
                    values.append(float(proc.cpu_percent(interval=None)))
                except Exception:
                    continue
            row["CPU%"] = round(sum(values) / len(values), 2) if values else None

        memory_mb = 0.0
        threads = 0
        handles: int | None = 0
        handle_denied = False
        for proc in alive:
            try:
                info = proc.memory_full_info()
                memory_mb += (info.uss if self.memory_mode == "uss" else info.rss) / MB
            except Exception:
                try:
                    memory_mb += proc.memory_info().rss / MB
                except Exception:
                    pass
            try:
                threads += int(proc.num_threads())
            except Exception:
                pass
            try:
                handles += int(proc.num_fds() if hasattr(proc, "num_fds") else proc.num_handles())
            except Exception:
                # 单个进程读不到 fd 不该中断整棵树的统计，标记后跳过
                handle_denied = True
                continue
        if handle_denied:
            handles = None

        if self.processes:
            row["内存占用（MB）"] = round(memory_mb, 2)
            row["线程"] = threads or None
            row["句柄"] = handles
        else:
            # 整机口径：内存取系统已用量，线程汇总全部进程，句柄取系统级已分配文件句柄
            used_mb = self.psutil.virtual_memory().used / MB
            row["内存占用（MB）"] = round(used_mb, 2)
            row["线程"] = self._system_threads()
            row["句柄"] = self._system_handles()

        total_mb = self.psutil.virtual_memory().total / MB
        row["系统总内存"] = round(total_mb, 2)
        if row["内存占用（MB）"] is not None:
            row["内存占用百分比"] = round(row["内存占用（MB）"] / total_mb * 100, 4)
        row["进程数"] = count

        disk_after = self._disk_counters()
        if disk_after and self._disk_before:
            read_mbps = self._rate(self._disk_before[0], disk_after[0], self.interval)
            write_mbps = self._rate(self._disk_before[1], disk_after[1], self.interval)
            read_iops = self._rate(self._disk_before[2], disk_after[2], self.interval)
            write_iops = self._rate(self._disk_before[3], disk_after[3], self.interval)
            row["磁盘读(MB/s)"] = None if read_mbps is None else round(read_mbps / MB, 3)
            row["磁盘写(MB/s)"] = None if write_mbps is None else round(write_mbps / MB, 3)
            row["IOPS"] = None if read_iops is None or write_iops is None else round(read_iops + write_iops, 1)
            if read_mbps is not None and write_mbps is not None:
                row["io"] = round((read_mbps + write_mbps) / MB, 3)
        self._disk_before = disk_after

        net_after = self._net_counters()
        if net_after and self._net_before:
            up = self._rate(self._net_before[0], net_after[0], self.interval)
            down = self._rate(self._net_before[1], net_after[1], self.interval)
            row["网络上行(KB/s)"] = None if up is None else round(up / 1024, 2)
            row["网络下行(KB/s)"] = None if down is None else round(down / 1024, 2)
        self._net_before = net_after

        ctx_after = self._ctx_switches()
        ctx_rate = self._rate(self._ctx_before, ctx_after, self.interval)
        row["上下文切换/秒"] = None if ctx_rate is None else round(ctx_rate, 1)
        self._ctx_before = ctx_after

        if self.metrics_file:
            row.update(map_metrics_snapshot(read_metrics_snapshot(self.metrics_file)))
        return row


def resolve_processes(psutil: Any, pid: int | None, name: str | None, include_children: bool) -> list[Any]:
    """按 PID / 进程名解析采集目标；同名多进程（ worker 集群）全部纳入聚合。"""
    if pid is not None:
        try:
            return [psutil.Process(int(pid))]
        except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
            raise SystemExit(f"PID {pid} 不存在或无权限访问：{error}") from error
    if not name:
        return []
    needle = name.lower()
    self_pid = psutil.Process().pid
    matched = []
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if proc.pid == self_pid:
                continue
            info = proc.info
            haystack = " ".join([str(info.get("name") or ""), *[str(item) for item in info.get("cmdline") or []]])
            if needle in haystack.lower():
                matched.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if include_children:
        expanded: dict[int, Any] = {proc.pid: proc for proc in matched}
        for proc in list(matched):
            try:
                for child in proc.children(recursive=True):
                    expanded[child.pid] = child
            except Exception:
                continue
        matched = list(expanded.values())
    return matched


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="采集应用资源消耗数据并写成 perf-analyzer 可直接上传的 Excel",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    target = parser.add_argument_group("采集目标（三选一）")
    group = target.add_mutually_exclusive_group()
    group.add_argument("--pid", type=int, help="目标进程 PID")
    group.add_argument("--name", help="目标进程名或命令行关键字，如 chrome / java / MyApp")
    group.add_argument("--system", action="store_true", help="采集整机（不绑定具体进程）")
    parser.add_argument("--children", action="store_true", help="--name 命中时连同子进程一起聚合")
    parser.add_argument("--interval", type=float, default=5.0, help="采样间隔（秒）")
    parser.add_argument("--duration", type=float, default=5.0, help="采集时长（分钟）；0 表示一直采到 Ctrl+C")
    parser.add_argument("--scenario", default="采集场景1", help="场景名，会成为 Excel sheet 名")
    parser.add_argument("--output", default="data/collected_performance.xlsx", help="输出 Excel 路径")
    parser.add_argument("--append", action="store_true", help="已存在文件时追加新场景 sheet，而不是覆盖文件")
    parser.add_argument("--overwrite-sheet", action="store_true", help="追加时若同名场景 sheet 已存在则覆盖它")
    parser.add_argument("--cpu-mode", choices=("process", "machine"), default="process",
                        help="CPU%% 口径：process=单进程相对单核（可超 100）；machine=整机总利用率（0-100，配置建议页口径）")
    parser.add_argument("--memory-mode", choices=("rss", "uss"), default="rss", help="内存口径：常驻内存或独占内存")
    parser.add_argument("--metrics-file", help="被测系统输出的业务指标 JSON/JSONL 快照，按标准字段名映射进表")
    parser.add_argument("--app-name", default="", help="系统信息：应用名称")
    parser.add_argument("--app-version", default="", help="系统信息：版本")
    parser.add_argument("--device", default="", help="系统信息：测试设备")
    parser.add_argument("--note", default="", help="系统信息：补充说明")
    parser.add_argument("--flush-samples", type=int, default=200, help="每积累多少行自动落盘一次")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    psutil = require_psutil()
    processes = [] if args.system else resolve_processes(psutil, args.pid, args.name, args.children)

    if not args.system and not processes:
        print(f"未找到目标进程（pid={args.pid}, name={args.name}）。可先用 --system 试采，或用 --pid 指定。")
        return 2

    if args.system:
        target_desc = "整机"
    else:
        label = args.name or f"pid={args.pid}"
        target_desc = f"{label}（进程数 {len(processes)}）"
        print(f"目标进程 {len(processes)} 个：" + ", ".join(f"{p.pid}:{p.name()}" for p in processes[:8]))

    sampler = Sampler(
        psutil,
        processes,
        interval=args.interval,
        cpu_mode=args.cpu_mode,
        memory_mode=args.memory_mode,
        metrics_file=args.metrics_file,
    )

    business_headers = [header for header in BUSINESS_HEADERS if args.metrics_file]
    system_info = build_system_info(
        app_name=args.app_name or (args.name or "整机"),
        app_version=args.app_version or "-",
        device=args.device or describe_os(),
        sampling_interval=args.interval,
        target_desc=target_desc,
        extra={"补充说明": args.note} if args.note else None,
    )

    interval = max(0.2, float(args.interval))
    total_seconds = float(args.duration) * 60.0
    started = time.monotonic()
    rows: list[dict[str, Any]] = []
    frame = build_frame(rows, business_headers)
    written: tuple[Path, str] | None = None

    print(f"开始采集：间隔 {interval:g}s，时长 {args.duration:g} 分钟，场景「{args.scenario}」，输出 {args.output}")
    if args.cpu_mode == "process" and not args.system:
        print("提示：当前 CPU% 为进程相对单核口径（可能 >100）；配置建议页的 CPU 核数估算需要整机口径，请用 --cpu-mode machine 另采一份。")
    try:
        while True:
            if total_seconds > 0 and time.monotonic() - started >= total_seconds:
                break
            time.sleep(interval)
            row = sampler.sample()
            rows.append(row)
            frame = build_frame(rows, business_headers)
            if not args.system and not sampler.processes:
                print("警告：目标进程已全部退出，继续按空值采样以保留时间轴；Ctrl+C 可提前结束。")
            if args.flush_samples > 0 and len(rows) % args.flush_samples == 0:
                written = write_workbook(args.output, system_info, args.scenario, frame, overwrite_sheet=args.overwrite_sheet)
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，提前结束采集。")

    if not rows:
        print("没有采集到任何样本，未写出文件。")
        return 1

    written = write_workbook(args.output, system_info, args.scenario, frame, overwrite_sheet=args.overwrite_sheet)
    elapsed = time.monotonic() - started
    print(f"采集完成：{len(rows)} 个样本 / {elapsed / 60:.1f} 分钟 → {written[0]}（场景 sheet：{written[1]}）")
    print("上传到页面即可分析；如需多场景对比，换 --scenario 名称并加 --append 采集多次。")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
