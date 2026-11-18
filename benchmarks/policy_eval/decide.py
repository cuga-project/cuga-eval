"""The method decision rule (design §7, fixed 2026-11-01 before the comparison), per statement type.

0. Code is judged on its own (it only covers statements that have a code rule): it may deny if its false deny rate
   is at most 2%. The rules below choose the checker for the type's other statements (the verifier side).
1. A method may deny for a type only if its false deny rate on that type's cases is at most 2%, and it catches at
   least half of the violations (amended 2026-11-01 after the comparison picked a judge with recall 0.06).
2. Among the methods allowed to deny, take the one that catches the most real violations (recall on "deny" cases).
3. Take a cheaper or faster method instead if it catches at most 2 points fewer and its false deny rate is not higher.
4. Reference models are never picked. If no other method passes rule 1, the type uses the default verifier in
   remind-only mode.
5. A type with fewer than 10 cases keeps the default and is marked "not measured".

Input: {type: {method: {"cases": n, "recall": 0..1, "false_deny": 0..1, "cost": $/check, "p50_ms": ms}}}.
Output: {type: {"checker", "model", "may_deny", "measured", "why"}} = method_choice.json.
"""

from __future__ import annotations

from typing import Any, Dict

FALSE_DENY_MAX = 0.02
NEAR = 0.02
MIN_CASES = 10
MIN_RECALL = 0.5
DEFAULT = {"checker": "verifier", "model": "aws/gpt-oss-120b"}
REFERENCE = {"gcp/gemini-3.8-flash"}
CHECKER = {"code": "code", "cedar": "cedar", "kev": "kev"}


def _entry(method: str) -> Dict[str, Any]:
    if method in CHECKER:
        return {"checker": CHECKER[method], "model": "jaredpalmer/kev-4b" if method == "kev" else None}
    return {"checker": "verifier", "model": method}


def decide(results: Dict[str, Dict[str, Dict[str, float]]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for typ, methods in results.items():
        cands = {m: v for m, v in methods.items() if m not in REFERENCE}
        n = max((v.get("cases", 0) for v in methods.values()), default=0)
        if n < MIN_CASES:
            out[typ] = {**DEFAULT, "may_deny": True, "measured": False, "why": f"{n} cases (< {MIN_CASES})"}
            continue
        code = cands.pop("code", None)
        code_note = (
            {}
            if code is None
            else {
                "code_may_deny": code.get("false_deny", 1.0) <= FALSE_DENY_MAX,
                "code": f"recall {code['recall']:.2f}, false deny {code['false_deny']:.1%} on {code['cases']} cases",
            }
        )
        ok = {
            m: v
            for m, v in cands.items()
            if v.get("false_deny", 1.0) <= FALSE_DENY_MAX and v.get("recall", 0) >= MIN_RECALL
        }
        if not ok:
            out[typ] = {
                **DEFAULT,
                "may_deny": False,
                "measured": True,
                **code_note,
                "why": f"no model with false deny <= {FALSE_DENY_MAX:.0%} and recall >= {MIN_RECALL:.0%}: remind only",
            }
            continue
        best = max(ok, key=lambda m: (ok[m]["recall"], -ok[m]["false_deny"]))
        cheaper = [
            m
            for m in ok
            if m != best
            and ok[m]["recall"] >= ok[best]["recall"] - NEAR
            and ok[m]["false_deny"] <= ok[best]["false_deny"]
            and (ok[m].get("cost", 0), ok[m].get("p50_ms", 0))
            < (ok[best].get("cost", 0), ok[best].get("p50_ms", 0))
        ]
        pick = min(cheaper, key=lambda m: (ok[m].get("cost", 0), ok[m].get("p50_ms", 0))) if cheaper else best
        v = ok[pick]
        out[typ] = {
            **_entry(pick),
            "may_deny": True,
            "measured": True,
            **code_note,
            "why": f"recall {v['recall']:.2f}, false deny {v['false_deny']:.2%}, best was {best}",
        }
    return out
