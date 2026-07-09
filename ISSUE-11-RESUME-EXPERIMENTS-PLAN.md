# Issue #11: Resume, Named Experiments, Background Execution for cuga-eval

## Context

Long-running evaluations (m3/appworld/bpo/oak) run start-to-finish today with no way to recover
from a crash except a full re-run. The current branch `fix/eval-harness-stale-report-guard`
(commits `af018fb`, `e72bec5` — PR #98, reviewed and CodeRabbit-addressed, not yet merged)
hardened the *end* of a run: a `finally:` block always saves whatever completed, a
`RUN_MARKER`/`-newer` check refuses to bundle stale results from a prior run, and a partial run
force-exits with code 2 instead of being silently reported as a clean pass. That's a durability
floor, not resumability.

Issue #11 asks for: resuming an interrupted run from where it left off, naming bundles as
experiments, running/stopping/restarting in the background, checking status at
task/run/combo granularity, and replaying a bundle's exact configuration. This plan implements
that as five independently-mergeable milestones (M1–M5), building directly on top of #98's
guarantees rather than replacing them.

## Branching & rebase workflow (do this, in this order)

This work starts from `main` **today**, before #96/#98 are merged, and gets rebased onto `main`
**after** they merge (expected tomorrow or the next day). Two clean phases, no ambiguity:

**Phase A — now, on your laptop:**
```
git fetch origin main
git checkout -b feat/issue-11-resume-experiments origin/main
```
All of M1–M5 below get implemented and committed on this branch, starting from plain `main` —
i.e. `main` as it exists *before* #96/#98 land. That means the `RUN_MARKER` stale-guard, the
`finally:`-save hardening, and everything else currently living only on
`fix/eval-harness-stale-report-guard` (PR #98) is genuinely **not present** on this new branch at
first. M1's design (converging `finally:`/`KeyboardInterrupt` handling onto
`finalize_merged_results`, threading `bundle_dir` around the existing guard) is written as if that
code already exists, because it's expected to land via the Phase B rebase — **don't hand-copy or
re-implement #98's guard logic onto this branch now**; that would just create a second copy to
reconcile later. Implement M1's *new* pieces (`incremental_results.py`, the `bundle_dir` threading,
the Langfuse retry fix, etc.) as if #98's guard code is already underneath them; the rebase in
Phase B is what actually puts it there.

**Phase B — after #96 and #98 both merge to `main` (tomorrow/next day):**
```
git fetch origin main
git rebase origin/main
# resolve any conflicts (see below), then:
git rebase --continue
```
What to expect when resolving:
- `#98`'s changes live in `benchmarks/{bpo,appworld,oak_health_insurance}/eval.sh` and
  `benchmarks/helpers/sdk_eval_helpers.py`/`bundle.py` — files this plan also touches. Conflicts
  here are expected and are the point of doing it this way: git will show you exactly where #98's
  guard logic and this plan's new code both touch the same lines, so you resolve once, cleanly,
  instead of guessing blind today.
- `#96`'s contents are unknown from this checkout (no remote access here to inspect it) — if it
  also touches `bundle.py`, `sdk_eval_helpers.py`, `common.sh`, or any benchmark's
  `eval.sh`/`compare.sh`, expect conflicts there too; resolve at rebase time.
- If either PR merged as a **squash commit** on GitHub rather than a regular merge, `git rebase`
  can still work fine here since this branch never contained #96/#98's commits to begin with (unlike
  the earlier concern about rebasing *on top of* the local `fix/eval-harness-stale-report-guard`
  branch) — there's nothing to "already applied" against, so a normal rebase is the right call, no
  merge-vs-rebase caveat needed for this branch.
- After a clean rebase, re-run the M1 verification steps (see Verification section) once more to
  confirm the merged-in #98 guard logic and this plan's new code work together correctly.

## Verified architecture

- **Identical loop shape in bpo/oak/appworld**: each evaluator's `evaluate_all()` builds
  `self.results = []`, loops (`for i, task/tid in enumerate(...)`) appending one result dict per
  task, and `self.results` is written to disk exactly once — not inside `evaluate_all()`, but by
  `save_results()`, called from a `finally:` block in each file's `main()`.
  (`benchmarks/bpo/eval_bench_sdk.py`: `__init__` L72, `evaluate_all` L170, loop L226-236,
  `save_results` L243-247, `finally`-invocation in `main()` L305-316. `benchmarks/oak_health_insurance/eval_bench_sdk.py`
  L189-206 mirrors this. `benchmarks/appworld/eval_appworld_sdk.py` L530-560 mirrors this, including
  a comment at L531-533 already documenting the "total vs len(results) detects partial run" logic
  that #98 hardened.)
- **Single choke point for per-task result finalization**: `evaluate_task_with_langfuse()` in
  `benchmarks/helpers/sdk_eval_helpers.py` (L809-1299, `async def`). The success path builds
  `result` at L1037, attaches `trace_id`/`total_tokens`/`total_cost`/etc. at L1065-1076 (only if
  Langfuse metrics were captured), calls `tracker_callback(result, ...)` at L1270-1271, then
  `return result` at L1273. The **exception path** (L1275-1299) builds a distinct `error_result`
  dict with `error: str(e)` — it does **not** get trace/token metadata — calls
  `tracker_callback(error_result, ...)` at L1296-1297, then `return error_result` at L1299. Both
  paths are the right place to add an incremental-write hook; a design decision follows below.
  `evaluate_task_with_langfuse_react()` (L1954) is a **thin wrapper that delegates** to the above,
  not a separate implementation — so there is genuinely only one place to patch, not two.
- **`save_evaluation_results()`** (`sdk_eval_helpers.py` L1862-1939): signature
  `(results: List[dict], output_dir: Path, prefix: str = "evaluation", run_timestamp: Optional[str] = None) -> Path`,
  produces `{"metrics": {...}, "results": [...]}`. `benchmarks/helpers/compare_report.py`'s
  `_parse_sdk_results()` (L100-157) depends on exactly this shape; all 4 evaluators (via
  `save_results()`) use this function, including appworld. (`compare_report.py` also has a
  `_parse_appworld_results()` reading a `task_results` dict shape at L160-197 — this is dead-code
  compat for some other/older appworld output format, not what `eval_appworld_sdk.py` produces
  today; ignore it, don't design against it.)
- **m3 has three loop shapes**, not two — this matters for where resume-filtering has to live:
  - Sequential single/multi-turn loops in `evaluate_all()` (`benchmarks/m3/eval_m3.py` L855-1011),
    same append-then-save-once shape as the other benchmarks.
  - Batched config-mode: `evaluate_tasks_in_batches()` (L2195-2254) runs `asyncio.gather` over a
    list of `(service_name, coroutine)` tuples built at L2638-2661. **Each coroutine is
    `evaluate_single_task()` (L1259+), and it evaluates ALL of that task's domains sequentially
    internally**, looping over `domains` and returning a `List[dict]` per task — so a single
    outer "task_evaluations" entry is not one benchmark task, it's a whole capability's worth of
    per-domain results. Consequence: resume-skip filtering by `(task_id, domain)` **cannot** be
    done by dropping entries from `task_evaluations` before the `gather` (too coarse — a service
    is only skippable if *all* its domains are already done); it must filter inside
    `evaluate_single_task()`'s domain loop, skipping already-completed `(task_id, domain)` pairs
    one at a time. `_finalize_and_save_results()` (L2260+) does the final save for this mode.
  - The `KeyboardInterrupt`/`asyncio.CancelledError` handler (L2763-2774, plus a generic exception
    handler at L2780-2791) saves whatever's in `all_results` to a `*_partial`-prefixed file.
  - The collision guard at L2143-2152 is unrelated to resume — it detects duplicate domain names
    across *expanded* services in the registry config and hard-fails config generation. It's not
    "collision-avoidance logic for partial-file naming" as originally assumed; the plan's own
    `(task_id, domain)` composite key for partial-file naming is a new, independent piece of logic.
- **Bundle assembly** (`benchmarks/helpers/bundle.py`): `assemble_bundle()` (L447-557) and
  `assemble_compare_bundle()` (L560-747) are invoked post-hoc, after the Python evaluator process
  exits, via `python -m benchmarks.helpers.bundle assemble[-compare]` from each benchmark's
  `eval.sh`/`compare.sh`. `_download_langfuse_traces()` (L287-403) sanitizes task IDs via
  `task_name.replace("/", "_").replace("\\", "_")` at L354 — reuse this exact sanitization for
  partial-result filenames. `metadata.json` today has no experiment-identity concept — bundle
  naming is purely `{timestamp}_{model_profile}` (L476) or `{timestamp}_compare_{suffix}` (L603).
  Existing fields: `bundle_version`, `created_at`, `benchmark`, `eval_repo`, `run`,
  `runtime_config`, `model`, `cuga`, `policies`, `environment`, `ground_truth` (L523-554) — new
  fields must be additive.
- **No atomic-write helper exists anywhere in `benchmarks/helpers/`** (checked: no `os.rename`,
  `NamedTemporaryFile`, or similar) — `atomic_write_json` is genuinely new, not a duplicate.
- **Shell flag flow**: `scripts/eval.sh` calls `parse_common_args` (`benchmarks/helpers/common.sh`
  L139-224), which recognizes `--benchmark`, `--runs`, `--output`, `--dry-run`, `--verbose`,
  `--model-profile`, `--model-name`, `--openai-base-url`, `--agent`/`--agents`/`--compare-agents`,
  `--no-bundle`, `--bundle-zip`, `--dotenv`, `--help`, and forwards everything else via
  `FORWARDED_ARGS`; `scripts/eval.sh` L104 does `exec bash "$BENCHMARK_EVAL" "${FORWARDED_ARGS[@]}"`
  into each benchmark's own `eval.sh` (e.g. `benchmarks/bpo/eval.sh` L118-178), which re-parses and
  calls `uv run python -m benchmarks.{bench}.eval_{bench}`. The `--model-profile` → `--models`
  propagation added in PR #94 has a working regression-test pattern to copy:
  `benchmarks/helpers/tests/test_model_config.sh` L249-277 (stub benchmark dir, `--dry-run`,
  `assert_contains`/`assert_not_contains` against `DISPATCH_ARGS`).
- **`RUN_MARKER` stale-guard (#98) is present in all three single-run `eval.sh`s** today
  (`benchmarks/bpo/eval.sh` L272/288, `benchmarks/appworld/eval.sh` L150/172,
  `benchmarks/oak_health_insurance/eval.sh` L174/185) via `mktemp` + `find -newer`, with a hard
  refuse-to-bundle-if-no-fresh-file check (e.g. bpo L300-304). **No test covers this logic** (no
  `docs/manual-verification.md` exists — that file is not present in the repo at all; this was
  simply never tested). M1's shell-test additions should close this gap alongside testing the new
  resume flags, using the same `test_model_config.sh` pattern.
- **`m3/compare.sh`** already tracks `total_runs`, `runs_done`, `TOTAL_PLANNED` (L207-211, updated
  L515-530, printed L586) but only to stdout — nothing is persisted to a machine-readable file, so
  cross-process (`--status` after `--background`) visibility genuinely doesn't exist yet.
- **Auto-continue (Slice F)**: `cuga` is an editable path dependency on a **sibling repo**
  (`pyproject.toml` L43: `cuga = { path = "../cuga-agent", editable = true }`), not vendored here —
  so `cuga_lite_nl_auto_continue`'s exact definition/default can't be directly verified from this
  checkout. What *is* verifiable here: zero references to any auto-continue setting or flag
  anywhere in `benchmarks/`, confirming today's eval harness has no coupling to it at all. The
  obligation for Slice F is simply: none of the new code introduces a config override that reaches
  into cuga-agent's settings — verify by grep for `auto_continue` returning empty after each
  milestone.

## Design decision: failed tasks are retried on resume

The exception path in `evaluate_task_with_langfuse` returns an `error_result` (has `error: str(e)`,
`success: False`) — distinct from a success-path `result` (`error: None`). **Decision: failed
tasks are retried on `--resume`, not skipped.** A task that raised may have failed transiently
(timeout, rate limit, flaky tool call), so `--resume` should re-attempt anything that didn't
succeed, not just anything the process never reached.

Implementation consequence for `incremental_results.py`: both outcomes are still written to
`results/partial/<sanitized_task_id>.json` (one file per task, so a retry's write simply overwrites
the prior attempt's file — no extra bookkeeping needed for "latest attempt wins"). But the two
read paths must diverge:
- `load_completed_task_ids(bundle_dir) -> set[str]` — used to build the skip-set passed into
  `evaluate_all()` — only counts a task as "completed" (and thus skippable) when its partial file's
  `error is None`. Files with `error is not None` are deliberately excluded, so `evaluate_all()`
  will re-run them.
- `load_all_partial_results(bundle_dir) -> list[dict]` — used for final merge/pre-seeding — loads
  every partial file regardless of success/failure, since `finalize_merged_results()` should report
  whatever the current state on disk is (including a task that's failed on every attempt so far).

This means a task that fails repeatedly across multiple `--resume` invocations is retried every
time, with no backoff or retry cap — acceptable for now since these are already long-running,
manually-invoked evaluations; a `--max-retries`/retry-cap flag is a natural follow-up if it becomes
a problem in practice, but is out of scope here.

## New shared Python modules (`benchmarks/helpers/`)

**`incremental_results.py`** — atomic per-task persistence (Slice A), pure stdlib, no `cuga`
dependency, fully unit-testable in isolation:
- `atomic_write_json(path, data)` — write to a temp file in the same directory, `os.rename` over
  the target (POSIX-atomic).
- `write_task_result(bundle_dir, task_id, result, *, domain=None) -> Path` — writes
  `results/partial/<sanitized_task_id>.json`, or `<sanitized_task_id>__<domain>.json` when
  `domain` is given (m3 config-mode only). Sanitize with the exact `.replace("/", "_").replace("\\", "_")`
  pattern already used in `bundle.py::_download_langfuse_traces` (L354). One file per task —
  different tasks touch different files, so concurrent writes from `asyncio.gather` batches need
  no locking.
- `write_task_result_async(...)` — `asyncio.to_thread` wrapper. This is the actual call site
  inserted into `evaluate_task_with_langfuse`, at both the success return point (~L1273) and the
  exception return point (~L1299), so persistence never blocks the eval loop. Both outcomes are
  written, but (per the retry decision below) only success is treated as "done" for resume.
- `load_completed_task_ids(bundle_dir) -> set[str]` — lists `results/partial/*.json` **whose
  `error` field is `None`** — a task that errored is deliberately excluded so it gets re-attempted
  on resume. Atomic rename means a crash mid-write can never leave a corrupt final-named file.
- `load_all_partial_results(bundle_dir) -> list[dict]` — loads every partial file regardless of
  success/failure, for final merge/reporting purposes.
- `finalize_merged_results(bundle_dir, prefix, run_timestamp=None) -> Path` — loads all partials,
  calls the existing `save_evaluation_results()` to produce the same `{"metrics":..., "results":[...]}`
  shape `compare_report.py`/`bundle.py` already depend on. Both the normal end-of-run save and the
  `finally:`/`KeyboardInterrupt` crash paths call this — unifying them so the crash guarantee
  becomes strictly stronger (merges from disk, not a possibly-incomplete in-memory list).

**`experiment.py`** — experiment identity + resume resolution (Slice B):
- `resolve_experiment_bundle_dir(benchmark_name, experiment_name, compare=False) -> Path` — named
  bundles live at `evaluation_bundles/<name>` (no timestamp prefix); reject a pure-timestamp-shaped
  name so it can never collide with legacy auto-named dirs.
- `write_last_experiment_pointer` / `resolve_last_experiment` — atomically-written
  `.last_experiment` file, written at the start of every run (named or not), so bare `--resume`
  always resolves to something.
- `new_or_resume_bundle_dir(benchmark_name, *, experiment, resume, resume_experiment, compare=False)
  -> tuple[Path, bool]` — single entry point encoding precedence: `--resume-experiment` must
  already exist; bare `--resume` resolves the pointer; `--experiment <new name>` creates fresh;
  `--experiment <existing name>` without a resume flag is a hard error (mirrors #98's
  refuse-to-silently-misreport spirit); no flags → legacy timestamp-named bundle, unchanged.

**`run_state.py`** — lifecycle state (Slice C):
- `RunState`: `status` (running/completed/stopped/failed), `pid`, `host`, `started_at`,
  `updated_at`, `completed_tasks`, `total_tasks`, `exit_code`.
- `write_run_state`/`read_run_state` via `atomic_write_json`; written at process start, updated
  periodically and at exit, stored at bundle root (`run_state.json`) independent of
  `results/partial/`.
- `is_process_alive(pid, host)` — `os.kill(pid, 0)` guarded by hostname match; returns `False`
  (never raises) on lookup/permission errors so `--status` degrades to "stopped (stale)" instead of
  crashing.

**`replay.py`** — `cli_args_from_metadata(metadata) -> list[str]`, best-effort reconstruction of an
`eval.sh`/`compare.sh` argv from `metadata.json`'s `run`/`runtime_config`/`model` fields; exposed as
a `replay` subcommand on `bundle.py`'s existing CLI.

**`compare_state.py`** — compare-level progress (Slice C/M4): `mark_combo_run_started/completed`,
`load_compare_progress(bundle_dir) -> dict`, `already_completed_combo_runs(bundle_dir) -> set[tuple[str, int]]`.

## Bundle repair & retry (new, in response to review feedback)

Two related gaps exist today, both surfaced by `scripts/create_eval_bundle.py` — the existing
"rebuild a bundle without re-running the eval" tool (its own docstring: "Use when eval.sh finished
successfully but bundle creation failed, or to re-assemble a bundle with different options"). Under
the bundle-as-workspace model these gaps get worse unless addressed directly, since a partial bundle
is now the normal mid-run state, not just a failure recovery case:

1. **Langfuse trace download has no skip-existing behavior at all today**, and **429s are
   misclassified as permanent failures**. In `bundle.py::_download_langfuse_traces` (L287-403):
   the per-trace loop never checks `out_file.exists()` before calling `urlopen` — every invocation
   re-downloads every trace from scratch. Worse, the HTTPError branch (L368-380) only retries on
   `404` ("not yet available"); everything else, including `429` (rate limit — called out
   explicitly as a frequent real-world failure when multiple people share one Langfuse key), falls
   into the "4xx/5xx other than 404 are typically permanent... don't retry" branch and gives up
   after one attempt. Fix as part of M1:
   - Add an upfront `if out_file.exists(): continue` (or an explicit `skip_existing: bool`
     parameter, default `True` for the new call sites, `False` preserved for any existing
     callers that expect a full re-fetch) before the attempt loop.
   - Reclassify `429` alongside the existing transient-network retry branch (L381), with backoff;
     honor a `Retry-After` response header when present instead of the flat `retry_delay`.
   - Since `out_file` is now conditionally skipped rather than always attempted, a bundle that
     failed to fetch some traces (429s, or a 500 on an oversized trace) is left with a
     `results/langfuse_traces/` directory that's simply missing those files — no sentinel needed to
     distinguish "not attempted" from "attempted and failed," since both cases just mean "the file
     isn't there yet, try again."
2. **No way to retry just the trace download or just the report against an existing bundle
   directory** — today, recovering from a failed/partial Langfuse fetch means re-running
   `create_eval_bundle.py`, which resynthesizes the whole bundle from flat result files under
   `benchmarks/<bench>/results/`, not from an existing (possibly named/workspace) bundle directory.
   Add two new `bundle.py` CLI subcommands, both operating directly on `--bundle-dir <path>` and
   idempotent by construction (since they only add missing files, per the skip-existing fix above):
   - `retry-langfuse --bundle-dir <path>` — re-invokes `_download_langfuse_traces` against the
     bundle's current merged `results/*.json`, letting the skip-existing logic naturally fetch only
     what's still missing.
   - `regenerate-report --bundle-dir <path>` — re-runs the existing
     `benchmarks.helpers.compare_report eval` logic (already used by
     `create_eval_bundle.py::_generate_report`, L91-108) against the bundle's current merged
     results, overwriting `report.md` in place. No new report logic — just a convenience wrapper
     that locates the right file inside a bundle dir instead of requiring an explicit
     `--result-file`.
   Update `scripts/create_eval_bundle.py` to add a `--bundle-dir <path>` mode as an alternative to
   its current `--latest`/`--result-file` flow, dispatching to these two new subcommands — this
   makes it the single entry point for both "build a bundle from scratch" (legacy, unchanged) and
   "repair/refresh part of an existing bundle" (new).

## Bundle changes (`benchmarks/helpers/bundle.py`)

Add `create_workspace_bundle(...)` — creates the named bundle dir + `results/partial/` upfront,
before the evaluator runs, writes an initial `metadata.json` marked `"status": "in_progress"`.
Add `finalize_workspace_bundle(...)` — idempotent (safe to re-run after `--resume`), handles what
can't happen incrementally: `report.md` generation, Langfuse trace download with a new
`skip_existing=True` mode (resume only fetches new traces), flips `metadata.json`'s status to
completed/partial. Keep `assemble_bundle`/`assemble_compare_bundle` unchanged for the legacy
no-experiment path — M1 adds the new path as opt-in; M2 makes it default without deleting the old
one. `metadata.json` gains only additive fields: `experiment_name`, `status`, `resume_history`.

## Per-evaluator changes (bpo, oak_health_insurance, appworld, m3)

In `sdk_eval_helpers.py::evaluate_task_with_langfuse`, add an optional `bundle_dir: Path | None = None`
param (and thread it through the `evaluate_task_with_langfuse_react` wrapper, which just forwards
kwargs). Right before both `return result` (~L1273) and `return error_result` (~L1299), call
`await write_task_result_async(bundle_dir, task_name, result_or_error_result)` when `bundle_dir` is
set. ~10-line change covers bpo/oak/appworld and most of m3's paths simultaneously.
`setup_agent_with_tools()` is untouched — no new callback wiring, Slice E stays deferred.

Each of the three simple evaluators (bpo/oak/appworld) needs mechanically identical edits:
constructor accepts `bundle_dir`/`resume_completed_ids` (the latter built from
`load_completed_task_ids()`, i.e. success-only); `evaluate_all()`'s loop skips task IDs already in
`resume_completed_ids` (so previously-failed tasks are naturally re-attempted, since they were
excluded from that set) and pre-seeds `self.results` from `load_all_partial_results()` — which
includes prior failures too, so if a retry is skipped this run (e.g. only some tasks are targeted),
the merged output still reports the last known state for every task; `bundle_dir` threaded to the
`evaluate_task_with_langfuse` call site; `save_results()` becomes a thin call to
`finalize_merged_results()`.

m3 needs the same treatment but split across its three loop shapes:
- Sequential mode (`evaluate_all()` L855-1011): same treatment as the simple evaluators.
- Config/batched mode: resume filtering must happen **inside `evaluate_single_task()`'s domain
  loop** (per the verified architecture above), not at the `task_evaluations` list level — pass
  `resume_completed_ids` (as a set of `(task_id, domain)` tuples) into `evaluate_single_task()` and
  skip already-done domains before evaluating them. Partial-result filenames use the
  `<task_id>__<domain>.json` composite to avoid cross-capability collisions.
  `_finalize_and_save_results()` switches to `finalize_merged_results(bundle_dir, prefix=...)`.
- `KeyboardInterrupt`/exception handlers (L2763-2791) switch to the same
  `finalize_merged_results()` call — this is what unifies m3's existing partial-save behavior with
  the new disk-backed one.

New CLI args on each evaluator's `main()`: `--bundle-dir <path>` and `--resume-task-ids <id> [...]`.
The evaluator never re-derives bundle-naming/resume-resolution logic itself — `experiment.py` does
that once at the shell layer and passes a concrete path + pre-computed skip-set, keeping the
evaluators trivially testable in isolation.

## Shell-level changes

New flags `--experiment`, `--resume`, `--resume-experiment`, `--background`, `--stop`, `--restart`,
`--status` added at every layer: `common.sh::parse_common_args`, `scripts/eval.sh`/`scripts/compare.sh`
forwarding (same `FORWARDED_ARGS` mechanism used for `--model-profile`), and each benchmark's own
`eval.sh`/`compare.sh` parsing loop.

`--status`/`--stop` short-circuit near the top of `eval.sh`, before server startup, dispatching to
thin `status_cli`/`stop_cli` Python entry points over `run_state.py` (text output only — no
dashboard, per the explicit Slice D deferral). `--background` re-execs the same script with
`--background` stripped, backgrounded via `nohup ... & disown`, PID recorded in `run_state.json`
(not a separate shell PID file) so `--status`/`--stop` have one source of truth regardless of how
the run started. `--restart` = `--stop` then re-invoke with `--resume-experiment <name> --background`.

The `RUN_MARKER`/`-newer` stale-guard needs **no changes** — it already only tests "is there a file
newer than this run's start marker," which correctly ignores older partial files left by a
previously-resumed-from process without any special-casing.

## compare.sh-level resume/status (M4)

Before the config/run loop starts, resolve the compare-bundle dir via `experiment.py` (compare
mode). Inside the loop, before invoking `eval.sh` for a `(config, run)` pair: skip if
`already_completed_combo_runs()` says done; if partially done, invoke with `--resume-experiment`
instead of a bare call. After each invocation, update `compare_state.json`. `compare.sh --status`
prints `load_compare_progress()`'s formatted string using the loop's existing counters (L207-211,
515-530) plus the persisted state — needed for cross-process visibility when backgrounded.

## PR #98 guarantee preservation

| Guarantee | Disposition |
|---|---|
| `finally:` save on crash | Strengthened — merges from on-disk partials, not the in-memory list, so it survives races that could lose a just-completed task under `asyncio.gather`. Legacy (no `--experiment`) path is byte-for-byte unchanged. |
| `RUN_MARKER`/`-newer` stale-guard | Unchanged, still correct against the upfront-created bundle dir. |
| Refuse-to-bundle-stale | Unchanged. |
| Partial-run exit codes | Unchanged mechanism; now correctly accounts for the whole resumed experiment (via pre-seeded `self.results`) rather than just the current process's task slice. |

## Backward compatibility

No new flags used → `experiment.py` returns the existing legacy timestamped bundle,
`bundle_dir`/`resume_task_ids` aren't passed to the evaluator, behavior is identical to today.
`--no-bundle` skips workspace creation entirely; `--experiment` + `--no-bundle` is a documented
no-op with a warning. `--bundle-zip`/`--model-profile` unaffected. Unnamed runs are still resumable
once via bare `--resume`, since `.last_experiment` is written for every run regardless of naming.

## Milestones (each independently mergeable, implemented in this order)

0. **Now (Phase A)**: `git checkout -b feat/issue-11-resume-experiments origin/main`, then implement
   M1 on top of it. **Later, after #96/#98 merge (Phase B)**: `git rebase origin/main` and resolve
   conflicts. See "Branching & rebase workflow" above for exact commands and what to expect.
1. **M1 — Incremental persistence + bundle-as-workspace foundation.** `incremental_results.py`,
   `bundle.py`'s workspace functions, the `sdk_eval_helpers.py` hook (both return points), the
   success-only skip-set / retry-on-failure split applied, per-evaluator `bundle_dir` threading
   across all 4 benchmarks (including m3's per-domain resume filtering inside `evaluate_single_task`),
   `finally:`/`KeyboardInterrupt` convergence on `finalize_merged_results`, and the Langfuse
   skip-existing/429-retry fix plus the two new `bundle.py retry-langfuse`/`regenerate-report`
   subcommands and `create_eval_bundle.py --bundle-dir` mode. No `--experiment`/`--resume` CLI
   surface yet — internal plumbing only. Verify: kill mid-run, confirm partial files, confirm
   bundle layout unchanged from a user's perspective. Also add the shell test that's been missing
   for #98's `RUN_MARKER` guard itself (using `test_model_config.sh`'s pattern).
2. **M2 — `--experiment`/`--resume`/`--resume-experiment`.** `experiment.py`, `.last_experiment`,
   shell flag threading across all 4 benchmarks + `scripts/eval.sh`, additive `metadata.json` fields.
3. **M3 — `--background`/`--stop`/`--restart`/`--status` lifecycle.** `run_state.py`,
   `status_cli`/`stop_cli`, `nohup`/`disown`/`SIGTERM`-escalation shell wiring, all 4 benchmarks.
4. **M4 — compare.sh-level combo/run status and resume.** `compare_state.py`, wired into all 4
   benchmarks' `compare.sh` loops (m3's is richest, already has the counters to build on).
5. **M5 — metadata replay.** `replay.py`, `bundle.py` CLI `replay` subcommand. Lowest risk, can
   land independently of M3/M4 if convenient.

Slice F (auto-continue non-regression) is a standing constraint checked at the end of each
milestone (`grep -r auto_continue benchmarks/` stays empty), not a separate milestone.

## Critical files

- `benchmarks/helpers/sdk_eval_helpers.py` — hook point: `evaluate_task_with_langfuse` (both
  return points), `evaluate_task_with_langfuse_react`, `save_evaluation_results`.
- `benchmarks/helpers/bundle.py` — gains workspace functions; `_download_langfuse_traces` for the
  sanitization pattern to reuse.
- `benchmarks/helpers/common.sh` — flag parsing, `find_latest_trajectory`'s portable-stat idiom.
- `benchmarks/m3/eval_m3.py` — three loop shapes; `evaluate_single_task` (L1259) is where m3's
  per-domain resume filtering must live.
- `benchmarks/m3/compare.sh` — richest multi-run/multi-config loop, existing counters at L207-211/515-530.
- `benchmarks/bpo/eval_bench_sdk.py` and `eval.sh` — representative of the bpo/oak/appworld shape.
- `scripts/create_eval_bundle.py` — existing "rebuild bundle without re-running eval" tool, gains
  `--bundle-dir` mode.
- `benchmarks/helpers/tests/test_model_config.sh` — shell-test pattern to extend for new flags and
  for the previously-untested `RUN_MARKER` guard.
- New: `benchmarks/helpers/incremental_results.py`, `experiment.py`, `run_state.py`, `replay.py`,
  `compare_state.py`, and matching `benchmarks/helpers/tests/test_*.py`/`test_*.sh` files.

## Verification

- Per milestone: run each of the 4 benchmarks' `eval.sh` end-to-end (small task subset), confirm
  bundle contents/layout match today's expectations from a user's perspective.
- M1: kill an in-flight run (`SIGKILL`), confirm partial files exist and a subsequent full run
  produces the same final result count as an uninterrupted baseline. Confirm a task forced to fail
  is re-attempted (not skipped) on the next resume, and that its partial file is overwritten with
  the latest attempt's result.
- M1 (bundle repair): simulate a Langfuse `429` (stub server or mock returning 429 for the first N
  requests) and confirm the trace is fetched on retry rather than abandoned after one attempt; run
  `retry-langfuse` a second time against a bundle with some traces already downloaded and confirm
  only the missing ones trigger network calls; run `regenerate-report` against a partial bundle and
  confirm `report.md` reflects the current merged results.
- M2: `--experiment foo`, kill it, `--resume-experiment foo`, confirm only remaining tasks execute
  and the merged bundle has all tasks.
- M3: `--background` returns immediately; `--status` shows running; `--stop` halts it and
  `run_state.json` reflects stopped; `--restart` resumes from the right point.
- M4: a multi-run/multi-config `compare.sh --experiment` interrupted mid-way and resumed — confirm
  already-completed `(config, run)` pairs are skipped and `--status` reports correct counts.
- M5: `replay` against a few real existing bundles under `benchmarks/*/evaluation_bundles/` as
  golden fixtures.
- New pytest suites (`test_incremental_results.py`, `test_experiment.py`, `test_run_state.py`,
  `test_compare_state.py`, `test_resume_integration.py`) plus shell tests extending
  `test_model_config.sh`'s pattern, plus a parametrized cross-benchmark test asserting all 4
  evaluators expose the same new CLI flags (via `argparse` introspection).
