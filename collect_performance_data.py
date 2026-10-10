#!/usr/bin/env python3
"""命令行入口：采集真实性能数据并生成本工具可直接上传的 Excel。

示例：
    # 采整机 10 分钟，间隔 5 秒
    python3 collect_performance_data.py --system --interval 5 --duration 10

    # 采指定进程（连同子进程）30 秒，另挂业务指标快照
    python3 collect_performance_data.py --name java --children \
        --scenario 压测-重载 --metrics-file /tmp/app_metrics.json

依赖：psutil（pip install psutil）
"""

from __future__ import annotations

from perf_analyzer.collector import main


if __name__ == "__main__":
    raise SystemExit(main())
