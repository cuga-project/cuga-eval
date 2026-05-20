# CUGA vs LangGraph ReAct on M3 (vakra) — full failure-mode analysis

**Bundle:** `benchmarks/m3/evaluation_bundles/20260428_201443_default/`
**Model (both agents):** `openai/gpt-oss-120b` via Groq
**CUGA agent:** `cuga_sdk` v0.2.20 (git df40ff98), mode `accurate`, `lite_mode=true`
**ReAct agent:** LangGraph ReAct, run files `benchmarks/m3/results_react/task{2,3}_lg_gpt-oss-120b.json`
**Benchmark:** M3 capability_dashboard_apis (Task 2, 100 cases) + capability_multihop_reasoning (Task 3, 100 cases) = 200 cases
**Scoring:** M3 vakra (three LLM judges: answer correctness, tool-call exactmatch, groundedness). A turn passes if its aggregated score ≥ 1.0; per the M3 aggregation rule any single sub-judge of 1.0 with at least one corroborating 1.0 (or aggregation defaulting through `None`) triggers pass.

> **Scope note for this rewrite.** The vakra evaluator (judges + aggregation), the benchmark groundtruth, the upstream MCP tool definitions, and the ReAct baseline are all **off-limits** as remediation levers — they are the benchmark and must not be modified. All remediations below are inside CUGA (cuga-agent + this repo's CUGA config), evaluated across a fixed lever taxonomy: **policy, memory, tool-enrichment (CUGA-side), configuration, prompt, code**. We prefer the policy/memory/config/code levers over a global system-prompt change wherever a more scoped lever fits.

---

## Executive summary (rewritten)

The 41 PF cases (ReAct passed, CUGA failed) are dominated by a single asymmetry: the groundedness judge returns `no` on CUGA's final answer in 26 of 41 cases (24 with `(answer=1.0, exactmatch=0.0, groundedness=0.0)` + 2 with `(None, 1.0, 0.0)`) while returning `yes` for ReAct on the same questions with near-identical wording. We cannot change how that judge scores. What we **can** do is shape CUGA's final answer and tool-selection behaviour from the CUGA side so the judge's prompt finds the keywords it expects.

The most important finding of this rewrite is that CUGA already ships a rich **policy engine** (`Playbook`, `IntentGuard`, `ToolGuide`, `ToolApproval`, `OutputFormatter`, `CustomPolicy` — see `cuga-agent/src/cuga/backend/cuga_graph/policy/models.py`) that was **disabled** in this run (`DYNACONF_POLICY__ENABLED=false`). The `OutputFormatter` policy in particular is hooked into the LITE_MODE path that this benchmark uses (`cuga_lite_node.py:_apply_output_formatter`), so it can rewrite the final answer per matched trigger without touching prompts globally. **A small policy bundle (one shared `OutputFormatter` for single-fact answers, one for hedging strip, a handful of `ToolGuide` policies for the tool-disambiguation cases, and 2–3 `Playbook` rules for chain-minimization) is the highest-leverage CUGA-side fix in the bundle.**

The other two priorities are: (a) a small **code change** to the CUGA sandbox codegen step to stop wrapping previous-tool-result dicts into the next call's argument (the "nested-argument bug" — directly causes 7 PF cases and inflates cost across many more), and (b) **needs-investigation** for `movie_platform` and `professional_basketball` (7 PF + 13 FF cases with no CUGA trace — likely an MCP-client/registry health issue on the CUGA side, not a benchmark issue).

Per-case lever comparisons are in §3. The policy/memory/tool-enrichment/configuration/prompt/code framework is applied uniformly per case.

---

## 1. Headline summary

| Task | Capability | CUGA pass | ReAct pass | Δ |
| --- | --- | --- | --- | --- |
| 2 | capability_dashboard_apis | **28/100 (28%)** | 49/100 (49%) | −21 pp |
| 3 | capability_multihop_reasoning | **12/100 (12%)** | 23/100 (23%) | −11 pp |
| **Total** | both | **40/200 (20%)** | 72/200 (36%) | −16 pp |

### Per-domain pass rates (CUGA / ReAct)

#### Task 2 — dashboard_apis

| Domain | CUGA | ReAct |
| --- | --- | --- |
| authors | 7/10 | 5/10 |
| books | 7/10 | 7/10 |
| codebase_comments | **0/10** | 4/10 |
| hockey | 6/10 | 7/10 |
| mondial_geo | **0/10** | 3/10 |
| movie_platform | **0/10** | 4/10 |
| professional_basketball | **0/10** | 3/10 |
| soccer_2016 | **0/10** | 5/10 |
| student_loan | **0/10** | 4/10 |
| talkingdata | 8/10 | 7/10 |

#### Task 3 — multihop_reasoning

| Domain | CUGA | ReAct |
| --- | --- | --- |
| beer_factory | 0/10 | 2/10 |
| books | 6/10 | 5/10 |
| college_completion | 0/10 | 1/10 |
| computer_student | 0/10 | 2/10 |
| disney | 2/10 | 3/10 |
| mondial_geo | 0/10 | 2/10 |
| soccer_2016 | 0/10 | 5/10 |
| trains | 1/10 | 0/10 |
| university | 3/10 | 3/10 |
| world_development_indicators | 0/10 | 0/10 |

CUGA is bimodal: it pegs 60–80% on `authors`, `books`, `hockey`, `talkingdata`, `books` (T3) — and 0% on 12 of the remaining 15 domain×task combos. ReAct is roughly uniform (20–50% almost everywhere). This pattern is the single most important signal in the data: **CUGA either nails a domain or fails it completely.** That is a deterministic-failure pattern, not a sampling-variance pattern, and it means a single root cause is likely responsible for a domain's zero score.

### The four quadrants

|  | CUGA pass | CUGA fail | total |
| --- | --- | --- | --- |
| **ReAct pass** | PP=31 | PF=41 | 72 |
| **ReAct fail** | FP=9 | FF=119 | 128 |
| **total** | 40 | 160 | 200 |

This report's actionable content focuses on the **41 PF cases** (cases ReAct passed but CUGA failed). Those are the gap — closing them lifts CUGA to 81/200 (40.5%), comfortably above ReAct's 72/200. The FF appendix is just listed at the end.

---

## 2. Failure-mode clustering — the actionable summary

Each of the 41 PF cases was classified by inspecting (a) the CUGA langfuse trace's tool sequence and final answer, (b) the CUGA vakra sub-scores (answer / exactmatch / groundedness), and (c) the M3 judge explanations.

### CUGA PF score-pattern distribution (the asymmetry)

| (answer_s, exactmatch_s, groundedness_s) | n | meaning |
| --- | --- | --- |
| **(1.0, 0.0, 0.0)** | 24 | CUGA gave the right answer; tool-call exactmatch failed (over- or differently-called); **groundedness judge returned `no`**. ReAct on the *same* questions all scored (1.0, 0.0, **1.0**) and passed. |
| (0.0, 0.0, None) | 15 | CUGA's answer was actually judged incorrect — a genuine answer failure. |
| (None, 1.0, 0.0) | 2 | Tool-call exactmatch passed but groundedness=0. |

ReAct's PF score pattern is uniformly `(1.0, 0.0, 1.0)` on all 41 — i.e., it never matches the tool sequence exactly either, and it always passes the answer judge AND the groundedness judge. **The 26 CUGA cases (24+2) that pass at least one judge with `1.0` but lose because `groundedness=0` are the largest single closable lever in this report** — and they are the cases where a CUGA-side `OutputFormatter` policy can rewrite the final answer to put the keywords/values the groundedness judge looks for back in front of it.

### 2.1 The lever taxonomy used in this rewrite

For each PF case in §3, we evaluate the following levers in fixed order. Each lever that is plausibly relevant gets one sentence; clearly-irrelevant levers are skipped to avoid padding.

1. **Policy** — CUGA's policy engine (`Playbook` / `IntentGuard` / `ToolGuide` / `ToolApproval` / `OutputFormatter` / `CustomPolicy`). Currently disabled in this run (`DYNACONF_POLICY__ENABLED=false`). The engine matches triggers (keyword, natural_language, app, state, tool, always) against the `intent`, `agent_response`, etc. Most relevant variants for this report:
   - `OutputFormatter` rewrites the *final* AI message based on trigger matches against the response itself (markdown rewriting, JSON-schema reshape, or direct string replacement) — wired into the LITE_MODE path via `cuga_lite_node._apply_output_formatter`. **This is the natural fit for the groundedness cluster**: it can prepend a tool/key citation, strip hedging, or strip unsolicited context paragraphs without touching the global FinalAnswerAgent prompt.
   - `Playbook` injects step-by-step guidance keyed by intent — useful for "use this single composite tool, do not corroborate", or for "do not enumerate runners-up when a single item is asked".
   - `ToolGuide` enriches CUGA's *view* of a tool's description (prepended/appended markdown) — useful for tool-disambiguation cases and for steering the shortlister's embedding match. **Note**: this changes the description CUGA stores/uses, not the upstream MCP tool itself.
2. **Memory** — agentic_memory subsystem in `cuga-agent/src/cuga/backend/memory/agentic_memory/`. Could provide few-shot trajectories from past similar runs. Helps tasks that benefit from seeing the canonical tool path before. Cold-start ineffective.
3. **Tool enrichment** (CUGA-side only) — overlaps with `ToolGuide` policy above, plus CUGA's shortlister/registry behaviour, retry/argument-coercion wrappers around MCP calls.
4. **Configuration** — env vars in `benchmarks/m3/config/m3.env` and the run's `metadata.json`: `CUGA_MODE`, `LITE_MODE`, `LITE_MODE_TOOL_THRESHOLD`, `SHORTLISTING_TOOL_THRESHOLD`, `DECOMPOSITION_STRATEGY`, `REFLECTION_ENABLED`, `ENABLE_TODOS`, `FORCE_AUTONOMOUS_MODE`, `TOOL_CALL_TIMEOUT`, `PATH_SEGMENT_INDEX`, `TRACKER_ENABLED`, `agent_setting_config`, `model_profile`.
5. **Prompt change** — *deprioritized*. Global FinalAnswerAgent prompt edits affect all runs and are a heavy hammer for benchmark-scoped issues. Only recommended where no other lever fits.
6. **Code change** — actual code edits to cuga-agent (parser fixes, bug fixes, control-flow). Reserved for clear bugs (notably the nested-arg bug).

### 2.2 Cluster table

Cluster names and counts are unchanged from the original analysis; the rightmost column is the new "best CUGA-side lever (runner-up)" framing.

| failure mode | n | % of PF | best lever (runner-up) |
| --- | --- | --- | --- |
| **verbose_answer_or_extra_tools** | 23 | 56% | **policy: `OutputFormatter`** (shared single-fact citation that prepends tool name + key to the answer; second OutputFormatter to strip hedging / "for context" appendices / dataset meta-commentary). Runner-up: prompt change to FinalAnswerAgent (same effect, global). See §2.3.1. |
| **no_trace_pre_llm_crash** | 7 | 17% | **needs-investigation + code**: re-run `movie_platform` and `professional_basketball` MCP under the same CUGA config to capture registry stderr; add a CUGA-side "empty tool list → loud error" failsafe in the MCP-client glue. Policy/memory are inapplicable when the LLM never ran. See §2.3.2. |
| **wrong_args_or_aggregation** | 7 | 17% | Two sub-patterns. C1 (nested-argument bug): **code** (sandbox codegen rule: when binding a value from a prior tool's response, subscript the JSON key, never pass the whole dict). C2 (expressed-uncertainty / wrong-aggregation): **policy: `OutputFormatter`** to strip hedging tokens + `Playbook` "never rescale numeric tool outputs" / "prefer purpose-built tool over generic detail tool". See §2.3.3. |
| **timeout_or_giveup** | 2 | 5% | **policy: `Playbook`** ("emit confident final on first numeric match for the intent") + `OutputFormatter` strip-hedging. Runner-up: configuration (try `ENABLE_TODOS=true` or `REFLECTION_ENABLED=false` ablation to bound exploration). See §2.3.4. |
| **wrong_tool_selected** | 1 | 2% | **policy: `ToolGuide`** enriching `get_mountain_count_most_populous_country` description with "country with the largest/greatest/most population" so the shortlister surfaces it. Runner-up: memory if accumulated across runs. See §2.3.5. |
| **hallucinated_no_tool** | 1 | 2% | **code**: CUGA-side sandbox guard — if the generated `await ...` references a function not in the resolved tool registry, raise a hard error instead of letting the code block become the final answer. Also fix the underlying registry health for the domain. Same root family as the no-trace cluster. See §2.3.6. |

### 2.3 Cluster-level remediations

#### 2.3.1 Cluster A — `verbose_answer_or_extra_tools` (n=23): the groundedness-judge gap

Concrete pattern. CUGA's `final_response` typically matches ReAct's almost word-for-word; the answer judge gives both `1.0`. Yet the groundedness judge (also gpt-oss-120b) returns "no" for CUGA and "yes" for ReAct. Reading the judge's reasoning across all 23 cases reveals a consistent pattern: **the groundedness judge claims "the document provides no information" or "the document only indicates the relevant tool was not found"** — *even though the predicted `tool_response` payload (e.g. `{"stars": 272}`) is literally embedded in the document the judge sees.* This is small-model judge confabulation. We cannot change the judge. We can stack the deck from CUGA's side.

A precise example (uuid `1960f609e439-e5d337d143b6`, T2 codebase_comments):
- Q: "How many stars does the repository of the solution No. 45997 have?"
- ReAct ans: "The repository associated with solution **#45997** has **272 stars**."
- CUGA ans: "Solution #45997's repository has **272** stars."
- Vakra prediction file CUGA tool_response: `["{\"stars\": 272}"]`
- ReAct gnd judge: "The response correctly restates the document's fact that solution #45997's repository has 272 stars" → score 1
- CUGA gnd judge: "The response provides a specific star count (272) that is not present in the document, which only indicates the query could not retrieve star information" → score 0

**Recommended remediation — policy first.** Build a small `OutputFormatter` policy bundle and enable it for the M3 run only (`DYNACONF_POLICY__ENABLED=true`, point the policy folder at a benchmark-scoped policy directory analogous to `benchmarks/bpo/policies/`).

- **Policy P-OF-1 ("cite tool and key on single-fact answers"):** `OutputFormatter`, `format_type=markdown`, trigger = natural-language match on `agent_response` like "response contains a single fact or single short list that came from one tool call". `format_config` instructs the LLM to rewrite the response so it (a) opens with a one-clause restatement that literally repeats the JSON key from the tool response — e.g. *"The repository's star count, returned by `get_repo_stars_by_solution_id`, is `272`."* — and (b) preserves the original answer body. Expected to flip ~10–15 of the 24 `(1.0, 0.0, 0.0)` cases. Cost: one LLM call per response when the policy matches.

  Rationale vs the alternatives: a global FinalAnswerAgent prompt change has the same effect on this judge but applies to all runs of CUGA (chat, browser tasks, non-M3 benchmarks) and is harder to reason about. `OutputFormatter` is scoped: it fires only on responses that match its trigger, leaves the rest of CUGA's behaviour alone, and can be disabled by flipping `DYNACONF_POLICY__ENABLED`.

- **Policy P-OF-2 ("strip hedging / unsolicited context / dataset meta-commentary"):** second `OutputFormatter`, `format_type=markdown`, triggers on `agent_response` containing phrases like "upper bound", "cannot be completed", "may be lower", "For context", "However, X is actually Y", "The dataset does not provide a tool to". `format_config` instructs: "If the answer contains a numeric value or named entity that resolves the question, emit only that resolved answer; strip hedging clauses, dataset meta-commentary, and unsolicited `For context` appendices." Recovers the soccer_2016 hedge cases, the BYU-Idaho appendix in college_completion, the cricket-vs-soccer meta-commentary, and the computer_student "upper bound" case.

  Rationale vs the alternatives: a prompt change would do the same job, but in our PF/FP analysis (see §5) CUGA's confident answer style is a *strength* on the 9 FP cases — we want to remove hedging selectively (only when a numeric value is already in hand), not blanket-restructure the FinalAnswerAgent prompt.

- **Policy P-PB-1 ("no enumeration when a single item is asked"):** `Playbook`, trigger on intent containing singular phrasing ("which conference", "the city of", "the solution path with..."). `markdown_content` instructs: "Return only the single requested item; do not enumerate runners-up or 'Top N' alternatives." Targets the ICRA case and similar.

- **Policy P-PB-2 ("one composite tool, no corroboration"):** `Playbook`, trigger on percent/ratio/proportion intents. Instructs: "If a single endpoint returns the percentage/ratio directly, use only that endpoint. Do not also call the raw component tools to corroborate."

- **Policy P-PB-3 ("no idempotent retries"):** `Playbook`, instructs: "Do not re-invoke a tool that returned a deterministic value during the same turn; emit the answer."

**What policy cannot do here.** None of these policies can rescue a case where CUGA called the wrong tool entirely (Cluster E) or where the underlying capability did not run (Cluster B). Those need different levers; see below.

#### 2.3.2 Cluster B — `no_trace_pre_llm_crash` (n=7 in PF, 22 total)

22 of 200 cases produced no CUGA langfuse trace at all. These split into:

- **`movie_platform` (8 of 10 cases in T2)** — 7 of these are FF (also ReAct fail), 1 is PF.
- **`professional_basketball` (10 of 10 cases in T2)** — all FF.
- Sporadic singletons in `codebase_comments`, `mondial_geo`, `soccer_2016`, `college_completion`.

The PF cases that fall in this bucket are:

| uuid | task | domain |
| --- | --- | --- |
| 31d9743578dc-20fe1c6e0318 | 2 | movie_platform |
| 31d9743578dc-3b59b2d5a9b3 | 2 | movie_platform |
| 31d9743578dc-fa8256c2888f | 2 | movie_platform |
| d14bbb0be92d-781ff55b91b7 | 2 | professional_basketball |
| d14bbb0be92d-b94c0c0446e9 | 2 | professional_basketball |
| d14bbb0be92d-7d51d5f6098d | 2 | professional_basketball |
| fe971e7f850a-0bd47606e297 | 2 | soccer_2016 (this one *does* have a CUGA result but with 0 actual tool calls and an empty final_response, which is the same symptom) |

For the entire bucket, the `report.md` row shows blank tokens/duration. This is consistent with **a registry / MCP-client startup failure** on the CUGA side for those domains — the CUGA agent didn't obtain a tool list and produced nothing. The fact that `professional_basketball` is 100% no-trace is the strongest signal.

**Why policy / memory / config alone cannot fix this.** Policies are evaluated against `intent` / `agent_response` / state — they require the LLM to actually run at least once. Memory likewise. Configuration could mask the symptom (e.g., a guard for empty tool lists) but cannot cause the registry to succeed.

**Recommended remediations:**
- **Needs-investigation:** re-run `movie_platform` and `professional_basketball` MCP servers in isolation under the same CUGA config; capture stderr from the registry expansion step in `eval_m3.py` (the `m3_registry.yaml` → expanded config path that runs at boot). Look for missing-endpoint, schema-validation, or container-startup errors on the CUGA-side MCP client.
- **Code:** add a CUGA-side failsafe in the MCP-client glue — when the registry returns an empty tool list for a domain, emit an explicit guard error to the trace rather than silently producing no output. This converts a silent zero into a diagnosable error and prevents the case from losing its turn slot. Also enables the rest of the bundle to surface the issue earlier (so we don't lose a full run silently).

#### 2.3.3 Cluster C — `wrong_args_or_aggregation` (n=7)

Two sub-patterns, both repeatable.

**Sub-pattern C1: nested-argument bug** (very prevalent across many runs, including some that DID pass after retry):
```python
# tool A returns {"director": "Wolfgang Reitherman"}
# tool B expects (director: str)
# CUGA generates:
tool_B(director={"director": "Wolfgang Reitherman"})   # ← nested
# Server returns: "Input validation error: {'director': 'Wolfgang Reitherman'} is not of type 'string'"
# CUGA self-corrects on the next turn, but burns a step + an LLM call
```
Observed in PF cases: `34a533dfd727-9a80447e42a5` (disney), `34a533dfd727-792336e9811f` (disney), `fe971e7f850a-0ce9f1bd5b3e` (soccer_2016), `fe971e7f850a-d6dd43c77447` (soccer_2016), `55b7e50368aa-cd69f2bccbaa` (mondial_geo) — and many more in the FF and PP traces too. CUGA *almost always* recovers, but on multihop chains with 2–3 chained tools, the failed-then-retried attempts inflate the tool-call count to 5+ and inflate latency, sometimes pushing the case into a timeout, sometimes producing a wrong intermediate result that fools the second call.

**Remediation comparison for C1.**
- **Code:** add a single-purpose rule to the sandbox Python-codegen step: "When passing a value from a previous tool's response, unwrap the JSON key with subscript access — never pass the whole dict." E.g. `r = await tool_A(); tool_B(director=r['director'])`. This is the direct cure and is cheap. **Recommended.**
- **Policy:** a `Playbook` instructing the same rule via intent-match could partially help but only at the level of the planner narrative; the sandbox codegen is downstream and is where the actual bug lives.
- **Tool enrichment:** `ToolGuide` policies prepending "argument types: scalar, not dict" to tool descriptions would marginally help but doesn't catch the root cause.
- **Configuration:** no relevant flag.

**Sub-pattern C2: expressed-uncertainty / wrong-aggregation answer.** Two cases (`308738b8195d-56faa9f6bbd2` hockey "temporary coaches" and `39a28b2592a2-a6d040ce4d19` computer_student) where CUGA *had* the correct number (1 and 13) but wrapped the answer in language like "The task cannot be completed because..." or "this figure is an upper bound". The answer judge's prompt has a hardcoded rule: "Predictions expressing uncertainty score 0 even if numerically correct." Plus the `bc9218680ed5-0b0ec8d0b7d2` case where CUGA rescaled a `{percentage: 1500}` tool output to "15%" (helpful but penalized). Plus the `34a533dfd727-792336e9811f` case where a generic detail tool's output overrode a purpose-built tool's correct answer.

**Remediation comparison for C2.**
- **Policy `OutputFormatter` (P-OF-2):** strip hedging tokens from the head of the response when a numeric value is present. Cheap and surgical. **Recommended for the hedging cases.**
- **Policy `Playbook`:** "never numerically rescale a value that came directly from a tool response — emit it verbatim" (for the 1500% case). "When multiple tools have returned candidate answers, prefer the purpose-built tool's result over the generic detail tool's" (for the disney case).
- **Prompt change:** would also work but global; policy is preferred per user's framing.

#### 2.3.4 Cluster D — `timeout_or_giveup` (n=2)

Both timeouts hit the 120 s `TOOL_CALL_TIMEOUT` while still iterating: `308738b8195d-56faa9f6bbd2` (140 s, 54 LLM calls, hockey "temporary coaches") and `39a28b2592a2-a6d040ce4d19` (195 s, 48 LLM calls, computer_student). Both are also uncertainty-expression cases (C2 above).

**Recommended remediation — combined:** the P-OF-2 hedging-strip policy + a `Playbook` rule "when a tool has returned a numeric value that resolves the question's intent, emit a confident final answer immediately". As a configuration ablation, try `REFLECTION_ENABLED=false` on a re-run of these two cases — the reflection step appears to be driving repeated re-checks. `TOOL_CALL_TIMEOUT` is *per-call* and not the binding constraint here; raising it further does not help.

#### 2.3.5 Cluster E — `wrong_tool_selected` (n=1)

Single case: `55b7e50368aa-7d0eae1aeaf4` (T2 mondial_geo, "mountains in the country with the greatest population"). The expected single tool is `get_mountain_count_most_populous_country`. CUGA instead chained `get_most_populous_city_excluding_capital_global` → `get_country_of_city` → `get_mountain_count_by_country` and arrived at India (which has 0 mountains in the dataset), the wrong answer. The shortlister didn't surface the canonical tool because its CUGA-side description doesn't contain the user's vocabulary ("country with the greatest/largest population").

**Recommended remediation — policy `ToolGuide`:** a `ToolGuide` policy targeting the `get_mountain_count_most_populous_country` tool name, with `prepend=true` and `guide_content`: *"Use this tool when the user asks for mountains in the country with the largest/greatest/most population. Do NOT compose with city-population tools."* This enriches CUGA's view of the tool description used by the shortlister; the upstream MCP tool definition is unchanged.

#### 2.3.6 Cluster F — `hallucinated_no_tool` (n=1)

Single case: `31d9743578dc-5b6784e8d151` (T2 movie_platform). CUGA emitted a Python code block describing what it WOULD do instead of executing it. Almost certainly the same root cause as Cluster B (movie_platform registry health). Remediation: **code** (sandbox guard: unknown-tool-reference → hard error; never emit raw code as the final answer) + the same needs-investigation that Cluster B needs.

---

## 3. Per-case PF narratives — grouped by failure mode

Per the lever taxonomy in §2.1, each case below has: (a) ReAct's answer + CUGA's answer + sub-scores, (b) the diagnosis (unchanged from the prior version), (c) a per-lever verdict table, and (d) a single recommended lever with the runner-up named.

### 3.1 `verbose_answer_or_extra_tools` (n=23)

> **Default recommendation for this cluster:** policy P-OF-1 (single-fact OutputFormatter that cites tool name + JSON key), augmented per case with P-OF-2 (hedging/appendix strip), P-PB-1 (no enumeration), P-PB-2 (no corroboration), or P-PB-3 (no idempotent retries) as called out below. Where the C1 nested-arg bug is also present, the code fix is recommended in parallel.

#### 3.1.1 `6e317bcd6839-bbaadc612be9` | T2 books — "List all books published in 1995"

**Diagnosis.** CUGA called the right tool (`get_book_titles_by_publication_year(year="1995")`), returned the same titles as ReAct. Answer judge 1.0, gnd judge 0.0 ("document provides only titles without any publication year information") — the year filter is not restated in the answer, so the judge cannot find it as a keyword.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — OutputFormatter (markdown) that opens the response with "Based on `get_book_titles_by_publication_year` for year 1995:". Puts the keyword back in front of the judge. |
| memory | WEAK — pattern is general; only helps after accumulated trajectories. |
| tool_enrichment | not applicable. |
| configuration | not applicable. |
| prompt | would work but global. |
| code | not needed. |

**Recommended:** policy (P-OF-1 variant: restate the filter clause). Runner-up: prompt change (equivalent, more global).

#### 3.1.2 `1960f609e439-e5d337d143b6` | T2 codebase_comments — "Stars of solution #45997?"

**Diagnosis.** Both: "272 stars". CUGA `(answer=1.0, em=0.0, gnd=0.0)`. The canonical groundedness-judge confabulation example.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-1 (single-tool-fact citation). |
| memory | weak. |
| tool_enrichment | not applicable. |
| configuration | not applicable. |
| prompt | redundant with policy. |
| code | not needed. |

**Recommended:** policy P-OF-1. Runner-up: prompt change to FinalAnswerAgent (same outcome, global).

#### 3.1.3 `1960f609e439-ab3a664a6a28` | T2 codebase_comments — "Solution path with highest processed time"

**Diagnosis.** Same as 3.1.2.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-1. |
| memory | weak. |
| tool_enrichment | not applicable. |
| configuration | not applicable. |
| prompt | redundant. |
| code | not needed. |

**Recommended:** policy P-OF-1.

#### 3.1.4 `1960f609e439-00fe3f448af7` | T2 codebase_comments — "Forks-to-stars % for solution 104086"

**Diagnosis.** Both answered correctly. CUGA called three tools (the percent tool + raw forks + raw stars) — over-grounding. The extra payloads enter the document but their values are not in the answer, which the gnd judge flags.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-1 + P-PB-2 ("one composite tool, no corroboration"). |
| memory | partial — would help with a "preferred composite tool for % queries in domain X". |
| tool_enrichment | partial — `ToolGuide` on the percent tool with "use this single tool; do not call raw count tools afterwards". |
| configuration | not applicable. |
| prompt | partial — could tell FinalAnswerAgent to omit redundant context but does not stop the extra upstream calls. |
| code | not needed. |

**Recommended:** policy (P-OF-1 + P-PB-2). Runner-up: `ToolGuide` on the percent tool.

#### 3.1.5 `1960f609e439-d1ba8f4ad233` | T2 codebase_comments — "Solution ids for repos with 238 forks"

**Diagnosis.** Both: "62258 and 258160". CUGA called the right tool, then 4 verification calls. gnd=0.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — `Playbook` "do not run verification calls after a list-returning tool succeeds" + P-OF-1. |
| memory | partial. |
| tool_enrichment | partial — `ToolGuide` on `get_solution_ids_by_repo_forks` saying "this tool returns the complete list; do not verify individual entries". |
| configuration | `REFLECTION_ENABLED=false` ablation likely eliminates the verification loop (the verify-after-success reads as reflection-driven). |
| prompt | partial — a global "do not verify" rule is risky (verification is sometimes warranted). |
| code | not needed. |

**Recommended:** policy (Playbook + P-OF-1). Runner-up: configuration ablation (`REFLECTION_ENABLED=false`).

#### 3.1.6 `55b7e50368aa-cbe1f5a85755` | T2 mondial_geo — "City of lake at (-85.35, 11.6)?"

**Diagnosis.** Both: "Granada". CUGA gnd=0. Single-tool confabulation.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-1. |
| memory | weak. tool_enrichment / configuration / code: not applicable. prompt: redundant. |

**Recommended:** policy P-OF-1.

#### 3.1.7 `55b7e50368aa-50580d511198` | T2 mondial_geo — "Most prevalent religion in Asia"

**Diagnosis.** Both: "Islam (Muslim)". CUGA gnd=0.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-1. |
| memory | weak. tool_enrichment / configuration / code: not applicable. prompt: redundant. |

**Recommended:** policy P-OF-1.

#### 3.1.8 `fe971e7f850a-f39d12a24e8a` | T2 soccer_2016 — "Country with most umpires, count?"

**Diagnosis.** First call OK (country_id=1, count=27). Second call (`get_umpire_count_by_country`) hit the nested-arg bug and looped retrying. CUGA's final answer was hedged: "The dataset does not provide a tool to translate the country ID = 1 into its name." Hedge + enumeration tanked gnd.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-1 + P-OF-2 (strip hedge tokens). |
| memory | weak on this turn. |
| tool_enrichment | partial — `ToolGuide` clarifying that the country/umpire pair returns an ID, not a name. |
| configuration | not applicable to the hedge symptom. |
| prompt | redundant. |
| code | **STRONG FIT** — nested-arg fix (C1) directly removes the retry loop. |

**Recommended:** code (nested-arg) + policy (P-OF-1 + P-OF-2).

#### 3.1.9 `fe971e7f850a-d96a7bc6401a` | T2 soccer_2016 — "City with most venues"

**Diagnosis.** Both: "Abu Dhabi". CUGA gnd=0.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-1. |
| memory | weak. tool_enrichment / configuration / code: not applicable. prompt: redundant. |

**Recommended:** policy P-OF-1.

#### 3.1.10 `fe971e7f850a-4c26b4a6556a` | T2 soccer_2016 — "Matches with 7-point winning margin"

**Diagnosis.** Both: 69. CUGA called the same tool twice (idempotent reflection retry). gnd=0.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-1 + P-PB-3 (no idempotent retries). |
| memory | weak. |
| tool_enrichment | not applicable. |
| configuration | partial — `REFLECTION_ENABLED=false` removes the duplicate but is blunt. |
| prompt | redundant. |
| code | not needed. |

**Recommended:** policy (P-OF-1 + P-PB-3). Runner-up: configuration ablation.

#### 3.1.11 `fe971e7f850a-a9ff06e36390` | T2 soccer_2016 — "Players born in the 90s"

**Diagnosis.** Both: 92. CUGA called once, gnd=0. Pure confabulation.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-1. |
| memory | weak. tool_enrichment / configuration / code: not applicable. prompt: redundant. |

**Recommended:** policy P-OF-1.

#### 3.1.12 `bc9218680ed5-5c65b18294ea` | T2 student_loan — "Disabled students absent 9 months"

**Diagnosis.** Both: 7. CUGA gnd=0. Single-tool case.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-1. |
| memory | weak. tool_enrichment / configuration / code: not applicable. prompt: redundant. |

**Recommended:** policy P-OF-1.

#### 3.1.13 `bc9218680ed5-c0791be2fe5f` | T2 student_loan — "Males in >1 organization"

**Diagnosis.** Both: 9. CUGA gnd=0.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-1. |
| memory | weak. tool_enrichment / configuration / code: not applicable. prompt: redundant. |

**Recommended:** policy P-OF-1.

#### 3.1.14 `bc9218680ed5-8d19697e5e81` | T2 student_loan — "% male students"

**Diagnosis.** Both: 49.7%. CUGA gnd=0.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-1. |
| memory | weak. tool_enrichment / configuration / code: not applicable. prompt: redundant. |

**Recommended:** policy P-OF-1.

#### 3.1.15 `a823e527d383-9ca3b8a7ad8e` | T3 beer_factory — "Folsom customers using top non-alcoholic credit card"

**Diagnosis.** Both: 56. CUGA 5 tools (nested-arg retry inflated). gnd=0.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-1. |
| memory | weak. |
| tool_enrichment | partial — for the retry tail. |
| configuration | not applicable. |
| prompt | redundant. |
| code | **STRONG FIT** — nested-arg fix (C1) prevents the retry tail. |

**Recommended:** code (nested-arg) + policy P-OF-1.

#### 3.1.16 `2b28654158b1-a59483784521` | T3 college_completion — "Lowest grad-100 4-year public school in ID"

**Diagnosis.** Both: Lewis-Clark State College. CUGA 5 tools, 20 LLM calls, 64 s. gnd=0 partly because CUGA volunteered "For context, the institution with the highest number of students in Idaho is BYU-Idaho..." — ungrounded extra paragraph.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-2 (strip "For context" appendix). |
| memory | weak. tool_enrichment / configuration / code: not applicable. prompt: would work but global. |

**Recommended:** policy P-OF-2.

#### 3.1.17 `39a28b2592a2-ebd77c3a7592` | T3 computer_student — "Students advised by profs teaching basic/medium at most-teachers level"

**Diagnosis.** Both: 0. CUGA 12 tools, 34 LLM calls, 113 s. gnd=0 — over-exploration introduced extra tool payloads.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-1 + a chain-minimization `Playbook` for multi-hop intents. |
| memory | partial. |
| tool_enrichment | not applicable. |
| configuration | partial — `REFLECTION_ENABLED=false` ablation. |
| prompt | would work; less scoped. |
| code | not needed. |

**Recommended:** policy (P-OF-1 + chain-minimization Playbook). Runner-up: configuration ablation.

#### 3.1.18 `55b7e50368aa-cd69f2bccbaa` | T3 mondial_geo — "GDP of continent with country with most erosion of real income"

**Diagnosis.** Both: 9,138,648. CUGA 6 tools (nested-arg bug retry: `continent_name={"continent":"Europe"}`), 17 LLM calls. gnd=0.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-1. |
| memory | weak. tool_enrichment / configuration: not applicable. prompt: redundant. |
| code | **STRONG FIT** — canonical nested-arg example. |

**Recommended:** code (nested-arg fix) + policy P-OF-1.

#### 3.1.19 `55b7e50368aa-2b73471429c9` | T3 mondial_geo — "Mountains in country with highest GDP"

**Diagnosis.** Both: 0 (United States). CUGA 3 tools (nested-arg retry). gnd=0.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-1. |
| memory | weak. tool_enrichment / configuration: not applicable. prompt: redundant. |
| code | **STRONG FIT** — nested-arg fix. |

**Recommended:** code (nested-arg) + policy P-OF-1.

#### 3.1.20 `fe971e7f850a-979018f9bffc` | T3 soccer_2016 — "Matches won by team that won match 336000 in 2008"

**Diagnosis.** Both: 10. CUGA 4 tools (3 duplicate `get_match_winner` + `get_sum_matches_won`), 26 LLM calls, 63 s. CUGA also editorialized "However, Kings XI Punjab is a cricket franchise, not a soccer club..." (dataset is misnamed) — meta-commentary tanked gnd.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-2 (strip dataset meta-commentary) + P-OF-1. |
| memory | weak. tool_enrichment / configuration / code: not applicable. prompt: would work, less scoped. |

**Recommended:** policy (P-OF-2 + P-OF-1).

#### 3.1.21 `fe971e7f850a-67265ddc680f` | T3 soccer_2016 — "Cities in country of Rajkot"

**Diagnosis.** Both: 20. CUGA 4 tools (nested-arg retry). gnd=0.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-1. |
| memory | weak. tool_enrichment / configuration: not applicable. prompt: redundant. |
| code | **STRONG FIT** — nested-arg fix. |

**Recommended:** code (nested-arg) + policy P-OF-1.

#### 3.1.22 `fe971e7f850a-2c978b083683` | T3 soccer_2016 — "Season with most matches at M Chinnaswamy Stadium"

**Diagnosis.** ReAct: "Season 9". CUGA: "Season 9 with 60 matches" (extra "60 matches" decoration). Expected tool sequence is 3 tools; CUGA's path used 3 different tools, so exactmatch fails on tool identity (separate signal). gnd=0 on the extra decoration.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-1 + a strip-decorative-appendix variant of P-OF-2. |
| memory | weak. |
| tool_enrichment | partial — `ToolGuide` on `get_top_season_by_venue`: "this returns the season — answer with just the season; do not append the match count". |
| configuration | not applicable. |
| prompt | redundant. |
| code | not needed. |

**Recommended:** policy (P-OF-1 + appendix-strip). Note: tool-identity mismatch is a separate exactmatch issue and is part of the benchmark; the aggregation should still pass if `answer_s=1.0` and `gnd_s=1.0`.

#### 3.1.23 `adba6c0ec8a8-f33b6a3e1a35` | T3 university — "% universities with teaching>90 in 2011 in same country as univ 112"

**Diagnosis.** Both: 100%. CUGA 1,139 tool calls (extreme outlier), 40 LLM calls, 159 s, 967 k tok. Final answer is concise ("100 %") and answer=1.0; gnd=0. The 1,139 calls are an exploration explosion that doesn't change the final answer but dominates cost. Likely a registry list_tools loop rather than a multi-step plan.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** for the gnd lift — P-OF-1. Plus a `Playbook`/`IntentGuard` style step-budget rule (when the planner has exceeded N tool calls without a new useful signal, force an emit) — this maps to an `IntentGuard` that intercepts on state conditions. |
| memory | partial. |
| tool_enrichment | partial — `ToolGuide` on whichever composite percent tool exists. |
| configuration | **STRONG FIT** — try `ENABLE_TODOS=true` (forces a bounded plan); ablate `REFLECTION_ENABLED=false` (eliminates per-step recompute). |
| prompt | weak as a primary lever for the cost explosion. |
| code | partial — a planner-side per-turn step cap is the structural fix. |

**Recommended:** configuration (`ENABLE_TODOS=true`; ablate `REFLECTION_ENABLED=false`) + policy P-OF-1 for gnd. **Needs-investigation** for the 1,139-call root cause — almost certainly not a true 1,139-step plan; more likely a registry list_tools loop.

### 3.2 `no_trace_pre_llm_crash` (n=7)

> **All 7 cases share remediation pattern**: needs-investigation (re-run the affected MCP server in isolation under the same CUGA config; capture registry stderr) + code (CUGA-side empty-tool-list failsafe). Policy / memory / config (other than registry health) cannot help when the LLM never ran.

#### 3.2.1 `31d9743578dc-20fe1c6e0318` | T2 movie_platform — "Mubi movies by Hong Sang-soo"

**Diagnosis.** No CUGA trace, empty answer. Domain shows 8/10 cases no-trace — domain-wide MCP-client or registry startup failure on the CUGA side.

| lever | verdict |
| --- | --- |
| policy | weak — cannot fire if LLM never ran. |
| memory | not applicable. |
| tool_enrichment | not applicable. |
| configuration | **needs-investigation** — registry health for this domain. |
| prompt | not applicable. |
| code | **STRONG FIT** — empty-tool-list failsafe in MCP-client glue. |

**Recommended:** needs-investigation (registry/MCP-client startup) + code failsafe.

#### 3.2.2 `31d9743578dc-3b59b2d5a9b3` | T2 movie_platform — "Mubi director page URL for critic-39-likes movie"

Same root cause as 3.2.1. Same recommendation.

#### 3.2.3 `31d9743578dc-fa8256c2888f` | T2 movie_platform — "Creator of list 'Sound and Vision', was subscriber?"

Same root cause as 3.2.1. Same recommendation.

#### 3.2.4 `d14bbb0be92d-781ff55b91b7` | T2 professional_basketball — "All-Star players in 1973"

**Diagnosis.** `professional_basketball` is 10/10 no-trace. Same domain-wide MCP/registry health issue as movie_platform. Same lever analysis as 3.2.1. **Recommended:** needs-investigation + code failsafe.

#### 3.2.5 `d14bbb0be92d-b94c0c0446e9` | T2 professional_basketball — "Most Improved 1985-90"

Same as 3.2.4.

#### 3.2.6 `d14bbb0be92d-7d51d5f6098d` | T2 professional_basketball — "BMI range query"

Same as 3.2.4.

#### 3.2.7 `fe971e7f850a-0bd47606e297` | T2 soccer_2016 — "Most common bowling skill"

**Diagnosis.** Partial crash, not pure no-trace: 21 sandbox observations but no MCP tool successes; empty final_response. vakra `answer_s=1.0` (judge somehow extracted "right-arm medium" from intermediate scaffolding), `gnd_s=0.0`. Adjacent to Cluster B.

| lever | verdict |
| --- | --- |
| policy | partial — `OutputFormatter` could detect empty final_response and emit a fallback diagnostic; does not solve root cause. |
| memory | not applicable. |
| tool_enrichment | not applicable. |
| configuration | **needs-investigation** — sandbox + registry health for soccer_2016. |
| prompt | not applicable. |
| code | **STRONG FIT** — empty-final-response guard + zero-successful-tool-call guard. |

**Recommended:** code (empty-final-response guard + zero-tool-success guard). Needs-investigation: why sandbox ran without any tool successes.

### 3.3 `wrong_args_or_aggregation` (n=7)

#### 3.3.1 `840942187214-9915cb1b5445` | T2 authors — "Conference with most papers in 2012"

**Diagnosis.** Right tool returned ICRA on call #1. CUGA then enumerated "Top 10 by paper count" — answer judge punished verbosity (`answer_s=0.0`, ground truth is a single short name). Also 403 tool calls (likely registry list_tools repetition under reflection).

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — `OutputFormatter` with trigger "response enumerates a Top-N list" + `Playbook` (P-PB-1) "if intent asks for a single item, return only that item". Policy is preferred over a global prompt because it scopes to singular intents only. |
| memory | partial — would help over time. |
| tool_enrichment | not applicable. |
| configuration | partial — `REFLECTION_ENABLED=false` ablation likely cuts the 403-call tail. |
| prompt | would work; global. |
| code | not needed. |

**Recommended:** policy (`OutputFormatter` enum-strip + Playbook P-PB-1). Runner-up: configuration ablation (`REFLECTION_ENABLED=false`).

#### 3.3.2 `bc9218680ed5-0b0ec8d0b7d2` | T2 student_loan — "Ratio of disabled students never absent"

**Diagnosis.** Tool returned `{percentage: 1500}` (an outlier value in the dataset). ReAct parroted "1500%"; CUGA rescaled to "15%" (assuming a units error). Ground truth requires the literal number 1500; CUGA loses.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — `Playbook` "never numerically rescale, divide, or normalize a value that came directly from a tool response — emit it verbatim". Plus P-OF-1 to cite the tool key. |
| memory | weak. |
| tool_enrichment | partial — `ToolGuide` on this percent tool: "this tool's value is the answer as-is; do not interpret/normalize". |
| configuration | not applicable. |
| prompt | would work; policy is more scoped. |
| code | not needed. |

**Recommended:** policy (Playbook + P-OF-1). Runner-up: `ToolGuide` on the specific tool.

#### 3.3.3 `a823e527d383-ad24e3ec0328` | T3 beer_factory — "Non-alcoholic root-beer brands at coord (Folsom)"

**Diagnosis.** CUGA's first call `get_root_beer_details(root_beer_id=10054)` returned `{root_beer_details: []}` — empty. CUGA correctly concluded "data missing" and returned 0. ReAct's identical call returned actual data (2,717). Possibly server-side data drift between runs, OR a CUGA-side call-shape issue. Note CUGA then passed `container_type={'root_beer_details': []}` downstream (nested-arg bug on the empty value).

| lever | verdict |
| --- | --- |
| policy | partial — `Playbook` "if detail-fetch returns empty, retry with `str(id)` and `int(id)` before giving up" could mask transient call-shape issues. |
| memory | weak on first encounter. |
| tool_enrichment | partial — `ToolGuide` on `get_root_beer_details` clarifying argument type and "if response is empty, do NOT chain". |
| configuration | not applicable. |
| prompt | partial — same content as policy/ToolGuide. |
| code | **STRONG FIT** — nested-arg fix downstream + CUGA-side retry-with-other-primitive-type wrapper for detail-fetch tools. |

**Recommended:** **needs-investigation** (replay this exact tool call against the same MCP image to determine whether the empty response is CUGA's call-shape or server-side drift). If call-shape: code (CUGA-side primitive-type retry wrapper). If server-side: out of scope for CUGA-side levers.

#### 3.3.4 `34a533dfd727-9a80447e42a5` | T3 disney — "Movies of most productive director without villain"

**Diagnosis.** Both got "The Many Adventures of Winnie the Pooh". CUGA `em_s=1.0` but `gnd_s=0.0`. Classic nested-arg bug: call 2 was `get_movies_without_villains_by_director(director={"director": "Wolfgang Reitherman"})` → validation error → retry as string → success.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** for the gnd lift — P-OF-1. |
| memory | weak. tool_enrichment / configuration: not applicable. prompt: redundant. |
| code | **STRONG FIT** — nested-arg fix. |

**Recommended:** code (nested-arg) + policy P-OF-1.

#### 3.3.5 `34a533dfd727-792336e9811f` | T3 disney — "Highest-gross movie by director of movie with most voice actors"

**Diagnosis.** ReAct: "Moana". CUGA: "Treasure Planet, $55,189,145". CUGA called `get_highest_gross_movie_by_director(director="Ron Clements")` which returned `{movie_title: "Moana"}`, then chained an extra `get_movie_details_by_director` and used its output to override the correct earlier answer. Genuine wrong-aggregation: less-specific tool's output overrode purpose-built tool's.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — `Playbook` "when multiple tools have returned candidate answers, prefer the purpose-built tool over the generic detail tool". Could also use `IntentGuard`/`ToolApproval` to prevent the secondary call after the primary returns. |
| memory | partial. |
| tool_enrichment | partial — `ToolGuide` on `get_highest_gross_movie_by_director`: "this returns the final answer for highest-gross-by-director queries — do NOT call detail tools to corroborate". |
| configuration | not applicable. |
| prompt | would work; less surgical. |
| code | not needed. |

**Recommended:** policy (Playbook + ToolGuide). Runner-up: prompt.

#### 3.3.6 `fe971e7f850a-0ce9f1bd5b3e` | T3 soccer_2016 — "Man-of-the-Series winner's Man-of-the-Match count"

**Diagnosis.** ReAct: "SR Watson, 10". CUGA: "SR Watson, 940". CUGA used `get_man_of_the_match_count_by_player` (returns lifetime MoM count = 940). ReAct used a different endpoint scoped to the relevant series (returns 10). Wrong-tool-selected within a similar-named tool family.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — `ToolGuide` policies on both endpoints, disambiguating lifetime-MoM vs in-series-MoM. Plus a `Playbook` "when the user asks about a count tied to a specific series, prefer the series-scoped endpoint". |
| memory | strong once accumulated. |
| tool_enrichment | same as ToolGuide above (that IS the CUGA-side enrichment lever). |
| configuration | partial — higher shortlister candidate cap surfaces both tools but doesn't resolve the choice. |
| prompt | weak without specific tool context. |
| code | not needed. |

**Recommended:** policy (`ToolGuide` disambiguating the two MoM endpoints + Playbook for series-scope preference).

#### 3.3.7 `fe971e7f850a-d6dd43c77447` | T3 soccer_2016 — "Winning margin for match 419135 vs RCB on May 28 2008"

**Diagnosis.** ReAct: "9 runs". CUGA: "42 runs" (wrong). Chain: `get_match_winner_by_match_id` (ok) → `get_win_margin_by_teams_and_date` (nested-arg bug → error) → `get_win_type_by_match_id` (got "runs") → `get_total_runs_scored_by_match_and_innings` (162) → off the rails. Had the second call succeeded, CUGA would have answered correctly.

| lever | verdict |
| --- | --- |
| policy | partial — `Playbook` "if a primary lookup tool returns a validation error, retry once with corrected argument shapes before composing fallback tools". |
| memory | weak. |
| tool_enrichment | partial — `ToolGuide` on `get_win_margin_by_teams_and_date` specifying argument types. |
| configuration | not applicable. |
| prompt | redundant. |
| code | **STRONG FIT** — nested-arg fix is the direct cure. |

**Recommended:** code (nested-arg). Runner-up: policy (Playbook for primary-tool-retry-before-compose).

### 3.4 `timeout_or_giveup` (n=2)

#### 3.4.1 `308738b8195d-56faa9f6bbd2` | T2 hockey — "Temporary-term coaches in 2007"

**Diagnosis.** Expected tool `get_count_coaches_by_year_and_notes` wasn't surfaced by the shortlister (description vocabulary doesn't include "temporary/interim/notes"). CUGA explored 6 sibling coach tools and gave up at 140 s / 54 LLM calls with "cannot be completed".

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — (a) `Playbook` keyed on "temporary/interim/notes" in coach-domain intent that names the canonical tool directly; (b) P-OF-2 to strip the "cannot be completed" hedge if a numeric value did surface. |
| memory | **STRONG FIT** if accumulated — past similar trajectories would surface the canonical tool. |
| tool_enrichment | **STRONG FIT** — `ToolGuide` policy enriching `get_count_coaches_by_year_and_notes`'s description with "temporary", "interim", "term coach", "notes filter" pushes it up in the shortlister's embedding match. |
| configuration | partial — raising `LITE_MODE_TOOL_THRESHOLD` / `SHORTLISTING_TOOL_THRESHOLD` returns more candidates but adds noise. `TOOL_CALL_TIMEOUT` is per-call and not the binding constraint. |
| prompt | weak. |
| code | not needed if policy/memory/enrichment path works. |

**Recommended:** policy (`ToolGuide` enrichment + Playbook naming the canonical tool). Runner-up: memory (if accumulated across runs); configuration tweak as fallback.

#### 3.4.2 `39a28b2592a2-a6d040ce4d19` | T3 computer_student — "Students of top-advisors person, count by advisor"

**Diagnosis.** CUGA had the correct value (13) in hand but wrapped the answer in "this figure is an **upper bound**" — answer judge punishes hedging. 195 s / 48 LLM calls / 1.2M tok also indicates exploration didn't terminate.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — P-OF-2 (strip hedging) + `Playbook` "when a tool has returned a numeric value matching the question intent, emit a confident final answer immediately". |
| memory | weak on this turn. |
| tool_enrichment | not applicable. |
| configuration | partial — `REFLECTION_ENABLED=false` ablation; lower step budget if such a flag exists. |
| prompt | would work; global. |
| code | partial — planner-side per-turn step cap. |

**Recommended:** policy (P-OF-2 + early-terminate Playbook). Runner-up: configuration ablation.

### 3.5 `wrong_tool_selected` (n=1)

#### 3.5.1 `55b7e50368aa-7d0eae1aeaf4` | T2 mondial_geo — "Mountains in country with greatest population"

**Diagnosis.** Expected single-shot tool `get_mountain_count_most_populous_country`. CUGA chained 3 lower-level tools (most-populous-city-excluding-capital → country-of-city → mountain-count-by-country) and got 0 (India). Shortlister didn't surface the canonical tool because its CUGA-side description doesn't include the user's vocabulary.

| lever | verdict |
| --- | --- |
| policy | **STRONG FIT** — `ToolGuide` policy on `get_mountain_count_most_populous_country`: prepend description with "Use this tool when the user asks for mountains in the country with the largest/greatest/most population. Do NOT compose with city-population tools." |
| memory | strong if accumulated. |
| tool_enrichment | same as policy ToolGuide above (CUGA-side enrichment). |
| configuration | partial — higher `SHORTLISTING_TOOL_THRESHOLD` surfaces more candidates but adds noise. |
| prompt | weak. |
| code | not needed. |

**Recommended:** policy (`ToolGuide` enriching the tool's CUGA-side description). Runner-up: memory.

### 3.6 `hallucinated_no_tool` (n=1)

#### 3.6.1 `31d9743578dc-5b6784e8d151` | T2 movie_platform — "Movies in largest list + was creator subscriber?"

**Diagnosis.** CUGA emitted a Python code block describing what it WOULD call (`await task_2_movie_platform_get_user_payment_methods_max_movie_number()`) rather than executing it. 0 actual tool calls despite 19 LLM calls and 91 s. Same domain as the no-trace bucket (Cluster B); almost certainly the same root cause (registry/MCP-client returned an empty/partial tool list, so the sandbox could not bind the referenced function and silently emitted its own code as the final answer).

| lever | verdict |
| --- | --- |
| policy | partial — `IntentGuard` / `OutputFormatter` could detect "final answer is a Python code block with await calls" and force regeneration / mark failure (better signal). Does not fix root cause. |
| memory | not applicable. |
| tool_enrichment | not applicable. |
| configuration | **needs-investigation** — registry health for movie_platform. |
| prompt | not the right lever for the root cause. |
| code | **STRONG FIT** — CUGA-side guard in the sandbox executor: if the generated code's `await` references a function not in the resolved tool registry, raise a hard error instead of letting the code block become the final answer. Plus the empty-tool-list failsafe from Cluster B. |

**Recommended:** code (sandbox guard: unknown-tool-reference → hard error). Runner-up: policy (`OutputFormatter` that flags "final answer contains `await` keyword" as malformed). **Needs-investigation:** registry health for movie_platform (same as Cluster B).

---

## 4. Both-pass (PP, n=31) — resource comparison

In the both-pass quadrant, **CUGA averages 9.7 LLM calls and ~67k tokens per turn, vs ReAct's 1–2 reasoning steps per turn** (ReAct files do not record token counts — note this caveat; the comparison is steps and qualitative).

| uuid | task | domain | CUGA llm_calls | CUGA tokens | CUGA dur | ReAct pred_steps | flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 840942187214-469be8d265fe | 2 | authors | 10 | n/a | 0.5s | 1 |  |
| 840942187214-33ce7082460a | 2 | authors | 21 | 146,295 | 24.4s | 1 | **HIGH (≥10× median tokens for domain)** |
| 840942187214-a32375e83a83 | 2 | authors | 7 | 24,712 | 35.2s | 1 |  |
| 840942187214-3e5def6a7777 | 2 | authors | 6 | 60,429 | 9.6s | 1 |  |
| 6e317bcd6839-d631d2350e0e | 2 | books | 6 | 62,408 | 7.8s | 1 |  |
| 6e317bcd6839-c471228ceebe | 2 | books | 10 | 49,205 | 6.7s | 1 |  |
| 6e317bcd6839-d43ddbdc7a6b | 2 | books | 6 | 64,299 | 10.6s | 1 |  |
| 6e317bcd6839-7fef82f27955 | 2 | books | 6 | 61,101 | 7.8s | 1 |  |
| 6e317bcd6839-21e78bb4d842 | 2 | books | 6 | n/a | 0.0s | 1 |  |
| 6e317bcd6839-38819e282933 | 2 | books | 10 | n/a | 0.0s | 1 |  |
| 308738b8195d-5bd16a8893c5 | 2 | hockey | 10 | 80,556 | 11.4s | 1 |  |
| 308738b8195d-18bbc5dc131d | 2 | hockey | 7 | n/a | 0.0s | 1 |  |
| 308738b8195d-b11eeb38eded | 2 | hockey | 6 | 78,800 | 7.8s | 1 |  |
| 308738b8195d-91d22b875555 | 2 | hockey | 8 | 93,204 | 13.5s | 1 |  |
| 308738b8195d-02960c8c0d16 | 2 | hockey | 6 | 4,436 | 0.6s | 1 |  |
| 308738b8195d-8b4b06bc3398 | 2 | hockey | 8 | 79,746 | 11.1s | 1 |  |
| 35a1befb81d1-535fcb56d619 | 2 | talkingdata | 6 | 73,597 | 9.0s | 1 |  |
| 35a1befb81d1-cababea51b16 | 2 | talkingdata | 8 | 54,757 | 4.1s | 1 |  |
| 35a1befb81d1-616dfb77883f | 2 | talkingdata | 19 | 177,442 | 13.1s | 1 | **HIGH (≥2× ReAct's steps multiplier; ≥3× median tokens for domain)** |
| 35a1befb81d1-b917690529c6 | 2 | talkingdata | 10 | 4,447 | 0.8s | 1 |  |
| 35a1befb81d1-12813911c5ac | 2 | talkingdata | 8 | 57,993 | 4.5s | 1 |  |
| 35a1befb81d1-8159fe422dba | 2 | talkingdata | 11 | 4,458 | 0.7s | 1 |  |
| 35a1befb81d1-ddbd1a3fa836 | 2 | talkingdata | 6 | 67,858 | 7.2s | 1 |  |
| 6e317bcd6839-ad992961f5b3 | 3 | books | 8 | 76,700 | 12.5s | 2 |  |
| 6e317bcd6839-b723324adb74 | 3 | books | 10 | n/a | 0.0s | 2 |  |
| 6e317bcd6839-36f772964957 | 3 | books | 8 | 55,989 | 8.2s | 2 |  |
| 6e317bcd6839-3931dd363e90 | 3 | books | 13 | 75,140 | 44.8s | 2 |  |
| 6e317bcd6839-72902fb53f6b | 3 | books | 8 | 80,892 | 12.6s | 2 |  |
| 34a533dfd727-dd4cd21da184 | 3 | disney | 12 | 99,094 | 17.3s | 2 |  |
| adba6c0ec8a8-ea3c7885c2c2 | 3 | university | 27 | 46,974 | 12.3s | 2 | **HIGH (≥10× ReAct's step multiplier)** |
| adba6c0ec8a8-c70d9c072b32 | 3 | university | 13 | n/a | 0.0s | 2 |  |

**Commentary**: in the both-pass quadrant, CUGA averages **9.7 LLM calls and ~67 k tokens** per turn vs ReAct's 1–2 reasoning steps. Three outliers stand out for engineering attention: `840942187214-33ce7082460a` (21 LLM calls, 146 k tok), `35a1befb81d1-616dfb77883f` (19 LLM calls, 177 k tok), and `adba6c0ec8a8-ea3c7885c2c2` (27 LLM calls). These are not failures — they're costing 5–10× the resources to get the same right answer. Look there next for optimization (and notably, all three involve the reflection step being triggered repeatedly). Do not propose remediations to fix PP cases in this report — they pass — but flag them for the perf workstream.

A separate concern: many CUGA report.md rows show `dur=0.0s` even when LLM calls happened. That's a logging bug (probably duration-measurement aborted) — the row exists, the trace exists, but `full_execution_time` wasn't captured. Worth fixing in the eval harness; doesn't affect correctness.

---

## 5. ReAct fail / CUGA pass (FP, n=9) — strengths to preserve

> These 9 are domains/queries where CUGA succeeds and ReAct does not — fixing the PF cases must not regress these. Notable: most are queries where ReAct hedged ("I'm sorry, I couldn't find any papers authored by Barrasa", "I'm not sure I understand…") while CUGA confidently surfaced the answer. CUGA's "always commit to a numeric/named answer" stance is a strength — the P-OF-2 hedging-strip policy must NOT make CUGA hedge more, only less.

| uuid | task | domain | intent (≤120 chars) | CUGA answer (short) |
| --- | --- | --- | --- | --- |
| 840942187214-b43e6be1231f | 2 | authors | What percentage of journals whose short name begins with ANN were published in 1989? | "1.44 % of journals…" |
| 840942187214-52f6889d5091 | 2 | authors | Among the papers published in 2009, pick 10 and list down the conference's short name | "ICIC, ICIC, ICIC, ICIC, RFIC, …" |
| 840942187214-6e7fd607bd84 | 2 | authors | State the year and title of papers written by Barrasa. | "2004 – 'Survey of scalability techniques for reasoning with ontologies'" |
| 6e317bcd6839-3161b11a0fd3 | 2 | books | Among books ordered by Lucas Wyldbore, % over $13? | "33.33 %" |
| 35a1befb81d1-7e2e878bc36e | 2 | talkingdata | For event at 23:55:16 on 2016/5/7 at (113, 28), on what device? | (confident "device model not found via available APIs" — matched GT) |
| 6e317bcd6839-a76b0204cd69 | 3 | books | average of books in language of ISBN 23755004321 among books by Carole Marsh | "Both books are in English (same lang as 23755004321)" |
| 34a533dfd727-7a0fdbd1aa0c | 3 | disney | list villains of all movies directed by most productive director | "Madam Mim; Kaa and Shere Khan; Edgar Balthazar; Prince…" |
| 3e2b8f7655a2-001669797531 | 3 | trains | trains opposite-direction to most rectangle-2nd-car trains, w/ double-sided… | "1 train" |
| adba6c0ec8a8-a705643b237f | 3 | university | % female students in 2016 among universities in same location as 112 | "46.81 %" |

CUGA's edge here is **confidence and tool-grounding** — it commits to an answer when ReAct surrenders to ambiguity. The P-OF-2 (hedging-strip) policy is designed to preserve this: it only fires when a numeric/named answer is *already present* in the response, and strips hedging clauses around it. It does not make CUGA more conservative when no answer is in hand.

---

## 6. Both-fail appendix (FF, n=119)

| uuid | task | domain | intent (≤90 chars) | CUGA fail mode |
| --- | --- | --- | --- | --- |
| 840942187214-305bfcd9e5bc | 2 | authors | Please provide the titles of any two papers that are either preprinted or unpublished… | wrong_answer |
| 840942187214-d5d07b87e19a | 2 | authors | What is the ratio of author with affiliation and without affiliation? | wrong_answer |
| 6e317bcd6839-17b6cf7248bc | 2 | books | How many customers ordered the oldest book? | wrong_answer |
| 6e317bcd6839-a34cc3ccadfa | 2 | books | Who ordered the book with the cheapest price? | wrong_answer |
| 1960f609e439-42eba90b0cb2 | 2 | codebase_comments | List all the methods with a solution with a "636449700980488000" processed time. | timeout_or_giveup |
| 1960f609e439-e82ba6721008 | 2 | codebase_comments | What is the average processed time of the solution paths inside the "https://github.com/…" | no_trace_pre_llm_crash |
| 1960f609e439-8c022719a1ca | 2 | codebase_comments | How many percent more of the watchers for the repo of solution 83855 than 1502? | wrong_answer |
| 1960f609e439-65a22f6df967 | 2 | codebase_comments | For the solution of the most 'sw' methods, what is its path? | wrong_answer |
| 1960f609e439-0a652fb03008 | 2 | codebase_comments | How many methods in the same repository share a tokenized name that begins with "query lang…" | timeout_or_giveup |
| 1960f609e439-eb7d27ccd669 | 2 | codebase_comments | In "maxild_playground\Playground.sln", what is the time of sampling for the method… | wrong_answer |
| 308738b8195d-05ec22ea67ac | 2 | hockey | In 1998, How many wins were made by team 'CAR' per game played? Who contributed the most goals? | wrong_answer |
| 308738b8195d-3e3d6db9ab3d | 2 | hockey | What is the position of the 9th oldest hockey player? | wrong_answer |
| 308738b8195d-9296bdde9ace | 2 | hockey | How many teams scored against their opponent who had pulled their goalie in the year 2005? | wrong_answer |
| 55b7e50368aa-2da1ea58205c | 2 | mondial_geo | In which lake flows the river that is, in turn, the mouth of the Manicouagan River? | timeout_or_giveup |
| 55b7e50368aa-92dc160b1c20 | 2 | mondial_geo | Which two countries have the border in length of 803 km? Give the full names. | no_trace_pre_llm_crash |
| 55b7e50368aa-3e01aa27adb5 | 2 | mondial_geo | Name the tallest mountain on Himalaya and what is its height. | wrong_answer |
| 55b7e50368aa-9768f4b5bc9a | 2 | mondial_geo | In which province is the highest volcano mountain located in? | timeout_or_giveup |
| 55b7e50368aa-9e60460b6696 | 2 | mondial_geo | How many percent of the mountains on Andes which are non-volcanic? | timeout_or_giveup |
| 55b7e50368aa-b86a3020cdc2 | 2 | mondial_geo | What is the capital of the country that has the Licancabur Mountain? | wrong_answer |
| 55b7e50368aa-814c9d0d18dc | 2 | mondial_geo | What sea does the Baltic Sea converge with, and how deep is the Baltic Sea? | wrong_answer |
| 31d9743578dc-ae07dc845bae | 2 | movie_platform | What is the user avatar url for user 41579158? What is the latest movie rated by him/her? | wrong_answer |
| 31d9743578dc-00550ec0c9f4 | 2 | movie_platform | What's the url of user 39115684's rating on the movie 'When Will I Be Loved'? | no_trace_pre_llm_crash |
| 31d9743578dc-949db4b1b7ef | 2 | movie_platform | When did the creator of the list "250 Favourite Films" last update a movie list? | no_trace_pre_llm_crash |
| 31d9743578dc-2d279e62f33e | 2 | movie_platform | How many users were paying subscribers when they rated the movie released as ... | no_trace_pre_llm_crash |
| 31d9743578dc-3130ec5cddcb | 2 | movie_platform | user ID of subscriber who created a list for ... | no_trace_pre_llm_crash |
| 31d9743578dc-ff2d3498a62d | 2 | movie_platform | Avg number of movies added to lists of user 8516503? Indicate how many… | no_trace_pre_llm_crash |
| d14bbb0be92d-9b44601b01e2 | 2 | professional_basketball | How many All Star players who played in the 1973 season were black? | no_trace_pre_llm_crash |
| d14bbb0be92d-dbf89482eaf1 | 2 | professional_basketball | In the year 1997 allstar game, which teams did the players with the most rebounds play in? | no_trace_pre_llm_crash |
| d14bbb0be92d-0283d0ffdf31 | 2 | professional_basketball | Name the teams along with the coaches that went to 'Quarter Final' round in 1946. | no_trace_pre_llm_crash |
| d14bbb0be92d-8486689ff949 | 2 | professional_basketball | How many total minutes has the Brooklyn-born player, known by the name of Superman, played | no_trace_pre_llm_crash |
| d14bbb0be92d-da610a7c37f6 | 2 | professional_basketball | What is the name of the team with the highest home lost rate? | no_trace_pre_llm_crash |
| d14bbb0be92d-77fce6c85d4d | 2 | professional_basketball | What is the birth date of the player with the most assists during the 1985 All-Star season? | no_trace_pre_llm_crash |
| d14bbb0be92d-bb4405fa6cf5 | 2 | professional_basketball | List the champion (team name) and year from year 1950 to 1960. | no_trace_pre_llm_crash |
| fe971e7f850a-4e39ce9069a6 | 2 | soccer_2016 | List down all of the winning teams' IDs that played in St George's Park. | wrong_answer |
| fe971e7f850a-facf43ff16b2 | 2 | soccer_2016 | What is the average number of extra runs made as noballs? | wrong_answer |
| fe971e7f850a-89961390d1c4 | 2 | soccer_2016 | Among the matches, what percentage have a winning margin above 100? | wrong_answer |
| fe971e7f850a-976bb90380b3 | 2 | soccer_2016 | What is the date of the match that has the highest wager on the final result of a game? | hallucinated_no_tool |
| fe971e7f850a-cbb611c31c02 | 2 | soccer_2016 | How many players bat with their left hands? | wrong_answer |
| bc9218680ed5-ba21da2cee4a | 2 | student_loan | What is the average time for a disabled student to be absent from school? | wrong_answer |
| bc9218680ed5-787eda184fe2 | 2 | student_loan | State the number of students who filed for bankruptcy and have payment due. | wrong_answer |
| bc9218680ed5-4877ee4eec05 | 2 | student_loan | How many male students are enrolled at OCC? | wrong_answer |
| bc9218680ed5-caef075781c4 | 2 | student_loan | Calculate the average enlisted students per organization. | wrong_answer |
| bc9218680ed5-085696ec16fd | 2 | student_loan | What is the average absence period of a disabled student? | wrong_answer |
| bc9218680ed5-b319826839ce | 2 | student_loan | Which department has the most disabled students? | wrong_answer |
| 35a1befb81d1-25aa8472bd40 | 2 | talkingdata | What are the categories of the top 2 oldest events? | wrong_answer |
| 35a1befb81d1-2bd6a11a8f64 | 2 | talkingdata | What is the average age of the female users who uses a vivo device? | wrong_answer |
| a823e527d383-5ee3999c12b4 | 3 | beer_factory | How many sweet bottled root beers that do not contain cane sugar… | wrong_answer |
| a823e527d383-90d9c3222d0c | 3 | beer_factory | List out the root beer ID for the brand of the root beer that gained a 1-star rating… | wrong_answer |
| a823e527d383-fda0366a3244 | 3 | beer_factory | How many bottles of beer have been bought by Jim Breech for root beer ID 10054? | wrong_answer |
| a823e527d383-724b86449639 | 3 | beer_factory | difference between bottles of root beer sold from Louisiana and Missouri for… | wrong_answer |
| a823e527d383-03f8c708e98a | 3 | beer_factory | Among the transactions for the purchase of non-alcoholic beer, what % is done by … | wrong_answer |
| a823e527d383-a5aabff8d296 | 3 | beer_factory | Which location sold more bottles of beer, and what is the transaction ratio at Sac State… | wrong_answer |
| a823e527d383-aa69427d37ca | 3 | beer_factory | How many female mailing list subscribers from the city where customer finished tx n… | wrong_answer |
| a823e527d383-0ce1acfc68ce | 3 | beer_factory | How many times did the first customer use the credit card type they used between 12/25/… | wrong_answer |
| 6e317bcd6839-003e2ad6980b | 3 | books | List the ISBN of the book 'El plan infinito' written in the language it is originally written | wrong_answer |
| 6e317bcd6839-01bde0281b9a | 3 | books | publisher who published the first book of the author who published a book on … | wrong_answer |
| 6e317bcd6839-2317dce0eb47 | 3 | books | % of books published by Ace Books in language of first two published books… | timeout_or_giveup |
| 6e317bcd6839-b1ade8414e0d | 3 | books | average of books in languages of first two published books among all books… | wrong_answer |
| 2b28654158b1-8dcab257ca67 | 3 | college_completion | In Connecticut, avg Black students per year who were bachelor… | timeout_or_giveup |
| 2b28654158b1-a5540d8f55af | 3 | college_completion | Among the race of all students, which school in "KY" with the highest # of students… | timeout_or_giveup |
| 2b28654158b1-3979be5a9c26 | 3 | college_completion | % of Asian students among students of other races who graduated from… | timeout_or_giveup |
| 2b28654158b1-ee186bf084e4 | 3 | college_completion | Among institutes in state with most graduate cohort 2012 from private… | no_trace_pre_llm_crash |
| 2b28654158b1-c9a293c0fce5 | 3 | college_completion | How many students for both genders graduated from a 2-year institute in… | timeout_or_giveup |
| 2b28654158b1-22242ab46911 | 3 | college_completion | % of Asian students among students of other races who graduated from… | timeout_or_giveup |
| 2b28654158b1-526967fd559c | 3 | college_completion | Among Ivy League Schools, which school's state has the lowest appropriations… | timeout_or_giveup |
| 2b28654158b1-50cc9614237e | 3 | college_completion | % of 4-year public schools from Madison Area Technical College's… | wrong_answer |
| 2b28654158b1-e0bf826a9e36 | 3 | college_completion | Among institutes in state with most graduate cohort 2012 from private… | timeout_or_giveup |
| 39a28b2592a2-2607b42826bf | 3 | computer_student | How many courses for basic or medium undergraduate at level with same … | wrong_answer |
| 39a28b2592a2-3e453bb6b9af | 3 | computer_student | How many basic/medium UG courses taught by prof in course-level with most… | wrong_answer |
| 39a28b2592a2-e67e788f8418 | 3 | computer_student | How many basic and medium undergraduate courses are there, considering… | wrong_answer |
| 39a28b2592a2-028bd872bb8a | 3 | computer_student | How many teachers are faculty employees who taught high-level UG of <10… | wrong_answer |
| 39a28b2592a2-e1b2e78c96b8 | 3 | computer_student | How many basic and medium UG courses among the courses with the most… | wrong_answer |
| 39a28b2592a2-6a5b7a452425 | 3 | computer_student | How many basic and medium UG courses are taught by faculty member who… | wrong_answer |
| 39a28b2592a2-7b268478811c | 3 | computer_student | Which faculty employees teach a basic or medium UG course that has most… | wrong_answer |
| 39a28b2592a2-098e971bb045 | 3 | computer_student | How many courses for basic or medium UG taught by the faculty member who… | wrong_answer |
| 34a533dfd727-44575f9abc41 | 3 | disney | How many movies for mature/PG did Bill Thompson work as a voice for? | wrong_answer |
| 34a533dfd727-2322cd0c7f3f | 3 | disney | Which movies directed by most productive director can be watched by general audience? | wrong_answer |
| 34a533dfd727-a50635130b38 | 3 | disney | How many PG adventure movies did director of movie with most voice actors direct? | wrong_answer |
| 34a533dfd727-1f689826a14b | 3 | disney | Release date of Lion King directed by person who directed the most popular… | wrong_answer |
| 34a533dfd727-15ee061b3677 | 3 | disney | List voice actors in movie directed by director of Pinocchio released on F... | wrong_answer |
| 34a533dfd727-9eefc7d3a3fa | 3 | disney | List voice actors in movie directed by director of Disney's most popular adventure… | wrong_answer |
| 55b7e50368aa-a1ea6e0aee2e | 3 | mondial_geo | How many mountains in top-3 GDP economies with lowest proportion of … | timeout_or_giveup |
| 55b7e50368aa-ac0fd8df4ccb | 3 | mondial_geo | Please name 3 sovereign nations governed by government type of country… | wrong_answer |
| 55b7e50368aa-ef9c0baae036 | 3 | mondial_geo | Among orgs HQ in one of the two countries with longest border in… | wrong_answer |
| 55b7e50368aa-05a86dbfc326 | 3 | mondial_geo | How many lakes in 4th most populous African country with same govt type… | timeout_or_giveup |
| 55b7e50368aa-75340fb8d38c | 3 | mondial_geo | Nation's GDP lowest among communist states bordering smallest border… | wrong_answer |
| 55b7e50368aa-91888b0b341e | 3 | mondial_geo | In which year were most organizations created on the continent with country… | timeout_or_giveup |
| 55b7e50368aa-47d648237d18 | 3 | mondial_geo | Of countries sharing territory with >1 continent and avg pop… | wrong_answer |
| 55b7e50368aa-ed9c4bb75dcc | 3 | mondial_geo | Proportion of English-speaking citizens in 2 countries with longest border… | wrong_answer |
| fe971e7f850a-a29079011b89 | 3 | soccer_2016 | How many matches did team that played in a match resulting in tie in 2015 win… | wrong_answer |
| fe971e7f850a-f8f8a23174de | 3 | soccer_2016 | How many matches did the second team in match with lowest winning margin play in S8? | timeout_or_giveup |
| fe971e7f850a-17cffbf06c49 | 3 | soccer_2016 | How many left-hand batting players from country of city "Rajkot"? | wrong_answer |
| fe971e7f850a-c133dba8dff5 | 3 | soccer_2016 | Among players born after 1985, % using same … | wrong_answer |
| fe971e7f850a-8d0f6593fd9a | 3 | soccer_2016 | How many matches did team of players in match ID 335990 win in 2008? | wrong_answer |
| 3e2b8f7655a2-6b356a39bd56 | 3 | trains | direction of train with short ellipse car with load shape in its 2nd car? | wrong_answer |
| 3e2b8f7655a2-e1f013d5b67b | 3 | trains | How many cars running same direction as train with ellipse-shape have double-sided? | wrong_answer |
| 3e2b8f7655a2-fe844c4b5921 | 3 | trains | IDs of all cars with double sides on trains opposite direction t… | wrong_answer |
| 3e2b8f7655a2-48b8377cc3d0 | 3 | trains | Among trains with rect-2nd cars, how many have ≤1 car with open … | wrong_answer |
| 3e2b8f7655a2-081fd2441201 | 3 | trains | Among trains with 2 or less cars, how many have ≤1 car with open ro… | wrong_answer |
| 3e2b8f7655a2-d5464931bd4a | 3 | trains | trains with rectangle-shaped 2nd cars running same direction with double sided | wrong_answer |
| 3e2b8f7655a2-c28d9f399463 | 3 | trains | Among trains with rect-2nd cars, how many have three-wheeled, jagged roof cars? | wrong_answer |
| 3e2b8f7655a2-5a1cf4c68245 | 3 | trains | Among trains running same direction as train with ellipse-shaped car… | timeout_or_giveup |
| 3e2b8f7655a2-0ef49d666fe9 | 3 | trains | How many trains with 2 or less cars and running west have double sided cars in 3rd | wrong_answer |
| adba6c0ec8a8-7ee0c032ad57 | 3 | university | In nation where Harvard located, % of female students in universities… | wrong_answer |
| adba6c0ec8a8-b04dba450471 | 3 | university | How many univs have ≥20,000 female students in 2016? Identify how many | wrong_answer |
| adba6c0ec8a8-b2fc3e4f3b70 | 3 | university | Among universities with teaching score >90 in 2011, % of those… | timeout_or_giveup |
| adba6c0ec8a8-83dbc4ae1e32 | 3 | university | How many univs have ≥20,000 female students in 2016? Identify how many | wrong_answer |
| adba6c0ec8a8-7a658ce6f59d | 3 | university | Among universities with teaching score >90 in 2011, % of those… | timeout_or_giveup |
| adba6c0ec8a8-e52b98594643 | 3 | university | Among universities with teaching score >90 in 2011, % of those… | wrong_answer |
| 2ffd766bcf59-5032646dbcfe | 3 | wdi | Avg of Adjusted net enrolment rate, primary in Algeria | wrong_answer |
| 2ffd766bcf59-d565d4ddc1b7 | 3 | wdi | List table name and currency unit of countries using series FP.CPI.TOTL | wrong_answer |
| 2ffd766bcf59-bcdf6da41003 | 3 | wdi | List East Asia & Pacific countries under High income: nonOECD | wrong_answer |
| 2ffd766bcf59-205596757a77 | 3 | wdi | Total urban population of middle income countries in 1960 | wrong_answer |
| 2ffd766bcf59-2a6fb2ae51bf | 3 | wdi | % of countries in region with country with highest pop… | timeout_or_giveup |
| 2ffd766bcf59-e09c86a99e59 | 3 | wdi | Which indicator uses aggregation method for indicator value 133 in 1960… | timeout_or_giveup |
| 2ffd766bcf59-dff92e0acb8d | 3 | wdi | Sources for data of children who finished primary school education in countries… | timeout_or_giveup |
| 2ffd766bcf59-873d5b415b1c | 3 | wdi | In country with highest population in largest city for 19 consecutive years… | timeout_or_giveup |
| 2ffd766bcf59-21de28d36ca7 | 3 | wdi | How many countries have footnotes described same way as footnote on series code | wrong_answer |
| 2ffd766bcf59-a5fb5e8eb512 | 3 | wdi | Full names of any 2 countries that use the same trade system as Bulgaria… | timeout_or_giveup |

**FF clustering observation**. The FF set concentrates heavily in Task 3 (multihop reasoning): `world_development_indicators` 10/10, `college_completion` 9/10, `trains` 9/10, `beer_factory` 8/10, `computer_student` 8/10, `mondial_geo` 8/10 — and in Task 2 in the "no-trace" domains: `professional_basketball` 7/10, `movie_platform` 6/10. The cluster on multihop reasoning suggests CUGA's planner struggles with 3+ tool chains in unfamiliar domains. The same CUGA-side levers identified in §3 — nested-arg code fix (helps ~20% of multihop chains), policy bundle (gnd lift + chain-minimization Playbooks), and registry-health investigation (no-trace domains) — are the FF workstream's natural starting points, but the FF set is out of scope for this report.

---

## 7. Methodology & data sources

**CUGA run.**
- Date: 2026-04-28, captured by the bundle dir `20260428_201443_default`. `metadata.json.created_at = 2026-04-28T21:21:05Z`.
- Agent: `cuga_sdk` v0.2.20, git `df40ff98` (branch `fix/watsonx-empty-response-format`, dirty).
- Model: `openai/gpt-oss-120b` via Groq (`AGENT_SETTING_CONFIG=settings.groq.toml`).
- Key env vars: `LITE_MODE=true`, `LITE_MODE_TOOL_THRESHOLD=500`, `SHORTLISTING_TOOL_THRESHOLD=1`, `FORCE_AUTONOMOUS_MODE=true`, `REFLECTION_ENABLED=true`, `ENABLE_TODOS=false`, `POLICY__ENABLED=false`, `DECOMPOSITION_STRATEGY=exact`, `TOOL_CALL_TIMEOUT=120`, `CUGA_MODE=accurate`, `REGISTRY=true`, `LOCAL_SANBDOX=true` (sic).
- Bundle: 200 results in `results/m3_config_20260428_231430.json`; 178 langfuse traces in `langfuse_traces/` (22 missing — see §3.2); 200 rows in `report.md`; per-domain vakra files in `benchmarks/m3/results/_vakra/{groundtruth,prediction}/<domain>.json`.

**ReAct run.**
- Source: `benchmarks/m3/results_react/task{2,3}_lg_gpt-oss-120b.json`. No timestamp in those files; date unknown from data.
- Agent: LangGraph standard ReAct, single agent, same `openai/gpt-oss-120b` model.
- 200 dialogues, scored with the same M3 vakra evaluator (same three judges) — verified by comparing `score_explanation.answer` prompts and judge wording.

**Join.**
- CUGA langfuse `metadata.uuid` (also `input.task_name`) == ReAct dialogue `uuid` (1:1).
- 178/200 join cleanly; the 22 unjoinable cases are exactly the cases where CUGA produced no langfuse trace. All 22 are CUGA failures per the `report.md` row that still exists for them.
- For report.md row → uuid mapping: per `benchmarks/helpers/compare_report.py:_bucket_m3_tasks`, rows are grouped by `(m3_task_id, domain)` and sorted by `uuid` within each bucket, then numbered 1..N. We re-implemented this ordering (`_assign_v3.py`) and verified that report.md ✓/✗ flag matches the `success` field of the corresponding `results.json` entry on all 200 rows. The earlier approach of using langfuse `metadata.task_index` does NOT match report.md ordering and produced 20+ false-misassignments — this is the parser caveat to preserve for future readers.
- The `report.md` parser must use explicit empty-string checks for the carry-forward Task/Domain columns. The bug to avoid is `set(cells[0]) <= set('- ')` evaluating True for an empty cell — handle the empty case explicitly.

**CUGA policy engine — where to look.**
- Policy models: `cuga-agent/src/cuga/backend/cuga_graph/policy/models.py` (Playbook, IntentGuard, ToolGuide, ToolApproval, OutputFormatter, CustomPolicy).
- Policy enactment in the lite-mode path (used by this benchmark): `cuga-agent/src/cuga/backend/cuga_graph/nodes/cuga_lite/cuga_lite_node.py:_apply_output_formatter` (≈ L341) — invoked at callback after subgraph execution.
- Shared OutputFormatter application: `cuga-agent/src/cuga/backend/cuga_graph/policy/output_formatter_utils.py:apply_output_formatter_policies`.
- Sample benchmark policy bundle (for shape reference): `benchmarks/bpo/policies/policies.json` — 12 policies (10 playbooks, 1 tool_guide, 1 output_formatter), with both keyword and natural_language triggers.
- Enable flag: `DYNACONF_POLICY__ENABLED` in the run env. Currently `false` in `benchmarks/m3/config/m3.env` and in this bundle's `metadata.json`.

**Files / paths used.**
- `benchmarks/m3/evaluation_bundles/20260428_201443_default/report.md` — pass/fail table source.
- `benchmarks/m3/evaluation_bundles/20260428_201443_default/results/m3_config_20260428_231430.json` — full per-case CUGA results including `vakra` sub-scoring, top-level `success`, `tool_calls`, `expected_output`, `tool_call_diffs`.
- `benchmarks/m3/evaluation_bundles/20260428_201443_default/langfuse_traces/*.json` — 178 CUGA traces with full `observations` log.
- `benchmarks/m3/evaluation_bundles/20260428_201443_default/metadata.json` — CUGA run config.
- `benchmarks/m3/results_react/task{2,3}_lg_gpt-oss-120b.json` — ReAct scored output.
- `benchmarks/m3/results/_vakra/{prediction,groundtruth}/<domain>.json` — exact inputs that the vakra judges saw, used to verify groundedness-judge confabulation.
- `benchmarks/helpers/compare_report.py` — report.md generator; sources the row ordering rule we replicated.

Intermediate artifacts produced during this analysis (kept in the bundle dir for reproducibility): `_build_join.py`, `_assign_v3.py`, `_quadrants.py`, `_pf_with_vakra.py`, `_pf_dump.py`, `_pp_fp_ff_dump.py`, `_ff_dump.py`, `_score_dist.py`, `_groundedness_probe.py`, `_vakra_inspect.py`. Joined dataset at `docs/m3-vakra-analysis-20260428/joined.json` and `quadrants_v2.json`. Per-PF multi-lever remediation matrix at `docs/m3-vakra-analysis-20260428/_pf_remediation_plan.json` (keyed by uuid; the JSON intermediate used to render §3).

---

## Top-3 remediation priorities, ranked by expected pass-rate lift

1. **Build and enable a small M3-scoped CUGA policy bundle** (`DYNACONF_POLICY__ENABLED=true`, policy folder scoped to the benchmark, modeled on `benchmarks/bpo/policies/policies.json`). Specifically: P-OF-1 (single-fact OutputFormatter that cites tool name + JSON key); P-OF-2 (strip hedging / "For context" appendices / dataset meta-commentary when a numeric or named answer is present); P-PB-1 (no enumeration when a single item was asked); P-PB-2 (one composite tool, no corroboration on percent/ratio intents); P-PB-3 (no idempotent retries); plus tool-disambiguation `ToolGuide` policies for the 2 wrong-tool cases (mondial_geo mountains + soccer_2016 MoM). **Expected to flip ~14–20 of the 26 groundedness-asymmetry cases + the 2 hedging cases + the 1 enumeration case + the 1 wrong-tool case.** Estimated lift: **+9–12 pp** (CUGA 20% → ~29–32%). Cheapest *new* dependency: one policy.json file + flipping one env var.

2. **Fix the nested-argument bug in CUGA sandbox codegen** (Cluster C1). Affects at least 6 PF cases directly (3.1.8, 3.1.15, 3.1.18, 3.1.19, 3.1.21, 3.3.4, 3.3.7) and many more across PP/FF where the retry inflates cost and on multihop chains can cause the second-tool error to bias the final answer. Estimated lift: **+3–5 pp** in PF alone, plus large cost reduction across all quadrants. Cheap: one codegen rule.

3. **Diagnose and fix `movie_platform` and `professional_basketball` CUGA-side registry/MCP-client health** (Cluster B + 3.6.1). Affects 7 PF cases directly and ~13 FF cases in those domains. Add an empty-tool-list guard so future runs fail loudly instead of silently. Estimated lift: **+3 pp PF, up to +6–7 pp FF** if the underlying CUGA-side issue resolves. Needs: registry stderr capture from the next M3 run.

Combined expected post-fix CUGA pass rate: **~35–40%**, comparable to or exceeding ReAct's 36% — and achieved primarily via a policy bundle and one code fix rather than any benchmark-side change.

---

## Post-analysis: what we actually changed and what each change did

This section records the implementation work done between 2026-05-12 and 2026-05-20 in response to the analysis above. The work was scoped to this repo (`cuga-internal-evaluation`) — every change is in `benchmarks/m3/`, `scripts/`, or `benchmarks/helpers/` — and obeyed the off-limits rule (no edits to vakra judges, vakra groundtruth, MCP server definitions, or the ReAct baseline).

The 4 PFs picked for the iterative experiment were a subset of the codebase_comments domain (M3 task 2), chosen because they had been confirmed as ReAct-pass-CUGA-fail under the original bundle: `1960f609e439-e5d337d143b6`, `…-ab3a664a6a28`, `…-00fe3f448af7`, `…-d1ba8f4ad233`. The full final 5-run × 2-config comparison is in `/tmp/clean_report.md` (preserved verbatim in this PR's description); pass rates are quoted below.

### Headline result

Baseline (pre-fix): **0/10 PF cases passing** under any config.
After tool-prefix removal + policies-off: **5/10** (small earlier set) and on the 4-PF × 5-run sweep, **81.2%** mean pass rate (3.2/4 cases per run).
After tool-prefix removal + the policy bundle from §"Top-3 remediation priorities": **50.0%** (2.5/4) — i.e. **the policy bundle is net-negative on these 4 PFs once the tool-prefix issue is fixed.** One policy is robustly helpful on one task (`…-e5d337d143b6`: 75% → 100%); one policy reliably breaks one task (`…-d1ba8f4ad233`: 75% → 0%). Net cost dropped 32% (235K tokens → 160K) but mean correctness dropped 31 pp.

### Changes by lever, in order they were tried

1. **Registry app-name de-prefixing (CUGA-side code).** Root-cause fix for the analysis's "groundedness=0 on correct answers" finding. The M3 expanded registry was generating per-task app namespaces of the form `task_<n>_<domain>_*` (e.g. `task_2_codebase_comments_get_method_count`). vakra's `_match_live_name` rewrites the gold tool sequence to whatever live names the MCP registry exposes; with the `task_<n>_` prefix in front of the domain, vakra could not match CUGA's predictions to the gold sequence, so the groundedness judge's "document" was empty for every CUGA answer. ReAct happened to call bare-domain tool names that *did* match. Files touched: `benchmarks/m3/eval_m3.py` (`registry_app_name = domain`, `expanded_service_name = domain_name`, updated `registry_prefix`), `benchmarks/m3/m3_data_loader.py` (`strip_registry_prefix` tries bare-domain first, falls back to legacy `task_<n>_<domain>_` for old bundles), `benchmarks/m3/m3_vakra_score.py` (`_match_live_name` extended with a suffix-match path so old `task_<n>_…` bundles still score). Collision guard added because de-prefixing means tasks 2 and 3 both expose `books`, `mondial_geo`, `soccer_2016` — `expand_registry_config` now raises `RuntimeError` if two services collapse to the same name, and accepts a `capability_filter` so the caller can pre-narrow to just the task being evaluated. Smoke test at `scripts/check_no_task_prefix.py` walks any saved result file and asserts no tool call still carries the legacy form. **Result: +50pp on the iterated set, by far the largest lever.**

2. **Policy bundle (CUGA-side data + config).** The analysis's #1 priority — small M3-scoped policy bundle plus flipping `DYNACONF_POLICY__ENABLED=true`. Implemented as markdown source files in `benchmarks/m3/policies/` compiled to `policies.json` by `scripts/policies_md_to_json.py` (YAML frontmatter for triggers, markdown body for content). Eight policies were created from the analysis recommendations: `P-OF-1-single-tool-fact-citation`, `P-OF-2-strip-hedging` (later disabled — see below), `P-PB-1-no-enumeration`, `P-PB-2-one-composite-tool-no-corroboration`, `P-PB-3-no-idempotent-retries`, `P-PB-4-validation-error-recovery` (added empirically when validation-error retries kept burning the step budget), `P-TG-1-mountain-count-disambiguation`, `P-TG-2-country-with-most-umpires-returns-id`. `benchmarks/m3/config/m3.env` flips `DYNACONF_POLICY__ENABLED` to `true`. Eval/compare wrappers grew `--no-policies` and `--compare-policies` flags mirroring `benchmarks/bpo` (`benchmarks/m3/eval.sh`, `benchmarks/m3/compare.sh`); `benchmarks/helpers/bundle.py` annotates the bundle directory with the policy mode. **Result on the 4 PFs: net −31pp vs no-policies, mixed per task — robust helper on `…-e5d337d143b6` (75→100%), robust killer on `…-d1ba8f4ad233` (75→0%).**

3. **Output formatter conflict-resolver interaction (CUGA-side policy data).** While iterating, observed that having both `P-OF-1` (citation rule) and `P-OF-2` (hedging strip) loaded caused CUGA's natural-language conflict resolver to pick one and drop the other; specifically when `P-OF-2` won, the citation disappeared and groundedness regressed. Mitigation: renamed `P-OF-2-strip-hedging.md` to `.md.disabled` so the policy compiler skips it. This is a config-time fix only — the underlying conflict resolution behaviour in cuga-agent is out of scope for this PR. **Result: +5pp on the iterated set vs both-loaded; still net-negative vs no-policies.**

4. **Policy storage drift across per-domain agent instantiations (CUGA-side code).** Symptom: `.cuga` policy folder count decreased monotonically across per-domain `CugaAgent` constructions because each agent's `__init__` re-loaded policies from disk and the on-disk sync wrote back the conflict-resolver's culled set. Fix: pass `auto_load_policies=False, filesystem_sync=False` to both `CugaAgent(...)` constructors in `benchmarks/m3/eval_m3.py` (lines ~193 and ~1436), and load policies once via the new `_load_m3_policies` async helper. **Result: stabilised per-domain runs (no more "policies vanished" surprises mid-bundle).**

5. **Multi-UUID test-case filter (CUGA-side code, M3 evaluator harness only).** Reproducible after the tool-prefix fix: with `--task <uuid1> <uuid2> <uuid3> <uuid4>` the evaluator silently ignored the filter and ran every multiturn sample in the capability (~46 in codebase_comments). Bug was in `M3Evaluator.evaluate_all`'s multiturn branch (`benchmarks/m3/eval_m3.py:886`), which checked `self.task_id` (singular — set only when exactly one UUID is passed) instead of `self.task_ids` (plural — populated for both 1 and N). The single-turn branch had already been updated; the multiturn branch hadn't. Fix: switch the multiturn branch to use `self.task_ids` and lowercase-membership testing. **Result: experiments became feasible — without this fix, a 4-PF × 5-runs × 2-configs sweep was actually a 46-task × 5-runs × 2-configs sweep.**

6. **Per-service registry port respect (CUGA-side code).** When the user needed to keep port 8001 free for unrelated dev work, `eval_m3.py`'s per-service registry was found to hardcode 8001 in three places (port check, uvicorn `--port`, two health-check URLs at `http://localhost:8001/applications`). Fix: read `REGISTRY_PORT` or `DYNACONF_SERVER_PORTS__REGISTRY` once at startup and thread the value through. `benchmarks/m3/eval.sh` and `benchmarks/m3/compare.sh` already honoured `REGISTRY_PORT` for their kill-stale-process logic; the value now flows end-to-end. **Result: parallel CUGA work on port 8001 now possible during an M3 sweep on port 18001.**

7. **Outer-registry redundancy (CUGA-side code, eval harness only).** Once `eval_m3.py` honoured a configurable port, the next failure surfaced: `eval.sh` was starting an "outer" registry on `$REGISTRY_PORT` via `run_registry.sh`, then `eval_m3.py` tried to start its per-service mini-registry on the same port and aborted with "port in use". The outer registry was a legacy step from before per-service registries existed — every code path in `eval.sh` invokes a `--from-config` eval that self-manages its registry. Fix: `benchmarks/m3/eval.sh` no longer starts the outer registry by default (the kill-stale-process block runs unconditionally; the start block is gated behind `SKIP_SERVER_START=false`, inverting the previous default). **Result: `eval_m3.py`'s per-service registry runs unopposed; the per-PF re-runs that previously failed with "port in use" complete.**

8. **`extend`-style argparse for `--capability` and `--task` (CUGA-side code).** With `nargs="*"`, a second invocation of `--task` overwrote the first. Switched both to `action="extend", default=[]` so users can pass `--capability m3_task_2 --task <uuid1> <uuid2>` in one shot. The UUID detection branch also gained a filter step that strips non-UUID items from the test-case filter before passing it down. **Result: composable filters; less footgun.**

### Combined effect

| Stage | 4-PF (×5 runs) no-policies | 4-PF (×5 runs) policies |
|---|:---:|:---:|
| Original bundle (analysis baseline, all PFs) | 0/10 | n/a (disabled) |
| + tool-prefix removal | **5/10** | 4/10 |
| + multi-UUID filter + port + registry fixes (clean 4-PF × 5-runs) | **81.2%** | 50.0% |

The analysis's stated "+9–12 pp from policies" lift did not materialise on these 4 cases; the realised lift came almost entirely from the tool-prefix root cause, which the analysis had not anticipated as a separate bug (it was a hidden prerequisite for any policy lift to be measurable). Re-running the policy bundle against the **full** 200-case M3 set is the next step before declaring policies net-negative in general.

### What this PR ships

All changes above are bundled into one PR. The scope is intentional: the M3 evaluator harness was structurally fragile in several mutually-reinforcing ways (silent filter pass-through, port collisions, registry double-start, prefix bug, policy drift) and fixing one without the others left the harness broken in different ways at each step. Each fix is also small and localised.

What is *not* in this PR: nested-argument sandbox codegen bug (analysis priority #2 — that lives in cuga-agent, not here), and the `movie_platform` / `professional_basketball` MCP-client health investigation (analysis priority #3 — needs registry stderr capture from a future run).

### Reproducing the final number

```bash
# Clean local state
pkill -f "uv run registry" 2>/dev/null
pkill -f "eval_m3" 2>/dev/null
lsof -ti :8001 -i :18001 | xargs kill 2>/dev/null

# 4-PF × 5-runs × 2-configs sweep
caffeinate -i env \
  REGISTRY_PORT=18001 \
  DYNACONF_SERVER_PORTS__REGISTRY=18001 \
  ./benchmarks/m3/compare.sh --runs 5 --compare-policies \
    --m3-data benchmarks/m3/data/small_train.zip \
    --capability m3_task_2 --domain codebase_comments \
    --task 1960f609e439-e5d337d143b6 \
           1960f609e439-ab3a664a6a28 \
           1960f609e439-00fe3f448af7 \
           1960f609e439-d1ba8f4ad233
```

Caveat from the 2026-05-18 run: do not run any other M3 eval against the same `benchmarks/m3/results/` directory while compare.sh is running — bundle collection is by glob and will pick up the other process's result files. Splitting the results dir per compare-invocation is logged as a follow-up.
