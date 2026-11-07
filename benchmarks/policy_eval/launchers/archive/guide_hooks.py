"""HOOKS_MODULE factory for the HANDBOOK runner: the procedure guide from the task SOP's offline intake build
(policy_eval/builds_handbook/v3/<task>.json; the SOP is a known policy document, read ahead of time).
POLICY_GUIDE_EVIDENCE=1 adds evidence checks of preconditions (model POLICY_GUIDE_MODEL, default aws/gpt-oss-120b)."""

from pathlib import Path

BUILDS = (
    Path(__file__).resolve().parent.parent
    / "policy_eval/builds_handbook"
    / __import__("os").environ.get("HB_BUILDS", "v3")
)


def make_hooks(ctx):
    from cuga.policy_layer.procedure_guide import guide_from_env

    return guide_from_env(str(BUILDS / f"{ctx['task']}.json"))
