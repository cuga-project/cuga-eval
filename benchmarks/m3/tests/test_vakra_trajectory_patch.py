"""Regression test for issue #71.

Vakra LLM-judge rescoring mutates ``result["match_rate"]`` /
``result["success"]`` in place after the cuga-agent tracker has already
flushed the pre-Vakra keyword score to its trajectory ``results.json``.
Without the post-Vakra patch, the bundled trajectories/results.json keeps
score=0 while report.md (which reads the SDK results.json) shows the
correct score — so reports disagree.

These tests exercise ``patch_tracker_scores`` against a fake tracker
that mirrors the public surface of ``cuga.backend.activity_tracker.tracker``
(update_task + tasks dict), so we don't have to spin up a real tracker.
"""

import json

import pytest

from benchmarks.m3.m3_vakra_score import patch_tracker_scores

pytestmark = pytest.mark.regression


class _FakeTracker:
    """Mimics the slice of ActivityTracker that patch_tracker_scores uses."""

    def __init__(self, task_ids):
        self.experiment_folder = "m3_evaluation_test"
        self.tasks = {tid: {"score": 0.0, "eval": "{}"} for tid in task_ids}

    def update_task(self, task_id, score=None, eval=None, **_):
        if task_id not in self.tasks:
            return False
        if score is not None:
            self.tasks[task_id]["score"] = score
        if eval is not None:
            self.tasks[task_id]["eval"] = eval
        return True


def _vakra_result(task_name, match_rate, success):
    return {
        "uuid": task_name,
        "task_name": task_name,
        "difficulty": "easy",
        "match_rate": match_rate,
        "success": success,
        "found_keywords": [],
        "missing_keywords": [],
    }


def test_patch_updates_score_and_eval_blob():
    tracker = _FakeTracker(["uuid-a", "uuid-b"])
    results = [
        _vakra_result("uuid-a", 1.0, True),
        _vakra_result("uuid-b", 0.0, False),
    ]

    patched = patch_tracker_scores(results, tracker)
    assert patched == 2

    assert tracker.tasks["uuid-a"]["score"] == 1.0
    ev_a = json.loads(tracker.tasks["uuid-a"]["eval"])
    assert ev_a["success"] is True
    assert ev_a["match_rate"] == 1.0
    assert ev_a["task_name"] == "uuid-a"

    # The failing task should still be patched (score/eval reflect the new verdict),
    # even though the verdict is "fail" — the point is consistency with report.md.
    assert tracker.tasks["uuid-b"]["score"] == 0.0
    ev_b = json.loads(tracker.tasks["uuid-b"]["eval"])
    assert ev_b["success"] is False


def test_patch_skips_unknown_task_ids():
    tracker = _FakeTracker(["uuid-a"])
    results = [
        _vakra_result("uuid-a", 1.0, True),
        _vakra_result("uuid-missing", 1.0, True),
    ]
    assert patch_tracker_scores(results, tracker) == 1
    assert "uuid-missing" not in tracker.tasks


def test_patch_noop_when_tracker_unconfigured():
    # No experiment_folder → tracker has nothing to write into.
    class _Bare:
        experiment_folder = None
        tasks = {"uuid-a": {}}

    assert patch_tracker_scores([_vakra_result("uuid-a", 1.0, True)], _Bare()) == 0


def test_patch_noop_when_tracker_is_none():
    assert patch_tracker_scores([_vakra_result("uuid-a", 1.0, True)], None) == 0


def test_patch_uses_task_name_when_uuid_missing():
    tracker = _FakeTracker(["task-fallback"])
    results = [{"task_name": "task-fallback", "match_rate": 1.0, "success": True}]
    assert patch_tracker_scores(results, tracker) == 1
    assert tracker.tasks["task-fallback"]["score"] == 1.0


def test_regression_vakra_inplace_mutation_leaves_tracker_stale_without_patch():
    """Issue #71 regression — asserts the exact pre-fix bad state and the
    post-fix good state.

    The bug: cuga-agent's ActivityTracker writes the pre-Vakra keyword-check
    score to its trajectory ``results.json`` at ``finish_task`` time. Vakra
    rescoring then mutates ``result["match_rate"]`` / ``result["success"]``
    *in place* (``m3_vakra_score._annotate_and_summarize``), but those updates
    only reach the SDK-level results.json (which feeds report.md). The
    tracker's trajectory file stays at the pre-Vakra score → bundles ship a
    trajectory that disagrees with report.md.

    Pre-patch: tracker has stale 0.0 score even though the in-memory results
    say match_rate=1.0. Post-patch: tracker matches the results list.
    """
    tracker = _FakeTracker(["uuid-a"])
    # Simulate tracker.finish_task having written the pre-Vakra keyword score.
    tracker.tasks["uuid-a"]["score"] = 0.0
    tracker.tasks["uuid-a"]["eval"] = json.dumps({"task_name": "uuid-a", "success": False, "match_rate": 0.0})

    # Simulate Vakra's in-place mutation (what _annotate_and_summarize does):
    # results gets updated match_rate/success but the tracker is untouched.
    results = [
        {
            "uuid": "uuid-a",
            "task_name": "uuid-a",
            "difficulty": "easy",
            "match_rate": 1.0,
            "success": True,
            "found_keywords": [],
            "missing_keywords": [],
        }
    ]

    # Pre-fix state: tracker is stale and disagrees with results.
    assert tracker.tasks["uuid-a"]["score"] == 0.0
    pre = json.loads(tracker.tasks["uuid-a"]["eval"])
    assert pre["success"] is False and pre["match_rate"] == 0.0
    # The in-memory results (source of truth for report.md) say otherwise.
    assert results[0]["success"] is True and results[0]["match_rate"] == 1.0

    # Apply the fix introduced by this PR.
    assert patch_tracker_scores(results, tracker) == 1

    # Post-fix state: tracker matches the corrected verdict.
    assert tracker.tasks["uuid-a"]["score"] == 1.0
    post = json.loads(tracker.tasks["uuid-a"]["eval"])
    assert post["success"] is True and post["match_rate"] == 1.0


def test_wiring_eval_m3_calls_patch_after_vakra():
    """Integration guard for issue #71.

    The unit tests above only exercise ``patch_tracker_scores`` in isolation —
    they'd still pass if a refactor dropped every call site in the eval loop.
    This test walks the AST of ``eval_m3`` and ``eval_m3_react`` and asserts
    that every call to ``vakra_score_results_async`` is followed by a call to
    ``patch_tracker_scores`` in the same code block (same parent statement
    list, within the next few sibling statements). The pairing is the actual
    fix; lose it and the trajectory goes stale again.
    """
    import ast
    import inspect

    from benchmarks.m3 import eval_m3, eval_m3_react

    for mod in (eval_m3, eval_m3_react):
        assert hasattr(mod, "patch_tracker_scores"), (
            f"{mod.__name__}: patch_tracker_scores wrapper missing — #71 fix dropped"
        )

        tree = ast.parse(inspect.getsource(mod))
        # Find call sites of vakra_score_results_async, ignoring the wrapper
        # def itself (its body returns _vakra().score_results_async(...), so
        # the name only appears in the FunctionDef header, not in a Call).
        unpaired = []
        for parent in ast.walk(tree):
            body = getattr(parent, "body", None)
            if not isinstance(body, list):
                continue
            for i, stmt in enumerate(body):
                if not _is_vakra_call(stmt):
                    continue
                # Look at the next few siblings for a patch_tracker_scores call.
                followers = body[i + 1 : i + 4]
                if not any(_is_patch_call(s) for s in followers):
                    line = getattr(stmt, "lineno", "?")
                    unpaired.append(f"{mod.__name__}:{line}")

        assert not unpaired, (
            "Vakra rescoring is not followed by patch_tracker_scores at: "
            + ", ".join(unpaired)
            + " — every vakra_score_results_async call must be paired with "
            "patch_tracker_scores so the tracker doesn't keep stale "
            "pre-Vakra scores (issue #71)."
        )


def _is_call_to(node, name):
    import ast

    if isinstance(node, ast.Expr):
        node = node.value
    if isinstance(node, ast.Await):
        node = node.value
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return isinstance(func, ast.Name) and func.id == name


def _is_vakra_call(stmt):
    return _is_call_to(stmt, "vakra_score_results_async")


def _is_patch_call(stmt):
    return _is_call_to(stmt, "patch_tracker_scores")
