set shell := ["bash", "-cu"]

default: lint test-sanity

# Sync dev dependencies into the project venv.
sync:
    uv sync --group dev

# Run lint and format checks (read-only).
lint:
    uv run ruff check .
    uv run ruff format --check .

# Apply ruff format and auto-fixable lint corrections.
format:
    uv run ruff format .
    uv run ruff check . --fix

# Fast unit tests, run on every commit.
test-sanity:
    uv run pytest -m sanity

# Live smoke: 1 AppWorld (SDK), 1 AppWorld (ReAct), 1 M3 hockey task; checks bundle report.md.
test-smoke-e2e:
    bash scripts/smoke_benchmarks.sh

# Sanity + regression suite, run on every PR and push to master.
test-regression:
    uv run pytest -m "sanity or regression"

# Long-running stability tests; need full runtime/LLM access.
test-stability:
    uv run pytest -m stability

# Static security scan (bandit) and dependency CVE audit (pip-audit).
# --skip-editable: cuga and appworld are editable path installs not on PyPI.
# --ignore-vuln CVE-2026-47214: docling is pinned to <2.92 until langchain-docling
#   supports the newer "slim" docling layout. See issue #45.
# --ignore-vuln CVE-2025-3000: torch CPU-only wheel has no published fix.
security:
    uv run bandit -c pyproject.toml -r benchmarks scripts -ll
    uv run pip-audit --skip-editable --ignore-vuln CVE-2026-47214 --ignore-vuln CVE-2025-3000

# Composite gate matching what CI runs.
ci: lint test-regression security
