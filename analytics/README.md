# Analytics

Decision intelligence analytics that run on data from evaluation experiments.

Analytics work with **evaluation bundles** produced by benchmark runs (stored in `benchmarks/{benchmark}/evaluation_bundles/`). They do not require the benchmark servers to be running.

Named experiment workspaces (`--experiment <name>`) and legacy timestamped bundles both work — analytics read whatever is under `evaluation_bundles/`. Use `uv run python -m benchmarks.helpers.bundle replay --bundle-dir <path>` to reconstruct the eval command that produced a bundle.

## Available Analytics

| Analytics | Description |
|---|---|
| [Trace Comparison](trace_comparison_rules/README.md) | Compares successful vs. failed traces **on the same tasks** to identify failure clusters, root causes, and remediation actions |

## Output

Each analytics writes its results to:
```
benchmarks/{benchmark}/analytics_output/{analytics_name}/
```
