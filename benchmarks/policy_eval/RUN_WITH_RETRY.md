# Run the policy evaluation with retries

## Why

A gateway sometimes answers a model call with `429`, a `5xx` status, a connection error, or `400` with
`quota_exceeded` in the body. The agent's client retries only twice within a few seconds. After that the task ends,
and the harness records it as an error. A run with many such errors gives a wrong score.

The retry proxy sits between the harness and the gateway. It waits and sends the same request again, so the agent
does not see the error.

## What the proxy does

| Item | Behavior |
|---|---|
| Retried | `429`, any `5xx`, connection errors and timeouts, `400` with `quota_exceeded` in the body |
| Not retried | Every other `4xx` (for example a wrong key or a wrong model name) |
| Wait | The time the gateway gives (`retry-after` or the rate-limit reset header), between 3 and 65 seconds |
| Attempts | Up to 60 per request, each with a 300 second timeout |
| Shared wait | After a rate limit, no request is sent until the wait is over |
| `--no-cache` | Asks the gateway for a fresh reply on every chat call. Use it when trials must be independent: a caching gateway returns the same reply for the same request |
| Log | One line per upstream call in `benchmarks/automationbench/proxy_log.jsonl` (status, attempts, wait, token use) |
| Key | The proxy forwards the client's own `Authorization` header. It stores no key |

## Steps

1. Start the proxy in its own terminal and leave it running:

   ```bash
   cd benchmarks/automationbench
   UPSTREAM_BASE_URL=<gateway base URL> .venv/bin/python -I retry_proxy.py --port 8814 --no-cache
   ```

   Without `UPSTREAM_BASE_URL` the proxy reads `OPENAI_BASE_URL` from the `.env` file at the repository root.
   It prints `forwarding 127.0.0.1:8814 -> <gateway base URL>` when it is ready.

2. Run the harness with `--proxy`:

   ```bash
   cd benchmarks/policy_eval
   $PY -I harness/run.py --bench automationbench --profile <profile> --set <set> \
       --snapshot <snapshot> --trial 1 --run <tag> --model <model layer> -j 3 \
       --proxy http://127.0.0.1:8814
   ```

   `--proxy` sets `OPENAI_BASE_URL` for the agent and for the policy layer's own model calls.

3. Check the run:

   - The proxy terminal prints one line per retry: `retry 2/60 /chat/completions after 429; waiting 20s`.
   - After the run, count the tasks that ended on an error. The number must be 0 before two arms are compared.
   - If some tasks ended on a gateway error, run the same command again. A task with a score is skipped; a task
     with no score or with a gateway error runs again.
   - The proxy's waits count toward the task's time limit (`--timeout`; AutomationBench: 1,800 s). A task that reaches
     it ends with `timeout after 1800s`. That is not a gateway error: the task is graded and the same command does not
     run it again. Run such a task under a new `--run`, with a larger `--timeout` if the gateway was slow.

## Notes

- Start one proxy per gateway. Two arms that run at the same time can share one proxy.
- Keep `-j` low (3 per arm) when the gateway has a throughput limit. The proxy waits, but a run with many waits is slow.
- The proxy only listens on `127.0.0.1`.
- A long wait is not an error. A request fails only when all 60 attempts fail, or when its `quota_exceeded` errors
  last more than 10 minutes (a daily or spend quota, not a throughput limit). The error then says which.
- **Free endpoint:** the ledger (`benchmarks/policy_pilot_costs.py`) counts every run at list price and the harness stops
  when the total passes `POLICY_PILOT_BUDGET`. For a run on an endpoint that costs nothing, set `POLICY_PILOT_FREE=1`:
  the ledger still records the tokens, with cost 0, and the budget stop does not apply to that run. The result files
  keep `cost_usd` at list price, as on a paid endpoint: it is what the run would cost, so `report.py` totals and the
  ledger differ on such a run.
