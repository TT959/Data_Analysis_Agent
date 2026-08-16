"""
清理过期本地产物（uploads/outputs）。
"""

from __future__ import annotations

import time
from pathlib import Path

from src.config import ROOT_DIR, get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _cleanup_dir(root: Path, retain_days: int) -> int:
    """删除 root 下超过 retain_days 的文件，返回删除数。"""
    if not root.exists():
        return 0
    cutoff = time.time() - retain_days * 86400
    deleted = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                deleted += 1
        except OSError as exc:
            logger.warning("cleanup_skip path=%s err=%s", path, exc)
    return deleted


def main() -> None:
    settings = get_settings()
    days = settings.artifact_retain_days
    total = 0
    total += _cleanup_dir(settings.upload_dir, days)
    total += _cleanup_dir(settings.charts_dir, days)
    total += _cleanup_dir(settings.reports_dir, days)
    cache_dir = settings.output_dir / "_download_cache"
    total += _cleanup_dir(cache_dir, days)
    logger.info("cleanup_done deleted=%s retain_days=%s root=%s", total, days, ROOT_DIR)
    print(f"deleted={total} retain_days={days}")


if __name__ == "__main__":
    main()
