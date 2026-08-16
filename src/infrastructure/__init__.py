"""对象存储模块导出。"""

from src.infrastructure.storage import get_storage, sync_job_artifacts

__all__ = ["get_storage", "sync_job_artifacts"]
