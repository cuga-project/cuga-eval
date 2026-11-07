import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from decide import decide  # noqa: E402


def m(recall, fd, cost=0.001, ms=100, cases=40):
    return {"cases": cases, "recall": recall, "false_deny": fd, "cost": cost, "p50_ms": ms}


def test_fd_above_2pct_is_remind_only():
    r = decide({"threshold": {"aws/gpt-oss-120b": m(0.9, 0.05), "code": m(0.8, 0.03)}})
    assert r["threshold"]["may_deny"] is False


def test_cheaper_within_2_points_wins():
    r = decide(
        {
            "format": {
                "aws/gpt-oss-120b": m(0.95, 0.0, cost=0.001),
                "openrouter:openai/gpt-oss-20b": m(0.94, 0.0, cost=0.0001),
            }
        }
    )
    assert r["format"]["model"] == "openrouter:openai/gpt-oss-20b"


def test_code_is_judged_on_its_own_and_low_recall_is_not_picked():
    r = decide(
        {"role_permission": {"code": m(1.0, 0.0), "kev": m(0.06, 0.0), "aws/gpt-oss-120b": m(0.94, 0.125)}}
    )
    assert r["role_permission"]["code_may_deny"] is True
    assert r["role_permission"]["may_deny"] is False and r["role_permission"]["checker"] == "verifier"


def test_under_10_cases_keeps_default():
    r = decide({"routing": {"code": m(1.0, 0.0, cases=6)}})
    assert r["routing"]["measured"] is False and r["routing"]["checker"] == "verifier"


def test_gemini_never_chosen():
    r = decide({"prohibition": {"gcp/gemini-3.8-flash": m(1.0, 0.0), "aws/gpt-oss-120b": m(0.7, 0.01)}})
    assert r["prohibition"]["model"] == "aws/gpt-oss-120b"
