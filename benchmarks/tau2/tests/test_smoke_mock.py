"""End-to-end smoke: one `mock` task through CUGA + the bridge + τ² (Phase 5).

This is the first test that runs the WHOLE pipeline live — τ²'s orchestrator + user
simulator on a background thread, CUGA on the main thread, connected by the bridge. It
therefore needs:
  - the `tau2` dependency group (importorskip), and
  - a user-simulator model + creds, supplied via env:
      TAU2_USER_SIM_MODEL  — the LiteLLM model string for τ²'s customer LLM
      (+ whatever creds that model needs, e.g. OPENAI_BASE_URL / OPENAI_API_KEY)
    If TAU2_USER_SIM_MODEL is unset, the test skips (so CI without creds stays green).

Marked regression: it spends real LLM calls (both CUGA and the user simulator).
"""

import os

import pytest

pytest.importorskip("tau2")

pytestmark = pytest.mark.regression


def test_smoke_mock_one_task():
    user_sim_model = os.environ.get("TAU2_USER_SIM_MODEL")
    if not user_sim_model:
        pytest.skip("set TAU2_USER_SIM_MODEL (+ creds) to run the live mock smoke")

    # config-before-cuga-import, same contract as the real entrypoint
    from config_loader import load_eval_config

    load_eval_config("tau2")

    from tau2.runner.helpers import get_tasks

    from benchmarks.tau2.cuga_runner import _run_one_task

    tasks = get_tasks("mock", num_tasks=1)
    assert tasks, "no mock tasks found — is τ² data installed? (tau2 check-data)"

    # pass the user-sim LLM's creds through (watsonx needs project_id; the gateway api_base/key)
    llm_args_user = {}
    if os.environ.get("WATSONX_PROJECT_ID"):
        llm_args_user["project_id"] = os.environ["WATSONX_PROJECT_ID"]
    elif os.environ.get("OPENAI_BASE_URL"):
        llm_args_user["api_base"] = os.environ["OPENAI_BASE_URL"]
        llm_args_user["api_key"] = os.environ.get("OPENAI_API_KEY")

    reward = _run_one_task("mock", tasks[0], user_sim_model, llm_args_user=llm_args_user, max_steps=30)

    # The point of the smoke test: it completes without hanging and returns a real reward.
    assert reward is None or (0.0 <= reward <= 1.0), f"reward out of range: {reward}"

    # no CUGA/τ² threads should be left alive
    import threading

    assert not any(t.name == "tau2-run" and t.is_alive() for t in threading.enumerate())
