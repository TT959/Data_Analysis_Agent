"""
结果缓存：相同文件内容哈希 + 相同问题 → 复用成功任务快照。

"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from src.config import get_settings
from src.core.redis_client import get_redis
from src.state import AnalysisState
from src.utils.logging import get_logger

logger = get_logger(__name__)


def file_sha256(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def cache_key(file_digest: str, question: str) -> str:
    q = hashlib.sha256(question.strip().encode("utf-8")).hexdigest()[:16]
    return f"analyst:result_cache:{file_digest}:{q}"


def get_cached_result(data_path: str, question: str) -> Optional[AnalysisState]:
    settings = get_settings()
    if not settings.enable_result_cache:
        return None
    client = get_redis()
    if client is None:
        return None
    try:
        digest = file_sha256(data_path)
        raw = client.get(cache_key(digest, question))
        if not raw:
            return None
        state = AnalysisState.model_validate_json(raw)
        logger.info("result_cache_hit digest=%s", digest[:12])
        return state
    except Exception as exc:  # noqa: BLE001
        logger.warning("result_cache_get_failed err=%s", exc)
        return None


def set_cached_result(data_path: str, question: str, state: AnalysisState) -> None:
    settings = get_settings()
    if not settings.enable_result_cache:
        return
    client = get_redis()
    if client is None:
        return
    try:
        digest = file_sha256(data_path)
        client.set(
            cache_key(digest, question),
            state.model_dump_json(),
            ex=settings.result_cache_ttl_seconds,
        )
        logger.info("result_cache_set digest=%s", digest[:12])
    except Exception as exc:  # noqa: BLE001
        logger.warning("result_cache_set_failed err=%s", exc)
