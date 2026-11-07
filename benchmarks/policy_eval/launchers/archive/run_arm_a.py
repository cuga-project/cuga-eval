#!/usr/bin/env python3
"""τ² airline headroom check, arm A (CUGA alone): run the PR #139 τ² runner from the ~/dev/cuga-eval-tau2 worktree
with a CUGA code snapshot, function calling, and a chosen agent model. Secrets (OPENAI_*) come from cuga-eval/.env and
are never printed; Langfuse is off.

  python3 policy_eval/tau2/run_arm_a.py --snapshot ~/dev/cuga_snapshots/<name>/src --agent-model azure/DeepSeek-V4-Pro --tag ds --num-tasks 20
  python3 policy_eval/tau2/run_arm_a.py --snapshot ~/dev/cuga_snapshots/<name>/src --agent-model aws/gpt-oss-120b --tag oss --num-tasks 20
"""

import argparse
import os
import subprocess
from pathlib import Path

WT = Path.home() / "dev/cuga-eval-tau2"
EVAL = Path.home() / "dev/cuga-eval"
FC = {  # same agent flags as benchmarks/automationbench/cuga.fc.dsv4.env (function calling)
    "DYNACONF_ADVANCED_FEATURES__CUGA_LITE_EXECUTION_MODE": "function_calling",
    "DYNACONF_ADVANCED_FEATURES__CUGA_LITE_FC_PROMPT_FRAGMENTS": '["evidence_first"]',
    "DYNACONF_ADVANCED_FEATURES__PRE_EXECUTE_VERIFY_ENABLED": "false",
    "DYNACONF_ADVANCED_FEATURES__DECOMPOSITION_STRATEGY": "exact",
    "DYNACONF_ADVANCED_FEATURES__CUGA_LITE_UNEXECUTED_CLAIM_RETRY": "true",
    "DYNACONF_ADVANCED_FEATURES__TRACKER_ENABLED": "true",
    "DYNACONF_ADVANCED_FEATURES__RUN_RECEIPT": "true",
    "DYNACONF_ADVANCED_FEATURES__LANGFUSE_TRACING": "false",
    "CUGA_LLM_HTTP_TIMEOUT": "120",
}
SETTINGS = {"aws/gpt-oss-120b": "settings.openai.gptoss-default.toml"}  # max_tokens 16000, default reasoning


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent-model", required=True)
    ap.add_argument("--domain", default="airline", choices=["airline", "retail", "telecom"])
    ap.add_argument("--split", help="official split name in the domain's split_tasks.json (e.g. test, base)")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--num-tasks", type=int, default=20)
    ap.add_argument("--task", nargs="*")
    ap.add_argument("--user-sim", default="openai/Azure/gpt-5-mini-2025-08-07")
    ap.add_argument("--max-steps", type=int, default=100)
    ap.add_argument(
        "--snapshot", required=True, help="~/dev/cuga_snapshots/<name>/src (policy_eval/snapshot_src.sh)"
    )
    a = ap.parse_args()
    snapshot = Path(a.snapshot).expanduser()
    if (
        not snapshot.is_dir()
    ):  # a missing path would be skipped by Python and cuga would come from the venv (main)
        raise SystemExit(f"no snapshot {snapshot}")
    from dotenv import dotenv_values

    env = dict(os.environ)
    sec = dotenv_values(EVAL / ".env")
    for k in ("OPENAI_API_KEY", "OPENAI_BASE_URL") + (
        ("OPENROUTER_API_KEY",) if env.get("SOP_NAVIGATOR") == "1" else ()
    ):
        if sec.get(k):
            env[k] = sec[k]
    for k in [k for k in env if k.startswith("LANGFUSE_")]:
        env.pop(k)
    env.update(FC)
    env.update(
        {
            "MODEL_NAME": a.agent_model,
            "AGENT_SETTING_CONFIG": SETTINGS.get(a.agent_model, "settings.openai.toml"),
            "PYTHONPATH": str(snapshot) + os.pathsep + str(WT),
            "CUGA_LOGGING_DIR": f"benchmarks/tau2/logging_{a.tag}",
            "PYTHONUNBUFFERED": "1",
        }
    )
    cmd = [
        str(WT / ".venv/bin/python"),
        "-m",
        "benchmarks.tau2.eval_tau2_sdk",
        "--subset",
        a.domain,
        "--max-workers",
        str(a.workers),
        "--agent",
        "cuga",
        "--user-simulator-model",
        a.user_sim,
        "--max-steps",
        str(a.max_steps),
        "--run-id",
        a.tag,
    ]
    if a.split and not a.task:  # the benchmark's own split, not the first N tasks of the full list
        import json as _json

        splits = _json.loads(
            (WT / "benchmarks/tau2/tau2-bench/data/tau2/domains" / a.domain / "split_tasks.json").read_text()
        )
        a.task = list(splits[a.split])
    cmd += ["--task", *a.task] if a.task else ["--num-tasks", str(a.num_tasks)]
    raise SystemExit(subprocess.call(cmd, cwd=WT, env=env))


if __name__ == "__main__":
    main()
