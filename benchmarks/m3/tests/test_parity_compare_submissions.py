"""Task-by-task comparison of two submissions: normalization, categories, missing tasks, outputs."""

import json

import pytest

from benchmarks.m3.parity import compare_submissions as cs

pytestmark = pytest.mark.sanity


def _rec(uuid, answer, tools=(), status="success"):
    calls = [{"name": t, "arguments": {}} for t in tools]
    return {
        "uuid": uuid,
        "domain": "hockey",
        "status": status,
        "error": "" if answer else "TimeoutError: agent timed out",
        "duration_s": 1.0,
        "output": [{"turn_id": 0, "query": f"q {uuid}", "answer": answer, "sequence": {"tool_call": calls}}],
    }


def _write(root, cap, recs):
    d = root / cap
    d.mkdir(parents=True, exist_ok=True)
    (d / "hockey.json").write_text(json.dumps(recs))
    (d / "hockey_tools.json").write_text("{}")  # a sidecar: never read as a domain file


def test_normalization_and_categories():
    assert cs.normalize(' "16.0" ') == cs.normalize("16") == "16"
    assert cs.normalize("1,000 Teams.") == "1000 teams"
    assert cs.categorize(_rec("u", "16"), _rec("u", "16.0")) == "same"
    assert (
        cs.categorize(_rec("u", "16 teams, 3 coaches"), _rec("u", "3 coaches and 16 teams")) == "same_numbers"
    )
    assert cs.categorize(_rec("u", "16"), _rec("u", "17")) == "different"
    assert cs.categorize(_rec("u", "16"), _rec("u", "", status="error")) == "only_a"
    assert cs.categorize(_rec("u", ""), _rec("u", "x")) == "only_b"
    assert cs.categorize(_rec("u", ""), _rec("u", "")) == "neither"
    assert cs.categorize(None, _rec("u", "x")) == "missing_a"
    assert cs.categorize(_rec("u", "x"), None) == "missing_b"


def test_compare_writes_one_row_per_task_and_the_reports(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a, "capability_2_dashboard_apis", [_rec("H-1", "16", ["get_x"]), _rec("H-2", "", status="error")])
    _write(
        b, "capability_2_dashboard_apis", [_rec("H-1", "16", ["get_x"]), _rec("H-2", "7"), _rec("H-3", "1")]
    )
    rows = cs.compare(a, b)
    assert [(r["uuid"], r["category"]) for r in rows] == [
        ("H-1", "same"),
        ("H-2", "only_b"),
        ("H-3", "missing_a"),
    ]
    assert rows[0]["same_tools"] and rows[0]["tools_a"] == "get_x"
    out = tmp_path / "out"
    assert cs.main(["--a", str(a), "--b", str(b), "--out", str(out)]) == 0
    assert (out / "tasks.csv").read_text().count("\n") == 4  # header + 3 tasks
    page = (out / "report.html").read_text()
    assert "q H-3" in page and "only campaign" in page
    assert "ALL" in (out / "summary.txt").read_text()


def test_long_digit_strings_are_compared_as_written():
    big = "9" * 400
    assert cs.normalize(big) == big and cs.categorize(_rec("u", big), _rec("u", big + "1")) == "different"


def test_value_inside_a_sentence_and_dates_markdown_spaces():
    assert cs.normalize("**July\u202f1\u202f, 2013**") == cs.normalize("2013-07-01")
    assert (
        cs.categorize(_rec("u", "2013-07-01"), _rec("u", "It was created on **July 1, 2013**."))
        == "contained"
    )
    assert cs.categorize(_rec("u", "GLA"), _rec("u", "The short name is **GLA**.")) == "contained"
    assert (
        cs.categorize(_rec("u", "44"), _rec("u", "There are 442 molecules")) == "different"
    )  # not a substring hit
    assert cs.categorize(_rec("u", "4"), _rec("u", "4.5 percent")) == "different"
