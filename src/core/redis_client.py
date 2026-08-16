"""Redis 连接。连不上返回 None。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Optional

from src.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


@lru_cache
def get_redis() -> Optional[Any]:
    """懒加载 Redis 客户端；失败则返回 None。"""
    settings = get_settings()
    try:
        import redis  # type: ignore

        client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=5,
        )
        client.ping()
        logger.info("redis_connected url=%s", settings.redis_url)
        return client
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis_unavailable fallback_memory err=%s", exc)
        return None
