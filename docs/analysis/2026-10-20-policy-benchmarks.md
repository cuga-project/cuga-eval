# Benchmarks where agents must follow enterprise policy

Companion to `2026-10-20-agent-policy-enforcement-sota.md`. As of 2026-10-20; best scores re-checked on 2026-10-21 (Artificial Analysis leaderboards, papers, READMEs).

## At a glance

| Benchmark | Policy given as | Policy size | How the work arrives | Graded on | Best reported |
|---|---|---|---|---|---|
| τ2-bench (airline, retail, telecom) | System prompt, shared by all tasks of a domain | A few pages (airline: 166 lines) | Simulated customer in a chat | Final database state + required messages | Frontier models > 80% pass^1 |
| **τ³ banking_knowledge** (Sierra) | **Knowledge base the agent searches with tools** | 698 documents, ~195K tokens | Simulated customer in a chat | Final database state, pass^k | 51.3% pass@1 (Qwen3.8 Max, AA leaderboard); ~25.5% pass^1 at launch |
| **HANDBOOK.md** (Surge AI) | **A document file in the workspace, unique per task** | 20–124 pages (average 43, ~22K tokens) | One short instruction; the requests sit in email, Slack, Jira and files | Rubric: required actions done, prohibited actions not done | Strict pass@1 ~20–22% for the top models |
| **EnterpriseOps-Gym** (ServiceNow) | System prompt with domain policies | 8–24k characters; several variants per domain | One instruction per task, no conversation | SQL checks on the final database | 51.1% task success (Claude Fable 5 Max, AA leaderboard); paper: 37.4% (Claude Opus 4.5) |
| **AutomationBench-AA** (Zapier; run by Artificial Analysis) | **Business data the agent reads with tools** (e.g. a "Policy" worksheet in a Google Sheet) | Short rule tables per task | One instruction plus trigger data, no conversation | Assertions on the final state; AA gives partial credit but **any guardrail violation scores the task 0** | AA: 77.5% (Gemini 4 Argon High); public set strict pass: 50.3% (Claude Opus 5, max) |

## How the task is given to the agent

**τ³ banking_knowledge.** A simulated customer chats with the agent, for example to dispute a transaction or raise a credit limit. The rules the agent needs (verification steps, dispute procedures, fees, retention offers) are mostly not in the prompt: they sit in a 698-document knowledge base, and some exist only there. The agent finds them with search tools (BM25, dense embeddings, or a shell), so **the policy is a tool output**. A task needs 18.6 documents on average. Some action tools are hidden until the agent unlocks them by name, using instructions from the knowledge base. Giving the agent the right documents directly ("golden retrieval") raised pass^1 only from 25.5% to about 40% at launch, so finding the policy is only part of the problem. Boaz found several grading and consistency issues; Sierra fixed banking_knowledge grading in July 2026.

**HANDBOOK.md.** The agent gets one line, such as "Handle today's unread emails according to the instructions in the provided handbook." The real work sits inside a simulated company: an inbox, Slack channels, Jira queues, spreadsheets and PDFs, reached through file, terminal and Office tools and MCP services (Gmail, Calendar, Slack, Jira, Shopify). The policy is a handbook file in the workspace (PDF, Word or HTML, up to 124 pages). Each task changes rules and thresholds of one of 10 base handbooks, so the agent cannot rely on memory. Some requests in the environment ask the agent to break the handbook without being adversarial, for example a VP's email ordering a termination that needs written approval from named people. A task takes about 17 steps and 30 tool calls.

**AutomationBench-AA.** Each task is a short instruction plus trigger data, with no conversation, over a simulated business (CRM, Sheets, Gmail, Slack, payroll and others) across sales, marketing, operations, support, finance and HR. The rules are business data the agent must read with tools, so again **the policy is a tool output**. For example, an HR offboarding task says "Follow our current offboarding policy", and the policy is an "Offboarding Policy" worksheet in a Google Sheet. The same prompt also asks the agent to process severance, which that policy forbids ("HR Ops must NOT process severance directly — route all severance requests to Payroll"). So the request itself is the trap. Assertions check the final state, including actions that must not happen. Artificial Analysis runs a private, held-out set of 657 tasks with REST-style tools; the public repo has 600 scored tasks.

**EnterpriseOps-Gym.** Each task is a single record: a `system_prompt` with the agent's role and the domain policies, a `user_prompt` with the instruction, and a set of tools from containerized MCP servers backed by seeded databases. The 8 domains are ITSM, HR, customer service, email, calendar, Drive, Teams, and hybrid tasks across systems: 512 tools and 164 tables in all. There is no simulated user. A tool-set mode adds 5, 10 or 15 random distractor tools, which tests tool selection. Tasks take 7 to 30 steps and are checked by SQL queries on the final database. Policy-heavy domains score lowest (ITSM 28.5%, secondary source). Agents often fail to refuse infeasible tasks: the best model refuses 53.9% (paper).

## Also relevant

| Benchmark | What it measures | Key number |
|---|---|---|
| **SOP-Bench** (Amazon) | Agents following expert-written standard operating procedures with tools, 10–12 business domains, ~1,800–2,000 tasks | Function-calling agent ~27%, ReAct ~48%; with a much larger tool registry, agents picked wrong tools almost every time |

## What they test for a policy layer

| Benchmark | Main policy challenge | Fits our design (SOTA notes) |
|---|---|---|
| τ³ banking_knowledge | Find the right rule in a large knowledge base, then apply it; tools unlocked mid-task | Section 6, policy as tool output: compile the KB offline per document; semantic verifier for the rest |
| HANDBOOK.md | Long, task-specific policy document; in-environment requests that conflict with it | Section 5, long PDFs: classify and compile per task; a rule like "termination needs written approval from X or Y" is an exact gate check |
| EnterpriseOps-Gym | Access control and referential integrity in long multi-step tasks; distractor tools | Closest to the gate as designed: policy known up front, writes graded by database state |
| AutomationBench-AA | Policy read from business data; the task request conflicts with it; a violation zeroes the task | Section 6 (policy as tool output). Compiling is hard because the rules arrive as data per task, so it needs runtime extraction plus the semantic verifier; a blocked forbidden write directly protects the score |
| τ2-bench | Short shared policy; confirmation and eligibility rules | Our first test bed (airline) |

Practical notes: we already have a CUGA adapter for AutomationBench (`benchmarks/automationbench/run_cuga.py`); the run stopped at 3 of 60 tasks because of LiteLLM rate limits. HANDBOOK.md ships its harness for Harbor (OpenHands-based, `harbor run`), which we already use for AppWorld. Only 3 sample tasks are public; the full 65 are available from benchmarks@surgehq.ai.

## Sources

- τ³ / τ-knowledge: [Sierra blog](https://sierra.ai/blog/tau-knowledge); code on the [`dev/tau3` branch of tau2-bench](https://github.com/sierra-research/tau2-bench/tree/dev/tau3); paper arXiv 2603.04370; [Artificial Analysis leaderboard](https://artificialanalysis.ai/evaluations/tau3-banking)
- HANDBOOK.md: [Surge AI blog](https://surgehq.ai/blog/handbook-md); [GitHub](https://github.com/surge-ai/handbook); [arXiv 2607.25398](https://arxiv.org/abs/2607.25398). Secondary coverage cites 36.2% for the best of 30 configurations; the blog gives ~20–22% strict pass@1 for the top models. Check the paper for the exact setting
- EnterpriseOps-Gym: [dataset card](https://huggingface.co/datasets/ServiceNow-AI/EnterpriseOps-Gym) (lists 1,115 tasks; the paper says 1,150); paper arXiv 2603.13594; [Artificial Analysis leaderboard](https://artificialanalysis.ai/evaluations/enterprise-ops-gym-aa); model results from [MarkTechPost](https://www.marktechpost.com/2026/03/18/servicenow-research-introduces-enterpriseops-gym-a-high-fidelity-benchmark-designed-to-evaluate-agentic-planning-in-realistic-enterprise-settings/) (secondary)
- AutomationBench: [GitHub](https://github.com/zapier/AutomationBench); paper arXiv 2604.18934; [AutomationBench-AA leaderboard](https://artificialanalysis.ai/evaluations/automationbench-aa); offboarding example from `automationbench/domains/hr/tasks.py` (`hr.offboarding_automation`)
- τ2-bench: [GitHub](https://github.com/sierra-research/tau2-bench)
- SOP-Bench: [arXiv 2506.08119](https://arxiv.org/abs/2506.08119)
