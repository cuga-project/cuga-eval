1. Prefer the repo shortcut: `just format` (runs `ruff format` and `ruff check --fix` on the project).

2. Or run explicitly: `uv run ruff check --fix` then `uv run ruff format`.

3. Fix any issues Ruff still reports after `--fix` (manual or refactors, not suppressed without a good reason).

4. Verify with `just lint` before pushing (read-only check, matches CI).
