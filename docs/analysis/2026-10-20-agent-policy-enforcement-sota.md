# Policy enforcement for tool-using agents: state of the art

Living notes, as of 2026-10-20. Covers the methods we have read or tested so far; add new sources to section 3 and to Sources.

## 1. The problem

An agent must follow a written policy (who may do what, in which order, under which conditions) while it talks to a user and calls tools. Putting the policy in the prompt is not enough, and it gets worse with long policies and small models:

- τ3 Banking/Knowledge with the right documents already in context (golden retrieval): GPT-5 30%, gpt-oss-120b 13% (Boaz). 83% of the gpt-oss failures were about using the context (policy neglect, unsupported assumptions), not about finding it.
- AppWorld with gpt-oss-120b: adding written playbooks raised tasks solved from 32% to 50% (our pilot; the playbooks were built from the same tasks).

## 2. Where the policy lives

Details and more benchmarks (HANDBOOK.md, EnterpriseOps-Gym, AutomationBench-AA): `2026-10-20-policy-benchmarks.md`. Real rule texts and traps from those benchmarks: `2026-10-20-policy-examples.md`.

| Benchmark or setting | Policy form | How the agent gets it | Graded on |
|---|---|---|---|
| τ2-bench (airline, retail, telecom) | `policy.md` (airline: 166 lines) | System prompt | Final database state + required messages |
| τ3 Banking/Knowledge | Knowledge-base documents | **Output of a tool** (KB search), or inserted by the benchmark (golden retrieval); some tools appear only after they are "unlocked" | Final state; known grading issues (Boaz, section 3) |
| AppWorld | No written policy; rules are implicit in tasks and API docs | Task text, API docs | Database checks per task |
| Enterprise (HR, banking, compliance) | PDFs of 40+ pages, several documents, versions | Usually not given to the agent at all | — |

## 3. Methods

### A. Policy as text for the model (advice, not enforcement)

| Method | How it works | Notes |
|---|---|---|
| Policy in the prompt | Whole policy in the system prompt | τ2 default. Breaks down on long policies and small models |
| CUGA policy system | Playbook, ToolGuide, IntentGuard, OutputFormatter, ToolApproval; one policy matched per task by intent (embeddings + LLM) | Playbooks are guidance; ToolApproval and IntentGuard can block |
| Retrieval of policy sections | Policy split into chunks; relevant chunks retrieved per turn | Misses rules whose preconditions sit in other sections |
| Knowledge graph for policy QA (Baldwin & Ghanavati, arXiv 2604.27713) | An LLM builds a graph of entities and relations from policy documents (EU AI Act, NIST AI RMF, OWASP LLM Top 10); questions are answered from the top-5 entities plus 1-hop neighbours, or a short ReAct search over the graph | Question answering, not enforcement. 42 questions: the graph improved 4 of 5 models (gpt-oss-20b: 0.66 → 0.79 heuristic score); an open, LLM-chosen schema matched a formal ontology for 3 of 5 models. Supports a thin open graph for evidence retrieval, not for decisions |
| **Parlant** (open source) | Guidelines as "when X, then Y" pairs, matched to the current context; journeys for multi-step flows. Attentive Reasoning Queries (ARQs): structured output that re-states the matched rules right before the model decides | Vendor-reported: 90.2% vs 86.1% (chain of thought) vs 81.5% (direct) on its own test suite |
| **Rasa CALM** | Business processes written as deterministic flows; the LLM only turns user messages into commands; access rules are flow guards, not LLM judgment | The model never chooses the branch; the flow does |

### C. Compile the policy into checks that code runs

| Method | Policy becomes | Checked when | Notes |
|---|---|---|---|
| **Our decision gate** | Policy graph (actions → rules → facts → fact source), compiled once by a strong model, with build verifiers and human sign-off | `before_tool_call`, `before_reply`, other CUGA hooks | Facts from code; Jev for narrow language questions; LLM when unsure. See `2026-10-15-decision-gate-architecture.html` |
| **Smith** (IBM) | OPA/Rego policy, generated from a guidance text by a coding-agent skill | Not described in the repo | Pipeline: guidance classification → policy (human approval) → tests from atomic conditions, red-team cases (Promptfoo) → test-and-patch loop, lint (Regal) |
| **AgMentor** (guardian agent) | Declarative order rules (AgDECLARE, based on Declare / LTLf), from text, BPMN or event logs | Runtime guardian (on its roadmap) + after the run (Declare4Py) | Handles order and time rules ("B only after A") |
| **AWS AgentCore Policy** | Cedar policies, written directly or generated from plain English; validated against the tool schema; automated reasoning flags rules that are too permissive, too strict or unsatisfiable | Each tool call, at the AgentCore Gateway | Log-only mode before enforcing (like our shadow mode). Preview Dec 2025 |
| **AWS Automated Reasoning checks** (Bedrock Guardrails) | Formal logic built from a policy document, refined with test cases (each fix approved by a person) | On model outputs: is the answer entailed by the policy? | Result is a logical verdict, not a score. Targets insurance, benefits, regulatory text |
| **ShieldAgent** (ICML 2025) | Probabilistic rule circuits built from regulations and corporate handbooks | Over the agent's action trajectory; plans a check and runs code for formal verification | Released ShieldAgent-Bench |
| ToolGuard* | Guard code generated from natural-language policy | Before a tool is invoked | Deterministic |
| AgentSpec* | Rules in a domain-specific language | Runtime | Deterministic |
| PCAS* | Datalog-style policies over a dependency graph of the run | Reference monitor at runtime | Deterministic |
| Solver-aided verification* | SMT constraints, checked with Z3 | Before execution | Deterministic |

### D. Runtime policy engines (reference monitors)

| Method | How it works | Notes |
|---|---|---|
| **CPEX** (ContextForge) | Deterministic reference monitor between the agent and every capability (tool, prompt, resource, LLM, A2A). One APL route per capability with 4 phases: `args` → `authorization.pre_invocation` → `result` → `authorization.post_invocation`. Plugins on named hooks (`cmf.tool_pre_invoke`, `cmf.tool_post_invoke`, `cmf.llm_input`, …) can block, modify or audit | Covers identity, delegation, taint tracking, redaction, human approval (elicitation), audit. Hands the allow/deny decision to Cedar, CEL or an external engine. Does not read a written policy: rules are configured |
| **Invariant Guardrails** (Invariant Labs, Apache 2.0) | Python-like rules (`raise ... if:`) over messages, tool calls and tool outputs, including sequences (e.g. read inbox, then email an unknown address); enforced by a gateway proxy or a local trace checker | Order and data-flow rules, close to our Declare-style order rules |
| **NeMo Guardrails** (NVIDIA) | Rails written in Colang: input, output, retrieval and execution rails; execution rails check tool inputs and outputs | Dialogue-flow oriented |
| **OpenAI Agents SDK guardrails** | Input, output and tool guardrails (before and after each function-tool call); rule- or LLM-based; a violation trips an exception | A hook point, like ours; no policy compilation |
| OPA/Rego, Cedar, CEL | General policy languages and engines | Answer "is this request allowed?" on structured input |
| XACML pattern | PEP (enforces) / PDP (decides) / PIP (supplies facts) / PAP (manages policies) | Our gate maps onto it: hooks = PEP, gate = PDP, fact sources = PIP, build phase = PAP |

### E. LLM or model verifiers at runtime

| Method | Checks | Input | Output |
|---|---|---|---|
| CUGA VERIFY gate | Each code block before it runs | Plan + code | Accept or revise. AppWorld ablation: off 54.3% vs on 65.2% |
| **Boaz's semantic verifier** | Policy violations, contradictions with history, made-up facts or arguments, wrong order, premature final answers | Atomic-statement graph of policy + conversation + tool results; top-k retrieval + expansion along relations; logic layer (A → (B ∨ C)) | Accept, or reject with a reason → agent regenerates. Pass-only or reject-only mode |
| **LlamaFirewall AlignmentCheck** (Meta) | Goal hijacking: does the agent's reasoning still serve the user's task? | Agent's chain of thought and actions (not raw tool output) | Flag; needs a large model. With PromptGuard 2 and CodeShield in LlamaFirewall |
| PolicyGuard* | Mutating tool calls only | Proposed call + policy + full history | Allow, or block with a remediation message |
| PolicyGuide* | Workflow progress | Policy compiled into workflow graphs | Step-by-step guidance |
| ToolSafe* | Harmful or injected tool calls (safety) | Interaction history | Feedback into the agent's reasoning |
| Jev (TypeSafe) | Narrow typed questions (choice, yes/no/unknown, score) | State + question templates | Answer + confidence; ~$0.00007 and ~0.8 s per question |

### F. Security by design (data flow and privileges)

These target prompt injection and data leaks more than business rules, but they enforce policies on tool calls in code and fit a code-executing agent like CUGA.

| Method | How it works | Notes |
|---|---|---|
| **CaMeL** (Google DeepMind) | A privileged LLM writes the plan as code from the trusted request; a quarantined LLM reads untrusted data without tools; a custom Python interpreter tracks where every value came from and checks policies at each tool call | AgentDojo: 77% tasks solved with provable security vs 84% undefended. Closest to CUGA's code execution |
| **FIDES** (Microsoft Research) | Confidentiality and integrity labels on data, propagated through messages, tool calls and results; consequential actions run only if the policy holds | Deterministic; code at microsoft/fides |
| **Progent** | Per-tool allow/forbid rules with conditions on arguments (JSON Schema), drafted and updated by an LLM from the task, checked before each call | Least privilege per task; authors report 0% attack success on AgentDojo |

### H. After the run (diagnosis, scoring)

| Method | What it does |
|---|---|
| Declare4Py (AgMentor) | Checks a trajectory log against Declare rules; % adherence per run and per rule |
| PolicyGuard-4B / PolicyGuardBench* | Classifies whole trajectories or prefixes as compliant or violating |
| NearMiss* | Finds runs with a correct outcome but skipped policy checks |
| LLM-as-a-Verifier* | Continuous scores for trajectories and steps; for ranking and rewards |
| AgentDoG, AgentDiagnose* | Fine-grained diagnosis and root cause of failures |

\* As summarized in Boaz's report (section 2.2); we have not read these papers yet.

### Additions 2026-10-21, including the new families B (procedure graphs) and G (train the agent)

From a web search, vendor docs and our own knowledge; abstracts or docs only, not read in full. Section letters follow the deck (A–H).

Two families were missing: **B · procedure graphs** (a step graph drives or guides the agent) and **G · training the agent on the policy**. The slide deck (`2026-10-21-policy-sota-benchmarks-slides.html`) shows all methods in eight families (slide 17) and when each one needs the policy (slide 18): trained into the model, built ahead of time, built per task, read at run time, or not clear from the sources.

| Family | Method | What it does | Reported result (authors) |
|---|---|---|---|
| Procedure graphs | **STAGE** (arXiv 2608.22538) | Policy → executable graph offline (LLM-assisted, validated, frozen); model judgment only inside policy-scoped nodes; a coordinator checks typed node results and picks the next step | pass^3 up to +55.0 pts on τ²-bench telecom, +65.7 on Smart Dispute (proprietary banking) vs full policy in the prompt |
| Procedure graphs | **PolicyGuide** (arXiv 2608.19861) | Policy compiled into workflow graphs; guides the agent through required steps (NeurIPS 2026) | Mean pass^4 0.42 (unguided ReAct) → 0.62 |
| Procedure graphs | Salesforce **Agent Script**; Decagon **Agent Operating Procedures**; Parlant **journeys** (soft: the agent may skip or revisit states, per Parlant docs) | Vendor products: deterministic flow around LLM turns; plain-English procedures turned into structured logic | Vendor claims only |
| Procedure graphs | **JourneyBench** (arXiv 2601.00596, EACL 2026 Industry) | Benchmark with SOPs as graphs; a dynamic-prompt agent that models policy control | Dynamic design beats static prompt; GPT-4o-mini > GPT-4o |
| Compile to checks | **ToolGuard** (IBM, arXiv 2507.16459, EMNLP 2025 Industry) | Policy text → guard code per tool at build time; runs before each tool call; τ-bench airline. In Langflow as "Policies" | — |
| Compile to checks | **Solver-aided verification** (arXiv 2603.20449) | Policy → logical constraints; each tool call checked by a solver | Fewer violating calls, more consistent runs |
| Compile to checks | **PolicyKG** (arXiv 2608.09028) | Policy documents → deontic logic → SHACL-validated knowledge graph | 86.9% deontic classification; 79.2% of rules via the logic path |
| Compile to checks | **Agentproof** (arXiv 2603.20356) | Static verification of agent workflow graphs | — |
| Runtime monitors | **AgentFlow** (arXiv 2608.22868) | Flow-centric policy language; reference monitor tracks labels and lineage; allow, deny or pause | — |
| Runtime monitors | **Temporal contracts** (arXiv 2609.18128); **ProbGuard** (arXiv 2508.00500) | Symbolic temporal supervision; probabilistic prediction of unsafe states | — |
| Runtime monitors | MCP gateways (ToolHive, Gravitee GAPL, Permit.io) | Cedar or Cedar-like authorization at the MCP gateway | Vendor docs |
| Runtime monitors | Google ADK callbacks, Claude Agent SDK hooks, LangChain middleware | Hook points before and after tool calls in agent frameworks; Claude Agent SDK `PreToolUse` can allow, deny or change a call ([docs](https://platform.claude.com/docs/en/agent-sdk/hooks)); ADK and LangChain from our knowledge, not re-checked | — |
| Model verifiers | **PolicyGuard** (arXiv 2606.29225) | Sub-agent verifier: full conversation + raw policy text + LLM-generated per-tool checklist; checks each mutating call; pass or block with remediation (NeurIPS 2026; same authors as PolicyGuide) | τ²-bench airline pass^4 +12.0 / +6.0 / +12.0 pts (GPT-5.4 / Claude Sonnet 4.6 / Gemini 2.5 Pro); blocks about half as often as argument-level guards |
| Model verifiers | **JevAct** (arXiv 2610.38620, read 2026-11-01) | Offline per domain: Claude Opus 4.6 compiles the policy into Python fact checks, yes/no questions, an allow rule and a hand-off checklist; Kev-27B (prefill-only) answers the questions before each write (P(yes) <= 0.05 counts as "no"); bounded revision R = 2; checks that fire on > 10% of development calls are dropped; a repair round on logged calls cut code false alarms 11.3% -> 1.4%. Not addressed: policies arriving at run time, several documents, cross-references, untrusted content, roles | τ²-Telecom pass^3 +16.9 pts on average over 8 agents (Opus 4.6 39.5% -> 80.7%); BFCL: all 9 agents improve in three-run success; Airline mixed; 42 of 101 incorrect development write calls break no compiled question; with a gpt-oss-120b user simulator the Telecom gain disappears (-1.8 pts) |
| Model verifiers | **gpt-oss-safeguard** (OpenAI, Oct 2025; 20B, 120B, Apache 2.0) | Open model that takes a developer-written policy at inference and returns a verdict with reasoning | — |
| Model verifiers | **AdaGuard** (arXiv 2609.34241) | Policy-conditioned guard, 0.6B/4B/8B; SFT then RL (SafePO) | — |
| Model verifiers | **ToolSafe / TS-Guard** (arXiv 2601.10156) | Step-level guard model (Qwen2.5-7B, GRPO) before each tool call | — |
| Model verifiers | **RePolicy** (arXiv 2608.24275) | RL to pick the applicable safety policy, then judge the trajectory | — |
| Model verifiers | **Jev-Guard** (HKUST, arXiv 2610.18326, Oct 2026) | Qwen3.5-2B + LoRA with two heads: routes each action to a policy in a hand-built, editable policy tree (content moderation, cybersecurity, privacy, legal compliance), then classifies it against that policy. Follows Typesafe AI's Jev paradigm (Open-Jev family). Integrated in the Hermes harness as a permission gate | 93.72% safety accuracy at 58 ms on 7,033 cases (Jev 1.13: 75.89%; Qwen3.5-2B SFT: 93.36% at ~514 ms); routing 93.10%. Tree edits without retraining: reordering 95%, adding a routing group 86%, deleting a category 50%. Hermes review time 4.80 s → 1.33 s per task |
| Model verifiers | Sierra supervisors; Decagon supervisor model | Vendor: supervisory agents monitor live conversations | Vendor claims only |
| Security by design | **Conseca** (arXiv 2501.17070, HotOS 2025) | LLM writes a just-in-time policy for the task and trusted context; code enforces it deterministically | — |
| Train the agent | **Deliberative alignment** (OpenAI, arXiv 2412.16339, Dec 2024) | Model trained on the text of a written specification and to reason over it before answering | Fewer jailbreaks and fewer over-refusals (authors) |
| Train the agent | **IH-Challenge** (OpenAI, arXiv 2603.10521); **ManyIH** (arXiv 2604.09443) | RL data for instruction hierarchy (system > developer > user > tool); benchmark with up to 12 levels | ManyIH: frontier models ~40% with many levels |
| Train the agent | **PVST** (arXiv 2610.19372, via an abstract mirror) | Policy-verified self-training: a compiled policy gate scores the agent's own trajectories; violations become negatives | Qwen3-8B on AgentDojo: violating runs 37.2% → 10.3%, attacks 12.4% → 0.5% |
| Train the agent | **SENTINEL** (arXiv 2606.12908); **TRACE** (arXiv 2604.05336) | Failure-driven RL on τ²-bench retail (Qwen3-4B); capability-targeted LoRA/GRPO on τ²-bench | TRACE: Qwen3-30B-A3B 32.9% → 37.8% |
| After the run | **NearMiss** (IBM) | Builds on ToolGuard; finds runs with a correct outcome but a skipped policy check | — |
| After the run | Compositional policy violations (arXiv 2609.18820) | Step-level compliance can still violate the policy over a trajectory | — |

### Offline or online policy intake (validated 2026-10-21)

Question: does the method process the policy offline only, can it also take in, map or compile a new policy during the run, or both? Each placement was checked against the paper, model card or official docs (slide 18 of the deck).

| Intake | Methods | Notes |
|---|---|---|
| Offline only: compiled to rules, code or graphs (34) | Parlant ARQs and journeys, CUGA playbooks, Policy KG for QA, Rasa CALM, Agent Script, STAGE, Agentproof, Decagon AOPs, ToolGuard, AgentCore Policy, Smith, Solver-aided (SMT), ShieldAgent, AgentSpec, PolicyKG, Automated Reasoning, CPEX, Invariant, NeMo Guardrails, OpenAI Agents SDK, Google ADK, Claude Agent SDK hooks, LangChain middleware, MCP gateways (Cedar), AgentFlow, PCAS, temporal contracts (ContrAgent), ProbGuard, Jev, CaMeL, FIDES, Declare4Py, NearMiss | Invariant, NeMo, Agents SDK, ADK, Claude hooks and LangChain can also call an LLM judge on policy text a developer placed in a prompt. CaMeL builds a new program per query, but its security policies are fixed |
| Offline only: trained into weights (4) | Deliberative alignment, PVST (plus a gate compiled once), ToolSafe / TS-Guard, AgentDoG | A changed policy needs retraining (PVST: also a new gate) |
| Both: offline artifact + online policy text (12) | Jev-Guard (policy tree built by hand; edits work without retraining, with accuracy loss), Section retrieval (index), PolicyGuide (graph per domain + raw policy each turn), Boaz verifier (policy graph + new context decomposed as it arrives), PolicyGuard (checklist per domain + raw policy each call), RePolicy (library curated offline, chosen online), Granite Guardian (trained risks + custom criteria at inference), Progent (generic rules + per-task rules generated online), PolicyGuard-4B (fine-tuned; policy text is an input), IH-Challenge, SENTINEL, TRACE (trained; the policy text stays in the prompt) | RePolicy maps online but takes in new policies only through the library |
| Online: compiles or maps during the run (1) | Conseca | LLM writes a policy for each task; code enforces it |
| Online: uses the raw text (3) | Policy in prompt, gpt-oss-safeguard, AdaGuard | Policy supplied at inference |
| No policy input (3) | CUGA VERIFY (4 fixed rules in `verify_system.jinja2`), LlamaFirewall AlignmentCheck (user goal only), LLM-as-a-Verifier (task correctness) | Not policy enforcement in the strict sense |
| Not clear (2) | Sierra supervisors, Decagon supervisor | Vendor blogs only |

Corrections from the validation: Solver-aided, PolicyGuide, Granite Guardian, PolicyGuard-4B, LLM-as-a-Verifier and AgentDoG were "not clear" before; the Boaz verifier was "offline" (it decomposes the accumulated context, including retrieved knowledge); CUGA VERIFY and AlignmentCheck read no policy. Renamed papers: AgentFlow v2 is "Agenra" (arXiv 2608.22868v2); PCAS v4 is "FORGE" (arXiv 2602.16708). PolicyGuard (arXiv 2606.29225) and PolicyGuard-4B (arXiv 2510.03485) are different papers.

Survey for cross-checking the families: "Toward Safe LLM Agents: A Survey of Specification, Verification, and Enforcement" (arXiv 2608.14590): of 38 studies, 15 check before execution (most need a fixed workflow graph) and 8 verify at runtime.

## 4. How the methods differ

| Dimension | Options |
|---|---|
| When | Build time (compile, test) · runtime before the action · runtime after the result · after the run |
| What is checked | Tool calls · replies · plans or code blocks · the whole trajectory |
| Who decides | Code or solver (exact) · trained classifier · decision model (Jev) · LLM · human |
| Output | Block · modify (redact) · feedback for a retry · score or report |
| Policy source | Hand-written rules · compiled from text · used as text at runtime |

Most of what we found works best in combination. Code decides what can be written as a rule (exact, cheap, auditable); a model verifier handles meaning (grounding, contradictions); a human signs off the compiled rules.

### What the newer methods add to our design

- **AgentCore Policy** is the same pipeline as our build phase (text → checked rules → log-only → enforce), with Cedar as the language. It supports making the policy language a plugin, and Cedar a candidate backend.
- **CaMeL / FIDES** show how to enforce rules inside a code interpreter, which matches our CodeAct design (wrapping the tool namespace) and adds data provenance to facts.
- **Invariant** rules on tool-call sequences are another order-rule language, next to Declare.
- **Parlant ARQs** and **Rasa CALM** keep the model from choosing the branch: the same idea as asking Jev narrow questions and letting code decide.

## 5. Long policies (a 40-page PDF)

| Approach | Works | Fails |
|---|---|---|
| Whole PDF in the prompt | Simple | Context rot; small models drop rules (policy neglect) |
| Retrieve sections per turn | Scales | A rule's preconditions are often in another section; top-k misses them |
| Compile offline into per-action rules (our gate, Smith, ToolGuard) | Runtime cost does not grow with the PDF; exact; testable | Compiling drops statements (Boaz: LLM decomposition omits facts); needs coverage checks and review |
| Atomic-statement graph (Boaz) | Keeps everything; finds related rules through relations | Lossy retrieval; no time order |
| One playbook per intent (CUGA) | Short guidance per task type | Advice only |

Suggested pipeline for a long PDF:

1. Parse into sections and statements, keeping page and section ids.
2. Classify each statement: checkable rule · guidance · definition · out of scope (Smith has a similar guidance classifier step).
3. Compile checkable rules per action, with generated tests (Smith-style allow / disallow cases).
4. Turn guidance into playbooks; put the rest in the atomic-statement graph for the semantic verifier.
5. Coverage report: every paragraph maps to a rule, playbook, graph statement, or "out of scope" with a reason.
6. Conflict check across the whole document and the tool schemas (catches τ3-style circular rules before any run).
7. Human review; freeze a version with a hash; recompile only changed sections on updates.

## 6. When the policy is a tool output (τ3 Knowledge)

- **The documents are fixed even if the agent sees them late.** Compile the knowledge base offline, per document (cache by document hash), so retrieval at runtime returns ready rules as well as text.
- **Unseen or changed documents:** send them to the semantic verifier as authority text, and compile them in the background for next time.
- **Tools unlocked mid-task:** key rules by tool name, so a rule attaches when the tool appears; an unknown tool goes to the semantic verifier.
- **Conflicts between documents and tool schemas** (Boaz: argument names and forms differ after unlocking) are found by a build-time check across the KB and the tool schemas.
- **Trust:** policy text that comes back from a tool can be wrong or injected. Only documents from a trusted source count as policy (keep the source on every rule).

## 7. Open questions

- Accuracy of Jev on dialogue questions (user confirmed? reason category?) is not measured.
- How much of a real 40-page policy is checkable as rules vs. needs a model? No measurement yet.
- Smith's runtime enforcement point is not documented; CPEX could be that point (APL + an OPA/Cedar decision engine). Not verified.
- None of the compile-based methods report results on τ2 or τ3 yet.

## Sources

- Our design: `docs/analysis/2026-10-15-decision-gate-architecture.html`; plan `~/.claude/plans/lets-plan-to-run-parallel-shore.md`
- CPEX: https://contextforge-org.github.io/cpex/ (APL: `/docs/apl/`, plugins and hooks: `/docs/pipeline/`)
- Smith: https://github.com/IBM/smith, example https://github.com/IBM/smith/blob/main/examples/hr-agent/README.md
- Boaz, "Boaz IBM Internship" (internal report, October 2026): τ3 integration, semantic verifier, related work
- "AgMentor as a guardian agent", February 2026 (internal slides)
- τ2-bench: https://github.com/sierra-research/tau2-bench (airline policy at commit 5ebebbe)
- AWS AgentCore Policy: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html ; announcement https://aws.amazon.com/about-aws/whats-new/2025/12/amazon-bedrock-agentcore-policy-evaluations-preview
- AWS Automated Reasoning checks: https://aws.amazon.com/blogs/machine-learning/how-automated-reasoning-checks-in-amazon-bedrock-transform-generative-ai-compliance/
- ShieldAgent: https://arxiv.org/abs/2503.22738
- Invariant Guardrails: https://invariantlabs.ai/blog/guardrails
- NeMo Guardrails: https://github.com/NVIDIA/NeMo-Guardrails
- OpenAI Agents SDK guardrails: https://openai.github.io/openai-agents-python/guardrails/
- Parlant: https://parlant.io/docs/concepts/customization/guidelines ; ARQs https://arxiv.org/abs/2503.03669
- Rasa CALM: https://rasa.com/docs/learn/concepts/calm/
- LlamaFirewall: https://arxiv.org/abs/2505.03574
- CaMeL: arXiv 2503.18813, code https://github.com/google-research/camel-prompt-injection
- FIDES: https://www.microsoft.com/en-us/research/publication/securing-ai-agents-with-information-flow-control/ (arXiv 2505.23643)
- Progent: https://arxiv.org/abs/2504.11703
- Knowledge graphs for policy compliance QA: https://arxiv.org/abs/2604.27713
- Our runs: AppWorld playbooks pilot (`docs/analysis/2026-10-15-playbooks-gpt-oss.html`); CUGA VERIFY gate ablation (cuga-eval notes)
