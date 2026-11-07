"""HOOKS_MODULE factories for the HANDBOOK runner: SOP planner spikes (level 1: plan; level 3: plan + next step + guide).
Planner model: POLICY_PLANNER_MODEL (default azure/DeepSeek-V4-Pro)."""

import os
from pathlib import Path

BUILDS = Path(__file__).resolve().parent.parent / "policy_eval/builds_handbook/v3"


def _planner(ctx, directive):
    from cuga.policy_layer.llm import openai_json_model
    from cuga.policy_layer.sop_planner import planner_from_build

    model = openai_json_model(
        os.environ.get("POLICY_PLANNER_MODEL") or "azure/DeepSeek-V4-Pro", timeout=400, max_tokens=16000
    )
    return planner_from_build(str(BUILDS / f"{ctx['task']}.json"), model, directive=directive)


def plan_only(ctx):
    return _planner(ctx, directive=False)


def plan_next_guide(ctx):
    from cuga.policy_layer.procedure_guide import guide_from_env

    return [_planner(ctx, directive=True), guide_from_env(str(BUILDS / f"{ctx['task']}.json"))]
