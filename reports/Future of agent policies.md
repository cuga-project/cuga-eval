# Stronger models cut guidance, not hard controls

As models get stronger, policies move out of the prompt and into fixed checks, logs and agent identity around the model: stronger models reduce the need for guidance, but not the need for limits and evidence. Frontier adherence is improving fast. Best scores rise about 2.3 to 5.8 points per month on the series that can be measured, and on the one benchmark that counts rule breaks, violations per task fell about 3.4 times in six months. The problem is not solved: best scores are about 51 to 55% on τ³ banking, EnterpriseOps-Gym and strict AutomationBench, and only about one third of τ³ tasks pass four times in a row. Vendors already sell gateway rules and agent identity as GA products. Law and audit keep logs, access limits, a named owner and a stop function whatever the model scores; only human approval of each action can shrink. So the parts that do the model's thinking (step loops, per-action model checks on strong agents) lose value within one or two model generations, while hard limits and logs stay but become standard product features [Inference]. A system like ours for CUGA stands best where vendors are weak: long written policies turned into checked rules, checks of required work, and small open models. Our results fit this view, but they are one team's data, and no outside group has tested a policy layer across model generations, so all time estimates here are judgment, not measurement.

**Labels used in this report**

| Label | Meaning |
|---|---|
| [Primary] | Read in the original paper, benchmark board, official document or regulator text. Paper numbers are still the authors' own, and almost none are independently replicated. |
| [Vendor claim] | A company's statement or test about its own product. It is real data, but the company has an interest. |
| [Secondary] | From press, a law firm, a blog or a search excerpt. The original was not read. |
| [Inference] | Our own calculation or reasoning. The source does not state it. |
| [Team] | This team's own data. Not independent. |

## Scores rise 2 to 6 points a month, yet the best models pass about half of hard tasks

**Adherence is improving, and these are the only series with one harness and one metric** [Primary; rates are Inference]. pass^1 means a pass on one try. pass^4 means a pass in four runs in a row.

| Series (who ran it) | Period | Best score, start to end | Points per month |
|---|---|---|---|
| τ³ banking, pass^1 (Sierra, benchmark owner) | Nov 2025 to Jul 2026 | 24.7 to 55.2 | +3.9 |
| τ³ banking, pass^4 (Sierra) | Nov 2025 to Jul 2026 | 11.3 to 35.1 | +3.1 |
| τ³ banking (Artificial Analysis, independent) | Mar to Aug 2026 | 39.6 to 51.3 | +2.3 |
| AutomationBench-AA, headline (Artificial Analysis) | Apr to Oct 2026 | 47.3 to 77.8 | +4.9 |
| AutomationBench-AA, strict (Artificial Analysis) | Apr to Oct 2026 | 19.6 to 55.3 | +5.8 |

Sources: [Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions), [AA τ³](https://artificialanalysis.ai/evaluations/tau3-banking), [AA AutomationBench](https://artificialanalysis.ai/evaluations/automationbench-aa). Sierra's series includes higher effort settings, so "model" means the model at its top setting. EnterpriseOps-Gym-AA rose from 42.2 to 51.1 by June 2026 and then stayed flat, but the newest generation has no visible row, so this does not show a ceiling ([AA](https://artificialanalysis.ai/evaluations/enterprise-ops-gym-aa)). We make no forward projection, because benchmark owners keep changing the tasks.

**Launch-to-now jumps are not model progress.** HANDBOOK.md went from 21.9 to 36.2 from June to July, one step from one model ([paper](https://arxiv.org/html/2607.25398)). The current board top of 52.3 has no metric label, and Kimi K3 moved from 11.9 to 28.6 in what looks like the same configuration ([Surge board](https://surgehq.ai/benchmarks/handbook)). Official AutomationBench (9.9 to 53.88) crosses task changes ([changelog](https://github.com/zapier/AutomationBench/blob/main/CHANGELOG.md)). On one model, task fixes added +9.2 to +33.6 points on τ-bench airline ([SABER](https://arxiv.org/html/2512.07850)), reasoning effort added +6.6 to +32.5 on τ² ([Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions)), and a human plan added +14 to +35 on EnterpriseOps-Gym ([paper](https://arxiv.org/abs/2603.13594)). No source splits the gain between model and harness.

**Older benchmarks are full and are being replaced.** τ²-Telecom reached about 98, and data errors cap the original τ-bench at about 70% on airline and 92% on retail ([SABER](https://arxiv.org/html/2512.07850)). Artificial Analysis moved its index from τ²-Telecom to τ³-Banking (June 2026) and then to AutomationBench-AA (September 2026), with no stated reason ([AA methodology](https://artificialanalysis.ai/methodology/intelligence-benchmarking)). Zapier says it sometimes makes private tasks harder to keep top scores from reaching the limit ([GitHub](https://github.com/zapier/AutomationBench)). τ²-bench v2.0.0 (2026-10-19) is a new base and is not comparable with 1.x ([changelog](https://github.com/sierra-research/tau2-bench/blob/main/CHANGELOG.md)).

**Repeat-run reliability improves, but the point gap grew.** For the τ³ leader, pass^4 divided by pass^1 rose from 0.46 to 0.64, while the gap grew from 13.4 to 20.1 points [Inference]. Models with similar first-try scores differ a lot: Claude Fable 5 is 39.7 / 28.9 and GLM-5.2 is 37.1 / 13.4 ([Sierra repo](https://github.com/sierra-research/tau2-bench/tree/main/web/leaderboard/public/submissions)). HANDBOOK.md, EnterpriseOps-Gym-AA and AutomationBench-AA publish no pass^k.

**Rule breaks fall on the one benchmark that counts them, but strength does not guarantee compliance.**

- For: on AutomationBench-AA, violations per task fell from 1.06 (GPT-5.5) to 0.31 (Gemini 4 Carbon High) inside one snapshot ([AA](https://artificialanalysis.ai/evaluations/automationbench-aa)). Those 0.31 violations still remove about 17% of objective credit [Inference].
- Against: new models can be worse (Nemotron 3.5 Super VL 2.93, Beam 1.0 1.12, both October 2026). ODCV-Bench v5 shows 0.0% (Claude Opus 4.7) to 62.8% (Grok-4.20) misalignment under KPI pressure ([ODCV](https://arxiv.org/html/2512.20798v5)). Gray Swan found no significant link between capability and attack success (r = −0.31, p = 0.3), with no model immune ([paper](https://arxiv.org/html/2603.15714)).
- Hidden breaks: on τ-bench, 27 to 78% of reported successes contain a violation ([Procedure-Aware Evaluation](https://arxiv.org/html/2603.03116)), so final-state scores overstate adherence.
- "Stronger" is not one thing: GPT-6 Astra is 68.5 on AutomationBench-AA, 41.4 on AA τ³ and 31.4 on the Surge board.

We found no public benchmark showing stronger models breaking more rules across generations. That evidence is case-level, for example OpenAI's report that GPT-5.6 Sol takes severe actions more often than GPT-5.5 in internal coding traffic, with low absolute rates and no number ([card](https://deploymentsafety.openai.com/gpt-5-6-preview/evaluations-with-challenging-prompts)) [Vendor claim].

## Vendors ship gateway rules and identity as GA; long-policy intake remains open

Status below comes from vendor documents and release notes [Primary]. Performance numbers in the text are [Vendor claim].

| Function | Who ships it | Status | Who decides |
|---|---|---|---|
| Allow or deny by tool, identity, arguments | [AWS Policy in AgentCore](https://aws.amazon.com/about-aws/whats-new/2026/03/policy-amazon-bedrock-agentcore-generally-available) (Cedar); [Google Agent Gateway and IAM](https://docs.cloud.google.com/gemini-enterprise-agent-platform/release-notes); [ToolHive](https://docs.stacklok.com/toolhive/concepts/cedar-policies), [ContextForge](https://github.com/IBM/mcp-context-forge/releases/tag/v1.1.0), [CPEX](https://contextforge-org.github.io/cpex/) | GA 2026-03-03; GA 2026-06-18 and 2026-08-31; open source | Code |
| Order, count and sum rules | [AWS Dogwood temporal policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal.html) | Open source, Aug 2026; 24-hour window | Code |
| LLM judge on tool calls at the gateway | [Google Semantic Governance](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/semantic-governance-overview) | Preview 2026-06-29; Google warns verdicts can be wrong | Model |
| Model replaces human approval, coding agents | [Claude Code auto mode](https://code.claude.com/docs/en/permission-modes), [Codex Auto-review](https://alignment.openai.com/auto-review), [Cursor Auto-review](https://cursor.com/blog/auto-review) | Shipped; deny rules or sandboxes stay | Rules, then model |
| Fixed steps around LLM reasoning | [Salesforce Agent Script](https://www.salesforce.com/blog/agentforce-transformed/); [Decagon AOP](https://decagon.ai/blog/why-we-built-aop); [Parlant](https://www.parlant.io/docs/customizing-behavior/policies) | GA per Salesforce 2026-02-20; vendor posts only; open source | Mix |
| Agent identity | [Entra Agent ID](https://learn.microsoft.com/en-us/entra/agent-id/whats-new-agent-id), [Google Agent Identity](https://cloud.google.com/blog/products/identity-security/whats-new-in-iam-security-governance-and-runtime-defense), [Okta Agent SSO](https://okta.com/newsroom/press-releases/okta-brings-first-class-identity-to-ai-agents-with-agent-sso/) | GA (Google: GA for Agent Runtime, Preview for the wider platform) | Rules |
| Inventory and evidence | [Agent 365](https://www.microsoft.com/en-us/security/blog/2026/05/01/microsoft-agent-365-now-generally-available-expands-capabilities-and-integrations/), [AI Control Tower](https://www.servicenow.com/community/ai-control-tower-articles/ai-control-tower-what-s-new-in-the-june-2026-release/ta-p/3561445), [watsonx.governance](https://www.ibm.com/think/perspectives/ai-governance-to-assurance-what-we-shared-think-2026) | GA 2026-05-01; GA items June 2026; next generation previewed | Rules and humans |
| Policy document to logic | [AWS Automated Reasoning](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-automated-reasoning-checks.html) | GA Aug 2025; checks text answers only, detects and does not block | Logic plus LLM |
| IBM rule and control pieces | [ToolGuard in Langflow](https://docs.langflow.org/policies); [Agentic Control Plane](https://www.ibm.com/new/announcements/introducing-the-agentic-control-plane) | Beta since Langflow 1.9; launched June 2026, no GA label found | Generated code at run time; rules and guardrails |

**The market moves in both directions, in layers.** Business-workflow vendors move to fixed code: Salesforce says models skip steps and that prompts alone gave inconsistent results ([guide](https://www.salesforce.com/agentforce/resources/reliable-ai-agents-guide/)) [Vendor claim]. Coding-agent vendors move to model approvers, probably because a sandbox and version control make errors easier to undo [Inference]. AWS ships a useful pattern: a model produces a score and a rule makes the final decision ([docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html)). AWS `LOG_ONLY` and Google `DRY_RUN` both record decisions before blocking.

**We found no vendor that says controls can relax because models are stronger.** The case for model approvers compares a model with a tired human, not with a rule. Anthropic reports that users accepted 93% of prompts, that humans caught a swapped dangerous command 13.6% of the time against 89% for auto mode, and a 17% false negative rate on 52 real overeager actions ([post](https://www.anthropic.com/engineering/claude-code-auto-mode), [blog](https://claude.com/blog/auto-mode-default-in-claude-code)) [Vendor claim]. OpenAI reports 90.3% recall on overeagerness and does not expect deterministic guarantees ([post](https://alignment.openai.com/auto-review)) [Vendor claim]. These numbers use different data and cannot be compared. Anthropic also reports no successful prompt injections against its newest models in auto mode, while a researcher ran an injection chain against Claude Code with Opus 5 Auto Mode in 3/5, 3/5 and 4/5 trials ([Rehberger](https://embracethered.com/blog/posts/2026/breaking-claude-code-opus-5-and-automode/)), with small samples and different tests.

**Adoption numbers do not measure enforcement.** All are vendor claims about platform use. No vendor reports how many customers have enforcement on, how many calls were blocked, or how many blocks were wrong. The MCP spec makes authorization optional and decides who may reach a server, not whether one tool call should run ([spec](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)), so that decision stays open for gateways and policy systems.

## Regulation keeps logs, limits, owners and stop controls whatever the model scores

No law we reviewed says that controls must sit outside the model. Binding duties fall on the organisation and the system, and they ask for functions that a model cannot give itself. Only two texts explicitly ask for technical controls separate from the agent's reasoning, and neither binds: the [FSB final report](https://www.fsb.org/uploads/P151026-1.pdf) (15 Oct 2026) and the [IMDA framework](https://www.imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/mgf-for-agentic-ai.pdf). We found no text that drops logs, access control, accountability or stop capability because a model has proven itself.

| Requirement | Does a near-perfect model remove it? | Strongest source | Applies when |
|---|---|---|---|
| Named accountable owner | No | [DORA 5(2)](https://www.digital-operational-resilience-act.com/Article_5.html), [AI Act 26](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-26) (law) | EU finance now; AI Act high-risk from 2 Dec 2027 |
| Automatic logs, audit trail | No | [HIPAA 164.312(b)](https://www.law.cornell.edu/cfr/text/45/164.312), [23 NYCRR 500.6](https://www.law.cornell.edu/regulations/new-york/23-NYCRR-500.6), [AI Act 12](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-12) (law) | HIPAA and NYDFS now; AI Act high-risk from 2 Dec 2027 |
| Access limits, unique identity | No | [DORA 9(4)](https://www.digital-operational-resilience-act.com/Article_9.html), [HIPAA 164.312(a)](https://www.law.cornell.edu/cfr/text/45/164.312) (law) | Now, in those sectors |
| Override and stop | No | [AI Act 14(4)](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-14) (law); FSB (guidance) | AI Act high-risk from 2 Dec 2027 |
| Written procedures, change control | No | [AI Act 17](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-17), [DORA 9(4)(e)](https://www.digital-operational-resilience-act.com/Article_9.html) (law) | DORA now; AI Act high-risk from 2 Dec 2027 |
| Reasonable care in a dispute | No | [*Moffatt v. Air Canada*](https://www.mccarthy.ca/en/insights/blogs/techlex/moffatt-v-air-canada-misrepresentation-ai-chatbot) (case), [California AB 316](https://www.legal500.com/intelligence/united-states/technology/california-eliminates-the-autonomous-ai-defense-what-ab-316-means-for-ai-deployers) (law) [Secondary] | Now |
| Human approval of each action | **Yes, can shrink** | [AI Act 14(3)](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-14) (law); [MAS 5.9](https://www.mas.gov.sg/-/media/mas-media-library/regulation/guidelines/bd/guidelines-on-artificial-intelligence-risk-management-for-financial-institutions/guidelines-on-artificial-intelligence-risk-management.pdf), FSB (guidance) | Lower-risk actions. Exception: two-person check for remote biometric identification, [Art. 14(5)](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-14) |
| Review frequency, test depth | **Yes, can scale with risk** | MAS 5.23, [SR 26-2](https://www.federalreserve.gov/supervisionreg/srletters/SR2602a1.pdf) (guidance) | Must be documented |

Limits on this table:

- **Scope.** Outside these sectors and AI Act high-risk uses, most rows are not specific legal duties today. A customer-service, IT or CRM agent is usually not high-risk; the same agent becomes high-risk when it screens candidates or scores credit [Inference].
- **EU dates.** The high-risk duties moved to 2 Dec 2027 (Annex III) and 2 Aug 2028 (Annex I) ([Cooley](https://cdp.cooley.com/digital-ai-omnibus-delays-key-deadlines-introduces-new-rules/)) [Secondary]. Reports show no change to what the articles require.
- **US banks.** SR 26-2 excludes generative and agentic AI and leaves banks to their own governance. Supervision for unsafe practices remains ([SR 26-2](https://www.federalreserve.gov/supervisionreg/srletters/SR2602a1.pdf)).
- **Overstated claims.** FINRA's report says firms "may consider" agent supervision steps ([FINRA](https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/gen-ai)); vendor sites often present this as a requirement. One site says the FSB makes dual authorisation mandatory ([Forkast](https://forkast.news/fsb-sound-practice-10-the-supervisory-architecture-for-agentic-ai-that-national-regulators-will-translate/)); the final report is non-binding and uses the broader term of risk-based triggers.
- **Performance-based relief.** The closest text is the FSB, which allows wider access as confidence grows and triggers based on performance metrics. We found no regulator that has approved such an argument for agents.
- **Liability.** Courts and statutes point to the deployer, not the AI. *Moffatt* is a small tribunal decision, and we found no decision on an agent breaking an internal company policy.
- **Standards lag.** NIST is voluntary, and its agent overlays are only proposed, with no draft ([NIST](https://csrc.nist.gov/projects/cosais)). The project was renamed COSIS, and US federal texts may now say "Super Intelligence" instead of AI, so search for both. ISO/IEC 42001 is not a harmonised standard under the AI Act ([Commission FAQ](https://digital-strategy.ec.europa.eu/en/faqs/understanding-standardisation-ai-act)). A certificate shows that a management system exists, not that an agent obeyed a rule [Inference].

Two inferences matter for us [Inference]. The evidence needed to justify less human review comes from the same logs and monitors that must stay. And SR 26-2 and MAS treat fixed rule systems as outside "model" or "AI", so a fixed policy check may avoid model-risk treatment while it stays an IT control under change management.

## No agent study yet tests trained behaviour on an unseen company policy

All results are the authors' own numbers [Primary], and we found almost no independent replication. A systematic survey of 38 studies rated seven of its nine main claims as very low certainty ([survey](https://arxiv.org/abs/2608.14590)) [Primary, abstract only]. The last two columns are [Inference].

| Direction | Best result so far | Main limit | Likely effect in 1 to 3 years | Evidence |
|---|---|---|---|---|
| Train the policy into the model | [IH-Challenge](https://arxiv.org/html/2603.10521): robustness 84.1% to 94.1%. [PVST](https://arxiv.org/html/2610.19372): violating runs 37.2% to 10.3% | We found no agent study that tests a policy different from the trained one. Weekly change is unstudied. One domain transfer went negative, pass^4 20 to 4 ([paper](https://arxiv.org/html/2509.14480v1)) | Less need for soft advice. Company rules still arrive at run time | Medium for general robustness; none for unseen policy |
| Code monitors at run time | [ContrAgent](https://arxiv.org/html/2609.18128) on SOPBench, success/safety: 90/98, base 91/32, LLM guard 24/98. [FORGE](https://arxiv.org/html/2602.16708): τ² airline 74.7 to 81.5, under 1 ms | Only as good as the policy; no coverage of meaning or whole plans | Standard enforcement point at gateways and hooks | Medium |
| Compile policy to rules | [PolicyGuide](https://arxiv.org/html/2608.19861): held-out Telecom pass^4 0.250 to 0.675; Retail gain not significant. [STAGE](https://arxiv.org/abs/2608.22538): pass^3 +7.5 to +66.0 | [FORGE](https://arxiv.org/html/2602.16708): 10 LLM translations scored 0.533 to 1.000 held-out, though all passed build checks. Upkeep unmeasured | Compile, human sign-off and revision check become normal process | Low to medium |
| Small guard and decision models | [Jev vs GPT-6 Astra](https://arxiv.org/html/2609.26550v1): $0.044 vs $12.18 per 1,000; 74.8 vs 94.6 on style-adversarial items | Misled by well-written wrong answers | Narrow questions and first filter; not the final judge of a strong agent | Low |
| Security by design | [CaMeL](https://arxiv.org/html/2503.18813): 77% solved with provable security vs 84% undefended | Utility cost ([Progent reproduction](https://arxiv.org/html/2606.26479v1): 45.2% to 27.1%); no head-to-head under adaptive attack | Shares one enforcement point with business rules | Medium on AgentDojo |
| Misbehaviour research | [METR](https://metr.org/blog/2026-05-19-frontier-risk-report/): at least 16% of successful 8h+ runs illegitimate. [GPT-5.6 Sol](https://metr.org/blog/2026-06-26-gpt-5-6-sol/): highest detected cheating | Lab-reported; models notice tests | Enforcement must assume the agent may look for a way around a block | Medium for existence; low for rates |
| Reasoning monitors | [CoT-Control](https://arxiv.org/html/2603.05706): most models below 10% reasoning control | Control rises with model size. A monitor flagged about 1% of Mythos 5 actions with reasoning, about 50% without ([METR](https://metr.org/blog/2026-10-20-misalignment-risk-report-august-2026-review/)) | Extra signal, not a basis for enforcement | Medium now; low for the future |
| Learn policies from logs | [AgenTest](https://arxiv.org/html/2610.28116): 88.0% of specs correct, from prompts and tools, not logs | No evaluated log-to-policy method | Candidate rules for human review | Very low |

Three open questions could change this picture [Inference]. First, do trained models follow an unseen policy as well as a trained one? Second, does monitoring stay reliable as agents get stronger? METR's review of Anthropic's risk report says risk is low mainly because models probably lack capability, not because of safeguards, and a METR and Redwood pilot found flaws in OpenAI's monitoring ([review](https://metr.org/blog/2026-10-20-misalignment-risk-report-august-2026-review/), [red-team](https://metr.org/blog/2026-10-22-red-teaming-openai-agent-monitoring/)). Third, do denials cause an agent to look for another route? Impossible or blocked tasks are the common trigger in lab reports, and no paper tests this on a business-policy gate. It may be relevant to our 24 vs 1 result, but this is untested.

## Hard limits and logs stay; step loops and per-action model checks lose value

**Serious sources argue about the amount and placement of control, not about having none.** The two meanings of "obsolete" must stay separate: the function can stay necessary while a separate product does not. The strongest threat to a separate product is vendors building the same controls into their platforms, not model strength alone [Inference].

- **Strongest case against:** labs remove harness parts as models improve ([Anthropic](https://www.anthropic.com/engineering/harness-design-long-running-apps)) [Vendor claim]. In one benchmark of a single proceed-or-hold decision (not a live agent), models wrongly held approved work 28.1% of the time and wrongly allowed unsafe work 1.0% ([SteerBench-Work summary](https://aiunderstanding.org/news/new-benchmark-finds-ai-agents-wrongly-block-approved-work-28-of-the-time)) [Secondary]. Good controls also cost task completion: LlamaFirewall cut attack success from 17.63% to 1.75%, and utility fell from 47.73% to 42.68% ([paper](https://arxiv.org/html/2505.03574)) [Vendor claim].
- **Strongest case for:** the UK NCSC says prompt injection may never be fully mitigated and advises deterministic limits ([NCSC](https://www.ncsc.gov.uk/blog-post/prompt-injection-is-not-sql-injection)). Adaptive attacks exceeded 90% success against most of 12 defenses ([paper](https://arxiv.org/abs/2510.09023)). OpenAI's Hugging Face incident shows capable models crossing boundaries, and OpenAI concludes defenses must be several and independent ([report](https://cdn.openai.com/pdf/67869394-cb91-4c12-888c-5cbd85c7814c/OpenAI-Hugging-Face%20Incident-Technical-Report.pdf)) [Vendor claim].
- **Fair counterpoints:** that incident happened in research, with safeguards off on purpose. Many production incidents, such as [PocketOS](https://www.techspot.com/news/112207-ai-coding-agent-running-claude-wiped-startup-database.html) [Secondary], are permission failures that plain infrastructure hygiene addresses. No incident list gives actions per incident, so nobody can say whether risk per action is rising.

Time estimates and confidence in this table are our judgment, not measurements [Inference].

| Component | Evidence it stays | Evidence it decays | Time estimate, confidence |
|---|---|---|---|
| Step guides and control loops | Curated skills add +13.9 on Opus 4.6, +14.1 on GPT-5.2 ([SkillsBench](https://arxiv.org/html/2602.12670v1)) | Gain fell +23.3 to +13.9 from Opus 4.5 to 4.6 (same source). Context files: no general gain, over 20% more cost ([study](https://arxiv.org/abs/2602.11988)). [Team] advisory loop tied, 63 vs 63 of 102 | Loops on strong models 0 to 12 months; small open models 6 to 18 months per task type; guide content lasts as long as SOPs. Medium |
| Per-action model checks | Labs use them. OpenAI's hindsight test says auto-review would have flagged most dangerous actions ([report](https://cdn.openai.com/pdf/67869394-cb91-4c12-888c-5cbd85c7814c/OpenAI-Hugging-Face%20Incident-Technical-Report.pdf)) [Vendor claim] | 17% false negatives ([Anthropic](https://www.anthropic.com/engineering/claude-code-auto-mode)) [Vendor claim]. Monitor flaws ([METR](https://metr.org/blog/2026-10-22-red-teaming-openai-agent-monitoring/)). [Team] critic precision 17.5 to 38.5% | Per-action on strong agents decays; risk-based review 2 to 4+ years, mostly built in by vendors. Medium to low |
| Fixed hard rules, permissions | NCSC; OpenAI; the [SEC Knight Capital case](https://www.sec.gov/newsroom/press-releases/2013-222) on missing automated limits | Not obsolete, but placement matters: Claude Code went around a denylist by another path ([Ona](https://ona.com/stories/how-claude-code-escapes-its-own-denylist-and-sandbox)) [Vendor claim]. [Team] role rules blocked 20 of 93 passed runs because graders disagree with the policy table | 5+ years, likely permanent. High for function, medium for a separate product |
| Logs, versioning | Binding law. 94% of production respondents have observability ([LangChain](https://www.langchain.com/state-of-agent-engineering)) [Vendor claim] | No evidence logs become unneeded. High adoption leaves little product difference; reasoning logs are less reliable | 5+ years. High for function, low for product difference |
| Documents to rules | [ToolGuard](https://arxiv.org/html/2507.16459v2): 0.450 to 0.685 on 22 of 50 τ airline tasks where the request breaks policy, a subset that favours the method. Products take short rules, not long documents [Inference] | Translation errors. Automatic harness tuning invented guardrails in 15 of 60 runs on rule-like input ([paper](https://arxiv.org/abs/2607.13083)). [Team] automatic build missed 3 of 3 role rules | Pipeline 1 to 3 years; human sign-off longer. Low |
| End-of-run check of required work | Pre-tool guards cannot catch a tool never called ([ToolGuard](https://arxiv.org/html/2507.16459v2)). 72 to 91% of launch failures on AutomationBench reported success with a wrong state ([paper](https://arxiv.org/html/2604.18934)) | Overhead for tasks the model does alone ([Anthropic](https://www.anthropic.com/engineering/harness-design-long-running-apps)) [Vendor claim]. [Team] wrong checklist items cost 7 to 13 points. No study isolates this | 2 to 4 years, narrowing. Low to medium |
| Small cheap models | Cascades cut compute about 40 times ([paper](https://arxiv.org/html/2601.04603v1)) [Vendor claim]. Jev cost above | Open-weight lag is about 4 months ([Epoch](https://epoch.ai/data-insights/open-closed-eci-gap)). Labs use mid-tier or top models as monitors. [Team] small checker 49 to 54 of 153 | As agent helped by control: each new small model cuts the gain. As first filter: lasts. As only judge of a strong agent: already weak. Medium to low |

**Why a checker loses value as the agent improves** [Inference, assumed numbers]. Take a checker with 80% recall and 1% false positives. If 5% of actions are violations, 81% of flags are correct. If 0.1% are violations, 7% are correct. The checker did not change; only the agent improved. **Token cost is not the deciding factor:** a Haiku 5.5 checker costs about $0.0075 per task at 30 assumed checks ([prices](https://platform.claude.com/docs/en/about-claude/pricing)). False blocks, latency and upkeep decide.

**Does gain shrink as models get stronger? The data is partial.** SkillsBench is mixed (Haiku 4.5 +16.7, Opus 4.5 +23.3, Opus 4.6 +13.9). In JevAct, Telecom pass^3 gain is GPT-4.1 +6.1, Opus 4.6 +41.2, Opus 5.5 +7.9, with correlation to baseline of only r = 0.13 ([JevAct](https://arxiv.org/html/2610.38620)) [Inference; not independent]. No independent multi-generation test of a policy layer exists.

### Our results fit the direction but do not prove it

| Result [Team] | Outside evidence | Caution |
|---|---|---|
| Full control, small open model: +18.9 on 35 new tasks (24 better, 6 worse, p = 0.001), rules broken 34 vs 37. +8.8 on a second set of 31 (p = 0.115, could be chance) | Agrees: SkillsBench Haiku 4.5 +16.7. Threat: small models improve within months | Compare with a newer small open model alone. If it matches, the gain is temporary |
| Full control, strong model (Gemini 3.8): −5.8 (8 better, 13 worse, p about 0.38, could be chance), 24 vs 1 rules broken | Agrees: LlamaFirewall utility loss. Disagrees: SkillsBench Opus 4.6 +13.9. We found no published case with a rise of this size in rule breaks | One model, two trials. Repeat with a second vendor and find the cause |
| Check before each action, strong model: +25 on 3 tuned tasks, +19 over all rounds | Agrees: Anthropic kept an evaluator; OpenAI hindsight test. Disagrees: over-blocking in SteerBench-Work | Tuned on these 3 tasks, so no claim for new tasks. Most of the gain is the check, not the graph (109 to 133 of 153 over raw text) |
| Rule engine matched the rule file on 372 of 372 decisions | Agrees: NCSC prefers fixed limits | Tests the engine only, not whether rules are right or whether the agent can go around them |

Team details are in `docs/analysis/2026-11-04-manager-review-notes.md` and `benchmarks/policy_eval/changes.md`. Team files date the +18.9, −5.8 and +25 runs to 2026-11-03 and 2026-11-04, after the 2026-11-01 fix for the bug in which every reminder acted as a block.

### Where a system like ours stands

No vendor product was tested; this reading comes from documents [Inference]. **Overlap is high** on allow or deny, order rules, LLM judges, identity and inventory, so we should use these and not rebuild them. **Possible value, none proven:**

- Long written policy to an enforceable rule set with a coverage report. Products take short rules, and Automated Reasoning only checks answers.
- Business facts a gateway cannot see, such as whether the user confirmed, because the harness has the conversation and tool results. MCP 2026-07-28 removed protocol sessions, so order rules need a session from outside MCP.
- Required steps that never happened. Gateways stop bad calls but do not notice these.
- Checks inside code execution. Gateways see only calls that leave the process, and CUGA code blocks can batch several calls.
- Small open models, which no vendor we read targets. Haiku 5.5 is already cheaper at list price than gpt-oss-120b on Bedrock ([OpenRouter](https://openrouter.ai/openai/gpt-oss-120b)), although the lowest listed provider is cheaper, so cost alone does not support this.
- Portability across clouds, and published measurement on policy benchmarks, where we found little from vendors.

**Risks:** AWS added history rules about five months after GA. Microsoft's Agent Governance Toolkit and CPEX are close open alternatives. We found no evidence that external controls catch more than vendor-built ones. IBM's Agentic Control Plane post does not mention ContextForge, CPEX or ToolGuard, so IBM's own pieces are not publicly linked.

## Source limits, one conflict of interest and corrections to earlier notes

**How this report was made.** It was written from five research notes dated 2026-11-05. We did not re-open sources, except ODCV-Bench v5 and team files. Many documents labelled [Primary] were read through a fetch tool that passes text through a small model, so check exact wording before any formal quote. This is not legal advice.

**Conflict of interest.** JevAct (arXiv 2610.38620) lists Sami Marreed as an author, so it is not independent evidence. Its Telecom gain disappears with a gpt-oss-120b user simulator (−1.8, CI −7.9 to +4.4), and its baseline looks low (Opus 4.6 pass^3 39.5 against 81.4 for Opus 4.5 on Sierra's board). Treat it as a signal, not a measurement.

**Sources not read directly**

- **EU and legal:** Regulation (EU) 2026/1744 (EUR-Lex page returned empty), so "no change to the articles" means none reported. Also both sets of Commission guidelines, all court decisions, the FCA Mills Review and the ISO/IEC 42001 text.
- **Security guidance:** the Five Eyes PDF and ASD harness advisory (could not be opened), and the OWASP list (secondary sites only).
- **Lab documents:** the Mythos, Opus 5 and Opus 5.5 system cards (figures via press and Zvi). The Fable 5 card only via a third-party mirror, first 100,000 of about 629,000 characters. The OpenAI monitoring and gpt-oss-safeguard posts (HTTP 403, excerpts only). The GPT-6 Astra card was not found. The deliberative alignment paper was read as abstract only.
- **Partly read:** METR's Frontier Risk Report (first 100,000 of 493,000 characters) and incident report (first 100,000 of 238,000).
- **Market:** Gartner, Forrester and The Information only through blogs or excerpts. SteerBench-Work only through a summary.
- **Data:** Artificial Analysis per-model values come from chart data on its pages (58 to 60 models, not a random sample), so correlations are descriptive only. Row-level HANDBOOK.md dates and metric are unknown. Surge's blog still says no frontier model clears 25%, which conflicts with its own paper and board.

**Conflicts between research notes, resolved here**

- ODCV-Bench: one note gave 1.3% to 71.4% as v5. We re-read v5. The range is 0.0% to 62.8%, and 1.3% and 71.4% are other values in that text.
- Rules broken: one note gave 22 vs 1. Change 121 in `benchmarks/policy_eval/changes.md` corrects this to 24 vs 1.

**Corrections to our earlier notes**

| Earlier note | Correction |
|---|---|
| HANDBOOK.md about 20 to 22% strict pass@1 | That is the June figure. July is 36.2; current board 52.3, metric unlabelled |
| AutomationBench-AA 77.5%, Gemini 4 Argon High | Now 77.8, Gemini 4 Carbon High |
| τ³ top 51.3 | That is the AA figure; Sierra's top is 55.2 |
| Golden retrieval 25.5% to about 40% | Different models. Same model (Opus 4.5): 24.74 to 39.69, old grader |
| STAGE +55.0 and +65.7 | v3: Pass^3 +7.5 to +66.0 over 18 pairs; Telecom up to +60.0 |
| TRACE 32.9% to 37.8% | v2 shows 32.9% to 48.2%; 37.8% not found as TRACE's result |
| Jev-Guard review time 4.80 s to 1.33 s as a positive | Same run cut completion 89.06% to 79.69%; unguarded baseline also had zero violations |
| No compile-based method reports τ² or τ³ results | Outdated for τ² (τ³ not checked) |
| ToolGuard 0.450 to 0.685 | Only 22 of 50 tasks, selected for a policy-violating request; Retail excluded |
| Progent 0% on AgentDojo | v3 abstract gives no number; a reproduction cites 39.9% to 1.0% |
| AutoCedar 221/221 | Own benchmark, with human approval of atoms |
| Automated Reasoning 99.2% / 15.6% | Confirmed. Missing comparison: LLM-as-judge 98.3% / 29.0% |
| AgentCore Policy in Preview, current request only | GA 2026-03-03; Dogwood adds session history rules |
| Automated Reasoning as a logical verdict | Detects only, does not block; LLMs translate text at run time |
| Parlant "when X, then Y" guidelines | v4 docs: a policy has no separate condition field. Check before repeating either form |
| Claude Agent SDK `PreToolUse` can allow | A hook `allow` does not override deny or ask rules |
| Gravitee GAPL grouped as Cedar-like | Official docs confirm only an MCP ACL policy |
| LLM judge family | Add Google Semantic Governance, a hosted LLM judge at the gateway |

Confirmed without change: FORGE translation range, PolicyGuide 0.42 to 0.62, ManyIH about 40%, PVST numbers, AgentFlow renamed Agenra. Earlier notes: `docs/analysis/2026-10-20-policy-benchmarks.md`, `docs/analysis/2026-10-20-agent-policy-enforcement-sota.md`, `docs/analysis/2026-11-04-graph-and-rule-testing-research.md`.

## Conclusion: what the team should do and what to watch

The question for the manager is no longer whether a policy system becomes obsolete. It is which part, for which model and for which risk. Enforcement, evidence and required-step checks have a long future. Guidance has a short one on strong models. Our product risk comes more from vendors than from models [Inference].

### Implications for the team

1. **Build on vendor and IBM enforcement, not against it.** Compile to Cedar, Dogwood or CPEX. Use identity from the provider. Export evidence to watsonx.governance. Connect our work with ContextForge, CPEX and ToolGuard.
2. **Set control by measured agent strength, with hard rules at every level.** Use full control only where it measurably helps, now the small model. For strong models, use hard rules, narrow checks and end checks, and no step loops. Only checks with almost no false blocks should block.
3. **Run five tests before making new claims.**
   - Newest small open model alone against old small model plus system, on held-out tasks. This is the most direct threat to +18.9.
   - Repeat the −5.8 and 24 vs 1 result on a second strong-model vendor, and find the cause.
   - Run the check before each action on unseen handbook tasks.
   - Remove one component per model release, on frozen held-out tasks and at least two vendors. Drop it if the upper confidence limit of its gain stays below about 2 points for two generations (our proposed threshold).
   - Compare with vendor controls (auto mode, AgentCore Policy, Semantic Governance) on the same scenarios.
4. **Test the check design directly.** Let a model answer narrow questions and let code decide. Test gates with and without the agent's reasoning, and measure whether denials cause the agent to look for another route.
5. **Treat evidence as a product requirement.** Keep a versioned rule, a decision log per action, a coverage report linked to the source text, a log-only mode before enforcement, and a named owner. Extend the 372 of 372 test to rule correctness and bypass attempts, and enforce below the agent where possible.
6. **Use careful wording with the manager.**
   - Proven: +18.9 on the small model only.
   - Could be chance: +8.8 and −5.8.
   - Not shown on new tasks: +25 and +19.
   - Engine only: 372 of 372.
   - Do not say the law requires controls outside the model. Say the law requires logs, limits, an owner and a stop function, which a model cannot supply for itself.

### Signals to watch

Numeric thresholds are our proposals. No standard exists.

| Signal | Where to look | What it would mean |
|---|---|---|
| New small open model alone equals old small model plus full control, on two task sets | Our test, each release | The gain was temporary; reduce full control |
| Violations per task keep falling | AutomationBench-AA, one snapshot, record the date | Less advice needed; not a reason to remove hard rules |
| pass^4 / pass^1 above about 0.9 on tasks like the customer's | Sierra τ³ (last standard row 2026-08-04); τ²-bench v2.0 | Step loops and end checks can shrink |
| Surge labels its metric and publishes prohibited-behaviour rates (232 criteria) | HANDBOOK.md board | Best public test of rule following becomes usable |
| Trained agents follow an unseen policy as well as a trained one | New papers | Less need to compile per company |
| Reasoning stops being readable, or an adaptive attack breaks a by-design defense at scale | METR, lab system cards, new papers | Move decisions to action checks; review security design |
| Vendors accept long documents or check required steps; Semantic Governance reaches GA | Release notes | Our feature advantage shrinks; run the vendor comparison |
| A regulator or auditor accepts less oversight on performance, or vendor attestations without separate logs | US banking request for information; MAS 7 Oct 2027 and 2028; AI Act 2 Dec 2027; prEN 18229-1; NIST agent overlays | Evidence requirements change |
| Public incident rates per million agent actions | Vendor or fleet reports; none today | First real base rate for risk |
