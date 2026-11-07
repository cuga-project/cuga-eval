# Policy Architecture Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One stable policy system and one clean environment: one package format, one config, one runtime, one runner, full compile coverage and obligations measured by replay, so that experiments start from a fixed base.

**Architecture:** Existing components stay and move behind one registry. New parts: `package.py`, `policy_config.py`, `runtime.py`, `obligations.py`, `levels.py`, `router.py` in the gate repo; `policy_eval/harness/` in cuga-eval. Migration is by parity: old wiring and new wiring must produce the same hooks, and saved results must reproduce known numbers, before old code is removed.

**Tech Stack:** Python 3.12, CUGA hooks, cedarpy, PyYAML, pytest, LiteLLM gateway (gpt-oss-120b, DeepSeek-V4-Pro), Kev-4B via OpenRouter.

**Spec:** `docs/superpowers/specs/2026-11-04-policy-system-design.md`

## Global Constraints

- Never push. Commit locally only. No attribution lines in commits.
- Approving this plan is the request to commit its work locally. Commit as each task says, not before.
- Never touch `~/dev/cuga-agent`. Code work happens in `~/dev/cuga-agent-gate`.
- Never file-checkout in cuga-eval: uncommitted live files were lost that way before. Check `git diff` first.
- No task-specific fixes. No benchmark names in `policy_layer`. Log every change in `benchmarks/policy_eval/changes.md`.
- Never use grader data inside a system. Labels are for measurement only. Packages are built from policy text only.
- Secrets: never print keys or `.env`. `pick_key.py` only inside `$(...)`.
- Downloads under `~/dev/untrusted` are read-only; Python reading them runs with `-I`; scripts stay outside.
- Do not kill port 8765. Do not delete without looking at the target and, for anything not created by this plan, asking.
- **No experiment runs in this plan.** Allowed: unit tests, offline replay, 1-task smoke runs. Budget for the whole plan: at most $25; the cap stays $2,000 ($1,622 spent).
- Working style (user, overrides the TDD default): implement first, run the existing tests, add tests only where they matter. This plan names those tests.
- Any later experiment: all arms at the same time, one count per task, held-out next to tuning.

## Review Focus

1. A task whose policy version has no package (today `80cd3ebb50`, 4 tasks): the run must stop with a clear error, or follow what the profile says. It must never run silently with no rules.
2. Policy off (`baseline.yaml`, or no hooks): behavior identical to CUGA without the policy layer.
3. Old result files must still load and reproduce their reported numbers after the schema changes.
4. A follow-up must never push blocked or held work (change 64). A code tool with no literal match gives `unknown`, not `missing`.
5. A typo or unknown key in a profile is an error, not a silently ignored setting.

Each one has a test in the task that owns it: Tasks 2.2, 2.2, 2.3, 4.1 and 2.1.

## Overview

| Phase | Result | Size | Gaps closed |
|---|---|---|---|
| 0 Freeze and clean | Everything committed, one branch, durable snapshots, env files composed, task-set registry | S | Uncommitted work, stray files, volatile `/tmp` |
| 1 Policy package | One format, converters, validator with coverage and conflicts | M | Two formats; no contradiction detection |
| 2 Config, runtime, harness | One YAML, one assembly, one runner, one result schema, one report, audit log | L | 42 env switches; 4 different runners; trace in 1 of 4 |
| 3 Compile coverage | Repair in the pipeline; audit for any package; skill makes full packages; matrix filled; pipeline vs skill measured | L | Compile gaps; τ² airline and retail have no package; compiler never measured |
| 4 Obligations | Ledger, producers, replay report | M | Omissions; separate follow-ups |
| 5 Levels, priorities, retrieval | Level switch, priority classes, swappable retrieval with a test bench, rule-list route | M | Level switch; priorities; rule-list shape; fixed retrieval |
| 6 Stability gate | Shims removed, gate report, local tag, docs updated | S | — |

**Order:** 0 → 1 → 2 → (3 and 4 in parallel) → 5 → 6. Experiments are planned with the user only after phase 6.

## Spend estimate

| Item | Cost |
|---|---|
| 1-task smoke runs, 4 benchmarks × 2 profiles | ≤ $3 |
| ITSM rebuilds, repair, Kev checks | ≤ $2 |
| Decision tests by DeepSeek-V4-Pro for new packages | ≤ $8 |
| Pipeline vs skill comparison | ≤ $8 |
| Obligation replay | ≤ $4 |
| Claude skill builds | not in the ledger |

---

## Phase 0: Freeze and clean

### Task 0.1: One integrated branch in the gate repo

**Files:** everything uncommitted in `~/dev/cuga-agent-gate` (`store_gate.py`, `ruleset.py`, `validate.py`, `rule_repair.py`, `shared_nodes.py`, `graph_adapter.py`, `config.py`, `settings.toml`, tests).

- [ ] **Step 1:** `git switch -c policy/stable` from `ee4615fca`. Keep every `best/*` branch: they are the records of measured code.
- [ ] **Step 2:** Three local commits: gate evidence grounding; hook note placement setting with its tests; rule repair, `membership`, `"*"` condition with their tests.
- [ ] **Step 3:** Verify.
  Run: `.venv/bin/python -m pytest -q src/cuga/policy_layer/tests src/cuga/backend/cuga_graph/nodes/cuga_lite/tests/test_agent_graph_adapter.py`
  Expected: all pass (154 + 46); `git status --short` empty.

### Task 0.2: Clean cuga-eval

**Files:** `.gitignore`, `benchmarks/policy_eval/ENVIRONMENT.md` (new), `benchmarks/policy_eval/launchers/archive/` (new).

- [ ] **Step 1:** Ignore run logs and scratch: `benchmarks/**/*.out`, `benchmarks/**/*_parent.log`, `benchmarks/.tmp`. Move `.run_*_frozen.sh` and `.run_hbq.sh` to `launchers/archive/`.
- [ ] **Step 2:** **Stop and ask the user** about `test.py` and `boaz_internship_ibm.pdf` in the repo root (not part of this work). Do nothing to them without a yes.
- [ ] **Step 3:** Write `ENVIRONMENT.md`: repos and branches (`cuga-agent-gate policy/stable`, `cuga-eval evaluation-work`, `cuga-eval-tau2 exp/tau2-policy-runner`), venvs (3), env files, ledger, where results live, key handling without values.
- [ ] **Step 4:** Commit tools and docs locally (`rule_audit.py`, `store_gate_replay.py`, `sop_retrieval_eval.py`, `toolguard_step1.py`, launchers, ledger, `docs/analysis/*`, specs, plans), no caches.
  Run: `git status --short | wc -l`. Expected: only files waiting for the user's answer in step 2.

### Task 0.3: τ² worktree

**Files:** `~/dev/cuga-eval-tau2` (55 uncommitted entries).

- [ ] **Step 1:** List them by kind. Commit `benchmarks/tau2/cuga_runner.py` and helpers. Ignore outputs; do not delete anything without looking.
- [ ] **Step 2:** Record in `ENVIRONMENT.md` that τ² stays a separate worktree with its own venv, and why (τ² library, one worker per process).

### Task 0.4: Durable snapshots

**Files:** `benchmarks/policy_eval/snapshot_src.sh`, launchers that name `/tmp/cuga_snapshots`.

- [ ] **Step 1:** Destination becomes `~/dev/cuga_snapshots/<name>`; `SOURCE.txt` keeps sha and dirty count. A dirty tree is an error unless `--allow-dirty` is given.
  Expected: a new snapshot appears there with a clean `SOURCE.txt`. Old `/tmp` snapshots are left alone; `best/*` branches can rebuild them.

### Task 0.5: Composed env files

**Files:** `benchmarks/policy_eval/envs/{base,model.gptoss,model.dsv4,model.gemini38,bench.automationbench,bench.itsm,bench.handbook}.env`, `benchmarks/policy_eval/envs/compose_env.py` (new).

**Interfaces:** Produces `compose(model: str, bench: str, extra: dict) -> Path`, writes one env file for a child process.

- [ ] **Step 1:** Split the 20 env files into base + overlays.
- [ ] **Step 2:** Check: for every old file in use, composed values equal old values.
  Run: `python3 benchmarks/policy_eval/envs/compose_env.py --check`. Expected: no differences, or each difference listed and explained in `ENVIRONMENT.md`. Old files stay until Task 6.1.

### Task 0.6: Task-set registry

**Files:** `benchmarks/policy_eval/sets/registry.json`, `benchmarks/policy_eval/sets/build_registry.py` (new).

**Interfaces:** Each entry: `id, benchmark, path, rule, seed, n, status (tuning|heldout), seen_by {model: [run prefixes]}`.

- [ ] **Step 1:** Fill from `policy_eval_tasks*.json`, `automationbench/policy_types_*.json`, τ² set files; compute `seen_by` by scanning results.
  Expected: the script prints, per model, which held-out sets are still unseen. `policy_types_holdout2.json` now shows Gemini and gpt-oss as seen, and `telecom_fresh40.json` as unseen.

### Task 0.7: Remove the old prototype

**Files:** `policy_layer/{gate,sdk_hooks,graph,models,checkers}.py`, `policy_layer/__init__.py` (imports them today), `tests/test_policy_gate.py`, `examples/`, `docs/examples/policy_gate_itsm/` (`run_demo.py` and `chat_app.py` use them).

- [ ] **Step 1:** Confirm by search that no runner or kept module imports them; note what `examples/` needs. `cedar_engine.py` stays (used by `ruleset.py`).
- [ ] **Step 2:** Delete them, their tests and the `policy_gate_itsm` demo (git history keeps them). If a kept module needs one small helper, move the helper.
  Run: the policy-layer suite. Expected: all remaining tests pass.

---

## Phase 1: Policy package

### Task 1.1: Package model and converters

**Files:** Modify `policy_layer/model.py`. Create `policy_layer/package.py`, `tests/test_package.py`, `benchmarks/policy_eval/tools/convert_all.py`.

**Interfaces:**
- Produces in `model.py`: `Obligation`, `PolicyPackage`; `Rule` gains `cls` (hard, judgment, guidance) and `level`; `Step` gains `text` (graph steps are strings, build steps have `action`); `Procedure` gains `applies_when, inputs, decisions, must_not, deadlines, links, notes, priority, category, src, extra`; `Document` gains `priority_class`.
- Produces in `package.py`: `load_package(path) -> PolicyPackage`, `save_package(pkg, path)`, `from_build(build: dict) -> PolicyPackage`, `to_build(pkg) -> dict`, `from_store_graph(graph: dict, statements: list | None = None) -> PolicyPackage`, `to_store_graph(pkg) -> dict`.
- `from_build` takes a runner build file or a builder output. Top-level `rules` wins over `build.rules`, as in `rule_audit.load_rules` (`builds_v4/*.v4A.json`: 83 vs 62).

- [ ] **Step 1:** Implement per spec section 4. `may_deny: false` maps to `level: remind`.
- [ ] **Step 2:** Tests: round trip on small fixtures; `may_deny` mapping; store graph → package → store graph equal; build → package → build equal. Conversion does not merge the two formats (spec section 4).
- [ ] **Step 3:** Convert all real artifacts: `builds_v2/*`, `gold/*.build.json`, `gold/ab/*/build.json`, `builds_handbook/v3/*`, `builds_handbook/v4/*`, `builds_v4/*`, `graphs_handbook/claude_v1/*.json`, `tau2/builds/telecom.json` into `benchmarks/policy_eval/packages/<bench>/<id>/<source>/package.json`. The `<source>` level keeps legacy artifacts separate.
  Run: `python -I benchmarks/policy_eval/tools/convert_all.py`. Expected: each artifact returns to its own format with `dropped fields: 0`.

### Task 1.2: Components read the package

**Files:** Modify `ruleset.py`, `procedure_store.py`, `procedure_guide.py`, `sop_loop.py`, `sop_navigator.py`, `store_gate.py`.

**Interfaces:** Consumes `PolicyPackage`. Produces a `from_package(pkg, ...)` constructor on each component; old inputs still work until Task 6.1.

- [ ] **Step 1:** Implement. `RuleSetHooks` reads `level`; `ProcedureStore` gets the same strings from the package as from the graph.
- [ ] **Step 2:** Parity on real data.
  Run: `policy_eval/rule_audit.py tests-run` and `replay` with package inputs. Expected: `v4A` 84 + 20 = 104 of 182 caught, 1 false deny; `passed_runs_with_deny` 2 of 93; `failed_runs_with_deny` 10.
  Check: `ProcedureStore.list_procedures()` and `get_procedure()` return identical text from the graph and from the package, for all 3 HANDBOOK graphs.

### Task 1.3: Package validator

**Files:** Modify `validate.py`, `cli.py`; test in `tests/test_validate.py`.

**Interfaces:** Produces `validate_package(pkg, tool_specs) -> List[ValidationError]`, new codes `rule_conflict`, `coverage_incomplete`, `rule_no_trigger`, `unfilled_slot`; CLI `python -m cuga.policy_layer.cli validate <package> --tools tools.json`.

- [ ] **Step 1:** Implement spec sections 9 and 10. Conflict by code: same tool and argument, overlapping `when`, disjoint values; required vs forbidden. A tie on date and rank drops both rules to `remind` and adds a policy question.
- [ ] **Step 2:** Tests on fixtures for each new code, including a conflict that date or rank resolves and one that it does not.
- [ ] **Step 3:** Run on all converted packages; write the findings to `packages/VALIDATION.md`.
  Expected: known items appear (the two `resolution_code` schema conflicts on ITSM; verify rules with no tool in `builds_v2`). No crash.

---

## Phase 2: Config, runtime, harness

### Task 2.1: Policy config

**Files:** Create `policy_layer/policy_config.py`, `tests/test_policy_config.py`, `benchmarks/policy_eval/profiles/{baseline,<one per best profile>}.yaml`.

**Interfaces:** Produces `PolicyConfig`, `load_config(path) -> PolicyConfig`, `config_from_env(env, bench) -> PolicyConfig` (migration only; maps all 42 `POLICY_*`, `SOP_*`, `HOOKS_*`, `HB_*` switches, table in its docstring).

- [ ] **Step 1:** Implement spec section 12. Unknown keys raise an error naming the key. **Test this.**
- [ ] **Step 2:** One YAML per entry of `best_profiles.json` (7) + `baseline.yaml` + `itsm-rules.yaml` (typed rules on IT service tasks; `best_profiles.json` has no ITSM entry because nothing beat CUGA alone there, so add the entry with that note). Best profiles list their components explicitly (`on` / `off`), never `auto`.
  Test: for each profile, `config_from_env(<its switches from best_profiles.json>)` equals `load_config(<its yaml>)`.

### Task 2.2: Runtime assembly

**Files:** Create `policy_layer/runtime.py`, `tests/test_runtime.py`, `benchmarks/policy_eval/profiles/golden_hooks.json`.

**Interfaces:**
```python
@dataclass
class RunContext:  # task_id, request, system_prompt, tool_specs, tools_in_run, principal, world_time, data_search, out_dir
@dataclass
class RuntimeParts:
    hooks: list; tools: list; system_note: str
    run: Callable | None          # replaces agent.invoke (SOP loop)
    turn_note: Callable | None    # note added to each user turn (SOP tracker)
    wrap_tools: Callable | None   # guards tools before the agent is built (navigator hand-off)
    after_reply: Callable | None  # may return a new prompt instead of sending the reply (navigator hand-off in text)
    usage: Callable[[], dict]; records: Callable[[], list]
def build_runtime(cfg: PolicyConfig, pkg: PolicyPackage | None, ctx: RunContext) -> RuntimeParts
COMPONENTS: dict[str, Component]  # name -> factory; adding a method = one entry
```

- [ ] **Step 1:** Capture `golden_hooks.json`: for each profile, a description of today's wiring: hook classes, their visible attributes, which `RuntimeParts` slots are used (the SOP tracker and navigator profiles create no hooks), and model name, `timeout` and `max_tokens`. These are hidden in closures in `llm.py`, so the dry-run path uses a recording model factory. No agent or model calls.
- [ ] **Step 2:** Move the wiring from the 4 runners into `COMPONENTS`. Runner differences become parameters: the IT service runner seeds the gate with the request (`gate.seed_request`), HANDBOOK does not. `build_runtime` runs inside each task's child process, in that benchmark's venv, with the gate source on its path.
- [ ] **Step 3:** Tests: every profile → the same description as the golden file. `baseline` → empty hooks, tools, note and slots. A profile that needs a package with none available → error naming task and policy version (Review Focus 1).

### Task 2.3: One runner, one result schema, one report

**Files:** Create `benchmarks/policy_eval/harness/{run.py,result.py,report.py}`, `harness/adapters/{automationbench,itsm,handbook,tau2}.py`.

**Interfaces:**
```python
class BenchmarkAdapter(Protocol):
    python: Path                                   # venv of this benchmark
    def task_ids(self, set_id: str) -> list[str]: ...
    async def prepare(self, task_id: str) -> RunContext: ...
    async def run(self, parts: RuntimeParts, ctx: RunContext, timeout: float) -> RawOutcome: ...
    async def grade(self) -> Score: ...
    def close(self) -> None: ...
```
`result.py`: `{benchmark, task, profile, trial, run, agent_model, gate_model, code_sha, profile_hash, package_version, score: {primary, partial, pass, guardrails_broken}, verdicts, obligations, usage_by_component, cost_usd, wall_s, error, trajectory}`, plus `from_legacy(path) -> Result` for the old formats (AutomationBench, ITSM, HANDBOOK, τ²).
CLI: `run.py --bench B --profile P --set S --trial T --run R -j N`.

- [ ] **Step 1:** Implement. Parent logic comes from `run_many` in `run_cuga_eog.py`; adapters reuse the benchmark logic of the old runners; τ² runs as a subprocess in its own worktree and venv.
- [ ] **Step 2:** Ledger: `costs.record` refuses usage with no model name (a missing name today prices it as Gemini). Usage is recorded per component.
- [ ] **Step 3:** Reproduce known numbers from saved files only. **This is the regression test for Review Focus 3.**
  Run: `report.py --runs ph_AF ph_B4TF`; `--runs pq_AF pq_B4TF pq_B4TFM`; `--runs hbq_A hbq_GR hbq_GW`; `--runs <τ² test1,test2 arms>`.
  Expected: +18.9, 24/6, p = 0.001; +8.8, 14/6/11, p = 0.115 and +4.6, 13/9/9; 49 / 51 / 54 of 153; 63.8% → 76.2%, 9/3, p = 0.146.
- [ ] **Step 4:** Smoke: 1 task per benchmark with `baseline` and the benchmark's best profile (`itsm-rules` for IT service tasks).
  Expected: 8 result files in the common schema with `code_sha` set; ledger grows by ≤ $3.

### Task 2.4: Trace and audit everywhere

**Files:** Modify `trace.py`, `runtime.py`.

- [ ] **Step 1:** `build_runtime` wraps every model and Kev call with the trace, for all benchmarks. Each run writes `audit.jsonl`: time, hook, tool, rule id, class, level, checker, verdict, evidence, source, package version.
- [ ] **Step 2:** Test: a scripted run with one deny and one remind gives both lines with rule id and version.

---

## Phase 3: Compile coverage

### Task 3.1: Repairs inside the pipeline

**Files:** Modify `builder.py`, `handlers/prose.py`, `rule_repair.py`; `benchmarks/enterpriseops_gym/build_rules.py`.

- [ ] **Step 1:** `build_policy_set` runs role grants (default `remind`), `attach_verify_tools`, `retype_verify` with `partial_update_overreach`. Remove `map_verify_tools` (measured no gain). Coverage uses the outcomes of spec section 9.
- [ ] **Step 2:** Rebuild all 9 ITSM versions, including `80cd3ebb50`, with gpt-oss.
  Expected: 9 of 9 validate. On `e2891a7b98`: at least 104 of 182 caught with 1 false deny on the existing tests, 2 of 93 passed runs denied. Cost ≤ $1.

### Task 3.2: Audit for any package

**Files:** Modify `benchmarks/policy_eval/rule_audit.py` (remove the hard-coded version and ITSM paths).

**Interfaces:** `rule_audit.py <method> --package P --tools T [--runs G]`; methods `static, tests-gen, tests-run, backtrans, replay, cedar, report`; `report` writes `<package dir>/AUDIT.md` with the two parts of spec section 9.

- [ ] **Step 1:** Implement; move the Cedar validator and batch check (372-request check) into method `cedar`. Tests stored in the package. Tool schema layer always counted. Result file names always include the build name (the old name lost one result).
- [ ] **Step 2:** Re-run on `e2891a7b98`.
  Expected: the table in `docs/analysis/2026-11-04-graph-and-rule-testing-research.md` section 3 reproduces for code-only numbers. Verifier numbers may move a little between runs (71 vs 65 seen); report the spread.

### Task 3.3: Claude skill makes full packages

**Files:** Modify `policy_layer/skill/SKILL.md`, `cli.py`, `MODEL.md`.

- [ ] **Step 1:** Skill steps after rules: mark rule classes; write procedures (cards, decisions, must-not rules, templates, links; pattern from `graphs_handbook/claude_v1/*_graph.py`); write obligations with value origins; list policy questions; write blind decision tests by a separate agent; run `cli validate`.
- [ ] **Step 2:** Hard rule inside the skill: read the policy text only; never rubrics, tests, verifiers or grader output. New rule types only per spec section 4.
- [ ] **Step 3:** Try it on Crestwood. Expected: a package that validates; each must-not rule of `claude_v1/hr_crestwood...json` is present.

### Task 3.4: Fill the coverage matrix

**Files:** Create `benchmarks/policy_eval/packages/COVERAGE.md`, packages per row.

| Benchmark | Input | Output |
|---|---|---|
| HANDBOOK, 3 public tasks | `claude_v1` graphs + SOP text (untrusted folder, read-only) | Package with obligations |
| ITSM `e2891a7b98` | Gold build + policy text | Package with obligations |
| ITSM, other 8 versions | Base package + text differences | Packages; reuse what did not change |
| τ² Telecom | Manual, `telecom.json`, workflow file noted | Package |
| τ² airline, retail | Policy text | New packages |
| AutomationBench, 10 tuning tasks | Gold builds | Audit only; runtime stays online intake |

- [ ] **Step 1:** Run the skill per row, one fresh agent per document.
- [ ] **Step 2:** `rule_audit.py report` per package. τ² replay uses saved runs where they exist.
- [ ] **Step 3:** `COVERAGE.md`: per package: statements, outcomes, rules per class, procedures, obligations, questions, both audit parts.
  Expected: no empty row; every open ambiguity is in `policy_questions`, including ITSM roles and priority.

### Task 3.5: Pipeline vs skill

**Files:** Create `benchmarks/policy_eval/tools/pipeline_vs_skill.py`, `packages/PIPELINE_VS_SKILL.md`.

- [ ] **Step 1:** Run `builder.py` and `procedure_compiler.py` (never measured) with gpt-oss, and with DeepSeek-V4-Pro as the largest open model, on the same documents.
- [ ] **Step 2:** Compare with the spec's bar: catches within 5 points, false denies not higher, must-not recall ≥ 80%, plus procedure recall and cost per document.
  Expected: one row per benchmark saying whether the pipeline can replace the skill today. Cost ≤ $8. This is a measurement; nothing switches automatically.

---

## Phase 4: Obligations

### Task 4.1: Ledger

**Files:** Create `policy_layer/obligations.py`, `tests/test_obligations.py`.

**Interfaces:** `ObligationLedger(AgentHooks)`, `bind_cases(model, request, reads, cards) -> list[Case]`, `match(ob, write_log) -> status`, `resolve_values(ob, case, store) -> dict`, `follow_up_text(open_items) -> str`.

- [ ] **Step 1:** Implement spec section 5. The ledger acts only at the final reply (one request: `before_reply`; SOP loop: its finish turn; conversation: a hand-off). Items per case; `duty` opens at its trigger; `request` opens at the user message. Holds attach by action.
- [ ] **Step 2:** Tests where a mistake would cost most:
  - a missing write gives a follow-up with its known values;
  - **a blocked call with no successful retry makes its matching items `held`; a successful retry clears it; the follow-up restates the hold**;
  - a case hold from the binding call needs quoted evidence, otherwise `unknown`, not sent;
  - `before_reply` during SOP-loop phases and ordinary conversation turns does nothing;
  - a hand-off tool call is blocked once with the open items;
  - a code tool without a literal match gives `unknown` and is not sent;
  - an inferred value is never called wrong; a `literal` mismatch is;
  - an unbound item is never shown;
  - `max_follow_ups` is respected;
  - at level 0 and 1 nothing is sent.

### Task 4.2: Producers and retirement

**Files:** Modify `deliverables.py`, `ruleset.py`, `procedure_monitor.py`, `sop_navigator.py`, `runtime.py`; remove `store_verifier.py`.

**Interfaces:** `obligations_from_package(pkg, case)`, `obligations_from_request(model, request, specs)`, `obligations_from_duties(rules)`.

- [ ] **Step 1:** Implement producers on top of existing extraction code. On the package path only the ledger sends follow-ups. `tracker.py` and the reply check in `intake.py` stay because they are part of measured B4T-F. `sop_navigator.py` stays until the ledger matches its offline result at hand-offs (24 of 26).
- [ ] **Step 2:** Move `_acts` and `READ_FIRST` out of `store_verifier.py` (`store_gate.py` imports them) into a shared module, and add `count`, `average`, `total` as read verbs. Then remove `store_verifier.py`.
- [ ] **Step 3:** Check: B4T-F's golden description is unchanged (Task 2.2).

### Task 4.3: Replay report

**Files:** Create `benchmarks/policy_eval/obligation_replay.py`, `obligation_replay/REPORT.md`.

- [ ] **Step 1:** Replay on saved arm-A runs: HANDBOOK (`hba_*_A`, `hbq_*_A`), ITSM (A arms), τ² Telecom. Labels only for measurement.
- [ ] **Step 2:** Report per benchmark and producer: false-open rate on passed checks, recall of failed checks, **share of items with a known value origin**, cost.
- [ ] **Step 3:** Apply the rule: false-open ≤ 10% and recall ≥ 30% allows level 2; otherwise level 1. Write the choice into profiles. HANDBOOK results are in-sample and are marked so.
  Expected: a table; no live run. Cost ≤ $4.

---

## Phase 5: Levels, priorities, retrieval

### Task 5.1: Level switch

**Files:** Create `policy_layer/levels.py`, `tests/test_levels.py`; modify `runtime.py`, `ruleset.py`, `store_gate.py`.

**Interfaces:** `resolve_level(cfg, agent_model, tool) -> int`, `components_for(level, shape) -> dict[str, bool]`, `WriteChecks(AgentHooks)` (runs the write checks in order, stops at the first block).

- [ ] **Step 1:** Implement spec sections 7 and 8: static by model, `risk.level3_tools`, `auto` resolution; explicit `on` / `off` wins; `gate.min_strength`. Level 0 records would-be verdicts and stops nothing. The gate and the verifier take only `judgment` rules from a package; general statements stay guidance or code rules. Online intake (B4T-F) keeps its measured verifier path until a re-baseline says otherwise.
- [ ] **Step 2:** `components_for` applies only to components marked `auto`. New profiles use `WriteChecks`; best profiles keep separate hooks.
- [ ] **Step 3:** Tests: level × shape → components; a hard deny means the gate model is not called; every best profile still matches its golden description.

### Task 5.2: Priorities, retrieval interface and test bench

**Files:** Create `policy_layer/router.py`, `benchmarks/policy_eval/tools/retrieval_eval.py` (from `sop_retrieval_eval.py`); modify `model.py` (`resolve_conflict`), `policy_config.py`, `store_gate.py`.

**Interfaces:**
- `Router.select(query, pkg: PolicyPackage) -> list[str]` and `Expander.expand(ids: list[str], pkg: PolicyPackage) -> Scope`, where `Scope` holds procedures and rules. Both receive the whole package, so a method can walk the graph.
- Registered by name: routers `agent_opened`, `bm25`, `bm25_kev`, `llm_cards` (moved from `sop_retrieval.py` and `policy_eval/sop_retrieval_eval.py`); expanders `next_links` (from `ProcedureStore._expand`), `k_hops` (over `refers_to`, `exception_of`, `supersedes`).
- CLI: `retrieval_eval.py --package P --router R --expand E --runs G`. Output: procedure recall@1 and @3, must-not recall@5, exception recall, tokens and time per query.

- [ ] **Step 1:** `priority_classes` map to `authority_rank`; verdicts carry the package version.
- [ ] **Step 2:** `StoreGate` and the ledger read their scope from `Scope`.
- [ ] **Step 3:** Tests:
  - a class decides when dates tie;
  - `agent_opened` + `next_links` give exactly today's gate scope (`StoreGate._rules` output unchanged);
  - **a dummy router registered in the test changes the gate's scope with no other code change.** This proves a method can be swapped.
- [ ] **Step 4:** Reproduce known numbers with no model calls.
  Run: `retrieval_eval.py` with `bm25` on the labels saved in `policy_eval/sop_retrieval/result.json`. Expected: 69.2% top-1, 80.0% top-3.

New retrieval methods (PageRank over the package graph, two-stage cards, dense, wrapped GraphRAG) are experiments and belong to the plan after the gate. This task only makes them cheap to add.

### Task 5.3: Rule-list route

**Files:** Modify `ruleset.py` (brief), `levels.py`.

- [ ] **Step 1:** For rule-list sources: the brief shows each rule with its `exception_of` links; SOP tracker off by default for this shape.
- [ ] **Step 2:** Add `brief_guidance` to `RuleSetHooks` (default off, so measured profiles do not change): the brief also shows guidance rules with no tools. Today 22 of 23 in the best ITSM build never appear.
- [ ] **Step 3:** Test on a fixture: a rule with an exception shows both; guidance with no tools shows only when the switch is on. Check on the τ² airline package from Task 3.4.
  Measuring it live belongs to the experiment plan.

---

## Phase 6: Stability gate

### Task 6.1: Remove migration code

**Files:** `policy_config.config_from_env`, env reads in `policy_layer`, old runner entry points, old env files, `from_build` callers in runners.

- [ ] **Step 1:** Remove. Old runner scripts become thin calls to `harness/run.py`, or go to `launchers/archive/`.
  Run: `grep -rE 'environ.*"(POLICY|SOP|HOOKS|HB)_' src/cuga/policy_layer benchmarks/policy_eval/harness`. Expected: no matches.

### Task 6.2: Gate report

**Files:** Create `benchmarks/policy_eval/STABILITY_REPORT.md`.

- [ ] **Step 1:** Run every check below and record the output.

| # | Check | Command or evidence | Pass when |
|---|---|---|---|
| G1 | One command for all | `harness/run.py`, 4 benchmarks × `baseline` + best profile, 1 task | 8 valid result files |
| G2 | Policy off is unchanged | `baseline.yaml` test; hooks-off tests | No hooks, tools or notes |
| G3 | Config only | Grep in Task 6.1 | No policy env reads |
| G4 | Reports reproduce | Task 2.3 step 3 | All 4 number sets equal |
| G5 | Rules reproduce | `rule_audit.py` on `e2891a7b98`, code-only | ≥ 104 of 182; 1 false deny; 2 of 93 |
| G6 | Compile coverage | `COVERAGE.md`, `cli validate` on all | No empty row; no unexplained statement |
| G7 | Tests | Policy-layer, hooks, CUGA-lite suites | Pass; only the known environment failures of change 71 remain, listed by name |
| G8 | Reproducible | Result has `code_sha`; `git status` clean in all 3 repos; no `/tmp` paths in launchers | True |
| G9 | Obligations known | `obligation_replay/REPORT.md` | Each producer has a level chosen by the rule |
| G10 | Docs true | Spec statuses and hub page match the code | Read and checked |

- [ ] **Step 2:** Tag locally: `git tag policy/stable-v1` in the gate repo. Do not push.
- [ ] **Step 3:** Update the spec status table, the hub page and `changes.md`.
- [ ] **Step 4:** **Stop.** Plan the experiments with the user.

## After the gate (not part of this plan)

Parity tests check wiring, not scores, and stable code is newer than the `best/*` snapshots. So the first run after the gate is a **re-baseline** of the best profiles on stable code. The rest of the experiment list is decided with the user then.
