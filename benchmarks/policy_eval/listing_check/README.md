# Listing check (`sources.listing`, 2026-11-08)

Scripts and data behind `docs/analysis/2026-11-08-listing-preregistration.md`. They were run from `/tmp/aud`; the paths
inside are absolute, so copy this folder to `/tmp/aud` (or edit the paths) to run them again.

| File | What |
|---|---|
| `worldsize.py`, `appsurvey.py`, `sheetcount.py`, `coverage.py` | World size and which apps hold data, fresh3 |
| `listcov.py <fresh3\|all>` | Offline coverage of the lister (text of 4+ words reached through read tools) |
| `disc/dump.py` | Every listed record per task -> `disc/records/` |
| `disc/label.py <model> <outdir>` | Gold labels (Opus 5.5, request and records only, no grader) -> `disc/gold/` |
| `disc/replay_old.py`, `disc/classify.py gptoss\|kev`, `disc/score.py` | Offline recall of keyword discovery against listing + sorters |
| `oney2.sh`, `list3o.sh`, `list3h.sh` | The live runs (arms R / P / L, gpt-oss and Haiku 5.5, 3 trials) |
| `lx.py` (`LXM=gptoss\|haiku55`) | Scores, paired differences, no-harm check, mechanism count |
| `cov/livecov.py <judge> <run-glob>...`, `cov/summ.py`, `cov/chk.py` | Live coverage: extracted statements against gold rule records (judge outputs in `cov/out/`) |

Run results are in `harness/results/lx_*` (not tracked, `.gitignore`).
