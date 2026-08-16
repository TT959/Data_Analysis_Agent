"""任务完成后的统一收尾：存产物、写缓存、回写会话历史。"""

from __future__ import annotations

from src.core.job_store import job_store
from src.core.result_cache import set_cached_result
from src.core.session_store import session_store
from src.infrastructure.storage import sync_job_artifacts
from src.state import AnalysisState, JobStatus
from src.utils.logging import get_logger

logger = get_logger(__name__)


def finalize_job_result(state: AnalysisState) -> AnalysisState:
    if state.status == JobStatus.SUCCEEDED:
        paths = [c.path for c in state.charts]
        if state.report_path:
            paths.append(state.report_path)
        if state.data_path:
            paths.append(state.data_path)
        keys = sync_job_artifacts(state.job_id, paths)
        state.add_trace("artifacts_synced", keys=keys)
        job_store.update(state)
        set_cached_result(state.data_path, state.question, state)

    # 成功/失败都尽量回写会话，方便用户看到该轮状态
    try:
        session_store.append_turn_from_job(state)
    except Exception as exc:  # noqa: BLE001
        logger.warning("session_append_failed job_id=%s err=%s", state.job_id, exc)
    return state
