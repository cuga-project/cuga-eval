# Contributing

## Local setup

```bash
uv sync --group dev
uv run pre-commit install --install-hooks --hook-type pre-commit --hook-type commit-msg
```

The pre-commit hook fixes formatting and lint findings on staged Python
files; the commit-msg hook enforces [Conventional Commits](https://www.conventionalcommits.org/).

## Branches

Branch off `master` using a Conventional-Commits-style prefix:

- `feat/<short-description>` — new functionality
- `fix/<short-description>` — bug fixes
- `chore/<short-description>` — tooling, deps, CI
- `docs/<short-description>` — documentation only

## Test taxonomy

Mark every new test with one tier so CI runs it at the right cadence.

| Marker | When it runs | Use it for |
|---|---|---|
| `pytest.mark.sanity` | every commit (locally) and every PR | fast, pure-logic unit tests with no network/LLM |
| `pytest.mark.regression` | every PR and every push to `master` | integration tests that touch fixtures or the FastAPI app, no LLM |
| `pytest.mark.stability` | scheduled / manual only | long-running tests that need real LLM or runtime |

Apply at module level:

```python
import pytest

pytestmark = pytest.mark.sanity
```

Tests live alongside the code they cover (e.g. `benchmarks/bpo/tests/`)
or under the root `tests/` directory.

## Run gates locally before pushing

```bash
just lint            # ruff check + ruff format --check
just test-sanity     # ~5s
just test-regression # ~7s
just security        # bandit + pip-audit
just ci              # all of the above
```

CI runs the same `lint`, `test-regression`, and `security` checks on
every PR; failing locally first is faster than failing in CI.

## Working with the cuga-agent path dependency

`pyproject.toml` declares `cuga` as an editable path install at
`../cuga-agent`. To run anything that imports `cuga`, you need that
sibling checkout. CI clones it automatically; locally, clone it once:

```bash
cd ..
git clone https://github.com/cuga-project/cuga-agent.git
```
