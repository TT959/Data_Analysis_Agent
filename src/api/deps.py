"""鉴权和请求 ID。"""

from __future__ import annotations

from uuid import uuid4

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware

from src.config import get_settings
from src.utils.logging import request_id_ctx

# auto_error=False：缺省头时由我们返回统一 JSON 错误，并让 Swagger 出现 Authorize
bearer_scheme = HTTPBearer(
    auto_error=False,
    description="填写 .env 中 API_KEYS 的值",
)

# 给每次请求一个可追踪的编号，排错时能把[某次api调用]与[该次调用的日志]关联起来
class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid4().hex
        token = request_id_ctx.set(rid)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response
        # 无论成功与否，都要清除请求ID，避免下次请求使用同一个请求ID
        finally:
            request_id_ctx.reset(token)

# 接口鉴权依赖
def require_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    """校验 Bearer Token；Swagger 通过右上角 Authorize 注入 Authorization 头。"""
    settings = get_settings()
    if settings.app_env == "development" and not settings.api_key_list:
        return "anonymous"

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=401,
            detail={"error_code": "UNAUTHORIZED", "message": "缺少 Authorization 头"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials.strip()
    if token.lower().startswith("bearer "):
        token = token.split(" ", 1)[1].strip()

    if token not in settings.api_key_list:
        raise HTTPException(
            status_code=403,
            detail={"error_code": "FORBIDDEN", "message": "无效的 API Key"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token
