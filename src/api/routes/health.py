"""健康检查与 Prometheus 指标暴露。"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src import __version__
from src.api.schemas import HealthResponse
from src.config import get_settings
from src.core.job_store import job_store
from src.core.redis_client import get_redis

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
@router.get("/healthz", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=__version__,
        llm_configured=bool(settings.llm_api_key.strip()),
    )


@router.get("/readyz")
def readyz() -> dict:
    """就绪探针：看 Redis / 任务存储是否可用（celery 模式更依赖 Redis）。"""
    settings = get_settings()
    redis_ok = get_redis() is not None
    ready = True
    if settings.use_celery and not redis_ok:
        ready = False
    return {
        "ready": ready,
        "task_backend": settings.task_backend,
        "job_store": job_store.backend,
        "redis": redis_ok,
        "storage": settings.storage_backend,
    }


@router.get("/metrics")
def metrics() -> Response:
    """Prometheus 抓取端点。"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
