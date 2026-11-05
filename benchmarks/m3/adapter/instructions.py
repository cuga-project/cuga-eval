"""Instruction blocks the adapter appends per invoke (ported from the VAKRA runs).

Ported verbatim from vakra-main ``agents/agent_interface.py`` and
``agents/cuga_v2_agent.py`` — these exact texts produced the validated scores.
Delivered through CUGA's documented ``configurable["special_instructions"]``
hook, which the SDK joins with any constructor-level instructions (additive).

No ``cuga`` imports here: composition is pure string work and unit-testable.
"""

from __future__ import annotations

from typing import Optional

from benchmarks.m3.adapter.config import AdapterConfig, TaskContext

# VAKRA_CUGA_CONTRACT — bare-value final-answer contract (agent_interface.py).
# The CUGA runs replace ReAct's IMPOSSIBLE token with CUGA's refusal string at
# compose time (cuga_v2_agent.py) — see compose_instruction_block below.
ANSWER_CONTRACT = (
    "FINAL-ANSWER RULES (mandatory): Reply with the bare value(s) — a number, a name, "
    "or the COMPLETE list (never truncate or summarize a list). Digits not words. "
    "No markdown, no commentary, no caveats. Never guess or fabricate a value such as "
    "0, N/A, or an empty list when a step failed: first re-read the tool list and try "
    "the missing step; only if it is truly impossible after re-checking, answer "
    "exactly IMPOSSIBLE."
)

# VAKRA_CUGA_CAP1_PROTOCOL — canonical-chain guidance for handle-based data tools.
CAP1_PROTOCOL = (
    "CHAIN PROTOCOL (mandatory): Solve by a SHORT canonical chain of data tools: "
    "first the data is initialized for you; then use filter/select tools for each "
    "condition (one condition per call), then exactly one aggregate/compute/retrieve "
    "call for the result. Always pass the data_label/handle returned by the PREVIOUS "
    "step. Use the minimum number of calls; never repeat a call that succeeded."
)

# VAKRA_CUGA_CAP2_VERBATIM — verbatim-relay rule for single-tool dashboard queries.
CAP2_VERBATIM_RULE = (
    "ANSWER RULE: Call the single most specific tool that answers the question, then "
    "answer with the raw value(s) it returned — verbatim and COMPLETE. Never aggregate, "
    "average, deduplicate, reformat, or summarize the returned values, and add no prose."
)

# VAKRA_V2_DISCIPLINE — tool-use + final-answer discipline (cuga_v2_agent.py).
ANSWER_DISCIPLINE = (
    "TOOL USE RULES (mandatory):\n"
    "1. Before writing code, check whether ONE tool directly answers the question (matching "
    "name/purpose). Prefer that single call over composing several general tools.\n"
    "2. Make at most ONE tool call per code block - never write loops that call tools "
    "repeatedly. Inspect each result before deciding the next call.\n"
    "3. As soon as you have the information needed to answer, STOP - give the final answer "
    "with no additional tool calls. Keep the total under 8 calls.\n"
    "4. Call a document retriever (query_*) at most 2 times per task - retriever results "
    "are large; two retrievals are enough to know whether the documents cover the question.\n"
    "\n"
    "FINAL ANSWER RULES (mandatory):\n"
    "5. State ONLY facts present in the tool outputs you received in this conversation. "
    "Never add fields, attributes or values the tools did not return.\n"
    "6. Copy numeric values EXACTLY as returned by the tools - full precision, never round "
    "or abbreviate (write 2.2773093614383138, not 2.28).\n"
    "7. If the tool outputs contain the needed information, answer from them - do not refuse.\n"
    "8. If - and ONLY if - your tool calls returned nothing relevant to the question, reply "
    "with exactly:\n"
    "I can not answer.\n"
    "Nothing else - no explanations, no comments about tools or their failures, no apologies.\n"
    "NEVER give this refusal without having made at least one tool call first - always try "
    "the most relevant tool before concluding the data is unavailable.\n"
    "9. Give only the requested values/facts - no methodology narration."
)

# VAKRA_V2_VERBATIM — strict grounding rule, applied only when a cap4 policy
# scopes the task to document retrievers (see scope.py / the agent wrapper).
VERBATIM_RULE = (
    "DOCUMENT-ONLY TASK - STRICT GROUNDING RULE:\n"
    "Your final answer may contain ONLY facts that are written word-for-word in the "
    "retrieved document chunks. Do not infer, compute, combine, or attribute values the "
    "documents do not literally state. Before answering, verify each name and number in "
    "your answer appears in the retrieved text.\n"
    "Before refusing, re-scan EVERY retrieved chunk carefully: if any chunk literally "
    "states the requested value, answer with that value verbatim instead of refusing.\n"
    "Only if the documents do not literally contain the requested values, reply with "
    "exactly:\nI can not answer."
)


def build_handle_info(handle: Optional[str], peek: Optional[dict]) -> str:
    """cap1 handle/columns lines (port of ``CugaV2Agent._handle_info``).

    Tells the model how to use the environment's server-side handle system:
    results are handles, chained by passing the handle as the ``data_label``
    argument. Returns "" when no handle is known (graceful no-op).
    """
    if not handle:
        return ""
    info = ""
    if peek:
        try:
            key_details = peek.get("key_details", [])
            info = (
                f"\n- Total records: {peek.get('num_records', '?')}"
                f"\n- Columns: {[kd['name'] for kd in key_details]}"
            )
        except (KeyError, TypeError, AttributeError):
            info = ""
    return (
        f'INITIAL DATA: the dataset for this task is available as handle "{handle}"{info}. '
        "Pass the handle string as the data_label argument to chain tools, reuse handles "
        "returned by previous steps, and start from this handle in your first call."
    )


def compose_instruction_block(cfg: AdapterConfig, ctx: TaskContext) -> str:
    """Per-invoke ``configurable["special_instructions"]`` block.

    Order mirrors the validated adapter (``CugaCleanAgent.run`` +
    ``CugaV2Agent._invoke``): the cap4 policy passthrough first, then
    DISCIPLINE -> CONTRACT -> CAP1 handle+protocol -> CAP2 verbatim rule.
    (``VERBATIM_RULE`` is appended by the agent wrapper only after a policy
    scope resolves to retriever_only — it is deliberately not composed here.)
    """
    parts: list[str] = []
    if ctx.additional_instructions:
        parts.append(ctx.additional_instructions)
    if cfg.discipline:
        parts.append(ANSWER_DISCIPLINE)
    # Faithful to the source: the contract was applied only while the answer
    # gates were active for the capability (cuga_v2_agent.py:186).
    if cfg.answer_contract and cfg.gates:
        parts.append(
            ANSWER_CONTRACT.replace("answer exactly IMPOSSIBLE", 'answer exactly "I can not answer."')
        )
    if cfg.cap1_protocol and cfg.capability == 1:
        handle_info = build_handle_info(ctx.initial_data_handle, ctx.initial_data_peek)
        parts.append((handle_info + "\n\n" + CAP1_PROTOCOL) if handle_info else CAP1_PROTOCOL)
    if cfg.cap2_verbatim and cfg.capability == 2:
        parts.append(CAP2_VERBATIM_RULE)
    return "\n\n".join(p for p in parts if p)
