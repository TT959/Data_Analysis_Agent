"""分析任务共享状态与领域模型。"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

# 任务生命周期
class JobStatus(str, Enum):
    QUEUED = "queued"  # 待运行，等待调度
    RUNNING = "running"  # 运行中
    SUCCEEDED = "succeeded"  # 成功
    FAILED = "failed"  # 失败
    CANCELLED = "cancelled"  # 取消
    TIMED_OUT = "timed_out"  # 超时

# 流水走到了哪一步
class PipelineStage(str, Enum):
    UPLOAD = "upload"  # 上传   
    PLAN = "plan"  # 规划
    ANALYZE = "analyze"  # 分析
    VISUALIZE = "visualize"  # 出图
    REPORT = "report"  # 报告
    CRITIQUE = "critique"  # 复核
    DONE = "done"  # 完成

# 规划里的一步，包括agent和任务
class PlanStep(BaseModel):
    id: int  # 步骤ID
    agent: str  # 执行该步骤的agent
    task: str  # 任务描述

# 一条分析发现
class Finding(BaseModel):
    step: str
    metrics: Dict[str, Any] = Field(default_factory=dict)
    note: str = ""
    evidence_id: str = Field(default_factory=lambda: f"ev_{uuid4().hex[:8]}")

# 一张图
class ChartArtifact(BaseModel):
    path: str  # 图的存储路径
    caption: str  # 图的标题
    chart_type: str = "unknown"

# 复核结果
class CriticVerdict(BaseModel):
    passed: bool  # 是否通过
    issues: List[str] = Field(default_factory=list)  # 问题列表
    suggestions: List[str] = Field(default_factory=list)  # 修改建议列表
    # 不通过时建议从哪一阶段重跑：analyze / visualize / report
    retry_stage: Optional[str] = None

# 追问时塞给agent的摘要
class ConversationTurnSummary(BaseModel):

    question: str
    findings_summary: str = ""
    report_summary: str = ""


class SessionTurn(BaseModel):
    

    turn_id: int  # 轮次ID
    job_id: str  # 对应哪次任务
    question: str  # 问题
    status: str = JobStatus.QUEUED.value  # 这轮任务的状态
    findings_summary: str = ""  # 这轮任务的分析发现摘要
    report_summary: str = ""  # 这轮任务的报告摘要
    report_path: Optional[str] = None  # 这轮任务的报告路径 
    charts: List[Dict[str, Any]] = Field(default_factory=list)  # 这轮任务的图列表
    created_at: datetime = Field(default_factory=utc_now)  # 这轮任务的创建时间


class AnalysisSession(BaseModel):
    """同一份数据上的多轮分析会话。"""

    session_id: str = Field(default_factory=lambda: uuid4().hex)
    data_path: str  # 数据文件路径
    original_filename: str = ""  # 原始文件名
    schema_info: Dict[str, Any] = Field(default_factory=dict)  # 数据画像
    turns: List[SessionTurn] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def touch(self) -> None:
        self.updated_at = utc_now()

# 一轮任务的全部状态
class AnalysisState(BaseModel):
    job_id: str = Field(default_factory=lambda: uuid4().hex)
    question: str
    data_path: str
    original_filename: str = ""
    # 所属会话
    session_id: Optional[str] = None
    # 追问时带入的最近几轮摘要
    conversation_history: List[ConversationTurnSummary] = Field(default_factory=list)
    status: JobStatus = JobStatus.QUEUED
    stage: PipelineStage = PipelineStage.UPLOAD
    schema_info: Dict[str, Any] = Field(default_factory=dict)
    plan: List[PlanStep] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)
    charts: List[ChartArtifact] = Field(default_factory=list)
    report_path: Optional[str] = None
    report_markdown: Optional[str] = None
    critic: Optional[CriticVerdict] = None
    critic_rounds: int = 0  # 已完成的复核轮次，用于限制打回次数
    error: Optional[str] = None
    error_code: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    trace: List[Dict[str, Any]] = Field(default_factory=list)

    def touch(self, stage: Optional[PipelineStage] = None) -> None:
        self.updated_at = utc_now()
        if stage is not None:
            self.stage = stage

    def add_trace(self, event: str, **payload: Any) -> None:
        self.trace.append(
            {
                "event": event,
                "at": utc_now().isoformat(),
                "stage": self.stage.value,
                **payload,
            }
        )
        self.touch()
