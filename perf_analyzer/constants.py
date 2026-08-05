from __future__ import annotations

from pathlib import Path

from .models import Metric


SAMPLE_FILE = Path("data/sample_resource_consumption.xlsx")
GENERIC_SAMPLE_FILE = Path("data/generic_timeseries_samples/generic_sensor_measurements.xlsx")
PERFORMANCE_MODE = "应用性能"
GENERIC_MODE = "通用时序"
ANALYSIS_MODES = (PERFORMANCE_MODE, GENERIC_MODE)
PLOTLY_COLORWAY = [
    "#2563eb",
    "#dc2626",
    "#16a34a",
    "#f59e0b",
    "#7c3aed",
    "#0891b2",
    "#db2777",
    "#65a30d",
    "#ea580c",
    "#4f46e5",
]
PLOTLY_AXIS_STYLE = {
    "showgrid": True,
    "gridcolor": "#e5e7eb",
    "zerolinecolor": "#d1d5db",
    "linecolor": "#d1d5db",
    "tickcolor": "#9ca3af",
}

TIME_KEYS = ("时间", "timestamp", "time", "date")
CPU_KEYS = ("cpu", "CPU")
MEMORY_KEYS = ("内存占用", "memory", "mem", "rss", "working")
TOTAL_MEMORY_KEYS = ("系统总内存", "total memory", "total_memory", "物理内存")
MEMORY_PERCENT_KEYS = ("内存占用百分比", "memory percent", "memory%", "mem%", "内存%")
THREAD_KEYS = ("线程", "thread")
HANDLE_KEYS = ("句柄", "handle")
IO_KEYS = ("io", "i/o", "读写", "磁盘")
QPS_KEYS = ("qps", "每秒请求", "请求吞吐")
TPS_KEYS = ("tps", "每秒事务", "事务吞吐")
TASK_COUNT_KEYS = ("任务数", "处理条数", "task", "processed", "records")
CONCURRENCY_KEYS = ("并发", "concurrency", "connections", "连接数", "用户数")
RESPONSE_TIME_KEYS = ("响应时间", "response", "latency", "耗时", "duration")
ERROR_COUNT_KEYS = ("错误数", "error", "失败数", "fail")
FPS_KEYS = ("fps", "帧率")
JANK_COUNT_KEYS = ("卡顿", "jank", "stutter")
GC_COUNT_KEYS = ("gc次数", "gc count", "gc_count")
GC_TIME_KEYS = ("gc耗时", "gc time", "gc_time")
HEAP_KEYS = ("堆内存", "heap")
NETWORK_UP_KEYS = ("网络上行", "上行", "upload", "network up", "tx")
NETWORK_DOWN_KEYS = ("网络下行", "下行", "download", "network down", "rx")
REQUEST_COUNT_KEYS = ("请求数", "request count", "requests")
FAILED_REQUEST_KEYS = ("失败请求", "failed request", "request fail")
RETRY_COUNT_KEYS = ("重试", "retry")
DISK_READ_KEYS = ("磁盘读", "disk read", "read mb")
DISK_WRITE_KEYS = ("磁盘写", "disk write", "write mb")
IOPS_KEYS = ("iops", "io次数")
IO_WAIT_KEYS = ("io等待", "io wait", "iowait")
MAPPING_FIELDS = {
    "timestamp": ("时间戳", TIME_KEYS),
    "cpu_percent": ("CPU%", CPU_KEYS),
    "memory_mb": ("内存占用（MB）", MEMORY_KEYS),
    "total_memory_mb": ("系统总内存", TOTAL_MEMORY_KEYS),
    "memory_percent": ("内存占用百分比", MEMORY_PERCENT_KEYS),
    "threads": ("线程", THREAD_KEYS),
    "handles": ("句柄", HANDLE_KEYS),
    "io": ("io", IO_KEYS),
    "qps": ("QPS", QPS_KEYS),
    "tps": ("TPS", TPS_KEYS),
    "task_count": ("任务数/处理条数", TASK_COUNT_KEYS),
    "concurrency": ("并发数/连接数", CONCURRENCY_KEYS),
    "response_time_ms": ("响应时间(ms)", RESPONSE_TIME_KEYS),
    "error_count": ("错误数", ERROR_COUNT_KEYS),
    "fps": ("FPS", FPS_KEYS),
    "jank_count": ("卡顿次数", JANK_COUNT_KEYS),
    "gc_count": ("GC次数", GC_COUNT_KEYS),
    "gc_time_ms": ("GC耗时(ms)", GC_TIME_KEYS),
    "heap_mb": ("堆内存(MB)", HEAP_KEYS),
    "network_up_kbps": ("网络上行(KB/s)", NETWORK_UP_KEYS),
    "network_down_kbps": ("网络下行(KB/s)", NETWORK_DOWN_KEYS),
    "request_count": ("请求数", REQUEST_COUNT_KEYS),
    "failed_requests": ("失败请求数", FAILED_REQUEST_KEYS),
    "retry_count": ("重试次数", RETRY_COUNT_KEYS),
    "disk_read_mbps": ("磁盘读(MB/s)", DISK_READ_KEYS),
    "disk_write_mbps": ("磁盘写(MB/s)", DISK_WRITE_KEYS),
    "iops": ("IOPS", IOPS_KEYS),
    "io_wait_ms": ("IO等待(ms)", IO_WAIT_KEYS),
}

CORE_METRICS = [
    Metric("cpu_percent", "CPU", "%", "CPU 告警阈值", 80.0),
    Metric("memory_mb", "内存占用", "MB", "内存告警阈值", 2048.0),
    Metric("memory_percent", "内存占比", "%", "内存占比告警阈值", 70.0),
    Metric("threads", "线程", "个", "线程告警阈值", 120.0),
    Metric("handles", "句柄", "个", "句柄告警阈值", 1500.0),
    Metric("io", "IO", "", "IO 告警阈值", 8.0),
]
CORE_METRIC_KEYS = {metric.key for metric in CORE_METRICS}
SEMANTIC_METRICS = [
    Metric("qps", "QPS", "", "QPS 告警阈值", 10.0, higher_is_worse=False),
    Metric("tps", "TPS", "", "TPS 告警阈值", 10.0, higher_is_worse=False),
    Metric("task_count", "任务数", "个", "任务数告警阈值", 10.0, higher_is_worse=False),
    Metric("concurrency", "并发数", "个", "并发告警阈值", 100.0),
    Metric("response_time_ms", "响应时间", "ms", "响应时间告警阈值", 1000.0),
    Metric("error_count", "错误数", "个", "错误数告警阈值", 1.0),
    Metric("fps", "FPS", "", "FPS 告警阈值", 45.0, higher_is_worse=False),
    Metric("jank_count", "卡顿次数", "次", "卡顿次数告警阈值", 1.0),
    Metric("gc_count", "GC次数", "次", "GC次数告警阈值", 10.0),
    Metric("gc_time_ms", "GC耗时", "ms", "GC耗时告警阈值", 100.0),
    Metric("heap_mb", "堆内存", "MB", "堆内存告警阈值", 1024.0),
    Metric("network_up_kbps", "网络上行", "KB/s", "网络上行告警阈值", 1024.0),
    Metric("network_down_kbps", "网络下行", "KB/s", "网络下行告警阈值", 4096.0),
    Metric("request_count", "请求数", "个", "请求数告警阈值", 1000.0, higher_is_worse=False),
    Metric("failed_requests", "失败请求数", "个", "失败请求告警阈值", 1.0),
    Metric("retry_count", "重试次数", "次", "重试次数告警阈值", 1.0),
    Metric("disk_read_mbps", "磁盘读", "MB/s", "磁盘读告警阈值", 100.0),
    Metric("disk_write_mbps", "磁盘写", "MB/s", "磁盘写告警阈值", 100.0),
    Metric("iops", "IOPS", "", "IOPS 告警阈值", 1000.0),
    Metric("io_wait_ms", "IO等待", "ms", "IO等待告警阈值", 50.0),
]
STANDARD_METRICS = [*CORE_METRICS, *SEMANTIC_METRICS]
META_COLUMNS = {"timestamp", "source", "scene", "display_scene"}
CONFIG_TOP_LEVEL_KEYS = {"version", "mode", "fields", "analysis", "metrics", "ui", "notes", "description", "_comment"}
CONFIG_ANALYSIS_KEYS = {"mode", "group_label", "memory_leak_slope_threshold", "warmup_minutes", "risk_rules", "notes", "description", "_comment"}
CONFIG_UI_SECTIONS = {
    "trend",
    "alerts",
    "version_compare",
    "decision",
    "capacity",
    "configuration_recommendation",
    "baseline_growth",
    "distribution",
    "efficiency",
    "sampling_interval",
    "filters",
    "notes",
    "description",
    "_comment",
}
CONFIG_METRIC_KEYS = {
    "label",
    "unit",
    "threshold",
    "threshold_label",
    "direction",
    "scale",
    "lower_threshold",
    "upper_threshold",
    "lower",
    "upper",
    "min_threshold",
    "max_threshold",
    "notes",
    "description",
    "_comment",
}

REPORT_SECTIONS = {
    "conclusions": "测试结论",
    "decision": "决策分析",
    "release_gate": "发布门禁",
    "stability": "稳定性评分",
    "bottleneck": "瓶颈提示",
    "summary": "汇总数据",
    "alert_continuity": "告警持续性摘要",
    "segments": "异常段",
    "leak": "内存趋势检测",
    "trend_slope": "全指标趋势斜率",
    "efficiency": "资源效率",
    "config_recommendation": "配置建议",
}
REPORT_SECTIONS_GENERIC = {
    "conclusions": "分析结论",
    "summary": "汇总数据",
    "alert_continuity": "告警持续性摘要",
    "segments": "异常段",
    "trend_slope": "全指标趋势斜率",
}
REPORT_SECTIONS_ALWAYS = {"conclusions", "methodology"}
FILTER_OPERATORS = (">", ">=", "<", "<=", "==", "!=")
