"""Bridge to vendor/vakra's evaluator, with cuga-eval-specific overrides layered on
top via monkeypatching — not a byte-for-byte fork of vendor's files.

Background (issue linked from PR #175... see there for full context): this module
used to be a full local copy of vendor/vakra/evaluator/evaluator.py (plus sibling
copies of judge.py, scorer.py, constant.py, mcp_tools.py, prompt.py, utils.py) that
had quietly drifted from upstream. Comparing every file against a freshly-pulled
vendor/vakra (which had just merged IBM/vakra PR #23,
"evaluator-internal-parity-updates") showed most of the local fork's drift was
already absorbed upstream — vendor now natively supports `policy_judge_path`
end-to-end, an "unanswerable, no tool calls" scoring special-case, and a Groq/RITS
judge-backend selector. Four real, load-bearing local differences remained:

1. **Judge LLM backend.** Vendor's `LLMJudge._build_llm()` supports `groq`/`rits`
   only. `_patched_build_llm()` adds a `litellm`/`azure` branch that redirects to
   this org's existing LiteLLM proxy (`OPENAI_BASE_URL`/`OPENAI_API_KEY`), falling
   through to vendor's original implementation for every other backend name. This is
   a single monkeypatch on `LLMJudge` (the common base of `GroundednessJudge`,
   `CorrectnessJudge`, `ExactMatchJudge` — none of which override `_build_llm`
   themselves), not a full rebuild of the backend selector.
2. **`CorrectnessJudge._find_first_json_object` is missing `self`.** A real bug in
   vendor's current code (defined without `self`, called as `self._find_...()`) —
   raises `TypeError` whenever a judge's raw output isn't directly valid JSON.
   Fixed by rewrapping it as a `staticmethod`, matching its actual definition.
3. **`DialogueScorer` silently substitutes the wrong predicted turn.** Vendor's
   `score()` falls back to the *last* predicted turn when a `turn_id` lookup
   misses, instead of recording a failure. `_PatchedDialogueScorer` records an
   explicit `missing predicted turn_id=...` failure instead.
4. **Missing predictions.** Vendor's `evaluate_domain` computes
   `missing_prediction_uuids` (GT samples with no matching prediction) but never
   scores or records them in `dialogues`/`summary` — they just vanish from the
   aggregate. `evaluate_domain` below wraps vendor's version and backfills a
   zero-score entry per missing prediction instead.

Policy-adherence scoring itself needs zero local code now — `evaluate_domain`'s
`policy_judge_path` param is threaded through by vendor already. This module
defaults it to `policy_judge.py` in this directory when present (untracked,
proprietary, expected to exist only in checkouts that have access to it) so
callers don't need their own path-detection logic; passing an explicit
`policy_judge_path` still overrides the default.

If `vendor/vakra` isn't present at all, this raises a clear, actionable error at
import time instead of a bare `ImportError` two frames down inside vendor's own
files — run ``./setup_m3.sh`` to clone it.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_THIS_DIR = Path(__file__).resolve().parent
_VENDOR_ROOT = Path(__file__).resolve().parents[3] / "vendor" / "vakra"
_VENDOR_EVALUATOR_DIR = _VENDOR_ROOT / "evaluator"

if not _VENDOR_EVALUATOR_DIR.is_dir():
    raise ImportError(
        f"vendor/vakra not found at {_VENDOR_ROOT} — the M3 Vakra evaluator is loaded "
        "directly from the vendored upstream checkout, not a local copy. Run "
        "./setup_m3.sh to clone it, then retry."
    )

# vendor/vakra/evaluator's own modules (judge.py, scorer.py, constant.py, mcp_tools.py,
# prompt.py, utils.py) use bare sibling imports (`from judge import ...`), and
# evaluator.py additionally does `from benchmark.mcp_client import ...` — so both
# vendor/vakra/evaluator and vendor/vakra itself need to be on sys.path. Appended
# (not inserted at 0) so this directory's own files — this bridge, and
# policy_judge.py — are always found first if a name ever collides.
for _p in (str(_VENDOR_EVALUATOR_DIR), str(_VENDOR_ROOT)):
    if _p not in sys.path:
        sys.path.append(_p)

# judge.py must be imported and patched *before* vendor's evaluator.py is loaded:
# evaluator.py's `CapabilityPolicy` dataclass has field defaults that construct
# real judge instances at class-definition time (`correctness_judge: Any =
# CorrectnessJudge(config={})`), i.e. at import time, not lazily. Patching
# `_build_llm` afterward would be too late — the eager defaults would already have
# tried (and, with no JUDGE_BACKEND set, failed) to build a RITS/Groq client.
import judge as _vendor_judge  # noqa: E402 — resolves to vendor/vakra/evaluator/judge.py
from langchain_openai import ChatOpenAI

# ---------------------------------------------------------------------------
# 1. Judge LLM backend redirect
# ---------------------------------------------------------------------------


class _LiteLLMChatModel(ChatOpenAI):
    """Azure/gpt-4.1 (or whatever JUDGE_MODEL_NAME names) served through this org's
    LiteLLM proxy. Reads the same env the agent's gpt4.1 profile uses
    (OPENAI_BASE_URL + OPENAI_API_KEY); override the model with JUDGE_MODEL_NAME."""

    def __init__(self, config: dict):
        model_name = config.get("model_name") or os.environ.get("JUDGE_MODEL_NAME", "gpt-4.1")
        base_url = (
            config.get("end_point") or os.environ.get("JUDGE_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
        )
        api_key = os.environ.get("JUDGE_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not base_url or not api_key:
            raise ValueError(
                "OPENAI_BASE_URL/OPENAI_API_KEY (or JUDGE_BASE_URL/JUDGE_API_KEY) must be "
                "set to use JUDGE_BACKEND=litellm."
            )
        params = config.get("params", {})
        cfg = {"model": model_name, "api_key": api_key, "base_url": base_url.rstrip("/"), "temperature": 0}
        cfg.update(params)
        super().__init__(**cfg)


_vendor_build_llm = _vendor_judge.LLMJudge._build_llm


def _patched_build_llm(self, config: dict) -> ChatOpenAI:
    # Defaults to litellm (this org's actual setup) rather than falling through to
    # vendor's own rits/groq default, since neither Groq (discontinued) nor RITS
    # credentials are assumed to be available here.
    backend = (
        config.get("backend") or config.get("provider") or os.environ.get("JUDGE_BACKEND") or "litellm"
    ).lower()
    if backend in ("litellm", "azure"):
        return _LiteLLMChatModel(config)
    return _vendor_build_llm(self, config)


# GroundednessJudge/CorrectnessJudge/ExactMatchJudge all inherit _build_llm from
# LLMJudge without overriding it, so patching the base class covers all three.
_vendor_judge.LLMJudge._build_llm = _patched_build_llm


# ---------------------------------------------------------------------------
# 2. CorrectnessJudge._find_first_json_object is missing `self`
# ---------------------------------------------------------------------------
# Defined as `def _find_first_json_object(text: str)` but called as
# `self._find_first_json_object(text)` — vendor's fallback path for judge output
# that isn't directly valid JSON (a real, non-rare case) raises TypeError: takes 1
# positional argument but 2 were given. Rewrapping as a staticmethod fixes the
# call convention without touching vendor's file or reimplementing the function.
_vendor_judge.CorrectnessJudge._find_first_json_object = staticmethod(
    _vendor_judge.CorrectnessJudge._find_first_json_object
)


# Loaded under a private module name (not "evaluator") so it can't collide with, or
# accidentally re-import, this file itself. Loaded *after* the judge.py patches
# above so CapabilityPolicy's eager judge-construction defaults pick them up.
_spec = importlib.util.spec_from_file_location(
    "_vendor_vakra_evaluator", _VENDOR_EVALUATOR_DIR / "evaluator.py"
)
_vendor = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _vendor
_spec.loader.exec_module(_vendor)


# ---------------------------------------------------------------------------
# 3. DialogueScorer silently substitutes the wrong predicted turn
# ---------------------------------------------------------------------------
# `DialogueScorer.score()` looks up the predicted turn matching the GT turn_id via
# `pred_by_id.get(turn_id, pred_turns[-1])` — if the id isn't found, it silently
# scores against whatever the *last* predicted turn happens to be instead of
# recording a failure. `_PatchedDialogueScorer.score()` is a full override (the
# method is short and entirely self-contained — for M3, `gt_turns[-1]` means only
# one turn is ever scored per call) that records an explicit
# `missing predicted turn_id=...` failure instead.
import scorer as _vendor_scorer  # noqa: E402 — resolves to vendor/vakra/evaluator/scorer.py


class _PatchedDialogueScorer(_vendor_scorer.DialogueScorer):
    def score(
        self,
        gt_dialogue: Dict[str, Any],
        pred_dialogue: Dict[str, Any],
        gt_key: str = "output",
        pred_key: str = "output",
    ) -> Tuple[float, Dict[str, Any]]:
        gt_turns = list(gt_dialogue.get(gt_key, []))
        pred_turns = list(pred_dialogue.get(pred_key, []))
        additional_instructions = gt_dialogue.get("additional_instructions", "")

        assert len(pred_turns) == 1, f"Predicted Turns {len(pred_turns)} should have been 1."  # noqa: S101

        pred_by_id = {t.get(_vendor_scorer.PRED_OUTPUT_TURN_ID_KEY): t for t in pred_turns if "turn_id" in t}

        per_turn: List[Dict[str, Any]] = []
        turn_scores: List[float] = []

        for gt_turn in [gt_turns[-1]]:
            turn_id = gt_turn.get(_vendor_scorer.GT_OUTPUT_TURN_ID_KEY)
            query = str(gt_turn.get(_vendor_scorer.GT_OUTPUT_QUERY_KEY))

            pred_turn = pred_by_id.get(turn_id)
            if pred_turn is None:
                per_turn.append(
                    {
                        "turn_id": turn_id,
                        "query": query,
                        "pred_answer": "",
                        "score": 0.0,
                        "metadata": {"error": f"missing predicted turn_id={turn_id}"},
                    }
                )
                turn_scores.append(0.0)
                continue

            gt_answer = self._stringify_answer(gt_turn.get(_vendor_scorer.GT_OUTPUT_ANSWER_KEY))
            gt_calls = gt_turn.get(_vendor_scorer.GT_OUTPUT_SEQUENCE_KEY, {}).get("tool_call", [])
            gt_responses = self._extract_tool_responses(
                gt_turn.get(_vendor_scorer.GT_OUTPUT_SEQUENCE_KEY, {}).get("tool_response", [])
            )
            pred_answer = self._stringify_pred_answer(
                pred_turn.get(_vendor_scorer.PRED_OUTPUT_ANSWER_KEY, "")
            )
            pred_sequence = pred_turn.get(_vendor_scorer.PRED_OUTPUT_SEQUENCE_KEY, {}) or {}
            pred_calls_all = pred_sequence.get("tool_call", []) or []
            pred_calls = (
                pred_calls_all[-_vendor_scorer.N_TOOL_CALLS_PER_TURN :]
                if isinstance(pred_calls_all, list)
                else []
            )
            pred_responses = self._extract_tool_responses(pred_sequence.get("tool_response", []))[
                -_vendor_scorer.N_TOOL_CALLS_PER_TURN :
            ]

            score, details = self.turn_scorer.compare(
                query=query,
                gt_answer=gt_answer,
                pred_answer=pred_answer,
                additional_instructions=additional_instructions,
                gt=gt_calls,
                pred=pred_calls,
                gt_responses=gt_responses,
                pred_responses=pred_responses,
            )
            per_turn.append(
                {
                    "turn_id": turn_id,
                    "query": query,
                    "pred_answer": pred_answer,
                    "score": score,
                    "metadata": details,
                }
            )
            turn_scores.append(float(score))

        dialogue_score = self._aggregate(turn_scores)
        details = {
            "dialogue_score": dialogue_score,
            "num_turns": len(gt_turns),
            "per_turn": per_turn,
            "aggregate": self.cfg.aggregate,
        }
        return dialogue_score, details


# `evaluate_domain` constructs `DialogueScorer(...)` by name, resolved from
# vendor's own module globals at call time — patching the attribute here is enough.
_vendor.DialogueScorer = _PatchedDialogueScorer


# ---------------------------------------------------------------------------
# 4. Missing predictions
# ---------------------------------------------------------------------------


def _make_missing_dialogue_entry(uuid: str, capability_name: str, domain: str, policy: Any) -> Dict[str, Any]:
    return {
        "uuid": uuid,
        "score": 0.0,
        "metadata": {
            "capability": capability_name,
            "domain": domain,
            "policy": {
                "dialogue_aggregate": policy.dialogue_aggregate,
                "execute_mcp_tools": policy.execute_mcp_tools,
            },
            "error": "missing_prediction",
        },
        "details": {
            "dialogue_score": 0.0,
            "num_turns": 0,
            "per_turn": [],
            "aggregate": policy.dialogue_aggregate,
        },
    }


_DEFAULT_POLICY_JUDGE_PATH = _THIS_DIR / "policy_judge.py"
_vendor_evaluate_domain = _vendor.evaluate_domain


async def evaluate_domain(
    domain: str,
    gt_path: Path,
    pred_path: Path,
    policy: Any,
    mcp_config: Optional[Any],
    capability_name: str,
    policy_judge_path: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[float]]:
    if policy_judge_path is None and _DEFAULT_POLICY_JUDGE_PATH.is_file():
        policy_judge_path = str(_DEFAULT_POLICY_JUDGE_PATH)

    domain_out, dialogue_scores = await _vendor_evaluate_domain(
        domain, gt_path, pred_path, policy, mcp_config, capability_name, policy_judge_path
    )
    missing = domain_out.get("missing_prediction_uuids") or []
    if missing:
        zero_dialogues = [
            _make_missing_dialogue_entry(uuid, capability_name, domain, policy) for uuid in missing
        ]
        domain_out["dialogues"] = list(domain_out["dialogues"]) + zero_dialogues
        dialogue_scores = list(dialogue_scores) + [0.0] * len(zero_dialogues)
        domain_scores = [d["score"] for d in domain_out["dialogues"]]
        domain_out["summary"] = {
            "num_samples": domain_out.get("n_groundtruth", len(domain_scores)),
            "num_correct": sum(domain_scores),
            "mean_dialogue_score": (sum(domain_scores) / len(domain_scores)) if domain_scores else 0.0,
            "min_dialogue_score": min(domain_scores) if domain_scores else 0.0,
            "max_dialogue_score": max(domain_scores) if domain_scores else 0.0,
        }
    return domain_out, dialogue_scores


_vendor.evaluate_domain = evaluate_domain


# ---------------------------------------------------------------------------
# Re-exports — everything m3_vakra_score.py (and any test that patches
# `evaluator.<name>`) actually uses.
# ---------------------------------------------------------------------------

CAPABILITY_MCP_TOOL_MAP = _vendor.CAPABILITY_MCP_TOOL_MAP
create_client_and_connect = _vendor.create_client_and_connect
load_mcp_config = _vendor.load_mcp_config
CapabilityPolicy = _vendor.CapabilityPolicy
build_default_capability_registry = _vendor.build_default_capability_registry
evaluate_capability = _vendor.evaluate_capability
