# Brief for a reviewer of failed checks

This is the text given to each independent reviewer in the run review (`../policy_conformance_review.md`, "Run review").
Replace `DOMAIN`, `DIRECTORY` and `FILES`. A reviewer gets 7 to 10 dossiers written by `build_dossiers.py` and is not
told any earlier verdict.

---

You are auditing failed grader checks of a benchmark (EnterpriseOps-Gym, DOMAIN domain). An AI agent was given a policy
(system prompt), a user request and a set of tools; afterwards SQL checks ran on the database and at least one failed.
For each task, decide for each FAILED check whether the failure is the agent's fault or the check is unfair. Some of
the tasks in your batch have fair checks and some may not; I do not know which, and there is no expected ratio. Do not
assume either answer.

Dossiers (read each fully; each has the complete policy, the request, the logged-in user, tool schemas, all checks with
expected/actual values, every tool call with results, and the agent's final answer) are in directory DIRECTORY. Your
files: FILES

The test for a FAIR check: a careful, competent agent who reads the policy and the request closely and uses the
available tools to look up data could determine the exact value the check expects (possibly by following a policy rule,
a template, a tool default, or data reachable through the tools), and the expected state does not contradict the
policy. A check is UNFAIR (grader defect) if the expected value cannot be determined from policy + request +
tool-reachable data (e.g. it requires guessing exact wording, an unstated field value, an unstated action, or the
identity of the logged-in user when no tool reveals it), or contradicts the policy or the request, or two checks cannot
both pass. Be strict in both directions: do not excuse the agent because the task is hard or the wording is subtle, and
do not blame the agent for failing to guess. Quote the exact policy/request sentence that determines the expected value
when you call a check fair; when you call it unfair, state what you searched for and did not find (search the whole
policy and request for relevant words; check tool schema defaults and enums; check what the tools returned). Each
dossier names the task's seed database SQL dump; grep it when a question turns on what data exists. Do not modify any
files.

One failed check being unfair does not excuse other failed checks: judge every failed check separately; identical
queries under several V-numbers are judged once. If the agent stopped early, refused, or made tool errors, say so, but
still judge whether each failed check's expected value was determinable.

Report, per task: for each failed check (V-number): verdict FAIR / UNFAIR / UNCLEAR, confidence (high/medium/low), and
the evidence (quotes) in 2-4 sentences; one sentence on what the agent did wrong, if anything. Then a task-level line:
"could a perfect agent pass all checks of this task? yes / no / unclear". End with a summary table: task | failed
checks | verdict | perfect agent passes?. Keep the report factual and compact.
