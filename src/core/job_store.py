"""
任务存储：优先 Redis 持久化，失败则回退内存。

"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

from src.config import get_settings
from src.core.redis_client import get_redis
from src.state import AnalysisState, JobStatus
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Redis key 前缀，避免与其它业务 key 冲突
_JOB_KEY = "analyst:job:{job_id}"


class MemoryJobStore:
    """进程内兜底实现（单机开发 / Redis 不可用时）。"""

    def __init__(self) -> None:
        self._jobs: Dict[str, AnalysisState] = {}
        self._lock = threading.RLock()

    def save(self, state: AnalysisState) -> AnalysisState:
        with self._lock:
            self._jobs[state.job_id] = state
            return state

    def get(self, job_id: str) -> Optional[AnalysisState]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, state: AnalysisState) -> AnalysisState:
        return self.save(state)

    def list_recent(self, limit: int = 20) -> List[AnalysisState]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return jobs[:limit]

    def set_status(self, job_id: str, status: JobStatus, error: str | None = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = status
            if error:
                job.error = error
            job.touch()


class RedisJobStore:
    """基于 Redis 的任务状态存储。"""

    def __init__(self, client) -> None:
        self._client = client
        self._ttl = get_settings().job_ttl_seconds

    def _key(self, job_id: str) -> str:
        return _JOB_KEY.format(job_id=job_id)

    def save(self, state: AnalysisState) -> AnalysisState:
        payload = state.model_dump_json()
        self._client.set(self._key(state.job_id), payload, ex=self._ttl)
        self._client.zadd("analyst:jobs:index", {state.job_id: state.updated_at.timestamp()})
        return state

    def get(self, job_id: str) -> Optional[AnalysisState]:
        raw = self._client.get(self._key(job_id))
        if not raw:
            return None
        return AnalysisState.model_validate_json(raw)

    def update(self, state: AnalysisState) -> AnalysisState:
        return self.save(state)

    def list_recent(self, limit: int = 20) -> List[AnalysisState]:
        ids = self._client.zrevrange("analyst:jobs:index", 0, max(limit - 1, 0))
        result: List[AnalysisState] = []
        for job_id in ids:
            state = self.get(job_id)
            if state:
                result.append(state)
        return result

    def set_status(self, job_id: str, status: JobStatus, error: str | None = None) -> None:
        state = self.get(job_id)
        if not state:
            return
        state.status = status
        if error:
            state.error = error
        state.touch()
        self.save(state)


class JobStore:
    """门面：自动选择 Redis 或 Memory。"""

    def __init__(self) -> None:
        client = get_redis()
        if client is not None:
            self._impl: MemoryJobStore | RedisJobStore = RedisJobStore(client)
            self.backend = "redis"
            logger.info("job_store_backend=redis")
        else:
            self._impl = MemoryJobStore()
            self.backend = "memory"
            logger.info("job_store_backend=memory")

    def save(self, state: AnalysisState) -> AnalysisState:
        return self._impl.save(state)

    def get(self, job_id: str) -> Optional[AnalysisState]:
        return self._impl.get(job_id)

    def update(self, state: AnalysisState) -> AnalysisState:
        return self._impl.update(state)

    def list_recent(self, limit: int = 20) -> List[AnalysisState]:
        return self._impl.list_recent(limit)

    def set_status(self, job_id: str, status: JobStatus, error: str | None = None) -> None:
        self._impl.set_status(job_id, status, error)


# 进程内单例；Worker 与 API 各自持有，但都指向同一 Redis
job_store = JobStore()
