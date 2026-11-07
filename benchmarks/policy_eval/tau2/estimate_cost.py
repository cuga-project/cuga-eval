#!/usr/bin/env python3
"""Estimate the cost of τ² CUGA runs. The runner saves no token counts and the trajectories keep no prompt text, so
the estimate comes from the scored conversations: every assistant message is one agent call that reads a fixed
prompt (CUGA system prompt + domain policy + tool schemas, --fixed tokens) plus the conversation so far; every user
message is one simulator call (~2k token guidelines + the conversation). Tokens = chars / 4.
--record adds one ledger line per run dir (once).

  python3 policy_eval/tau2/estimate_cost.py logging_tel_test_ds_s0 ... [--agent azure/DeepSeek-V4-Pro] [--record]
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import policy_pilot_costs as ppc  # noqa: E402

T2 = Path.home() / "dev/cuga-eval-tau2/benchmarks/tau2"


def estimate(run_dir: Path, fixed: int):
    a_in = a_out = u_in = u_out = n = 0
    for f in (run_dir / "results").glob("*.json"):
        d = json.load(open(f))
        for r in d.get("results", []) if isinstance(d, dict) else d:
            if not isinstance(r, dict):
                continue
            n += 1
            ctx = 0
            for m in r.get("messages") or []:
                k = len(json.dumps(m)) // 4
                if m.get("role") == "assistant":
                    a_in += fixed + ctx
                    a_out += k
                elif m.get("role") == "user":
                    u_in += 2000 + ctx
                    u_out += k
                ctx += k
    return n, a_in, a_out, u_in, u_out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--agent", default="azure/DeepSeek-V4-Pro")
    ap.add_argument("--user-sim", default="Azure/gpt-5-mini-2025-08-07")
    ap.add_argument(
        "--fixed", type=int, default=13000, help="agent prompt tokens per call (telecom ~13k, airline ~9k)"
    )
    ap.add_argument("--record", action="store_true")
    a = ap.parse_args()
    ppc.PRICES.setdefault("Azure/gpt-4.1", (2.00, 8.00))
    done = (
        {json.loads(l)["name"] for l in ppc.LEDGER.read_text().splitlines() if l.strip()}
        if ppc.LEDGER.exists()
        else set()
    )
    tot = 0.0
    for d in a.dirs:
        n, a_in, a_out, u_in, u_out = estimate(T2 / d, a.fixed)
        pa, pu = ppc._price(a.agent), ppc._price(a.user_sim)
        c = (a_in * pa[0] + a_out * pa[1] + u_in * pu[0] + u_out * pu[1]) / 1e6
        tot += c
        print(
            f"{d:28} {n:3} tasks | agent {a_in / 1e6:5.2f}M in {a_out / 1e3:5.0f}k out | sim {u_in / 1e6:5.2f}M in | ${c:6.2f}"
        )
        if a.record and f"tau2/{d}" not in done:
            with ppc.LEDGER.open("a") as fh:
                fh.write(
                    json.dumps(
                        {
                            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "kind": "tau2_run_estimate",
                            "name": f"tau2/{d}",
                            "agent_in": a_in,
                            "agent_out": a_out,
                            "policy_in": u_in,
                            "policy_out": u_out,
                            "policy_calls": 0,
                            "cost_usd": round(c, 4),
                        }
                    )
                    + "\n"
                )
    print(f"total ${tot:.2f}; ledger now ${ppc.spent():.2f}")
