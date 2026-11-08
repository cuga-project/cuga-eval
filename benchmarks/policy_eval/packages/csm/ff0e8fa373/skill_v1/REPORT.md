# CSM policy package

**Structure.** meta.json has a structure profile with two patterns: a short title line, and a "... policies:" lead line. Result: 22 sections and 108 statements. Section ids are the first word of each title (`policy:Assigning:2`). "Knowledge" and "Free" have no title. policy.md is not changed.

**Counts.** 48 must/must_not statements; 0 have no outcome.
- Rules: 73. By type: allowed_values 23, reference_status 12, guidance 10, verify 6, role_permission 5, duty 4, required_args 4, format 3, membership 2, transition, record_condition, grounded_values, id_provenance 1 each. By level: deny 29, block_once 15, remind 17, observe 12.
- Procedures 4 (19 steps), must-nots 0, obligations 11, questions 13, tests 0 (skipped).

**validate:** 0 errors, 4 warnings, all `rule_conflict`. The SLA duties (Service:3, Knowledge:5) need SLA tools that the agent and manager grant lists do not name. A policy question covers this.

**Unclear or conflicting:**
- The default role is admin, but there are also grant lists for agent, manager and customer.
- No source state is given for "canceled".
- No tool argument for sys_updated_on or case notes.
- Escalation reason is described as free text, but the tool takes an enum.
- Does the 30–120 char limit apply to the KB body?
- "Collect necessary inputs" vs "Do not ask for any information".
- Typos: "ing record relationships", "it should as applied".
- The tool accepts contract status "draft"; the policy list does not have it.

**Files seen:** only policy.md, tools.json and the polisys skill/source files. No forbidden file.
