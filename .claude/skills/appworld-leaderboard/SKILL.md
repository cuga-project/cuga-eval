---
name: appworld-leaderboard
description: "Run, resume, retry and pack a CUGA AppWorld leaderboard submission (test_normal + test_challenge) batch-by-batch from eval_config.toml. Use when asked to run the full AppWorld test splits, continue an interrupted AppWorld run, retry failed/uncompleted AppWorld tasks, check AppWorld SGC/TGC, or produce leaderboard.bundle files."
trigger: /appworld-leaderboard
---

# AppWorld leaderboard flow

Everything is driven by keys in `benchmarks/appworld/eval_config.toml`. One cuga-eval
workspace (`benchmarks/appworld/evaluation_bundles/<name>`) and one AppWorld experiment
directory (`benchmarks/appworld/appworld/experiments/outputs/<prefix>_<split>`) per split.
Never create a second workspace for the same prefix+split.

## 0. Prepare batch keys (once per split)

    uv run python -m benchmarks.appworld.leaderboard split-key test_challenge_all --batch-size 100
    uv run python -m benchmarks.appworld.leaderboard split-key test_normal_all --batch-size 100

Writes `test_challenge_all_b1..b5` (100/100/100/100/17) and `test_normal_all_b1..b2` (100/68);
scenarios `_1/_2/_3` of a base always stay in the same batch.

## 1. First batch

    ./benchmarks/appworld/eval.sh --sdk --experiment cuga_v1_chal --leaderboard cuga_v1 \
        --eval-key test_challenge_all_b1 --background

Watch: `./benchmarks/appworld/eval.sh --status --resume-experiment cuga_v1_chal`
→ `cuga_v1_chal  split=test_challenge  completed 100/417  errored 0  score<1: 31  missing 317`
The console/background.log also prints `cuga-viz experiment: <card name>`.

## 2. Inspect in cuga-viz (http://localhost:8988/)

Open the card named in the log. **Uncompleted** = never finished (kill, crash).
**Failed** in cuga-viz only lists score == 0.0 and misses AppWorld's fractional scores —
prefer the harness list:

    uv run python -m benchmarks.appworld.leaderboard retry-key errored   --bundle-dir benchmarks/appworld/evaluation_bundles/cuga_v1_chal --of-key test_challenge_all_b1
    uv run python -m benchmarks.appworld.leaderboard retry-key uncompleted --bundle-dir ... --of-key test_challenge_all_b1

Either command appends a key like `cuga_v1_chal_errored = [...]` to eval_config.toml. Pasting
the cuga-viz line (`<card>_uncompleted_tasks = [...]`) into the toml works too.

Decide what to retry: open a failed task's trajectory; timeout / connection reset / 5xx / empty
LLM reply → retry. A genuine agent mistake is NOT retried on a leaderboard run (one attempt per task).

## 3. Retry (same workspace, same AppWorld dir)

    ./benchmarks/appworld/eval.sh --resume-experiment cuga_v1_chal --eval-key cuga_v1_chal_errored

A key ending in `_errored|_failed|_uncompleted|_failed_tasks|_uncompleted_tasks` re-runs every id
even if its partial is clean. For any other key add `--force-retry`.

## 4. Next batches

    ./benchmarks/appworld/eval.sh --resume-experiment cuga_v1_chal --eval-key test_challenge_all_b2 --background
    # inspect / retry, then b3, b4, b5

Batch keys skip ids that already completed. Ids must belong to the workspace's split or the run aborts.

## 5. Validate + official numbers

    uv run python -m benchmarks.appworld.leaderboard validate cuga_v1 --split test_challenge
    uv run python -m benchmarks.appworld.leaderboard evaluate cuga_v1_test_challenge --split test_challenge \
        --bundle-dir benchmarks/appworld/evaluation_bundles/cuga_v1_chal

`validate` exits 1 on missing tasks/files/scenarios. Tasks with ≤1 environment interaction are
a known CUGA logging gap (API calls bypass `world.execute`); pass `--allow-low-interactions`
only when that is understood. `evaluate` prints TGC + SGC by difficulty and writes them into the
workspace `report.md` under "AppWorld official metrics".

## 6. Pack both splits

    ./benchmarks/appworld/pack_leaderboard.sh cuga_v1 "CUGA" "CUGA lite via SDK" "gpt-4.1" "gpt-4.1-2025-04-14" \
        https://github.com/cuga-project/cuga-agent

Refuses unless both splits validate; runs `appworld pack`, unpacks the bundle into a temp dir and
byte-compares every file; prints the two `leaderboard.bundle` paths and the
`/add-to-leaderboard --python … --appworld … cuga_v1` comment for the PR.

## Do not

- Rename an AppWorld experiment dir after packing (the bundle then refuses to unpack).
- Run `--task` for leaderboard retries; use a toml key so the attempt is recorded in `resume_history`.
- Trust `appworld pack` output alone: it prints WARNINGs and still writes the bundle, and says
  nothing about absent task dirs. Only `pack_leaderboard.sh` / `leaderboard pack` verify.
