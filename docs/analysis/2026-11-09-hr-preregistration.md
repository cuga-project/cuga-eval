# EnterpriseOps-Gym HR: pre-registration (fresh domain for the CSM findings)

Written 2026-11-09, before any HR run. HR tasks have never been run by any model.

- Set `hr-heldout`: all 80 HR oracle tasks without same-name verifiers (upstream issue 23). One run, 3 trials, Haiku 5.5,
  proxy 8801. Grader: upstream result, with the text-integer fix reported beside it (`numeric_string_fix.py`).
- Arms: A `baseline` (CUGA alone); K `experiments/csm-readback` (read-back turn); W the CSM round-2 arm, if one passes
  the round-2 rule in `2026-11-08-csm-preregistration.md` (decided on CSM tuning runs only, before HR runs). Snapshot:
  `polisys-32100d8` for all arms (A and K contain no round-2 code path).
- Primary claim per arm against A, paired per task: strict difference > 0 with sign-flip p < 0.05 (upstream grader).
  Partial and the fixed-grader numbers are reported with the paired difference, 95% bootstrap CI and p.
- No-harm (AGENTS.md): arm − A ≥ −2 × SE for strict and partial, SE from A. An arm that fails it is not supported on HR.
- The CSM tuning and held-out numbers are reported next to the HR numbers.
