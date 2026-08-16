"""文件上传与路径工具。"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from src.config import Settings

SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\u4e00-\u9fff-]+")

# 把危险/奇怪的文件名变成安全名
def sanitize_filename(name: str) -> str:
    name = Path(name).name
    name = SAFE_NAME_RE.sub("_", name)
    return name[:180] or f"data_{uuid4().hex[:8]}"

# 只允许 csv/xlsx 等配置类型
def validate_extension(filename: str, settings: Settings) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in settings.extension_list:
        allowed = ", ".join(settings.extension_list)
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "UNSUPPORTED_FILE_TYPE",
                "message": f"仅支持文件类型: {allowed}，收到: {suffix or '(无扩展名)'}",
            },
        )
    return suffix

# 校验后写入上传目录，返回最终路径
async def save_upload(file: UploadFile, job_id: str, settings: Settings) -> Path:
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "MISSING_FILENAME", "message": "缺少文件名"},
        )

    validate_extension(file.filename, settings)
    safe_name = sanitize_filename(file.filename)
    job_dir = settings.upload_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    dest = job_dir / safe_name

    max_bytes = settings.max_upload_mb * 1024 * 1024
    size = 0
    with dest.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                out.close()
                shutil.rmtree(job_dir, ignore_errors=True)
                raise HTTPException(
                    status_code=413,
                    detail={
                        "error_code": "UPLOAD_TOO_LARGE",
                        "message": f"文件超过 {settings.max_upload_mb}MB 限制",
                    },
                )
            out.write(chunk)

    await file.close()
    return dest
