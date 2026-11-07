# Vendor products for AI agent policy enforcement and governance (as of 2026-11-05)

Labels used below. **Docs** = product documentation or release notes. **Vendor claim** = marketing text or a number the vendor measured itself. **Analyst** = Gartner or Forrester, usually read through a blog. **Secondary** = press or a third party. **Status** = GA, Preview, Beta, Announced, or Open source (released code with no GA label). "Decides by" uses four types: code or rules, model, human, or a mix. All quotes from sources are paraphrased except one, so check the linked page before quoting.

## What do these products ship today, and what is only announced?

### Takeaway
Rule-based checks at a gateway and agent identity are GA at AWS, Google and Microsoft. Deterministic flows are GA at Salesforce. Model-based checks of business rules are newer: Google's Semantic Governance is still Preview (2026-06-29), while model-based approvals are shipped for coding agents at Anthropic, OpenAI and Cursor. Much of what ServiceNow and watsonx.governance ship is inventory, risk and evidence, with blocking added later and less clearly documented.

### Cited Findings

#### AWS

| Product | Status and date | What it enforces | Where | Decides by | Source |
|---|---|---|---|---|---|
| Policy in AgentCore (Cedar) | **GA 2026-03-03**, 13 Regions (Preview Dec 2025) | Which tools an agent may call; conditions on user identity and tool input | AgentCore Gateway, outside agent code | **Code.** Cedar rules, deny by default. Plain-English authoring produces Cedar, checks it against the tool schema, and uses automated reasoning to flag rules that are too wide, too narrow or impossible. `LOG_ONLY` before `ENFORCE` | [What's New](https://aws.amazon.com/about-aws/whats-new/2026/03/policy-amazon-bedrock-agentcore-generally-available); [Docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html) |
| Bedrock Guardrails inside Policy | **GA**, announced 2026-06-17, 5 Regions at launch (Secondary; it cites an AWS page with "generally available" in the URL) | Prompt injection, harmful content and sensitive data, on input to each gateway target and output of authorized actions | Gateway | **Mix.** A guardrail emits a score at evaluation time, and a policy rule decides on that score | [Classmethod](https://dev.classmethod.jp/en/articles/20260617-amazon-bedrock-agentcore-policy-guardrails/); [Docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html) |
| Temporal policies in Dogwood | Dogwood **Open source** (Apache 2.0), August 2026, exact day not checked. Docs page has no preview label | Rules over history in a session: approval before an action, at most N calls, running total under a budget | Gateway; the policy engine records events per session ID supplied by the caller | **Code.** Stateful rules, Cedar-compatible. Quotas: 20 temporal policies per engine, 3 operators per policy, 24 hour window. Same account and Region only. A new session resets counts | [Docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal.html); [The New Stack](https://thenewstack.io/aws-dogwood-agent-policies/); [InfoQ](https://infoq.com/news/2026/08/aws-dogwood-agent-policy) |
| Automated Reasoning checks | **GA August 2025**; Sydney added June 2026 | Whether a model's text answer agrees with logic rules extracted from a policy document. Not tool calls | Guardrails APIs, on model output | **Mix.** Formal logic, plus LLMs that extract rules and translate text into logic. Detect mode only: returns findings and does not block. English only, no streaming, no prompt injection protection. `VALID` covers only what the policy variables capture. Source document limit 50,000 characters per document | [Docs](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-automated-reasoning-checks.html); [What's New 2025](https://aws.amazon.com/about-aws/whats-new/2025/08/automated-reasoning-checks-amazon-bedrock-guardrails/); [Sydney 2026](https://aws.amazon.com/about-aws/whats-new/2026/06/amazon-bedrock-guardrails-sydney/) |

- Vendor claim: AWS says up to 99% verification accuracy for Automated Reasoning checks — [AWS blog](https://aws.amazon.com/blogs/aws/minimize-ai-hallucinations-and-deliver-up-to-99-verification-accuracy-with-automated-reasoning-checks-now-available/). A search summary says an AWS engineering post limits that figure to cases where the translation from text to logic is unambiguous; I did not confirm the exact page.
- Sources conflict on temporal policy details: an older docs snapshot in search results showed 25 policies per engine and only a few Regions, while the page I read shows 20 and most Regions. I used the page I read — [Docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal.html).
- Dogwood costs more to run than Cedar because it stores and searches event history (Secondary) — [The New Stack](https://thenewstack.io/aws-dogwood-agent-policies/).

#### Salesforce

| Product | Status and date | What it enforces | Where | Decides by | Source |
|---|---|---|---|---|---|
| Agent Script, Hybrid Reasoning, new Agentforce Builder | Pilot, then public beta planned Nov 2025. **GA** per Salesforce blog 2026-02-20. Creating agents in the legacy builder ended the week of 2026-07-13 (search excerpt; the page blocked direct fetch) | Required steps before and after LLM reasoning, routing, validation, formatting, permissions | In the agent definition. Text file that compiles to Salesforce metadata | **Mix.** Code and rules control the flow; the LLM handles ambiguous judgment. Builders set how much is fixed | [Dev blog Oct 2025](https://developer.salesforce.com/blogs/2025/10/introducing-hybrid-reasoning-with-agent-script); [Salesforce 2026-02-20](https://www.salesforce.com/blog/agentforce-transformed/); [Guide, undated](https://www.salesforce.com/agentforce/resources/reliable-ai-agents-guide/); [Migration post](https://developer.salesforce.com/blogs/2026/08/migrate-legacy-agents-to-the-new-agentforce-builder) |

- Vendor claim: the guide says instructions using words like always, before or never are converted into executable deterministic logic, but it does not explain how — [Salesforce guide](https://www.salesforce.com/agentforce/resources/reliable-ai-agents-guide/).

#### ServiceNow

| Product | Status and date | What it enforces | Where | Decides by | Source |
|---|---|---|---|---|---|
| AI Control Tower, June 2026 release | **GA** (article posted 2026-06-22): automated rules for managed assets, new discovery connectors (Databricks, Snowflake, Hugging Face), publish to Agent 365, compliance packs for California, Colorado and EU AI Acts | Mostly inventory, scope and compliance content. No blocking described for these items | ServiceNow control plane | **Rules and human stewards** | [ServiceNow community](https://www.servicenow.com/community/ai-control-tower-articles/ai-control-tower-what-s-new-in-the-june-2026-release/ta-p/3561445) |
| Q1 2026 enforcement items | **GA** per same article | Unapproved MCP servers hidden from builders; approved model providers only. Threat monitoring only detects and flags | Inside ServiceNow build tooling | **Rules** | [ServiceNow community](https://www.servicenow.com/community/ai-control-tower-articles/ai-control-tower-what-s-new-in-the-june-2026-release/ta-p/3561445) |
| Block policies and kill switch | Australia release notes, Patch 6 and 7. **No GA label.** Page date stamp is inconsistent | Block a department from an agent, model or domain; containment of agents on Azure AI Foundry | AI Control Tower, through connected platforms | **Rules** | [Release notes](https://www.servicenow.com/docs/r/australia/release-notes/ai-control-tower-rn.html) |
| Real-time shutdown of an off-script agent | **Announced** 2026-05-05 as a Vendor claim; enhancements expected GA August 2026, GA not confirmed | Shut down an agent that exceeds its permissions | AI Control Tower | Not explained | [Press release](https://investor.servicenow.com/news/news-details/2026/ServiceNow-expands-AI-Control-Tower-to-discover-observe-govern-secure-and-measure-AI-deployed-across-any-system-in-the-enterprise/default.aspx) |
| AI Gateway in AI Control Tower | Release notes say from the **September 2026** release. A LinkedIn post says GA on 10 September (weak source). Early availability items March 2026 | Which MCP connections are allowed, how they authenticate, what data flows | Proxy between agents and MCP servers | **Rules** | [Release notes](https://www.servicenow.com/docs/r/australia/release-notes/ai-control-tower-rn.html); [March post](https://www.servicenow.com/community/now-assist-articles/ai-gateway-what-s-new-in-the-march-2026-release/ta-p/3501670) |
| AI Control Tower and Agent 365 integration | **Preview** 2026-05-05. Agent 365 enforcement described as future work in the June article | Shared registry | Between both products | Not explained | [Press release](https://newsroom.servicenow.com/press-releases/details/2026/ServiceNow-expands-AI-agent-governance-through-deeper-integration-with-Microsoft/default.aspx) |
| Intelligent Approvals | **GA** May 2026 per press release | Handles routine approval requests automatically | ServiceNow workflows | **Model** implied; logic not documented in the page read (Vendor claim) | [Press release](https://investor.servicenow.com/news/news-details/2026/ServiceNow-expands-AI-Control-Tower-to-discover-observe-govern-secure-and-measure-AI-deployed-across-any-system-in-the-enterprise/default.aspx) |
| AI Passport | **Announced**, tied to Q4 2026 (Analyst blog only) | Credentials for agents | Not checked | Not checked | [Futurum](https://futurumgroup.com/?p=96805) |

#### Microsoft

| Product | Status and date | What it enforces | Where | Decides by | Source |
|---|---|---|---|---|---|
| Agent 365 | **GA 2026-05-01**, USD 15 per user per month or in M365 E7 | Registry, oversight, network limits for Copilot Studio and endpoint agents, admin approval and blocking of MCP servers and individual tools | Microsoft 365 admin center, Entra, Intune, Defender, Purview | **Rules and human admin**, plus Defender detection | [Security blog](https://www.microsoft.com/en-us/security/blog/2026/05/01/microsoft-agent-365-now-generally-available-expands-capabilities-and-integrations/); [Tools doc 2026-10-08](https://learn.microsoft.com/en-us/microsoft-agent-365/tooling-servers-overview) |
| Registry sync with AWS Bedrock and Google Cloud | **Preview** at 2026-05-01; start and stop actions announced as coming | Inventory across clouds | Agent 365 registry | Not a decision control | [Security blog](https://www.microsoft.com/en-us/security/blog/2026/05/01/microsoft-agent-365-now-generally-available-expands-capabilities-and-integrations/) |
| Entra Agent ID | **GA** (docs dated 2026-05-01, updated 2026-08-13). Creation wizard is Preview | Agent identity, sponsor lifecycle, access packages, Conditional Access templates for autonomous and on-behalf-of agents, block for high-risk agents | Entra sign-in and token issue | **Rules**, plus a risk signal | [Docs](https://learn.microsoft.com/en-us/entra/agent-id/whats-new-agent-id) |
| Defender on-device runtime protection (local agents such as Claude Code, Codex CLI, Copilot CLI, OpenClaw) | **Preview** per blog dated 2026-07-08 | Audit or block malicious instructions from prompt injection; with Purview, audit or block prompts and tool calls | Endpoint | **Detection, logic not published.** Default audits per Secondary coverage; custom rules can block | [Agent 365 June update](https://techcommunity.microsoft.com/blog/agent-365-blog/whats-new-in-agent-365-%E2%80%93-june-2026/4535107); [Windows Forum](https://windowsforum.com/windows-news.4/microsoft-defender-for-endpoint-previews-ai-agent-runtime-blocking.440835/?amp=1) |
| Defender for Agent 365 | Docs dated 2026-07-30 describe blocking of unsafe actions with no preview label. A search summary says GA for registered tool servers, but I could not open that page | Unsafe tool actions and data exposure | Runtime | **Detection, logic not published** | [Docs](https://learn.microsoft.com/microsoft-agent-365/guidance/defender-agent-365) |
| Copilot Studio external threat detection | **Preview** on the page read 2026-11-05 | A webhook can block a tool call before it runs. Generative orchestration agents only | Copilot Studio orchestrator | **External code or model.** One second to answer; on timeout the default is to allow (fail open) | [Docs](https://learn.microsoft.com/en-us/microsoft-copilot-studio/external-security-provider); [Copilot blog](https://www.microsoft.com/en-us/copilot/blog/copilot-studio/strengthen-agent-security-with-near-real-time-protection-in-microsoft-copilot-studio/) |
| Purview | Data security for Agent 365 **GA** May 2026. Runtime DLP for agent prompts in Foundry **Preview** | Data loss rules on prompts | Purview service | **Purview policies**; detection logic not read | [What's new](https://learn.microsoft.com/en-us/purview/whats-new); [Purview blog](https://techcommunity.microsoft.com/blog/microsoft-security-blog/microsoft-purview-securing-data-and-enabling-apps-and-agents-across-your-ai-stac/4503806) |
| Agent Governance Toolkit | **Open source** (MIT), 2026-04-02. One directory calls it public preview | Each action before it runs; kill switch; signed plugins; identity and trust score | Library inside the agent runtime; works with other frameworks | **Code.** YAML, Rego or Cedar. Vendor claim: under 0.1 ms at p99 | [Microsoft OSS blog](https://opensource.microsoft.com/blog/2026/04/02/introducing-the-agent-governance-toolkit/) |

#### Google

| Product | Status and date | What it enforces | Where | Decides by | Source |
|---|---|---|---|---|---|
| Agent Gateway | **GA 2026-06-18** | Connections among users, agents, tools. Hands decisions to IAM, Semantic Governance and Model Armor | Network layer; Agent Runtime and Gemini Enterprise route through it | **Delegates** | [Release notes](https://docs.cloud.google.com/gemini-enterprise-agent-platform/release-notes); [Overview](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/agent-gateway-overview) |
| IAM Unified Access Policies for agents | **GA 2026-08-31** | Access to MCP servers, agents, endpoints | Gateway with IAP | **Code.** CEL conditions, dry run | [Release notes](https://docs.cloud.google.com/gemini-enterprise-agent-platform/release-notes) |
| Model Armor for Agent Gateway | **GA 2026-06-24** | Content rules on prompts and responses | Gateway | **Content filters**; type of logic not stated in the release notes | [Release notes](https://docs.cloud.google.com/gemini-enterprise-agent-platform/release-notes) |
| Semantic Governance policies | **Preview 2026-06-29.** Updates through 2026-10-26: Anthropic, OpenAI, Mistral, Llama and vLLM tool calls | Each proposed tool call against user intent and plain-English business constraints (up to 5,000 characters) | Gateway, through an authorization extension | **Model.** An LLM judge returns ALLOW or DENY with a rationale. `DRY_RUN` available. Google warns verdicts can be wrong. Streamed responses may not be blocked | [Overview](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/semantic-governance-overview); [Best practices](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/best-practices); [Configure](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/configure-semantic-governance) |
| Agent Identity | **GA** for Agent Runtime, **Preview** for the wider platform (2026-05-07). Agent Identity API **Preview** 2026-06-18 | Agent as its own principal | IAM | **Rules** | [IAM blog](https://cloud.google.com/blog/products/identity-security/whats-new-in-iam-security-governance-and-runtime-defense); [Release notes](https://docs.cloud.google.com/gemini-enterprise-agent-platform/release-notes) |
| ADK callbacks and plugins | Shipped library; docs undated | Tool and model input and output. Plugins include Gemini-as-a-Judge, Model Armor and PII redaction | Inside the agent process | **Code or model**, developer chooses | [ADK docs](https://adk.dev/safety/) |

#### OpenAI

| Product | Status and date | What it enforces | Where | Decides by | Source |
|---|---|---|---|---|---|
| Agents SDK guardrails and approvals | Shipped library, docs undated | Input, output, and function-tool calls. Hosted tools, built-in execution tools and handoffs are outside tool guardrails. Approval with `needs_approval` and durable paused state | Inside the agent process | **Code, model or human**, developer chooses | [Guardrails](https://openai.github.io/openai-agents-python/guardrails/); [Human in the loop](https://openai.github.io/openai-agents-python/human_in_the_loop/) |
| AgentKit Agent Builder | Shutdown **2026-11-30**, notice 2026-06-03 (Secondary and a search excerpt; OpenAI's page blocked direct fetch). Developers directed to Agents SDK or ChatGPT Workspace Agents | Its guardrail layer goes with it | Hosted builder | Not checked | [OpenAI post](https://openai.com/blog/introducing-agentkit); [MintMCP](https://www.mintmcp.com/blog/openai-agent-builder) |
| gpt-oss-safeguard (20B, 120B) | **Research preview**, open weights, 2025-10-29 | A developer's policy, applied to messages, completions and chats. A classifier, not an enforcement point | Wherever the developer calls it | **Model.** Policy text supplied at inference. OpenAI says a classifier trained on many labels can still be better, and that it is slow and costly at scale | [Technical report](https://cdn.openai.com/pdf/08b7dee4-8bc6-4955-a219-7793fb69090c/Technical_report__Research_Preview_of_gpt_oss_safeguard.pdf); [Help Net Security](https://www.helpnetsecurity.com/2025/10/29/openai-gpt-oss-safeguard-safety-models/) |
| Codex Auto-review | **Shipped**, reported 2026-04-30 | Actions that try to leave the sandbox | Sandbox boundary | **Model replaces human approval.** Sandbox and organization rules stay in force. Not used in `never` or `--yolo` modes | [Alignment blog](https://alignment.openai.com/auto-review); [Docs](https://developers.openai.com/codex/auto-review) |
| Frontier | **Announced**; availability not checked. Secondary coverage says each agent gets its own identity, permissions and guardrails | Agent permissions | Enterprise platform | Not documented in what I read | [The Decoder](https://the-decoder.com/openais-frontier-gives-ai-agents-employee-like-identities-shared-context-and-enterprise-permissions/) |

#### Anthropic

| Product | Status and date | What it enforces | Where | Decides by | Source |
|---|---|---|---|---|---|
| Claude Agent SDK permission flow | Shipped; docs show versions, not dates | Tool calls, in fixed order: hooks, deny rules, ask rules, permission mode, allow rules, `canUseTool` callback. A hook `allow` does not override deny or ask rules | Inside the agent process | **Code, rules, human or model**, by mode | [Docs](https://code.claude.com/docs/en/agent-sdk/permissions) |
| Claude Code auto mode | Research preview 2026-03. GA 2026-07-10 per a search summary only. Default on Pro, Max and Team from **2026-08-14**. Current docs: default for interactive sessions on every plan from v2.1.283; `claude -p` and Agent SDK runs start in Manual; HIPAA configuration default is Manual | Actions outside allow rules and the project directory | Agent harness | **Mix.** Rules first, then a classifier model (default Claude Sonnet 5) that does not see tool results. Pauses after 3 consecutive or 20 total blocks. Deny rules apply in every mode | [Engineering post 2026-03-25](https://www.anthropic.com/engineering/claude-code-auto-mode); [Blog 2026-08-07](https://claude.com/blog/auto-mode-default-in-claude-code); [Docs](https://code.claude.com/docs/en/permission-modes) |
| Enterprise controls | Shipped; docs undated | Admin can disable auto or bypass modes through managed settings, and can set connector tools to `ask` for the organization | Managed settings, connector admin | **Rules and human** | [Permission modes](https://code.claude.com/docs/en/permission-modes); [SDK permissions](https://code.claude.com/docs/en/agent-sdk/permissions) |

- Sources conflict: the 2026-08-07 post says Claude Enterprise and cloud platforms stay opt-in for now, with a default planned within a month — [Blog](https://claude.com/blog/auto-mode-default-in-claude-code). The current docs show auto as default on every plan and provider — [Docs](https://code.claude.com/docs/en/permission-modes). The docs are later, so I treat the change as made.

#### IBM

| Product | Status and date | What it enforces | Where | Decides by | Source |
|---|---|---|---|---|---|
| watsonx Orchestrate Agentic Control Plane | Launched June 2026; available on AWS and IBM Cloud per post dated 2026-07-02. No GA label | Policy rules at runtime; content guardrails block outputs; view of which agents reach what | Orchestrate | **Rules and guardrails**; logic not described. Post does not mention ContextForge, CPEX or ToolGuard | [IBM post](https://www.ibm.com/new/announcements/introducing-the-agentic-control-plane) |
| watsonx.governance | Next generation **previewed** at Think 2026. Enforcement Tracking August 2026 (search excerpt): scheduled evaluation of metrics against thresholds. Discovery updates to October 2026 | Evidence, risk mapping and discovery. Not inline blocking | Governance console | **Metrics and human** | [Think 2026](https://www.ibm.com/think/perspectives/ai-governance-to-assurance-what-we-shared-think-2026); [Enforcement Tracking](https://www.ibm.com/new/announcements/from-governance-policies-to-governance-proof-with-enforcement-tracking-for-watsonx-orchestrate); [Discovery](https://www.ibm.com/new/announcements/expanding-ai-asset-discovery-for-broader-visibility) |
| ToolGuard in Langflow Policies | **Beta** since Langflow 1.9 (2026-04-13). ToolGuard repo Apache 2.0, last release v.0.2.21 on 2026-06-30 | Business rules on each guarded tool call | Wraps tools in the flow | **Code at run time** (generated Python you can review), **model at build time** | [Docs](https://docs.langflow.org/policies); [Blog 2026-05-20](https://langflow.org/blog/langflow-policies-guarded-tools); [Langflow 1.9](https://langflow.org/blog/langflow-1-9); [Repo](https://github.com/AgentToolkit/toolguard) |
| ContextForge | **Open source**, v1.1.0 on 2026-10-20 with MCP 2026-07-28 negotiation on by default | RBAC, per-user rate limits, Origin and Host checks; 40+ plugins; Cedar plugin in repo | MCP, A2A and REST gateway | **Code**, plugins can call other engines | [Release](https://github.com/IBM/mcp-context-forge/releases/tag/v1.1.0); [README](https://github.com/IBM/mcp-context-forge); [Cedar plugin](https://github.com/IBM/mcp-context-forge/tree/main/plugins/external/cedar) |
| CPEX | **Open source**, v0.3.1 on 2026-10-16, no maturity label. API and hook names changed from 0.2 | Per-capability pipeline: authorization, delegation, redaction, information flow, audit, before and after each call | Between agent and every capability | **Code.** Calls RBAC, ABAC, Cedar, OPA or AuthZEN for allow or deny | [Docs](https://contextforge-org.github.io/cpex/); [Releases](https://github.com/contextforge-org/cpex/releases); [Migration](https://github.com/IBM/mcp-context-forge/blob/main/docs/docs/using/plugins/migration-to-cpex.md) |

#### Sierra, Decagon, Parlant

| Product | Status and date | What it enforces | Where | Decides by | Source |
|---|---|---|---|---|---|
| Sierra | Vendor blog 2026-08-13; no public feature status | Input screening, reply review, tool access gated on authentication, sensitive data scan | Inside the hosted agent | **Mix.** Separate models can block, rewrite or nudge. Non-model checks hold absolute rules | [Sierra blog](https://sierra.ai/blog/defense-in-depth-in-the-age-of-agents) |
| Decagon Agent Operating Procedures | Vendor posts 2025-04-08 and 2025-07-29; no public docs found | Business logic in natural language; key validation for refunds and identity checks in code; supervisor model reviews replies; bad-actor model; after-the-call review | Inside the hosted agent | **Mix** (Vendor claim). The July 2025 post does not say which layers are code | [Why AOP](https://decagon.ai/blog/why-we-built-aop); [Guardrails](https://decagon.ai/resources/designing-layered-guardrails-for-reliable-ai-agents); [SOPs to AOPs](https://decagon.ai/blog/from-sops-to-agent-operating-procedures) |
| Parlant | **Open source** (Apache 2.0), v4.0.2 on 2026-11-04 | Plain-language policies selected per turn and shown to the agent; `weight` sets how firm; tools attached to a policy | Inside the agent server | **Model.** Parlant judges applicability from the policy text, and signals train a per-agent classifier. The policy page describes no separate gate on tools | [Policies doc](https://www.parlant.io/docs/customizing-behavior/policies); [Release](https://github.com/emcie-co/parlant/releases/tag/v4.0.2) |

#### Corrections to our 2026-10-20 notes

- AgentCore Policy is no longer Preview. It went GA 2026-03-03 — [What's New](https://aws.amazon.com/about-aws/whats-new/2026/03/policy-amazon-bedrock-agentcore-generally-available).
- AgentCore Policy is no longer limited to rules on the current request. Dogwood adds history rules over a session, and provider scores from Guardrails — [Docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html). This overlaps the order rules we listed under AgMentor and Invariant.
- Automated Reasoning checks: add that they only detect and do not block, and that LLMs translate text into logic at run time, so the "logical verdict" depends on that translation — [Docs](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-automated-reasoning-checks.html).
- Parlant: our notes describe "when X, then Y" guidelines. The v4 docs say a policy has no separate condition field for its applicability; only observations have one — [Policies doc](https://www.parlant.io/docs/customizing-behavior/policies). The docs do not state a rename, so check before repeating either form.
- Claude Agent SDK hooks: our notes say `PreToolUse` can allow, deny or change a call. Add that a hook `allow` does not override deny or ask rules — [Docs](https://code.claude.com/docs/en/agent-sdk/permissions).
- Gateways: our notes group Gravitee GAPL under Cedar-like. Official Gravitee docs I could confirm show an MCP ACL policy; GAPL details come only from low-quality Gravitee pages — [MCP ACL](https://documentation.gravitee.io/apim/4.10/create-and-configure-apis/apply-policies/policy-reference/ai-mcp-acl); [GAPL page](https://gravitee.io/corpus/gen-1152/enterprise-control/gapl-based-authorization-controls.html).
- New family member for section E and the "online raw text" row: Google Semantic Governance, a hosted LLM judge at the gateway — [Overview](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/semantic-governance-overview).

### Inferences
- There are three product layers. Control planes (Agent 365, AI Control Tower, watsonx.governance, Agentic Control Plane) mainly handle inventory, identity and evidence. Gateways (AgentCore, Agent Gateway, ContextForge, ToolHive) decide on single calls. Agent frameworks (Agent Script, Claude SDK, OpenAI SDK, ADK, Parlant) control behavior inside the run.
- Few products read a long written policy and enforce it. Automated Reasoning reads a document but only checks answers. AgentCore authoring works from plain-English rule descriptions. Google's judge takes short constraints.

### Gaps
- Exact GA state of ServiceNow's August and September 2026 items: release notes carry no clear label, and one page has inconsistent dates.
- Whether Defender tool server blocking is GA: the supporting page was blocked and Microsoft Learn pages read do not settle it.
- Auto mode GA date of 2026-07-10 is from a search summary; Anthropic pages I read do not state it.
- OpenAI pages at openai.com and some Salesforce developer pages blocked direct fetch, so those facts rest on search excerpts or secondary coverage.
- Sierra Journeys and Decagon reference docs: I found no primary technical docs.

## MCP authorization and gateways: what does the spec require, and what do gateways enforce?

### Takeaway
The current spec (2026-07-28) makes authorization optional, and when used over HTTP it should follow an OAuth 2.1 based profile. It decides who may reach a server with which token and scopes. It does not decide whether a specific tool call should run, and gateways sell that second decision.

### Cited Findings

#### What the spec says

- Authorization is OPTIONAL. HTTP transports SHOULD conform; STDIO SHOULD NOT and takes credentials from the environment — [MCP 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization).
- MCP servers act as OAuth 2.1 resource servers and MUST implement Protected Resource Metadata (RFC 9728). Clients MUST use it to discover the authorization server — [MCP 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization).
- Clients MUST send the `resource` parameter (RFC 8707). Servers MUST validate that a token was issued for them. Servers MUST NOT accept or pass on other tokens — [MCP 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization).
- Client ID Metadata Documents are SHOULD. Dynamic Client Registration is deprecated and kept for compatibility — [Changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog).
- New in this version: issuer checks (RFC 9207), and credentials bound to the authorization server that issued them — [Changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog).
- Scopes: a server SHOULD reply 403 with `insufficient_scope` and the needed scopes; clients acting for a user SHOULD try step-up authorization — [MCP 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization).
- Protocol sessions, `Mcp-Session-Id` and the initialize handshake are removed. Streamable HTTP POST requests must carry `Mcp-Method` and `Mcp-Name` headers — [Changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog).
- Enterprise-Managed Authorization is an opt-in extension with a stable 2026-07-28 version. The company identity provider decides which MCP servers an employee may reach, using ID-JAG tokens — [MCP extension](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization).
- ID-JAG support table: Okta, Ping, Descope, Athenz, ThunderID and Janssen issue and accept; Auth0, Scalekit and WorkOS accept in early access; Keycloak accepts as experimental — [MCP extension](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization).
- Permit.io, a vendor, says OAuth alone cannot decide whether one tool call should run, and places a policy decision point behind the gateway (Vendor claim, 2026-07-29) — [Permit.io](https://www.permit.io/blog/mcp-auth-vs-tool-call-authorization-2026-07-28).

#### What gateways enforce

| Gateway | Status and date | What it checks | Decides by | Source |
|---|---|---|---|---|
| AgentCore Gateway + Policy | GA 2026-03-03 | Tool, principal, input; session history with Dogwood | Cedar or Dogwood rules | [Docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html) |
| Google Agent Gateway | GA 2026-06-18; Semantic Governance Preview | MCP and agent connections; proposed tool calls | IAM and CEL; LLM judge | [Release notes](https://docs.cloud.google.com/gemini-enterprise-agent-platform/release-notes) |
| ContextForge | Open source, v1.1.0 2026-10-20 | RBAC, plugin hooks; Cedar plugin available | Code | [Release](https://github.com/IBM/mcp-context-forge/releases/tag/v1.1.0) |
| CPEX | Open source, v0.3.1 2026-10-16 | Pipeline per capability, before and after each call; information flow labels | Delegates allow or deny to Cedar, OPA, RBAC or AuthZEN | [Docs](https://contextforge-org.github.io/cpex/) |
| ToolHive | Open source, v0.62.0 2026-11-04 | `call_tool`, `get_prompt`, `read_resource`; JWT claims, tool arguments, tool annotations; list responses filtered | Cedar, deny by default; errors count as deny | [Docs](https://docs.stacklok.com/toolhive/concepts/cedar-policies); [Repo](https://github.com/stacklok/toolhive) |
| Gravitee APIM 4.10 | Release date not checked. Access Management MCP Server support is tech preview | MCP ACL policy on tools, resources, prompts; deny all if no rules; OAuth 2.0 plans | Rules | [Release notes](https://documentation.gravitee.io/apim/4.10/release-information/release-notes/apim-4.10); [MCP ACL](https://documentation.gravitee.io/apim/4.10/create-and-configure-apis/apply-policies/policy-reference/ai-mcp-acl); [AM changelog](https://documentation.gravitee.io/am/4.10/releases-and-changelog/changelog/am-4.10.x) |
| Permit.io | Vendor reference pattern, 2026-07-29; no detailed product docs read | Principal, tenant, method, tool name, arguments, environment | External policy decision point. Vendor claim: 5.6 ms p99 on RBAC checks | [Permit.io](https://www.permit.io/blog/mcp-auth-vs-tool-call-authorization-2026-07-28) |
| ServiceNow AI Gateway | Release notes say from September 2026 | Allowed MCP connections, authentication, data flow | Rules | [Release notes](https://www.servicenow.com/docs/r/australia/release-notes/ai-control-tower-rn.html) |
| Microsoft Agent 365 Tools and Tools Gateway | Docs 2026-10-08 | Approve or block MCP servers and individual tools | Admin decisions; Defender for runtime | [Docs](https://learn.microsoft.com/en-us/microsoft-agent-365/tooling-servers-overview) |

### Inferences
- The spec's new request headers make gateway rules cheaper, because a gateway can classify a call without parsing the body. Permit.io makes the same point about routing.
- Removing protocol sessions means a gateway cannot group calls using an MCP session ID. AWS requires its own session header for temporal rules. Order rules need a session concept from outside MCP, and the agent harness is a natural place to supply it.
- Gateways agree on deny by default and on rules over principal, tool and arguments. They differ on business meaning, and only Google ships an LLM judge at the gateway. AWS brings model signals in as a score that a rule reads.

### Gaps
- I did not research Kong, Cloudflare, Docker MCP Gateway or Azure API Management.
- I did not find independent performance or security tests of any gateway.
- The MCP blog post for the release returned 404 at the URL I tried; dates come from the spec path and from [Anthropic's post](https://claude.com/blog/bringing-mcp-2026-07-28-to-claude).

## How are agents given their own identity and permissions?

### Takeaway
The market has moved from shared service accounts to the agent as its own identity with a human sponsor, using existing standards (OAuth, OIDC, SPIFFE). Products are GA at Microsoft, Google (partly) and Okta. Standards are still drafts, and policy itself stays outside the identity standards.

### Cited Findings

#### Standards

| Item | Status and date | What it says | Source |
|---|---|---|---|
| draft-klrc-aiagent-auth-03 | Informational Internet-Draft, 2026-07-06. Authors from Defakto, AWS, Zscaler, Ping, OpenAI, Okta | No new protocol; profiles WIMSE, SPIFFE and OAuth. One identifier per agent, bound credentials, short-lived preferred, static API keys an antipattern. Transaction tokens for downscoping. CIBA for out-of-band human approval. Policy format out of scope | [Draft](https://www.ietf.org/archive/id/draft-klrc-aiagent-auth-03.html) |
| draft-ietf-wimse-aims-00 | Working group name, September 2026 (search excerpt) | Same work under WIMSE | [Datatracker](https://datatracker.ietf.org/doc/html/draft-ietf-wimse-aims) |
| draft-ni-wimse-ai-agent-identity-03 | Individual draft, October 2026 | Bind agent identity to an accountable user or organization | [Draft](https://datatracker.ietf.org/doc/html/draft-ni-wimse-ai-agent-identity-03) |
| ID-JAG | IETF OAuth draft, draft-04 dated 2026-05-21 per WorkOS. Implementations follow different revisions | Identity provider issues a grant that the app exchanges for a token | [MCP extension](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization); [WorkOS](https://workos.com/blog/agent-sso-resource-app-side) |
| NIST NCCoE concept paper | Published February 2026; comment summary dated 2026-09 by URL, 600+ commenters. First use case from DevSecOps | Asks what identity metadata to carry, how long identity should live, how to link to a human | [Concept paper](https://www.nccoe.nist.gov/sites/default/files/2026-02/accelerating-the-adoption-of-software-and-ai-agent-identity-and-authorization-concept-paper.pdf); [NIST news](https://www.nist.gov/news-events/news/2026/09/comments-software-and-agentic-ai-identity-concept-paper); [Summary](https://pages.nist.gov/nccoe-ai-identity/summary-of-comments.html) |

- Analyst (Forrester, 2026-03-20): no mature portable agent identity standard exists, and MCP, A2A, BeeAI and Entra each cover only part of it — [Forrester](https://www.forrester.com/blogs/agent-control-planes-still-need-a-robust-standards-stack/).

#### Products

| Product | Status and date | How the agent gets identity and permissions | Source |
|---|---|---|---|
| Microsoft Entra Agent ID | GA, docs 2026-05-01 | Blueprints and agent identities; owners, sponsors, managers; access packages for on-behalf-of and autonomous use; Conditional Access templates. Works with AWS, GCP and n8n through sidecar or federation | [Docs](https://learn.microsoft.com/en-us/entra/agent-id/whats-new-agent-id) |
| Google Agent Identity | GA for Agent Runtime, Preview for platform, 2026-05-07 | New principal type built on SPIFFE; IAM allow and deny. Auth Manager (Preview) handles user OAuth | [IAM blog](https://cloud.google.com/blog/products/identity-security/whats-new-in-iam-security-governance-and-runtime-defense) |
| Okta Agent SSO | GA; WorkOS and another changelog date it 2026-08-24. Included in core SSO | Cross App Access over ID-JAG. MCP docs list a cap of 250 ID-JAGs per user per resource app per month; more requires Okta for AI Agents | [Okta release](https://okta.com/newsroom/press-releases/okta-brings-first-class-identity-to-ai-agents-with-agent-sso/); [MCP extension](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization); [WorkOS](https://workos.com/blog/cross-app-access-converged-in-eight-days) |
| Okta for AI Agents | GA; 2026-04-28 per a third-party profile; Okta recap June 2026. Separate paid product | Agent lifecycle and token exchange | [Okta recap](https://developer.okta.com/blog/2026/06/09/okta-developer-connect-sf-recap); [Third-party profile](https://guptadeepak.com/agent-security/vendor/okta/) |
| Microsoft Agent Governance Toolkit | Open source, 2026-04-02 | DID-based identity with a trust score from 0 to 1000 | [Microsoft OSS blog](https://opensource.microsoft.com/blog/2026/04/02/introducing-the-agent-governance-toolkit/) |
| ServiceNow with Veza | Veza purchase closed March 2026 per Diginomica; rollout over following months | Access graph, scoped permissions, least privilege | [Diginomica](https://diginomica.com/servicenow-knowledge-2026-ai-control-tower-expands-autonomous-workforce-reaches-every-function-and) |
| OpenAI Frontier | Announced; availability not checked | Agent identity with explicit permissions (Secondary) | [The Decoder](https://the-decoder.com/openais-frontier-gives-ai-agents-employee-like-identities-shared-context-and-enterprise-permissions/) |

- A TrueFoundry doc called Cross App Access Early Access in mid-2026, which conflicts with the later Okta GA release, so I treat it as out of date — [TrueFoundry](https://www.truefoundry.com/docs/agent-platform/agent-governance/scenarios/okta).

### Inferences
- Four patterns repeat: the agent as a principal in the identity provider; separate on-behalf-of and autonomous modes; workload identity through SPIFFE; and short-lived tokens narrowed to one task.
- Identity answers who the agent is and what it can reach. No identity standard or product I read covers business rules such as refund limits. That space stays open for a policy layer.

### Gaps
- I did not check AgentCore Identity status or A2A identity features.
- I found no data on how many deployed agents actually use per-agent identities outside Microsoft's own registry claim.

## Is the market moving to deterministic controls outside the model, to model-based supervisors, or to both?

### Takeaway
Both, in layers. Vendors put fixed code rules around what can be stated exactly, and add a model for intent and meaning. Business-workflow vendors moved towards determinism; coding-agent vendors moved towards model-based approval while keeping a sandbox and hard rules.

### Cited Findings

#### Moves towards deterministic control

| Vendor | Move and date | Stated reason | Label |
|---|---|---|---|
| Salesforce | Agent Script and Hybrid Reasoning, Oct 2025 to Feb 2026 | Models skip steps, ignore rules, invent facts; prompts alone gave inconsistent results; Salesforce's own early deployments did not always behave as intended; visual trees were hard to debug | Vendor text: [Guide](https://www.salesforce.com/agentforce/resources/reliable-ai-agents-guide/), [Blog 2026-02-20](https://www.salesforce.com/blog/agentforce-transformed/), [Blog 2026-04-07](https://www.salesforce.com/blog/agentforce-guide/?bc=OTH) |
| AWS | Cedar at the gateway (GA 2026-03), Dogwood for sequences (Aug 2026) | Agents may misread business rules or act beyond their authority; rules outside code reduce bypass by manipulation; single-call rules miss sequences | Docs: [Policy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html). Secondary: [The New Stack](https://thenewstack.io/aws-dogwood-agent-policies/) |
| Microsoft | Agent Governance Toolkit, 2026-04-02 | Build governance into the execution path, because optional security tends to go unused | Vendor text: [OSS blog](https://opensource.microsoft.com/blog/2026/04/02/introducing-the-agent-governance-toolkit/) |
| Sierra | Deterministic guards next to supervisors, 2026-08-13 | Some rules are absolute and should not depend on model judgment | Vendor text: [Sierra](https://sierra.ai/blog/defense-in-depth-in-the-age-of-agents) |
| Decagon | Code for key validation steps, 2025-04-08. Note: Decagon moved away from decision trees towards natural language, with code only for sensitive steps | Decision trees are brittle and expensive to maintain; refunds and identity checks need control | Vendor text: [Why AOP](https://decagon.ai/blog/why-we-built-aop) |
| IBM and Langflow | ToolGuard in Langflow, 2026-04 and 2026-05 | A fixed control point at the tool call, rather than prompt text the model might ignore | Vendor text: [Langflow](https://langflow.org/blog/langflow-policies-guarded-tools) |

Salesforce's public comments:

- Salesforce SVP Sanjna Parulekar: "We all had more confidence in LLMs a year ago." (reported December 2025) — [The Decoder, citing The Information](https://the-decoder.com/salesforce-executives-signal-declining-trust-in-large-language-models/). The Information article itself is paywalled.
- A Salesforce spokesperson denied backtracking and said the company is being more deliberate about LLM use — [The Decoder](https://the-decoder.com/salesforce-executives-signal-declining-trust-in-large-language-models/).
- CTO Muralidhar Krishnaprasad reportedly said models start to drop instructions beyond about eight. This is paraphrased by a secondary site and I did not see the original — [Aihola](https://aihola.com/article/salesforce-llm-trust-declined).
- Phil Mui described "drift", where agents lose the main goal when users ask side questions (October blog post, via secondary) — [Aihola](https://aihola.com/article/salesforce-llm-trust-declined).
- Vivint's AI sometimes failed to send satisfaction surveys despite instructions, and deterministic triggers fixed this — [Aihola, citing The Information](https://aihola.com/article/salesforce-llm-trust-declined).
- Salesforce cites a Gartner forecast that companies will cancel 40% of agentic projects by 2027. That is a forecast, not a measurement — [Salesforce guide](https://www.salesforce.com/agentforce/resources/reliable-ai-agents-guide/).
- Aron Kale (titled Agentforce Product Director in the guide, VP of Product Management in the blog) says lack of control keeps workflows at simple FAQ level (Vendor claim) — [Salesforce guide](https://www.salesforce.com/agentforce/resources/reliable-ai-agents-guide/).

#### Moves towards model-based checks

| Vendor | Move and date | Stated reason | Label |
|---|---|---|---|
| Google | Semantic Governance, Preview 2026-06-29 | An agent allowed to use a tool can still misuse it, and static IAM cannot see that. It adds to IAM and does not replace it | Docs: [Overview](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/semantic-governance-overview) |
| AWS | Guardrail scores readable by Policy rules, 2026-06-17 | Add prompt attack and content signals at the gateway | Docs: [Policy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html) |
| Anthropic | Auto mode, 2026-03; default 2026-08 | Users approve almost all prompts anyway (93%), and approvals become routine | Vendor: [Engineering post](https://www.anthropic.com/engineering/claude-code-auto-mode) |
| OpenAI | Codex Auto-review, 2026-04 | Too many prompts push users to Full Access or broad rules, which is worse for security | Vendor: [Alignment blog](https://alignment.openai.com/auto-review) |
| Cursor | Auto-review, 2026-06 | Repeated prompts stop people reading carefully | Vendor: [Cursor](https://cursor.com/blog/auto-review) |
| Sierra, Decagon | Supervisors on replies and input | Subtle cases that rules miss. Sierra adds that supervisors, being models, share some of the weaknesses they watch for | Vendor: [Sierra](https://sierra.ai/blog/defense-in-depth-in-the-age-of-agents); [Decagon](https://decagon.ai/resources/designing-layered-guardrails-for-reliable-ai-agents) |

#### Layering in shipped designs

- Claude Code: allow rules and the project directory check run first, and the model classifier handles the rest. Deny rules apply in every mode — [Docs](https://code.claude.com/docs/en/permission-modes).
- Cursor: allowlist first, sandbox next, classifier for the rest; the classifier runs on a small share of actions — [Cursor](https://cursor.com/blog/auto-review).
- AWS: a Dogwood rule can read a Guardrails score, so a rule makes the final decision — [Docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html).
- Google: IAM for base access, the LLM judge on top; start in dry run — [Best practices](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/best-practices).
- Failure behavior differs. ToolHive treats evaluation errors as deny — [ToolHive](https://docs.stacklok.com/toolhive/concepts/cedar-policies). Copilot Studio by default allows on timeout — [Docs](https://learn.microsoft.com/en-us/microsoft-copilot-studio/external-security-provider).

#### Analysts

- Analyst (Gartner, 2026-02-25): first Market Guide for Guardian Agents; no vendor ranking; six architecture approaches; expects guardian agents as a separate control layer rather than a platform feature. I read this through search excerpts of a Hacker News piece, not the report — [The Hacker News](https://thehackernews.com/2026/03/5-learnings-from-first-ever-gartner.html).
- Arcjet, a vendor, says the guide advises deterministic checks first and a model judge after, and says inline blocking is still limited. Treat as secondhand — [Arcjet](https://arcjet.com/learn/guardian-agents).
- Analyst (Gartner, 2026): first Magic Quadrant for AI Agent Management Platforms; IBM reports being named a Leader and mentions runtime guardrails (IBM post 2026-11-02) — [IBM](https://www.ibm.com/new/announcements/ibm-named-a-leader-in-the-2026-gartner-magic-quadrant-for-ai-agent-management-platforms).
- Analyst (Forrester, 2026-03-20): control plane is becoming a distinct category, but standards underneath are incomplete, and integration across planes has no owner — [Forrester](https://www.forrester.com/blogs/agent-control-planes-still-need-a-robust-standards-stack/).
- Analyst (Forrester): AEGIS treats human approval for irreversible actions as a formal control. It links this to joint Five Eyes guidance from 2026-05-01 (search excerpt) — [Forrester](https://www.forrester.com/blogs/five-eyes-cybersecurity-agencies-careful-agentic-ai-adoption-guidance-operationalized-by-aegis/).

### Inferences
- The split follows the risk and the ability to undo. Coding agents run in a sandbox with version control, so a model approver with some misses is acceptable. Customer and business workflows touch real records and policy rules, so vendors fix the required steps in code.
- AWS (`LOG_ONLY`) and Google (`DRY_RUN`) both ship a mode that records decisions without blocking. Testing a rule on live traffic before it blocks looks like the expected rollout path at these two vendors.
- A combined pattern is emerging where a model produces a signal and a rule decides. AWS ships this. It keeps a clear audit point and is close to our Jev questions plus code design.

### Gaps
- I could not read the Gartner guide, the Forrester reports or The Information directly.
- No vendor publishes how often its rule layer and its model layer each decide in production.

## What do vendors say about stronger models reducing the need for controls?

### Takeaway
I found no vendor that says in plain terms that controls can be relaxed because models are stronger. Vendors justify model-driven approval by saying humans are poor approvers. They keep sandboxes or hard rules, and OpenAI and Anthropic both state that the model approver is not a guarantee.

### Cited Findings

- Model-driven auto-approve exists at least at three vendors: Anthropic auto mode ([Docs](https://code.claude.com/docs/en/permission-modes)), OpenAI Codex Auto-review ([Docs](https://developers.openai.com/codex/auto-review)), Cursor Auto-review ([Cursor](https://cursor.com/blog/auto-review)).
- OpenAI (2026-04-30): in its evaluations, stronger models are better at detecting risk and reading user intent. This is about the reviewer. The same post says agents are not yet trusted with employee-level permissions, does not expect deterministic guarantees from this approach, and says Auto-review may not be the final form — [Alignment blog](https://alignment.openai.com/auto-review).
- OpenAI vendor-measured results: about 200x fewer approval stops; 99.1% of escalated actions auto-approved; recall 90.3% on overeagerness, 99.3% on prompt injection, 96.1% on MonitoringBench Hard — [Alignment blog](https://alignment.openai.com/auto-review).
- Anthropic (2026-03-25) vendor-measured results: users accepted 93% of prompts. Full pipeline false positive rate 0.4%; false negative rate 17% on 52 real overeager actions, and 5.7% on synthetic exfiltration. It says this does not replace careful review on high-stakes infrastructure — [Engineering post](https://www.anthropic.com/engineering/claude-code-auto-mode).
- Anthropic (2026-08-07) vendor-measured study with 1,053 paid testers in a test environment: humans caught a swapped dangerous command 13.6% of the time and auto mode blocked 89%. Among flagged real sessions, serious unintended harm at production severity was 6.3% with manual approval and 2.4% with auto mode. The post says auto mode does not eliminate risk — [Blog](https://claude.com/blog/auto-mode-default-in-claude-code).
- Anthropic (2026-08-07) also reports no successful prompt injections against its newest models in auto mode, and 5.83% against GPT-5.6 Sol in Codex Auto-review. This is a competitor comparison, in Anthropic's own test, and I found no OpenAI response — [Blog](https://claude.com/blog/auto-mode-default-in-claude-code).
- Anthropic docs: auto mode requires recent models and is not supported on older ones on any provider — [Docs](https://code.claude.com/docs/en/permission-modes).
- Anthropic (2026-02-18): models can handle more autonomy than they use in practice (it calls this a deployment overhang). It tells policymakers that mandates to approve each action add friction without clear safety gain, and asks them to focus on whether humans can monitor and intervene. It does not claim better models make oversight unnecessary. Users moved from about 20% full auto-approve under 50 sessions to over 40% near 750 sessions — [Anthropic research](https://www.anthropic.com/research/measuring-agent-autonomy).
- Cursor (2026-06-11) vendor-measured: classifier blocks about 4% of the actions it reviews; about 7% of chats get at least one interruption; no false negative rate published — [Cursor](https://cursor.com/blog/auto-review).
- Opposite direction: Salesforce says trust in LLMs fell — [The Decoder](https://the-decoder.com/salesforce-executives-signal-declining-trust-in-large-language-models/). Sierra keeps non-model checks for absolutes — [Sierra](https://sierra.ai/blog/defense-in-depth-in-the-age-of-agents). Google warns its judge can be wrong — [Overview](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/semantic-governance-overview). Salesforce's April 2026 post makes no claim on model strength — [Blog](https://www.salesforce.com/blog/agentforce-guide/?bc=OTH).
- Secondary: a McKinsey leader expects 2026 autonomy to shrink by design, with hard guardrails in controlled settings — [McKinsey](https://www.mckinsey.com/uk/our-insights/uk-insights/ais-next-act-mckinsey-ai-leaders-on-the-year-ahead).

### Inferences
- These vendor numbers are not comparable. Each vendor uses its own data, attack sets and definition of a dangerous action.
- The model-approver argument mainly compares a model with a tired human, not a model with a rule. No vendor removes deny rules or sandboxes.
- Our internal note from 2026-11-04 says policy methods help weak agents and not Gemini 3.8, and records the principle "the stronger the agent, the less control", with hard code rules at all levels (project memory, not re-run for this task). I found no vendor stating this principle. Vendor designs are consistent with its second half: hard rules stay at all levels. Our internal result would be new evidence in public discussion, if it holds on re-baseline.

### Gaps
- I found no public vendor data showing fewer controls needed as model versions improve, for the same task set.
- My search for explicit vendor statements returned mostly blogs. A statement in a keynote or interview could exist and be missed.

## What adoption numbers or customer evidence exist?

### Takeaway
All numbers are vendor claims, or come from vendors through the press. Most measure platform use and not use of policy controls. I found no independent measurement of policy enforcement adoption.

### Cited Findings

| Vendor | Number | Date | What it measures | Label and source |
|---|---|---|---|---|
| Microsoft | Tens of thousands of companies managing tens of millions of agents in Agent 365 | 2026-04-29 | Registered agents, before GA | Vendor claim, CEO on earnings call. Seen only in a search excerpt of a transcript; the full text is behind a login: [Insider Monkey](https://www.insidermonkey.com/blog/microsoft-corporation-nasdaqmsft-q3-2026-earnings-call-transcript-1750980/) |
| Microsoft | 40 million agents registered within two months of launch | About 2026-09-16 | Same; the article cites no Microsoft source | Secondary, unverified: [Motley Fool on Webull](https://www.webull.com/news/15587179543675904) |
| Salesforce | Agentforce ARR above USD 1.5B, up more than 240%; with Data 360 near USD 3.9B; 3.2B Agentic Work Units in the quarter, 7B to date | Q2 FY27, reported 2026-08-26 | Revenue and usage. CXO Digital Pulse says the metric was broadened to include Slackbot and Headless 360, so periods may not compare; a second article does not mention this | Vendor claim, through press: [CXO Digital Pulse](https://www.cxodigitalpulse.com/?p=61209); [Salesforce Dictionary](https://salesforcedictionary.com/news/salesforce-news-august-27-2026-agentforce-partner-revenue-gap) |
| Salesforce | Over 6,000 paying customers | Reported 2026-08-26 | Paying Agentforce customers. One secondary article only | Vendor claim, through press: [Salesforce Dictionary](https://salesforcedictionary.com/news/salesforce-news-august-27-2026-agentforce-partner-revenue-gap) |
| Salesforce | 18,500 deals, 9,500 paid; ARR USD 540M | Q3 FY26 call, Dec 2025 | Deals, not customers. One source says these include deals at some stage of implementation | Vendor claim, search excerpts: [MarketBeat transcript](https://www.marketbeat.com/earnings/reports/2025-12-3-salesforcecom-inc-stock/) |
| Salesforce | About 29,000 deals since launch | Q4 FY26, one blog | Unverified: same blog gives an ARR that conflicts with other reports for its period | Secondary: [Cyntexa](https://cyntexa.com/blog/agentforce-statistics-and-trends/) |
| Salesforce customers | Wiley 40% more case resolution; Falabella 60% of WhatsApp inquiries resolved; Datasite admin says Script runs every time | 2026-02-20; 2026-04-07 | Outcomes; the Datasite remark is a personal quote, not a measurement | Vendor claim: [Blog Feb](https://www.salesforce.com/blog/agentforce-transformed/); [Blog Apr](https://www.salesforce.com/blog/agentforce-guide/?bc=OTH) |
| ServiceNow | Evaluation Suite in 150+ customers, about 1M AI interactions; HDFC Bank testimonial for AI Control Tower; Rolls-Royce 38,000 tickets deflected and 34% faster resolution | 2026-05-05 | Rolls-Royce is not about governance. No AI Control Tower customer count found | Vendor claim: [Press release](https://investor.servicenow.com/news/news-details/2026/ServiceNow-expands-AI-Control-Tower-to-discover-observe-govern-secure-and-measure-AI-deployed-across-any-system-in-the-enterprise/default.aspx) |
| OpenAI | Majority of Codex Desktop token use inside OpenAI runs in Auto-review | 2026-04-30 | Internal staff use only | Vendor claim: [Alignment blog](https://alignment.openai.com/auto-review) |
| Anthropic | Team and Enterprise auto mode users ship about 25% more PRs | 2026-08-07 | Productivity, opt-in adopters, so selection is possible | Vendor claim: [Blog](https://claude.com/blog/auto-mode-default-in-claude-code) |
| Anthropic | 80% of public API tool calls come from agents with at least one safeguard; 73% with some human in the loop; 0.8% appear irreversible | 2026-02-18 | Authors say human involvement is likely overestimated | Vendor research: [Anthropic](https://www.anthropic.com/research/measuring-agent-autonomy) |
| Okta | Agent SSO placed in a product used by more than 20,000 customers | 2026-08 | Reach of core SSO, not use of Agent SSO | Vendor claim, through WorkOS: [WorkOS](https://workos.com/blog/cross-app-access-converged-in-eight-days) |
| Forrester poll | 47 tech vendors: 79% see a distinct category, 92% have a named owner, 40% report active buying requests | Late Feb 2026 | Supply side, self-reported | Analyst: [Forrester](https://www.forrester.com/blogs/agent-control-planes-still-need-a-robust-standards-stack/) |
| GitHub stars (read 2026-11-05) | Parlant 18,326; ContextForge 4,753; ToolHive 2,325; CPEX 16; ToolGuard 7 | 2026-11-05 | Interest only, not use | GitHub API: [Parlant](https://github.com/emcie-co/parlant), [ContextForge](https://github.com/IBM/mcp-context-forge), [ToolHive](https://github.com/stacklok/toolhive), [CPEX](https://github.com/contextforge-org/cpex), [ToolGuard](https://github.com/AgentToolkit/toolguard) |

### Inferences
- For a manager, the safe statement is that buyers are paying for agent platforms and vendors see demand for control planes. The numbers do not show how many customers run enforcing policies, rather than inventory.

### Gaps
- No vendor reports how many customers have enforcement on, how many calls were blocked, or how many blocks were wrong.
- No adoption numbers found for AgentCore Policy, Semantic Governance, Sierra or Decagon guardrails.
- Microsoft's 40 million figure and later earnings statements were not checked against Microsoft's own transcript.

## Where would a CUGA policy system overlap or add value?

### Takeaway
A CUGA system should not rebuild access control or identity, which are GA at large vendors or available in open source gateways. Its possible value is agent-side: turning long written policies into checked rules and obligations, giving useful feedback so the agent recovers, enforcing inside code execution, and measuring results on policy benchmarks. Vendors publish little measurement on that last point.

### Cited Findings

| Capability | Who ships it | Status | Overlap with CUGA |
|---|---|---|---|
| Allow or deny on tool, identity and arguments | [AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html), [Google](https://docs.cloud.google.com/gemini-enterprise-agent-platform/release-notes), [ToolHive](https://docs.stacklok.com/toolhive/concepts/cedar-policies), [CPEX](https://contextforge-org.github.io/cpex/), [Microsoft AGT](https://opensource.microsoft.com/blog/2026/04/02/introducing-the-agent-governance-toolkit/) | GA and open source | **High.** Same as our code rule layer. Use Cedar, Dogwood or CPEX as a backend |
| Order, count and sum rules | [Dogwood](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal.html) | Open source and in AgentCore, Aug 2026 | **High** for order rules. Dogwood is limited to a session and 24 hours |
| Plain English to rules | [AgentCore authoring](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html), [ToolGuard](https://langflow.org/blog/langflow-policies-guarded-tools) | GA; Beta | **Medium.** These start from rule text. Long-document handling is less clear |
| Policy document to logic | [Automated Reasoning](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-automated-reasoning-checks.html) | GA | **Medium.** Checks answers only and only detects. It reports fidelity scores that link each rule back to the source, which is a useful model for our coverage report |
| LLM judge on tool calls | [Google Semantic Governance](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/semantic-governance-overview), [Agents SDK](https://openai.github.io/openai-agents-python/guardrails/), [ADK](https://adk.dev/safety/) | Preview; shipped | **High** with a model verifier. Google hosts it at the gateway |
| Approval replaced by a model | [Auto mode](https://code.claude.com/docs/en/permission-modes), [Auto-review](https://alignment.openai.com/auto-review), [Cursor](https://cursor.com/blog/auto-review) | Shipped, coding agents | **Medium.** Same pattern as VERIFY, different domain |
| Fixed flows around LLM steps | [Agent Script](https://www.salesforce.com/blog/agentforce-transformed/), [Decagon](https://decagon.ai/blog/why-we-built-aop), [Parlant](https://www.parlant.io/docs/customizing-behavior/policies) | GA in Salesforce's closed platform; vendor text; open source | **Medium.** Overlaps playbooks. Agent Script is tied to Salesforce |
| Identity | [Entra](https://learn.microsoft.com/en-us/entra/agent-id/whats-new-agent-id), [Google](https://cloud.google.com/blog/products/identity-security/whats-new-in-iam-security-governance-and-runtime-defense), [Okta](https://okta.com/newsroom/press-releases/okta-brings-first-class-identity-to-ai-agents-with-agent-sso/) | GA | **None to build.** Consume it |
| Inventory and compliance mapping | [AI Control Tower](https://www.servicenow.com/community/ai-control-tower-articles/ai-control-tower-what-s-new-in-the-june-2026-release/ta-p/3561445), [Agent 365](https://www.microsoft.com/en-us/security/blog/2026/05/01/microsoft-agent-365-now-generally-available-expands-capabilities-and-integrations/), [watsonx.governance](https://www.ibm.com/think/perspectives/ai-governance-to-assurance-what-we-shared-think-2026) | GA | **None to build.** Export evidence to them |

- IBM's own pieces are not linked in public text I read: the Agentic Control Plane post does not mention ContextForge, CPEX or ToolGuard — [IBM post](https://www.ibm.com/new/announcements/introducing-the-agentic-control-plane).
- Auto-review found an acceptable other path in more than half of denials, which shows the value of a denial that explains itself — [Alignment blog](https://alignment.openai.com/auto-review). Google returns a rationale with each denial, and warns it can leak constraint details — [Overview](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/semantic-governance-overview).
- Auto-review does not look at actions inside the sandbox — [Alignment blog](https://alignment.openai.com/auto-review).

### Inferences
Possible value, all my inference and not yet proven:

- **Long policy to enforceable set.** Products accept short rules or plain-English requests. The team's pipeline (document, rule classification, coverage report, obligations) has no direct match in the products I read, except partly Automated Reasoning. It could compile into Cedar or Dogwood instead of competing with them.
- **Business facts.** Gateways see principal, tool, arguments and, with Dogwood, earlier events in the session. Facts such as whether the user confirmed, or whether a customer is eligible, need a source. The harness has the conversation and tool results, so CUGA is better placed to supply them.
- **Duties, not only blocks.** Gateways stop bad calls. They do not notice a required step that never happened at the end of a run, unless a later call depends on it. Internal note: up to 54 of 104 failed ITSM verifiers need a step or value the policy prescribes (project memory, 2026-11-02, not re-run here). Obligations target this.
- **Code execution.** Gateways see only calls that leave the process. CUGA's code blocks can batch several tool calls and logic, so an in-interpreter check can see more. This is close to CaMeL, as in our earlier notes.
- **Recovery after a denial.** Internal results show false denies and steering can hurt strong agents more than they help (project memory, 2026-11-01 and 2026-11-04). This is a measured result that vendors do not publish. The advice for a product: only checks with almost no false denies may block.
- **Small open models.** Vendor approvers use strong proprietary models. The team's pitch is that small open models can do the work with the policy system. No vendor I read targets this.
- **Portability.** Forrester says portable control planes lack standards. A layer that runs across clouds and emits to Cedar, Dogwood or CPEX has a role. Microsoft's Agent Governance Toolkit and CPEX are the closest open alternatives and should be compared directly.
- **Risk to this view.** AWS added temporal rules within about five months of GA, and Google already has an LLM judge. Vendors may reach long-document intake soon, so differentiation based on features alone may not last. Measured benchmark results and integration with IBM's ContextForge stack are harder to copy.

### Gaps
- I did not test any vendor product. All overlap claims come from docs and blogs.
- I found no vendor results on τ²-bench, AutomationBench, HANDBOOK or similar compliance benchmarks, but I did not search for this specifically.
- Whether CUGA should integrate with CPEX or ContextForge at the hook level was not checked in code for this task.
