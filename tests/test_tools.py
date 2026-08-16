"""工具冒烟测试（不调用远端模型）。"""

from __future__ import annotations

from pathlib import Path

from src.tools.data_tools import AggregateTool, LoadDataTool, profile_dataframe, load_dataframe
from src.tools.plot_tools import PlotBarTool, PlotHistTool, take_created_charts
from src.tools.report_tools import job_report_path, write_markdown_report
from src.core.orchestrator import _auto_charts, _is_real_report


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "src" / "data" / "sample_sales.csv"


def test_load_and_profile():
    df = load_dataframe(str(SAMPLE))
    info = profile_dataframe(df)
    assert info["rows"] > 0
    assert "sales" in info["column_names"]


def test_load_tool():
    resp = LoadDataTool().run({"data_path": str(SAMPLE)})
    assert resp.status.value == "success"


def test_aggregate_tool():
    resp = AggregateTool().run(
        {
            "data_path": str(SAMPLE),
            "group_by": "category",
            "value_col": "sales",
            "agg": "sum",
        }
    )
    assert resp.status.value == "success"
    assert "Electronics" in resp.data["aggregation"]


def test_auto_charts(tmp_path, monkeypatch):
    from src.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "charts_dir", tmp_path)
    take_created_charts()
    charts = _auto_charts(str(SAMPLE))
    assert len(charts) >= 1
    assert Path(charts[0].path).exists()
    take_created_charts()


def test_plot_bar(tmp_path, monkeypatch):
    from src.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "charts_dir", tmp_path)
    resp = PlotBarTool().run(
        {
            "data_path": str(SAMPLE),
            "x": "region",
            "y": "sales",
            "title": "Sales by region",
        }
    )
    assert resp.status.value == "success"
    assert Path(resp.data["path"]).exists()
    recorded = take_created_charts()
    assert recorded and recorded[0]["path"] == resp.data["path"]


def test_write_report_overwrites_same_job(tmp_path, monkeypatch):
    from src.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "reports_dir", tmp_path)
    first = write_markdown_report("job1", "# 分析报告\n第一版")
    second = write_markdown_report("job1", "# 分析报告\n第二版")
    assert first == second
    assert first == job_report_path("job1")
    assert first.read_text(encoding="utf-8") == "# 分析报告\n第二版"
    assert len(list(tmp_path.glob("*.md"))) == 1


def test_is_real_report_rejects_save_ack():
    assert _is_real_report("# 分析报告\n\n## 背景与问题\n内容足够长" + "。" * 80)
    assert not _is_real_report("报告已成功生成并保存。")
    assert not _is_real_report("")
