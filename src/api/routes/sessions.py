"""
会话 API：同一份数据上保存历史并支持追问。
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from src.api.deps import require_api_key
from src.api.routes.analysis import _enqueue_job
from src.api.schemas import (
    SessionAskAccepted,
    SessionAskRequest,
    SessionCreated,
    SessionDetailResponse,
    SessionTurnResponse,
)
from src.config import get_settings
from src.core.errors import ErrorCode
from src.core.job_store import job_store
from src.core.session_store import build_conversation_history, session_store
from src.state import AnalysisSession, AnalysisState, JobStatus, SessionTurn
from src.utils.files import save_upload
from src.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["sessions"])

# 分析还没跑完时，先在 session.turns 里插一条「排队中」记录。
def _pending_turn(session: AnalysisSession, job_id: str, question: str) -> SessionTurn:
    
    return SessionTurn(
        turn_id=len(session.turns) + 1,
        job_id=job_id,
        question=question,
        status=JobStatus.QUEUED.value,
    )


@router.post("/sessions", response_model=SessionCreated)
async def create_session(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="CSV 或 XLSX，会话内后续追问复用该文件"),
    question: str | None = Form(
        default=None, description="可选：创建会话时同时发起第一轮分析"
    ),
    _api_key: str = Depends(require_api_key),
) -> SessionCreated:
    settings = get_settings()
    session_id = uuid4().hex
    # 文件挂在 session 目录下，后续多轮共用同一路径
    saved = await save_upload(file, f"sessions/{session_id}", settings)

    session = AnalysisSession(
        session_id=session_id,
        data_path=str(saved),
        original_filename=saved.name,
    )
    session_store.save(session)
    logger.info("session_created session_id=%s file=%s", session_id, saved.name)

    job_id = None
    status = "created"
    message = "会话已创建。请调用 POST /api/v1/sessions/{session_id}/ask 继续提问"

    if question and question.strip():
        job_id = uuid4().hex
        turn = _pending_turn(session, job_id, question.strip())
        session.turns.append(turn)
        session_store.save(session)

        state = AnalysisState(
            job_id=job_id,
            session_id=session_id,
            question=question.strip(),
            data_path=str(saved),
            original_filename=saved.name,
            conversation_history=[],
            status=JobStatus.QUEUED,
        )
        state.add_trace("session_first_turn", session_id=session_id)
        job_store.save(state)
        _enqueue_job(job_id, background_tasks)
        status = JobStatus.QUEUED.value
        message = "会话已创建，第一轮分析已入队，请轮询 /api/v1/jobs/{job_id}"

    return SessionCreated(
        session_id=session_id,
        original_filename=saved.name,
        job_id=job_id,
        status=status,
        message=message,
    )

# 不重新上传，用会话里已有文件追问一轮
@router.post("/sessions/{session_id}/ask", response_model=SessionAskAccepted)
def ask_in_session(
    session_id: str,
    body: SessionAskRequest,
    background_tasks: BackgroundTasks,
    _api_key: str = Depends(require_api_key),
) -> SessionAskAccepted:
    if not body.question.strip():
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": ErrorCode.EMPTY_QUESTION.value,
                "message": "追问内容不能为空",
            },
        )

    session = session_store.get(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": ErrorCode.SESSION_NOT_FOUND.value,
                "message": f"会话不存在: {session_id}",
            },
        )

    history = build_conversation_history(session)
    job_id = uuid4().hex
    turn = _pending_turn(session, job_id, body.question.strip())
    session.turns.append(turn)
    session_store.save(session)

    state = AnalysisState(
        job_id=job_id,
        session_id=session_id,
        question=body.question.strip(),
        data_path=session.data_path,
        original_filename=session.original_filename,
        conversation_history=history,
        schema_info=session.schema_info or {},
        status=JobStatus.QUEUED,
    )
    state.add_trace(
        "session_follow_up",
        session_id=session_id,
        history_turns=len(history),
    )
    job_store.save(state)
    _enqueue_job(job_id, background_tasks)
    logger.info(
        "session_ask session_id=%s job_id=%s history=%s",
        session_id,
        job_id,
        len(history),
    )

    return SessionAskAccepted(
        session_id=session_id,
        job_id=job_id,
        status=JobStatus.QUEUED.value,
        turn_id=turn.turn_id,
        message="追问已受理，请轮询 /api/v1/jobs/{job_id}；完成后可在会话详情查看历史",
    )

# 只读查询，返回会话元数据 + 每一轮摘要
@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
def get_session(
    session_id: str, _api_key: str = Depends(require_api_key)
) -> SessionDetailResponse:
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": ErrorCode.SESSION_NOT_FOUND.value,
                "message": f"会话不存在: {session_id}",
            },
        )
    return SessionDetailResponse(
        session_id=session.session_id,
        original_filename=session.original_filename,
        data_path=session.data_path,
        turns=[
            SessionTurnResponse(
                turn_id=t.turn_id,
                job_id=t.job_id,
                question=t.question,
                status=t.status,
                findings_summary=t.findings_summary,
                report_summary=t.report_summary,
                report_path=t.report_path,
                charts=t.charts,
                created_at=t.created_at,
            )
            for t in session.turns
        ],
        created_at=session.created_at,
        updated_at=session.updated_at,
    )
