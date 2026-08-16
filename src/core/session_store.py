"""
会话存储：同一份数据上的多轮追问历史。

"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

from src.config import get_settings
from src.core.redis_client import get_redis
from src.state import (
    AnalysisSession,
    AnalysisState,
    ConversationTurnSummary,
    SessionTurn,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)

_SESSION_KEY = "analyst:session:{session_id}"
# 追问时最多带入最近几轮，控制 prompt 体积
MAX_HISTORY_TURNS = 3


def summarize_job_for_history(state: AnalysisState) -> tuple[str, str]:
    """从任务结果生成简短摘要，供后续轮次注入上下文。"""
    notes = [f.note.strip() for f in state.findings if f.note.strip()]
    findings_summary = " | ".join(notes[:5])[:1200]
    report = (state.report_markdown or "").strip()
    # 报告只取前几段，避免历史爆炸
    report_summary = report[:1200]
    return findings_summary, report_summary


def build_conversation_history(
    session: AnalysisSession, max_turns: int = MAX_HISTORY_TURNS
) -> List[ConversationTurnSummary]:
    """取最近成功轮次，转成 Agent 可用的历史摘要。"""
    succeeded = [t for t in session.turns if t.status == "succeeded"]
    recent = succeeded[-max_turns:]
    return [
        ConversationTurnSummary(
            question=t.question,
            findings_summary=t.findings_summary,
            report_summary=t.report_summary,
        )
        for t in recent
    ]


class MemorySessionStore:
    def __init__(self) -> None:
        self._sessions: Dict[str, AnalysisSession] = {}
        self._lock = threading.RLock()

    def save(self, session: AnalysisSession) -> AnalysisSession:
        with self._lock:
            session.touch()
            self._sessions[session.session_id] = session
            return session

    def get(self, session_id: str) -> Optional[AnalysisSession]:
        with self._lock:
            return self._sessions.get(session_id)


class RedisSessionStore:
    def __init__(self, client) -> None:
        self._client = client
        self._ttl = get_settings().job_ttl_seconds

    def _key(self, session_id: str) -> str:
        return _SESSION_KEY.format(session_id=session_id)

    def save(self, session: AnalysisSession) -> AnalysisSession:
        session.touch()
        self._client.set(
            self._key(session.session_id),
            session.model_dump_json(),
            ex=self._ttl,
        )
        return session

    def get(self, session_id: str) -> Optional[AnalysisSession]:
        raw = self._client.get(self._key(session_id))
        if not raw:
            return None
        return AnalysisSession.model_validate_json(raw)


class SessionStore:
    def __init__(self) -> None:
        client = get_redis()
        if client is not None:
            self._impl: MemorySessionStore | RedisSessionStore = RedisSessionStore(client)
            logger.info("session_store_backend=redis")
        else:
            self._impl = MemorySessionStore()
            logger.info("session_store_backend=memory")

    def save(self, session: AnalysisSession) -> AnalysisSession:
        return self._impl.save(session)

    def get(self, session_id: str) -> Optional[AnalysisSession]:
        return self._impl.get(session_id)

    def append_turn_from_job(self, state: AnalysisState) -> None:
        """任务结束后，把本轮结果写回所属会话。"""
        if not state.session_id:
            return
        session = self.get(state.session_id)
        if not session:
            logger.warning("session_missing_on_append session_id=%s", state.session_id)
            return

        findings_summary, report_summary = summarize_job_for_history(state)
        # 若该 job 已存在则更新，否则追加（防止重复回调）
        existing = next((t for t in session.turns if t.job_id == state.job_id), None)
        if existing:
            existing.status = state.status.value
            existing.findings_summary = findings_summary
            existing.report_summary = report_summary
            existing.report_path = state.report_path
            existing.charts = [c.model_dump() for c in state.charts]
        else:
            turn = SessionTurn(
                turn_id=len(session.turns) + 1,
                job_id=state.job_id,
                question=state.question,
                status=state.status.value,
                findings_summary=findings_summary,
                report_summary=report_summary,
                report_path=state.report_path,
                charts=[c.model_dump() for c in state.charts],
            )
            session.turns.append(turn)

        # 缓存 schema，后续追问可复用展示
        if state.schema_info:
            session.schema_info = state.schema_info
        self.save(session)
        logger.info(
            "session_turn_appended session_id=%s job_id=%s turns=%s",
            session.session_id,
            state.job_id,
            len(session.turns),
        )


session_store = SessionStore()
