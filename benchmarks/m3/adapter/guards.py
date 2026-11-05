"""Post-invoke answer pipeline (ported from ``CugaCleanAgent.run`` + ``CugaV2Agent``).

Everything here needs run evidence (the recorded tool calls) or a follow-up
LLM/agent call, so it cannot live in the pure ``final_answer`` function. The
order is EXACTLY the validated adapter's:

    gates retry (same thread) -> strip -> refusal_norm -> evidence_gate ->
    support_check -> self_verify -> cap2 value extraction -> normalize ->
    bluff_map

Each step is preset-gated; with everything off the pipeline returns the
stripped answer unchanged.
"""

from __future__ import annotations

import re
from typing import Awaitable, Callable, List, Optional

from loguru import logger

from benchmarks.m3.adapter.config import AdapterConfig, TaskContext
from benchmarks.m3.adapter.final_answer import (
    REFUSAL,
    canonicalize_final_answer,
    extract_values_answer,
    is_giveup,
    looks_like_failure,
    normalize_answer,
    strip_channel_tokens,
)

_HEDGE_RE = re.compile(
    r"\bhowever\b|\bbut note\b|\bapproximately\b|\bnot (?:entirely )?sure\b|"
    r"\bmight be\b|\buncertain\b|\bplease note\b",
    re.IGNORECASE,
)

# Answer-token support check ignores these leading sentence words (cuga_v2_agent).
_STOPWORDS = {
    "The",
    "This",
    "That",
    "These",
    "Those",
    "Here",
    "There",
    "Based",
    "According",
    "Answer",
    "Note",
    "However",
    "Additionally",
    "Overall",
}

_SELF_VERIFY_PROMPT = (
    "Documents:\n{chunks}\n\nDraft answer:\n{answer}\n\n"
    "Task: for EACH factual claim in the draft answer, find one exact "
    "quote from the documents that directly supports it. If every claim "
    "has a supporting quote, reply with exactly: SUPPORTED. If any claim "
    "has no supporting quote in the documents, reply with exactly: UNSUPPORTED."
)


def simple_gate_correction(final_text: str) -> Optional[str]:
    """Non-LLM answer gates: empty answer and hedged answers."""
    text = (final_text or "").strip()
    if not text:
        return (
            "You have not provided a final answer. Using the tool results above, "
            "state the final answer now — the bare value(s) or the COMPLETE list. "
            "If a needed value is missing, call the appropriate tool first."
        )
    if _HEDGE_RE.search(text):
        return (
            "Restate the final answer exactly once: the bare value(s) or the COMPLETE "
            "list — no qualifications, no commentary, no markdown."
        )
    return None


def _successful_calls(recorded_calls: List[dict]) -> List[dict]:
    return [c for c in recorded_calls if not str(c.get("result", "")).startswith("Error:")]


def _retriever_evidence(recorded_calls: List[dict]) -> str:
    return " ".join(str(c.get("result", "")) for c in _successful_calls(recorded_calls))


async def run_answer_pipeline(
    invoke_round: Callable[[str], Awaitable],
    first_result,
    cfg: AdapterConfig,
    ctx: TaskContext,
    recorded_calls: List[dict],
    llm_ainvoke: Optional[Callable[[str], Awaitable[str]]] = None,
    *,
    final_answer_installed: bool = True,
) -> str:
    """Apply the validated answer pipeline; returns the final answer string.

    ``invoke_round(correction_text)`` must continue the SAME thread (the CUGA
    checkpointer appends the follow-up) and return an InvokeResult-shaped
    object. ``recorded_calls`` is the live sink shared with the recording
    provider — it accumulates across retry rounds within this task.
    """
    result = first_result

    # 1. Answer-gate retry loop (VAKRA_CUGA_GATES): on an empty/hedged draft,
    # send a correction and continue the same thread.
    if cfg.gates:
        for _ in range(cfg.max_gate_rounds):
            draft = strip_channel_tokens(str(getattr(result, "answer", "") or ""))
            correction = simple_gate_correction(draft)
            if correction is None:
                break
            logger.info("[m3-adapter gate] retrying with correction (same thread)")
            follow_up = await invoke_round(correction)
            if getattr(follow_up, "error", None):
                logger.warning("[m3-adapter gate] retry errored; keeping the pre-retry draft")
                break
            result = follow_up

    answer = getattr(result, "answer", "")
    if not isinstance(answer, str):
        answer = str(answer or "")
    answer = strip_channel_tokens(answer)

    # Fallback for agents built without the in-graph final_answer function
    # (e.g. a pre-built agent wrapped after construction): apply the same
    # canonicalization here, at the equivalent point in the pipeline.
    if not final_answer_installed and cfg.canonicalize:
        answer = canonicalize_final_answer(answer)

    # 2. Refusal normalization (VAKRA_CUGA_REFUSAL_NORM).
    if cfg.refusal_norm and is_giveup(answer):
        answer = REFUSAL

    # 3. Evidence gate (VAKRA_V2_EVIDENCE_GATE): no factual answer without at
    # least one successful tool call.
    if cfg.evidence_gate and answer.strip() and not is_giveup(answer):
        if not _successful_calls(recorded_calls):
            logger.info("[m3-adapter evidence-gate] factual answer with 0 successful tool calls -> refusal")
            answer = REFUSAL

    # 4-5. Retriever-scope grounding guards (VAKRA_V2_SUPPORT_CHECK / SELF_VERIFY),
    # applied only when the policy scoped the task to document retrievers.
    if ctx.last_scope == "retriever_only" and answer.strip() and not is_giveup(answer):
        if cfg.support_check:
            evidence = _retriever_evidence(recorded_calls).lower().replace(",", "")
            nums = re.findall(r"\d[\d,.]*\d|\d", answer)
            ents = re.findall(r"\b[A-Z][a-zA-Z'’\-]+(?:\s+[A-Z][a-zA-Z'’\-]+)*", answer)
            tokens = {t.strip(".,;:") for t in nums + ents}
            tokens = {t for t in tokens if len(t) > 2 and t not in _STOPWORDS}
            if tokens:
                supported = sum(1 for t in tokens if t.lower().replace(",", "") in evidence)
                ratio = supported / len(tokens)
                if ratio < 0.5:
                    logger.info(
                        "[m3-adapter support-check] only {}/{} answer tokens found in evidence -> refusal",
                        supported,
                        len(tokens),
                    )
                    answer = REFUSAL
        if cfg.self_verify and answer != REFUSAL and llm_ainvoke is not None:
            chunks = _retriever_evidence(recorded_calls)[:24000]
            if chunks.strip():
                try:
                    verdict = (
                        (await llm_ainvoke(_SELF_VERIFY_PROMPT.format(chunks=chunks, answer=answer[:4000])))
                        .strip()
                        .upper()
                    )
                    if "UNSUPPORTED" in verdict:
                        logger.info("[m3-adapter self-verify] unsupported claims -> refusal")
                        answer = REFUSAL
                except Exception as exc:  # noqa: BLE001  (verifier is best-effort)
                    logger.warning("[m3-adapter self-verify] failed ({}); keeping draft answer", exc)

    # 6. cap2 verbatim value extraction (VAKRA_CUGA_CAP2_VERBATIM).
    if cfg.cap2_verbatim and cfg.capability == 2:
        answer = extract_values_answer(answer)

    # 7. Deterministic normalization (VAKRA_CUGA_NORMALIZE).
    if cfg.normalize:
        answer = normalize_answer(answer)

    # 8. Bluff map (VAKRA_CUGA_BLUFF_MAP): failure-looking AND unsupported -> refusal.
    if cfg.bluff_map and looks_like_failure(answer):
        if not _successful_calls(recorded_calls):
            logger.info("[m3-adapter bluff-map] unsupported failure-looking answer -> refusal")
            answer = REFUSAL

    return answer
