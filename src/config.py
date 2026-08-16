"""应用配置：从 .env 加载配置信息
TASK_BACKEND=celery 时走 Redis 队列；memory 时仍用进程内 BackgroundTasks（本地无 Redis 也能跑）
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ----- 模型接口 -----
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_base_url: str = Field(default="https://api.openai.com/v1", alias="LLM_BASE_URL")
    llm_model_id: str = Field(default="gpt-4o-mini", alias="LLM_MODEL_ID")

    planner_model: str = Field(default="", alias="PLANNER_MODEL")
    analyst_model: str = Field(default="", alias="ANALYST_MODEL")
    visualizer_model: str = Field(default="", alias="VISUALIZER_MODEL")
    reporter_model: str = Field(default="", alias="REPORTER_MODEL")
    critic_model: str = Field(default="", alias="CRITIC_MODEL")

    # ----- 服务 -----
    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    debug: bool = Field(default=True, alias="DEBUG")
    api_keys: str = Field(default="dev-key-change-me", alias="API_KEYS")

    # ----- 本地路径（Worker/API 可通过共享卷看到同一目录）-----
    data_dir: Path = Field(default=ROOT_DIR / "src" / "data", alias="DATA_DIR")
    upload_dir: Path = Field(default=ROOT_DIR / "uploads", alias="UPLOAD_DIR")
    output_dir: Path = Field(default=ROOT_DIR / "outputs", alias="OUTPUT_DIR")
    charts_dir: Path = Field(default=ROOT_DIR / "outputs" / "charts", alias="CHARTS_DIR")
    reports_dir: Path = Field(default=ROOT_DIR / "outputs" / "reports", alias="REPORTS_DIR")

    max_upload_mb: int = Field(default=20, alias="MAX_UPLOAD_MB")
    max_rows: int = Field(default=50000, alias="MAX_ROWS")
    max_columns: int = Field(default=200, alias="MAX_COLUMNS")
    # 超限时是否抽样保留 max_rows（True）还是直接拒绝（False）
    enable_row_sampling: bool = Field(default=True, alias="ENABLE_ROW_SAMPLING")
    allowed_extensions: str = Field(default=".csv,.xlsx", alias="ALLOWED_EXTENSIONS")
    code_exec_timeout: int = Field(default=30, alias="CODE_EXEC_TIMEOUT")
    allow_code_execution: bool = Field(default=True, alias="ALLOW_CODE_EXECUTION")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    # true 时输出 JSON 行日志，便于采集
    log_json: bool = Field(default=False, alias="LOG_JSON")

    llm_timeout_seconds: int = Field(default=60, alias="LLM_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=3, alias="LLM_MAX_RETRIES")
    agent_max_steps: int = Field(default=15, alias="AGENT_MAX_STEPS")
    critic_max_rounds: int = Field(default=2, alias="CRITIC_MAX_ROUNDS")

    # 任务后端：celery | memory 
    task_backend: str = Field(default="memory", alias="TASK_BACKEND")
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", alias="REDIS_URL")
    celery_queue: str = Field(default="analysis", alias="CELERY_QUEUE")
    # 单任务软超时（秒），超时后标记 timed_out
    job_timeout_seconds: int = Field(default=600, alias="JOB_TIMEOUT_SECONDS")
    # Celery 失败自动重试次数
    job_max_retries: int = Field(default=2, alias="JOB_MAX_RETRIES")
    # Worker 侧并发（celery --concurrency 也可覆盖）
    worker_concurrency: int = Field(default=2, alias="WORKER_CONCURRENCY")
    worker_metrics_port: int = Field(default=9091, alias="WORKER_METRICS_PORT")
    # 任务状态 TTL（秒），到期可被清理脚本删除
    job_ttl_seconds: int = Field(default=604800, alias="JOB_TTL_SECONDS")

    # 对象存储：local | s3（MinIO 兼容 S3 API）
    storage_backend: str = Field(default="local", alias="STORAGE_BACKEND")
    s3_endpoint: str = Field(default="http://127.0.0.1:9000", alias="S3_ENDPOINT")
    s3_access_key: str = Field(default="minioadmin", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="minioadmin", alias="S3_SECRET_KEY")
    s3_bucket: str = Field(default="analyst", alias="S3_BUCKET")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    # 产物在对象存储中的保留天数（清理脚本使用）
    artifact_retain_days: int = Field(default=7, alias="ARTIFACT_RETAIN_DAYS")

    # 结果缓存：相同文件内容 + 相同问题可复用 
    enable_result_cache: bool = Field(default=True, alias="ENABLE_RESULT_CACHE")
    result_cache_ttl_seconds: int = Field(default=86400, alias="RESULT_CACHE_TTL_SECONDS")

    @field_validator(
        "data_dir",
        "upload_dir",
        "output_dir",
        "charts_dir",
        "reports_dir",
        mode="before",
    )
    @classmethod
    def _resolve_path(cls, value: str | Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = ROOT_DIR / path
        return path

    @property
    def api_key_list(self) -> List[str]:
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]

    @property
    def extension_list(self) -> List[str]:
        items = []
        for ext in self.allowed_extensions.split(","):
            ext = ext.strip().lower()
            if not ext:
                continue
            if not ext.startswith("."):
                ext = f".{ext}"
            items.append(ext)
        return items or [".csv", ".xlsx"]

    @property
    def use_celery(self) -> bool:
        return self.task_backend.strip().lower() == "celery"

    @property
    def use_s3(self) -> bool:
        return self.storage_backend.strip().lower() in {"s3", "minio"}

    def model_for(self, role: str) -> str:
        mapping = {
            "planner": self.planner_model,
            "analyst": self.analyst_model,
            "visualizer": self.visualizer_model,
            "reporter": self.reporter_model,
            "critic": self.critic_model,
        }
        return mapping.get(role) or self.llm_model_id

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.upload_dir,
            self.output_dir,
            self.charts_dir,
            self.reports_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def require_llm(self) -> None:
        if not self.llm_api_key or not self.llm_api_key.strip():
            raise RuntimeError(
                "LLM_API_KEY 未配置。请在项目根目录 .env 中填写后重试。"
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
