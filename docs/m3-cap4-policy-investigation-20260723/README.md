# M3 capability_4 investigation — full record

**Status:** living document, investigation in progress as of 2026-07-23. Deadline for cap4 results: 2026-07-24.
**Repos involved:** `cuga-eval` (this repo, branch `integration/m3-eval`) and `cuga-agent` (sibling repo, same branch).
**Purpose of this doc:** a complete record of what was investigated, decided, built, and tested — written specifically so prototype/uncommitted/stashed code can be told apart from real, ready-to-commit fixes before anything gets swept into a PR. Individual threads below are candidates for separate GitHub issues later; this doc is the source material for writing those, not a replacement for them.

> **Scope note**, borrowed from the earlier `docs/m3-vakra-analysis-20260428/` investigation in this repo: the vakra evaluator (judges + aggregation), the benchmark groundtruth, and the upstream MCP tool definitions are off-limits as remediation levers. That applies with extra force to `benchmarks/m3/evaluator/policy_judge.py` specifically — see §5, this was hit directly during this investigation.

---

## 0. Status snapshot: what's real vs prototype, right now

| # | Item | Repo | State | Committable? |
|---|---|---|---|---|
| 1 | ToolGuide enrichment ordering-bug fix (`prepare_node.py`) | cuga-agent | Uncommitted, working tree | **Yes** — verified via trajectory inspection (§2.1), real bug, no gate |
| 2 | Native per-task ToolGuide policy mechanism (replaces `user_context` prompt-stuffing) | cuga-eval `eval_m3.py` | Uncommitted, working tree | **Yes** — direct answer to "make CUGA's own policy engine work" |
| 3 | GroundednessJudge input-truncation crash fix | cuga-eval `evaluator/judge.py` | Uncommitted, working tree | **Yes** — user explicitly approved ("it's general, leave as is"), verified live |
| 4 | `CorrectnessJudge` exception-message bug fix (`{e}` → `f"...{e}"`) | cuga-eval `evaluator/judge.py` | Uncommitted, working tree | **Yes** — trivial, unrelated pre-existing bug fixed in passing |
| 5 | `--registry-port` / `find_free_port()` / Langfuse background-download resumability (`schedule_langfuse_download_for_results`/`await_pending_langfuse_downloads`) | cuga-eval `eval_m3.py`, `benchmarks/helpers/bundle.py`, `m3_vakra_score.py` | **Applied to working tree** (2026-07-23, later session) via `git apply` from cuga-eval `stash@{0}`, file-by-file (`eval_config.toml`'s hunk skipped — pure no-op, deletes an already-absent block). Verified: `py_compile` clean on all 3 touched files, `pytest benchmarks/m3/tests/` → 95 passed, 2 skipped (unrelated), 0 failed. **Stash NOT dropped** — still present as `stash@{0}` in cuga-eval, kept as a fallback until this is validated live. | **Yes for the code itself** — but still needs a real eval run to confirm `--registry-port`/Langfuse resumability behave correctly outside unit tests, not just that they compile and don't break existing tests. Worker-pool scheduler (actual parallel execution) still not built — this only lays the groundwork (§7) |
| 6 | ToolGuide/groundedness/runaway probe eval-keys | cuga-eval `eval_config.toml` | Uncommitted, working tree | **Yes** — pure test infra, no behavior change |
| 7 | Change #1 groundedness rider (`M3_GROUNDEDNESS_INSTRUCTIONS`) | cuga-eval `eval_m3.py` | Uncommitted, **on by default** | Predates this session's later changes; part of the working tree diff |
| 8 | Change #1b trim rule (`M3_GROUNDEDNESS_TRIM_RULE`) | cuga-eval `eval_m3.py` | Uncommitted, **off by default** (`M3_GROUNDEDNESS_TRIM`) | Built, status of independent testing not confirmed in this doc's authoring session — verify before relying on it |
| 9 | Change #2 claim-verification rider (`M3_GROUNDEDNESS_CLAIM_RULE`) | cuga-eval `eval_m3.py` | Uncommitted, **off by default** (`M3_GROUNDEDNESS_CLAIM_CHECK`) | Previously tested only bundled with #10 (10/15, 66.7%). **Isolated 3-run test in progress** (2026-07-23, later session) against `cars` (`1f58b1e965af-03bc27917845`) with #19/#20 also enabled, to finally separate its contribution — see live run, not yet concluded as of this doc edit |
| 10 | `P-OF-3-groundedness-claim-verification.md` output-formatter policy | cuga-eval `benchmarks/m3/policies/` | Untracked file | Tested bundled with #9 — 10/15 (66.7%) vs 0/3 baseline (§3) |
| 11 | Change #3 extractive-construction rider (`M3_GROUNDEDNESS_EXTRACTIVE_RULE`) | cuga-eval `eval_m3.py` | Uncommitted, **off by default** (`M3_GROUNDEDNESS_EXTRACTIVE`) | **Never run, zero evidence** — pure prototype |
| 12 | `policy_judge.py` (`PolicyAdherenceJudge`) | cuga-eval `evaluator/` | Untracked file | **DO NOT EDIT — see §5.** User stopped an in-progress edit mid-session (2026-07-23): *"i am not allowed to change the judge!"* Treat as a fixed evaluation criterion, full stop — not just "origin unclear" |
| 13 | ToolApproval as an enforcement mechanism | cuga-agent | Investigated only, **no code written** | Ruled out (§6.1) — do not build |
| 14 | Full `ToolGuardRuntime`/`ToolGuardManager` integration | cuga-agent + cuga-eval | Investigated only, **no code written** | Ruled impractical for the 2026-07-24 deadline (§6.2) — needs LLM buildtime step + `RuntimeDomain` file generation |
| 15 | `RetrieverPolicyGuard` ("ToolGuard-lite", hand-written enforcement) | cuga-agent + cuga-eval | **Implemented, uncommitted, validated live.** New file `cuga-agent/.../tracking/policy_guard.py`; wired into `local_executor.py`, `registry.py`, `combined.py`, `code_executor.py` (cuga-agent) and `sdk_eval_helpers.py`, `eval_m3.py` (cuga-eval). Confirmed firing on a real attempted violation in a live eval run (2026-07-23): `professional_basketball`'s retriever tool was blocked with `{'blocked_by_policy': True}` when the model tried it against a retriever-forbidden policy, and the model correctly recovered and continued with legitimate tools. | **Yes** — real bug-catching behavior confirmed under live conditions, not just smoke tests |
| 16 | `TaskToolCallHistory` (runaway/repetition annotator) | cuga-agent | **Stashed** (`stash@{0}` in cuga-agent, message: `"TaskToolCallHistory prototype (design b'):..."`) | **No** — explicitly stashed pending `compare.sh` signal. Full writeup already exists: `cuga-agent/docs/issues/task-tool-call-history-contextvar-isolation.md` (committed, `81cb1714`) — not duplicated here, see §4 |
| 17 | `BlockToolCallBudget` removal | cuga-agent | Not started | Out of scope for this investigation — belongs to PR #493's review thread, not this exercise (noted only because #16 exists as its replacement) |
| 18 | Earlier `m3-cap4-fixes-after-training` stash (Langfuse resumability, an earlier registry-port/policy-judge-path attempt, subprocess-parallelization groundwork) | cuga-eval | **Superseded by #5** (2026-07-23, later session) — the Langfuse/registry-port portions were applied to the working tree via `git apply`; the `policy_judge_path` and `eval_config.toml` cleanup portions were superseded independently. Stash itself left in place, not dropped. | Partially resolved — see #5 |
| 19 | `find_tools` query-phrasing rider (`M3_FIND_TOOLS_QUERY_RULE`) | cuga-eval `eval_m3.py` | Uncommitted, **off by default** (`M3_FIND_TOOLS_QUERY_RIDER`) | **Tested, working with caveats.** Built after discovering catalog-size did NOT correlate with pass rate across the full cap4-300 dataset (r≈0, 300 tasks) — ruling out a catalog-size-gated design. Alone: fixed tool-discovery misses (found the right tool on the very first `find_tools` call in 2 real runs) but its "if find_tools returns little, try again" clause can send the model hunting for tools that don't exist, ballooning cost (40 LLM calls / 1.23M tokens / 595.7s on one solo test, vs. ~9-16 calls baseline) |
| 20 | Parameter-variation retry rider (`M3_PARAMETER_VARIATION_RULE`) | cuga-eval `eval_m3.py` | Uncommitted, **off by default** (`M3_PARAMETER_VARIATION_RIDER`) | **Tested combined with #19, strong result.** 3-run compare on `professional_basketball`'s hardest task (`d14bbb0be92d-d09ad3135cea`): 2/3 pass (up from 20% single-task baseline), avg tokens -55%, avg LLM calls -44%, avg duration -48% vs. the pre-rider 5-run baseline. Single run on the full 3-task ToolGuide probe set: 3/3. Combined 6-task read (ToolGuide set + groundedness set): 5/6, with the 1 miss (`cars`) being an unrelated groundedness/fabrication failure, not a discovery or parameter-guessing failure. The 1/3 miss on the `professional_basketball`-alone compare was a pure `find_tools` retrieval miss (11 failed search queries, including a near-identical first query to the runs that succeeded) — confirms `find_tools`'s underlying LLM shortlister has real sampling variance neither rider fully removes |

---

## 1. Starting point: two judges, one langgraph baseline

Set up `.scratch/cap4-analysis/` (gitignored) with two downloaded result JSONs and the expanded `benchmarks/m3/evaluation_bundles/cap4-300.zip` bundle, then compared three scorings of the same 300-task capability_4 set: CUGA's own `report.md` self-scoring, the "proper" VAKRA judge scoring, and a langgraph ReAct baseline run on the identical 300 tasks.

**Findings that set the whole investigation's direction:**
- CUGA's self-reported score and the VAKRA judge score disagreed materially on the same trajectories. Decision: **trust VAKRA**, since that's what the official evaluator actually runs.
- langgraph beat CUGA on the same 300 tasks, and the gap concentrated specifically in **policy compliance** (the `additional_instructions` retriever-usage rule), not general task competence.

This framed everything downstream as two parallel tracks: (a) make CUGA's policy-following actually work (§2), and (b) close CUGA's groundedness/fabrication gap, which turned out to be entangled with (a) — see the cross-reference at the end of §3.

---

## 2. Policy compliance track (ToolGuide)

### 2.1 The ordering bug and its fix — REAL, verified, uncommitted

Before touching anything, checked whether CUGA's own native policy engine (`ToolGuide`, universal/`AlwaysTrigger`-style trigger) worked at all, rather than accepting the ad-hoc `additional_instructions` → `user_context` prompt-stuffing the harness used previously. Switched `eval_m3.py`'s `evaluate_multiturn_task` to call `agent.policies.add_tool_guide(name=f"cap4_policy_{sample_id}", content=policy_text, target_tools=["*"], target_apps=[domain])` immediately before each task's invocation, and `agent.policies.delete(policy_id)` in a `finally` block right after — see `benchmarks/m3/eval_m3.py:928-1025`. `ToolGuide`'s default (no explicit triggers) resolves to an always-match trigger, so this applies unconditionally for exactly that one task's lifetime.

This surfaced a **real bug** in cuga-agent's `src/cuga/backend/cuga_graph/nodes/cuga_lite/adapter/prepare_node.py`: tool-guide enrichment was applied to `tools_for_execution` too late in some code paths, so the LLM's own tool list sometimes never carried the guide text at all — the retriever-only/retriever-forbidden instruction was silently absent from what the model actually saw. Fixed with two parts:
1. Early enrichment of `tools_for_execution` (and `app_to_tools_map`) right after it's assembled, gated on `state.cuga_lite_metadata` actually carrying guide content.
2. A guard against double-enriching `tools_for_prompt` later in the same function, only re-enriching when `enable_find_tools` is true (i.e. when `tools_for_prompt` is a genuinely separate object from `tools_for_execution`, not an alias).

Verified via direct trajectory inspection: the retriever tool's own description now correctly shows the domain-specific guide text where before the fix it did not.

**This fix is the direct answer to "how do we improve score on policy-failing tasks."** It's real, it's isolated to `prepare_node.py`, and it is ready to commit — the only reason it hasn't been is that no commit has been requested yet in either repo this session.

### 2.2 At-scale evidence the fix isn't sufficient alone

Single-run test on the `professional_basketball` ToolGuide probe (`d14bbb0be92d-d09ad3135cea`) flipped to a clean pass after the fix. Per the standing rule in this investigation (never trust a single run — always follow with `compare.sh --runs 5`), the 5-run compare came back **0/5**. Deep trajectory analysis across those 5 runs showed the fix *was* doing real work — 3 of 5 runs correctly avoided the forbidden retriever tool entirely, a genuine compliance improvement the ordering fix enabled — but all 5 still failed, even the 3 compliant ones, because that specific task's remaining bottleneck is parameter-search persistence (getting the exact right query against the retriever), a different problem the ToolGuide fix was never meant to solve.

**Conclusion:** the fix measurably improves policy compliance but is not, by itself, sufficient to move Pass@1 on tasks whose failure mode is downstream of compliance (e.g. parameter search). This is what motivated investigating enforcement mechanisms (§6) as a follow-on, rather than treating §2.1 as case-closed.

### 2.3 The real scale of the problem (offline `policy_judge.py` analysis, see §5)

Offline analysis against the real `20260722_131115` cap4-300 run, using `PolicyAdherenceJudge` (§5) as a diagnostic (not as a live scoring gate in that run):
- **150/300 tasks carry a policy** (all a variant of one binary rule — see §5.2).
- **112/150 (75%) have a detectable violation.**
- **72/150 (48%) both violate and fail overall.**
- 40/150 violate but the task still passed overall anyway (meaning the judge was not a live gate for that run).
- Of those 72 violate-and-fail tasks, the violation is overwhelmingly one-directional: **71/72 are "policy said retriever-only, agent used something else"**; only 1/72 is the reverse direction. Avoiding a forbidden tool type is easy discipline for the model; restricting itself to *only* one tool type when others look obviously useful is the hard discipline it's actually failing at.
- Separately (§3, Change #2's design comment): **55 of those same 72 policy-related failures fail specifically on the groundedness judge**, not on tool selection/exactmatch — meaning the groundedness track (§3) and the compliance-enforcement track (§6) are attacking overlapping parts of the same 72-task pool from different angles, and groundedness fixes may already be covering more of it than compliance enforcement alone would.

---

## 3. Groundedness / fabrication track

A separate but overlapping thread: groundedness failures kept surfacing independent of policy compliance.

**Judge-side crash fix (REAL, §0 item 3):** `GroundednessJudge.judge()` crashed on long tool outputs (context overflow). The user explicitly decided this belongs in the judge itself, not pushed to the caller ("it's general, leave as is") — fixed via input truncation directly in `benchmarks/m3/evaluator/judge.py` (`M3_GROUNDEDNESS_JUDGE_MAX_CHARS` env, default 100000 chars, truncates tool-response text from the tail and predicted-answer text from the head). Verified live: a previously-crashing task (cars domain) flipped to a clean pass.

**Agent-side riders**, all independently toggleable (default-off except #1, following the file's existing A/B convention), composed in `_build_m3_special_instructions()`:

- **Change #1** (`M3_GROUNDEDNESS_INSTRUCTIONS`, `eval_m3.py:137-164`, on by default) — the base evidence-chain rider: state values exactly as returned, show a one-line evidence chain for multi-hop answers, never claim a tool "cannot"/"lacks" something. Predates the later changes below; already part of the working tree.
- **Change #1b** (`M3_GROUNDEDNESS_TRIM_RULE`, rule 8, off by default via `M3_GROUNDEDNESS_TRIM`) — don't restate the question's own selection criteria as asserted fact when a single tool encapsulated the derivation.
- **Change #2** (`M3_GROUNDEDNESS_CLAIM_RULE`, rules 9-11, off by default via `M3_GROUNDEDNESS_CLAIM_CHECK`) — mined directly from cap4-300's real judge explanations (per the code comment, 55/72 of the policy-related failures fail here): don't assert an attribute/category a tool response never returned; don't call a list "complete/exhaustive" unless nothing indicates otherwise; never state a fact that wasn't in any tool response, even if true/common knowledge.
- **`P-OF-3-groundedness-claim-verification.md`** (untracked policy file, output-formatter type) — companion to Change #2. Built around a hard constraint: the markdown output formatter's own enactment code hardcodes "preserve all facts, don't remove details," so P-OF-3 asks for caveats/annotations on unverified claims rather than deleting content.
- **Change #3** (`M3_GROUNDEDNESS_EXTRACTIVE_RULE`, rules 12-13, off by default via `M3_GROUNDEDNESS_EXTRACTIVE`) — attacks fabrication at construction time instead of catching it after the fact: for list/attribute-style answers, requires the model's last code step to build the answer as a Python variable pulled only from actual tool-response fields, `print()` it, then have the final NL answer just restate what was printed. **Built, never run — zero evidence either way.**

**Evidence so far:** 5-run compare on the groundedness probes with **Change #2 + P-OF-3 together**: 10/15 (66.7%), up from 0/3 baseline. Real improvement, but the two mechanisms were tested as a bundle — individual contribution of each is not isolated. Change #1b and Change #3 have no compare.sh evidence at all yet.

---

## 4. Runaway / repetition track — see the cuga-agent doc, not duplicated here

Full investigation, two distinct LangGraph contextvar-scoping bugs found and fixed, and the working `(b′)` design are documented in detail in **`cuga-agent/docs/issues/task-tool-call-history-contextvar-isolation.md`** (committed at `81cb1714`). Summary for cross-reference only:

- Motivated by 36/300 cap4-300 tasks hitting the step limit; PR cuga-agent#493 (merged) only fixes one specific runaway shape (sandbox-timeout blind retry) that doesn't match capability_4's actual failures (distributed, individually-fast repeated calls across many blocks).
- User's binding design constraints: general (not cap4-specific), **never cache tool results** (only observe+annotate; confirmed real side-effecting tools exist elsewhere in the M3 catalog), purely observational (never block/abort), no regex matching.
- `TaskToolCallHistory`: tracks distinct tool+arg combinations per task, injects a soft note into sandbox output on exact repeats or 3+ distinct argument variations for the same tool.
- Two real bugs found and fixed: (1) `reset()`/`record_call()` ran in different LangGraph node dispatches, invisible to each other because every dispatch gets its own `copy_context()`; (2) even after fixing (1), *every* dispatch of the *same* node is independently context-copied, so **no placement of pure-contextvar state can survive across code blocks at all** — this is structural to LangGraph's Pregel runner, not a bug in usage.
- Working fix: `(b′)` — a contextvar carries only a stable per-task key (`thread_id`), freshly rebound every dispatch; the actual accumulating state lives in an ordinary module-level dict keyed by that id.
- **Status: plumbing confirmed working** (notes fire in all 4 `cap4_runaway_probe` tasks, verified against full untruncated trajectory JSON). **Whether the notes change outcomes is still unknown** — one `law_episode` PASS is not proof of causation (tool-call count in that run was still 675, the mechanism visibly didn't stop the loop). Code is stashed (`stash@{0}` in cuga-agent) pending `compare.sh --runs 5` on `cap4_runaway_probe_n4`/`_n3`.

**This session's decision (explicit user instruction):** the `RetrieverPolicyGuard` work in §6.3 must **not** depend on or un-stash this — build independent, minimal key-threading instead, so policy-enforcement's fate isn't tied to an unvalidated prototype.

---

## 5. Policy judge (measurement) track — `policy_judge.py`

### 5.1 Hard constraint: this file must never be edited

Mid-session, the user stopped an in-progress edit: *"i am not allowed to change the judge!"* No code had been written yet at that point (only read/analysis), so nothing needed reverting. This is now a standing rule (also saved to persistent memory, `feedback_policy_judge_immutable.md`): `benchmarks/m3/evaluator/policy_judge.py` defines the pass/fail criterion itself, not agent behavior, and must be treated as read-only — analogous to not being allowed to edit an exam's grading key. If its logic looks fragile or improvable, that's information to relay, never something to patch unilaterally.

### 5.2 What it actually is and does

`PolicyAdherenceJudge.judge()` — a deterministic, non-LLM judge. When wired in via `--policy-judge-path` and `"multiturn" in capability`, `scorer.py:112-133` treats a 0.0 score as a **hard gate**: the entire task score becomes 0.0 before exactmatch/answer/groundedness are even computed.

Detection logic: requires the domain's mapped topic-group name (from a hardcoded `DOMAIN_MAPPING` table, ~87 domains) to literally appear as a substring of `additional_instructions`, AND one of two directive substrings ("do not use document retrievers" / "only using document retrievers"); falls back to two exact global strings for the non-domain-scoped phrasing. Retriever-tool identification is `"query_" in tool["name"]`.

**Checked (not assumed) whether policy-type coverage was a gap:** pulled all 21 distinct `additional_instructions` strings that actually occur across the real dataset (`.scratch/cap4-analysis/dataset/capability_4_multiturn_policy_sampled/input/*.json`). Every one of the 150 policy-bearing tasks is a variant of exactly one binary rule (retriever-only-required vs. retriever-forbidden, phrased either globally — 66/150 — or per domain-group — 84/150). The judge's phrase list covers all 21/21. **This ruled out an initial hypothesis** that other policy shapes (enumeration, corroboration, idempotent-retry rules — from the now-deleted `P-PB-*`/`P-TG-*` policy files, which were this session's own harness-side ToolGuide experiments, not part of the dataset's real `additional_instructions` field) needed separate coverage. They don't; there's only the one rule.

**Checked retriever-name detection against real trace data:** confirmed capability_4's retriever tools consistently follow `{app}_query_{domain}` naming, and the leaf tool name is what actually gets logged (not hidden behind CUGA's `find_tools` shortlisting indirection). No live counterexample found — this is a naming-convention dependency, not a demonstrated bug, worth hardening someday but not urgent.

### 5.3 Improvement ideas that were proposed, then withdrawn per §5.1

Two concrete robustness fixes were designed (phrasing-drift resilience via keyword-only detection instead of nested exact-substring matching; an audit signal distinguishing "compliant" from "policy present but unrecognized") — **neither was implemented**, per the "never edit the judge" rule. If robustness genuinely matters, the fix belongs on the agent side (make CUGA's tool choices satisfy what the judge already checks), not in the judge's detection logic.

---

## 6. Enforcement mechanisms surveyed

Given §5.2's numbers (112/150 violations, 71/72 failures one-directional) and that the judge can't be touched, the only lever left is making the agent's actual tool choices satisfy what the judge checks. Three mechanisms were investigated.

### 6.1 ToolApproval — ruled out, no code written

The third `PolicyType` (alongside `ToolGuide` and `ToolGuard`). Investigated `src/cuga/backend/cuga_graph/nodes/cuga_agent_core/policy/tool_approval_handler.py`: it's a **human-in-the-loop LangGraph interrupt** (renders a code-preview UI, waits for an approve/deny action), not an automatic gate. Critically, `handle_denial()` (`tool_approval_handler.py:255-270`) doesn't retry on denial — it ends the turn outright (`goto=END`, `final_answer="Execution cancelled by user."`). Since 40/150 policy violations still pass overall on other judges (§2.3), an unattended hard-stop on every violation would be strictly worse than doing nothing. Ruled out; no code was written for this.

### 6.2 Full ToolGuard (`ToolGuardRuntime`/`ToolGuardManager`) — ruled impractical for the deadline, no code written

`ToolGuide` policies can optionally carry a `tool_guards: Dict[str, ToolGuard]` (default `{}`) where each `ToolGuard.policy_code` is real Python (`async def guard_xxx(api, args)`), normally LLM-generated once at buildtime via the third-party `toolguard` library's `generate_guards_code()`, then executed at runtime by `ToolGuardRuntime.guard_tool_call()` before a tool call is allowed through — a genuine hard block (`PolicyViolationException` → the call never happens), not an advisory.

Investigated whether the LLM buildtime step could be skipped (hand-write `policy_code` directly, since `_build_runtime()` uses `load_toolguards_from_memory()` — genuinely in-memory, no LLM needed for that part). **Found it can't be fully skipped**: `_build_runtime()` requires a `RuntimeDomain` (`app_types`/`app_api`/`app_api_impl` file twins) loaded via `_load_runtime_domain()`, and the only code path that produces those files is `ToolGuardManager.generate_guard_code()`, which bundles RuntimeDomain generation together with the LLM-based guard-code generation in one call to the third-party library (`manager.py:490-502`) — they're not separable without reaching into the third-party `toolguard` package's internals. This means a real `ToolGuardRuntime` integration needs at least one LLM call per domain just for domain-file setup, plus wiring `ToolGuardingToolProvider` (`nodes/cuga_lite/providers/toolguard.py` — already exists, wraps any provider, returns a `{"error": ..., "blocked_by_policy": True}` dict on block rather than crashing) into the M3 eval harness, which isn't done anywhere today.

Given the 2026-07-24 deadline, decided this is too large to build and validate today. Ruled out for now, not ruled out forever — flagged as the properly-general version of §6.3 for a future issue.

### 6.3 `RetrieverPolicyGuard` ("ToolGuard-lite") — design finalized, implementation paused for this doc

The chosen scope: reproduce the **effect** ToolGuard would have on this dataset's single dominant policy rule (§2.3 — retriever-only-required, 71/72 of the failing violations), as a hand-written check at the same tool-call interception points already used by `BlockToolCallBudget`/`TaskToolCallHistory` (`registry.py::call_api`, `combined.py`'s tracker-tool wrapper) — skipping the third-party `toolguard` library, the LLM buildtime step, and `RuntimeDomain` entirely. On a block, return `{"error": ..., "blocked_by_policy": True}` (matching `ToolGuardingToolProvider`'s existing convention from §6.2) instead of executing — never crash, let the agent retry, exactly the "return a descriptive string/dict, never raise" convention already used throughout this codebase.

**Design, informed directly by §4's hard-won lesson** (a contextvar set in one LangGraph node dispatch is invisible in another — confirmed this session would have hit the exact same bug by planning to set the policy text in `prepare_node.py` and read it in `registry.py`/`combined.py`, two different dispatches):

- User's explicit instruction: build this **independently** of the stashed `TaskToolCallHistory` plumbing (§4) — don't un-stash it, don't depend on its fate.
- Reuse the proven `(b′)` shape, but as new, separately-named code: a contextvar carrying only a per-task key, rebound fresh at the top of every `local_executor.py::execute()` dispatch; the actual policy value (small, non-accumulating — just the resolved directive, unlike `TaskToolCallHistory`'s growing history) lives in an ordinary module-level dict keyed by `thread_id`.
- `thread_id` is constructed inside `benchmarks/helpers/sdk_eval_helpers.py` (`evaluate_task_with_langfuse` line 881, `evaluate_multiturn_task_with_langfuse` line 1391) — **not** currently visible to `eval_m3.py`, which only has `policy_text` at its `add_tool_guide()` call site (`eval_m3.py:939-948`). Plan: thread a new `policy_text: Optional[str] = None` parameter into both `sdk_eval_helpers.py` functions (from `eval_m3.py`'s existing call sites, which already have `policy_text` in scope), and register `RetrieverPolicyGuard.register(thread_id, policy_text)` immediately after `thread_id` is constructed, with `unregister()` in a `finally` once the task completes.
- Enforcement check itself mirrors `policy_judge.py`'s own keyword logic (§5.2) — deliberately, since building enforcement against a *different* criterion than what the immutable judge checks would be pointless: `"do not use any other type of tool"`/`"do not use other types of tool"` → retriever-only required, block any call where `"query_" not in tool_name`; `"do not use document retriever"` → retriever forbidden, block any call where `"query_" in tool_name`.

**Not yet implemented.** No code has been written for this in either repo as of this doc. Concrete next steps if/when resumed: add `RetrieverPolicyGuard` to `cuga-agent/.../tracking/tracker.py` (or a new small module, to avoid entangling with the stashed `TaskToolCallHistory` class in the same file), thread `task_key` into `local_executor.py::execute()`, add the check in `registry.py::call_api()` and `combined.py`'s tool wrapper, thread `policy_text` through `sdk_eval_helpers.py` and `eval_m3.py`. Validate single-run first, then `compare.sh --runs 5` on the ToolGuide probes, per this investigation's standing validation pattern.

---

## 7. Deferred / stashed work inventory

Two unrelated stashes exist; neither should be touched until the current work (§6.3) is working, and even then only if time remains before the 2026-07-24 deadline (explicit user instruction).

**cuga-agent `stash@{0}`** — `TaskToolCallHistory` prototype, see §4. Full writeup already committed as `docs/issues/task-tool-call-history-contextvar-isolation.md`.

**cuga-eval `stash@{0}`** — `"m3-cap4-fixes-after-training: policy-judge-path, langfuse resumability, registry-port step1, eval_config cleanup"`. Predates this session's current working-tree changes; contains an **earlier, superseded** attempt at registry-port handling (the current working tree has its own fresh, independent implementation — §0 item 5) plus:
- `benchmarks/helpers/bundle.py` (+128/-0-ish) — Langfuse resumability rework, not evaluated in this session.
- `benchmarks/m3/m3_vakra_score.py` (+10) — an earlier `policy_judge_path` wiring attempt (superseded by whatever produced the currently-untracked `policy_judge.py` + the `scorer.py`/`evaluator.py` wiring already present in the current working tree — see §5).
- `benchmarks/m3/eval_config.toml` (-9) — cleanup, likely superseded by the current probe-key additions.
- Unfinished subprocess-parallelization groundwork (per direct user instruction mid-session: *"there's the unfinished subprocess parallelization stuff too"*) — this is the actual worker-pool scheduler for `--batch-size`/`--parallel-containers` (cutting `compare.sh` turnaround time, not a scoring lever). Only a port-finder exists in the current working tree (§0 item 5); the real scheduler was never built, in this stash or since.
- `.../tests/test_eval_m3_env_health_wiring.py` (2 lines) — test fallout from the above.

**Decision:** leave both stashes untouched. Reconcile the cuga-eval stash (pop, diff against current working tree, decide what if anything is still worth keeping) only after §6.3 is working and validated, and only if time remains.

---

## 8. Open threads / candidate future issues

Roughly in the order they'd need attention:

1. **Finish `RetrieverPolicyGuard`** (§6.3) — implement, single-run validate on the ToolGuide probes, then `compare.sh --runs 5`.
2. **Isolate Change #2 from P-OF-3** (§3) — currently only tested as a bundle; need to know which is actually driving the 66.7% result before recommending either alone.
3. **Run Change #3 for the first time** (§3) — zero evidence either way.
4. **`compare.sh --runs 5` on `TaskToolCallHistory`** (§4, cuga-agent) — plumbing is proven, outcome effect is not. Not blocking this session's work per the explicit decoupling decision, but is the natural next step once someone picks that thread back up.
5. **Reconcile the cuga-eval stash** (§7) — after 1-3, if time remains.
6. **`BlockToolCallBudget` removal** (cuga-agent, PR #493 review thread) — explicitly out of scope for this investigation, but blocks any future consolidation of the runaway-fix code paths.
7. **Full `ToolGuard` integration** (§6.2) — the properly-general version of #1, deferred past the deadline.
8. **Subprocess-parallelization / worker-pool `--batch-size` step 2** (§7) — pure turnaround-time improvement for `compare.sh`, not a scoring lever. Explicitly deferred.
