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

# Sanity + regression suite, run on every PR and push to master.
test-regression:
    uv run pytest -m "sanity or regression"

# Long-running stability tests; need full runtime/LLM access.
test-stability:
    uv run pytest -m stability

# Static security scan (bandit) and dependency CVE audit (pip-audit).
# --skip-editable: cuga and appworld are editable path installs not on PyPI.
# --ignore-vuln GHSA-r7w7-9xr2-qq2r: langchain-openai is pinned to 1.1.10 by
#   cuga-agent's transitive constraints. Track the upstream bump separately.
security:
    uv run bandit -c pyproject.toml -r benchmarks scripts -ll
    uv run pip-audit --skip-editable --ignore-vuln GHSA-r7w7-9xr2-qq2r

# Composite gate matching what CI runs.
ci: lint test-regression security
