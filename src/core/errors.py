"""接口和任务用的错误码。"""

from __future__ import annotations

from enum import Enum


class ErrorCategory(str, Enum):
    USER = "user"  # 坏文件、空问题、鉴权失败等
    INTERNAL = "internal"  # 本服务未预期异常
    UPSTREAM = "upstream"  # 模型 API / Redis / 对象存储等外部依赖


class ErrorCode(str, Enum):
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    EMPTY_QUESTION = "EMPTY_QUESTION"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    UPLOAD_TOO_LARGE = "UPLOAD_TOO_LARGE"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    REPORT_NOT_READY = "REPORT_NOT_READY"
    REPORT_MISSING = "REPORT_MISSING"
    CHART_NOT_FOUND = "CHART_NOT_FOUND"
    CHART_MISSING = "CHART_MISSING"
    QUEUE_UNAVAILABLE = "QUEUE_UNAVAILABLE"
    PIPELINE_ERROR = "PIPELINE_ERROR"
    PIPELINE_TIMEOUT = "PIPELINE_TIMEOUT"
    UPSTREAM_LLM_ERROR = "UPSTREAM_LLM_ERROR"
    STORAGE_ERROR = "STORAGE_ERROR"


# 错误码默认归属类别
ERROR_CATEGORY_MAP = {
    ErrorCode.UNAUTHORIZED: ErrorCategory.USER,
    ErrorCode.FORBIDDEN: ErrorCategory.USER,
    ErrorCode.EMPTY_QUESTION: ErrorCategory.USER,
    ErrorCode.UNSUPPORTED_FILE_TYPE: ErrorCategory.USER,
    ErrorCode.UPLOAD_TOO_LARGE: ErrorCategory.USER,
    ErrorCode.JOB_NOT_FOUND: ErrorCategory.USER,
    ErrorCode.SESSION_NOT_FOUND: ErrorCategory.USER,
    ErrorCode.REPORT_NOT_READY: ErrorCategory.USER,
    ErrorCode.REPORT_MISSING: ErrorCategory.INTERNAL,
    ErrorCode.CHART_NOT_FOUND: ErrorCategory.USER,
    ErrorCode.CHART_MISSING: ErrorCategory.INTERNAL,
    ErrorCode.QUEUE_UNAVAILABLE: ErrorCategory.INTERNAL,
    ErrorCode.PIPELINE_ERROR: ErrorCategory.INTERNAL,
    ErrorCode.PIPELINE_TIMEOUT: ErrorCategory.INTERNAL,
    ErrorCode.UPSTREAM_LLM_ERROR: ErrorCategory.UPSTREAM,
    ErrorCode.STORAGE_ERROR: ErrorCategory.UPSTREAM,
}
