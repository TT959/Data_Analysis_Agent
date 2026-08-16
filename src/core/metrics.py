"""Prometheus 指标：任务次数和耗时。"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

# 任务终态计数：succeeded / failed / timed_out ...
JOBS_TOTAL = Counter(
    "analyst_jobs_total",
    "分析任务终态计数",
    ["status"],
)

# 流水线耗时（秒）
JOB_DURATION_SECONDS = Histogram(
    "analyst_job_duration_seconds",
    "分析任务耗时",
    buckets=(5, 15, 30, 60, 120, 300, 600, 1200),
)

# 按错误类别计数
ERRORS_TOTAL = Counter(
    "analyst_errors_total",
    "错误计数",
    ["category", "code"],
)
