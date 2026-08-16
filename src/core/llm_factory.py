"""OpenAI 兼容 LLM 客户端。"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union

from openai import OpenAI

from src.config import get_settings
from src.tools.base import ToolRegistry, ToolResponse
from src.utils.logging import get_logger

logger = get_logger(__name__)

Message = Dict[str, Any]

# 定义OpenAIChatClient类
class OpenAIChatClient:
    """薄封装：普通补全 + Tool Calling 多步循环。"""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        timeout: int = 60,
        temperature: float = 0.2,
        max_retries: int = 3,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )

    def complete(self, *, system: str, user: str) -> str:
        """单轮对话，返回助手文本。"""
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = resp.choices[0].message.content
        return (content or "").strip()
# 带工具的多轮循环——模型可反复选工具，直到给出最终文本或步数用尽。
    def complete_with_tools(
        self,
        *,
        system: str,
        user: str,
        registry: ToolRegistry,
        max_steps: int = 8,
    ) -> str:
        """ReAct 风格：模型可多次调用工具，直到给出最终文本或达到步数上限。"""
        tools = registry.to_openai_tools()
        messages: List[Message] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        final_text = ""

        for step in range(max(1, max_steps)):
            kwargs: Dict[str, Any] = {
                "model": self.model,
                "temperature": self.temperature,
                "messages": messages,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            resp = self.client.chat.completions.create(**kwargs)
            msg = resp.choices[0].message
            tool_calls = msg.tool_calls or []

            # 先把助手消息写入历史（含 tool_calls）
            assistant_payload: Message = {"role": "assistant", "content": msg.content or ""}
            if tool_calls:
                assistant_payload["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments or "{}",
                        },
                    }
                    for tc in tool_calls
                ]
            messages.append(assistant_payload)

            if not tool_calls:
                final_text = (msg.content or "").strip()
                break

            for tc in tool_calls:
                name = tc.function.name
                args_raw = tc.function.arguments or "{}"
                logger.info("tool_call step=%s name=%s", step + 1, name)
                result: ToolResponse = registry.execute(name, args_raw)
                payload = {
                    "ok": result.status.value == "success",
                    "text": result.text,
                    "data": result.data,
                    "error_code": result.code,
                }
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(payload, ensure_ascii=False)[:8000],
                    }
                )
            # 若本轮只有工具调用没有最终文本，继续循环
            if msg.content:
                final_text = msg.content.strip()
        else:
            if not final_text:
                final_text = "已达到最大工具调用步数，请根据已有工具结果继续分析。"

        return final_text


def create_llm(role: str = "default") -> OpenAIChatClient:
    settings = get_settings()
    settings.require_llm()
    model = settings.model_for(role) if role != "default" else settings.llm_model_id
    return OpenAIChatClient(
        model=model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout_seconds,
        temperature=0.2,
        max_retries=settings.llm_max_retries,
    )
