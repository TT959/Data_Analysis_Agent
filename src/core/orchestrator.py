"""
分析流水线编排（LangGraph）：规划 → 分析 → 出图 → 报告 → 复核。

"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, TypedDict

from langgraph.graph import END, StateGraph

from src.agents.factory import (
    create_analyst,
    create_critic,
    create_planner,
    create_reporter,
    create_visualizer,
)
from src.config import get_settings
from src.core.job_store import job_store
from src.state import (
    AnalysisState,
    ChartArtifact,
    CriticVerdict,
    Finding,
    JobStatus,
    PipelineStage,
    PlanStep,
)
from src.tools.data_tools import load_dataframe, profile_dataframe
from src.tools.plot_tools import (
    PlotBarTool,
    PlotHeatmapTool,
    PlotHistTool,
    PlotLineTool,
    take_created_charts,
)
from src.tools.report_tools import job_report_path, write_markdown_report
from src.utils.logging import get_logger

logger = get_logger(__name__)

# 定义LangGraph的图状态
class PipelineState(TypedDict):
    """LangGraph 图状态：持有可变的 AnalysisState。"""

    analysis: AnalysisState

# 从模型杂乱文本里抠出JSON对象
def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("无法从模型输出中解析 JSON")

# Planner 失败时的默认三步：分析 → 出图 → 报告。
def _default_plan(question: str) -> List[PlanStep]:
    return [
        PlanStep(id=1, agent="analyst", task=f"画像数据并围绕问题分析: {question}"),
        PlanStep(id=2, agent="visualizer", task="生成分布/对比/相关类图表"),
        PlanStep(id=3, agent="reporter", task="撰写含证据引用的分析报告"),
    ]

# 把 conversation_history 格式化成 prompt 片段，供追问理解上下文。
def _format_history(state: AnalysisState) -> str:
    """把会话历史格式化成 prompt 片段；无历史则返回空串。"""
    if not state.conversation_history:
        return ""
    lines = ["以下是同一份数据上的历史对话摘要（供理解追问，请勿编造未出现的数字）："]
    for idx, turn in enumerate(state.conversation_history, start=1):
        lines.append(f"[第{idx}轮问题] {turn.question}")
        if turn.findings_summary:
            lines.append(f"[第{idx}轮发现摘要] {turn.findings_summary[:800]}")
        if turn.report_summary:
            lines.append(f"[第{idx}轮报告摘要] {turn.report_summary[:800]}")
    lines.append(f"[当前问题] {state.question}")
    return "\n".join(lines)

# 规则出图兜底：模型不可用或失败时使用。
def _auto_charts(data_path: str) -> List[ChartArtifact]:
    """规则出图兜底：模型不可用或失败时使用。"""
    df = load_dataframe(data_path)
    info = profile_dataframe(df)
    charts: List[ChartArtifact] = []
    numeric = info["numeric_columns"]
    categorical = info["categorical_columns"]

    if categorical and numeric:
        resp = PlotBarTool().run(
            {
                "data_path": data_path,
                "x": categorical[0],
                "y": numeric[0],
                "title": f"{numeric[0]} by {categorical[0]}",
            }
        )
        if resp.status.value == "success" and resp.data:
            charts.append(ChartArtifact(**resp.data))
    elif categorical:
        resp = PlotBarTool().run(
            {
                "data_path": data_path,
                "x": categorical[0],
                "title": f"Count of {categorical[0]}",
            }
        )
        if resp.status.value == "success" and resp.data:
            charts.append(ChartArtifact(**resp.data))

    if numeric:
        resp = PlotHistTool().run(
            {
                "data_path": data_path,
                "column": numeric[0],
                "title": f"Distribution of {numeric[0]}",
            }
        )
        if resp.status.value == "success" and resp.data:
            charts.append(ChartArtifact(**resp.data))

    if len(numeric) >= 2:
        resp = PlotHeatmapTool().run({"data_path": data_path, "title": "Correlation heatmap"})
        if resp.status.value == "success" and resp.data:
            charts.append(ChartArtifact(**resp.data))
        elif len(df) > 1 and not categorical:
            resp = PlotLineTool().run(
                {
                    "data_path": data_path,
                    "x": str(df.columns[0]),
                    "y": numeric[0],
                    "title": f"{numeric[0]} trend",
                }
            )
            if resp.status.value == "success" and resp.data:
                charts.append(ChartArtifact(**resp.data))

    return charts


def _is_real_report(text: Optional[str]) -> bool:
    if not text or not str(text).strip():
        return False
    body = str(text).strip()
    if body.startswith("报告已") and "分析报告" not in body:
        return False
    return "分析报告" in body or len(body) >= 200


def _unlink_chart_files(charts: List[ChartArtifact]) -> None:
    for chart in charts:
        path = Path(chart.path)
        if path.is_file():
            path.unlink()


def _drop_new_orphans(before: Set[Path], keep: List[ChartArtifact]) -> None:
    keep_paths = {Path(chart.path).resolve() for chart in keep}
    charts_dir = get_settings().charts_dir
    if not charts_dir.exists():
        return
    for path in charts_dir.glob("*.png"):
        resolved = path.resolve()
        if resolved not in before and resolved not in keep_paths and path.is_file():
            path.unlink()


def _charts_from_tools() -> List[ChartArtifact]:
    charts: List[ChartArtifact] = []
    for item in take_created_charts():
        try:
            charts.append(ChartArtifact(**item))
        except Exception:  # noqa: BLE001
            continue
    return charts


def _fallback_report(state: AnalysisState) -> str:
    lines = [
        "# 分析报告",
        "",
        "## 背景与问题",
        state.question,
        "",
        "## 数据与方法",
        f"- 文件: `{state.original_filename or state.data_path}`",
        f"- 规模: {state.schema_info.get('rows')} 行 × {state.schema_info.get('columns')} 列",
        "",
        "## 关键发现",
    ]
    for finding in state.findings:
        lines.append(
            f"- [{finding.evidence_id}] **{finding.step}**: {finding.note} "
            f"`metrics={json.dumps(finding.metrics, ensure_ascii=False)}`"
        )
    lines.extend(["", "## 可视化说明"])
    if state.charts:
        for chart in state.charts:
            lines.append(f"- ![{chart.caption}]({chart.path}) — {chart.caption}")
    else:
        lines.append("- 本次未生成图表")
    lines.extend(
        [
            "",
            "## 结论与建议",
            "结合上述指标核验业务口径；如需更细结论，可补充时间粒度或对照样本。",
            "",
            "## 局限与下一步",
            "- 当前为单表分析，未做跨表关联",
            "- 图表按字段类型规则生成，业务口径需人工确认",
        ]
    )
    return "\n".join(lines)


_RETRY_STAGE_ALIASES = {
    "analyze": "analyze",
    "analyst": "analyze",
    "visualize": "visualize",
    "visualizer": "visualize",
    "report": "report",
    "reporter": "report",
}


def _normalize_retry_stage(raw: Any) -> str:
    """把模型给出的重跑阶段收成 analyze / visualize / report。"""
    key = str(raw or "report").strip().lower()
    return _RETRY_STAGE_ALIASES.get(key, "report")


def _needs_revision(state: AnalysisState) -> bool:
    return bool(state.critic and not state.critic.passed)


def _format_critic_feedback(state: AnalysisState) -> str:
    """把上一轮复核意见塞进执行节点 prompt；已通过或无复核则空串。"""
    if not _needs_revision(state):
        return ""
    verdict = state.critic
    assert verdict is not None
    issues = "\n".join(f"- {item}" for item in verdict.issues) or "- （未列出具体问题）"
    suggestions = "\n".join(f"- {item}" for item in verdict.suggestions) or "- （无）"
    return (
        "【复核未通过，必须修正后再交付】\n"
        f"问题:\n{issues}\n"
        f"建议:\n{suggestions}\n"
        "请针对上述问题修正；所有数字必须来自工具结果或给定 findings/charts，禁止编造。\n"
    )


def _route_after_critique(gs: PipelineState) -> str:
    """复核通过或达到轮次上限则结束，否则打回到对应阶段。"""
    state = gs["analysis"]
    max_rounds = max(1, get_settings().critic_max_rounds)
    verdict = state.critic
    if verdict is None or verdict.passed:
        return "end"
    if state.critic_rounds >= max_rounds:
        logger.info(
            "critic max rounds reached job_id=%s rounds=%s",
            state.job_id,
            state.critic_rounds,
        )
        return "end"
    return _normalize_retry_stage(verdict.retry_stage)


def _node_profile(gs: PipelineState) -> PipelineState:
    state = gs["analysis"]
    state.touch(PipelineStage.ANALYZE)
    df = load_dataframe(state.data_path)
    state.schema_info = profile_dataframe(df)
    state.add_trace("data_profiled", rows=state.schema_info.get("rows"))
    job_store.update(state)
    return {"analysis": state}

# 规划阶段：调用 planner 模型，生成分析步骤。
def _node_plan(gs: PipelineState) -> PipelineState:
    state = gs["analysis"]
    state.touch(PipelineStage.PLAN)
    job_store.update(state)
    try:
        planner = create_planner()
        history_block = _format_history(state)
        prompt = (
            f"{history_block}\n"
            f"用户问题: {state.question}\n"
            f"数据 schema: {json.dumps(state.schema_info, ensure_ascii=False)[:3000]}\n"
            "若存在历史对话，请把当前问题理解为追问，并承接上文意图。"
        )
        raw = planner.run(prompt)
        data = _extract_json(str(raw))
        steps = [
            PlanStep(
                id=int(item.get("id", idx + 1)),
                agent=str(item.get("agent", "analyst")),
                task=str(item.get("task", "")),
            )
            for idx, item in enumerate(data.get("steps") or [])
            if item.get("task")
        ]
        state.plan = steps or _default_plan(state.question)
    except Exception as exc:  # noqa: BLE001
        logger.warning("planner fallback: %s", exc)
        state.plan = _default_plan(state.question)
        state.add_trace("planner_fallback", error=str(exc))
    state.add_trace("plan_ready", steps=len(state.plan))
    job_store.update(state)
    return {"analysis": state}

# 分析阶段：调用 analyst 模型，生成分析结论。
def _node_analyze(gs: PipelineState) -> PipelineState:
    state = gs["analysis"]
    state.touch(PipelineStage.ANALYZE)
    job_store.update(state)

    info = state.schema_info
    revision = _needs_revision(state)
    if revision:
        # 打回时保留画像类 findings，丢掉旧的分析结论以免和修订结果打架。
        state.findings = [
            f for f in state.findings if f.step in ("data_profile", "numeric_summary")
        ]
    if not any(f.step == "data_profile" for f in state.findings):
        state.findings.append(
            Finding(
                step="data_profile",
                metrics={
                    "rows": info.get("rows"),
                    "columns": info.get("columns"),
                    "missing_counts": info.get("missing_counts"),
                },
                note="完成数据画像：规模、字段类型与缺失情况。",
            )
        )
    if info.get("numeric_describe") and not any(
        f.step == "numeric_summary" for f in state.findings
    ):
        state.findings.append(
            Finding(
                step="numeric_summary",
                metrics={"numeric_describe": info.get("numeric_describe")},
                note="数值列描述统计已计算。",
            )
        )

    analyst_tasks = [s for s in state.plan if s.agent == "analyst"] or [
        PlanStep(id=1, agent="analyst", task=state.question)
    ]
    try:
        analyst = create_analyst()
        history_block = _format_history(state)
        critic_block = _format_critic_feedback(state)
        for step in analyst_tasks:
            query = (
                f"数据路径: {state.data_path}\n"
                f"{history_block}\n"
                f"{critic_block}\n"
                f"用户问题: {state.question}\n"
                f"本步任务: {step.task}\n"
                f"请先 load_data/profile_data，必要时 aggregate/correlation，再给出结论。"
                f"若为追问，请结合历史摘要，但仍须用工具核对当前问题所需数字。"
            )
            answer = analyst.run(query)
            state.findings.append(
                Finding(
                    step=f"analyst_{step.id}",
                    metrics={"task": step.task, "revision": revision},
                    note=str(answer)[:4000],
                )
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("analyst llm/tool loop failed: %s", exc)
        state.findings.append(
            Finding(
                step="analyst_error",
                metrics={},
                note=f"分析阶段执行异常，已保留数据画像结果。错误: {exc}",
            )
        )
        state.add_trace("analyst_fallback", error=str(exc))

    state.add_trace("analyze_done", findings=len(state.findings), revision=revision)
    job_store.update(state)
    return {"analysis": state}

# 可视化阶段：调用 visualizer 模型，生成可视化图表。
def _node_visualize(gs: PipelineState) -> PipelineState:
    state = gs["analysis"]
    state.touch(PipelineStage.VISUALIZE)
    job_store.update(state)
    _unlink_chart_files(state.charts)
    state.charts = []
    take_created_charts()
    charts_dir = get_settings().charts_dir
    before = {p.resolve() for p in charts_dir.glob("*.png")} if charts_dir.exists() else set()
    try:
        visualizer = create_visualizer()
        history_block = _format_history(state)
        prompt = (
            f"数据路径: {state.data_path}\n"
            f"{history_block}\n"
            f"{_format_critic_feedback(state)}\n"
            f"问题: {state.question}\n"
            f"schema: {json.dumps(state.schema_info, ensure_ascii=False)[:2000]}\n"
            f"请至少生成 2 张图，优先覆盖与当前问题相关的分布、分组对比或相关性。"
        )
        visualizer.run(prompt)
    except Exception as exc:  # noqa: BLE001
        logger.warning("visualizer stage failed: %s", exc)
        state.add_trace("visualizer_fallback", error=str(exc))

    model_charts = _charts_from_tools()
    if model_charts:
        state.charts = model_charts
    else:
        state.charts = _auto_charts(state.data_path)
        take_created_charts()
    _drop_new_orphans(before, state.charts)
    state.add_trace("visualize_done", charts=len(state.charts))
    job_store.update(state)
    return {"analysis": state}


def _node_report(gs: PipelineState) -> PipelineState:
    state = gs["analysis"]
    state.touch(PipelineStage.REPORT)
    job_store.update(state)
    findings_payload = [f.model_dump() for f in state.findings]
    charts_payload = [c.model_dump() for c in state.charts]
    markdown: Optional[str] = None
    try:
        reporter = create_reporter()
        history_block = _format_history(state)
        prompt = (
            f"job_id: {state.job_id}\n"
            f"{history_block}\n"
            f"{_format_critic_feedback(state)}\n"
            f"问题: {state.question}\n"
            f"findings: {json.dumps(findings_payload, ensure_ascii=False)[:6000]}\n"
            f"charts: {json.dumps(charts_payload, ensure_ascii=False)}\n"
        )
        if _needs_revision(state) and state.report_markdown:
            prompt += f"上一版报告:\n{state.report_markdown[:4000]}\n请按复核意见重写完整 Markdown 报告，并调用 write_report 保存。"
        else:
            prompt += (
                "请撰写完整 Markdown 报告，并调用 write_report 保存。"
                "若为追问，报告应回应当前问题，并可简要承接历史结论。"
            )
        raw = reporter.run(prompt)
        markdown = str(raw)
        written_path = job_report_path(state.job_id)
        written = written_path.read_text(encoding="utf-8") if written_path.is_file() else None
        if _is_real_report(written):
            markdown = written
        elif not _is_real_report(markdown):
            markdown = _fallback_report(state)
    except Exception as exc:  # noqa: BLE001
        logger.warning("reporter failed: %s", exc)
        markdown = _fallback_report(state)
        state.add_trace("reporter_fallback", error=str(exc))

    assert markdown is not None
    path = write_markdown_report(state.job_id, markdown)
    state.report_markdown = markdown
    state.report_path = str(path)
    state.add_trace("report_written", path=str(path))
    job_store.update(state)
    return {"analysis": state}


def _node_critique(gs: PipelineState) -> PipelineState:
    settings = get_settings()
    state = gs["analysis"]
    state.touch(PipelineStage.CRITIQUE)
    job_store.update(state)
    max_rounds = max(1, settings.critic_max_rounds)

    try:
        critic = create_critic()
        prompt = (
            f"findings: {json.dumps([f.model_dump() for f in state.findings], ensure_ascii=False)[:5000]}\n"
            f"charts: {json.dumps([c.model_dump() for c in state.charts], ensure_ascii=False)}\n"
            f"report: {(state.report_markdown or '')[:6000]}"
        )
        raw = critic.run(prompt)
        data = _extract_json(str(raw))
        passed = bool(data.get("passed", True))
        retry_stage = _normalize_retry_stage(data.get("retry_stage")) if not passed else None
        verdict = CriticVerdict(
            passed=passed,
            issues=list(data.get("issues") or []),
            suggestions=list(data.get("suggestions") or []),
            retry_stage=retry_stage,
        )
        state.critic = verdict
        state.critic_rounds += 1
        will_retry = (not verdict.passed) and state.critic_rounds < max_rounds
        state.add_trace(
            "critique_round",
            round=state.critic_rounds,
            passed=verdict.passed,
            retry_stage=retry_stage,
            will_retry=will_retry,
        )
        if will_retry:
            logger.info(
                "critic retry job_id=%s stage=%s round=%s/%s",
                state.job_id,
                retry_stage,
                state.critic_rounds,
                max_rounds,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("critic failed: %s", exc)
        state.critic = CriticVerdict(
            passed=True,
            issues=[f"Critic 跳过: {exc}"],
            suggestions=[],
            retry_stage=None,
        )
        state.critic_rounds += 1
        state.add_trace("critique_skipped", error=str(exc))

    job_store.update(state)
    return {"analysis": state}


def build_analysis_graph():
    """构建 LangGraph：profile → plan → analyze → visualize → report → critique。

    复核不通过时按 retry_stage 打回 analyze / visualize / report，轮次由 critic_max_rounds 限制。
    """
    graph = StateGraph(PipelineState)
    graph.add_node("profile", _node_profile)
    graph.add_node("plan", _node_plan)
    graph.add_node("analyze", _node_analyze)
    graph.add_node("visualize", _node_visualize)
    graph.add_node("report", _node_report)
    graph.add_node("critique", _node_critique)

    graph.add_edge("profile", "plan")
    graph.add_edge("plan", "analyze")
    graph.add_edge("analyze", "visualize")
    graph.add_edge("visualize", "report")
    graph.add_edge("report", "critique")
    graph.add_conditional_edges(
        "critique",
        _route_after_critique,
        {
            "analyze": "analyze",
            "visualize": "visualize",
            "report": "report",
            "end": END,
        },
    )
    graph.set_entry_point("profile")
    return graph.compile()


class AnalysisOrchestrator:
    """对外仍暴露 run(state)，内部走 LangGraph。"""

    def __init__(self) -> None:
        self._graph = build_analysis_graph()

    def run(self, state: AnalysisState) -> AnalysisState:
        state.status = JobStatus.RUNNING
        state.add_trace("pipeline_started", engine="langgraph")
        job_store.update(state)

        try:
            max_rounds = max(1, get_settings().critic_max_rounds)
            result = self._graph.invoke(
                {"analysis": state},
                {"recursion_limit": 8 + max_rounds * 4},
            )
            final: AnalysisState = result["analysis"]
            final.status = JobStatus.SUCCEEDED
            final.touch(PipelineStage.DONE)
            final.add_trace("pipeline_succeeded")
            job_store.update(final)
            return final
        except Exception as exc:  # noqa: BLE001
            logger.exception("analysis failed job_id=%s", state.job_id)
            state.status = JobStatus.FAILED
            state.error = str(exc)
            state.error_code = "PIPELINE_ERROR"
            state.add_trace("pipeline_failed", error=str(exc))
            job_store.update(state)
            return state


orchestrator = AnalysisOrchestrator()
