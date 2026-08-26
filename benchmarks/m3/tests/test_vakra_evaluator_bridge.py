"""Tests for benchmarks/m3/evaluator/evaluator.py — the bridge to vendor/vakra's
evaluator (see that module's docstring for what it does and why).

These pin the four local overrides layered on top of vendor's own evaluator, so a
future vendor sync that silently fixes (or re-breaks) one of them is caught here
rather than discovered in a real scoring run.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip(
    "evaluator", reason="M3 Vakra vendor not installed; run ./setup_m3.sh to enable this test."
)

import evaluator as vakra_evaluator  # noqa: E402

pytestmark = pytest.mark.sanity


def test_default_judge_backend_is_litellm():
    registry = vakra_evaluator.build_default_capability_registry()
    policy = registry["capability_multiturn"]
    assert type(policy.correctness_judge.llm).__name__ == "_LiteLLMChatModel"
    assert type(policy.groundedness_judge.llm).__name__ == "_LiteLLMChatModel"
    assert type(policy.exactmatch_judge.llm).__name__ == "_LiteLLMChatModel"


def test_correctness_judge_find_first_json_object_is_callable():
    judge = vakra_evaluator._vendor_judge.CorrectnessJudge(config={})
    text = 'Here is the answer:\n```json\n{"score": "yes", "explanation": "ok"}\n```'
    result = judge._find_first_json_object(text)
    assert result == '{"score": "yes", "explanation": "ok"}'


def test_dialogue_scorer_records_missing_turn_instead_of_substituting():
    class _FakeTurnScorer:
        cfg = type("cfg", (), {"aggregate": "mean"})()

        def compare(self, **kwargs):
            raise AssertionError("compare() should not be called when the turn is missing")

    cfg = vakra_evaluator._vendor_scorer.DialogueScorerConfig(aggregate="mean")
    scorer = vakra_evaluator._PatchedDialogueScorer(turn_scorer=_FakeTurnScorer(), cfg=cfg)

    gt_dialogue = {"output": [{"turn_id": "t1", "query": "q1"}, {"turn_id": "t2", "query": "q2"}]}
    pred_dialogue = {"output": [{"turn_id": "some-other-turn"}]}

    score, details = scorer.score(gt_dialogue, pred_dialogue)

    assert score == 0.0
    assert len(details["per_turn"]) == 1
    assert details["per_turn"][0]["metadata"]["error"] == "missing predicted turn_id=t2"


def test_dialogue_scorer_still_scores_a_matched_turn():
    class _FakeTurnScorer:
        cfg = type("cfg", (), {"aggregate": "mean"})()

        def compare(self, **kwargs):
            return 1.0, {"ok": True}

    cfg = vakra_evaluator._vendor_scorer.DialogueScorerConfig(aggregate="mean")
    scorer = vakra_evaluator._PatchedDialogueScorer(turn_scorer=_FakeTurnScorer(), cfg=cfg)

    gt_dialogue = {"output": [{"turn_id": "t1", "query": "q1"}]}
    pred_dialogue = {"output": [{"turn_id": "t1", "answer": "the answer"}]}

    score, details = scorer.score(gt_dialogue, pred_dialogue)

    assert score == 1.0
    assert details["per_turn"][0]["metadata"] == {"ok": True}


def test_evaluate_domain_backfills_missing_predictions(monkeypatch):
    class _FakePolicy:
        dialogue_aggregate = "mean"
        execute_mcp_tools = False

    async def _fake_vendor_evaluate_domain(
        domain, gt_path, pred_path, policy, mcp_config, capability_name, policy_judge_path
    ):
        return {
            "domain": domain,
            "n_groundtruth": 3,
            "n_prediction": 1,
            "n_paired": 1,
            "missing_prediction_uuids": ["uuid-2", "uuid-3"],
            "extra_prediction_uuids": [],
            "dialogues": [{"uuid": "uuid-1", "score": 1.0, "metadata": {}, "details": {}}],
            "summary": {
                "num_samples": 3,
                "num_correct": 1.0,
                "mean_dialogue_score": 1.0,
                "min_dialogue_score": 1.0,
                "max_dialogue_score": 1.0,
            },
        }, [1.0]

    monkeypatch.setattr(vakra_evaluator, "_vendor_evaluate_domain", _fake_vendor_evaluate_domain)

    domain_out, scores = asyncio.run(
        vakra_evaluator.evaluate_domain("addr", None, None, _FakePolicy(), None, "capability_bi_apis")
    )

    assert len(domain_out["dialogues"]) == 3
    assert scores == [1.0, 0.0, 0.0]
    assert domain_out["summary"]["num_samples"] == 3
    assert domain_out["summary"]["mean_dialogue_score"] == pytest.approx(1.0 / 3)
    assert domain_out["summary"]["min_dialogue_score"] == 0.0
    missing_entries = [
        d for d in domain_out["dialogues"] if d["metadata"].get("error") == "missing_prediction"
    ]
    assert {d["uuid"] for d in missing_entries} == {"uuid-2", "uuid-3"}


def test_evaluate_domain_no_missing_predictions_is_a_passthrough(monkeypatch):
    class _FakePolicy:
        dialogue_aggregate = "mean"
        execute_mcp_tools = False

    expected = (
        {
            "domain": "addr",
            "n_groundtruth": 1,
            "missing_prediction_uuids": [],
            "dialogues": [{"uuid": "uuid-1", "score": 1.0, "metadata": {}, "details": {}}],
            "summary": {
                "num_samples": 1,
                "num_correct": 1.0,
                "mean_dialogue_score": 1.0,
                "min_dialogue_score": 1.0,
                "max_dialogue_score": 1.0,
            },
        },
        [1.0],
    )

    async def _fake_vendor_evaluate_domain(*args, **kwargs):
        return expected

    monkeypatch.setattr(vakra_evaluator, "_vendor_evaluate_domain", _fake_vendor_evaluate_domain)

    domain_out, scores = asyncio.run(
        vakra_evaluator.evaluate_domain("addr", None, None, _FakePolicy(), None, "capability_bi_apis")
    )

    assert domain_out == expected[0]
    assert scores == expected[1]


def test_evaluate_domain_defaults_policy_judge_path_when_present(monkeypatch):
    captured = {}

    async def _fake_vendor_evaluate_domain(
        domain, gt_path, pred_path, policy, mcp_config, capability_name, policy_judge_path
    ):
        captured["policy_judge_path"] = policy_judge_path
        return {"missing_prediction_uuids": [], "dialogues": [], "summary": {}}, []

    monkeypatch.setattr(vakra_evaluator, "_vendor_evaluate_domain", _fake_vendor_evaluate_domain)
    monkeypatch.setattr(type(vakra_evaluator._DEFAULT_POLICY_JUDGE_PATH), "is_file", lambda self: True)

    asyncio.run(vakra_evaluator.evaluate_domain("addr", None, None, object(), None, "capability_multiturn"))

    assert captured["policy_judge_path"] == str(vakra_evaluator._DEFAULT_POLICY_JUDGE_PATH)


def test_evaluate_domain_explicit_policy_judge_path_overrides_default(monkeypatch):
    captured = {}

    async def _fake_vendor_evaluate_domain(
        domain, gt_path, pred_path, policy, mcp_config, capability_name, policy_judge_path
    ):
        captured["policy_judge_path"] = policy_judge_path
        return {"missing_prediction_uuids": [], "dialogues": [], "summary": {}}, []

    monkeypatch.setattr(vakra_evaluator, "_vendor_evaluate_domain", _fake_vendor_evaluate_domain)

    asyncio.run(
        vakra_evaluator.evaluate_domain(
            "addr", None, None, object(), None, "capability_multiturn", policy_judge_path="/explicit/path.py"
        )
    )

    assert captured["policy_judge_path"] == "/explicit/path.py"
