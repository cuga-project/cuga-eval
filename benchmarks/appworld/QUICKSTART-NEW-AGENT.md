# Quick start: add your agent to the AppWorld comparison

**Branch:** `feat/appworld-external-agent-comparison` (PR #100). Not on `main` yet.

```bash
git clone git@github.com:cuga-project/cuga-eval.git && cd cuga-eval
git checkout feat/appworld-external-agent-comparison
./setup_appworld.sh
uv sync --all-extras
cp .env.example .env
```

Fill these four in `.env`. Only these two `AGENT_SETTING_CONFIG` values are supported:

```bash
AGENT_SETTING_CONFIG=settings.openai.toml   # or settings.groq.toml
MODEL_NAME=<your-model>
OPENAI_BASE_URL=<your-litellm-or-azure-endpoint>
OPENAI_API_KEY=<key>
```

## 1. Check the harness first

```bash
./benchmarks/appworld/smoke_external.sh --agents stub          # no servers, ~10s
./benchmarks/appworld/eval.sh --agent stub --eval-key test_challenge_easy
```

`stub` is a plain chat model on the shared tool loop, no framework. If `stub` scores
and yours doesn't, the bug is in your adapter.

## 2. Write the adapter

```bash
cp benchmarks/appworld/agents/stub.py benchmarks/appworld/agents/myagent.py
```

Read that file's docstring — it is the full instructions. You replace **one method**,
`_call_llm`. Then register the name in two places:

- `agents/factory.py` — `EXTERNAL_AGENT_NAMES` and a branch in `create_appworld_agent`
- `eval.sh` — `is_external_agent()`

Do not change these; they are what makes the comparison fair:

| | |
|---|---|
| Tools | from `setup_appworld_tools` (`CombinedToolProvider`). Don't build your own list |
| Prompt | `APPWORLD_AGENT_PROMPT`, as a parameter — don't bake in a different default |
| Return | an `AppWorldInvokeResult`; the evaluator reads `answer` and `tool_calls` |

Pass `invoke_callbacks` through to whatever calls your model. They carry the token
counter, and dropping them silently zeroes your cost column.

## 3. Run and compare

```bash
./benchmarks/appworld/eval.sh --agent myagent --eval-key test_challenge_easy
./benchmarks/appworld/compare.sh --eval-key test_challenge_easy --agents cuga,myagent --runs 3
uv run pytest benchmarks/appworld/tests/ -q
```

## 4. Read the numbers honestly

Both sides get tools from the same `CombinedToolProvider` against the same registry
(`tests/test_tool_provider_parity.py` enforces it). Three differences remain, and all
three favour your agent:

| | CUGA | Yours |
|---|---|---|
| Apps | all; CUGA finds tools itself via `find_tools` | only the task's apps — tool selection is solved for you |
| Prompt | `APPWORLD_SDK_PROMPT` | same base plus filtering/pagination rules CUGA handles in code |
| LLM | CUGA's `LLMManager` | `create_eval_llm`, straight from env |

Both prompts sit side by side in `agents/base.py` so the gap shows in a diff.

`--compare-agents` expands to `cuga,deepagents,openclaw,hermes`, but `openclaw` and
`hermes` have no installable client and both fall back to the shared eval LLM — so
they are three runs of the same loop, not three frameworks.
