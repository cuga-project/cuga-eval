"""τ²-native agent path (`--agent llm_agent`). No LLM, no τ² run.

The native path (_run_one_task_native) bypasses the bridge entirely: τ²'s own agent solves
the task in-process. These tests pin the two things that matter without spinning up τ²:
  1. _run_one_task(agent != "cuga") dispatches to the native path and forwards agent config.
  2. the native path builds a TextRunConfig with the agent's model/creds and returns τ²'s reward.
"""

from types import SimpleNamespace

import pytest

import benchmarks.tau2.cuga_runner as runner

pytestmark = pytest.mark.sanity


def test_non_cuga_agent_dispatches_to_native(monkeypatch):
    """A non-cuga agent short-circuits to _run_one_task_native BEFORE any bridge/τ² setup,
    forwarding the agent name + model + creds. (If the cuga path ran instead, it would try to
    build a τ² env and bridge — so returning the sentinel proves the early dispatch.)"""
    captured = {}

    def fake_native(domain, task, **kwargs):
        captured["domain"] = domain
        captured["task"] = task
        captured.update(kwargs)
        return 0.5

    monkeypatch.setattr(runner, "_run_one_task_native", fake_native)

    task = SimpleNamespace(id="t1")
    reward = runner._run_one_task(
        "retail",
        task,
        "openai/user-sim",
        agent="llm_agent",
        agent_model="openai/Azure/gpt-4.1",
        agent_llm_args={"api_base": "http://gw", "api_key": "k"},
        llm_args_user={"api_base": "http://gw"},
        max_steps=7,
    )

    assert reward == 0.5
    assert captured["agent"] == "llm_agent"
    assert captured["agent_model"] == "openai/Azure/gpt-4.1"
    assert captured["agent_llm_args"] == {"api_base": "http://gw", "api_key": "k"}
    assert captured["user_sim_model"] == "openai/user-sim"
    assert captured["max_steps"] == 7


def test_native_builds_config_and_returns_reward(monkeypatch):
    """_run_one_task_native hands τ² a run config carrying the agent's model + creds, runs
    τ²'s own task runner, and returns its reward — no bridge involved."""
    import tau2.runner.batch as tau2_batch

    # Stub out the scoring-reachability patch + langfuse so the test needs no network/keys.
    monkeypatch.setattr(runner, "_patch_tau2_nl_assertion_model", lambda *a, **k: "judge-x")
    monkeypatch.setattr(runner, "_maybe_setup_langfuse", lambda *a, **k: (None, "trace-x", None))
    monkeypatch.setattr(runner, "_maybe_score_and_flush", lambda *a, **k: None)

    seen = {}

    def fake_run_single_task(cfg, task):
        seen["cfg"] = cfg
        return SimpleNamespace(reward_info=SimpleNamespace(reward=1.0), messages=[])

    monkeypatch.setattr(tau2_batch, "run_single_task", fake_run_single_task)

    out: dict = {}
    reward = runner._run_one_task_native(
        "mock",
        SimpleNamespace(id="task_1"),
        agent="llm_agent",
        agent_model="openai/Azure/gpt-4.1",
        agent_llm_args={"api_base": "http://gw", "api_key": "k"},
        user_sim_model="openai/user-sim",
        llm_args_user={"api_base": "http://gw"},
        max_steps=5,
        thread_id=None,
        out=out,
    )

    assert reward == 1.0
    # The agent's model + creds reached τ²'s config (this is what makes the baseline runnable).
    cfg = seen["cfg"]
    assert cfg.agent == "llm_agent"
    assert cfg.llm_agent == "openai/Azure/gpt-4.1"
    assert cfg.llm_args_agent == {"api_base": "http://gw", "api_key": "k"}
    assert cfg.llm_user == "openai/user-sim"
    # Side outputs recorded for the results JSON.
    assert out["nl_judge_model"] == "judge-x"
    assert out["trace_id"] == "trace-x"
