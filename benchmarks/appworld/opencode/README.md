# Evaluating OpenCode on AppWorld

This adds [OpenCode](https://github.com/anomalyco/opencode) — an open-source AI coding agent with its
own agentic loop and native MCP support — as a first-class agent for the AppWorld benchmark, alongside
`cuga`, `codeact`, and `react`. It runs through the **same harness** and is scored by the **same**
`world.evaluate()`, so results are directly comparable.

> Architecture diagram & deep-dive: [`docs/architecture.md`](docs/architecture.md).

---

## TL;DR

```bash
# from cuga-eval/
./benchmarks/appworld/eval.sh --agent opencode --task 82e2fac_1                 # repl tools (default)
./benchmarks/appworld/eval.sh --agent opencode --opencode-tools apis --task 82e2fac_1
./benchmarks/appworld/eval.sh --agent opencode --eval-key test_challenge_easy   # a task set
# or via the top-level dispatcher:
./scripts/eval.sh --benchmark appworld --agent opencode --task 82e2fac_1
```

`eval.sh` starts the AppWorld servers + registry and cleans them up on exit. No extra services are
needed for the opencode agent.

---

## How it works (one paragraph)

OpenCode runs as a subprocess (`opencode run`). Its built-in file/shell/web tools are **disabled**; the
only tools it can use are AppWorld tools served by an **in-process MCP bridge** that the harness binds to
the live `world`. Every tool call therefore routes into the *same* `world` object the harness scores with
`world.evaluate()`. OpenCode makes its **own** LLM calls directly to the configured endpoint
(`OPENAI_BASE_URL` / `LITE_LLM_URL`, or real OpenAI), and the harness reads **tokens / cost / llm_calls
from OpenCode's `--format json` output** — no proxy.

```
OpenCode loop ──MCP──► bridge.execute_python(code) ──► world.execute(code) ──► AppWorld
OpenCode LLM  ──HTTP──► LLM endpoint (OPENAI_BASE_URL / OpenAI)
harness ──► world.evaluate()  +  metrics parsed from OpenCode's JSON usage events
```

---

## Two action surfaces (`--opencode-tools`)

| mode | tools exposed to OpenCode | mirrors | routing |
|------|---------------------------|---------|---------|
| `repl` (default) | one tool `execute_python(code)` | **codeact** (stateful Python REPL) | `world.execute("\n"+code+"\n")` |
| `apis` | one tool per API `{app}__{api}(arguments)` (schemas from AppWorld's `ApiDocCollection`) | **cuga** (discrete API calls) | `world.execute("apis.{app}.{api}(**arguments)")` |

Both route through the same `world`, so scoring is identical regardless of surface. In `apis` mode the
agent finishes by calling the `supervisor__complete_task` tool; in `repl` mode it calls
`apis.supervisor.complete_task(...)` inside `execute_python`.

---

## Prerequisites

1. **The `opencode` CLI on `PATH`.** Not bundled. Install one of:
   ```bash
   npm  i -g opencode-ai          # npm
   brew install opencode          # macOS
   curl -fsSL https://opencode.ai/install | bash
   ```
   Verify: `opencode --version`. (If missing, the harness logs a clear warning and each task fails fast.)

2. **Python deps** (already in the eval environment): `fastmcp`, `mcp`, `uvicorn` (for the MCP bridge).

3. **Environment variables** — read from the **same `.env`** as the rest of the framework. `eval.sh`
   loads it via `load_env.sh`, and the harness also loads the root `.env` itself (without override) so a
   direct `python -m …` run gets the same values.
   - Model: `MODEL_NAME` (e.g. `gpt-4o`, `openai/gpt-oss-120b`, `Azure/gpt-5.2-chat-2025-12-11`).
   - LLM endpoint OpenCode posts to: `OPENAI_BASE_URL` + `OPENAI_API_KEY` (or `LITE_LLM_URL` +
     `LITE_LLM_KEY`). If none is set, OpenCode talks to real OpenAI. Override per-run with
     `--opencode-base-url`.
   - Langfuse (optional, for run visibility): `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`,
     `LANGFUSE_HOST` and `DYNACONF_ADVANCED_FEATURES__LANGFUSE_TRACING=true` — same project as the
     other agents.

---

## Metrics (tokens / cost / llm_calls)

Sourced from OpenCode's `--format json` usage events ([`runner.py`](runner.py)
`parse_opencode_events`): input/output tokens are aggregated, `llm_calls` counted, and `total_cost` taken
from OpenCode if it reports one. The values populate the same `TaskResult` fields the other agents use, so
reports/comparisons line up.

**Cost for models the endpoint doesn't price** (e.g. Azure GPT-5.x) is computed from token counts via
`MODEL_PRICES` in the runner — litellm wants `$/token`, so the published `$/1M` are divided by 1e6:

| model (matched leniently) | input $/1M → $/token | output $/1M → $/token |
|---|---|---|
| `…gpt-5.2…` | 1.75 → `0.00000175` | 14.00 → `0.000014` |
| `…gpt-5.5…` | 2.50 → `0.0000025` | 15.00 → `0.000015` |

> Note: OpenCode's exact JSON usage schema varies by version; the parser is defensive and assumes one
> usage object per assistant turn. Validate the totals against your installed OpenCode on a first run.

**Langfuse (optional).** When `LANGFUSE_*` are set in `.env` (and `…LANGFUSE_TRACING=true`), the harness
records a per-task **trace** with the run's input/output and the token/cost/success metadata, so opencode
runs show up in Langfuse alongside the other agents. There is **no proxy** — OpenCode's individual LLM-call
generations are not traced; only the harness-level trace + the metrics above are pushed.

---

## Comparison runs (`compare.sh`)

OpenCode participates in the multi-run / multi-agent / multi-model comparison harness:

```bash
./benchmarks/appworld/compare.sh --agents cuga,codeact,opencode --runs 3 --task 82e2fac_1
./benchmarks/appworld/compare.sh --models gpt-5.2,gpt-5.5 --agent opencode --eval-key test_challenge_easy
```

`gpt-5.2` / `gpt-5.5` are model profiles in [`../../scripts/model_profiles.sh`](../../scripts/model_profiles.sh)
that set `MODEL_NAME` + the Azure gateway `OPENAI_BASE_URL`. No extra services are started for opencode, so
comparison sweeps need no special lifecycle handling.

---

## Components / files

| File | Role |
|------|------|
| [`eval.py`](eval.py) | Main harness (mirrors `appworld_eval_codeact.py`); owns `world`, tracking, evaluation, metrics. |
| [`bridge.py`](bridge.py) | In-process FastMCP server bound to `world` (`repl` + `apis` tools). |
| [`runner.py`](runner.py) | `opencode.json` generation, model resolution, subprocess launch, JSON usage parsing, cost computation. |
| [`prompts/instructions.txt`](prompts/instructions.txt) | Minimal (~12-line) system prompt for the `appworld` agent. |
| [`docs/architecture.md`](docs/architecture.md) | Diagrams + flow. |

Shared helpers `completion_called` / `extract_completion_answer` live in
[`utils/appworld_utils.py`](utils/appworld_utils.py) (used by both codeact and the bridge).

**Modified existing files (for the opencode agent):**

| File | Change |
|------|--------|
| [`eval.sh`](eval.sh) | Adds the `opencode` dispatch branch + `--opencode-tools` passthrough. |
| [`compare.sh`](compare.sh) | `opencode` works in multi-run/agent/model sweeps; usage docs. |
| [`../../scripts/eval.sh`](../../scripts/eval.sh) | Top-level dispatcher allow-list now accepts `--agent opencode` (appworld-only). |
| [`../../scripts/model_profiles.sh`](../../scripts/model_profiles.sh) | Adds the `gpt-5.2` / `gpt-5.5` model profiles. |
| [`appworld_eval_codeact.py`](appworld_eval_codeact.py) | Imports the shared completion helpers (refactor). |

---

## CLI flags (`eval.py`)

| flag | default | meaning |
|------|---------|---------|
| `--task-id <id...>` | — | run specific task id(s) |
| `--dataset <name>` | `train` | dataset when not using `--task-id`/`--eval-key` |
| `--eval-key <key>` | from settings | a predefined task group from `eval_config.toml` |
| `--specific-task-levels 1 2 3` | — | filter by difficulty |
| `--opencode-tools repl\|apis` | `repl` | action surface |
| `--opencode-bin <name>` | `opencode` | path/name of the CLI |
| `--opencode-base-url <url>` | `$LITE_LLM_URL`/`$OPENAI_BASE_URL` | LLM endpoint OpenCode posts to |

Outputs land where every AppWorld agent writes them: `experiments/outputs/<run>/…_final_report.json`,
per-task JSON under `tasks/`, and a trajectory under `logging/trajectory_data/` (tagged `agent_v="opencode"`).

---

## Tests

```bash
uv run --no-sync python -m pytest benchmarks/appworld/opencode/tests/test_runner.py \
                                  benchmarks/appworld/opencode/tests/test_bridge.py -q
```

- `test_runner.py` — model resolution, prompt rendering, `opencode.json` generation, JSON usage
  parsing, and the per-token cost computation.
- `test_bridge.py` — starts the real MCP bridge over a fake `world`, connects an MCP client, and
  asserts tool calls route to `world.execute` and completion/answer are captured.

---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Every task fails immediately; log says *opencode CLI not found* | Install the `opencode` binary and ensure it's on `PATH`. |
| Tokens/cost are 0 | OpenCode didn't emit usage in the expected JSON shape for your version. Inspect the raw events and adjust `parse_opencode_events`. For unpriced models, set `MODEL_PRICES` so cost is computed from tokens. |
| OpenCode hangs / no output in CI | Non-interactive TTY quirk. The harness passes the prompt as an arg with `-q --dangerously-skip-permissions` and no stdin; if it persists, run under a PTY or use `opencode serve` + `--attach`. |
| Agent "solves" tasks without touching AppWorld | Built-in tools should be disabled via `opencode.json` (`write/edit/bash/read/...: false`). Confirm the generated config in the task scratch dir. |

---

## Notes / limitations

- One task runs at a time (matches the sequential eval loop); the MCP bridge binds a fresh free port per task.
- `apis` mode builds per-API tools from `ApiDocCollection`; if doc-building fails it falls back to a single
  generic `call_api(app_name, api_name, arguments)` tool (logged, never silent).
- `opencode.json` uses a custom openai-compatible provider via `@ai-sdk/openai-compatible`; config key names
  can drift across OpenCode versions — verify against your installed `opencode`.
- Metrics come from OpenCode's JSON output (not a proxy). A harness-level Langfuse trace is recorded when
  `LANGFUSE_*` are configured, but OpenCode's per-call generations are not traced.
