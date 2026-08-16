"""Celery 应用实例：Broker/Backend 使用 Redis，供 API 入队与 Worker 消费。"""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_ready
from prometheus_client import start_http_server

from src.config import get_settings
from src.utils.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)

celery_app = Celery(
    "analyst",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["src.worker.tasks"],
)

# 软超时触发 SoftTimeLimitExceeded（tasks.py 会标 timed_out）；
# 硬超时略长，防止进程彻底卡死。
_soft = max(1, int(settings.job_timeout_seconds))
_hard = _soft + 60

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_default_queue=settings.celery_queue,
    task_soft_time_limit=_soft,
    task_time_limit=_hard,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
)


@worker_ready.connect
def _start_worker_metrics(**_kwargs) -> None:
    port = int(get_settings().worker_metrics_port)
    if port <= 0:
        return
    try:
        start_http_server(port)
    except OSError as exc:
        logger.warning("worker_metrics_bind_failed port=%s err=%s", port, exc)
        return
    logger.info("worker_metrics_listening http://127.0.0.1:%s/", port)
