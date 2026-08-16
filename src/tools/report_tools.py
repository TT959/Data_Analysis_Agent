"""报告写入工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src.config import get_settings
from src.tools.base import Tool, ToolErrorCode, ToolParameter, ToolResponse


def job_report_path(job_id: str) -> Path:
    settings = get_settings()
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    return settings.reports_dir / f"report_{job_id}.md"


def write_markdown_report(job_id: str, content: str) -> Path:
    path = job_report_path(job_id)
    path.write_text(content, encoding="utf-8")
    return path


class WriteReportTool(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="write_report",
            description="将 Markdown 分析报告写入磁盘。参数: job_id, content。",
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(name="job_id", type="string", description="任务 ID", required=True),
            ToolParameter(name="content", type="string", description="Markdown 正文", required=True),
        ]

    def run(self, parameters: Dict[str, Any]) -> ToolResponse:
        try:
            job_id = parameters.get("job_id") or "unknown"
            content = parameters.get("content") or parameters.get("input")
            if not content:
                return ToolResponse.error(
                    code=ToolErrorCode.INVALID_PARAM, message="content 不能为空"
                )
            path = write_markdown_report(str(job_id), str(content))
            return ToolResponse.success(
                text=f"报告已写入: {path}",
                data={"path": str(path)},
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResponse.error(code=ToolErrorCode.EXECUTION_ERROR, message=str(exc))
