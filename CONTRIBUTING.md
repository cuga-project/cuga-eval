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

## AI Agent Commands

If you are working in an AI-assisted IDE or using an AI agent (Cursor, Claude, Bob), a set of pre-built workflow commands is available to streamline common contributor tasks. The same commands are mirrored across all three tooling directories:

| Location | For |
|---|---|
| `.cursor/commands/cuga-*.md` | Cursor agent |
| `.claude/commands/cuga-*.md` | Claude / claude-code |
| `.bob/commands/cuga-*.md` | Bob agent |

### Available Commands

| Command | What it does |
|---|---|
| `cuga-commit` | Stages and commits changes using Conventional Commits with scoped messages and bullet-point descriptions |
| `cuga-create-pr` | Validates local state, picks the right PR template, fills it out from current changes, and opens the PR via `gh` |
| `cuga-report-bug` | Creates a GitHub issue using the `bug_report.yml` template with context from the current code |
| `cuga-new-feature` | Creates a GitHub issue using the `feature_request.yml` template |
| `cuga-ruff-check` | Runs `just format` (or `uv run ruff`) to fix and format Python |

These commands follow all repo conventions (Conventional Commits, `gh` CLI, `just` tasks, no promotional footers). To invoke them, use the slash-command syntax of your tool (e.g. `/cuga-commit` in Cursor).

**Maintenance:** The five `cuga-*.md` files are duplicated under `.cursor/commands/`, `.claude/commands/`, and `.bob/commands/`. When you edit one command, update the same filename in all three directories so they stay in sync.
