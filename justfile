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
# --ignore-vuln CVE-2026-47214: docling is pinned to <2.92 until langchain-docling
#   supports the newer "slim" docling layout. See issue #45.
# --ignore-vuln CVE-2025-3000: torch CPU-only wheel has no published fix.
# --ignore-vuln PYSEC-2026-3447: setuptools fix (83.0.0) is blocked by torch's
#   own "setuptools<82" pin; nothing we can bump on our side.
security:
    uv run --frozen bandit -c pyproject.toml -r benchmarks scripts -ll
    uv run --frozen pip-audit --skip-editable --ignore-vuln CVE-2026-47214 --ignore-vuln CVE-2025-3000 --ignore-vuln PYSEC-2026-3447

# Composite gate matching what CI runs.
ci: lint test-regression security
