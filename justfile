set shell := ["bash", "-cu"]

default: lint test-sanity

# Sync dev dependencies into the project venv, updating uv.lock if the
# resolved graph changed (e.g. the local ../cuga-agent editable checkout's own
# dependencies moved). This is the only recipe allowed to touch uv.lock; every
# other recipe runs --frozen so routine dev-loop commands don't silently
# rewrite the lockfile against whatever cuga-agent commit happens to be
# checked out next door. Run this explicitly when you actually want to pick
# up new cuga-agent dependencies. See issue #110.
sync:
    uv sync --group dev

# Run lint and format checks (read-only).
lint:
    uv run --frozen ruff check .
    uv run --frozen ruff format --check .

# Apply ruff format and auto-fixable lint corrections.
format:
    uv run --frozen ruff format .
    uv run --frozen ruff check . --fix

# Fast unit tests, run on every commit.
test-sanity:
    uv run --frozen pytest -m sanity

# Live smoke: 1 AppWorld (SDK), 1 AppWorld (ReAct), 1 M3 hockey task; checks bundle report.md.
test-smoke-e2e:
    bash scripts/smoke_benchmarks.sh

# Sanity + regression suite, run on every PR and push to master.
test-regression:
    uv run --frozen pytest -m "sanity or regression"

# Long-running stability tests; need full runtime/LLM access.
test-stability:
    uv run --frozen pytest -m stability

# Static security scan (bandit) and dependency CVE audit (pip-audit).
# --skip-editable: cuga and appworld are editable path installs not on PyPI.
security:
    uv run --frozen bandit -c pyproject.toml -r benchmarks scripts -ll
    uv run --frozen pip-audit --skip-editable

# Composite gate matching what CI runs.
ci: lint test-regression security
