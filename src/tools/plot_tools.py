"""可视化工具：生成图表并落盘。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402
from src.config import get_settings
from src.tools.base import Tool, ToolErrorCode, ToolParameter, ToolResponse
from src.tools.data_tools import load_dataframe

_created_charts: List[Dict[str, Any]] = []


def take_created_charts() -> List[Dict[str, Any]]:
    items = list(_created_charts)
    _created_charts.clear()
    return items


def _chart_ok(path: Path, caption: str, chart_type: str, text: str) -> ToolResponse:
    data = {"path": str(path), "caption": caption, "chart_type": chart_type}
    _created_charts.append(data)
    return ToolResponse.success(text=text, data=data)

# Windows 中文标题常见字体回退
plt.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "Arial Unicode MS",
    "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False


def _save_fig(prefix: str) -> Path:
    settings = get_settings()
    settings.charts_dir.mkdir(parents=True, exist_ok=True)
    path = settings.charts_dir / f"{prefix}_{uuid4().hex[:10]}.png"
    plt.tight_layout()
    plt.savefig(path, dpi=120, bbox_inches="tight")
    plt.close()
    return path


class PlotBarTool(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="plot_bar",
            description="绘制柱状图。参数: data_path, x, y, title(可选)。若 y 为空则统计 x 频次。",
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(name="data_path", type="string", description="数据路径", required=True),
            ToolParameter(name="x", type="string", description="X 轴列名", required=True),
            ToolParameter(name="y", type="string", description="Y 轴数值列，可空", required=False),
            ToolParameter(name="title", type="string", description="图标题", required=False),
        ]

    def run(self, parameters: Dict[str, Any]) -> ToolResponse:
        try:
            df = load_dataframe(str(parameters["data_path"]))
            x = parameters["x"]
            y = parameters.get("y") or ""
            title = parameters.get("title") or f"{x} bar chart"
            if x not in df.columns:
                return ToolResponse.error(
                    code=ToolErrorCode.INVALID_PARAM, message=f"列不存在: {x}"
                )
            plt.figure(figsize=(9, 5))
            if y and y in df.columns:
                grouped = df.groupby(x, dropna=False)[y].sum().sort_values(ascending=False).head(20)
                sns.barplot(x=grouped.index.astype(str), y=grouped.values, color="#2F6FED")
                plt.ylabel(y)
            else:
                counts = df[x].astype(str).value_counts().head(20)
                sns.barplot(x=counts.index, y=counts.values, color="#2F6FED")
                plt.ylabel("count")
            plt.xticks(rotation=35, ha="right")
            plt.title(title)
            path = _save_fig("bar")
            return _chart_ok(path, title, "bar", f"柱状图已保存: {path}")
        except Exception as exc:  # noqa: BLE001
            plt.close()
            return ToolResponse.error(code=ToolErrorCode.EXECUTION_ERROR, message=str(exc))


class PlotLineTool(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="plot_line",
            description="绘制折线图。参数: data_path, x, y, title(可选)。",
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(name="data_path", type="string", description="数据路径", required=True),
            ToolParameter(name="x", type="string", description="X 轴列名", required=True),
            ToolParameter(name="y", type="string", description="Y 轴数值列", required=True),
            ToolParameter(name="title", type="string", description="图标题", required=False),
        ]

    def run(self, parameters: Dict[str, Any]) -> ToolResponse:
        try:
            df = load_dataframe(str(parameters["data_path"]))
            x, y = parameters["x"], parameters["y"]
            title = parameters.get("title") or f"{y} by {x}"
            if x not in df.columns or y not in df.columns:
                return ToolResponse.error(
                    code=ToolErrorCode.INVALID_PARAM, message=f"列不存在: {x}/{y}"
                )
            work = df[[x, y]].dropna().copy()
            # 尝试按时间或类别聚合
            if pd.api.types.is_numeric_dtype(work[y]):
                series = work.groupby(x, dropna=False)[y].sum()
            else:
                series = work.groupby(x, dropna=False)[y].count()
            plt.figure(figsize=(9, 5))
            plt.plot(series.index.astype(str), series.values, marker="o", color="#2F6FED")
            plt.xticks(rotation=35, ha="right")
            plt.title(title)
            plt.xlabel(x)
            plt.ylabel(y)
            path = _save_fig("line")
            return _chart_ok(path, title, "line", f"折线图已保存: {path}")
        except Exception as exc:  # noqa: BLE001
            plt.close()
            return ToolResponse.error(code=ToolErrorCode.EXECUTION_ERROR, message=str(exc))


class PlotHistTool(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="plot_hist",
            description="绘制数值列直方图。参数: data_path, column, title(可选)。",
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(name="data_path", type="string", description="数据路径", required=True),
            ToolParameter(name="column", type="string", description="数值列名", required=True),
            ToolParameter(name="title", type="string", description="图标题", required=False),
        ]

    def run(self, parameters: Dict[str, Any]) -> ToolResponse:
        try:
            df = load_dataframe(str(parameters["data_path"]))
            column = parameters["column"]
            title = parameters.get("title") or f"Distribution of {column}"
            if column not in df.columns:
                return ToolResponse.error(
                    code=ToolErrorCode.INVALID_PARAM, message=f"列不存在: {column}"
                )
            series = pd.to_numeric(df[column], errors="coerce").dropna()
            if series.empty:
                return ToolResponse.error(
                    code=ToolErrorCode.INVALID_PARAM, message=f"列 {column} 无有效数值"
                )
            plt.figure(figsize=(9, 5))
            sns.histplot(series, bins=30, color="#2F6FED", kde=True)
            plt.title(title)
            plt.xlabel(column)
            path = _save_fig("hist")
            return _chart_ok(path, title, "hist", f"直方图已保存: {path}")
        except Exception as exc:  # noqa: BLE001
            plt.close()
            return ToolResponse.error(code=ToolErrorCode.EXECUTION_ERROR, message=str(exc))


class PlotHeatmapTool(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="plot_heatmap",
            description="绘制数值列相关热力图。参数: data_path, title(可选)。",
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(name="data_path", type="string", description="数据路径", required=True),
            ToolParameter(name="title", type="string", description="图标题", required=False),
        ]

    def run(self, parameters: Dict[str, Any]) -> ToolResponse:
        try:
            df = load_dataframe(str(parameters["data_path"]))
            numeric = df.select_dtypes(include="number")
            if numeric.shape[1] < 2:
                return ToolResponse.error(
                    code=ToolErrorCode.INVALID_PARAM, message="数值列不足，无法绘制热力图"
                )
            title = parameters.get("title") or "Correlation heatmap"
            plt.figure(figsize=(8, 6))
            sns.heatmap(numeric.corr(), annot=True, fmt=".2f", cmap="Blues")
            plt.title(title)
            path = _save_fig("heatmap")
            return _chart_ok(path, title, "heatmap", f"热力图已保存: {path}")
        except Exception as exc:  # noqa: BLE001
            plt.close()
            return ToolResponse.error(code=ToolErrorCode.EXECUTION_ERROR, message=str(exc))
