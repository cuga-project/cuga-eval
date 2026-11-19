# Rules for coding agents in cuga-eval

## Benchmark adapters

- An adapter (`benchmarks/policy_eval/harness/adapters/`, `benchmarks/<bench>/`) may add general instructions for its benchmark, such as how to work with spreadsheets or when to read a procedure. Each instruction must hold for every task of that benchmark.
- Put such instructions in a file next to the adapter, behind a flag that is off by default, so a run can measure them.
- No branches on task IDs, and no text from a task, its data or its grader.

## No overfitting to benchmarks

- A fix is a general rule. It must hold for any task of the benchmark and for the same kind of work outside it.
- Never put task IDs, record names, values, or phrases copied from benchmark tasks into prompts, code or rules. Examples in prompts are invented, not taken from tasks.
- A commit message, PR text or code comment may name the task that showed the problem. A prompt or rule may not.
- Do not design a fix from the grader, rubric or expected answer. Read them only to decide whether a failure is a benchmark defect. Never tune to a broken check; report it.
- Sets: develop on a tuning set. A set whose failures you traced becomes a tuning set. Run the final fresh set once, after code and setup are frozen, with at least 3 trials. Report the tuning score next to the held-out score.
- Write the decision rule (metric, threshold, guardrail limit) before the run, not after.

## No-harm rule for the policy system

- The policy system must never make the agent less accurate than the same agent without it, beyond run-to-run noise. This holds for every model and every benchmark, not on average across them.
- Noise is measured on the no-policy arm of the same run: `SE = sqrt(2 * mean per-task variance / trials / tasks)`, the standard error of the difference between two arms with no real effect.
- Check, paired per task: policy − no-policy ≥ −2 × SE for strict pass and for partial score. Guardrail breaks may not rise by more than 2 × their own SE.
- A model or benchmark that fails the check is not supported: the policy system stays off there, and the result is reported as a failure, not averaged away.
- Report the no-harm check next to the gain test in every result table.

## Regex and code checks

- Use code for what is exact: dates and day counts, numbers and sums, IDs, schemas, JSON shape, whether a quote is copied.
- Do not use regex or keyword lists to decide meaning: whether a record is excluded, whether a rule applies, whether a write was requested. A model decides those from quoted evidence.
- Regex is for fixed formats only (ISO dates, ID patterns, extracting JSON). Keep it simple and test it.
- Text matching used as evidence must match whole words and be long enough. A short value (one word or a bare number) needs context: the field name or the record it belongs to.
- When a case is unclear, take the "unknown" path (read more, or say the data is missing). Do not guess with a pattern.

## Tests

- Do not change product text to make a weak test pass. Fix the test so it checks the behavior, for example with a unique marker.
