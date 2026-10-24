"""Post-invoke answer pipeline (ported from ``CugaCleanAgent.run`` + ``CugaV2Agent``).

Everything here needs run evidence (the recorded tool calls) or a follow-up
LLM/agent call, so it cannot live in the pure ``final_answer`` function. The
order is EXACTLY the validated adapter's:

    gates retry (same thread) -> strip -> refusal_norm -> evidence_gate ->
    support_check -> self_verify -> cap2 value extraction -> normalize ->
    bluff_map

Beyond the campaign's submitted configs, opt-in steps run right after the gate
retries: require-tool (the campaign's VAKRA_CUGA_REQUIRE_TOOL, its soft2
mechanism), refusal recovery, an LLM fact-check of the draft against the
recorded tool results, and a deterministic values check (a value no tool
returned is re-asked).

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
    strip_demo_layout,
)
from benchmarks.m3.adapter.recording import RESULT_MAX_CHARS

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
COMPOSER_PROMPT = """You write the FINAL ANSWER to a database question from the tool results an agent obtained.
The answer is graded against the expected value(s), so it must contain exactly the requested values.

Rules:
1. Bare value(s) only: no sentence, no explanation, no markdown, no labels.
2. Copy every value EXACTLY as the tool results show it (spelling, case, number format, full precision).
   Never round, re-type from memory, convert units (1.0 stays 1.0, 100 stays 100) or invent a value.
3. A list question: give ALL items of the tool result that answers it, in its order, comma-separated,
   keeping duplicates. Never truncate or write "...".
4. Several things asked: give each requested value, in the order asked, comma-separated.
5. Nothing extra: no ids, names or fields the question did not ask for.
6. If a tool result answers the question, answer it even when other calls failed or returned nothing.
7. Only if no tool result contains the answer, reply exactly: KEEP

Examples (illustrative):
Q: How many orders did customer 17 place in 2015?
Results: 1. get_order_count(customer_id=17, year=2015) -> {{"count": 4}}
Draft: The customer placed 4 orders in 2015.
Final answer: 4

Q: List the names of the stores in Ohio.
Results: 1. get_store_names(state="OH") -> {{"names": ["Akron East", "Dayton", "Toledo North"]}}
Draft: Akron East, Dayton, ...
Final answer: Akron East, Dayton, Toledo North

Q: Which product sold the most, and how many units?
Results: 1. get_top_product() -> {{"product": "Desk Lamp", "units": 1250}}
Draft: Desk Lamp
Final answer: Desk Lamp, 1250

Q: What share of tickets were resolved in March?
Results: 1. get_ticket(id=9) -> {{"rows": []}}  2. get_resolved_share(month="March") -> {{"share": 0.4375}}
Draft: I can not answer.
Final answer: 0.4375

Now the task.
Q: {question}
Results:
{calls}
Draft: {answer}
Final answer:"""


def format_full_evidence(recorded_calls: List[dict], limit: int) -> Optional[str]:
    """The successful calls with their FULL results (last 20); None when one result exceeds ``limit``."""
    lines = []
    for i, c in enumerate(_successful_calls(recorded_calls)[-FACT_CHECK_MAX_CALLS:], start=1):
        full = str(c.get("result_full", c.get("result", "")))
        if len(full) > limit:
            return None
        args = json.dumps(c.get("arguments") or {}, ensure_ascii=False, default=str)[:300]
        lines.append(f"{i}. {c.get('tool_name')}({args}) -> {full}")
    return "\n".join(lines)


def parse_composed(text: str) -> str:
    """The composer's answer: the reply after any 'Final answer:' label, trimmed."""
    t = strip_channel_tokens(str(text or "")).strip()
    m = re.search(r"(?is)final answer\s*:\s*(.+)$", t)
    return (m.group(1) if m else t).strip().strip("`").strip()


FACT_CHECK_RETRY = (
    "Your answer is not supported by the tool results yet: {need} Call the tool(s) needed to "
    "obtain it, then give the final answer based strictly on their output."
)
FACT_CHECK_MAX_CALLS = 20  # the judge reads the last 20 tool responses; so does the checker
FACT_CHECK_RESULT_CHARS = 1500

VALUES_CHECK_CORRECTION = (
    "Your answer states {values}, but no tool result contains {it}. The final answer must use values "
    "exactly as the tools returned them. Call the tool that returns the value the question asks for "
    "(check that its arguments are right), then give the final answer based strictly on its output."
)

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}\b)")
_NAME_RE = re.compile(r"\b[A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+)*")
_DERIVED_OK = {"yes", "no", "true", "false"}


def _norm_evidence(text: str) -> str:
    text = _THOUSANDS_RE.sub("", str(text).lower())
    return re.sub(r"\s+", " ", re.sub(r"[\"'`\[\]{}()\\]", " ", text))


def _number_supported(token: str, evidence_numbers: List[float]) -> bool:
    """``token`` equals, or is a rounding of, a number in the evidence (651.78 for 651.7844...)."""
    decimals = len(token.split(".")[1]) if "." in token else 0
    x, tol = float(token), 0.5 * 10 ** (-decimals) + 1e-12
    return any(abs(x - y) <= tol for y in evidence_numbers)


def unsupported_values(answer: str, evidence: str) -> List[str]:
    """The answer's values found nowhere in ``evidence`` (the question + the tool results).

    Each comma/semicolon/line item of the answer is a value: a number must equal (or round) a number
    in the evidence, a short item must appear in it verbatim (case-insensitive); in a sentence only its
    numbers and capitalized names are checked. Yes/no answers are derived by nature and pass.
    """
    ev = _norm_evidence(evidence)
    ev_numbers = [float(t) for t in _NUM_RE.findall(_THOUSANDS_RE.sub("", str(evidence)))]
    missing: List[str] = []
    for item in re.split(r"[,;\n]", _THOUSANDS_RE.sub("", answer or "")):
        item = item.strip().strip(".*`'\"[](){} ")
        if not item or item.lower() in _DERIVED_OK:
            continue
        if _NUM_RE.fullmatch(item):
            if not _number_supported(item, ev_numbers):
                missing.append(item)
        elif len(item.split()) <= 6:
            if len(item) >= 3 and _norm_evidence(item).strip() not in ev:
                numbers = _NUM_RE.findall(item)  # "44 players": the number carries the value
                if not numbers or not all(_number_supported(n, ev_numbers) for n in numbers):
                    missing.append(item)
        else:
            missing += [n for n in _NUM_RE.findall(item) if not _number_supported(n, ev_numbers)]
            missing += [
                n
                for n in _NAME_RE.findall(item)
                if len(n) > 3 and n not in _STOPWORDS and n.lower() not in ev
            ]
    return list(dict.fromkeys(missing))


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


#: Openings of a draft that is the model's working notes, not an answer (FC ends on any reply without
#: tool calls). Offline on 417 recorded answers: 5 matches, all of them failed answers.
_PLAN_TEXT_RE = re.compile(
    r"^\s*(?:we need|we should|we must|let'?s|i need|i will|i'll|need to|now (?:call|we)|first,? (?:we|i)|to answer)\b",
    re.IGNORECASE,
)
PLAN_TEXT_CORRECTION = (
    "That reply is your working notes, not the final answer. Finish the task: if a value is still missing, "
    "call the tool that returns it now; then reply with only the final answer — the bare value(s) or the "
    "COMPLETE list, no explanation."
)


def looks_like_plan_text(final_text: str) -> bool:
    """The draft opens like reasoning about what to do next ("We need ...", "Let's call ...")."""
    return bool(_PLAN_TEXT_RE.match(final_text or ""))


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
            results = " ".join(str(c.get("result", "")) for c in _successful_calls(recorded_calls))
            if kind == "CORRECTED" and cfg.fact_check_strict and unsupported_values(payload, results):
                logger.info("[m3-adapter fact-check] correction kept out: not in any tool result")
            elif kind == "CORRECTED":
                if cfg.strip_demo_layout:
                    payload = strip_demo_layout(payload)
                answer = canonicalize_final_answer(payload) if cfg.canonicalize else payload
            elif kind == "MISSING" and cfg.fact_check == "verify_and_retry":
                follow_up = await retry(FACT_CHECK_RETRY.format(need=payload), "fact-check")
                if follow_up is not None:
                    result = follow_up
                    answer = draft_of(result)

    # 1d1. Plan-text check, after every re-ask above: a draft that is the model's working notes ("We
    # need ...") is sent back; any re-ask can end that way (FC ends on a reply without tool calls).
    if cfg.plan_text_gate:
        for _ in range(cfg.max_gate_rounds):
            if not looks_like_plan_text(answer):
                break
            follow_up = await retry(PLAN_TEXT_CORRECTION, "plan-text")
            if follow_up is None:
                break
            result, answer = follow_up, draft_of(follow_up)

    # 1d3. Answer composer: one LLM pass over the question + every FULL tool result writes the answer in
    # the benchmark's form (bare values, exact copies, every list item / requested part, no refusal when a
    # result answers). Kept only when every value it states is found in the results or the question.
    if cfg.answer_composer and llm_ainvoke is not None and _successful_calls(recorded_calls):
        evidence = format_full_evidence(recorded_calls, cfg.composer_result_chars)
        if evidence is None:
            logger.info(
                "[m3-adapter composer] skipped: a tool result is longer than {} chars",
                cfg.composer_result_chars,
            )
        else:
            try:
                composed = parse_composed(
                    await llm_ainvoke(
                        COMPOSER_PROMPT.format(
                            question=question or "(see the tool calls)", calls=evidence, answer=answer[:4000]
                        )
                    )
                )
            except Exception as exc:  # noqa: BLE001  (the composer is best-effort)
                logger.warning("[m3-adapter composer] failed ({}); keeping the draft", exc)
                composed = ""
            if composed and composed.upper() != "KEEP":
                pool = (
                    (question or "")
                    + " "
                    + " ".join(
                        str(c.get("result_full", c.get("result", "")))
                        for c in _successful_calls(recorded_calls)
                    )
                )
                missing = unsupported_values(composed, pool)
                if missing:
                    logger.info(
                        "[m3-adapter composer] kept the draft: {} not in the tool results", missing[:3]
                    )
                else:
                    new = canonicalize_final_answer(composed) if cfg.canonicalize else composed
                    if new != answer:
                        logger.info("[m3-adapter composer] rewrote {!r} -> {!r}", answer[:80], new[:80])
                    answer = new

    # 1d2. Values check (deterministic): a draft stating a value no tool returned (and the question
    # does not state) is re-asked once. A re-ask that ends empty or in a give-up keeps the draft.
    # Skipped when a result was cut at RESULT_MAX_CHARS: the evidence would be incomplete.
    for _ in range(cfg.values_check_rounds):
        successful = _successful_calls(recorded_calls)
        if not answer.strip() or is_giveup(answer) or not successful:
            break
        if any(len(str(c.get("result", ""))) >= RESULT_MAX_CHARS for c in successful):
            break
        evidence = " ".join([question] + [str(c.get("result", "")) for c in successful])
        missing = unsupported_values(answer, evidence)
        if not missing:
            break
        shown = ", ".join(missing[:6])
        logger.info("[m3-adapter values-check] not in any tool result: {}", shown[:200])
        follow_up = await retry(
            VALUES_CHECK_CORRECTION.format(values=shown, it="it" if len(missing) == 1 else "them"),
            "values-check",
        )
        new_answer = draft_of(follow_up) if follow_up is not None else ""
        if not new_answer.strip() or is_giveup(new_answer):
            break
        result, answer = follow_up, new_answer

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
    if not final_answer_installed and cfg.strip_demo_layout:
        answer = strip_demo_layout(answer)
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
