"""EnterpriseOps-Gym grader defect: some `equals` checks store `expected_value` as an integer written as text ("1"),
and the upstream comparison `actual == expected` sets an integer COUNT against it, so the check can never pass.

`fixed_pass(row, config)` passes such a check when the text is an integer and equals the number. Every other check keeps
the upstream result. Exact type rule only: no text other than an integer is changed, and other comparison types are not
touched. It is a benchmark fix and applies to every arm; results are reported with and without it.

    python3 numeric_string_fix.py <result folder prefix>...   # strict and partial with and without the fix
"""

from __future__ import annotations

import glob
import json
import re
import statistics as st
import sys
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
INT_TEXT = re.compile(r"-?\d+")


def fixed_pass(row: Dict[str, Any], config: Dict[str, Any]) -> bool:
    if row.get("passed"):
        return True
    vc = config.get("validation_config") or {}
    expected, actual = row.get("expected"), row.get("actual")
    return (
        vc.get("comparison_type", "equals") == "equals"
        and isinstance(expected, str)
        and INT_TEXT.fullmatch(expected.strip()) is not None
        and isinstance(actual, (int, float))
        and not isinstance(actual, bool)
        and int(expected.strip()) == actual
    )


def tasks() -> Dict[str, dict]:
    out = {}
    for f in sorted(HERE.glob("tasks/*_oracle.json")):
        out.update({t["task_id"]: t for t in json.loads(f.read_text())})
    return out


def rescore(result: dict, task: dict) -> Dict[str, Any]:
    rows: List[dict] = result["score"]["detail"]["verifiers"]
    configs = task["verifiers"]
    if len(rows) != len(configs):
        raise ValueError(f"{task['task_id']}: {len(rows)} rows, {len(configs)} verifiers")
    fixed = [fixed_pass(r, c) for r, c in zip(rows, configs)]
    return {"pass": all(fixed), "partial": sum(fixed) / len(fixed), "changed": sum(f and not r["passed"] for f, r in zip(fixed, rows))}


def main(prefixes: List[str]) -> None:
    T = tasks()
    root = HERE.parent / "policy_eval/harness/results"
    for pre in prefixes:
        S, P, S2, P2, changed = {}, {}, {}, {}, 0
        for f in glob.glob(str(root / f"{pre}_t[0-9]/task_*.json")):
            d = json.loads(Path(f).read_text())
            if not d.get("score"):
                continue
            r = rescore(d, T[d["task"]])
            changed += r["changed"]
            for D, v in ((S, d["score"]["pass"]), (P, d["score"]["partial"]), (S2, r["pass"]), (P2, r["partial"])):
                D.setdefault(d["task"], []).append(float(v or 0))
        m = lambda D: 100 * st.mean(st.mean(v) for v in D.values()) if D else float("nan")  # noqa: E731
        print(f"{pre}: tasks {len(S)} strict {m(S):.1f} -> {m(S2):.1f}  partial {m(P):.1f} -> {m(P2):.1f}  checks changed {changed}")


if __name__ == "__main__":
    main(sys.argv[1:])
