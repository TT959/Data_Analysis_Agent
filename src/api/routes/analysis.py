"""
分析任务 API：入队解耦 + 状态查询 + 产物下载。
对外提供 4 个能力：
POST /analyze — 上传文件 + 提问，开一张分析工单
GET /jobs/{id} — 用单号查做到哪了
GET /jobs/{id}/report — 下载报告
GET /jobs/{id}/charts/{name} — 下载某张图
"""

from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from src.api.deps import require_api_key
from src.api.schemas import AnalyzeAccepted, JobStatusResponse
from src.config import get_settings
from src.core.errors import ErrorCode
from src.core.job_store import job_store
from src.core.job_finalize import finalize_job_result
from src.core.metrics import JOBS_TOTAL, JOB_DURATION_SECONDS
from src.core.orchestrator import orchestrator
from src.core.result_cache import get_cached_result
from src.infrastructure.storage import get_storage
from src.state import AnalysisState, JobStatus
from src.utils.files import save_upload
from src.utils.logging import get_logger, job_id_ctx

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["analysis"])


def _run_job_inline(job_id: str) -> None:
    """memory 模式：仍在 API 进程内执行（无 Redis/Celery 时的兜底）。"""
    token = job_id_ctx.set(job_id)
    started = time.time()
    try:
        state = job_store.get(job_id)
        if not state:
            return
        result = orchestrator.run(state)
        finalize_job_result(result)
        JOBS_TOTAL.labels(status=result.status.value).inc()
        JOB_DURATION_SECONDS.observe(time.time() - started)
    finally:
        job_id_ctx.reset(token)


def _enqueue_job(job_id: str, background_tasks: BackgroundTasks) -> None:
    """按配置选择 Celery 入队或本地 BackgroundTasks。"""
    settings = get_settings()
    if settings.use_celery:
        try:
            from src.worker.tasks import run_analysis_job

            run_analysis_job.delay(job_id)
            logger.info("job_enqueued_celery job_id=%s", job_id)
            return
        except Exception as exc:  # noqa: BLE001
            logger.error("celery_enqueue_failed fallback_inline err=%s", exc)
            raise HTTPException(
                status_code=503,
                detail={
                    "error_code": ErrorCode.QUEUE_UNAVAILABLE.value,
                    "message": f"任务队列不可用: {exc}",
                },
            ) from exc

    # 默认：进程内异步（开发便捷，不适合生产多实例）
    background_tasks.add_task(_run_job_inline, job_id)
    logger.info("job_enqueued_inline job_id=%s", job_id)


@router.post("/analyze", response_model=AnalyzeAccepted)
async def analyze(
    background_tasks: BackgroundTasks,
    question: str = Form(..., description="分析问题"),
    file: UploadFile = File(..., description="CSV 或 XLSX 数据文件"),
    _api_key: str = Depends(require_api_key),
) -> AnalyzeAccepted:
    settings = get_settings()
    if not question.strip():
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": ErrorCode.EMPTY_QUESTION.value,
                "message": "分析问题不能为空",
            },
        )

    # 先落盘拿到路径，再查缓存（缓存键=文件内容哈希+问题）
    tmp_job_id = uuid4().hex
    saved = await save_upload(file, tmp_job_id, settings)

    cached = get_cached_result(str(saved), question.strip())
    if cached is not None:
        # 缓存命中：复制一份新 job_id 返回，避免撞车
        cached.job_id = uuid4().hex
        cached.status = JobStatus.SUCCEEDED
        cached.add_trace("served_from_cache", source_file=saved.name)
        job_store.save(cached)
        logger.info("analyze_cache_hit new_job_id=%s", cached.job_id)
        return AnalyzeAccepted(
            job_id=cached.job_id,
            status=cached.status.value,
            message="命中结果缓存，可直接查询报告/图表",
        )

    state = AnalysisState(
        job_id=tmp_job_id,
        question=question.strip(),
        data_path=str(saved),
        original_filename=saved.name,
        status=JobStatus.QUEUED,
    )
    state.add_trace("uploaded", path=str(saved))
    job_store.save(state)
    _enqueue_job(state.job_id, background_tasks)

    return AnalyzeAccepted(
        job_id=state.job_id,
        status=state.status.value,
        message="分析任务已受理，请轮询 /api/v1/jobs/{job_id}",
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str, _api_key: str = Depends(require_api_key)) -> JobStatusResponse:
    state = job_store.get(job_id)
    if not state:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": ErrorCode.JOB_NOT_FOUND.value,
                "message": f"任务不存在: {job_id}",
            },
        )
    return JobStatusResponse(
        job_id=state.job_id,
        status=state.status.value,
        stage=state.stage.value,
        question=state.question,
        original_filename=state.original_filename,
        error=state.error,
        error_code=state.error_code,
        report_path=state.report_path,
        charts=[c.model_dump() for c in state.charts],
        findings_count=len(state.findings),
        critic_passed=state.critic.passed if state.critic else None,
        critic_issues=list(state.critic.issues) if state.critic else [],
        critic_retry_stage=state.critic.retry_stage if state.critic else None,
        created_at=state.created_at,
        updated_at=state.updated_at,
    )


def _resolve_local_or_storage(job_id: str, path_or_name: str) -> Path | None:
    """优先本地文件；否则尝试从对象存储 jobs/{job_id}/{name} 拉到临时目录。"""
    path = Path(path_or_name)
    if path.exists():
        return path
    name = path.name
    local_candidates = [
        get_settings().reports_dir / name,
        get_settings().charts_dir / name,
        get_settings().upload_dir / job_id / name,
    ]
    for cand in local_candidates:
        if cand.exists():
            return cand

    storage = get_storage()
    key = f"jobs/{job_id}/{name}"
    if storage.exists(key):
        dest = get_settings().output_dir / "_download_cache" / job_id / name
        return storage.download_to_path(key, dest)
    return None


@router.get("/jobs/{job_id}/report")
def download_report(job_id: str, _api_key: str = Depends(require_api_key)):
    state = job_store.get(job_id)
    if not state:
        raise HTTPException(
            status_code=404,
            detail={"error_code": ErrorCode.JOB_NOT_FOUND.value, "message": "任务不存在"},
        )
    if state.status != JobStatus.SUCCEEDED or not state.report_path:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": ErrorCode.REPORT_NOT_READY.value,
                "message": "报告尚未生成",
            },
        )
    path = _resolve_local_or_storage(job_id, state.report_path)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": ErrorCode.REPORT_MISSING.value,
                "message": "报告文件丢失",
            },
        )
    return FileResponse(path, media_type="text/markdown", filename=path.name)


@router.get("/jobs/{job_id}/charts/{chart_name}")
def download_chart(
    job_id: str, chart_name: str, _api_key: str = Depends(require_api_key)
):
    state = job_store.get(job_id)
    if not state:
        raise HTTPException(
            status_code=404,
            detail={"error_code": ErrorCode.JOB_NOT_FOUND.value, "message": "任务不存在"},
        )

    allowed = {Path(c.path).name: c.path for c in state.charts}
    if chart_name not in allowed:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": ErrorCode.CHART_NOT_FOUND.value,
                "message": "图表不存在或不属于该任务",
            },
        )
    path = _resolve_local_or_storage(job_id, allowed[chart_name])
    if path is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": ErrorCode.CHART_MISSING.value,
                "message": "图表文件丢失",
            },
        )
    return FileResponse(path, media_type="image/png", filename=path.name)
