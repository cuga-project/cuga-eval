# Open-source graph technology and rule-testing methods (research notes, 2026-11-04)

Sources for the design in `docs/superpowers/specs/2026-11-04-policy-system-design.md`. Web research of 2026-11-04.
Numbers below are the authors' numbers unless marked "ours". We did not reproduce them.

## 1. Graph technology for SOP retrieval

**Result.** The open-source GraphRAG systems build graphs of entities and relations. None models step order,
conditions or exceptions. On GraphRAG-Bench (arXiv 2506.05690, ICLR 2026), plain RAG with a reranker beats MS
GraphRAG, LightRAG and fast-graphrag on fact retrieval; only HippoRAG 2 is equal or better. The methods that fit
procedures key rules to tools at build time (ToolGuard, ShieldAgent), or retrieve in two stages and then check
whether the rule applies (GraphCompliance, SOPRAG).

Type: **E** entity-centric, **P** procedure or workflow, **R** rule or policy. Stars and dates: GitHub API, 2026-11-04.

| Name | Type | Repo · license · stars | Graph → retrieval | Evidence | Fit for us |
|---|---|---|---|---|---|
| MS GraphRAG | E | microsoft/graphrag · MIT · 36.6k | entities, relations, claims, communities → local / global / DRIFT | fact retrieval 49.3 / 38.6 vs RAG 58.8 / 63.7 (Novel / Medical) | Poor |
| LightRAG | E | HKUDS/LightRAG · MIT · 40.5k | entities + relations → local / global / hybrid | 58.6 / 63.3, about equal to RAG | Poor |
| HippoRAG 2 | E | OSU-NLP-Group/HippoRAG · MIT · 4.1k | phrase + passage nodes → query-to-triple, LLM filter, PPR | best on fact retrieval (60.1 / 66.3); recall@5 78.2 vs 73.4 | Best entity option; risk of jumps through shared entities |
| KAG | E | OpenSPG/KAG · Apache-2.0 · 9.2k | schema KG + rules → logical-form planner | +19.6 / +33.5% F1 (baselines not named in abstract) | Too heavy |
| nano-graphrag | E | gusye1234/nano-graphrag · MIT · 4.0k | small GraphRAG copy | not checked | Hack base |
| PathRAG | E | BUPT-GAMMA/PathRAG · no license · 379 | LightRAG graph → relation paths | not verified | Skip |
| MiniRAG | E | HKUDS/MiniRAG · MIT · 2.0k | chunk + entity graph for small models | own numbers only | Idea only |
| fast-graphrag | E | circlemind-ai/fast-graphrag · MIT · 4.0k | configurable entities → PPR | 57.0 / 60.9 | Stale |
| LinearRAG | E | DEEP-PolyU/LinearRAG · GPL-3.0 | entity graph without relations | not verified | Cheap baseline |
| LlamaIndex PropertyGraphIndex | E toolkit | run-llama/llama_index · MIT · 52.8k | strict schema extractor → vector + path | none | Graph builder |
| Neo4j GraphRAG | E toolkit | neo4j/neo4j-graphrag-python · Apache file · 1.3k | typed schema → vector, Text2Cypher | none; needs Neo4j | Graph builder |
| Cognee | E | topoteretes/cognee · Apache-2.0 · 33.1k | entities, chunks | memory benchmark only | Poor |
| Graphiti / Zep | E | getzep/graphiti · Apache-2.0 · 32.5k | facts with validity times → BM25 + vector + graph | DMR 94.8 vs 93.4 | Partial; README warns that small models break schemas |
| Mem0 graph | E | mem0ai/mem0 · Apache-2.0 · 68.4k | entity-link ranking boost | none | No |
| SOP-Agent | P | arXiv 2501.09316 · no code found | decision graph; offers only the tools of the current node's children | 99.8% vs ReAct 67.4% path accuracy (GPT-4) | Design reference |
| FlowAgent | P | Lightblues/FlowAgent · no license · 14 | PDL nodes with preconditions; controllers check each decision | 67.7 vs 62.5 (GPT-4o) | Schema reference |
| AutoSOP | P | NeurIPS 2026 workshop · no code | SOP compiled offline; rule engine picks the next step | RuleArena 81.3 vs 61.0 | Closest to our build step |
| SOPRAG | P | arXiv 2602.01858 · no code | procedure cards + graphs → LLM router | MRR 0.49 vs 0.39 | Copy the card stage |
| SOPStruct | P | arXiv 2504.00029 · no code | SOP → DAG, checked with PDDL + LLM judge | not verified | Validation idea |
| Agent Workflow Memory | P | zorazrw/agent-workflow-memory · Apache-2.0 · 481 | workflows from trajectories | +24.6 / +51.1% relative | Not from SOP text |
| Parlant | R | emcie-co/parlant · Apache-2.0 · 18.3k | condition → action guidelines; LLM match per turn | 90.2 vs 86.1% | Production pattern |
| ToolGuard | R | IBM/tool_guard · Apache-2.0 · 5 | per-tool policies with exact references → guard code | τ airline pass^1 0.450 → 0.685; mapper F1 0.80 | Tested by us, dropped (section 3) |
| ShieldAgent | R | arXiv 2503.22738 · no code | LTL rules per action | rule recall 90.1% | Same idea, heavy |
| GraphCompliance | R | arXiv 2510.26309 · code promised | compliance units + applicability units + REFERS_TO → bi-encoder + cross-encoder per entity | GDPR micro-F1 51.7–57.1 vs 43.8–50.6 | Best method reference |
| PolicyGuard | R | NeurIPS 2026 workshop | per-tool checklist on mutating calls | τ² airline Pass^4 +6 to +12 | Same pattern as our gate |

Data sets found: SOP-Bench (amazon-science/SOP-Bench, CC-BY-NC-4.0, 2,000+ tasks), FlowBench, SOP-Maze (397 tasks).

Not verified: no code found for AutoSOP, SOP-Agent, SOPRAG, SOPStruct or ShieldAgent; PathRAG, LinearRAG and
nano-graphrag numbers; exact Neo4j GraphRAG license terms. No candidate reports results with gpt-oss-120b.

**Ours (offline, `benchmarks/policy_eval/tools/retrieval_eval.py` (was `sop_retrieval_eval.py`), HANDBOOK, 120 acting calls):** 55 calls govern no
procedure. On the other 65: gpt-oss router over procedure cards 87.7% top-1, 93.8% top-3; BM25 69.2%, 80.0% (CareIG
BM25 41.7% top-3). Labels come from DeepSeek-V4-Pro reading the same cards, so this is agreement between two models,
not truth. Earlier test with another label set: BM25 + Kev 74% vs loop LLM 64% (`policy_eval/sop_discovery.py`, 47
cases). LiteLLM has no embedding or reranker model, so dense retrieval and HippoRAG 2 were not run.

## 2. Methods for testing compiled rules

**"Rule Keeper".** No agent-policy engine has this name. Found: RuleKeeper (Ferreira et al., IEEE S&P 2023; GDPR
compliance for MERN web apps), MustangBro7/rulekeeper (CLI that audits CLAUDE.md rules; no runtime gate),
williamcfrancis/rulekeeper (tabletop RPG rules), RuleKeeper-Bot (Discord). Real alternatives to Cedar: Invariant
Guardrails (Apache-2.0), FORGE / PCAS Datalog, SMT / Z3, Progent DSL, OPA / Rego.

Detects: **M** missing rule, **V** wrong value, **S** wrong scope, **O** over-broad deny, **T** wrong trigger.

| Method | Detects | Cost | Needs gold? | Tool |
|---|---|---|---|---|
| Schema validation | S | about 0 | No | `cedarpy.validate_policies` (Apache-2.0) |
| Symbolic analysis: always-deny, shadowed, equivalent | O, S | Low | No | `cedar-policy-symcc` 0.8.1 (Rust, needs cvc5), Cedar Analysis CLI |
| Statement coverage | M | about 0 | No | DIY; FORGE and AWS do this |
| Value grounding (each literal is in the source) | V | about 0 | No | DIY |
| Compile with several models and compare | V, S | k compiles | No | DIY; AWS confidence idea |
| Back-translation + judge | V, S, T | 2 calls per rule | No | DIY; FORGE App. H |
| Allow / deny tests written from the text | V, T, O | 1 call per statement | Labels from text | Hypothesis for property tests |
| Mutation testing of rules | Strength of the tests | Cheap | Needs tests | Martin & Xie, WWW 2007 |
| Conflict detection | Contradictions | Low | No | symcc `disjoint` / `implies`, Z3 |
| Replay with labels | O, M | Low | Violation labels | Our replays |

**AWS Bedrock Automated Reasoning checks (closest production system, arXiv 2511.09008):** chunks → LLM writes SMT-LIB
units with a repair loop; quality report (conflicting rules, unused variables); fidelity report (coverage and accuracy
scores); generated scenarios ranked most-likely-wrong first for a person to review; QnA tests; several LLM translations
must agree or the result is `TRANSLATION_AMBIGUOUS`. Reported: 99.2% soundness at 3/3 agreement but 15.6% recall.

| Work | Target | How the compile is checked |
|---|---|---|
| FORGE (arXiv 2602.16708) | Datalog | Clause IDs, blind back-translation, behavioral judge; 10 τ² airline translations scored 0.53–1.00 |
| Winston et al. 2026 (arXiv 2603.20449) | SMT / Z3, τ² airline | Human review; a Bedrock draft covered about 95% but was underconstrained |
| AutoCedar / CedarBench (arXiv 2607.03656) | Cedar | Verifier on human-approved intent atoms; 221/221 tasks |
| Prose2Policy (arXiv 2603.15799) | Rego | OPA compile, lint, generated tests |
| ShieldAgent, GuardAgent, AGrail, Progent, Policy-as-Prompt | various | End task metrics only |
| nl2spec, NL2LTL, Logic-LM, SatLM, PolicyLR | LTL, solvers | Editable sub-translations or solver feedback |

Links: [Bedrock testing](https://docs.aws.amazon.com/bedrock/latest/userguide/test-automated-reasoning-policy.md),
[ARc paper](https://arxiv.org/html/2511.09008v1), [symcc](https://docs.rs/cedar-policy-symcc),
[Cedar Analysis](https://aws.amazon.com/blogs/opensource/introducing-cedar-analysis-open-source-tools-for-verifying-authorization-policies),
[cedar-py](https://github.com/k9securityio/cedar-py), [FORGE](https://arxiv.org/html/2602.16708),
[Solver-aided τ²](https://arxiv.org/html/2603.20449), [AutoCedar](https://arxiv.org/abs/2607.03656),
[Prose2Policy](https://arxiv.org/abs/2603.15799), [RuleKeeper S&P](https://api.openalex.org/works/doi:10.1109%2FSP46215.2023.10179395),
[MustangBro7/rulekeeper](https://github.com/MustangBro7/rulekeeper).

Not verified: IAM round-trip numbers on Quacky, Progent's generated-policy results (secondary sources); exact CLI names
for the single-set Cedar checks.

## 3. What we ran (ours, ITSM policy e2891a7b98, `benchmarks/policy_eval/rule_audit.py`)

182 should-deny and 165 should-allow decision tests written by DeepSeek-V4-Pro from the policy text without seeing any
rules; replay over 182 real arm-A runs (93 passed). Details: `policy_eval/changes.md` entries 105, 107, 112–118.

| Build | Caught, code + tool schema | Caught, + gpt-oss verifier | False denies | False reminders (verifier) | Passed runs with a deny |
|---|---|---|---|---|---|
| pipeline_v2 | 87 | 114 | 1 | 26 | 2 |
| gold (Claude) | 97 | 148 | 1 | 65–71 (two runs) | 9 |
| v3, role rules deny | 99 | 115 | 7 | 19 | 20 |
| v3, role rules remind | 99 | 115 | 1 | 25 | 2 |
| **v4A, verify → code rules** | **104** | 110 | 1 | 21 | 2 |
| v4B, verify rules mapped to tools | not run | 114 | 1 | 31 | 2 |

Other results:

- Cedar's validator passes on the generated policies; Cedar decisions equal the rule JSON on all 372 role × tool requests.
- Back-translation (gpt-oss restates, DeepSeek judges): gold 50 of 79 equivalent, 21 different; pipeline_v2 22 of 37, 8 different. Not reviewed by a person. (Change 132: the 50 and the 22 are not comparable with each other or with later runs. The old pipeline_v2 rules had no statement ids, so the judge saw the whole section; with the ids the judge sees the statement: 29 of 37 equivalent, 4 different. Gold on the same statements: 50 of 79 again.)
- Tests written by gpt-oss were too noisy (49 false denies on gold). The first test version counted other statements' rules as false denies; the second required allow cases to follow the whole policy.
- ToolGuard step 1 (policies per tool, 21 finished tools, 103 cases, same verifier): caught 43 of 54 (ours 43, gold 50), false flags 34 of 49 (ours 12, gold 28). Stopped at 30 of 42 tools, about $1.73. Step 2 (generated guard code) not run.
- Second-opinion judge (DeepSeek on gpt-oss flags): gold 148 → 141 caught, false flags 66 → 53; v4A unchanged. 15 of v4A's 16 remaining verifier false flags come from one ambiguous sentence (priority "determined automatically").
