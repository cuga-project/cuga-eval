# Policy intake and adherence for CUGA: design

Date: 2026-11-01. Status: approved by the user on 2026-11-01 ("go ahead"); next step: implementation plan. Code: `~/dev/cuga-agent-gate`, branch `feat/policy-gate`, package
`src/cuga/policy_layer/` (uncommitted). Evaluation: `~/dev/cuga-eval/benchmarks/` (`enterpriseops_gym/`,
`automationbench/`). History of the work so far: `~/dev/cuga-eval/history.md`. Earlier design and research:
`docs/analysis/policy-flow.html`, `docs/analysis/2026-10-20-agent-policy-enforcement-sota.md`.

## 1. Intent

Companies give an agent policies in two ways: as documents before the work starts (an SOP, a handbook chapter, a
role matrix), and as data that the agent meets during the work (an email that changes a rule, a sheet with
approval limits, a rule the user states in the request). Small and mid-size models follow long policy text
poorly, and text in the prompt is only advice. We want CUGA to turn any policy it is given into checks that run
at its lifecycle hooks, so the agent is stopped or reminded at the right moment, with a reason and a remedy.

The user's requirements (2026-11-01):

- Support both cases: **offline** documents (2–4 pages, PDF, Markdown and similar; one or several documents) and
  **online** intake during the run. Online intake must be fast in the cases where it matters.
- Intake uses **several kinds of parsing**, chosen by the **type** of each policy statement: code, a rule engine,
  decision questions, LLM questions, and SOPs as a **step graph**, with links between parts of the policy.
- It must handle every type of policy found in our benchmarks, based on a classification of its type.
- Use a decision model (Kev) **only where a measurement shows it is better**. Otherwise use a small model:
  gpt-oss-20b or gpt-oss-120b. Use a rule engine where it is better for some policies.
- A clear structure, and a **well-documented domain model** of policies.
- Validate on **10 AutomationBench + 10 EnterpriseOps-Gym ITSM (ServiceNow) tasks** for tuning, and a second,
  unseen **10 + 10** for the final score. HANDBOOK.md is out of scope (very long PDF).
- Find benchmark cases where a policy section refers to another section, page or document, and see how the agent
  reacts. If there are none, build such cases later.

## 2. Goals, non-goals, anti-goals

Goals

1. One domain model for policies, shared by the offline and online paths and by the runtime checks.
2. A type classifier and a handler per type, where each handler is chosen by measurement (section 7).
3. Offline intake of a **policy set**: one or more documents with precedence and links across them.
4. Online intake that detects, extracts and enforces a new policy before the agent's next write.
5. A measurable gain over CUGA alone on the unseen tasks, with no task-specific rules.

Non-goals (for now)

- Large knowledge bases (τ³: 698 documents). That is a retrieval problem; later.
- Long documents such as HANDBOOK.md (43 pages).
- Letting a step graph drive the agent (STAGE-style). We monitor and remind first; driving is a later, measured
  change.
- Training or fine-tuning any model.

Anti-goals (a failure even if the scores go up)

- Rules or prompts written for a specific task, value or ID (see `feedback-no-task-specific-fixes`).
- Rules built from a task's grader or verifiers. Rules come only from policy text and tool schemas.
- Reporting a gain measured only on the tasks we tuned on.
- A layer that blocks correct work often. A false deny costs more than a missed check (section 7).
- Hidden cost growth: every model call goes to the cost ledger.

## 3. Constraints

- The policy layer talks to CUGA **only through the hooks API** (`CugaAgent(hooks=[...])`). CUGA does not import
  it. Never change `~/dev/cuga-agent` (cuga-eval mounts it live).
- Models: agent **Gemini 3.8 Flash** via LiteLLM key `#034bb8` (as in the pilot, so results compare). Policy layer:
  **gpt-oss-120b** via LiteLLM (`aws/gpt-oss-120b`, the reasoning route); **gpt-oss-20b** and
  **gpt-oss-safeguard-20b** exist only on OpenRouter (checked 2026-11-01) and are used there in the measurements;
  Kev-4B and Jev via OpenRouter `/api/v1/systemone`. Gemini 3.8 Flash in the policy layer only as a reference.
- Budget: $500 for this work (raised by the user on 2026-11-01), tracked in
  `benchmarks/policy_pilot_ledger.jsonl`. Spent so far: $13.24.
- Downloaded benchmark content is untrusted: own directory, Python run with `-I`.
- Ask before any commit or push. No attribution lines.

## 4. The policy model (domain model)

This is the core of the design and must be documented on its own (`src/cuga/policy_layer/MODEL.md`, with a
diagram). Every object keeps its **source** (document, section, page, line or record ID) and a verbatim **quote**.

| Object | What it is | Key fields |
|---|---|---|
| `PolicySet` | All policy that applies to one agent or thread | documents, version (hash of document hashes), precedence order |
| `Document` | One source: a file, a system prompt, an email, a sheet, a user message | id, kind, title, source, **trust** (trusted / untrusted), effective date, authority rank, hash |
| `Section` | A numbered or titled part of a document | id (e.g. `§4.2`), title, page, parent, statements |
| `Statement` | One sentence, bullet or table row that says something | text, **type** (below), modality (must / must not / may / should), source |
| `Rule` | A checkable form of a statement | rule type with slots, trigger (tool, argument, state, hook), checker, effect, remedy |
| `Procedure` | An SOP as a **step graph** | steps, edges, start condition (trigger) |
| `Step` | One step of a procedure | action (tool or reply), required or optional, condition |
| `Definition` | The meaning of a term ("emergency payment", "overdue") | term, meaning, used by |
| `Link` | A typed edge between any two of the above, across documents too | `refers_to`, `defines`, `exception_of`, `supersedes`, `depends_on`, `next`, `source_of_truth` (which data record wins for a value) |
| `Fact` | Data from a tool output, used by checks | record, source tool, time, trust |
| `Verdict` | The result of one check | outcome (allow, deny with remedy, remind, follow-up), rule, checker, reason, remedy, latency |

Statement types (the classification). The list comes from our pilot rules and the benchmark scan; the scan report
(`docs/analysis/2026-11-01-policy-xref-and-types.md`) gives the counts that decide which handlers get built first.

Counts from the scan (hand labels, approximate; a statement can have 2 types): ITSM base policy 63 statements
plus 34 added across versions; AutomationBench 304 statements in 40 sampled tasks.

| Type | Example | Runtime checker (first choice) | ITSM | AB |
|---|---|---|---|---|
| allowed values | "urgency must be one of 1, 2, 3" | code | 27 | 5 |
| lookup matrix | priority from impact × urgency | code | 3 | 10 |
| state transition | "new → in progress → resolved" | code | 15 | 7 |
| required field | "every incident needs a caller" | code | 13 | 9 |
| derived value / calculation | "monthly charge = (cost − salvage) / life" | code | 9 | 26 |
| threshold / limit | "refunds above $500 need approval" | code | 2 | 24 |
| role or permission | "only managers may close a change" | Cedar | 10 | 7 |
| approval | "CAB must approve a normal change" | monitor + Cedar | 6 | 3 |
| prohibition (must not) | "do not schedule units on hold" | code if the condition is a field test, else verifier | 10 | 47 |
| routing / assignment | "network incidents go to the NetOps group" | code or verifier | 3 | 21 |
| deadline / time window | "respond within 24 hours" | code (with a clock) | 2 | 20 |
| notification duty | "notify the owner when status changes" | monitor (duty) | 2 | 11 |
| procedure (SOP steps) | "1. check, 2. approve, 3. close" | step graph monitor | 8 | 11 |
| exception / override / supersedes | "emergency payments may skip step 3" | link; folded into the rule it changes | 9 | 52 |
| definition | "overdue = more than 30 days since inspection" | link; used by other rules | 8 | 19 |
| format | "IDs as INC_###" | code | 2 | 54 |
| open judgment | "use judgment for major incidents" | verifier (raw text), or brief only | 9 | 6 |
| eligibility / exclusion filter | "skip units whose Notes contain an FSR- code" | code if the condition is a field test, else verifier with the matched records | 4 | 74 |
| source of truth | "monitoring emails take precedence over the queue sheet" | link between data sources; the verifier gets the winning record | 0 | 16 |

What the scan changes (`docs/analysis/2026-11-01-policy-xref-and-types.md`):

- **Filters, overrides and format rules dominate AutomationBench** (74, 52, 54 of 304); 84 of 304 statements test a
  Notes or description field, so checks need the records from tool calls (the matched-records fix), not only text.
- **Source-of-truth rules** say which *data* record wins for a value ("emails from ops-manager@ take precedence
  over the sheet"). This is precedence between data sources, so it is a link type of its own (`source_of_truth`).
- **13 of 52 AutomationBench overrides come from untrusted or non-authorized senders** and must be refused: the
  trust test runs on real benchmark data, not only on made-up records.
- **ITSM has almost no explicit cross-references** (16 pointers, none by section number) but 9 overrides without
  pointer words, and version `d5ab75ff0f` contradicts itself in 4 places. The conflict check (section 5, step 5)
  must find these and report which side it keeps.
- **Some ITSM pointers have no target** (an "Assignment Rules Engine", a `sys_approval` table, a priority matrix
  that is not there). A link with no target becomes a coverage-report item, never a rule.
- **The word filter misses graded rules** (7 of 40 sampled tasks, e.g. "Only the HR Director can cancel
  orientation sessions"), which supports tier 1 on every text record.

Precedence when two statements disagree: a trusted source always wins over an untrusted one; then an explicit
`supersedes` link; then the newer effective date; then the higher authority rank of the document. Document order
alone does not decide (ruling 2026-11-01, Task 1): conflicts that remain are recorded and both rules become
advisory (brief only); neither denies.

## 5. Offline intake (before the run)

Input: one or more documents. Formats: PDF, DOCX, HTML, Markdown, plain text, a system prompt. Conversion to
structured Markdown with page numbers uses **docling** (already a CUGA dependency).

1. **Convert and split** (code): sections by headings and numbering, statements by bullet, sentence and table
   row; keep page, section and line. A preamble is a section.
2. **Classify** (model, per section, batched): each statement → one type from section 4, plus modality. Model:
   chosen by measurement (section 7). Tables are classified by their shape in code first.
3. **Link** (code + model): explicit references (`§4.3`, "see section", "Appendix B", "page 2", a document named by
   title) by code; defined terms by code (term match); exceptions, overrides and implicit links proposed by the
   model and kept only if the target exists. Links work across documents of the set.
4. **Handle by type** (section 4 table): code parsers for tables, matrices, transitions and value lists; the model
   fills rule slots for prose rules; numbered procedures become a step graph; definitions attach to the rules that
   use the term; exceptions fold into the rule they change.
5. **Validate** (code): tool and argument names exist in the tool schemas; values are in the schema enum; quotes
   are verbatim; Cedar policies validate; every link target exists; generated allow/deny examples pass; build twice
   and compare (a statement whose rules differ between the two builds goes to review).
6. **Coverage report**: every statement maps to a rule, a step, a definition, guidance, or "out of scope" with a
   reason. Nothing is dropped silently.
7. **Publish**: version = hash; cache per section hash, so a changed document rebuilds only changed sections.
   Optional review by a person (in benchmark runs: no person; the report is saved).

Time budget: a few minutes for 2–4 pages (my estimate; measured in the evaluation).

### 5.1 Two generators, one contract (decided 2026-11-01)

The policy layer ships inside CUGA for users without Claude. Steps 2–4 above can be done by either of two
generators. Both write the same policy model (section 4) and must pass the same validators (steps 5–6).

| Generator | What it is | Who runs it | When to use |
|---|---|---|---|
| **Policy compiler skill** | A harness-neutral skill: `SKILL.md` with the method (convert → split → classify → link → handle by type → validate → fix until the validators pass), plus CLI scripts for conversion, validation and the coverage report. No harness-specific tools: plain files and shell commands | Any agent harness and model: Claude Code, Bob, Codex, or CUGA itself | Authoring and review of a policy set; hard documents (cross-references, exceptions); building the **gold** rule sets for measurement (with a person's review) |
| **Pipeline** | Fixed Python steps with small models (default gpt-oss-120b), one call per section, repair step that sends only failing statements back with the validator error | `builder.py`, no harness | Batch and CI builds; cheap rebuilds of changed sections; the same code path as online intake |

The validators are the method; the generators are replaceable. The output records which generator, harness and
model built it. Benchmark reports name the generator of the rules: the main result uses rules built with an open
model (pipeline, or the skill run by CUGA with gpt-oss-120b); rules built by Claude are a separate, labelled arm.

## 6. Online intake (during the run)

Already built and tested in the pilot (`intake.py`), with the 2026-11-01 fixes:

1. **Tier 0, code, every tool output**: policy words in any text field; records named by a flagged ID; hash
   de-duplication.
2. **Tier 1, decision model, every text record** (a text field of 80+ characters): Kev-4B, threshold 0.47. Chosen
   by measurement: 94.5% recall, 1.1% false alarms, 0.8 s p50 (detector probe, 2026-10-31). Runs in a background
   thread, in parallel.
3. **Tier 2, extraction, one call per tool output**: statements, type, trust, what it replaces. Structured records
   (a sheet of limits, a table of rules) go to the code parsers of section 5 at once. Prose goes to the small model.
4. **Overlay**: new rules apply to this thread only, with their source and trust. Untrusted rules are advice only.
5. **Enforce before the next write**: a write waits for pending intake (bounded, 45 s). If a rule is not compiled
   yet, the verifier checks the write against the raw statement.

Latency targets: tier 0 under 10 ms; tier 1 under 1.5 s p95 per tool output; extraction under 10 s; no wait at
all when a tool output has no candidate.

Policies stated in the user's request (`on_user_message`) go through tiers 2–4 directly.

## 7. Runtime checks, and choosing each method by measurement

Order at `before_tool_call`: code → Cedar → monitor → decision model → verifier. The first deny wins; every
verdict names its rule, source and checker. The verifier gets the statements plus **the records that mention
identifiers from the call** first, then the most recent data (fix of 2026-11-01). The reply check gets the data
the agent read (fix of 2026-11-01). The step graph monitor reminds the agent of the next required step in the
brief and lists missing required steps before the reply.

**Every method is chosen by measurement, not by assumption.** Build a labelled **check set** from the tuning
tasks only: (statement, planned action, data, correct verdict). Sources: tool calls from our pilot and tuning runs
labelled by their outcome, plus controlled changes of one argument that break one statement (labelled by
construction), plus a hand check of a sample. Size about 200 cases, spread over the statement types.

For each type, compare the candidates that can handle it: code, Cedar, gpt-oss-120b (LiteLLM), gpt-oss-20b,
gpt-oss-safeguard-20b (OpenRouter), Kev-4B (systemone questions), and Gemini 3.8 Flash as a reference. Measure
accuracy, **false deny rate**, latency and cost. Decision rule (my call, fixed before the comparison):

1. A method may **deny** for a type only if its false deny rate on that type's cases is at most 2%. Above that it
   may only remind (brief) for that type.
2. Among the methods allowed to deny, take the one that catches the most real violations.
3. Take a cheaper or faster method instead if it catches at most 2 points fewer and its false deny rate is not
   higher.
4. Gemini 3.8 Flash is a **reference only** and is never picked (the user asked for small models). If no small
   model passes rule 1 for a type, that type uses the gpt-oss-120b verifier on the raw statement in remind-only
   mode, and the report names the gap.
5. A type with fewer than 10 cases keeps the default (gpt-oss-120b verifier) and is marked "not measured". The same measurement
is done for the classify step (type accuracy) and for detection (already done: Kev).

The offline generators (section 5.1) are measured against the **gold rule sets** of the tuning policies (built
with the skill and reviewed by a person): statements covered, type accuracy, slot accuracy, links found, and
validator failures before repair. Candidates: the skill run by Claude Code, by CUGA with gpt-oss-120b, and the
pipeline with gpt-oss-120b. Bob and other harnesses can be added with the same script.

## 8. Evaluation

Task selection, by fixed rules written down **before** any run (`benchmarks/policy_eval_tasks.json`, with the
seed and the rule):

- **EnterpriseOps-Gym ITSM**: tasks whose request involves resolve, close, on hold, SLA, change requests or
  approvals (41 of 103 by keyword), minus the 5 pilot tasks and the 2 tasks with broken verifiers. Seed
  20261101: 10 tuning, 10 unseen. The ITSM policy versions are near copies (64 of 103 tasks use two versions; 6 of
  the other 8 are at least 93% the same text), so the unseen ITSM tasks test **new tasks on a policy the build
  was tuned on**, not a new document (decided with the user on 2026-11-01, option A). The report says so. A
  new-document test with another EnterpriseOps-Gym domain is left for later.
- **AutomationBench**: public tasks with a policy record in their data and at least one must-not check in the
  rubric (the selection uses only the rubric's check types, not its values), minus the 5 pilot tasks and the
  detector-probe tasks. Tuning tasks from the probe's tune half, unseen tasks from its test half (so the Kev
  threshold never saw them). At most 2 per domain. Seed 20261101.

Arms: A = CUGA alone; B = CUGA + policy layer. Same agent model and settings. Tuning set: 1 trial per task.
Unseen set: **3 trials per task** (my call; about $90 at pilot prices), compared task by task between the arms.
**Primary metrics** (my call, fixed before the first unseen run): AutomationBench AA-style score (a guardrail
break scores 0) and ITSM task pass rate. Everything else is secondary. Agent trajectories are saved (the ITSM
pilot saved only tool calls).

AutomationBench selection detail (my call): draw from the detector-probe task pool, where Gemini labels (not
Kev, not tier 0) say the task data has a policy record; tuning tasks from the probe's tune half, unseen tasks from
its test half. This keeps selection independent of arm B's detector and keeps the Kev threshold off the unseen
tasks.

Offline features that no benchmark exercises (PDF and DOCX conversion, sets of several documents, authority rank,
links across documents) are validated with fixtures (my call): the accounts-payable policy sample
(`docs/examples/policy_samples/accounts_payable_policy.md`, about 28 `§` references, also converted to PDF) split
into 2–3 documents with an update document. Benchmark evidence for these comes later, with a built document set.
Precedence across records during the run is exercised by AutomationBench (source-of-truth and supersedes cases).

Report per arm: tasks passed; verifiers or rubric checks passed; AA-style score and guardrail breaks
(AutomationBench); denies, **false denies**, follow-ups; policy-layer latency and cost; the coverage report per
policy. Every change made after seeing a tuning run is listed. Only the unseen set is reported as the result.

**Cross-reference study** (a separate set of 7 tasks, excluded from the unseen selection): the 5 strongest
AutomationBench cases from the scan (`operations.twilio_afterhours_incident`, `operations.sheets_asana_approved_request`,
`marketing.customer_feedback_aggregation`, `hr.benefits_enrollment_review`, `marketing.hashtag_performance`) and the
2 ITSM override cases (policy versions `cb2d4ee021`, `c47f8ceef3`). Run both arms and record, per reference, whether
the agent fetched the target, used it, and got the graded value right. Cases with a reference to a numbered section
of another document are rare (1 in 600 AutomationBench tasks: `marketing.social_comment_response_queue`); a built
set for those stays out of scope.

Estimated cost: about $0.63 per AutomationBench run and $0.13 per ITSM run (pilot averages), so 40 tasks × 2 arms
≈ $16–30 per trial; measurements and builds a few dollars more. Well inside $500.

## 9. Code structure

Package `cuga.policy_layer` (one model, one runtime):

| Module | Content |
|---|---|
| `model.py` | The domain model of section 4 (dataclasses), with docstrings; serialised as JSON |
| `documents.py` | Convert (docling), split, page and section ids; policy set loading and precedence |
| `classify.py` | Statement type classification (code shapes first, then a model) |
| `handlers/` | One module per handler family: `tables.py` (values, matrices, transitions), `prose.py` (slot filling), `procedures.py` (step graph), `links.py` (references, terms, exceptions) |
| `builder.py` | Offline pipeline: steps 1–7 of section 5, coverage report, cache |
| `intake.py` | Online pipeline (section 6) |
| `detectors.py` | Tier 1 detectors (Kev via systemone; built 2026-11-01) |
| `models_llm.py` | Small-model clients (LiteLLM, OpenRouter) with usage counts for the ledger |
| `ruleset.py` | Rule types and `RuleSetHooks` (runtime checks) |
| `procedure_monitor.py` | Step graph monitor (duties, order, missing steps) |
| `cedar_engine.py` | Cedar (role and attribute rules) |
| `MODEL.md`, `README.md` | The domain model with a diagram; how to use the package |
| `skill/` | The policy compiler skill: `SKILL.md`, and CLI entry points `convert`, `validate`, `coverage` (`python -m cuga.policy_layer.cli ...`) shared with the pipeline |

The hooks API stays as it is (my call): there is no `modify` effect at `before_tool_call`; a rule that would change
an argument denies with a remedy that names the right value.

The older prototype (`gate.py`, `graph.py`, `checkers.py`, `models.py`, `sdk_hooks.py`) is used only by the chat
demo in `docs/examples/policy_gate_itsm/`. New code must not depend on it.

Measurement and evaluation scripts live in cuga-eval: `benchmarks/policy_eval/` (check set, method comparison,
task selection, runners for both arms, report).

## 10. Risks

| Risk | What we do |
|---|---|
| Few tasks where the policy decides the result (ITSM pilot: A = B) | Selection rule targets policy-sensitive tasks; report check-level results too |
| The check set is small per type | Report per-type sample sizes; do not pick a method on fewer than 10 cases, use the default (verifier) instead |
| Small models extract or classify poorly | Measured in section 7; Gemini is a reference only, never used in arm B; gaps are reported |
| False denies (the operations case) | Verifier gets matched records; false denies counted; repeated-deny cap; shadow mode for a new policy |
| OpenRouter models differ from LiteLLM routes | Decisions name the route; the default route for runs is LiteLLM |
| Network or gateway outages (seen 2026-11-01) | Timeouts and retries; a run that loses the gateway is re-run, not scored |

## 11. Left to the builder

- Exact prompts, JSON schemas and batch sizes.
- How to store the step graph and links (JSON layout).
- The docling options and how to handle tables that docling splits.
- Exact keyword lists for the ITSM selection rule (start from the one used on 2026-11-01).
- Whether to remove the old prototype after the chat demo moves to the new model.
