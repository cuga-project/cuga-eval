"""Post-invoke answer pipeline (ported from ``CugaCleanAgent.run`` + ``CugaV2Agent``).

Everything here needs run evidence (the recorded tool calls) or a follow-up
LLM/agent call, so it cannot live in the pure ``final_answer`` function. The
order is EXACTLY the validated adapter's:

    gates retry (same thread) -> strip -> refusal_norm -> evidence_gate ->
    support_check -> self_verify -> cap2 value extraction -> normalize ->
    bluff_map

Beyond the campaign's submitted configs, three opt-in steps run right after the
gate retries: require-tool (the campaign's VAKRA_CUGA_REQUIRE_TOOL, its soft2
mechanism), refusal recovery, and an LLM fact-check of the draft against the
recorded tool results.

Each step is preset-gated; with everything off the pipeline returns the
stripped answer unchanged.
"""

from __future__ import annotations

import json
import re
from typing import Awaitable, Callable, List, Optional, Tuple

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


#: VAKRA_CUGA_REQUIRE_TOOL's correction, verbatim (vakra-main agents/cuga_clean_agent.py).
REQUIRE_TOOL_CORRECTION = (
    "Your previous answer used no tool results, so it is not grounded in real data. "
    "You MUST call at least one relevant tool to obtain the actual value, then give the "
    "final answer based strictly on that tool's output. Call the appropriate tool now."
)

REFUSAL_RECOVERY_CORRECTION = (
    "The tools you called already returned data relevant to the question. Re-read those tool "
    "results and extract the requested value from them, then give the final answer. Only if "
    "they truly do not contain it, call the tool that would return it before answering."
)

_FACT_CHECK_PROMPT = (
    "You are checking an agent's final answer against the tool results it obtained.\n\n"
    "Question:\n{question}\n\nTool calls and their results, in order:\n{calls}\n\n"
    "Draft answer:\n{answer}\n\n"
    "Reply with exactly one line:\n"
    "OK — if the draft answer is supported by the tool results and answers the question.\n"
    "CORRECTED: <answer> — if the tool results contain the right answer but the draft states it "
    "wrongly (wrong value or item, incomplete list, extra or missing elements). Use only values "
    "that appear in the tool results; give the bare value(s), no explanation.\n"
    "MISSING: <what is still needed> — if the tool results do not contain what the question asks."
)
FACT_CHECK_RETRY = (
    "Your answer is not supported by the tool results yet: {need} Call the tool(s) needed to "
    "obtain it, then give the final answer based strictly on their output."
)
FACT_CHECK_MAX_CALLS = 20  # the judge reads the last 20 tool responses; so does the checker
FACT_CHECK_RESULT_CHARS = 1500


_DISTILL_PROMPT = """You turn an assistant's draft answer into the final answer to the user's question.

Question: {question}

Tool results the assistant obtained:
{calls}

Draft answer:
{answer}

Write ONLY the answer: the value or values the question asks for, copied exactly as the tool results show
them (same spelling, full precision, every requested item, in the order the tools returned them). No
explanation, no restating the question, no units or labels unless the question asks for them. If the
question asks for several things, give all of them, separated by commas. If the draft's value does not
appear in the tool results, keep the draft's value. Reply with the answer only."""


def format_tool_evidence(recorded_calls: List[dict]) -> str:
    """The recorded calls as numbered ``tool(args) -> result`` lines (last 20, results truncated)."""
    lines = []
    for i, c in enumerate(recorded_calls[-FACT_CHECK_MAX_CALLS:], start=1):
        args = json.dumps(c.get("arguments") or {}, ensure_ascii=False, default=str)[:300]
        result = str(c.get("result", ""))[:FACT_CHECK_RESULT_CHARS]
        lines.append(f"{i}. {c.get('tool_name')}({args}) -> {result}")
    return "\n".join(lines)


def parse_fact_check(verdict: str) -> Tuple[str, str]:
    """``("OK"|"CORRECTED"|"MISSING", payload)``; anything unparseable counts as OK."""
    for line in (verdict or "").strip().splitlines():
        line = line.strip().strip("*`").strip()
        if not line:
            continue
        head, _, rest = line.partition(":")
        key = head.strip().strip("*`").strip().upper()
        payload = rest.strip().strip("*`").strip()  # tolerate markdown bold around the label
        if key in ("CORRECTED", "MISSING") and payload:
            return key, payload
        return "OK", ""
    return "OK", ""


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
    question: str = "",
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

    def draft_of(res) -> str:
        return strip_channel_tokens(str(getattr(res, "answer", "") or ""))

    async def retry(correction: str, tag: str):
        logger.info("[m3-adapter {}] retrying with correction (same thread)", tag)
        follow_up = await invoke_round(correction)
        if getattr(follow_up, "error", None):
            logger.warning("[m3-adapter {}] retry errored; keeping the pre-retry draft", tag)
            return None
        return follow_up

    # 1b. Ground-before-answer (VAKRA_CUGA_REQUIRE_TOOL): a draft backed by ZERO successful
    # tool calls is re-asked to call a tool. Like the campaign, a give-up is left alone —
    # unless retry_unattempted_refusal and no tool was even tried.
    for _ in range(cfg.require_tool_rounds):
        draft = draft_of(result)
        if not draft.strip() or _successful_calls(recorded_calls):
            break
        if is_giveup(draft) and not (cfg.retry_unattempted_refusal and not recorded_calls):
            break
        follow_up = await retry(REQUIRE_TOOL_CORRECTION, "require-tool")
        if follow_up is None:
            break
        result = follow_up

    # 1c. Refusal recovery: a give-up although tools returned data.
    for _ in range(cfg.refusal_recovery_rounds):
        if not is_giveup(draft_of(result)) or not _successful_calls(recorded_calls):
            break
        follow_up = await retry(REFUSAL_RECOVERY_CORRECTION, "refusal-recovery")
        if follow_up is None:
            break
        result = follow_up

    answer = draft_of(result)

    # 1d. Fact-check: one LLM pass over the recorded tool results. CORRECTED replaces the draft
    # (values from the tool results only); MISSING re-asks once in verify_and_retry mode.
    if cfg.fact_check != "off" and llm_ainvoke is not None:
        if answer.strip() and not is_giveup(answer) and _successful_calls(recorded_calls):
            prompt = _FACT_CHECK_PROMPT.format(
                question=question or "(see the tool calls)",
                calls=format_tool_evidence(recorded_calls),
                answer=answer[:4000],
            )
            try:
                kind, payload = parse_fact_check(await llm_ainvoke(prompt))
            except Exception as exc:  # noqa: BLE001  (the checker is best-effort)
                logger.warning("[m3-adapter fact-check] failed ({}); keeping the draft", exc)
                kind, payload = "OK", ""
            logger.info("[m3-adapter fact-check] {}{}", kind, f": {payload[:120]}" if payload else "")
            if kind == "CORRECTED":
                answer = canonicalize_final_answer(payload) if cfg.canonicalize else payload
            elif kind == "MISSING" and cfg.fact_check == "verify_and_retry":
                follow_up = await retry(FACT_CHECK_RETRY.format(need=payload), "fact-check")
                if follow_up is not None:
                    result = follow_up
                    answer = draft_of(result)

    # 1e. Answer distillation: the draft rewritten as only the requested value(s), copied from the
    # tool results. Refusals, empty drafts and drafts without tool evidence are left alone.
    if cfg.answer_distill and llm_ainvoke is not None:
        if answer.strip() and not is_giveup(answer) and _successful_calls(recorded_calls):
            prompt = _DISTILL_PROMPT.format(
                question=question or "(see the tool calls)",
                calls=format_tool_evidence(recorded_calls),
                answer=answer[:4000],
            )
            try:
                distilled = strip_channel_tokens(str(await llm_ainvoke(prompt) or "")).strip()
            except Exception as exc:  # noqa: BLE001  (best-effort; never lose the draft)
                logger.warning("[m3-adapter distill] failed ({}); keeping the draft", exc)
                distilled = ""
            if distilled and not is_giveup(distilled):
                logger.info("[m3-adapter distill] {!r} -> {!r}", answer[:80], distilled[:80])
                answer = distilled

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
