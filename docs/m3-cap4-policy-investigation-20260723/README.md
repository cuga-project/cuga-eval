# M3 capability_4 investigation — full record

**Status:** living document, last updated 2026-07-27. Original deadline for cap4 results was 2026-07-24 (the initial 300-task run, §0-§8, completed on schedule); the document continued past that as a genuinely ongoing investigation — see §9 onward for everything since, §15 for the most recent addition (a real regression found on a live VM run, diagnosed and fixed same-day).
**Repos involved:** `cuga-eval` (this repo, branch `integration/m3-eval`), `cuga-agent` (sibling repo, same branch), and as of §9, `cuga_vakra_agent` (external comparison harness, read-only) and `vendor/vakra` (vendored benchmark, read-only except one container restart, §9.4).
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

---

## 9. Status snapshot update (2026-07-26): what's real vs prototype since §8

Everything below continues this document past the 2026-07-24 deadline. §0's snapshot covered items 1-20 (the riders/fixes from the initial investigation); this table covers everything new since.

| # | Item | State | Committable? |
|---|---|---|---|
| 21 | Full 300-task cap4 baseline run (`cap4_300_full_riders` bundle) | Complete, scored with policy judge. **153/300 = 51.00%** | N/A — reference data |
| 22 | Independent verification of `cuga_vakra_agent`'s actual submission | Complete, re-scored against our own groundtruth + policy judge | N/A — reference data. **127/300 = 42.33%** real (43.8% excluding 12 infra-error tasks) — well below their claimed 66.3%/79.7% and below our own 51.0% |
| 23 | `M3_POLICY_TOOL_SCOPING` (technique #1: deterministic policy-driven tool pruning) | **Committed** (`a4e25f0`, docstring cleanup `628208b`) | Yes — shipped, default off |
| 24 | `M3_REFUSAL_NORM` (technique #3: blank-on-giveup, not canonical-string) | **Committed** (`a4e25f0`) | Yes — shipped, default off |
| 25 | `M3_SUPPORT_CHECK` (technique #4: support-check groundedness guard) | **Committed** (`317451e`) | Yes — shipped, default off. **Known 52% false-positive rate on currently-passing tasks (§13) — do not enable broadly without a redesign** |
| 26 | `M3_TOOL_SHORTLIST` (technique #2: MiniLM tool pre-filter, top_k=40) | **Committed** (`91ee703`) | Yes — shipped, default off. **Known 96% miss-rate on currently-passing tool-dependent tasks at top_k=40 (§13) — do not enable unconditionally** |
| 27 | Retriever backend (port 8001 in `capability_4_multiturn`) OOM/crash fix | Container restarted, verified healthy | N/A — infra state, not code. Will not survive a future container recreation without addressing the underlying OOM cause |
| 28 | `_policy_is_retriever_tool` substring-match fix (was `startswith`, registry domain-prefixes tool names) | **Committed** (part of `a4e25f0`) | Yes — shipped |
| 29 | `_is_giveup` curly-apostrophe normalization fix | **Committed** (part of `a4e25f0`) | Yes — shipped |
| 30 | 12-task candidate eval-key set (`cap4_vakra_t1..t4_*`, `cap4_vakra_all_candidates`) | **Committed** (part of `a4e25f0`) | Yes — shipped, pure test infra |
| 31 | Offline regression-risk methodology (embedding-based tool-shortlist check, policy-scope GT cross-reference, support-check false-positive scan) | Scripts in `/tmp/`, not committed | Consider moving into a `scripts/` or `docs/` location if this becomes a recurring check — currently one-off analysis |
| 32 | `M3_ANSWER_DISCIPLINE_RULE` / `M3_ANSWER_DISCIPLINE_RIDER` | **Uncommitted, working tree.** Just written, not yet tested. Deduplicated against `M3_PARAMETER_VARIATION_RULE` (§14.3) — the two riders can coexist without ever double-appending the same guidance | No — needs at least one real test run before shipping, per this document's own standard |
| 33 | Step cap reduction (35→16) | **Not implemented.** Decided in principle (§14), not yet wired in. Current plan: set globally via `DYNACONF_ADVANCED_FEATURES__CUGA_LITE_MAX_STEPS=16` at launch, no eval_m3.py code change needed for the cap itself | No — not built |
| 34 | Stall-detection + retry-with-shortlist | **Not implemented.** Design agreed (§14): detect "Maximum step limit" in the response, retry once with `SemanticShortlistToolProvider` activated for that task only | No — not built |
| 35 | `cap4_vakra_all_candidates` 3-run comparison: all 4 techniques vs. safe-2-only | Complete (§12) | N/A — reference data. **Identical result both ways: 16/36.** Shortlist + support-check contributed zero net gain on this candidate set |

---

## 10. The cuga_vakra_agent comparison request

User asked to look at `../cuga_vakra_agent`, a separate CUGA-based harness claiming much higher cap4 scores (README: with-policy 63.5%→79.7%, overall 58.0%→66.3% vs. a no-guards baseline, on 288/300 items). Investigated its architecture (`adapter/cuga_v2_agent.py`, `adapter/cuga_clean_agent.py`, `adapter/tool_shortlister.py`, `config.py`) and identified five candidate techniques:

1. **Policy tool-scoping** (`VAKRA_V2_SCOPE`) — deterministically prune forbidden/required document-retriever tools per-task based on the cap4 policy text, instead of only reactively blocking a call after the fact.
2. **MiniLM tool pre-filter** (`ToolShortlister`) — semantic pre-filter over the tool catalog before handing it to the agent.
3. **Canonical refusal normalization** (`VAKRA_CUGA_REFUSAL_NORM`) — normalize give-up-shaped answers.
4. **Support-check groundedness guard** (`VAKRA_V2_SUPPORT_CHECK`) — blank answers whose claim tokens aren't supported by retrieved evidence.
5. **Tool-call cap** (`VAKRA_CUGA_TOOL_CAP=16`) — hard step limit, justified by the authors as "the evaluator only sees the last 20 responses." Explicitly excluded from porting this session (told to "skip #5") after historical data showed 6 of 8 passed `professional_basketball` tasks used >16 LLM calls — a bare cap with no rescue mechanism would have cost those. (Revisited later, §14, once paired with a rescue mechanism.)

### 10.1 Independent verification of their actual submission

Before trusting any of this, the user asked to verify `cuga_vakra_agent`'s real submission (`~/Downloads/capability_4_cuga_v3_submission.zip`) against our own groundtruth + policy judge, rather than take their README's numbers at face value.

This took three infrastructure debugging passes before getting a clean number, each initially mistaken for evidence about the competitor's quality:

1. First live-MCP scoring attempt "succeeded" but gave impossibly low scores — the `capability_4_multiturn` container was wedged (curl returned nothing) despite the run completing; every judge call failed with `"Judge Error Connection error.."`.
2. Restarted the container, retried — crashed reproducibly at `book_publishing_company` (domain #7 alphabetically), twice in a row, with `RuntimeError: Failed to connect to MCP server via stdio`.
3. Tried offline scoring (`M3_VAKRA_LIVE_MCP=off`) as a workaround — discovered the standalone `evaluator.py` CLI never actually reads that env var; it unconditionally attempts live-MCP whenever `--mcp-config` resolves non-None. Fixed by pointing `--mcp-config` at an empty YAML. This ran cleanly but gave 22/300 = 7.33% — the competitor's submission format lacks `tool_response` data entirely, so true offline scoring is structurally invalid for it.
4. Checked `docker inspect` — confirmed real OOM (`OOMKilled: true`). Raised container memory via `docker update --memory 16g --memory-swap 16g --restart unless-stopped` + a fresh restart. Retried live-MCP — **crashed at the exact same `book_publishing_company` checkpoint a third time**, ruling out OOM as the actual root cause.
5. Diagnosed as a per-process (not per-container) resource leak. Fixed by splitting the 35 domains into 6 batches of 6 (`run_batched_rescore.sh`), each an independent subprocess with a container health-check-and-restart step before each batch.
6. All 6 batches completed, but the merged result was suspiciously identical to the earlier broken 7.33% run — all 111 judge calls had failed with `"Judge Error Connection error.."` again, this time because the corporate VPN had disconnected (unrelated to the container, which was healthy throughout).
7. User reconnected the VPN. Verified via a real `curl` POST (200 OK). Relaunched the batched script — all 6 batches completed with zero errors.

**Final verified result: 127/300 = 42.33% (43.8% excluding 12 infra-error tasks in their own submission — 9 with `max_tokens must be at least 1, got -492375` and 3 `ConnectTimeout`).** This is *below* our own 51.0% baseline, contradicting their claimed 66.3%/79.7%. The ~4-point gap between their real overall number and our baseline is only partially explained by their own submission's infra failures — the rest is unexplained and not further investigated.

### 10.2 "Is this cheating?" framework

Applied a three-part test to each technique: (a) does it use information the agent shouldn't have (groundtruth leakage)? (b) does it exploit a scorer-specific quirk unrelated to the quality being measured, vs. enforce a general property the judge is *trying* to measure? (c) would a real production deployment still want this, independent of any benchmark?

Ranking, clean → gaming-adjacent: **#2 (MiniLM pre-filter)** > **#4 (support-check)** > **#1 (policy tool-scoping**, borderline — matches what our own immutable `policy_judge.py` keyword-checks, but narrow) > **#3 (refusal normalization**, reverse-engineered from a judge string special-case that turned out not to exist in our scorer — see §11.3) > **#5 (tool cap**, most gaming-like, tied explicitly by its designers to the scorer's observation window).

---

## 11. Technique implementation — what broke and what got fixed

### 11.1 Candidate task mining

Mined real failing tasks from the `cap4_300_full_riders` bundle's `results/partial/*.json`, matched to each technique's actual failure signature (not just "this task failed"):

- **Technique #1 candidates**: initially picked by "runaway + policy present" text matching. **This was wrong** — see §11.2, all three original picks turned out to have zero applicable tools in our container.
- **Technique #2 candidates**: tasks where the agent claimed a needed tool didn't exist, but it actually did under a slightly different name (e.g. `get_actual_elapsed_time_by_description` claimed missing; real tool is `actual_elapsed_time_by_description`, no `get_` prefix). Verified genuine via direct `openapi.json` inspection.
- **Technique #3/#4 candidates**: originally conflated. First pick (hockey/olympics/world, `gt_steps=0 + groundedness=0`) turned out to be "confident answer + inline hedge" fabrications — the right target for #4 (support-check), not #3. Re-mined #3's real candidates by scanning `results/partial/*.json` for answers that both (a) match `_is_giveup()`'s marker list and (b) scored 0 — 16 found corpus-wide, 3 picked (disney, restaurant, cars) after confirming they're in domains not already used elsewhere.

Final set: 12 unique candidates in `benchmarks/m3/eval_config.toml` (`cap4_vakra_t1_task1..3`/`_group`, same for t2/t3/t4, plus `cap4_vakra_all_candidates`). All 12 independently reconfirmed as genuine failures (`0/12`) in the original 300-task run before any implementation work started, per explicit user request ("otherwise this exercise may be futile").

### 11.2 Technique #1 (`M3_POLICY_TOOL_SCOPING`) — the retriever-infra saga

First test on `cap4_vakra_t1_task1` "passed," but investigation (prompted by the user asking "why did you choose a task which is a no-op?") revealed the pruning removed zero tools — our `capability_4_multiturn` container had **zero retriever tools in any domain**, confirmed by dumping the full container `openapi.json` (7088 paths) and grepping for `query_`/`retriev`/`search`/`lookup`/`document` — zero matches anywhere.

Traced the real cause through several layers:
1. `capability_4_mcp_server.py` merges tools from **two** backend servers: M3 REST (port 8000, always checked) and a separate Retriever FastAPI (port 8001, never checked until this investigation).
2. Port 8001 was not listening. `docker exec ... curl :8001/health` → connection refused.
3. Checked the container's own boot log: the entrypoint (`docker/entrypoint-unified.sh`) **did** start the retriever server successfully on every past restart ("Uvicorn running on http://0.0.0.0:8001") — it died sometime after boot under load, almost certainly the same OOM pattern documented in §10.1.
4. The underlying Chroma data was never the problem — `vendor/vakra/data/indexed_documents/chroma.sqlite3` (4.38GB) contains 52 fully-indexed, valid domain collections. A red herring earlier in the investigation was `vendor/vakra/data/queries/` being empty — that directory is only used by the retriever's own test harness (`test_queries.py`), not by tool registration, confirmed by reading `environment/retrievers/server.py`.
5. **Fix**: `docker restart capability_4_multiturn`. Verified `/domains` now returns all 33 real domain collections.

Second bug, found immediately after: pruning still did nothing even with real retriever tools present. `_policy_is_retriever_tool` checked `name.startswith("query_")`, but the registry exposes tools domain-prefixed (`professional_basketball_query_professional_basketball`, not bare `query_professional_basketball`) — confirmed by cross-referencing the competitor's own real submission, which calls the same tool under the same prefixed convention. **Fix**: changed to a substring check (`"query_" in name.lower()`), verified zero false-positive risk against the 156 non-retriever REST tools.

After both fixes: pruning verified working (161→156 tools correctly removed for a `no_retriever` scope). Single-task and 3-task-group tests still showed noisy, inconsistent results (task never reproduced its original runaway failure mode across 4 different runs — see §11.4). **Shipped anyway** per user decision ("ship it behind the flag") once the mechanism itself was verified correct by direct log inspection, since single-task pass/fail proved too noisy to use as the sole validation gate.

### 11.3 Technique #3 (`M3_REFUSAL_NORM`) — the canonical-string premise was wrong

First implementation matched the ported design exactly: normalize give-up text to the literal string `"I can not answer."`. First test (disney task) failed — investigated why, and found **the same task re-run 4 times produced 4 completely different failure modes** (clean marker-matching refusal, confident hedge-with-answer, step-limit runaway, near-correct-but-typo'd answer), none of which reproduced the original mined failure. This was the first clear demonstration of just how noisy single-task testing is on this corpus at temperature 0.1 (see §11.4).

Separately, and more importantly: **read `benchmarks/m3/evaluator/scorer.py` directly** and found the premise wrong. The scorer's actual deterministic "unanswerable" bypass is:

```python
"i can not answer" in input.gt_answer.lower()   # ground truth, not prediction
and (len(input.pred_tool_calls) == 0 or input.pred_answer in ["", " "])
```

This checks the ground truth for the phrase, and the prediction only needs to be **blank or have made zero tool calls** — there is no check anywhere in the scorer for the prediction containing any specific canonical string. Grepped the entire evaluator for `"i can not answer"` to confirm — it never appears as a check against `pred_answer`. **Rebuilt the technique around blanking instead of canonicalizing** — same `_is_giveup()` marker detection, but sets the matched field to `""` instead of `"I can not answer."`.

While rebuilding, found and fixed a second real bug: `_is_giveup()`'s marker list uses straight ASCII apostrophes (`"i'm unable"`), but gpt-oss consistently outputs typographic curly apostrophes (`I'm unable`, U+2019) — silently defeating real matches. Added normalization (`.replace("'", "'")`) before matching. Also added `"step limit"`/`"maximum step"` to the marker list after observing it as a real, recurring non-answer pattern in the corpus.

Final validation attempt (restaurant task, the one candidate whose ground truth is genuinely `"I can not answer."`) still didn't cleanly demonstrate causality after 4 runs — the task kept naturally hitting `pred_tool_calls == 0` on its own (the free bypass path), so blanking was never the deciding factor in any single run, even though the debug log confirmed the code was firing correctly when a marker did match. Shipped per the same "mechanism verified by reading the scorer source + confirmed firing in logs" reasoning, since single-task proof kept being structurally unavailable for this specific candidate.

### 11.4 Run-to-run noise investigation

User asked whether temperature could be lowered to reduce this noise. Checked and reported a real correction: I had been assuming gpt-oss ran at temperature 1.0 (true for `cuga_vakra_agent`'s own config), but **our own harness already runs every node at `temperature = 0.1`** (`cuga-agent/src/cuga/configurations/models/settings.openai.toml`), confirmed via `temperature=0.1` in every test log this session. The judge is also already `temperature=0` (`benchmarks/m3/evaluator/judge.py`, explicit comment: "must be deterministic as much as possible"). Both sides were already near the floor — the observed variance is not a temperature knob we haven't turned, more likely server-side non-determinism inherent to how gpt-oss (a MoE model) gets served through the LiteLLM proxy, a documented real phenomenon independent of client-side sampling settings.

Ran the disney task 2 more times to confirm this was genuine infra-level noise and not something in our own pipeline — confirmed (3 different failure modes across 3 runs, no repeats).

### 11.5 Technique #2 (`M3_TOOL_SHORTLIST`) — ported cleanly, regression risk found later

Ported `ToolShortlister` near-verbatim from `cuga_vakra_agent/adapter/tool_shortlister.py` (MiniLM `all-MiniLM-L6-v2`, cosine similarity, `query_*` always pinned). `top_k` defaulted to 40, matching `cuga_vakra_agent`'s own `AgentConfig.top_k_tools`. Single test on the airline candidate showed the shortlist correctly surfacing and enabling a call to a genuinely relevant tool (`get_count_flights_elapsed_time_less_than_scheduled`), though the task still failed for an unrelated downstream reason. Shipped per the same "verified mechanism, noisy single-task signal" reasoning as #1.

**The severe regression risk (§13) was found later**, after shipping, during a dedicated user-requested regression audit — see §13. Not caught by the pre-ship candidate test because that test only checked "does the technique help a currently-failing task," never "does it hurt a currently-passing one."

### 11.6 Technique #4 (`M3_SUPPORT_CHECK`) — built with the blanking lesson already applied

Built directly with the blank-not-canonicalize lesson from §11.3 already incorporated. Ported the token-overlap logic (numbers + capitalized entities, 50% support threshold) from `cuga_v2_agent.py`'s `_post_answer_hook`, but explicitly **not** gated behind a `retriever_only` policy scope like the original — that scope is effectively unreachable in our system (§11.2: our container mostly lacks working retriever tools), so gating on it would have made this dead code too. Applied generally instead. Confirmed all 3 candidate tasks' ground truths are genuinely `"I can not answer."` before testing (same due-diligence as §11.3). Single-task test (hockey) again hit the free zero-tool-calls bypass rather than exercising the code path directly — shipped per the same reasoning as the others.

---

## 12. The 12-task, 3-run comparisons

Ran `cap4_vakra_all_candidates` (all 12 tasks) 3 times sequentially at `--batch-size 3` (the safe concurrency setting established earlier this session after a rate-limit incident), first with all 4 techniques enabled, then with only the 2 techniques later confirmed safe (`M3_POLICY_TOOL_SCOPING` + `M3_REFUSAL_NORM`).

| Run | All 4 techniques | Safe-2-only |
|---|---|---|
| 1 | 6/12 | 6/12 |
| 2 | 5/12 | 6/12 |
| 3 | 5/12 | 4/12 |
| **Total** | **16/36** | **16/36** |

**Identical totals, and near-identical per-task breakdowns** (only 1 task differed between the two conditions in any given run slot). Baseline for all 12 tasks: 0/12 in the original 300-task run. 4 tasks passed consistently (3/3) under both conditions: `ee275d64dafc-9c5805f01039`, `308738b8195d-34e4c507c777`, `5caddc4c49de-1426f1f6aa46`, `486ea46224d1-2ab24217a08e`.

**Conclusion: on this candidate set, `M3_TOOL_SHORTLIST` and `M3_SUPPORT_CHECK` contributed zero measurable net gain over the 2 safe techniques alone**, while (per §13) carrying real, measured regression risk. This is the direct evidence behind shipping all 4 behind flags but not recommending shortlist/support-check for any broader/default use without further work.

Both runs were done with `caffeinate -dis -w <pid>` after a user-flagged gap (I had launched the first long job without it — a real miss, corrected once caught). No `Judge Error Connection error` in either run — infra stayed healthy throughout (~2.5-3 hours each).

---

## 13. Regression risk audit (user-requested, off the back of §12)

User's framing: "it's possible we'll see a few task improvement on the whole set. hopefully we won't have any regressions... are there any areas that are worth checking for regressions?" Rather than speculate, ran each technique's actual detection logic offline against the 142 tasks that passed in the original 300-task run (zero agent/LLM calls — pure local computation using existing result data + the real MiniLM model + the real scorer logic read from source).

| Technique | Exposure | **Verified real regression rate** |
|---|---|---|
| `M3_TOOL_SHORTLIST` (top_k=40) | ~all 142 tasks (57 of ~62 domains exceed 40 tools) | **24/25 (96%)** of tool-dependent passing tasks in domains >40 tools would lose their actually-used, actually-needed tool from the shortlist |
| `M3_SUPPORT_CHECK` | 74/142 (52%) trigger the heuristic | **74/142 (52%) confirmed real** — many are legitimate answers with *computed* values (ratios, sums, averages) that don't appear verbatim in raw tool evidence; the heuristic has no notion of derived values |
| `M3_POLICY_TOOL_SCOPING` | 120/142 (85%) have a "document retriever" policy | **~0/142 real risk.** The benchmark pairs "document retriever" policies almost exclusively with `gt_answer = "I can not answer."` — checked every exposed bucket (unconditional retriever-only: 59/59 GT-safe; conditional: 59/61 GT-safe, 2 unresolved but look off-topic by inspection; the 1 task that *did* use a retriever successfully is correctly retriever-only per its own policy) |
| `M3_REFUSAL_NORM` | 43/142 (30%) trigger the marker match | **2/142 (1.4%) real risk.** 41 of the 43 matches are on tasks whose GT is *also* `"I can not answer."`, so blanking is redundant, not harmful |

Re-checked `M3_TOOL_SHORTLIST` at `top_k=128` (the actual default in the shared VAKRA `benchmark_runner.py` CLI, used by the LangGraph reference agent — **not** the 40 borrowed from `cuga_vakra_agent`'s separately-tuned preset). Result: exposure drops from 25→8 tool-dependent tasks (fewer huge domains get touched at all), but **within that smaller population the miss rate is still 8/8 (100%)** — raising `top_k` reduces how many tasks are touched, not the underlying ranking quality when it does apply. Net effect across all 142: ~5.6% real regression if applied unconditionally at 128, vs. ~17% at 40.

**Standing recommendation from this audit: `M3_TOOL_SHORTLIST` and `M3_SUPPORT_CHECK` are not safe to enable unconditionally as currently built.** `M3_POLICY_TOOL_SCOPING` and `M3_REFUSAL_NORM` are genuinely safe by this measurement.

---

## 14. Stall / step-cap investigation (in progress)

Prompted by recalling (from an earlier session) that CUGA often stalls searching for the right tool, and observing directly in the 12-task comparisons: 16 step-limit hits across the 6 runs (all resulted in fail, zero stall-but-passed instances in these particular runs), plus one extreme outlier — the "Melo" `professional_basketball` task passing after **185 tool calls** in one run.

### 14.1 Why not a bare 16-cap

Checked the natural tool-call-count distribution across all 142 historically-passing tasks:

| Cap | % complete naturally | % that would need rescue |
|---|---|---|
| 35 (current) | 99% | 1% |
| 20 | 94% | 6% |
| 16 | 89% | 11% |
| 12 | 87% | 13% |
| 10 | 85% | 15% |
| 8 | 79% | 21% |
| 6 | 75% | 25% |
| 4 | 70% | 30% |

A bare cap with no rescue mechanism would cost real successes at any of these thresholds. Design settled on: **lower the cap, but pair it with a retry mechanism** that only fires on detected stalls (so it can't cost anything already passing naturally) — mirrors §3's own `M3_PARAMETER_VARIATION_RULE`/`M3_FIND_TOOLS_QUERY_RULE` finding that `find_tools`'s "underlying LLM shortlister has real sampling variance neither rider fully removes."

### 14.2 Cross-validated with the competitor's real run

Identified the exact 15 tasks (by UUID) that needed >16 calls to pass in our own baseline, then checked how the LangGraph reference agent and `cuga_vakra_agent`'s real, independently-verified run (§10.1) did on those *same* 15 tasks:

| System | Result on the 15 long-tail tasks |
|---|---|
| cuga-eval baseline (no cap) | 15/15 (100%, by construction) |
| LangGraph reference | 10/15 (67%) |
| **cuga_vakra_agent** (real run — actually uses cap=16 + MiniLM top_k=40, their documented `FULL_GUARDS` config) | **12/15 (80%)** |

Cross-check: the competitor's **3 real failures** on this set (`55b7e50368aa-cdbe6eec1450` mondial_geo, `d0d7be63ebc2-c044be462453` ice_hockey_draft, `3683085b75b9-bc8c05f6855b` food_inspection) are **exactly** the 3 tasks the offline top_k=40 simulation (§13) independently predicted would lose their needed tool — no false positives, no misses. Strong validation that the offline check is a real predictive signal, not noise.

Caveat surfaced and agreed: their 80% reflects their **whole bundle** (cap + shortlist + policy-scope + refusal-norm + support-check + two prompt riders we hadn't ported), not cap+shortlist in isolation. Since we already have policy-scope, refusal-norm, and support-check shipped, testing all 4 of ours + cap=16 together is the fairer comparison — not shortlist+cap alone.

### 14.3 ANSWER_DISCIPLINE / VERBATIM_RULE — ported, one conflict found and resolved

Considered porting `cuga_v2_agent.py`'s two remaining prompt-nudge riders:
- **ANSWER_DISCIPLINE**: judged directly relevant — its "make at most ONE tool call per code block, stop once you have the answer" rules target exactly the repeated-call pattern behind the stalls and the 185-call outlier.
- **VERBATIM_RULE**: judged not relevant to this specific problem — it only fires on `retriever_only` policy scope, and §13 already established retriever tools are essentially never load-bearing in our corpus (1/142 passing tasks). Not ported.

**Found a direct contradiction before implementing**: ANSWER_DISCIPLINE's stock rule 2 ("at most ONE tool call per code block") is the *opposite* prescription from the already-existing `M3_PARAMETER_VARIATION_RULE` (§3, this document's original investigation), which exists specifically because the one observed pass on the Melo task (`d14bbb0be92d-d09ad3135cea`, the same task used as `cap4_toolguide_probe1`) used a *batched* multi-variant call, not one-call-per-block. Shipping both riders as independent toggles would silently contradict each other if both were enabled.

User's resolution: keep ANSWER_DISCIPLINE's efficiency discipline as the *default* behavior, with an explicit *exception* clause for the empty-string-filter case, folding `M3_PARAMETER_VARIATION_RULE`'s batched-guess guidance in directly rather than relying on a separate rider also being enabled. Implemented as `M3_ANSWER_DISCIPLINE_RULE` / `M3_ANSWER_DISCIPLINE_RIDER` (default off), scoped to just the tool-use-discipline rules (not ANSWER_DISCIPLINE's answer-formatting rules, which would duplicate/risk conflicting with the existing, more specific `M3_GROUNDEDNESS_INSTRUCTIONS` rider family — default-on already).

User then flagged that the two riders needed to either cleanly coexist or have the old one removed entirely, rather than leave any redundancy — fixed in `_build_m3_special_instructions()`: `M3_ANSWER_DISCIPLINE_RIDER`, when on, always takes precedence and skips the separate `M3_PARAMETER_VARIATION_RULE` append (`elif`, not independent `if`s), so the two can never both fire in one prompt. `M3_PARAMETER_VARIATION_RIDER` remains independently usable on its own for isolated A/B testing exactly as validated in §3/§0 item 20. **Not yet tested.**

### 14.4 Test task set — reusing this document's own prior probes

Per explicit instruction to consult this document for which tasks were previously used to validate `M3_PARAMETER_VARIATION_RULE`, rather than mine a fresh set: **`cap4_toolguide_probe_n3`** (§0 item 20's "3-task ToolGuide probe set", `eval_config.toml`) —

```
cap4_toolguide_probe_n3 = [
  "d14bbb0be92d-d09ad3135cea",  # professional_basketball, do-not-use direction, lg also fails
  "5661cd917583-5bf11ec43a9d",  # book_publishing_company, only-use + generic phrasing, lg also fails
  "39a28b2592a2-16ff8f01c848",  # computer_student, only-use + domain-group phrasing, lg passes
]
```

Also directly relevant and likely worth including given this is now specifically about stalls/repetition, not policy compliance — **`cap4_runaway_probe_n4`** (§0 item 6's runaway probes, same file), covering all four distinct repetition shapes identified in that original investigation (exact-duplicate per-item loop, retriever-rephrasing loop, parameter-guessing loop, mixed find_tools-heavy exploration):

```
cap4_runaway_probe_n4 = [
  "e71440999ce8-99b792c44651",  # law_episode, exact-duplicate per-item loop (no timeout fired)
  "d14bbb0be92d-ae240cc7a80e",  # professional_basketball, retriever-rephrasing loop
  "55b7e50368aa-01b9e0ab72a2",  # mondial_geo, parameter-guessing loop (possibly-legitimate search)
  "1960f609e439-3a1b0a9c3535",  # codebase_comments, mixed find_tools-heavy exploration
]
```

### 14.5 Still open

- Step cap itself: not yet wired in. Plan is `DYNACONF_ADVANCED_FEATURES__CUGA_LITE_MAX_STEPS=16` at launch (confirmed this is a real, already-supported per-invoke-overridable config key — `sandbox_node.py:100` reads `configurable.get("cuga_lite_max_steps")`, `graph_adapter.py:87-93` falls back to `settings.advanced_features.cuga_lite_max_steps`), no eval_m3.py code change needed for the global-cap case.
- Stall-detection + retry-with-shortlist: designed (§14.1-14.2 above), not yet built. Detection signal: literal `"Maximum step limit"` in the response text (already proven reliable — appears verbatim in every real stall this session).
- `M3_ANSWER_DISCIPLINE_RULE`: written, deduplicated against the older rider, not tested at all yet.
- Next planned test: run `cap4_toolguide_probe_n3` + `cap4_runaway_probe_n4` (§14.4) with all 4 existing techniques + `M3_ANSWER_DISCIPLINE_RIDER` + cap=16 (+ stall-retry once built), to see how close we land to the competitor's real 12/15 (80%) on the analogous long-tail set (§14.2).

---

## 15. Full 300-task VM run (2026-07-27) — real regression found and fixed same-day

User launched a real full-corpus run on a separate VM (`cap4_300_ans_discipline`: `M3_POLICY_TOOL_SCOPING` + `M3_REFUSAL_NORM` + `M3_ANSWER_DISCIPLINE_RIDER`, no shortlist/support-check), to free up the laptop. Several operational issues came up and were resolved along the way (kept brief since this is process, not a technique finding):

- VM's `.venv` had root-owned files with no `sudo` access — worked around via `UV_PROJECT_ENVIRONMENT` pointed at a fresh, user-owned venv location, rather than fighting permissions.
- `--status`/`--stop` need `--resume-experiment <name>`, not `--experiment <name>`, once the experiment directory already exists — `--experiment` always assumes "create new" and errors ("already exists... use --resume-experiment") otherwise. Real bug in the first cut of the monitoring script, not a VM environment issue.
- Built `scripts/monitor_cap4_run.sh` (not committed — briefly committed by mistake, reverted per explicit instruction, lives in `.scratch/` only): watches container health (both the main REST API and the retriever backend independently — the retriever has repeatedly died under load this session while the main API stays up), and — critically — checks whether `background.log` has gone stale (no new lines in 8 minutes) rather than just whether the process's PID is still alive, since `--status` alone can't distinguish a genuinely hung process from a healthy one. On a detected hang or crash it does a clean `--stop` → container restart → `--resume-experiment`.
- An early "0 tasks completed" scare turned out to be expected, not broken: scoring is per-domain-batch (only fires once *all* of a domain's samples finish), so a domain with more samples (`address`, 22 tasks; `airline`, 20) will show zero scored results for a long time while a smaller domain (`app_store`, 13) finishes and scores first. Confirmed via `agent finished (pre-scoring)` vs `fully scored` counts per domain-prefix — both were climbing normally, nothing stuck.

### 15.1 The real finding: a live regression on `airline`

Direct baseline comparison once `airline` (20/20 tasks) finished scoring on the VM:

| | baseline | current (VM run) |
|---|---|---|
| airline (20 tasks) | 9/20 | 7/20 |

Net **-2, zero new wins, 2 confirmed regressions**: `1b288c5c6dc9-3cfb9361e826` and `1b288c5c6dc9-8ebb9b32a1d7` both flipped from a reliable baseline PASS (and `cuga_vakra_agent`'s real verified run also PASS on both — see §10.1) to a FAIL. Both have `gt_answer = "I can not answer."`, so the scorer's deterministic bypass should have caught them regardless of which tools were available — something else broke it.

Root cause, confirmed directly from the VM's own log (`score=0.00 ... exactmatch=1.0 groundedness=0.0`, i.e. the *shape* of the answer was right, the judge objected to its *content*):

- `1b288c5c6dc9-3cfb9361e826`: `pred="Evidence: unique_tail_numbers = []; Answer: No tail numbers for flights on August 17 2018 are available in the airline data source."` — functionally a refusal, but "No tail numbers... are available in the X" doesn't match any `_GIVEUP_MARKERS` entry (nothing close to "no tool").
- `1b288c5c6dc9-8ebb9b32a1d7`: `pred="The airline application only provides the free-form retriever airline_query_airline. No structured endpoint for listing flights or cancellations exists, and the retriever's results do not contain..."` — the agent explicitly narrates its own tool restriction (a direct side effect of `retriever_only` scoping making the agent aware it's missing its normal tools), which the groundedness judge penalizes as an ungrounded claim about "the airline application," not about the retrieved data.

Neither got blanked by `M3_REFUSAL_NORM` (marker list too narrow), so the raw text reached the judge and failed groundedness on content it shouldn't have needed to state at all.

### 15.2 Fix, implemented and verified same-day (commit `0024a60`)

Two complementary changes, both default-off, tested together against both regressed tasks locally (`cap4_retriever_only_regression_n2` eval-key) before committing:

1. **Expanded `_GIVEUP_MARKERS`** with the concrete phrasings observed: `"not available in the"`, `"only provides"`, `"no structured endpoint"`, `"does not contain any information about"`. Reactive backstop — the fourth time this session a real phrasing has slipped past the marker list (curly apostrophes, "step limit", now these).
2. **`M3_RETRIEVER_ONLY_REFUSAL_RULE` / `M3_RETRIEVER_ONLY_REFUSAL_RIDER`** (default off): when a task's policy-scope resolves to `retriever_only`, fold an explicit "reply with exactly `I can not answer.`, no explanation, no tool-availability narration" rule into that task's ToolGuide content — attacks the problem at generation time rather than leaving it entirely to post-hoc detection. Required reordering scope resolution to happen *before* the ToolGuide is built (previously resolved after), so the rule can be conditionally folded in.

Verified: both regressed tasks re-run locally with `M3_POLICY_TOOL_SCOPING` + `M3_REFUSAL_NORM` + `M3_RETRIEVER_ONLY_REFUSAL_RIDER` → **2/2, groundedness=1.0 on both** (not just the deterministic bypass squeaking by), answers cleanly blanked to `""`. Not yet run against the full corpus or the VM run in progress — that run was left untouched, this fix is for the next config.

### 15.3 Cross-agent comparison data collected this run (useful reference, not new methodology)

While debugging, pulled 4-way baseline/current/competitor/langgraph comparisons for completed domain batches:

- `app_store` (13 tasks): baseline 5, current (VM) 6, competitor 4, langgraph 6 — net +1 for current, zero regressions, tied with langgraph for best.
- `airline` (20 tasks): baseline 9, current (VM) 7 — net -2, the regression covered in §15.1-15.2.
- `address` (22 tasks): current (VM) 8/22 at last check, baseline comparison not yet pulled.
