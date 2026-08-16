"""
离线评测：不调用大模型，只验证工具层计算与出图。

"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.config import ROOT_DIR, get_settings
from src.core.orchestrator import _auto_charts
from src.tools.data_tools import AggregateTool, load_dataframe, profile_dataframe
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _run_case(case: dict) -> list[str]:
    """跑单个用例，返回错误列表（空=通过）。"""
    errors: list[str] = []
    data_path = ROOT_DIR / case["data_file"]
    if not data_path.exists():
        return [f"missing data file: {data_path}"]

    expect = case.get("expect") or {}
    df = load_dataframe(str(data_path))
    info = profile_dataframe(df)

    if "min_rows" in expect and info["rows"] < expect["min_rows"]:
        errors.append(f"rows {info['rows']} < {expect['min_rows']}")

    for col in expect.get("required_columns") or []:
        if col not in info["column_names"]:
            errors.append(f"missing column: {col}")

    agg_cfg = expect.get("aggregate")
    if agg_cfg:
        resp = AggregateTool().run(
            {
                "data_path": str(data_path),
                "group_by": agg_cfg["group_by"],
                "value_col": agg_cfg["value_col"],
                "agg": agg_cfg.get("agg", "sum"),
            }
        )
        if resp.status.value != "success":
            errors.append(f"aggregate failed: {resp.text}")
        else:
            keys = set((resp.data or {}).get("aggregation", {}).keys())
            for must in agg_cfg.get("must_include_keys") or []:
                if must not in keys:
                    errors.append(f"aggregate missing key: {must}")

    min_charts = int(expect.get("min_charts") or 0)
    if min_charts > 0:
        charts = _auto_charts(str(data_path))
        if len(charts) < min_charts:
            errors.append(f"charts {len(charts)} < {min_charts}")
        for chart in charts:
            if not Path(chart.path).exists():
                errors.append(f"chart file missing: {chart.path}")

    return errors


def main() -> int:
    get_settings()  # 确保输出目录存在
    cases_path = ROOT_DIR / "evals" / "cases.json"
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = payload.get("cases") or []

    failed = 0
    for case in cases:
        case_id = case.get("id", "unknown")
        errs = _run_case(case)
        if errs:
            failed += 1
            print(f"[FAIL] {case_id}")
            for e in errs:
                print(f"  - {e}")
        else:
            print(f"[PASS] {case_id}")

    total = len(cases)
    passed = total - failed
    print(f"summary total={total} passed={passed} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
