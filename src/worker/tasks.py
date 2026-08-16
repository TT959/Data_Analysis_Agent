"""Celery 任务定义：执行分析流水线。"""

from __future__ import annotations

import time

from celery.exceptions import SoftTimeLimitExceeded

from src.config import get_settings
from src.core.errors import ErrorCode
from src.core.job_store import job_store
from src.core.metrics import ERRORS_TOTAL, JOB_DURATION_SECONDS, JOBS_TOTAL
from src.core.job_finalize import finalize_job_result
from src.core.orchestrator import orchestrator
from src.state import JobStatus
from src.utils.logging import get_logger
from src.worker.celery_app import celery_app

logger = get_logger(__name__)

# 告诉 Celery这是一个可入队的任务
@celery_app.task(
    bind=True,
    name="analysis.run_job",
    max_retries=get_settings().job_max_retries,
    # 网络/瞬时错误可重试；业务逻辑失败一般不重试（在 run 内自行判断）
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
)
def run_analysis_job(self, job_id: str) -> dict:
    """Worker 入口：根据 job_id 拉取状态并跑 orchestrator。"""
    started = time.time()
    settings = get_settings()
    state = job_store.get(job_id)
    if not state:
        logger.error("celery_job_missing job_id=%s", job_id)
        return {"ok": False, "error": "JOB_NOT_FOUND"}

    try:
        logger.info("celery_job_start job_id=%s", job_id)
        result = orchestrator.run(state)
        finalize_job_result(result)

        JOBS_TOTAL.labels(status=result.status.value).inc()
        JOB_DURATION_SECONDS.observe(time.time() - started)
        return {"ok": result.status == JobStatus.SUCCEEDED, "status": result.status.value}

    except SoftTimeLimitExceeded:
        # 软超时：标记 timed_out，便于前端展示
        logger.error("celery_job_timeout job_id=%s", job_id)
        job_store.set_status(job_id, JobStatus.TIMED_OUT, error="任务执行超时")
        state = job_store.get(job_id)
        if state:
            state.error_code = ErrorCode.PIPELINE_TIMEOUT.value
            job_store.update(state)
            finalize_job_result(state)
        JOBS_TOTAL.labels(status=JobStatus.TIMED_OUT.value).inc()
        ERRORS_TOTAL.labels(category="internal", code=ErrorCode.PIPELINE_TIMEOUT.value).inc()
        JOB_DURATION_SECONDS.observe(time.time() - started)
        return {"ok": False, "error": "TIMEOUT"}

    except Exception as exc:  # noqa: BLE001
        logger.exception("celery_job_failed job_id=%s", job_id)
        # 有限次重试
        if self.request.retries < settings.job_max_retries:
            raise self.retry(exc=exc, countdown=5 * (self.request.retries + 1))
        job_store.set_status(job_id, JobStatus.FAILED, error=str(exc))
        state = job_store.get(job_id)
        if state:
            state.error_code = ErrorCode.PIPELINE_ERROR.value
            job_store.update(state)
            finalize_job_result(state)
        JOBS_TOTAL.labels(status=JobStatus.FAILED.value).inc()
        ERRORS_TOTAL.labels(category="internal", code=ErrorCode.PIPELINE_ERROR.value).inc()
        JOB_DURATION_SECONDS.observe(time.time() - started)
        return {"ok": False, "error": str(exc)}
