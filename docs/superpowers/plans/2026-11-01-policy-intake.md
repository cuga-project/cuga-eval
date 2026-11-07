# Policy intake and adherence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn offline policy documents and policies met during a run into typed rules, links and step graphs, enforce them at CUGA's hooks with the cheapest method proven good enough per statement type, and show the result on unseen AutomationBench and ITSM tasks.

**Architecture:** One domain model (`model.py`) shared by an offline builder (documents → statements → type → handler → validators → policy build), online intake (tiers 0–2 into the same model), and the runtime (`RuleSetHooks` + procedure monitor + verifier fallback). Which checker handles a type is read from a measured `method_choice.json`. The offline generator is either the pipeline or a harness-neutral skill; both pass the same validators.

**Tech Stack:** Python 3.12, CUGA hooks API (`cuga.backend.hooks`), cedarpy 4.12, docling (PDF/DOCX/HTML → Markdown), OpenAI-compatible clients (LiteLLM, OpenRouter), OpenRouter `/api/v1/systemone` (Kev), pytest.

**Spec:** `docs/superpowers/specs/2026-11-01-policy-intake-design.md` (cuga-eval). Benchmark scan: `docs/analysis/2026-11-01-policy-xref-and-types.md`.

Paths: `PL` = `~/dev/cuga-agent-gate/src/cuga/policy_layer`; `PE` = `~/dev/cuga-eval/benchmarks/policy_eval`.
Run package tests with `cd ~/dev/cuga-agent-gate && uv run --no-sync pytest src/cuga/policy_layer/tests -q`.

## Global Constraints

- The policy layer uses CUGA only through `cuga.backend.hooks` (`CugaAgent(hooks=[...])`); CUGA core does not import it. Never change `~/dev/cuga-agent`.
- Do not change the hooks API: no `modify` effect; a rule that would change an argument denies with a remedy naming the right value.
- Agent model: `gcp/gemini-3.8-flash` via LiteLLM key `#034bb8` (`pick_key.py 034bb8`). Policy-layer default: `aws/gpt-oss-120b` (LiteLLM). Measured candidates on OpenRouter: `openai/gpt-oss-20b`, `openai/gpt-oss-safeguard-20b`. Kev: `jaredpalmer/kev-4b`, threshold 0.47, via `https://openrouter.ai/api/v1/systemone`. Gemini is a reference only and is never used in arm B.
- Rules come only from policy text and tool schemas, never from a task's grader or verifiers. No rule, prompt or example may name a benchmark task, ID or value.
- Method decision rule: deny only if false deny rate ≤ 2% for that type; else remind only. Prefer cheaper if within 2 points and false deny rate not higher. A type with fewer than 10 cases keeps the default (gpt-oss-120b verifier) and is "not measured".
- Precedence: trusted beats untrusted; then explicit `supersedes` > newer effective date > higher authority rank; document order alone does not decide; an unresolved conflict is advisory only.
- Online latency targets: tier 0 < 10 ms; tier 1 < 1.5 s p95 per tool output; extraction < 10 s; a write waits at most 45 s for pending intake; no wait when an output has no candidate.
- Budget $500; every model call is recorded with `policy_pilot_costs.record(kind, name, agent=..., policy=...)` in `~/dev/cuga-eval/benchmarks/policy_pilot_ledger.jsonl`.
- Seed 20261101 for every selection. Unseen set: 3 trials per task. Primary metrics: AutomationBench AA-style score, ITSM task pass rate.
- Downloaded benchmark content: scripts outside the clone, Python with `-I`.
- **Commits:** every "Checkpoint" step shows the diff summary and asks the user; commit only after the user says yes. No attribution lines.
- Docs and docstrings in plain, simple English (non-native readers).

## Review Focus

1. A rule whose tool is not in the run's tool set must never deny or ask for follow-ups; it goes to the coverage report (pilot bug). Test in Task 9.
2. Two documents that disagree with no `supersedes` link, date or rank difference: both rules become advisory; neither denies. Test in Task 1.
3. An untrusted record that claims to supersede a trusted policy (13 such overrides in AutomationBench) changes nothing that is enforced. Test in Task 10.
4. A tool output with hundreds of text records: tier 1 scores at most `MAX_DETECT_RECORDS = 200` per output and the run continues. Test in Task 10.
5. A model call that times out or returns invalid JSON: classify falls back to `open_judgment` with a coverage note; the verifier allows and records `verifier_error`, never denies on an error. Tests in Tasks 3 and 9.

---

## Phase 1 — Model and documents

### Task 1: Policy domain model

**Files:**
- Create: `PL/model.py`, `PL/MODEL.md`, `PL/tests/test_model.py`

**Interfaces:**
- Produces: dataclasses `PolicySet`, `Document`, `Section`, `Statement`, `Rule`, `Procedure`, `Step`, `Definition`, `Link`, `Fact`, `Verdict`, `CoverageItem(statement_id, kind, reason)`, `PolicyBuild` (`version`, `rules`, `procedures`, `links`, `definitions`, `coverage`, `validation`, `generator` = `{"kind": "pipeline"|"skill", "harness": str, "model": str}`, `stats`); enums `StatementType`, `Modality` (`must`, `must_not`, `may`, `should`), `LinkType` (`refers_to`, `defines`, `exception_of`, `supersedes`, `depends_on`, `next`, `source_of_truth`), `Trust` (`trusted`, `untrusted`); `to_json(obj) -> dict`, `from_json(cls, d) -> obj`; `resolve_conflict(a: Statement, b: Statement, policy_set: PolicySet) -> Optional[Statement]` (None = unresolved → advisory).
- `StatementType` values (exactly): `allowed_values, lookup_matrix, state_transition, required_field, derived_value, threshold, role_permission, approval, prohibition, eligibility_filter, routing, deadline, notification_duty, procedure, exception_override, definition, format, source_of_truth, open_judgment`.
- Every object has `source: dict` (`document`, `section`, `page`, `line` or `record_id`) and `quote: str`. `Statement.types` holds at most 2 types. `Rule.rule` holds today's rule dict (as `ruleset.py` uses it), so `RuleSetHooks` keeps working.

- [ ] **Step 1: Write the failing tests**

```python
def test_json_round_trip_keeps_source_and_types(): ...        # PolicySet with 2 docs → to_json → from_json == original
def test_supersedes_wins_over_newer_date(): ...                # a supersedes b, b newer → a
def test_newer_date_wins_then_authority_rank(): ...
def test_trusted_beats_untrusted_even_with_supersedes(): ...   # untrusted a supersedes trusted b → b
def test_no_precedence_signal_is_unresolved(): ...             # same date, same rank, no link → None
def test_statement_rejects_more_than_two_types(): ...          # ValueError
```

- [ ] **Step 2: Run them; expect ImportError**
- [ ] **Step 3: Implement `model.py`; write `MODEL.md`** (one table per object, a Mermaid diagram of objects and link types, the precedence order, 3 worked examples taken from the AP policy fixture)
- [ ] **Step 4: Run the tests; expect PASS**
- [ ] **Step 5: Checkpoint (ask before commit)**

### Task 2: Documents and policy sets

**Files:**
- Create: `PL/documents.py`, `PL/tests/test_documents.py`, `PL/tests/fixtures/ap_policy.md` (copy of `docs/examples/policy_samples/accounts_payable_policy.md`), `PL/tests/fixtures/ap_policy.pdf` (made once from the Markdown with any local tool and checked in), `PL/tests/fixtures/ap_set/` (the AP policy split into `sop.md`, `appendix.md`, and `update_2026.md`, a short update that supersedes one clause)
- Modify: `PL/builder.py` (move `Section` and `split_policy` into `documents.py`; keep a re-export)

**Interfaces:**
- Consumes: Task 1 model.
- Produces: `load_document(source: str | Path, kind: str = "auto", meta: dict | None = None) -> Document` (Markdown/text directly; PDF/DOCX/HTML through docling; sections by numbering and headings; statements by bullet, sentence and table row; page kept for PDF); `load_policy_set(sources: list, meta: dict | None = None) -> PolicySet` (`meta` per source: `trust`, `effective_date`, `authority_rank`); `document_from_text(text: str, kind: str, source: dict, trust: Trust) -> Document` (for system prompts and online records).

- [ ] **Step 1: Write the failing tests**

```python
def test_markdown_sections_keep_numbered_ids(): ...          # "4.2" and "8.1" in section ids; preamble is a section
def test_pdf_and_markdown_give_the_same_statements(): ...     # same statement texts (whitespace-normalised); PDF statements have page >= 1
def test_table_rows_are_statements(): ...
def test_policy_set_keeps_meta_and_hash(): ...                # 3 docs, version changes when one doc changes
def test_split_policy_still_importable_from_builder(): ...
```

- [ ] **Step 2: Run; expect failures**
- [ ] **Step 3: Implement `documents.py`**
- [ ] **Step 4: Run all package tests; expect PASS** (the 31 existing tests must still pass)
- [ ] **Step 5: Checkpoint**

## Phase 2 — Classify and handle by type

### Task 3: Statement type classifier

**Files:**
- Create: `PL/classify.py`, `PL/llm.py`, `PL/tests/test_classify.py`
- Modify: `PL/builder.py` (`openai_json_model` moves to `llm.py`, re-exported)

**Interfaces:**
- Produces: `classify(document: Document, model: Callable[[str, str], str], tool_catalog: str) -> list[CoverageItem]` (sets `Statement.types` and `modality` in place; returns notes for the coverage report); `llm.py`: `openai_json_model(model: str, base_url: str | None = None, api_key_env: str = "OPENAI_API_KEY", timeout: float = 90.0)` and `openrouter_json_model(model: str)`; both carry `.usage` and `.model_name`.
- Table rows are typed by shape in code (enum table → `allowed_values`, input→output table → `lookup_matrix`, "a → b" lists → `state_transition`) with no model call. Prose is classified in one model call per section.

- [ ] **Step 1: Write the failing tests** (FakeModel returns canned JSON)

```python
def test_tables_are_typed_without_a_model_call(): ...          # model.calls == 0 for a section with only a matrix
def test_prose_types_and_modality_from_model(): ...
def test_unknown_type_from_model_becomes_open_judgment_with_note(): ...
def test_model_error_or_bad_json_falls_back_to_open_judgment(): ...   # Review Focus 5
```

- [ ] **Step 2: Run; expect failures**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run; expect PASS**
- [ ] **Step 5: Checkpoint**

### Task 4: Handlers for tables and prose rules, and new rule types

**Files:**
- Create: `PL/handlers/__init__.py`, `PL/handlers/tables.py`, `PL/handlers/prose.py`, `PL/tests/test_handlers.py`
- Modify: `PL/builder.py` (`code_rules` moves to `handlers/tables.py`), `PL/ruleset.py` (new rule types)

**Interfaces:**
- Produces: `table_rules(statements: list[Statement], specs: list[dict]) -> list[Rule]`; `prose_rules(statements: list[Statement], specs: list[dict], model) -> tuple[list[Rule], list[CoverageItem]]`; `ROUTE: dict[StatementType, str]` (handler per type, overridable by `method_choice.json`).
- New rule types in `ruleset.py` (added to `RULE_TYPES` and the module table):
  - `record_condition`: slots `tools`, `field`, `op` (`contains|equals|in|gt|lt|empty`), `value`, `effect` (`forbid`). Checker: code, on the records that the call names (Task 9 `facts.py`). Serves `eligibility_filter` and `prohibition` when the condition is a field test.
  - `threshold`: slots `tool`, `arg`, `op` (`gt|ge|lt|le`), `value`, `then` (`forbid` or `requires_approval`).
  - `format`: slots `tool`, `arg`, `pattern` (regex).
- Statement types without a compiled handler (`routing`, `deadline`, `open_judgment`, and any prose rule whose slots fail validation) become a `Rule` whose rule dict is `{"type": "verify", "statement": <text>, "tools": [...] or []}`; `verify` is added to `RULE_TYPES` and checked by the verifier (Task 9).

- [ ] **Step 1: Write the failing tests**

```python
def test_matrix_and_transition_rules_unchanged_on_itsm_policy(): ...  # same rules as today's code_rules on docs/analysis/samples/enterpriseops-gym/itsm_policy.md
def test_record_condition_from_filter_statement(): ...                # "skip units whose Notes contain an FSR- code" → field=Notes, op=contains, value="FSR-"
def test_threshold_rule_slots(): ...
def test_format_rule_pattern_compiles(): ...
def test_unvalidated_prose_rule_becomes_verify_rule(): ...
def test_new_rule_types_enforced_by_ruleset(): ...                    # RuleSetHooks denies a threshold breach, a bad format; allows otherwise
```

- [ ] **Step 2–4: Run (fail) → implement → run (pass)**
- [ ] **Step 5: Checkpoint**

### Task 5: Links, definitions and exceptions

**Files:**
- Create: `PL/handlers/links.py`, `PL/tests/test_links.py`

**Interfaces:**
- Produces: `find_links(policy_set: PolicySet, model=None) -> tuple[list[Link], list[CoverageItem]]`; `fold_exceptions(rules: list[Rule], links: list[Link]) -> list[Rule]` (adds `rule["unless"] = [{"condition": str, "source": dict}]`).
- Code finds: `§4.3`, "section N", "Appendix X", "page N", a document title of the set, "supersedes", "takes precedence over", defined terms (bold or "means"/"is defined as"). The model only proposes `exception_of` / `supersedes` / `source_of_truth` links; a proposed link is kept only if both ends exist. A pointer whose target does not exist becomes a coverage item, never a rule.

- [ ] **Step 1: Write the failing tests** (AP fixture and `ap_set/`)

```python
def test_section_reference_link(): ...                 # §4.2 step 3 refers_to §4.3
def test_exception_folded_into_rule(): ...             # §8.1 exception_of §4.2 step 3 → rule.unless has the §8.1 condition
def test_cross_document_supersedes(): ...              # update_2026.md supersedes the clause in sop.md
def test_dangling_reference_is_coverage_item(): ...    # "Appendix Z" → CoverageItem(kind="dangling_link")
def test_model_link_without_target_is_dropped(): ...
```

- [ ] **Step 2–4: Run (fail) → implement → run (pass)**
- [ ] **Step 5: Checkpoint**

### Task 6: Procedures as step graphs, and the procedure monitor

**Files:**
- Create: `PL/handlers/procedures.py`, `PL/procedure_monitor.py`, `PL/tests/test_procedures.py`

**Interfaces:**
- Produces: `procedures(statements: list[Statement], specs: list[dict], model=None) -> list[Procedure]` (numbered steps → `Step(action_tool | "reply", required, condition)`; edges `next`; trigger = first step's tool or a request condition); `ProcedureMonitor(procedures: list[Procedure], tools_in_run: list[str] | None)` (an `AgentHooks`): `after_tool_call` advances the state; `before_llm_call` returns "Next required step: …" for an active procedure; `before_reply` returns a follow-up listing missing required steps, once per thread; out-of-order steps are recorded as `order_warning`, never denied. Steps whose tool is not in `tools_in_run` are skipped (Review Focus 1).

- [ ] **Step 1: Write the failing tests**

```python
def test_numbered_sop_becomes_three_steps_with_next_edges(): ...
def test_reminder_names_next_required_step_after_trigger(): ...
def test_reply_follow_up_lists_missing_required_step_once(): ...
def test_out_of_order_is_warning_not_deny(): ...
def test_step_with_tool_not_in_run_is_skipped(): ...
```

- [ ] **Step 2–4: Run (fail) → implement → run (pass)**
- [ ] **Step 5: Checkpoint**

## Phase 3 — Validate, build, CLI and skill

### Task 7: Validators

**Files:**
- Create: `PL/validate.py`, `PL/tests/test_validate.py`
- Modify: `PL/builder.py` (its `validate()` moves here)

**Interfaces:**
- Produces: `validate_build(build: PolicyBuild, specs: list[dict]) -> list[ValidationError]` where `ValidationError(statement_id: str, code: str, message: str)`; codes: `unknown_tool`, `unknown_arg`, `value_not_in_enum`, `quote_not_verbatim`, `cedar_invalid`, `link_target_missing`, `statement_uncovered`, `bad_pattern`; `diff_builds(a: PolicyBuild, b: PolicyBuild) -> list[str]` (statement ids whose rules differ).

- [ ] **Step 1: Write one failing test per error code, plus `test_diff_builds_flags_changed_statement`**
- [ ] **Step 2–4: Run (fail) → implement → run (pass)**
- [ ] **Step 5: Checkpoint**

### Task 8: Builder, CLI and the policy compiler skill

**Files:**
- Modify: `PL/builder.py`
- Create: `PL/cli.py`, `PL/skill/SKILL.md`, `PL/README.md`, `PL/tests/test_builder.py`, `PL/tests/test_cli.py`
- Modify: `~/dev/cuga-eval/benchmarks/enterpriseops_gym/build_rules.py` (default model `aws/gpt-oss-120b`; call `build_policy_set`)

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces: `build_policy_set(policy_set: PolicySet, specs: list[dict], model, cache_dir: Path | None = None, repair_rounds: int = 2, generator: dict | None = None) -> PolicyBuild` (Task 1 dataclass); the repair loop resends only failing statements with their `ValidationError` messages; the cache key is the section hash plus the prompt version. `build(policy: str, specs, model=None, cache_dir=None) -> BuildResult` stays as a wrapper (same output shape as today). CLI: `python -m cuga.policy_layer.cli convert <files...> -o set.json`, `build set.json --tools tools.json -o build.json [--model M]`, `validate build.json --tools tools.json`, `coverage build.json`; exit code 1 when validation errors remain.
- `SKILL.md`: harness-neutral steps (convert → read sections → classify → link → write `build.json` per `MODEL.md` → `validate` → fix → `coverage`), only plain files and the CLI; states that the output must record `generator.kind = "skill"`, the harness and the model.

- [ ] **Step 1: Write the failing tests**

```python
def test_build_ap_set_end_to_end_with_fake_model(): ...        # no validation errors; every statement in coverage
def test_repair_loop_fixes_one_bad_slot(): ...                 # round 1 unknown_arg → round 2 ok; model called again only for that statement
def test_rebuild_after_one_section_change_hits_cache_elsewhere(): ...
def test_build_wrapper_matches_pilot_rule_counts(): ...         # code-only build of the 5 pilot ITSM versions == code rules in benchmarks/enterpriseops_gym/rules/<hash>.json
def test_cli_validate_exit_codes(): ...                          # subprocess; 0 on the valid fixture build, 1 on a broken one
```

- [ ] **Step 2–4: Run (fail) → implement → run (pass)**
- [ ] **Step 5: Run `build_rules.py --pilot --no-model` and compare rule counts with the saved pilot files; expect equal**
- [ ] **Step 6: Checkpoint**

### Task 9: Runtime: facts, verifier fallback, method choice

**Files:**
- Create: `PL/facts.py`, `PL/verifier.py`, `PL/tests/test_runtime.py`
- Modify: `PL/ruleset.py`, `PL/intake.py` (move `call_tokens`, `_remember`, `_facts_for` into `facts.py`; both use it)

**Interfaces:**
- Produces: `FactStore` with `add(tool: str, result: Any)`, `for_call(args: dict, budget: int = 8000) -> str` (records naming identifiers from the call first, then recent data), `recent(chars: int) -> str`, `records_for(args) -> list[dict]`; `call_tokens(args) -> list[str]` (unchanged behaviour); `Verifier(model, may_deny: Callable[[str], bool])` with `check(request: str, statements: list[dict], tool: str, args: dict, facts: str) -> Verdict` (errors → `Verdict(outcome="allow", reason="verifier_error")`); `RuleSetHooks(..., method_choice: dict | None = None, verifier: Verifier | None = None)`: order code → Cedar → monitor → verifier; a `verify` rule or a type marked remind-only goes to the brief instead of denying; `method_choice.json` format: `{"<statement_type>": {"checker": "code|cedar|verifier|kev", "model": str | null, "may_deny": bool, "measured": bool}}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_record_condition_uses_records_named_in_call(): ...   # FE-103 Notes empty → allow; FE-111 with FSR- → deny
def test_rule_for_tool_not_in_run_never_denies(): ...         # Review Focus 1
def test_verifier_error_allows_and_records(): ...             # Review Focus 5
def test_remind_only_type_goes_to_brief_not_deny(): ...
def test_method_choice_routes_type_to_checker(): ...
```

- [ ] **Step 2–4: Run (fail) → implement → run (pass)**; the 31 earlier tests still pass
- [ ] **Step 5: Re-run the operations and marketing replays (`benchmarks/automationbench/intake_replay.py`) with the moved code; expect the same verdicts as on 2026-11-01 (FE-103 allow 5/5; reply follow-up 3/3)**
- [ ] **Step 6: Checkpoint**

### Task 10: Online intake on the shared model

**Files:**
- Modify: `PL/intake.py`, `PL/detectors.py`, `~/dev/cuga-eval/benchmarks/automationbench/run_cuga.py`
- Test: `PL/tests/test_intake.py`

**Interfaces:**
- Consumes: Tasks 1–9.
- Produces: `OnlinePolicyIntake(model, detector=None, detect_threshold=0.47, method_choice=None, ...)`: extraction writes `Statement`s (with types) into an overlay `PolicySet` (`Document` per record, trust from extraction); structured records (sheet rows of rules) go through `table_rules` with no model call; prose statements go through `prose_rules` when they validate, else become `verify` rules; `supersedes` / `source_of_truth` become links; policies in the user's request (`on_user_message`) go to extraction directly. `MAX_DETECT_RECORDS = 200` per tool output. `run_cuga.py --arm B` builds the intake with `systemone_detector()` and the `method_choice.json` path from `POLICY_METHOD_CHOICE`.

- [ ] **Step 1: Write the failing tests**

```python
def test_rule_sheet_compiles_without_model_call(): ...
def test_request_policy_becomes_overlay_rule(): ...               # "link an SLA only if none is linked"
def test_untrusted_supersedes_is_not_enforced(): ...              # Review Focus 3
def test_detector_capped_on_huge_output(): ...                    # 500 text records → detector sees 200; no exception (Review Focus 4)
def test_source_of_truth_link_puts_winning_record_first(): ...
```

- [ ] **Step 2–4: Run (fail) → implement → run (pass)**
- [ ] **Step 5: Checkpoint**

## Phase 4 — Measurement (cuga-eval `benchmarks/policy_eval/`)

### Task 11: Task selection

**Files:**
- Create: `PE/select_tasks.py`, `PE/tests/test_select_tasks.py`, output `PE/policy_eval_tasks.json`

**Interfaces:**
- Produces: `policy_eval_tasks.json` = `{"seed": 20261101, "rules": {...text...}, "itsm": {"tune": [10 ids], "unseen": [10 ids]}, "automationbench": {"tune": [10], "unseen": [10]}, "xref": {"automationbench": [5 names], "itsm": [2 ids]}}`.
- ITSM rule: user prompt matches `\b(resolv\w*|clos\w*|on hold|transition\w*|change request\w*|sla\w*|approv\w*)\b` (41 of 103), minus the 5 tasks in `enterpriseops_gym/tasks/pilot.json`, minus the 2 broken-verifier tasks excluded in `select_pilot.py`, minus the 2 xref ITSM tasks (one task each on policy versions `cb2d4ee021` and `c47f8ceef3`, picked by seed).
- AutomationBench rule: tasks in the detector-probe pool with a Gemini-labelled policy record (`results/detector_probe/labels.jsonl`), at least one rubric check with `negative: true`, not a pilot task, not an xref task (`operations.twilio_afterhours_incident`, `operations.sheets_asana_approved_request`, `marketing.customer_feedback_aggregation`, `hr.benefits_enrollment_review`, `marketing.hashtag_performance`); tune from the probe's tune half, unseen from its test half (`_split` in `detector_probe.py`); at most 2 per domain.

- [ ] **Step 1: Write the failing tests** (`test_deterministic`, `test_no_overlap_between_sets`, `test_pilot_and_xref_excluded_from_unseen`, `test_at_most_two_per_domain`, `test_unseen_ab_from_test_half`)
- [ ] **Step 2–4: Run (fail) → implement → run (pass)**
- [ ] **Step 5: Generate `policy_eval_tasks.json` before any run; checkpoint**

### Task 12: Gold rule sets (skill + review by the user)

**Files:**
- Create: `PE/gold/<policy_id>.json` (ITSM policy versions used by the tuning tasks; the policy records of the 10 AutomationBench tuning tasks), `PE/gold/README.md`

- [ ] **Step 1: Run the skill (`PL/skill/SKILL.md`) in Claude Code on each tuning policy; output must pass `cli validate`**
- [ ] **Step 2: The user reviews each gold build (coverage report + rules); record the review date in `gold/README.md`. This step needs the user.**
- [ ] **Step 3: Checkpoint**

### Task 13: Check set and method comparison

**Files:**
- Create: `PE/checkset.py`, `PE/compare_methods.py`, `PE/decide.py`, `PE/tests/test_decide.py`; outputs `PE/checkset.jsonl`, `PE/method_comparison.md`, `PE/method_choice.json`

**Interfaces:**
- Produces: check case `{"id", "type": StatementType, "statement": str, "tool": str, "args": dict, "records": str, "label": "allow"|"deny", "origin": "run"|"perturbed"|"hand", "task": str}` from tuning tasks only (pilot and tuning-run tool calls labelled by their graded outcome; one-argument perturbations that break one gold statement; writes that follow an untrusted override, labelled deny; 20+ hand-checked); `decide(results: dict[type, dict[method, Metrics]]) -> dict` implementing the Global Constraints decision rule; `compare_methods.py --methods code,cedar,aws/gpt-oss-120b,openai/gpt-oss-20b,openai/gpt-oss-safeguard-20b,kev,gcp/gemini-3.8-flash` writes accuracy, false deny rate, violations caught, p50/p95 latency and cost per type; ledger entries per method.

- [ ] **Step 1: Write the failing tests for `decide`** (`test_fd_above_2pct_is_remind_only`, `test_cheaper_within_2_points_wins`, `test_under_10_cases_keeps_default`, `test_gemini_never_chosen`)
- [ ] **Step 2–4: Run (fail) → implement → run (pass)**
- [ ] **Step 5: Build the check set (about 200 cases); report per-type counts**
- [ ] **Step 6: Run the comparison; write `method_comparison.md` and `method_choice.json`; checkpoint**

### Task 14: Generator comparison

**Files:**
- Create: `PE/compare_generators.py`; output `PE/generator_comparison.md`

- [ ] **Step 1: Build each tuning policy with (a) the pipeline + gpt-oss-120b, (b) the skill run by CUGA with gpt-oss-120b, (c) the skill run by Claude Code**
- [ ] **Step 2: Score each against gold: statements covered, type accuracy, slot accuracy, links found, validator errors before repair, time, cost**
- [ ] **Step 3: Pick the generator for arm B (open model only); write the table; checkpoint**

## Phase 5 — Evaluation

### Task 15: Runners, trajectories and report

**Files:**
- Modify: `~/dev/cuga-eval/benchmarks/enterpriseops_gym/run_cuga_eog.py`, `~/dev/cuga-eval/benchmarks/automationbench/run_cuga.py`
- Create: `PE/report.py`, `PE/tests/test_report.py`

**Interfaces:**
- Both runners: `--set {tune,unseen,xref}` reads `policy_eval_tasks.json`; `--trial N`; arm B loads the chosen build (`PE/builds/<version>.json`) and `method_choice.json`; trajectories saved (`cuga_folder` kept per task; tracker on); a run that loses the gateway is marked `infra_error` and re-run, not scored.
- `report.py`: primary metrics per arm and set; task-by-task paired table over 3 trials; denies, false denies (a denied write the grader needed), follow-ups; tier 0 / tier 1 / extraction / verifier latency p50 and p95 against the Global Constraints targets; cost; xref table (per reference: target fetched? used? graded value right?); list of changes made after tuning runs (read from `PE/changes.md`).

- [ ] **Step 1: Write failing tests for `report.py` on two fake result files** (`test_primary_metrics`, `test_false_deny_counted`, `test_infra_error_not_scored`)
- [ ] **Step 2–4: Run (fail) → implement → run (pass)**
- [ ] **Step 5: Smoke: 1 task per benchmark, both arms; trajectories present; ledger updated**
- [ ] **Step 6: Checkpoint**

### Task 16: Tuning, freeze, unseen runs, write-up

- [ ] **Step 1: Tuning set, 1 trial, both arms; analyse failures (analyze-cuga-trajectory method); general fixes only, each listed in `PE/changes.md`**
- [ ] **Step 2: Freeze: record the sha256 of `PL/` files, the build versions and `method_choice.json` in `PE/freeze.json`; no code change after this**
- [ ] **Step 3: Unseen set, 3 trials, both arms; xref set, 1 trial, both arms**
- [ ] **Step 4: `report.py` → `PE/report.md`; add the results to `docs/analysis/policy-flow.html` (section 5) and `history.md`; update the memory file**
- [ ] **Step 5: Show the user the report; checkpoint**
