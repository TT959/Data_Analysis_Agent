"""日志：支持普通文本或 JSON（LOG_JSON=true）。"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

from src.config import get_settings

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
job_id_ctx: ContextVar[str] = ContextVar("job_id", default="-")


class ContextFilter(logging.Filter):
    """把 request_id / job_id 注入日志字段。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        record.job_id = job_id_ctx.get()
        return True


class JsonFormatter(logging.Formatter):
    """一行一条 JSON，方便采集到 ELK / Loki。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "job_id": getattr(record, "job_id", "-"),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    settings = get_settings()
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | rid=%(request_id)s | "
                "job=%(job_id)s | %(message)s"
            )
        )
    handler.addFilter(ContextFilter())
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
