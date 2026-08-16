"""数据加载与分析工具（支持 CSV / XLSX）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from src.config import get_settings
from src.tools.base import Tool, ToolErrorCode, ToolParameter, ToolResponse

_DATAFRAME_CACHE: Dict[str, pd.DataFrame] = {}


def clear_dataframe_cache(data_path: Optional[str] = None) -> None:
    if data_path is None:
        _DATAFRAME_CACHE.clear()
    else:
        _DATAFRAME_CACHE.pop(str(Path(data_path).resolve()), None)

# 安全加载表格，返回 DataFrame
def load_dataframe(data_path: str) -> pd.DataFrame:
    """加载表格；超 max_rows 时按配置抽样或截断，避免大表打满内存。"""
    settings = get_settings()
    path = Path(data_path)
    if not path.exists():
        raise FileNotFoundError(f"数据文件不存在: {data_path}")

    key = str(path.resolve())
    if key in _DATAFRAME_CACHE:
        return _DATAFRAME_CACHE[key]

    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(path)
    elif suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    else:
        raise ValueError(f"不支持的文件类型: {suffix}")

    original_rows = int(df.shape[0])
    if original_rows > settings.max_rows:
        if settings.enable_row_sampling:
            # 抽样：固定随机种子，保证同文件可复现
            df = df.sample(n=settings.max_rows, random_state=42).reset_index(drop=True)
        else:
            raise ValueError(
                f"行数 {original_rows} 超过上限 {settings.max_rows}，"
                "请调高 MAX_ROWS 或开启 ENABLE_ROW_SAMPLING"
            )
    if df.shape[1] > settings.max_columns:
        df = df.iloc[:, : settings.max_columns].copy()

    # 在 attrs 里记下是否抽样，画像时可透出
    df.attrs["original_rows"] = original_rows
    df.attrs["sampled"] = original_rows > settings.max_rows and settings.enable_row_sampling

    _DATAFRAME_CACHE[key] = df
    return df


def _json_safe(obj: Any) -> Any:
    """把 numpy/pandas 类型转成可 JSON 序列化的 Python 原生类型。"""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        val = float(obj)
        if np.isnan(val) or np.isinf(val):
            return None
        return val
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj

# 对 DataFrame 做详细画像：描述统计、缺失值、样例行。
def profile_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    categorical_cols = [c for c in df.columns if c not in numeric_cols]

    missing = {
        col: int(df[col].isna().sum())
        for col in df.columns
        if int(df[col].isna().sum()) > 0
    }

    describe = {}
    if numeric_cols:
        desc = df[numeric_cols].describe().to_dict()
        describe = _json_safe(desc)

    return {
        "rows": int(df.shape[0]),
        "columns": int(df.shape[1]),
        "original_rows": int(df.attrs.get("original_rows", df.shape[0])),
        "sampled": bool(df.attrs.get("sampled", False)),
        "column_names": list(map(str, df.columns)),
        "dtypes": {str(c): str(t) for c, t in df.dtypes.items()},
        "numeric_columns": numeric_cols,
        "categorical_columns": categorical_cols,
        "missing_counts": missing,
        "numeric_describe": describe,
        "sample_rows": _json_safe(df.head(5).to_dict(orient="records")),
    }

# 加载 CSV/XLSX 数据并返回表结构摘要（行列数、字段、类型、缺失值）。
class LoadDataTool(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="load_data",
            description="加载 CSV/XLSX 数据并返回表结构摘要（行列数、字段、类型、缺失值）。",
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="data_path",
                type="string",
                description="数据文件绝对或相对路径",
                required=True,
            )
        ]

    def run(self, parameters: Dict[str, Any]) -> ToolResponse:
        data_path = parameters.get("data_path") or parameters.get("input")
        if not data_path:
            return ToolResponse.error(
                code=ToolErrorCode.INVALID_PARAM, message="data_path 不能为空"
            )
        try:
            df = load_dataframe(str(data_path))
            info = profile_dataframe(df)
            text = (
                f"已加载数据: {info['rows']} 行 x {info['columns']} 列。"
                f"数值列: {info['numeric_columns']}; "
                f"类别列: {info['categorical_columns']}"
            )
            return ToolResponse.success(text=text, data=info)
        except Exception as exc:  # noqa: BLE001
            return ToolResponse.error(code=ToolErrorCode.EXECUTION_ERROR, message=str(exc))

# 对已加载的数据做详细画像：描述统计、缺失值、样例行。
class ProfileDataTool(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="profile_data",
            description="对已加载的数据做详细画像：描述统计、缺失值、样例行。",
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="data_path",
                type="string",
                description="数据文件路径",
                required=True,
            )
        ]

    def run(self, parameters: Dict[str, Any]) -> ToolResponse:
        data_path = parameters.get("data_path") or parameters.get("input")
        if not data_path:
            return ToolResponse.error(
                code=ToolErrorCode.INVALID_PARAM, message="data_path 不能为空"
            )
        try:
            df = load_dataframe(str(data_path))
            info = profile_dataframe(df)
            return ToolResponse.success(
                text=json.dumps(info, ensure_ascii=False)[:4000],
                data=info,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResponse.error(code=ToolErrorCode.EXECUTION_ERROR, message=str(exc))

# 按分组列聚合数值列。
class AggregateTool(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="aggregate",
            description=(
                "按分组列聚合数值列。参数: data_path, group_by, value_col, agg(sum|mean|count|max|min)。"
            ),
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(name="data_path", type="string", description="数据路径", required=True),
            ToolParameter(
                name="group_by",
                type="string",
                description="分组列名；多列用逗号分隔，例如 month,region 或 category",
                required=True,
            ),
            ToolParameter(name="value_col", type="string", description="数值列名", required=True),
            ToolParameter(
                name="agg",
                type="string",
                description="聚合方式: sum/mean/count/max/min",
                required=False,
                default="sum",
            ),
        ]

    def run(self, parameters: Dict[str, Any]) -> ToolResponse:
        try:
            data_path = parameters["data_path"]
            group_by_raw = str(parameters["group_by"])
            value_col = parameters["value_col"]
            agg = (parameters.get("agg") or "sum").lower()
            df = load_dataframe(str(data_path))

            # 支持单列或多列： "region" 或 "month,region,category"
            group_cols = [c.strip() for c in group_by_raw.replace(";", ",").split(",") if c.strip()]
            missing = [c for c in group_cols + [value_col] if c not in df.columns]
            if missing:
                return ToolResponse.error(
                    code=ToolErrorCode.INVALID_PARAM,
                    message=f"列不存在: {missing}；可用列: {list(map(str, df.columns))}",
                )

            grouped = df.groupby(group_cols, dropna=False)[value_col]
            if agg == "sum":
                result = grouped.sum()
            elif agg == "mean":
                result = grouped.mean()
            elif agg == "count":
                result = grouped.count()
            elif agg == "max":
                result = grouped.max()
            elif agg == "min":
                result = grouped.min()
            else:
                return ToolResponse.error(
                    code=ToolErrorCode.INVALID_PARAM, message=f"不支持的聚合: {agg}"
                )

            result = result.sort_values(ascending=False).head(30)
            if isinstance(result.index, pd.MultiIndex):
                payload = {
                    " | ".join(map(str, idx)): _json_safe(val)
                    for idx, val in result.items()
                }
            else:
                payload = _json_safe(result.to_dict())

            return ToolResponse.success(
                text=f"{group_cols} 按 {agg}({value_col}) 聚合结果(Top30): {payload}",
                data={
                    "aggregation": payload,
                    "group_by": group_cols,
                    "value_col": value_col,
                    "agg": agg,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResponse.error(code=ToolErrorCode.EXECUTION_ERROR, message=str(exc))

# 计算数值列之间的相关系数矩阵（Pearson）。
class CorrelationTool(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="correlation",
            description="计算数值列之间的相关系数矩阵（Pearson）。",
        )

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(name="data_path", type="string", description="数据路径", required=True),
        ]

    def run(self, parameters: Dict[str, Any]) -> ToolResponse:
        try:
            df = load_dataframe(str(parameters["data_path"]))
            numeric = df.select_dtypes(include=[np.number])
            if numeric.shape[1] < 2:
                return ToolResponse.error(
                    code=ToolErrorCode.INVALID_PARAM,
                    message="数值列不足 2 个，无法计算相关矩阵",
                )
            corr = _json_safe(numeric.corr().round(4).to_dict())
            return ToolResponse.success(text=f"相关矩阵: {corr}", data={"correlation": corr})
        except Exception as exc:  # noqa: BLE001
            return ToolResponse.error(code=ToolErrorCode.EXECUTION_ERROR, message=str(exc))
