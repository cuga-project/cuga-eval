"""Glue between M3 agent results and the Vakra evaluator (benchmarks/m3/evaluator/).

The evaluator was authored to be invoked from its own working directory, so its
internal imports use sibling-module form (``from judge import ...`` rather than
``from .judge import ...``). We keep the package drop-in by prepending the
package directory to ``sys.path`` here.

Both sync (``score_results``) and async (``score_results_async``) entry points
are provided. M3 eval scripts run inside an asyncio event loop, so they MUST
use the async variant — calling ``score_results`` from inside a running loop
raises immediately rather than crashing later inside ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_EVAL_DIR = Path(__file__).resolve().parent / "evaluator"
# The upstream vendor was renamed `enterprise-benchmark` → `vakra`. Try the
# new name first; fall back to the old name so older clones still work.
_VENDOR_ROOT = Path(__file__).resolve().parents[2] / "vendor"
_VENDOR = next(
    (_VENDOR_ROOT / d for d in ("vakra", "enterprise-benchmark") if (_VENDOR_ROOT / d).is_dir()),
    _VENDOR_ROOT / "vakra",
)
# Order matters: insert _VENDOR first (lower priority), then _EVAL_DIR (highest
# priority). Otherwise vendor's older evaluator/ package shadows our copy when
# Python resolves `import evaluator` and `from judge import ...`.
for _p in (str(_VENDOR), str(_EVAL_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import evaluator as vakra_evaluator  # noqa: E402

CAPABILITY_DEFAULT = "capability_bi_apis"


def capability_name_for_task_id(task_id: Any) -> Optional[str]:
    """Map an M3 task_id (1-4 or the string forms ``m3_task_<id>`` /
    ``capability_<id>_<...>``) to Vakra's capability_name string.

    Returns ``None`` if the input doesn't look like a known M3 task_id, so the
    caller can fall back to its default.
    """
    if task_id is None:
        return None
    cap_map = getattr(vakra_evaluator, "CAPABILITY_MCP_TOOL_MAP", {})
    inverted = {int(v): k for k, v in cap_map.items()}

    if isinstance(task_id, int):
        return inverted.get(task_id)
    s = str(task_id).strip()
    if s.isdigit():
        return inverted.get(int(s))
    # m3_task_<n>
    if s.startswith("m3_task_") and s[len("m3_task_") :].isdigit():
        return inverted.get(int(s[len("m3_task_") :]))
    # capability_<n>_<...>
    if s.startswith("capability_"):
        rest = s[len("capability_") :]
        first = rest.split("_", 1)[0]
        if first.isdigit():
            return inverted.get(int(first))
    # Already a Vakra capability_name
    if s in cap_map:
        return s
    return None


_DEFAULT_MCP_CONFIG_PATH = _VENDOR / "benchmark" / "mcp_connection_config.yaml"


_REGISTRY_PREFIX_RE = None  # populated lazily on first use


def _strip_registry_prefix(name: str) -> str:
    """Strip a leading ``task_<id>_<domain>_`` registry prefix if present.

    The registry server (benchmarks/m3/run_registry.sh) renames each capability
    container's MCP tools as ``task_<task_id>_<domain>_<short_name>``. The
    underlying MCP server itself exposes the long auto-generated operation_id
    (e.g. ``get_players_by_position_no_shoot_catch_v1_hockey_players_by_position_no_shoot_catch_get``).
    """
    global _REGISTRY_PREFIX_RE
    if _REGISTRY_PREFIX_RE is None:
        import re as _re

        _REGISTRY_PREFIX_RE = _re.compile(r"^task_\d+_[A-Za-z0-9]+_(.+)$")
    m = _REGISTRY_PREFIX_RE.match(name)
    return m.group(1) if m else name


def _collect_tool_names(dialogues: List[Dict[str, Any]]) -> List[str]:
    """Return the distinct tool_call names that appear in a list of dialogues."""
    names: List[str] = []
    seen = set()
    for d in dialogues:
        for turn in d.get("output", []) or []:
            for tc in (turn.get("sequence") or {}).get("tool_call", []) or []:
                n = tc.get("name") or ""
                if n and n not in seen:
                    seen.add(n)
                    names.append(n)
    return names


def _match_live_name(name: str, live_tool_names: List[str]) -> Optional[str]:
    """Resolve ``name`` to a live MCP tool name, accounting for the three
    naming conventions in play:

    - registry-prefixed: ``task_<id>_<domain>_<short>`` (what the agent records)
    - short form: ``<short>`` (what the capability container often exposes)
    - long form: ``<short>_v1_<domain>_<...>_get`` (what the zip's
      gold_sequence carries — FastAPI auto-generated operation_id)

    The matcher tries exact, then directional prefix matches in both directions,
    so a live "short" name resolves both registry-prefixed and long-form inputs.
    """
    if name in live_tool_names:
        return name
    stripped = _strip_registry_prefix(name)
    if stripped != name and stripped in live_tool_names:
        return stripped

    candidates: List[str] = []
    for ln in live_tool_names:
        # Live name is the canonical short form, name extends it (long form).
        if name.startswith(ln + "_"):
            candidates.append(ln)
        # Live name extends the (possibly stripped) input (live is long form).
        elif ln.startswith(stripped + "_"):
            candidates.append(ln)

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    # Tie-break: shortest match — closest to the canonical short form.
    return min(candidates, key=len)


def _build_name_map(
    dialogues: List[Dict[str, Any]], live_tool_names: List[str]
) -> Tuple[Dict[str, str], List[str]]:
    """Build {original_name → live_name} for every distinct tool name in the
    dialogues. Returns (mapping, unmapped_names)."""
    name_map: Dict[str, str] = {}
    unmapped: List[str] = []
    for n in _collect_tool_names(dialogues):
        live = _match_live_name(n, live_tool_names)
        if live is not None:
            name_map[n] = live
        else:
            unmapped.append(n)
    return name_map, unmapped


def _apply_name_map(dialogues: List[Dict[str, Any]], name_map: Dict[str, str]) -> int:
    """Rewrite tool_call names in place across a list of dialogues. Returns count rewritten."""
    n_rewrites = 0
    for d in dialogues:
        for turn in d.get("output", []) or []:
            for tc in (turn.get("sequence") or {}).get("tool_call", []) or []:
                old = tc.get("name") or ""
                new = name_map.get(old)
                if new and new != old:
                    tc["name"] = new
                    n_rewrites += 1
    return n_rewrites


async def _rewrite_tool_names_for_live_mcp(
    pred_path: Path, gt_path: Path, mcp_config: Any, domain: str
) -> Tuple[int, int, List[str], List[str]]:
    """Open a pre-flight session, list live MCP tools, rewrite *both* the
    prediction and ground-truth files in place to use live tool names.

    Returns (pred_rewrites, gt_rewrites, pred_unmapped, gt_unmapped).
    """
    pred_dialogues = json.loads(pred_path.read_text(encoding="utf-8"))
    gt_dialogues = json.loads(gt_path.read_text(encoding="utf-8"))
    async with vakra_evaluator.create_client_and_connect(mcp_config, domain) as session:
        tools_result = await session.list_tools()
        live_tool_names = [t.name for t in tools_result.tools]

    pred_map, pred_unmapped = _build_name_map(pred_dialogues, live_tool_names)
    gt_map, gt_unmapped = _build_name_map(gt_dialogues, live_tool_names)
    pred_n = _apply_name_map(pred_dialogues, pred_map)
    gt_n = _apply_name_map(gt_dialogues, gt_map)
    if pred_n:
        pred_path.write_text(json.dumps(pred_dialogues, indent=2, ensure_ascii=False), encoding="utf-8")
    if gt_n:
        gt_path.write_text(json.dumps(gt_dialogues, indent=2, ensure_ascii=False), encoding="utf-8")
    return pred_n, gt_n, pred_unmapped, gt_unmapped


def _resolve_mcp_config(capability_name: str) -> Tuple[Optional[Any], Optional[str]]:
    """Resolve the MCPConnectionConfig for ``capability_name``.

    Returns ``(mcp_config, error_message)``. ``mcp_config`` is ``None`` if the
    YAML can't be loaded or no entry matches. ``error_message`` describes the
    failure when ``mcp_config`` is ``None``; both ``None`` means the lookup
    succeeded but the YAML simply doesn't list this capability.
    """
    config_path = os.getenv("M3_VAKRA_MCP_CONFIG") or str(_DEFAULT_MCP_CONFIG_PATH)
    if not Path(config_path).is_file():
        return None, f"MCP config not found at {config_path}"

    cap_map = getattr(vakra_evaluator, "CAPABILITY_MCP_TOOL_MAP", {})
    if capability_name not in cap_map:
        return None, f"capability '{capability_name}' not in CAPABILITY_MCP_TOOL_MAP"

    try:
        configs_by_id = vakra_evaluator.load_mcp_config(config_path)
    except Exception as e:  # noqa: BLE001 — surface the message to caller
        return None, f"load_mcp_config({config_path}) failed: {type(e).__name__}: {e}"

    cfg = configs_by_id.get(int(cap_map[capability_name]))
    if cfg is None:
        return None, f"no entry for capability_id={cap_map[capability_name]} in {config_path}"
    return cfg, None


def _result_uuid(result: Dict[str, Any]) -> Optional[str]:
    return (
        result.get("uuid")
        or (result.get("task_metadata") or {}).get("uuid")
        or result.get("name")
        or result.get("task_name")
    )


def _norm_tc(tc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": tc.get("name", ""),
        "arguments": tc.get("arguments", tc.get("args", {})),
    }


def _norm_resp(tc: Dict[str, Any]) -> str:
    if not tc:
        return ""
    payload = tc.get("result") if "result" in tc else tc.get("error", "")
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, default=str)
    except (TypeError, ValueError):
        return str(payload)


def _norm_gt_resp(payload: Any) -> Any:
    """Pass-through normalizer for GT tool_response payloads. Vakra's scorer
    flattens these (scorer.py:_extract_tool_responses) and stringifies via
    ExactMatchJudge._as_list_of_str, so we just hand the raw value through."""
    return payload


def _to_vakra_pair(
    result: Dict[str, Any],
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Build (gt_dialogue, pred_dialogue) from one agent result. None if unscorable."""
    uuid = _result_uuid(result)
    if not uuid:
        return None
    domain = result.get("domain") or (result.get("task_metadata") or {}).get("domain") or "hockey"
    intent = result.get("intent") or result.get("query") or ""
    expected = result.get("expected_output") or {}
    expected_resp = expected.get("response") or ""
    expected_tcs_raw = expected.get("tool_calls") or []
    expected_tool_responses = expected.get("tool_responses") or []
    pred_answer = result.get("answer") or result.get("response") or ""
    pred_tcs_raw = result.get("tool_calls") or []

    gt = {
        "uuid": uuid,
        "domain": domain,
        "output": [
            {
                "turn_id": 0,
                "query": intent,
                "answer": expected_resp,
                "sequence": {
                    "tool_call": [_norm_tc(tc) for tc in expected_tcs_raw],
                    "tool_response": [_norm_gt_resp(r) for r in expected_tool_responses],
                },
            }
        ],
    }
    pred = {
        "uuid": uuid,
        "domain": domain,
        "output": [
            {
                "turn_id": 0,
                "query": intent,
                "answer": pred_answer,
                "sequence": {
                    "tool_call": [_norm_tc(tc) for tc in pred_tcs_raw],
                    "tool_response": [_norm_resp(tc) for tc in pred_tcs_raw],
                },
            }
        ],
    }
    return gt, pred


def _prepare_inputs(
    results: List[Dict[str, Any]],
    output_dir: Path,
    domain: str,
) -> Optional[Tuple[Path, Path, Path, Path, Path]]:
    """Write GT + prediction Vakra files. Returns (work, gt_dir, pred_dir, gt_path, pred_path) or None."""
    work = Path(output_dir) / "_vakra"
    gt_dir = work / "groundtruth"
    pred_dir = work / "prediction"
    gt_dir.mkdir(parents=True, exist_ok=True)
    pred_dir.mkdir(parents=True, exist_ok=True)

    pairs = [pair for pair in (_to_vakra_pair(r) for r in results) if pair]
    if not pairs:
        return None
    gt_list = [g for g, _ in pairs]
    pred_list = [p for _, p in pairs]
    gt_path = gt_dir / f"{domain}.json"
    pred_path = pred_dir / f"{domain}.json"
    gt_path.write_text(json.dumps(gt_list, indent=2))
    pred_path.write_text(json.dumps(pred_list, indent=2))
    return work, gt_dir, pred_dir, gt_path, pred_path


def _annotate_and_summarize(
    results: List[Dict[str, Any]],
    domain: str,
    domain_out: Dict[str, Any],
    work: Path,
    gt_dir: Path,
    pred_dir: Path,
    capability_name: str,
) -> Dict[str, Any]:
    """Annotate results in-place from domain_out, write results.json, return summary dict."""
    domain_out_full = dict(domain_out)
    if "summary" not in domain_out_full:
        scores = [d["score"] for d in domain_out_full.get("dialogues", [])]
        domain_out_full["summary"] = {
            "num_samples": domain_out_full.get("n_paired", len(scores)),
            "num_correct": sum(scores) if scores else 0.0,
            "mean_dialogue_score": (sum(scores) / len(scores)) if scores else 0.0,
            "min_dialogue_score": min(scores) if scores else 0.0,
            "max_dialogue_score": max(scores) if scores else 0.0,
        }

    summary: Dict[str, Any] = {
        "capability_name": capability_name,
        "groundtruth_dir": str(gt_dir),
        "prediction_dir": str(pred_dir),
        "domains": {domain: domain_out_full},
        "summary": domain_out_full["summary"],
    }
    out_path = work / "results.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    by_uuid = {d["uuid"]: d for d in domain_out_full.get("dialogues", [])}
    for r in results:
        uuid = _result_uuid(r)
        if uuid in by_uuid:
            d = dict(by_uuid[uuid])
            d["_results_path"] = str(out_path)
            r["vakra"] = d
            r["match_rate"] = float(d["score"])
            r["success"] = float(d["score"]) >= 1.0
    summary["_results_path"] = str(out_path)
    return summary


def patch_tracker_scores(results: List[Dict[str, Any]], tracker: Any) -> int:
    """Sync Vakra-corrected scores back into the tracker's trajectory files.

    The tracker writes results.json/results.csv at ``finish_task`` time with the
    pre-Vakra keyword score. Vakra rescoring mutates ``results[i]["match_rate"]``
    and ``results[i]["success"]`` in place, but those updated values never reach
    the trajectory bundle — so trajectories/results.json ends up at score=0
    while report.md shows the correct score (issue #71).

    Call this immediately after ``score_results_async`` returns. It walks the
    rescored results and uses ``tracker.update_task`` to overwrite the stored
    ``score`` and the ``eval`` JSON blob with the Vakra verdict.

    Returns the number of tracker entries patched (useful for logging/tests).
    """
    if tracker is None or not getattr(tracker, "experiment_folder", None):
        return 0
    tracker_tasks = getattr(tracker, "tasks", None)
    if not isinstance(tracker_tasks, dict):
        return 0

    patched = 0
    for r in results:
        task_id = _result_uuid(r)
        if not task_id or task_id not in tracker_tasks:
            continue
        score = float(r.get("match_rate", 0.0))
        new_eval = json.dumps(
            {
                "task_name": r.get("task_name", task_id),
                "difficulty": r.get("difficulty", "unknown"),
                "success": bool(r.get("success", False)),
                "match_rate": score,
                "found_keywords": r.get("found_keywords", []),
                "missing_keywords": r.get("missing_keywords", []),
            }
        )
        if tracker.update_task(task_id=task_id, score=score, eval=new_eval):
            patched += 1
    return patched


async def score_results_async(
    results: List[Dict[str, Any]],
    output_dir: Path,
    capability_name: str = CAPABILITY_DEFAULT,
    domain: str = "hockey",
) -> Optional[Dict[str, Any]]:
    """Async variant of :func:`score_results`. Use this when called from inside
    an asyncio event loop (i.e. from any ``async def`` function in eval_m3.py).

    Mode selection (``M3_VAKRA_LIVE_MCP`` env var, default ``auto``):

    - ``on``    — require live-MCP; raise if the capability container can't be
                  reached. Matches Vakra CLI verdicts byte-for-byte.
    - ``auto``  — try live-MCP; on connection failure fall back to offline
                  scoring (uses the tool responses the agent recorded).
    - ``off``   — never connect; always score offline.
    """
    prepared = _prepare_inputs(results, output_dir, domain)
    if prepared is None:
        return None
    work, gt_dir, pred_dir, gt_path, pred_path = prepared

    registry = vakra_evaluator.build_default_capability_registry()
    if capability_name not in registry:
        raise ValueError(f"Capability '{capability_name}' not in Vakra registry: {list(registry)}")
    policy = registry[capability_name]

    mode = (os.getenv("M3_VAKRA_LIVE_MCP") or "auto").strip().lower()
    if mode not in ("on", "auto", "off"):
        raise ValueError(f"M3_VAKRA_LIVE_MCP must be one of on/auto/off (got {mode!r})")

    mcp_config = None
    if mode in ("on", "auto"):
        mcp_config, err = _resolve_mcp_config(capability_name)
        if mcp_config is None:
            msg = f"[vakra] live-MCP config unavailable for {capability_name}: {err}"
            if mode == "on":
                raise RuntimeError(msg + " (set M3_VAKRA_LIVE_MCP=auto or off to bypass)")
            print(f"{msg} — falling back to offline scoring.", file=sys.stderr)

    domain_out = None
    used_mode = "offline"
    if mcp_config is not None:
        try:
            # Pre-flight: agent records registry-prefixed names; the zip's
            # gold_sequence uses long auto-generated operation_ids; the
            # capability container can speak either. Rewrite both predicted
            # AND ground-truth tool names to the actual live MCP names so
            # Vakra's replay finds every tool.
            try:
                pred_n, gt_n, pred_unmapped, gt_unmapped = await _rewrite_tool_names_for_live_mcp(
                    pred_path, gt_path, mcp_config, domain
                )
                if pred_n or gt_n:
                    print(
                        f"[vakra] rewrote tool names to match live MCP for "
                        f"{capability_name}/{domain} (pred={pred_n}, gt={gt_n})",
                        file=sys.stderr,
                    )
                if pred_unmapped or gt_unmapped:
                    print(
                        f"[vakra] WARNING: {len(pred_unmapped)} predicted and "
                        f"{len(gt_unmapped)} ground-truth tool name(s) had no "
                        f"live MCP match and will be replayed verbatim "
                        f"(likely to error). pred sample: {pred_unmapped[:3]}; "
                        f"gt sample: {gt_unmapped[:3]}",
                        file=sys.stderr,
                    )
            except Exception as rewrite_err:  # noqa: BLE001
                # Treat as a connection failure — drop into the broad fallback.
                raise RuntimeError(
                    f"tool-name rewrite pre-flight failed: {type(rewrite_err).__name__}: {rewrite_err}"
                ) from rewrite_err

            print(
                f"[vakra] live-MCP scoring against {capability_name} / {domain}",
                file=sys.stderr,
            )
            domain_out, _ = await vakra_evaluator.evaluate_domain(
                domain=domain,
                gt_path=gt_path,
                pred_path=pred_path,
                policy=policy,
                mcp_config=mcp_config,
                capability_name=capability_name,
            )
            used_mode = "live-mcp"
        except Exception as e:  # noqa: BLE001 — broad fallback on any MCP/exec failure
            if mode == "on":
                raise
            print(
                f"[vakra] live-MCP failed ({type(e).__name__}: {e}); falling back to offline scoring.",
                file=sys.stderr,
            )
            domain_out = None  # force the offline path below

    if domain_out is None:
        print(
            f"[vakra] offline scoring for {capability_name} / {domain} "
            "(judges see the agent's recorded tool_responses)",
            file=sys.stderr,
        )
        domain_out, _ = await vakra_evaluator.evaluate_domain(
            domain=domain,
            gt_path=gt_path,
            pred_path=pred_path,
            policy=policy,
            mcp_config=None,
            capability_name=capability_name,
        )

    summary = _annotate_and_summarize(results, domain, domain_out, work, gt_dir, pred_dir, capability_name)
    if summary is not None:
        summary["_scoring_mode"] = used_mode
        # Stash the mode on each annotated result so the summary printer can
        # surface it without needing access to the summary object.
        for r in results:
            if "vakra" in r:
                r["vakra"]["_scoring_mode"] = used_mode
    return summary


def score_results(
    results: List[Dict[str, Any]],
    output_dir: Path,
    capability_name: str = CAPABILITY_DEFAULT,
    domain: str = "hockey",
) -> Optional[Dict[str, Any]]:
    """Sync entry point. Call only from non-async code; for async callers use
    :func:`score_results_async`. Raises ``RuntimeError`` if invoked while an
    asyncio event loop is already running (rather than letting asyncio.run blow
    up deeper inside the evaluator)."""
    try:
        asyncio.get_running_loop()
        raise RuntimeError(
            "score_results was called while an asyncio loop is running. "
            "Use `await score_results_async(...)` instead."
        )
    except RuntimeError as e:
        # get_running_loop() raises RuntimeError when no loop is running, which
        # is the path we want; only re-raise if it's our explicit guard above.
        if "asyncio loop is running" in str(e):
            raise
    return asyncio.run(
        score_results_async(
            results,
            output_dir=output_dir,
            capability_name=capability_name,
            domain=domain,
        )
    )


_JUDGE_KEYS = ("exactmatch", "answer", "groundedness")


def _judge_lines(turn: Dict[str, Any], indent: str = "      ") -> List[str]:
    """One line per judge with score + explanation. Used for failure detail."""
    meta = turn.get("metadata") or {}
    expl = meta.get("score_explanation") or {}
    lines: List[str] = []
    for key in _JUDGE_KEYS:
        score_key = "exactmatch_score" if key == "exactmatch" else f"{key}_score"
        score = meta.get(score_key)
        if score is None:
            continue  # judge skipped (e.g. answer judge skipped when exactmatch=1)
        msg = expl.get(key)
        if msg is None:
            msg = "(no explanation)"
        msg = str(msg).strip().replace("\n", " ")
        if len(msg) > 280:
            msg = msg[:277] + "..."
        mark = "✓" if score == 1.0 else "✗"
        lines.append(f"{indent}{mark} {key:<13} score={score}  {msg}")
    if not lines:
        lines.append(f"{indent}(no per-judge breakdown — see _vakra/results.json)")
    return lines


def _count_actual_tool_calls(result: Dict[str, Any]) -> int:
    """Count tool calls in an agent result. Falls back across known shapes."""
    actual = result.get("actual_tool_call_count")
    if isinstance(actual, int):
        return actual
    total = 0
    if isinstance(result.get("tool_calls"), list):
        total += len(result["tool_calls"])
    for turn in result.get("all_responses") or []:
        if isinstance(turn, dict) and isinstance(turn.get("tool_calls"), list):
            total += len(turn["tool_calls"])
    return total


def print_vakra_summary(results: List[Dict[str, Any]]) -> None:
    """Print a unified evaluation summary driven by the Vakra LLM judges.

    Pass/fail comes from the dialogue ``score`` (>=1.0 = pass). Each task line
    shows the tool-call count (expected→actual when known, else just actual).
    Failing tasks expand into per-turn judge detail with explanations so the
    user can see exactly which step failed and why.
    """
    scored = [r for r in results if "vakra" in r]
    if not scored:
        return
    scores = [float(r.get("match_rate", 0.0)) for r in scored]
    n = len(scores)
    mean_s = sum(scores) / n
    min_s = min(scores)
    max_s = max(scores)
    num_correct = sum(1 for s in scores if s >= 1.0)

    # Use sys.__stdout__ so the output isn't swallowed by stdout redirection in
    # eval_m3.py's _emit_cleanly path (loguru/stderr races otherwise).
    out = sys.__stdout__
    write = out.write if out is not None else (lambda s: print(s, end=""))

    # Surface the scoring mode (live-mcp / offline). When mixed across results
    # (rare), label it as "mixed" so the user knows to check per-task data.
    modes = {(r.get("vakra") or {}).get("_scoring_mode", "offline") for r in scored}
    mode_label = next(iter(modes)) if len(modes) == 1 else "mixed"

    write("\n")
    write("=" * 80 + "\n")
    write("EVALUATION COMPLETE — Vakra LLM judges (correctness × groundedness × exact-match)\n")
    write("=" * 80 + "\n")
    write(f"Scoring mode:          {mode_label}\n")
    write(f"Scored samples:        {n}\n")
    write(f"Pass / total:          {num_correct} / {n}  ({(num_correct / n) * 100:.1f}%)\n")
    write(f"Mean dialogue score:   {mean_s:.4f}\n")
    write(f"Min  dialogue score:   {min_s:.4f}\n")
    write(f"Max  dialogue score:   {max_s:.4f}\n")

    write("\nPer-task results:\n")
    for r in scored:
        uuid = _result_uuid(r) or "?"
        score = float(r.get("match_rate", 0.0))
        passed = score >= 1.0
        mark = "✓" if passed else "✗"
        actual_tcs = _count_actual_tool_calls(r)
        expected_tcs = r.get("expected_tool_call_count")
        if isinstance(expected_tcs, int):
            tc_str = f"tool_calls={actual_tcs}/{expected_tcs}"
        else:
            tc_str = f"tool_calls={actual_tcs}"
        write(f"  {mark} {uuid:<30}  score={score:.2f}  {tc_str}\n")
        if not passed:
            details = (r.get("vakra") or {}).get("details") or {}
            per_turn = details.get("per_turn") or []
            if per_turn:
                for t in per_turn:
                    turn_id = t.get("turn_id", "?")
                    turn_score = t.get("score")
                    pred_answer = (t.get("pred_answer") or "").strip()
                    if len(pred_answer) > 200:
                        pred_answer = pred_answer[:197] + "..."
                    write(f"    turn {turn_id} score={turn_score} pred=\"{pred_answer}\"\n")
                    for line in _judge_lines(t):
                        write(line + "\n")
            else:
                write("    (Vakra produced no per-turn detail; see _vakra/results.json)\n")

    # Pointer to the on-disk artifact so the user can drill in
    results_path = (scored[0].get("vakra") or {}).get("_results_path")
    if results_path:
        write(f"\nFull judge details: {results_path}\n")
    else:
        write("\nFull judge details: <results_dir>/_vakra/results.json\n")
    write("=" * 80 + "\n")
    if hasattr(out, "flush"):
        try:
            out.flush()
        except Exception:  # noqa: S110 — flush is best-effort cleanup
            pass
