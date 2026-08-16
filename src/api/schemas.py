"""API 请求/响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# post/analyze的返回
class AnalyzeAccepted(BaseModel):
    job_id: str
    status: str
    message: str = "分析任务已受理"
    session_id: Optional[str] = None

# post/sessions的返回
class SessionCreated(BaseModel):
    session_id: str
    original_filename: str
    job_id: Optional[str] = None
    status: str = "created"
    message: str = "会话已创建"

# 追问的请求体
class SessionAskRequest(BaseModel):
    question: str = Field(..., description="追问内容，不需要重新上传文件")

# 追问受理后的返回
class SessionAskAccepted(BaseModel):
    session_id: str
    job_id: str
    status: str
    turn_id: int
    message: str = "追问已受理，请轮询 /api/v1/jobs/{job_id}"

# 会话里（一轮任务）的对外展示
class SessionTurnResponse(BaseModel):
    turn_id: int
    job_id: str
    question: str
    status: str
    findings_summary: str = ""
    report_summary: str = ""
    report_path: Optional[str] = None
    charts: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime

# GET /sessions/{id} 的返回
class SessionDetailResponse(BaseModel):
    session_id: str
    original_filename: str
    data_path: str
    turns: List[SessionTurnResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

# GET /jobs/{id} 的返回
class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    stage: str
    question: str
    original_filename: str = ""
    error: Optional[str] = None
    error_code: Optional[str] = None
    report_path: Optional[str] = None
    charts: List[Dict[str, Any]] = Field(default_factory=list)
    findings_count: int = 0
    critic_passed: Optional[bool] = None
    critic_issues: List[str] = Field(default_factory=list)
    critic_retry_stage: Optional[str] = None
    created_at: datetime
    updated_at: datetime

# 健康检查返回
class HealthResponse(BaseModel):
    status: str
    version: str
    llm_configured: bool

# 错误返回
class ErrorBody(BaseModel):
    error_code: str
    message: str
    request_id: str = "-"
