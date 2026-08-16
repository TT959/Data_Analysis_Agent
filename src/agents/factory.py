"""分析角色：基于 OpenAI 兼容 SDK + 自研 ToolRegistry。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.agents.prompts import (
    ANALYST_SYSTEM,
    CRITIC_SYSTEM,
    PLANNER_SYSTEM,
    REPORTER_SYSTEM,
    VISUALIZER_SYSTEM,
)
from src.config import get_settings
from src.core.llm_factory import OpenAIChatClient, create_llm
from src.tools.base import ToolRegistry
from src.tools.data_tools import AggregateTool, CorrelationTool, LoadDataTool, ProfileDataTool
from src.tools.plot_tools import PlotBarTool, PlotHeatmapTool, PlotHistTool, PlotLineTool
from src.tools.report_tools import WriteReportTool

# 所有角色对外统一接口
@dataclass
class AgentRunner:
    """统一 Agent 外观：run(user_prompt) -> 文本。"""

    name: str
    llm: OpenAIChatClient
    system_prompt: str
    tool_registry: Optional[ToolRegistry] = None
    max_tool_steps: int = 6

    def run(self, user_prompt: str) -> str:
        if self.tool_registry and self.tool_registry.list_tools():
            return self.llm.complete_with_tools(
                system=self.system_prompt,
                user=user_prompt,
                registry=self.tool_registry,
                max_steps=self.max_tool_steps,
            )
        return self.llm.complete(system=self.system_prompt, user=user_prompt)

# 给分析员装配数据工具
def build_analyst_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in (LoadDataTool(), ProfileDataTool(), AggregateTool(), CorrelationTool()):
        registry.register_tool(tool)
    return registry

# 给可视化员装配图表工具
def build_visualizer_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in (PlotBarTool(), PlotLineTool(), PlotHistTool(), PlotHeatmapTool()):
        registry.register_tool(tool)
    return registry

# 给报告员装配报告工具
def build_reporter_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_tool(WriteReportTool())
    return registry

# 创建规划agent
def create_planner() -> AgentRunner:
    return AgentRunner(
        name="规划",
        llm=create_llm("planner"),
        system_prompt=PLANNER_SYSTEM,
    )

# 创建分析agent
def create_analyst() -> AgentRunner:
    settings = get_settings()
    return AgentRunner(
        name="分析",
        llm=create_llm("analyst"),
        system_prompt=ANALYST_SYSTEM,
        tool_registry=build_analyst_registry(),
        max_tool_steps=min(settings.agent_max_steps, 8),
    )

# 创建出图agent
def create_visualizer() -> AgentRunner:
    return AgentRunner(
        name="出图",
        llm=create_llm("visualizer"),
        system_prompt=VISUALIZER_SYSTEM,
        tool_registry=build_visualizer_registry(),
        max_tool_steps=6,
    )

# 创建出报告agent
def create_reporter() -> AgentRunner:
    return AgentRunner(
        name="报告",
        llm=create_llm("reporter"),
        system_prompt=REPORTER_SYSTEM,
        tool_registry=build_reporter_registry(),
        max_tool_steps=3,
    )

# 创建复核agent
def create_critic() -> AgentRunner:
    return AgentRunner(
        name="复核",
        llm=create_llm("critic"),
        system_prompt=CRITIC_SYSTEM,
    )
