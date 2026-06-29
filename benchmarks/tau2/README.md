# tau2-bench (τ²) — CUGA evaluation

Evaluates CUGA on [tau2-bench](https://github.com/sierra-research/tau2-bench), a
multi-turn customer-service benchmark. τ² drives the conversation (user simulator +
orchestrator + scoring); CUGA plugs in as the agent under test through a small
**bridge** so that CUGA's tool calls round-trip through τ²'s orchestrator (required
for correct env-state scoring).

> **Status: scaffold (Phase 1).** Only the layout, config, installer, and the
> config-load sanity test exist. The bridge, proxy agent, driver, and reporting land
> in later phases. Full design: `TAU2_CUGA_EVAL_PLAN.md` (outside this repo).

## Install

```bash
bash setup_tau2.sh          # clone tau2-bench (pinned), editable install, check data
uv sync --group tau2        # install base deps + tau2
```

## Layout

| File | Role |
|------|------|
| `config/tau2.env` | DYNACONF flags + safety pins (e2b off; REGISTRY inherits false) |
| `eval_tau2_sdk.py` | entrypoint — config-load-first, task loop (Phase 6) |
| `tau2_bridge.py` | ConversationBridge + decoy tools + CugaProxyAgent (Phase 2/4) |
| `cuga_runner.py` | build_cuga_agent() + run_cuga_loop() hybrid (Phase 5) |
| `tests/` | `test_config_load.py` (sanity), bridge/smoke placeholders |

## Credentials

CUGA needs an LLM (e.g. via the LiteLLM gateway: `AGENT_SETTING_CONFIG`,
`MODEL_NAME`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`). τ²'s **user simulator** is a
*second* LLM — model + creds are an open decision (see plan §9.1). Both models are
recorded in run metadata because τ² scores are not comparable across user-sim choices.
