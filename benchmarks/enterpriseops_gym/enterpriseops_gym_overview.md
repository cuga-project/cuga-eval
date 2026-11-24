# EnterpriseOps-Gym: paper overview and dataset notes

**Paper:** Malay, Nayak, Nair, Davasam, Tiwari, Tejaswi, Nemala, Sunkara, Rajeswar. *EnterpriseOps-Gym: Environments and Evaluations for Stateful Agentic Planning and Tool Use in Enterprise Settings.* ServiceNow Research / Mila / Université de Montréal. arXiv:2603.13594v1, 13 March 2026.

**Notes compiled:** 19 November 2026, with a focus on the dataset and on policy compliance.

**How to read these notes.** Unless marked otherwise, statements come from the paper. Two other kinds of statement are labelled:

- **[release]** comes from the Hugging Face dataset card or a third-party write-up, checked on 19 November 2026.
- **[inference]** is my own reading, not something the paper states.

---

## 1. Summary

EnterpriseOps-Gym is a benchmark for LLM agents doing stateful, policy-constrained, multi-step tool use in a simulated enterprise. The agent receives a system prompt (role plus policies) and one user request, calls tools against a live database inside a Docker sandbox, and is graded on the final database state rather than on its action sequence.

- 1,150 expert-authored tasks, including 30 deliberately infeasible ones
- 8 domains, 512 tools, 164 database tables
- Best of 14 models (Claude Opus 4.5) completes 37.4% of tasks
- The authors' main claim: the bottleneck is planning, not tool selection or invocation

---

## 2. Dataset

### 2.1 Scale and domains

| Domain | Tasks | Avg steps | Max steps | Tools | Character |
|---|---|---|---|---|---|
| CSM (Customer Service Management) | 186 | 12.1 | 27 | 89 | B2B support: cases, entitlements, SLAs, installed products |
| HR | 184 | 10.5 | 34 | 89 | Employee lifecycle, privacy, role-based access |
| ITSM (IT Service Management) | 181 | 9.0 | 31 | 93 | ITIL: incidents, problems, changes, CMDB |
| Hybrid | 156 | 7.8 | 19 | multi-domain | Usually two domains at once; about 40 tables per task |
| Drive | 105 | 8.7 | 29 | 55 | Permissions, versions, folder hierarchies |
| Email | 104 | 6.2 | 22 | 79 | Mailbox workflows, send-as aliases, filters |
| Calendar | 104 | 7.0 | 17 | 37 | Access control lists, recurrence, timezones, webhooks |
| Teams | 100 | 9.4 | 18 | 70 | Channels, membership, tabs, virtual events |

- Task counts are from the paper's Figure 3. Average steps are from Figure 7.
- **[release]** Max steps and per-domain tool counts are from the dataset card. The paper only gives the tool range (37 for Calendar to 93 for ITSM).
- Overall: expert trajectories average 9.15 steps, maximum 34.

### 2.2 What each task contains

- **System prompt.** Agent role, operating rules and, for some tasks, a full policy document (see section 5).
- **User prompt.** A single-turn request in natural business language, often with hidden sub-tasks such as resolving a customer's email through a chain of lookups.
- **Oracle tool list.** Exactly the tools needed for the task.
- **SQL verifiers.** Executable checks on the final database state. A task has 5.3 verification conditions on average, up to 44.
- **Gold trajectory.** The annotator's manual execution, with parameters, responses and rationale for each call.
- **Human-written plan.** A natural-language reasoning plan that grounds each action in the system constraints, user request and available tools.

### 2.3 Environment

- 164 unique tables across the eight domains.
- Each task touches a sub-graph of 24.9 tables on average, up to 73 in Hybrid.
- Each task operates over about 3,443 rows on average, above 10,000 in data-heavy domains such as CSM.
- Foreign keys per table: 1.1 (Calendar) to 2.4 (HR), mean about 1.7. The paper presents this as denser than prior enterprise benchmarks.
- Seed data is synthetic and vendor-agnostic, modelled on public API documentation and data models with subject matter experts.
- Seed data varies substantially per task; each database represents a distinct use case rather than a small edit of one seed.
- A fresh database instance is initialised for every task run.

### 2.4 How it was built

1. **Domain and sandbox setup.** Schemas, seed data and tools per domain.
2. **Scenario design.** Annotators wrote multi-step scenarios to complexity thresholds on tool-call count, verification conditions, state dependencies, access constraints and policy conflicts.
3. **Gold execution and plan authoring.** Each task was executed by hand in the sandbox and a plan written.
4. **Outcome-based verification.** Annotators wrote the SQL verifiers.
5. **Quality assurance.** Draft tasks were first run against GPT-5, Gemini and Claude to find broken definitions and to discard trivial tasks, then reviewed by humans against rubrics.

Other facts:

- Vendor: Turing. Over 160 contributors, about 20 annotators and 6 reviewers per domain.
- About four months, including a one-month pilot. About 100 USD per task.
- Tasks are constrained to a unique final state, though several valid paths may reach it.

### 2.5 Infeasible tasks

- 30 tasks across the 8 domains where completion is intentionally impossible.
- Three mechanisms: insufficient tool availability, explicit policy violation, resource unavailability (for example an inactive user or a system in migration mode).
- Correct behaviour is to refuse and leave no side effects. Each has about 10 verification checks.
- Requests use compound constraints, averaging 3 to 4 per request.

### 2.6 Evaluation protocol

- **Primary metric:** pass@1. A task scores 1 only if every verifier passes. Reported as the average over three runs.
- **Default setting:** oracle-tool mode (the agent gets exactly the right tools) with a ReAct loop.
- **Secondary metric:** verifier-level pass rate (about 47% to 68% across models). The paper warns this overstates success because setup steps pass easily while core logic fails.

---

## 3. Public release and caveats

**[release]** Dataset: <https://huggingface.co/datasets/ServiceNow-AI/EnterpriseOps-Gym>. Code: <https://github.com/ServiceNow/EnterpriseOps-Gym>. Site: <https://enterpriseops-gym.github.io>.

```python
from datasets import load_dataset
ds = load_dataset("ServiceNow-AI/EnterpriseOps-Gym", "oracle", split="teams")
```

**[release]** Configurations are tool modes and splits are domains:

| Config | Meaning | Rows |
|---|---|---|
| `oracle` | Only the tools the task needs | 649 |
| `plus_5_tools` | Oracle tools plus 5 distractors | 637 |
| `plus_10_tools` | Oracle tools plus 10 distractors | 637 |
| `plus_15_tools` | Oracle tools plus 15 distractors | 637 |

**[release]** `oracle` rows per domain: calendar 61, csm 103, drive 64, email 67, hr 102, hybrid 88, itsm 103, teams 61.

**[release]** Documented fields:

| Field | Content |
|---|---|
| `task_id` | Unique task identifier |
| `domain` | Domain name |
| `system_prompt` | Agent role and domain policies |
| `user_prompt` | Task instruction |
| `selected_tools` | Tools available in this mode |
| `verifiers` | JSON string of SQL-based final-state checks |
| `gym_servers_config` | JSON string of MCP server configuration for the sandbox |

The viewer also shows four undocumented columns: `restricted_tools`, `mcp_endpoint`, `number_of_runs`, `reset_database_between_runs`.

**[release]** The GitHub framework supports ReAct, Planner-ReAct and Decomposing Planner orchestrators, several LLM providers, and parallel runs via Ray.

### Caveats

- **The public release is smaller than the paper's benchmark.** 649 oracle rows against 1,150 tasks. A third-party write-up says the GitHub README describes the public split as 60% of the benchmark. I could not open the repository to confirm. Results on the public split may not match the paper's tables.
- **Human plans and gold trajectories may not be released.** Neither appears in the documented fields. Check the repository.
- **Licence needs checking.** The dataset card showed Apache-2.0 when fetched, but a search snippet of its README showed CC-BY-NC-4.0. Confirm before any commercial use.
- **Counts are inconsistent.** Figure 3's domain counts sum to 1,120, which suggests the 30 infeasible tasks are counted separately **[inference]**. The dataset card's own domain table sums to 1,115. Opus 4.5's average is 37.4% in Table 2 and 37.0% in Table 6.
- **Selection bias.** Tasks that GPT-5, Gemini and Claude solved too easily were discarded during QA, so the set is partly adversarially filtered against those model families **[inference]**.
- **No user simulation.** System prompts tell the agent not to ask for confirmation, so clarification dialogue is not tested.
- **Infeasible results are noisy.** With 30 tasks, each one is worth about 3.3 points.
- **Whether infeasible tasks are in the public split is unknown.**

---

## 4. Results

### 4.1 Main table (paper Table 2, pass@1 %, oracle tools)

| Model | Teams | CSM | Email | ITSM | Calendar | HR | Drive | Hybrid | Infeasible | Avg |
|---|---|---|---|---|---|---|---|---|---|---|
| Claude Opus 4.5 | 50.0 | 34.2 | 51.9 | 23.8 | 43.2 | 32.1 | 49.5 | 30.7 | 50.0 | 37.4 |
| Gemini-3-Flash | 47.3 | 35.0 | 44.3 | 28.5 | 30.5 | 12.6 | 49.7 | 24.2 | 38.5 | 31.9 |
| GPT-5.2 (High) | 31.0 | 34.8 | 51.0 | 21.7 | 38.5 | 25.0 | 40.0 | 22.2 | 50.0 | 31.8 |
| Claude Sonnet 4.5 | 51.0 | 16.7 | 51.3 | 17.6 | 34.6 | 21.6 | 52.1 | 28.1 | 46.2 | 30.9 |
| GPT-5 | 26.3 | 36.4 | 49.0 | 18.9 | 41.3 | 17.9 | 34.0 | 23.5 | 50.5 | 29.8 |
| Gemini-3-Pro | 43.0 | 27.7 | 33.6 | 22.2 | 28.8 | 12.5 | 46.7 | 22.9 | 50.0 | 28.0 |
| GPT-5.2 (Low) | 25.0 | 21.2 | 43.3 | 6.7 | 28.9 | 13.0 | 26.7 | 20.9 | 53.9 | 21.9 |
| GPT-5-Mini | 25.7 | 15.8 | 47.4 | 8.9 | 28.8 | 10.7 | 23.8 | 22.5 | 47.4 | 21.3 |
| Gemini-2.5-Pro | 39.3 | 11.6 | 31.1 | 13.9 | 12.5 | 4.9 | 27.0 | 19.6 | 34.7 | 18.2 |
| DeepSeek-V3.2 (High) | 37.0 | 14.1 | 47.1 | 16.1 | 21.2 | 16.3 | 35.2 | 22.9 | 53.8 | 24.5 |
| GPT-OSS-120B (High) | 32.0 | 16.3 | 42.3 | 6.1 | 35.6 | 16.3 | 41.0 | 19.6 | 50.0 | 23.7 |
| DeepSeek-V3.2 (Medium) | 35.7 | 15.4 | 45.8 | 9.6 | 21.5 | 15.0 | 27.6 | 22.9 | 40.0 | 22.3 |
| Kimi-K2-Thinking | 30.0 | 7.1 | 51.0 | 12.2 | 15.4 | 8.2 | 39.6 | 15.7 | 30.5 | 19.5 |
| Qwen3-30B (Think) | 22.0 | 5.4 | 51.9 | 6.7 | 18.3 | 7.6 | 25.7 | 15.7 | 36.8 | 16.8 |
| Qwen3-235B (Inst.) | 28.0 | 4.7 | 38.1 | 9.3 | 15.7 | 7.8 | 23.8 | 17.7 | 30.5 | 16.1 |
| Qwen3-4B (Think) | 24.0 | 3.8 | 38.4 | 5.6 | 5.8 | 7.1 | 21.9 | 15.8 | 31.6 | 13.7 |

The first nine rows are closed-source models; the last seven are open-weight.

### 4.2 Findings

- **Domain difficulty.** Collaboration domains are easiest (best scores about 51–52% on Email, Teams, Drive). ITSM (best 28.5%) and Hybrid (best 30.7%) are hardest.
- **Infeasible tasks.** Best clean-refusal rate is 53.9% (GPT-5.2 Low), then 53.8% (DeepSeek-V3.2 High).
- **Horizon.** Closed-source models fall from about 35% at 4 steps to under 20% at 16. Open-weight models fall faster, to about 10%.
- **Distractor tools.** Adding 5, 10 or 15 distractors changed Claude Sonnet 4.5 by +0.07, +2.35 and +0.64 points. Output tokens rose 4–9%. Tool discovery is not the bottleneck.
- **Cost.** Gemini-3-Flash gives 31.9% at about 0.03 USD per task. Opus 4.5 costs about 0.36 USD per task; Qwen3-235B about 0.007 USD.
- **Thinking budget (GPT-OSS-120B).** Low to high: CSM 1.1% to 16.3%, HR 0.0% to 16.3%, Drive 8.6% to 41.0%. ITSM plateaus at 6.1% from medium; Email peaks at medium (45.2%).

### 4.3 Planning ablations

Plan-conditioned execution (paper Table 3). CP is a plan written by Claude Sonnet 4.5; HP is the human-authored plan. Brackets show the gain over the ReAct baseline.

| Executor | Plan | CSM | ITSM | HR |
|---|---|---|---|---|
| Kimi-K2 | CP | 19.6 (+12.5) | 18.1 (+5.9) | 17.2 (+9.0) |
| Kimi-K2 | HP | 42.2 (+35.1) | 29.1 (+16.9) | 34.5 (+26.3) |
| Qwen3-30B | CP | 15.2 (+9.8) | 11.7 (+5.0) | 17.9 (+10.3) |
| Qwen3-30B | HP | 33.9 (+28.5) | 20.9 (+14.2) | 33.2 (+25.6) |
| Qwen3-4B | CP | 16.8 (+13.0) | 12.2 (+6.6) | 19.6 (+12.5) |
| Qwen3-4B | HP | 37.16 (+33.4) | 23.3 (+17.7) | 36.4 (+29.3) |

Multi-agent orchestration with Claude Sonnet 4.5 (paper Figure 6):

| Architecture | CSM | ITSM | HR |
|---|---|---|---|
| ReAct baseline | 16.7 | 17.6 | 21.6 |
| Planner + Executor | 27.4 | 22.2 | 30.4 |
| Planner + Decompose + Subtask Executor | 16.2 | 20.0 | 18.5 |
| Oracle human plan + Executor | 55.7 | 33.3 | 56.5 |

- Human plans add 14–35 points, about twice the gain from Claude-written plans.
- Qwen3-4B with human plans is competitive with much larger models.
- Task decomposition regresses below the baseline in CSM and HR, which the authors attribute to strong sequential state dependencies.

### 4.4 Failure modes

- **Missing prerequisite lookup.** Creating records without first querying what they depend on, leaving broken foreign-key links.
- **Cascading state propagation.** Not triggering the follow-up actions a policy requires after a state change.
- **Incorrect ID resolution.** Passing unverified identifiers to tools.
- **Premature completion hallucination.** Declaring the task done before all steps have run.

---

## 5. System prompts and policies

### 5.1 Role of the system prompt

Policies are established in the system prompt. There is no separate policy file or rules engine. Each task's `system_prompt` carries:

- **Role and authority.** Who the agent is and what permissions it holds.
- **Operating rules.** Do not ask the user for confirmation; never fabricate IDs; look up missing identifiers; if unable to proceed, give the reason and stop.
- **Domain policies.** The business rules that constrain how the task may be done.

How policies take effect:

- The user prompt states only the goal and does not repeat the policies.
- Policies can conflict with the request. Policy conflict is a deliberate design dimension, and it is one of the three mechanisms behind infeasible tasks.
- Applying a policy usually requires querying the database (is the entitlement active, is the assignee in the group).
- Policies are checked after the fact by the SQL verifiers. In Figure 2 the agent's policy-violating call is not blocked; the task fails verification. The paper does not say whether tools enforce any rules themselves **[inference: assume the agent must self-enforce]**.
- The gold plans cite the system prompt's policies to justify step ordering.

### 5.2 Prompt types seen in the appendix

The appendix shows one example task per domain. Prompts are set per task, so these examples do not classify whole domains.

| Domain | Example system prompt | Contents |
|---|---|---|
| CSM | Long policy document | Four roles with permissions; case state transitions; entitlement and installed-product rules; knowledge-linking rules; escalation rules; allowed enumeration values; free-text formatting and character limits |
| HR | Long policy document | Four roles with restrictions; case lifecycle; approvals; SLA breach rule; PII/PHI handling; validation lists |
| Drive | Long policy document | Permissions model; file lifecycle (trash preferred over delete); sharing rules; webhook requirements; validation and quotas |
| Teams | Medium | Four roles; general instructions; summary of core operations |
| Calendar | Short, generic | Role plus operating rules only |
| Email | Short, generic | Role plus operating rules only |
| ITSM | Short, generic | Role plus operating rules only |
| Hybrid | Short, generic | Role plus operating rules only |

- **ITSM shows that prompts vary by task.** The appendix example is short and generic, but the ITSM failure case study quotes a sectioned policy ("§7 Knowledge Creation", "§1 General Constraint").
- Some policy text cannot be acted on. The Drive policy requires explicit confirmation before destructive actions, but the setting is single-turn **[inference]**.

### 5.3 Verifier categories (paper Table 7)

The authors used Claude Sonnet 4.5 to tag each SQL verifier, from its expert-written description, as one of:

- **Task completion.** Was the user's objective achieved?
- **Integrity constraints.** Is the system in a consistent state with valid foreign keys?
- **Permission and process compliance.** Were the system policies followed?

| Domain | Task completion: samples | score | Integrity: samples | score | Policy compliance: samples | score |
|---|---|---|---|---|---|---|
| Teams | 100 | 82.3 | 20 | 90.0 | 8 | 81.3 |
| CSM | 183 | 58.3 | 30 | 70.0 | 120 | 45.5 |
| Email | 103 | 70.9 | 17 | 76.5 | 12 | 79.2 |
| ITSM | 176 | 53.7 | 30 | 50.6 | 70 | 30.0 |
| Calendar | 104 | 71.5 | 8 | 62.5 | 19 | 76.1 |
| HR | 182 | 63.2 | 47 | 56.0 | 94 | 50.4 |
| Drive | 105 | 75.1 | 26 | 87.8 | 6 | 66.7 |
| Hybrid | 152 | 60.0 | 23 | 72.5 | 18 | 61.1 |

- "Samples" appears to be the number of tasks with at least one verifier of that type **[inference]**. The task-completion counts match the per-domain task counts closely.
- Policy compliance is the weakest category in the heavy domains: ITSM 30.0%, CSM 45.5%, HR 50.4%.
- CSM, HR and ITSM hold 284 of the 347 policy-tagged tasks.
- The caption says integrity scores are highest overall and policy compliance lowest. That ordering does not hold in every domain (in ITSM and HR, integrity is below task completion).

### 5.4 Why Table 7 does not identify which tasks have policies

Every verifier is a SQL check on final database state, including the policy ones. "Policy compliance" is a post hoc label, not a separate mechanism. A task with no policy-tagged verifier is in one of three situations **[inference]**:

1. **No real policy in its system prompt.** The short generic prompt.
2. **A policy that the task does not put under pressure.** Following the request and following the policy never diverge, so no dedicated check is needed.
3. **A policy checked by a verifier tagged as something else.** In Figure 2, the "Link Case Knowledge" verifier fails because the agent linked an article as "resolution" where policy required "suggested". In the ITSM case study, the "New KB verifier" checks that the article is in the draft state, which enforces a policy section.

The paper does not give the proportions of these three cases.

Prompt length also does not predict policy verifiers: Drive has a long policy but only 6 policy-tagged tasks; Calendar has a short prompt but 19. In short-prompt domains the tag may capture constraints stated in the user request **[inference]**.

### 5.5 Policy rules that final-state checks cannot see

Final-state verification only sees what is left in the database. It would miss **[inference]**:

- reading or disclosing data outside the permitted scope
- taking steps in a forbidden order when the end state is the same, unless timestamps or audit rows record it
- process rules such as "one lookup per entity type" or "one operation at a time"

The paper mentions no trajectory-level checking.

### 5.6 Working notes for a policy-compliance focus

- Do not use domain as a proxy for "has a policy". Inspect each task's `system_prompt`; length should separate full policy documents from generic paragraphs.
- The release has no verifier-type column. Tagging verifiers as policy checks has to be redone, as the authors did with an LLM.
- For each task, compare the rules in the system prompt with what the SQL in `verifiers` actually checks. This gives the set of policies that are stated and enforced, stated but unenforced, and unenforceable by final state.
- Changing or truncating a system prompt changes the task, because the verifiers assume those exact policies.
- Check whether the infeasible tasks (the cleanest test of policy-driven refusal) are in the public split.

---

## 6. Related work positioning (paper Table 1)

| Benchmark | Domains | Tasks | Tools | Avg steps | DB tables | Refusal | Human plans |
|---|---|---|---|---|---|---|---|
| τ-bench | 2 | 165 | 28 | — | 3 | yes | no |
| τ²-bench | 3 | 279 | 56 | — | 9 | yes | no |
| WorkArena | 7 | 33 | 30 | 10 | 7 | no | no |
| WorkArena++ | 7 | 682 | 30 | 30–50 | 7 | yes | no |
| WorkBench | 5 | 690 | 26 | 2 | 5 | no | no |
| CRMArena | 1 | 1,170 | 27 | — | 16 | no | no |
| CRMArena-Pro | 3 | 8,560 | — | — | 25 | yes | no |
| EnterpriseBench | 5 | 500 | 46 | 3 | 17 | yes | no |
| **EnterpriseOps-Gym** | **8** | **1,150** | **512** | **9** | **164** | **yes** | **yes** |

The paper's positioning: prior enterprise benchmarks stay within one vendor ecosystem, have fewer than 25 tables and under 50 tools, and lack expert plans.

---

## 7. Authors' conclusions

- Current agents are not ready for autonomous enterprise deployment, even with oracle tools.
- Planning is the dominant bottleneck, not tool execution.
- More thinking budget helps but has domain-specific ceilings.
- Suggested research directions: constraint-aware plan generation, long-horizon state management, safe refusal and escalation.

---

## Sources

- Paper: <https://arxiv.org/abs/2603.13594>
- Dataset card: <https://huggingface.co/datasets/ServiceNow-AI/EnterpriseOps-Gym>
- Code repository (not opened directly): <https://github.com/ServiceNow/EnterpriseOps-Gym>
- Project site: <https://enterpriseops-gym.github.io>
- Third-party write-up citing the 60% public split: <https://discuss.pytorch.kr/t/autosynthdata-servicenow-feat-enterpriseops-gym/12083>
