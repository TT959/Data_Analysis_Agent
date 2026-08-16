"""FastAPI 应用入口。组装并导出fastapi应用app。main.
py里的uvicorn加载的就是这里的app"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src import __version__
from src.api.deps import RequestIdMiddleware
from src.api.routes import analysis, health, sessions
from src.config import get_settings
from src.utils.logging import setup_logging

# 工厂函数
def create_app() -> FastAPI:
    # 配置好日志
    setup_logging()
    # 加载配置
    settings = get_settings()
    # 确保uploads/,outputs/等目录存在
    settings.ensure_dirs()
# 创建Fastapi实列
    app = FastAPI(
        title="数据分析服务",
        description=(
            "上传 CSV/XLSX，提问后出图和 Markdown 报告。\n\n"
            "同一份数据要追问：先 `POST /api/v1/sessions`，再 "
            "`POST /api/v1/sessions/{id}/ask`。\n\n"
            "先点右上角 Authorize，填 `.env` 里的 `API_KEYS`，不用加 Bearer。"
        ),
        version=__version__,
    )
    # 添加请求ID中间件
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # 挂载路由，把各文件里定义的API注册到同一个app上，让Swagger里出现这些接口
    app.include_router(health.router)
    app.include_router(analysis.router)
    app.include_router(sessions.router)
    return app


app = create_app()
