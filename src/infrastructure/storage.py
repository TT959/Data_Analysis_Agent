"""
对象存储抽象：本地磁盘 或 S3 兼容（MinIO）。

"""

from __future__ import annotations

import io
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Optional

from src.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ObjectStorage(ABC):
    @abstractmethod
    def upload_file(self, local_path: str | Path, object_key: str) -> str:
        """上传本地文件，返回可记录的 object_key。"""

    @abstractmethod
    def download_to_path(self, object_key: str, local_path: str | Path) -> Path:
        """下载到本地路径。"""

    @abstractmethod
    def open_stream(self, object_key: str) -> BinaryIO:
        """以二进制流读取对象（供 API 下载）。"""

    @abstractmethod
    def exists(self, object_key: str) -> bool:
        ...

    @abstractmethod
    def delete_prefix(self, prefix: str) -> int:
        """删除某前缀下对象，返回删除数量（清理脚本用）。"""


class LocalObjectStorage(ObjectStorage):
    """本地落盘：object_key 直接使用真实路径。"""

    def upload_file(self, local_path: str | Path, object_key: str) -> str:
        src = Path(local_path)
        return str(src.resolve())

    def download_to_path(self, object_key: str, local_path: str | Path) -> Path:
        src = Path(object_key)
        dest = Path(local_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dest.resolve():
            dest.write_bytes(src.read_bytes())
        return dest

    def open_stream(self, object_key: str) -> BinaryIO:
        return open(object_key, "rb")

    def exists(self, object_key: str) -> bool:
        return Path(object_key).exists()

    def delete_prefix(self, prefix: str) -> int:
        return 0


class S3ObjectStorage(ObjectStorage):
    """MinIO / OSS 等 S3 兼容存储。"""

    def __init__(self) -> None:
        import boto3
        from botocore.client import Config

        settings = get_settings()
        self._bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4"),
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception:  # noqa: BLE001
            try:
                self._client.create_bucket(Bucket=self._bucket)
                logger.info("s3_bucket_created bucket=%s", self._bucket)
            except Exception as exc:  # noqa: BLE001
                logger.warning("s3_bucket_create_failed err=%s", exc)

    def upload_file(self, local_path: str | Path, object_key: str) -> str:
        path = Path(local_path)
        self._client.upload_file(str(path), self._bucket, object_key)
        logger.info("s3_uploaded key=%s", object_key)
        return object_key

    def download_to_path(self, object_key: str, local_path: str | Path) -> Path:
        dest = Path(local_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(self._bucket, object_key, str(dest))
        return dest

    def open_stream(self, object_key: str) -> BinaryIO:
        obj = self._client.get_object(Bucket=self._bucket, Key=object_key)
        return io.BytesIO(obj["Body"].read())

    def exists(self, object_key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=object_key)
            return True
        except Exception:  # noqa: BLE001
            return False

    def delete_prefix(self, prefix: str) -> int:
        paginator = self._client.get_paginator("list_objects_v2")
        deleted = 0
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            contents = page.get("Contents") or []
            if not contents:
                continue
            objects = [{"Key": item["Key"]} for item in contents]
            self._client.delete_objects(Bucket=self._bucket, Delete={"Objects": objects})
            deleted += len(objects)
        return deleted


_storage: Optional[ObjectStorage] = None


def get_storage() -> ObjectStorage:
    """进程内单例存储后端。"""
    global _storage
    if _storage is not None:
        return _storage
    settings = get_settings()
    if settings.use_s3:
        try:
            _storage = S3ObjectStorage()
            logger.info("storage_backend=s3 endpoint=%s", settings.s3_endpoint)
        except Exception as exc:  # noqa: BLE001
            logger.warning("s3_init_failed fallback_local err=%s", exc)
            _storage = LocalObjectStorage()
    else:
        _storage = LocalObjectStorage()
        logger.info("storage_backend=local")
    return _storage


def sync_job_artifacts(job_id: str, local_paths: list[str]) -> list[str]:
    """把任务产物同步到对象存储，返回 object_key 列表。"""
    storage = get_storage()
    keys: list[str] = []
    for path in local_paths:
        p = Path(path)
        if not p.exists():
            continue
        key = f"jobs/{job_id}/{p.name}"
        keys.append(storage.upload_file(p, key))
    return keys
