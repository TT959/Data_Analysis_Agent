"""
自研工具协议。
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# 工具执行结果状态
class ToolStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"

# 统一错误分类，便于日志与模型理解失败原因。
class ToolErrorCode(str, Enum):
    INVALID_PARAM = "INVALID_PARAM"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    NOT_FOUND = "NOT_FOUND"

#  描述「一个入参」——协议层用。
@dataclass
class ToolParameter:
    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    default: Any = None

# 工具执行后的统一返回体。
@dataclass
class ToolResponse:
    status: ToolStatus
    text: str = ""
    data: Optional[Dict[str, Any]] = None
    code: Optional[str] = None
    message: Optional[str] = None

    @classmethod
    def success(cls, text: str = "", data: Optional[Dict[str, Any]] = None) -> "ToolResponse":
        return cls(status=ToolStatus.SUCCESS, text=text, data=data or {})

    @classmethod
    def error(cls, code: ToolErrorCode | str, message: str) -> "ToolResponse":
        code_str = code.value if isinstance(code, ToolErrorCode) else str(code)
        return cls(
            status=ToolStatus.ERROR,
            text=message,
            code=code_str,
            message=message,
            data={},
        )

# 所有业务工具的抽象父类。
class Tool(ABC):
    """业务工具基类。"""

    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description

    @abstractmethod
    def get_parameters(self) -> List[ToolParameter]:
        raise NotImplementedError

    @abstractmethod
    def run(self, parameters: Dict[str, Any]) -> ToolResponse:
        raise NotImplementedError

    def to_openai_schema(self) -> Dict[str, Any]:
        """导出 OpenAI tools[] 中的单个 function 定义。"""
        properties: Dict[str, Any] = {}
        required: List[str] = []
        for p in self.get_parameters():
            properties[p.name] = {
                "type": p.type if p.type in {"string", "number", "integer", "boolean"} else "string",
                "description": p.description or p.name,
            }
            if p.required:
                required.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


class ToolRegistry:
    """工具注册表：供 Agent 查询与执行。"""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register_tool(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def to_openai_tools(self) -> List[Dict[str, Any]]:
        return [t.to_openai_schema() for t in self._tools.values()]

    def execute(self, name: str, arguments: Dict[str, Any] | str) -> ToolResponse:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResponse.error(ToolErrorCode.NOT_FOUND, f"未知工具: {name}")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError:
                return ToolResponse.error(
                    ToolErrorCode.INVALID_PARAM, f"工具参数不是合法 JSON: {arguments[:200]}"
                )
        if not isinstance(arguments, dict):
            return ToolResponse.error(ToolErrorCode.INVALID_PARAM, "工具参数必须是对象")
        try:
            return tool.run(arguments)
        except Exception as exc:  # noqa: BLE001
            return ToolResponse.error(ToolErrorCode.EXECUTION_ERROR, str(exc))
