# Regulation, standards and audit requirements for AI agents that follow company policy

Status: research notes as of 2026-11-05. This is not legal advice.

**Short answer.** No law reviewed says in words "controls must sit outside the model". But the binding duties fall on the organisation and the system, and they ask for logs, access limits, identity, a named owner, a way to stop the system, and written records. Model accuracy does not produce any of these. The only texts that explicitly ask for technical controls separate from the agent's reasoning are non-binding: the FSB final report and the Singapore IMDA framework. Regulators do allow less human review per action when risk is lower. None of the texts reviewed reduces logging, access control, accountability or incident duties because a model performs well.

**Labels used below**

| Label | Meaning |
|---|---|
| [LAW] | Binding statute, regulation or SRO rule |
| [CASE] | Court or tribunal decision |
| [FORMAL GUIDANCE] | Issued by a regulator or official body, but not binding as such |
| [DRAFT] | Formally proposed, not final |
| [VOLUNTARY] | Standard or framework that an organisation chooses to use |
| [SECONDARY] | I read a law firm, vendor or news summary, not the primary text |

How sources were read:
- Full text extracted from the PDF: SR 26-2 attachment, MAS final Guidelines, IMDA framework v1.5, FSB final report and June consultation report, SEC FY2027 priorities, NIST AI RMF and AI 600-1, CRS IF13245 (parts).
- Through a fetch tool that summarises a web page: OCC Bulletin 2026-13, csrc.nist.gov and nist.gov pages, FINRA pages, CFR and NYCRR sections, DORA articles, and AI Act articles on the Commission's AI Act Service Desk (the site says its page summaries are not legally binding). Check exact wording against the page before quoting these in a formal document.
- Texts I could not open are listed under Gaps.

## EU AI Act: current dates, what Articles 9, 12, 14, 15, 17, 19 and 26 require, how they apply to agents, and guidance on agents

### Takeaway
The Digital Omnibus moved the high-risk duties to 2 December 2027 (Annex III) and 2 August 2028 (Annex I), but the reporting I read shows no change to what Articles 9 to 19 and 26 require. These articles apply to agents only when the use case is high-risk, so most company-policy agents fall outside them, while Article 4 and Article 50 already apply. The Act has no legal category called "agent"; the only Commission text that addresses agents is non-binding guidance.

### Cited Findings

**Application dates [LAW]** (Regulation (EU) 2024/1689 as amended by Regulation (EU) 2026/1744, published in the Official Journal on 24 July 2026 and in force on 27 July 2026, per [Cooley, secondary](https://cdp.cooley.com/digital-ai-omnibus-delays-key-deadlines-introduces-new-rules/) and [ActuIA, secondary](https://www.actuia.com/en/news/ai-act-obligations-in-force-and-delays-under-omnibus-2026-1744/))

| Date | What applies | Source |
|---|---|---|
| 2 Feb 2025 | Article 5 prohibitions; Article 4 AI literacy | [ActuIA](https://www.actuia.com/en/news/ai-act-obligations-in-force-and-delays-under-omnibus-2026-1744/) |
| 2 Aug 2025 | General-purpose AI model duties; governance | [ActuIA](https://www.actuia.com/en/news/ai-act-obligations-in-force-and-delays-under-omnibus-2026-1744/) |
| 2 Aug 2026 | Article 50 transparency (already applies); Article 101 fines for GPAI | [ActuIA](https://www.actuia.com/en/news/ai-act-obligations-in-force-and-delays-under-omnibus-2026-1744/) |
| 2 Dec 2026 | End of grace period for Article 50(2) marking (systems on the market before 2 Aug 2026); new Article 5 bans on nudifiers and CSAM | [Cooley](https://cdp.cooley.com/digital-ai-omnibus-delays-key-deadlines-introduces-new-rules/) |
| 2 Aug 2027 | National sandboxes; GPAI models on the market before 2 Aug 2025 must comply (Art. 111(3)) | [Cooley](https://cdp.cooley.com/digital-ai-omnibus-delays-key-deadlines-introduces-new-rules/); [ActuIA](https://www.actuia.com/en/news/ai-act-obligations-in-force-and-delays-under-omnibus-2026-1744/) |
| **2 Dec 2027** | **Annex III stand-alone high-risk systems (was 2 Aug 2026)** | [Cooley](https://cdp.cooley.com/digital-ai-omnibus-delays-key-deadlines-introduces-new-rules/); [Orrick](https://www.orrick.com/en/Insights/2026/07/EU-AI-Act-Update-Digital-Omnibus-Finalizes-8-Compliance-Changes) |
| **2 Aug 2028** | **Annex I high-risk systems in regulated products (was 2 Aug 2027)** | [Cooley](https://cdp.cooley.com/digital-ai-omnibus-delays-key-deadlines-introduces-new-rules/) |
| 2 Aug 2030 | High-risk systems used by public authorities (Art. 111(2)) | [ActuIA](https://www.actuia.com/en/news/ai-act-obligations-in-force-and-delays-under-omnibus-2026-1744/) |

- The final text uses fixed calendar dates. The Commission's proposal had tied the dates to the availability of standards — [RegDossier, secondary](https://regdossier.eu/digital-omnibus-ai-act/); [Gibson Dunn, secondary](https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/).
- A high-risk system placed on the market before its application date is covered only if its design later changes significantly (Art. 111(2)) — [ActuIA, secondary](https://www.actuia.com/en/news/ai-act-obligations-in-force-and-delays-under-omnibus-2026-1744/).
- The Act's "fundamental architecture", including core obligations, is reported as intact — [Gibson Dunn, secondary](https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/). Providers relying on the Article 6(3) exemption must still register, in a simplified form; legislators rejected the Commission's proposal to remove this — [Cooley, secondary](https://cdp.cooley.com/digital-ai-omnibus-delays-key-deadlines-introduces-new-rules/).
- Article 4 literacy was softened from "ensure" to measures that "support" literacy. Sources differ on who holds the duty: [RegDossier](https://regdossier.eu/digital-omnibus-ai-act/) and [ActuIA](https://www.actuia.com/en/news/ai-act-obligations-in-force-and-delays-under-omnibus-2026-1744/) say providers and deployers; [Cooley](https://cdp.cooley.com/digital-ai-omnibus-delays-key-deadlines-introduces-new-rules/) says the Commission and member states support and facilitate.
- Fines for operator obligations and Article 50 are up to EUR 15 million or 3% of worldwide turnover (Art. 99) — [ActuIA, secondary](https://www.actuia.com/en/news/ai-act-obligations-in-force-and-delays-under-omnibus-2026-1744/).

**What the articles require [LAW, from 2 Dec 2027 for Annex III]**

| Article | Who | Requirement | Area |
|---|---|---|---|
| [Art. 9](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-9) | Provider | Continuous risk management over the whole lifecycle, including foreseeable misuse. Residual risk must be judged acceptable. Testing before market against prior defined metrics and probabilistic thresholds (9(8)). | Proof |
| [Art. 12](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-12) | Provider | System must allow "automatic recording of events (logs) over the lifetime of the system". Logs must support risk detection, post-market monitoring and deployer monitoring. Detailed log fields are listed only for remote biometric identification (12(3)). | Logging |
| [Art. 14](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-14) | Provider designs; deployer applies | Oversight proportionate to risk, autonomy and context (14(3)). People must be able to understand limits, watch for automation bias, interpret outputs, decide not to use, override or reverse (14(4)(d)), and stop the system (14(4)(e)). Two-person verification only for remote biometric identification (14(5)). | Oversight |
| [Art. 15](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-15) | Provider | "Appropriate" accuracy, robustness and cybersecurity over the lifecycle. Metrics declared in the instructions (15(3)). Resistance to manipulation by third parties (15(5)). No numeric threshold. Prompt injection is not named. | Accuracy, security |
| [Art. 17](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-17) | Provider | Quality management system as written policies, procedures and instructions. Covers change management, testing, record-keeping (17(1)(k)) and an accountability framework (17(1)(m)). Proportionate to organisation size (17(2)). | Proof, versioning |
| [Art. 19](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-19) | Provider | Keep logs under its control for at least six months. Financial institutions keep them inside their existing records. | Logging |
| [Art. 26](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-26) | Deployer | Technical and organisational measures to use the system per instructions (26(1)). Assign oversight to people with competence, training and authority (26(2)). Monitor, suspend use and report risks (26(5)). Keep logs at least six months (26(6)). | Oversight, logging |

Related articles for proof of compliance:
- [Art. 18](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-18): keep technical and QMS documents for 10 years.
- [Art. 73](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-73): report serious incidents within 15 days, 10 days for a death, 2 days for widespread infringements.
- [Art. 86](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-86): affected persons may ask for an explanation of the AI system's role in a decision.
- [Art. 25](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-25): a deployer becomes the provider if it makes a substantial modification or changes the purpose of a system so that it becomes high-risk. Providers must also agree in writing with suppliers on the information and help they need.

**When these articles apply**
- [Annex III](https://ai-act-service-desk.ec.europa.eu/en/ai-act/annex-3) covers, among others: recruitment and work decisions, including task allocation based on behaviour or traits and worker monitoring (point 4); creditworthiness, excluding fraud detection (5(b)); life and health insurance pricing (5(c)); emergency call triage (5(d)) [LAW].
- The Article 6(3) filter removes narrow procedural tasks and some preparatory tasks, but it is not available for profiling, nor where the system is part of a complex system that materially influences an Annex III decision — [Freshfields on the draft guidelines, secondary](https://www.freshfields.com/en/our-thinking/blogs/technology-quotient/eu-ai-act-unpacked-32-draft-commission-guidelines-on-high-risk-ai-implicati-102n1bn).

**Guidance on agents**
- "Agent" has no legal definition in the Act, and neither the Act nor the draft harmonised standards use it as a category. Agents fall under the Article 3(1) "AI system" definition. As of early 2026 the AI Office had no agent-specific guidance — [Nannini et al., working paper, secondary](https://arxiv.org/html/2604.04604).
- [FORMAL GUIDANCE] Final Article 50 Guidelines, 20 July 2026, non-binding: agents must disclose that they are artificial and who they act for, including in multi-agent setups. Generic labels are not enough — [Paul Weiss, secondary](https://www.paulweiss.com/insights/client-memos/eu-finalises-transparency-rules-for-ai-generated-content). The primary duty is on providers; if interactions cannot be foreseen, the agent should reveal itself whenever a human is reasonably likely to be involved — [Dastra, secondary](https://www.dastra.eu/en/blog/ai-act-transparency-rules-land-august-2-inside-the-commissions-new-guidelines/60198).
- [DRAFT] Commission high-risk classification guidelines, published 19 May 2026, consultation to 23 July 2026 — [Osborne Clarke, secondary](https://www.osborneclarke.com/insights/european-commission-publishes-draft-ai-act-guidelines-high-risk-classification-and). Complex or modular systems, including agentic ones, are assessed as a whole. Split architectures cannot be used to avoid classification. Human review does not by itself remove a system from high-risk, because classification depends on intended purpose. Another consultation round is planned before adoption — [Freshfields, secondary](https://www.freshfields.com/en/our-thinking/blogs/technology-quotient/eu-ai-act-unpacked-32-draft-commission-guidelines-on-high-risk-ai-implicati-102n1bn).
- [VOLUNTARY, gives presumption of conformity once cited] EN 18286:2026 (quality management, Art. 17) is reported as cited in the Official Journal on 14 Oct 2026 and is the only cited standard. Reported status of the others at 15 Oct 2026: prEN 18228 (risk) reportedly rejected at enquiry, in comment resolution; prEN 18282 (cybersecurity) reportedly rejected at enquiry, in revision; prEN 18229-1 (logging) reportedly failed at enquiry, in comment resolution; prEN 18229-3 (human oversight) in enquiry to 22 Oct 2026; prEN 18229-4 and -5 (accuracy, robustness) in drafting. No deliverable is described as covering agents — [KLA tracker, secondary, enquiry results come from a newsletter](https://kla.digital/blog/jtc-21-standards-tracker).
- Academic view, not law: high-risk agents with untraceable behaviour drift cannot currently meet the essential requirements. Retrospective review alone is insufficient for irreversible actions. The first compliance task is an inventory of external actions, data flows, connected systems and affected persons. Runtime state should be versioned so that drift can be measured — [Nannini et al.](https://arxiv.org/html/2604.04604).

### Inferences
These are my application to agents. The Act does not say them.
- A customer-service, IT or CRM agent that follows company policy is usually not high-risk. The same agent becomes high-risk when it screens candidates, allocates work by personal traits, or scores credit. The classification follows the use case, not the technology.
- Art. 12 logs for an agent should include tool calls, policy checks, inputs that triggered actions and human overrides. Art. 12 does not list these for agents, but its purposes (detecting risk, monitoring) cannot be met without them.
- Art. 14(3) allows oversight levels to differ by risk and autonomy. It does not require approval of every action. Art. 14(4)(d) and (e) still require that override and stop exist.
- A company that builds a high-risk agent on a general-purpose LLM is likely the provider under Art. 25 and takes on Arts. 9, 12, 15, 17 and 19.
- An agent whose rules exist only in its prompt gives weak evidence for "technical and organisational measures" (Art. 26(1)) and for written procedures (Art. 17(1)).

### Gaps
- I could not open Regulation (EU) 2026/1744 on EUR-Lex (the page returned empty). All Omnibus details are from secondary sources. No source I read lists changes to Articles 9 to 15, 19 or 26 line by line, so "no change" means "none reported". The Article 17 Service Desk text does mention small mid-caps (SMCs), which matches the reported Omnibus extension.
- The final date for the high-risk guidelines is not confirmed. Some search results said end of 2026; I did not verify this.
- I did not read either set of Commission guidelines directly.
- I did not verify the conformity assessment route for agents (Art. 43, Annex VI or VII).
- EN 18286 publication date: KLA gives 22 July 2026; a search excerpt gave 31 July 2026. I could not open the second source. I did not check the Official Journal citation directly.

## NIST: AI RMF, the generative AI profile, and 2025–2026 agent work including COSAIS and identity

### Takeaway
All of it is voluntary. The AI RMF and the generative AI profile do not address agents as a category. The agent-specific work exists as an initiative, a concept paper and a comment summary. The agent overlays are listed as proposed, with no published draft as of the project page on 5 November 2026.

### Cited Findings
- [VOLUNTARY] AI RMF 1.0 (January 2023). I found no use of the word "agent" in the text. Relevant items: GOVERN 1.4 (transparent policies and controls), MAP 3.5 (human oversight processes defined, assessed and documented), MEASURE 2.8 (transparency and accountability risks examined and documented), MANAGE 2.4 (mechanisms and assigned responsibility to supersede, disengage or deactivate systems), MANAGE 4.1 (post-deployment monitoring, including override, incident response and change management) — [NIST AI 100-1](https://nvlpubs.nist.gov/nistpubs/ai/nist.ai.100-1.pdf).
- [VOLUNTARY] Generative AI Profile (July 2024). "Autonomous agents" appears once, in a list of security concerns (MS-2.7-001). Other uses of "agent" refer to chemical and biological agents. So it does not address software agents as a category — [NIST AI 600-1](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf).
- [VOLUNTARY] AI Agent Standards Initiative (page created 17 Feb 2026, updated 14 Aug 2026): three pillars, namely industry-led standards, community protocols, and research on agent security and identity. It lists an RFI and listening sessions and no final guidance. It aims at voluntary guidelines — [NIST CAISI](https://www.nist.gov/caisi/ai-agent-standards-initiative).
- [DRAFT, non-binding] NCCoE concept paper on software and AI agent identity and authorization, February 2026 — [NCCoE](https://csrc.nist.gov/pubs/other/2026/02/05/accelerating-the-adoption-of-software-and-ai-agent/ipd). Comment summary released 29 Sep 2026: more than 600 commenters. First use case is DevSecOps. Input is reviewed on a rolling basis, not in a fixed period — [NIST](https://www.nist.gov/news-events/news/2026/09/comments-software-and-agentic-ai-identity-concept-paper).
- [DRAFT, proposed] SP 800-53 Control Overlays for Securing AI Systems (COSAiS) was renamed "Control Overlays for Super Intelligence Systems (COSIS)" on 20 Oct 2026, citing a 29 Sep 2026 Executive Order. Five proposed use cases include "Using SI Agent Systems: Single Agent" and "Multi-Agent". The published items are the concept paper (14 Aug 2025) and a predictive AI outline (8 Jan 2026). No draft is listed for agents, and no date is given — [csrc.nist.gov](https://csrc.nist.gov/projects/cosais).
- [DRAFT] A May 2026 Cyber AI Profile working session proposed priority for PR.AA-01, unique and traceable identities and credentials for AI systems — [NCCoE slides](https://www.nccoe.nist.gov/sites/default/files/2026-05/Cyber-AI-Profile-Working-Session-Extending-Tech-Content-Slides-Slido.pdf).
- Search note: US federal texts since 29 Sep 2026 may say "Super Intelligence" or "SI" instead of "AI". The SEC FY2027 priorities do so ([SEC](https://www.sec.gov/files/2027-exam-priorities.pdf)). The order is reported as EO 14434 ([Katten via NatLawReview, secondary](https://natlawreview.com/article/secs-2027-examination-priorities-artificial-intelligence-and-cyber-risk)). It was signed on 29 Sep 2026 and applies to executive branch agencies for non-statutory materials ([Fox Business, secondary](https://www.foxbusiness.com/politics/trump-signs-executive-order-rebranding-ai-super-intelligence-tech-titans-ink-separate-accord)). CAISI is reported as now "CAISSI" ([AT Pulse, secondary](https://at-pulse.com/stories/2265/)); I did not confirm this on nist.gov.

### Inferences
- NIST does not bind private companies. Its value is as a shared vocabulary and as the expected reference for US auditors and contract terms. That second point is my expectation, not a finding.
- MANAGE 2.4 and MAP 3.5 are written for AI systems generally, and they apply to agents only by my reading. The items for monitoring, override and deactivation do not depend on model quality.
- The NCCoE direction treats identity and authorization as enterprise functions, separate from the model. No final NIST text says this yet.

### Gaps
- I did not read the NCCoE concept paper in full, nor the comment summary hub.
- I did not verify the status of NIST IR 8596 (Cyber AI Profile). A Cloud Security Alliance note in search results forecast that final agent guidance is unlikely before 2027; I did not verify this.
- I did not read the text of the Executive Order.

## ISO/IEC 42001 and related standards: which controls bear on agent actions and audit

### Takeaway
ISO/IEC 42001 is a voluntary management-system standard, not a harmonised standard under the AI Act. Its controls relevant to agents are A.6.2.8 (event logs), A.9 (use of AI systems) and A.10 (responsibilities across suppliers). Nothing I found in it addresses agents by name, and certification shows that a management system exists. It does not show that an agent obeyed a given rule.

### Cited Findings
- [VOLUNTARY] Mandatory clauses are 4 to 10. Annex A has 38 controls in nine domains (A.2 to A.10), which an organisation selects based on risk. A Statement of Applicability must give a justification for each inclusion or exclusion — [SureCloud, secondary](https://www.surecloud.com/resource-hub/iso-42001-annex-a-controls).
- Control titles below are from a reference listing that uses B-numbers and calls itself a placeholder — [myctrl.tools, secondary](https://www.myctrl.tools/frameworks/iso-42001). The mapping of B to A numbers is my reading.

| Control | Title | Why it matters for agents (my reading) |
|---|---|---|
| A.2.2 | AI policy | Top-level policy the agent must follow |
| A.3.2 | AI roles and responsibilities | Named owners |
| A.3.3 | Reporting of concerns | Route for reporting agent problems |
| A.5.2 | AI system impact assessment process | Assessment before deployment |
| A.6.2.4 | AI system verification and validation | Evidence from testing |
| A.6.2.5 | AI system deployment | Release control |
| A.6.2.6 | AI system operation and monitoring | Runtime monitoring |
| A.6.2.8 | AI system recording of event logs | Audit trail |
| A.8.4 | Communication of incidents | Incident reporting |
| A.9.2 | Processes for responsible use of AI systems | Operating rules |
| A.9.3 | Objectives for responsible use of AI system | Human-oversight objectives |
| A.9.4 | Intended use of the AI system | Keeps the agent within its purpose |
| A.10.2 | Allocating responsibilities | Vendor and deployer split |
| A.10.3 | Suppliers | Model and tool vendors |

- A.6.2.8 leaves it to the organisation to decide at which lifecycle phases event logging is enabled. Retention is left to law, policy and business need — [ISMS.online, secondary](https://www.isms.online/iso-42001/annex-a-controls/a-6-ai-system-life-cycle/a-6-2-8-ai-system-recording-of-event-logs/).
- A.9 covers responsible-use processes, use objectives such as human-in-the-loop requirements, and checks that the system stays within its intended purpose — [SureCloud, secondary](https://www.surecloud.com/resource-hub/iso-42001-annex-a-controls).
- Source conflict: [CertPro](https://certpro.com/hub/iso-42001/controls/iso-42001-controls-list/) titles A.9 as "AI System Documentation" and A.3.2 as "AI Roles Within Projects". This disagrees with the other sources, so I treat CertPro as unreliable.
- The Commission says the goals and definitions of ISO/IEC 42001:2023 do not align with the quality management system the Act requires, and it asked for a new standard — [Commission FAQ](https://digital-strategy.ec.europa.eu/en/faqs/understanding-standardisation-ai-act). No ISO/IEC standard currently carries the Article 40 presumption — [KLA tracker, secondary](https://kla.digital/blog/jtc-21-standards-tracker).
- ISO/IEC 42006 sets requirements for bodies that certify to 42001 — [Bright Defense, secondary](https://www.brightdefense.com/news/iso-42006-raises-the-bar-for-iso-42001-certifiers/).
- ISO/IEC 22989 is being amended, with agent definitions expected. ISO/IEC DIS 42105 (human oversight) assumes a bounded system giving discrete outputs to a reviewer, and multi-agent orchestration does not fit this model. The authors cite the view that technical standards will likely not fully address agent risks — [Nannini et al., working paper, secondary](https://arxiv.org/html/2604.04604).

### Inferences
- A certificate gives process evidence for an audit. It does not replace the action-level evidence that a rule was checked for a specific agent action.
- An auditor could accept a reduced control set if the documented risk assessment supports it. The justification would need to rest on risk treatment. I found no text allowing exclusion based on model performance alone.

### Gaps
- The ISO text is sold by ISO and I did not read it. Control wording above is from secondary sources, so check it against the standard before quoting.
- I did not find a published ISO/IEC control set specific to agents.

## Sector rules: US banking, FINRA and SEC, HIPAA, FDA, EU DORA, NYDFS, MAS. Which apply to automated actions, and 2025–2026 statements on agents

### Takeaway
Existing binding rules on supervision, records, access and logs apply to agents because they are technology-neutral. They were not written for agents. Three formal texts address agents directly and all are non-binding: the FINRA report, the MAS Guidelines and the FSB report. The US banking guidance goes the other way and excludes agents, leaving banks to their general risk frameworks.

### Cited Findings

| Framework | Type | Date | Names agents? | Key point for agents |
|---|---|---|---|---|
| [SR 26-2](https://www.federalreserve.gov/supervisionreg/srletters/SR2602a1.pdf) / [OCC 2026-13](https://www.occ.gov/news-issuances/bulletins/2026/bulletin-2026-13.html) | FORMAL GUIDANCE | 17 Apr 2026 | Yes, to exclude them | Agents out of scope; own governance applies |
| [FINRA Rule 3110 and report](https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/gen-ai) | LAW (rule); report is FORMAL GUIDANCE | Report Dec 2025 | Yes | Supervision must fit the agent |
| [SEC FY2027 priorities](https://www.sec.gov/files/2027-exam-priorities.pdf) | Staff statement, no legal force | 23 Oct 2026 per [Katten](https://natlawreview.com/article/secs-2027-examination-priorities-artificial-intelligence-and-cyber-risk) | No (only "transfer agents") | Existing duties, monitoring procedures |
| [HIPAA 45 CFR 164.312](https://www.law.cornell.edu/cfr/text/45/164.312) | LAW | In force | No | Access, unique ID, audit controls |
| FDA device law, per [CRS](https://www.congress.gov/crs_external_products/IF/PDF/IF13245/IF13245.1.pdf) | LAW plus guidance | Report 10 Jun 2026 | No | Applies only if the software is a device |
| [DORA](https://www.digital-operational-resilience-act.com/Article_9.html) | LAW | Applies since [17 Jan 2025](https://www.digital-operational-resilience-act.com/Article_64.html) | No | Access, change control, logging, board duty |
| [23 NYCRR 500](https://www.law.cornell.edu/regulations/new-york/23-NYCRR-500.6) and [DFS letter](https://www.dfs.ny.gov/industry-guidance/industry-letters/il20241016-cyber-risks-ai-and-strategies-combat-related-risks) | LAW; letter is FORMAL GUIDANCE | Letter 16 Oct 2024 | No | Access limits, audit trail 5 years |
| [MAS Guidelines](https://www.mas.gov.sg/-/media/mas-media-library/regulation/guidelines/bd/guidelines-on-artificial-intelligence-risk-management-for-financial-institutions/guidelines-on-artificial-intelligence-risk-management.pdf) | FORMAL GUIDANCE (supervisory expectations) | Issued 7 Oct 2026; effective 7 Oct 2027 and 7 Oct 2028 | Yes | Inventory, oversight, monitoring of actions |
| [IMDA framework v1.5](https://www.imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/mgf-for-agentic-ai.pdf) | VOLUNTARY | 20 May 2026, updated 5 Jun 2026 | Yes, whole document | Limits by design, checkpoints |
| [FSB final report](https://www.fsb.org/uploads/P151026-1.pdf) | FORMAL GUIDANCE, international, non-binding | 15 Oct 2026 | Yes | Oversight plus deterministic controls |

**US banking**
- SR 26-2 replaces SR 11-7 and SR 21-8 — [Federal Reserve](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm). Footnote 3 says generative and agentic AI models are "not within the scope of this guidance", and that a bank's own risk management and governance should guide controls for such tools — [SR 26-2 attachment](https://www.federalreserve.gov/supervisionreg/srletters/SR2602a1.pdf).
- The guidance has no enforceable standards, but footnote 1 keeps supervisory action for violations of law and for unsafe or unsound practices. It is most relevant above $30 billion in assets — [SR 26-2 attachment](https://www.federalreserve.gov/supervisionreg/srletters/SR2602a1.pdf).
- The term "model" excludes simple arithmetic, spreadsheet calculations and deterministic rule-based processes without underpinning theories — [OCC Bulletin 2026-13](https://www.occ.gov/news-issuances/bulletins/2026/bulletin-2026-13.html).
- The agencies plan a request for information that will cover generative and agentic AI — [OCC Bulletin 2026-13](https://www.occ.gov/news-issuances/bulletins/2026/bulletin-2026-13.html). Vice Chair Bowman (delivered 27 April, posted 1 May 2026) said the guidance does not apply to generative or agentic AI, that other risk and governance practices are expected to support adoption, and that third-party risk guidance is being simplified. Her speech does not address human oversight — [Federal Reserve](https://www.federalreserve.gov/newsevents/speech/bowman20260501a.htm).
- [VOLUNTARY] The Financial Services AI Risk Management Framework came from a Treasury-led public-private partnership, announced February 2026. It lists 230 controls and is not mandatory — [Legal 500, secondary](https://www.legal500.com/intelligence/united-states/finance-and-banking/financial-services-ai-risk-management-framework-expanded-controls-for-the-financial-services-industry). I did not read the framework itself.

**FINRA and SEC**
- [LAW plus guidance] FINRA's rules are technology-neutral and apply to AI use. Regulatory Notice 24-09 (27 June 2024) created no new requirements — [FINRA](https://www.finra.org/rules-guidance/notices/24-09).
- [FORMAL GUIDANCE] The 2026 Oversight Report names agent risks: acting without human validation, going beyond the user's scope and authority, and outcomes that are hard to trace. It says firms may consider supervision specific to the agent's type and scope, where to place human-in-the-loop, how to track actions and decisions, and what guardrails to set. This wording is "may consider", not "must" — [FINRA](https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/gen-ai).
- FINRA's blog (27 Jan 2026) says agents may lack the transparency and predictability that traditional supervision assumes, and that the post creates no new requirements — [FINRA](https://www.finra.org/media-center/blog/observations-on-ai-agents).
- [LAW] Rule 4511 requires firms to make and preserve books and records. The report section does not discuss agents — [FINRA](https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/books-and-records).
- [DRAFT] Regulatory Notice 26-14 (July 2026) asks for comment on modernising Rule 2210, including AI-generated communications. It does not address agents directly — [FINRA](https://www.finra.org/sites/default/files/2026-07/Regulatory-Notice-26-14.pdf).
- [Staff statement, no legal force] SEC FY2027 priorities: the Division will study how the technology influences outcomes and whether firms comply with "existing, technology-neutral obligations". It will prioritise policies and procedures for monitoring SI in fraud detection, back-office work, AML and Reg BI compliance, and trading — [SEC](https://www.sec.gov/files/2027-exam-priorities.pdf).
- No SEC recordkeeping rule is written for AI. Existing Rule 17a-4 and Rule 204-2 apply — [Meilynx, vendor, secondary](https://www.meilynx.com/reference/sec-17a-4-ai-recordkeeping).

**HIPAA and FDA**
- [LAW] Access only for "persons or software programs" granted rights (164.312(a)(1)). Unique user identification required (a)(2)(i). Audit controls that record and examine activity (b). Integrity (c). Authentication of persons or entities (d) — [45 CFR 164.312](https://www.law.cornell.edu/cfr/text/45/164.312). Required documentation is retained for 6 years — [45 CFR 164.316](https://www.law.cornell.edu/cfr/text/45/164.316).
- [LAW] Covered entities must make reasonable efforts to identify and reduce discrimination risk from patient care decision support tools — [45 CFR 92.210](https://www.law.cornell.edu/cfr/text/45/92.210).
- [DRAFT] The January 2025 Security Rule proposal is not final, with a projected final action date of July 2027 — [Emerson, secondary](https://www.bdemerson.com/article/hipaa-and-ai).
- FDA regulates AI as a device only if the software meets the device definition. As of June 2026, FDA did not appear to have authorised any generative AI device, though it gave breakthrough designation to one in March 2026. CRS describes the January 2026 updates to the clinical decision support and general wellness guidance as somewhat deregulatory. PCCPs allow certain planned changes without a new submission, under performance requirements — [CRS IF13245](https://www.congress.gov/crs_external_products/IF/PDF/IF13245/IF13245.1.pdf).

**EU DORA**
- [LAW] Management body bears ultimate responsibility for ICT risk (Art. 5(2)) — [DORA Art. 5](https://www.digital-operational-resilience-act.com/Article_5.html). Access limited to what approved functions need (Art. 9(4)(c)). Strong authentication (9(4)(d)). Documented change management: recorded, tested, assessed, approved (9(4)(e)) — [DORA Art. 9](https://www.digital-operational-resilience-act.com/Article_9.html).
- [LAW] RTS 2024/1774 Art. 12: identify events to log, including access control and identity management. The entity sets the retention period. Logs must be protected against tampering and deletion — [unofficial mirror, secondary](https://springlex.netlify.app/en/packages/dora/rts-rmf-regulation/article-12/).
- [FORMAL GUIDANCE] Joint ESA statement JC 2026 25 (31 July 2026) covers ICT risk from frontier AI. It adds no new requirements and calls for a move from periodic to continuous monitoring, and for inventories that include AI/ML components. Reported as not discussing agents — [BankingNewsAI, secondary](https://www.bankingnewsai.com/ai-regulation/documents/esas-jc-2026-25-frontier-ai-statement).

**NYDFS**
- [LAW] 23 NYCRR 500.6: audit trails designed to detect and respond to cybersecurity events, records kept at least five years — [500.6](https://www.law.cornell.edu/regulations/new-york/23-NYCRR-500.6).
- [FORMAL GUIDANCE] The 16 Oct 2024 letter adds no new requirements. It restates 500.7 (access only as needed for job functions, reviewed at least annually), 500.12 (MFA), 500.11 (third parties) and 500.5(b) (monitor activity), and asks for an inventory of systems that use AI. It does not address agents — [DFS](https://www.dfs.ny.gov/industry-guidance/industry-letters/il20241016-cyber-risks-ai-and-strategies-combat-related-risks).
- The frontier-AI advisory of 21 May 2026 recommends testing and human oversight of AI-generated code before production. It creates no new legal requirements, though DFS may use it as a benchmark in examinations. The law firm article does not mention agents — [Greenberg Traurig, secondary](https://www.gtlaw.com/en/insights/2026/6/nydfs-issues-dual-guidance-on-heightened-cybersecurity-threats-frontier-ai-risks).

**MAS and IMDA (Singapore)** — [MAS Guidelines](https://www.mas.gov.sg/-/media/mas-media-library/regulation/guidelines/bd/guidelines-on-artificial-intelligence-risk-management-for-financial-institutions/guidelines-on-artificial-intelligence-risk-management.pdf); paragraph references below are to this text
- Para 1.1 calls these supervisory expectations. Para 1.8: effective 7 Oct 2027 for Sections 3 and 4; Sections 5 and 6 by 7 Oct 2028.
- Footnote 6: AI agents and multi-agent systems are in scope. Rule-based systems and fixed RPA are generally not AI for these purposes.
- Para 1.11: agents with tool access may take unauthorised or wrong actions because of a gap between goals and actions; compromised agents can exfiltrate data at scale.
- Footnote 25: inventory attributes for agents may include agent identifiers, tools and systems accessible, components and guardrails.
- Para 4.12: materiality considers impact, complexity and reliance. Reliance includes the autonomy granted and the degree of human involvement.
- Para 5.3: high-risk use cases need tested fallback plans. Para 5.15: testing should cover agents' failure modes and the effectiveness of guardrails.
- Para 5.9: human oversight proportionate to materiality, with assigned roles, authority to intervene, escalation at pre-defined conditions, records and logs, and review of near misses. Automation bias and decision fatigue must be taken into account.
- Para 5.23: monitor reasoning, actions and tools where relevant; name an accountable person; strictly control and log access. Para 5.23(b) asks firms to "consider" kill switches for high-risk AI, so they are not mandated.
- [VOLUNTARY] IMDA framework: define checkpoints for human approval on high-stakes, irreversible, outlier and user-defined actions. Prefer deterministic limits; for example, impose access controls instead of telling the agent in a prompt not to use a tool. Roll out gradually. Extend identity management to agents. Its case study on OpenClaw asks that all agent actions be logged and attributable — [IMDA v1.5](https://www.imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/mgf-for-agentic-ai.pdf). MAS footnote 11 refers firms to this framework. First released 22 Jan 2026. Singapore has no AI-specific legislation and the framework is described as structured guidance — [Mayer Brown, secondary](https://www.mayerbrown.com/en/insights/publications/2026/04/singapores-agentic-ai-framework-practical-guidance-for-market-entry). The "voluntary" label is my reading: the framework states no legal duty.

**International and UK**
- [FORMAL GUIDANCE, non-binding] FSB final report, 15 Oct 2026, section 3.7, Sound Practice 10 (human oversight). Firms combine human oversight with deterministic controls for agents. The report describes these as technical controls, introduced at design and coded in the layer that decides what an agent can do. Examples:
  - prohibited actions outside risk appetite;
  - limited external access;
  - risk-based triggers for human approval, for example transactions above a certain value or actions that may cause irreversible harm;
  - AI monitoring of agents, with the monitor itself evaluated;
  - documentation of anomalous behaviour, which may include the reasoning at each decision point, tools accessed and final outcome (fn 86);
  - tested kill switches.
  Even when monitoring is done mostly by machines, institutions and individuals keep ultimate accountability (fn 85). Firms name an accountable individual for each agent use case. Capabilities can change over time with new tools or prompts. Section 3.8, Sound Practice 11, adds zero-trust principles: explicit identity verification, least privilege and action-level authorisation. The report states the practices are non-prescriptive and not a binding international standard — [FSB final report](https://www.fsb.org/uploads/P151026-1.pdf).
- The final text is reported as stronger than the June draft on oversight, and it drops the idea of treating AI as "synthetic employees" — [Reuters via Investing.com, secondary](https://www.investing.com/news/economy-news/global-financial-watchdog-calls-for-more-human-oversight-of-agentic-ai-4950478).
- Source conflict: the June draft named human approval or dual authorisation above a value, and audit trails of agent transactions ([FSB consultation report](https://www.fsb.org/uploads/P100626.pdf)). I did not find the words "dual authorisation" or "audit trail" in the final text. One secondary site says the framework "requires" dual authorisation ([Forkast](https://forkast.news/fsb-sound-practice-10-the-supervisory-architecture-for-agentic-ai-that-national-regulators-will-translate/)). That does not match the final report, which is non-binding and uses the broader term of risk-based triggers.
- UK: the FCA Mills Review (July 2026) makes recommendations and creates no new obligations. Firms may find it harder to show how decisions were reached and what reasonable steps they took, and accountability under SM&CR remains relevant — [Freeths, secondary](https://www.freeths.co.uk/insights-events/legal-articles/2026/fca-s-mills-review-agentic-ai-consumer-duty-and-the-future-of-financial-services/).

### Inferences
- HIPAA's words "software programs" and "unique user identification" fit an agent identity directly. An agent running under a shared human or service credential is hard to reconcile with this. No regulator has said so for agents; this is my reading.
- US banks: excluding agents from SR 26-2 does not remove obligations. Safety-and-soundness supervision, third-party rules and cybersecurity rules still apply. It removes the common reference document, so banks must write their own standard.
- SR 26-2 and MAS both treat fixed rule systems as outside "model" or "AI". A deterministic policy check coded outside the model may therefore avoid model-risk treatment itself, while still being an IT control subject to change management. This is my inference.
- Vendor sites often say FINRA "requires" agent logs or human-in-the-loop. The FINRA text says "may consider". The binding duty is the general Rule 3110 and Rule 4511, and applying them to specific agent controls is an inference.

### Gaps
- I did not find a direct agent statement from HHS OCR, FDA, NYDFS, the SEC or the ESAs.
- Not verified: the retention periods in Rule 17a-4 and Rule 204-2; 21 CFR Part 11 audit trails; NYDFS Circular Letter 2024-7 for insurers; the compliance date of 45 CFR 92.210.
- The January 2025 FDA draft on AI-enabled device software functions appears to remain a draft. I did not verify this on fda.gov.
- I found no confirmation that the US banking request for information has been issued.
- I did not read the Mills Review directly.

## Liability and case law: who is responsible when an agent breaks policy

### Takeaway
The courts and statutes reviewed point responsibility at the organisation that deploys the system, and sometimes at the vendor. None treats the AI as a responsible party. Case law is thin, and most cases are early-stage or from low-level tribunals. No decision I found concerns an agent breaking an internal company policy.

### Cited Findings
- [CASE] *Moffatt v. Air Canada*, 2024 BCCRT 149 (British Columbia Civil Resolution Tribunal, a small claims tribunal, 14 Feb 2024): negligent misrepresentation by a website chatbot. The tribunal rejected the argument that the chatbot was a separate entity, held the airline responsible for all information on its website, and found that it did not take reasonable care to ensure the chatbot was accurate — [McCarthy Tétrault, secondary](https://www.mccarthy.ca/en/insights/blogs/techlex/moffatt-v-air-canada-misrepresentation-ai-chatbot). Wikipedia gives damages of C$812 ([Wikipedia, secondary](https://en.wikipedia.org/wiki/Moffatt_v._Air_Canada)); a search excerpt of another summary gave $650.88. The amount is not important to the holding.
- [CASE] *Mobley v. Workday* (N.D. Cal., No. 3:23-cv-00770), July 2024: at the pleading stage, the court accepted that a vendor can be directly liable for employment discrimination as the employer's "agent", because customers delegated a traditional hiring function to it — [Seyfarth, secondary](https://www.seyfarth.com/news-insights/mobley-v-workday-court-holds-ai-service-providers-could-be-directly-liable-for-employment-discrimination-under-agent-theory.html). Conditional certification of the ADEA claim followed in 2025 — [Proskauer, secondary](https://www.lawandtheworkplace.com/2025/06/ai-bias-lawsuit-against-workday-reaches-next-stage-as-court-grants-conditional-certification-of-adea-claim/). "Agent" here is the legal term and does not mean a software agent.
- [CASE] *Amazon.com Services, LLC v. Perplexity AI, Inc.*, No. 26-1444 (9th Cir., 4 Aug 2026): vacated a preliminary injunction against the Comet Assistant. Because the assistant ran on the user's device, the user, not Perplexity, was treated as accessing Amazon's site. The court said it was not creating a new legal regime for agentic AI, did not decide tort liability, and did not limit Amazon's terms of service — [Pearl Cohen, secondary](https://www.pearlcohen.com/ninth-circuit-vacates-injunction-against-perplexitys-ai-shopping-agent/).
- [LAW] California Civil Code § 1714.46 (AB 316), effective 1 Jan 2026: a party that developed, modified or used an AI system cannot defend by saying the AI acted autonomously. Causation, foreseeability and comparative fault remain available. It is not strict liability — [Baker Botts via Legal 500, secondary](https://www.legal500.com/intelligence/united-states/technology/california-eliminates-the-autonomous-ai-defense-what-ab-316-means-for-ai-deployers).
- [LAW] E-SIGN, 15 U.S.C. § 7001(h): a contract is not invalid only because electronic agents formed it, so long as the agent's action is "legally attributable to the person to be bound" — [15 U.S.C. § 7001](https://www.law.cornell.edu/uscode/text/15/7001).
- [LAW] EU Product Liability Directive 2024/2853: software and AI are in scope; member states transpose by 9 Dec 2026, for products placed on the market after that date — [Taylor Wessing, secondary](https://www.taylorwessing.com/en/insights-and-events/insights/2025/01/di-new-product-liability-directive). The proposed AI Liability Directive was withdrawn (dates differ: February or October 2025), which leaves fault-based liability to national law — [IAGovernance, secondary](https://iagovernance.com/en/blog/ai-liability-act-withdrawn/); [Puglisi, secondary](https://basilpuglisi.com/eu-ai-liability-product-directive/).
- [LAW] Colorado SB 189 (signed 14 May 2026, effective 1 Jan 2027) removes the duty of care and the deployer risk programme and impact assessment duties. It keeps developer disclosures and, in limited cases, access and correction rights and meaningful human review of adverse automated decisions — [Hunton, secondary](https://www.hunton.com/privacy-and-cybersecurity-law-blog/colorado-ai-act-amended-and-effective-date-delayed).
- [FORMAL GUIDANCE] FSB: controls limit agent behaviour but "do not, by themselves resolve questions about who is accountable". Firms should document accountable individuals and seek contract clarity on legal liability from third parties — [FSB final report](https://www.fsb.org/uploads/P151026-1.pdf).

### Inferences
- If an agent breaks company policy and harms a customer, expect the deploying company to answer first. It may then seek recovery from the vendor by contract.
- A better model reduces how often harm occurs. It does not change who answers for the harm that does occur. *Moffatt* also shows that a defendant needs evidence of reasonable care, and that evidence is about process.
- Attribution reasoning in *Perplexity* and E-SIGN supports treating the agent's acts as the principal's acts, though neither case addresses policy breaches.

### Gaps
- I found no court decision on an autonomous agent that broke an internal policy or exceeded delegated authority inside a company.
- Search excerpts reported an amended Amazon complaint on 21 Sep 2026 about iOS Comet and a May 2026 *Mobley* discovery order; I did not verify either.
- I did not read any of these decisions in the original.

## Do these frameworks care about model accuracy or process evidence, and which requirements stay if the model becomes near-perfect? Is any regulator open to reducing controls based on proven performance?

### Takeaway
Accuracy is one required item among many, it has no numeric threshold, and the firm sets it and must evidence it. Most binding duties ask for process evidence. Soft guidance allows the amount of human review to change with risk and, in the FSB's example, with performance metrics. I found no text that drops logs, access control, accountability, stop capability or incident duties because a model has proven itself.

### Cited Findings

**How accuracy is treated**
- Article 15 asks for an "appropriate" level with declared metrics, not a number — [Art. 15](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-15). Testing is against metrics defined in advance — [Art. 9](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-9).
- SR 26-2: materiality comes from model exposure and purpose. Even a sound model with accurate outputs "can exhibit high model risk if it is misapplied or misused" — [SR 26-2 attachment](https://www.federalreserve.gov/supervisionreg/srletters/SR2602a1.pdf). This guidance does not cover agents, but it shows the regulators' reasoning.
- FINRA treats the integrity, reliability and accuracy of a GenAI model as something procedures may consider inside a supervisory system — [FINRA](https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/gen-ai).
- FSB: a performance track record may show where closer scrutiny is needed and helps calibrate assessment benchmarks — [FSB final report](https://www.fsb.org/uploads/P151026-1.pdf).

**Which requirements stay**

| Requirement | Near-perfect model removes it? | Strongest source (type) | Applies when |
|---|---|---|---|
| Named accountable person or management duty | No | [DORA 5(2)](https://www.digital-operational-resilience-act.com/Article_5.html) (LAW); [AI Act 17, 26(2)](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-26) (LAW); [MAS 5.23(c)](https://www.mas.gov.sg/-/media/mas-media-library/regulation/guidelines/bd/guidelines-on-artificial-intelligence-risk-management-for-financial-institutions/guidelines-on-artificial-intelligence-risk-management.pdf); [FSB](https://www.fsb.org/uploads/P151026-1.pdf) | EU finance now; AI Act high-risk from 2 Dec 2027; MAS from 2028 |
| Automatic logs and audit trail | No | [AI Act 12](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-12), [19](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-19), [26(6)](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-26); [HIPAA 164.312(b)](https://www.law.cornell.edu/cfr/text/45/164.312); [NYCRR 500.6](https://www.law.cornell.edu/regulations/new-york/23-NYCRR-500.6); [DORA RTS 12](https://springlex.netlify.app/en/packages/dora/rts-rmf-regulation/article-12/) (all LAW) | HIPAA, NYDFS, DORA now; AI Act high-risk from 2 Dec 2027 |
| Access limits and least privilege | No | [DORA 9(4)(c)](https://www.digital-operational-resilience-act.com/Article_9.html); [HIPAA 164.312(a)](https://www.law.cornell.edu/cfr/text/45/164.312); [NYDFS 500.7](https://www.dfs.ny.gov/industry-guidance/industry-letters/il20241016-cyber-risks-ai-and-strategies-combat-related-risks) (LAW) | Now, in those sectors |
| Unique identity and authentication | No | [HIPAA 164.312(a)(2)(i), (d)](https://www.law.cornell.edu/cfr/text/45/164.312); [DORA 9(4)(d)](https://www.digital-operational-resilience-act.com/Article_9.html) (LAW) | Now, in those sectors |
| Ability to override and stop | No | [AI Act 14(4)(d),(e)](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-14) (LAW); [FSB](https://www.fsb.org/uploads/P151026-1.pdf); [MAS 5.3, 5.23(b)](https://www.mas.gov.sg/-/media/mas-media-library/regulation/guidelines/bd/guidelines-on-artificial-intelligence-risk-management-for-financial-institutions/guidelines-on-artificial-intelligence-risk-management.pdf) | AI Act high-risk from 2 Dec 2027 |
| Written procedures, change control, versioned records | No | [AI Act 17](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-17), [18](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-18); [DORA 9(4)(e)](https://www.digital-operational-resilience-act.com/Article_9.html) (LAW) | DORA now; AI Act high-risk from 2 Dec 2027 |
| Monitoring and incident reporting | No | [AI Act 26(5)](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-26), [73](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-73) (LAW); [MAS 5.23](https://www.mas.gov.sg/-/media/mas-media-library/regulation/guidelines/bd/guidelines-on-artificial-intelligence-risk-management-for-financial-institutions/guidelines-on-artificial-intelligence-risk-management.pdf) | AI Act high-risk from 2 Dec 2027 |
| Disclosure that an AI agent is acting | No | [Art. 50(1) guidelines](https://www.paulweiss.com/insights/client-memos/eu-finalises-transparency-rules-for-ai-generated-content) (LAW plus non-binding guidance) | Now, in the EU, regardless of risk class |
| Explanation or human review for affected persons | No, this is a person's right | [AI Act 86](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-86); [Colorado SB 189](https://www.hunton.com/privacy-and-cybersecurity-law-blog/colorado-ai-act-amended-and-effective-date-delayed) (LAW) | Annex III from 2 Dec 2027; Colorado from 1 Jan 2027 |
| Reasonable care in a legal dispute | No | [*Moffatt*](https://www.mccarthy.ca/en/insights/blogs/techlex/moffatt-v-air-canada-misrepresentation-ai-chatbot) (CASE); [AB 316](https://www.legal500.com/intelligence/united-states/technology/california-eliminates-the-autonomous-ai-defense-what-ab-316-means-for-ai-deployers) (LAW) | Now |
| Human approval of every action | **Yes, can shrink.** No general text requires it | [AI Act 14(3)](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-14); [MAS 5.9, fn 37](https://www.mas.gov.sg/-/media/mas-media-library/regulation/guidelines/bd/guidelines-on-artificial-intelligence-risk-management-for-financial-institutions/guidelines-on-artificial-intelligence-risk-management.pdf); [FSB](https://www.fsb.org/uploads/P151026-1.pdf) | Lower-risk actions. Exception: two-person check for remote biometric identification, Art. 14(5) |
| Review frequency, sampling depth, test depth | **Yes, can scale**, but by materiality | [MAS 5.23](https://www.mas.gov.sg/-/media/mas-media-library/regulation/guidelines/bd/guidelines-on-artificial-intelligence-risk-management-for-financial-institutions/guidelines-on-artificial-intelligence-risk-management.pdf); [SR 26-2](https://www.federalreserve.gov/supervisionreg/srletters/SR2602a1.pdf) | Must be documented |
| Accuracy thresholds themselves | Stays, and the firm sets it | [Art. 9](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-9), [Art. 15](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-15) | AI Act high-risk from 2 Dec 2027 |

Scope warning: outside the listed sectors and outside AI Act high-risk uses, most of these rows are not specific legal duties today. General liability and contract still apply.

**Retention periods**

| Source | Period |
|---|---|
| [AI Act 19](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-19), [26(6)](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-26) | At least 6 months (logs) |
| [AI Act 18](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-18) | 10 years (technical and QMS documents) |
| [NYCRR 500.6](https://www.law.cornell.edu/regulations/new-york/23-NYCRR-500.6) | At least 5 years (audit trail records) |
| [HIPAA 164.316](https://www.law.cornell.edu/cfr/text/45/164.316) | 6 years (required documentation; it does not state this for logs specifically) |
| [DORA RTS 12](https://springlex.netlify.app/en/packages/dora/rts-rmf-regulation/article-12/) | Entity decides, with stated factors |
| [ISO A.6.2.8](https://www.isms.online/iso-42001/annex-a-controls/a-6-ai-system-life-cycle/a-6-2-8-ai-system-recording-of-event-logs/) | Organisation decides |

**Is any regulator open to reducing controls based on proven performance?**

| Body | Basis for less oversight | Is performance the basis? | Type |
|---|---|---|---|
| [FSB final report](https://www.fsb.org/uploads/P151026-1.pdf) | Firms may progressively increase an agent's external access as they gain confidence. An example practice is triggers that move between forms of oversight based on performance metrics or user requests. High-risk use may warrant layered controls and more intensive oversight. | **Yes, in part. This is the closest text found.** | FORMAL GUIDANCE, non-binding |
| [MAS](https://www.mas.gov.sg/-/media/mas-media-library/regulation/guidelines/bd/guidelines-on-artificial-intelligence-risk-management-for-financial-institutions/guidelines-on-artificial-intelligence-risk-management.pdf) | Basic governance only if poor performance or unavailability is unlikely to cause material harm (2.3). Oversight proportionate to materiality (5.9). Complexity rating can change as understanding improves (4.12(b)). Escalation can use reliability and accuracy conditions (5.9(c)). | Indirect: the test is impact | FORMAL GUIDANCE |
| [AI Act 14(3)](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-14) | Oversight "commensurate with the risks, level of autonomy and context of use" | No | LAW |
| [Draft Art. 6 guidelines](https://www.freshfields.com/en/our-thinking/blogs/technology-quotient/eu-ai-act-unpacked-32-draft-commission-guidelines-on-high-risk-ai-implicati-102n1bn) | Filter depends on task. Human involvement alone does not change the class. | No | DRAFT |
| [SR 26-2](https://www.federalreserve.gov/supervisionreg/srletters/SR2602a1.pdf) | Rigor follows materiality, size and complexity. Immaterial models may only need identification and monitoring. Agents are excluded. | No | FORMAL GUIDANCE |
| [FDA PCCP, per CRS](https://www.congress.gov/crs_external_products/IF/PDF/IF13245/IF13245.1.pdf) | Pre-agreed changes need no new submission, under performance requirements | Partly, but concerns changes to the product, not oversight of actions | LAW plus guidance |
| [IMDA](https://www.imda.gov.sg/-/media/imda/files/about/emerging-tech-and-research/artificial-intelligence/mgf-for-agentic-ai.pdf) | Four levels of human involvement, gradual rollout. A case study has one company reassessing tier limits as safeguards are validated. | Partly; the example is one company's practice | VOLUNTARY |
| [FCA Mills Review, per Freeths](https://www.freeths.co.uk/insights-events/legal-articles/2026/fca-s-mills-review-agentic-ai-consumer-duty-and-the-future-of-financial-services/) | Describes a range from AI as a tool to AI acting within agreed boundaries; I found no loosening of oversight | No | Recommendations, secondary |
| [CSA Agentic Trust Framework](https://cloudsecurityalliance.org/blog/2026/02/02/the-agentic-trust-framework-zero-trust-governance-for-ai-agents) | Promotion through Intern, Junior, Senior, Principal, using gates that include accuracy above 95% and 99%, zero critical incidents and governance sign-off. Automatic demotion for Principal after a significant incident. Its time thresholds are inconsistent within the source. | **Yes, explicit**, but not a regulator | VOLUNTARY, by one author |

**Calendar through 2030**

| Date | Event |
|---|---|
| 2 Dec 2026 | AI Act Art. 50(2) grace period ends; new Art. 5 bans |
| 9 Dec 2026 | EU Product Liability Directive transposition deadline |
| 1 Jan 2027 | Colorado SB 189 effective |
| July 2027 | HIPAA Security Rule final action, projected only |
| 2 Aug 2027 | EU national sandboxes |
| 7 Oct 2027 | MAS Sections 3 and 4 |
| 2 Dec 2027 | AI Act Annex III high-risk duties |
| 2 Aug 2028 | AI Act Annex I high-risk duties |
| 7 Oct 2028 | MAS Sections 5 and 6 |
| 2 Aug 2030 | AI Act high-risk systems of public authorities |

Sources are the dated findings in the sections above.

### Inferences
- Do the frameworks require controls outside the model? In binding text this is functional, not architectural. A law asks for logs, limits, a stop function and a named owner. In practice these must sit in the surrounding system, because a model cannot give independent proof of its own conduct, cannot grant itself or remove its own access rights, and cannot be the named owner. Only the FSB and IMDA texts say this directly, and neither binds.
- Near-perfect performance measured at one time does not cover later changes. The FSB notes that capabilities change with new tools and prompts, MAS names compromised agents, and third-party models get updated. So the logs and monitoring are what show that performance still holds. This also means the evidence needed to reduce human review is produced by the same controls that stay.
- A defensible argument to a regulator would be: move lower-risk actions from per-action approval to exception-based review; define the triggers in advance; record the metrics; keep the ability to move back; keep all logs and access limits. This matches FSB and MAS text, but I found no regulator that has approved such an argument for agents.
- High accuracy may help in one area: it supports "reasonable care" and an acceptable residual risk under Art. 9(5). It reduces how often controls fire. It does not replace them.

### Gaps
- I found no enforcement action or supervisory finding that accepted or rejected reduced oversight based on agent performance.
- I did not find a regulator's stated accuracy threshold for agents. CSA's percentages come from a voluntary framework and have no regulatory status.
- How "human-in-command" will be treated in examinations is unknown. National regulators may or may not adopt the FSB practices.

## Security guidance on agents: OWASP, CSA and government guidance (guidance, not law)

### Takeaway
This guidance is the most specific about agents and consistently asks for least privilege, identity, monitoring and stop mechanisms. None of it is law. Auditors and regulators may still use it as a reference for what reasonable security looks like; that is my expectation.

### Cited Findings
- [VOLUNTARY] OWASP Top 10 for Agentic Applications, December 2025: ASI01 Agent Goal Hijack, ASI02 Tool Misuse and Exploitation, ASI03 Identity and Privilege Abuse, ASI04 Agentic Supply Chain Vulnerabilities, through ASI10 Rogue Agents, with Memory Poisoning and Cascading Failures also listed — [Giskard, secondary](https://www.giskard.ai/knowledge/owasp-top-10-for-agentic-application-2026); [Auth0, secondary](https://auth0.com/blog/owasp-top-10-agentic-applications-lessons/).
- [FORMAL GUIDANCE, not law] "Careful adoption of agentic AI services", from ASD's ACSC, CISA, NSA, the Canadian Centre for Cyber Security, NCSC-NZ and NCSC-UK. The PDF path is dated 30 April 2026; a news report implies 1 May. It advises starting with clearly defined low-risk tasks, assuming agents may behave unexpectedly until practices mature, and building products that stop and escalate to humans in uncertain cases. It treats accountability, monitoring and human oversight as prerequisites — [The Register, secondary](https://www.theregister.com/security/2026/05/04/five-eyes-warn-agentic-ai-is-too-dangerous-for-rapid-rollout/5229103). Official pages: [cyber.gov.au](https://www.cyber.gov.au/business-government/secure-design/artificial-intelligence/careful-adoption-of-agentic-ai-services); [NSA release](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/Article/4475134/nsa-joins-the-asds-acsc-and-others-to-release-guidance-on-agentic-artificial-in/).
- [VOLUNTARY] CSA MAESTRO (February 2025): a seven-layer threat modelling method for agentic AI — [CSO Online, secondary](https://www.csoonline.com/article/4072341/introducing-maestro-a-framework-for-securing-generative-and-agentic-ai.html).
- [VOLUNTARY] Agentic Trust Framework (2 Feb 2026, posted on the CSA blog, by Josh Woodruff of MassiveScale.AI): identity, behaviour, data governance, segmentation and incident response; autonomy levels are earned through gates — [CSA](https://cloudsecurityalliance.org/blog/2026/02/02/the-agentic-trust-framework-zero-trust-governance-for-ai-agents).
- [FORMAL GUIDANCE] Overlap with financial guidance: the FSB asks for zero-trust principles, explicit identity verification, least privilege and action-level authorisation for agents — [FSB final report](https://www.fsb.org/uploads/P151026-1.pdf).

### Inferences
- These documents treat prompt injection and privilege abuse as reasons for controls outside the model. A model that is near-perfect on policy can still be hijacked or given too much access. Security controls therefore do not depend on the model's policy accuracy.
- ASD's companion advisory on agentic AI harnesses appears to focus on the harness as the part organisations can most directly govern. This matches the question directly, but I saw only a search excerpt ([cyber.gov.au](https://www.cyber.gov.au/advisory/agentic-ai-harnesses)).

### Gaps
- The Five Eyes PDF and the harness advisory could not be opened (blocked or timed out). Their detailed recommendations on logging and identity are not confirmed here.
- I read OWASP's list only through secondary sites. A reported count of about 100 Five Eyes recommendations is not verified.
- I did not find guidance from ENISA specific to agents; I did not search for it separately.
