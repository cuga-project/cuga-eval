# PR Regression Testing

This folder contains the scripts used to set up and run PR-triggered regression evaluations from GitHub Actions comments.

## Files

- `setup-pr-regression-workflow.sh`: bootstraps the self-hosted GitHub Actions runner VM.
- `run-pr-regression-eval.sh`: consumes validated `/run-pr-eval` parameters and runs the requested benchmark using the `cuga-eval/scripts/eval.sh` script.

## Setup The PR Regression Flow

1. Add the workflow file to the `cuga-agent` repository:

   ```text
   .github/workflows/run-pr-eval.yml
   ```

2. In GitHub, create a self-hosted runner token for the `cuga-agent` repository.

   Go to:

   ```text
   cuga-agent repository -> Settings -> Actions -> Runners -> New self-hosted runner
   ```

   Copy temporary runner token from the generated `config.sh` command.

3. Ensure the workflow file uses the self-hosted runner labels:

   ```yaml
   runs-on: [self-hosted, linux, run-pr-eval]
   ```

4. On the runner VM, export the required setup variables:

   ```bash
   export GITHUB_REPO_URL="https://github.com/OWNER/cuga-agent"
   export GITHUB_RUNNER_TOKEN="YOUR_TEMPORARY_RUNNER_TOKEN"
   export RUNNER_LABELS="run-pr-eval"
   ```

5. Optionally choose repo mode and branches:

   ```bash
   export REPO_MODE="fork"
   export CUGA_AGENT_BRANCH="main"
   export CUGA_EVAL_BRANCH="main"
   ```

   Supported `REPO_MODE` values:

   - `fork`: uses `https://github.com/AnkitaNaik/cuga-agent.git` and `https://github.com/AnkitaNaik/cuga-eval.git`.
   - `upstream`: uses `https://github.com/cuga-project/cuga-agent.git` and `https://github.com/cuga-project/cuga-eval.git`.

6. Run the setup script on the VM as the normal runner user, not with `sudo`:

   ```bash
   bash /path/to/cuga-eval/scripts/pr-regression-testing/setup-pr-regression-workflow.sh
   ```

   The script will:

   - verify required commands: `git`, `curl`, `tar`, `python3`, `git-lfs`, and `uv`;
   - clone or update `cuga-agent` and `cuga-eval` under `~/pr-regression-testing`;
   - run `cuga-eval/setup_cuga.sh`;
   - create and sync the `uv` environment;
   - run AppWorld setup;
   - download and register the GitHub Actions runner;
   - start the runner in the background.

7. Confirm the runner is online in GitHub:

   ```text
   cuga-agent repository -> Settings -> Actions -> Runners
   ```

   Ensure the runner is running with the labels `[self-hosted, linux, run-pr-eval]` i.e. same as workflow file.

8. Check runner logs on the VM if needed:

   ```bash
   tail -f ~/pr-regression-testing/github-runner/runner.log
   ```

## GitHub Secrets And Variables

Configure these in the `cuga-agent` repository:

```text
Settings -> Secrets and variables -> Actions
```

Required secrets:

- `RITS_API_KEY`: required for `provider=rits`.
- `LITE_LLM_KEY`: preferred secret for `provider=litellm`; the workflow injects it into `OPENAI_API_KEY`.
- `OPENAI_API_KEY`: optional fallback secret for `provider=litellm` when `LITE_LLM_KEY` is not set.

Optional repository variables:

- `MODEL_NAME`: default model override used by the workflow environment.
- `RITS_BASE_URL`: RITS endpoint override for `provider=rits`.
- `LITELLM_BASE_URL`: LiteLLM endpoint override for `provider=litellm`; the workflow injects it into `OPENAI_BASE_URL`.

Provider defaults used by `run-pr-regression-eval.sh`:

- `provider=rits` selects `settings.rits.toml`, requires `RITS_API_KEY`, and passes `RITS_BASE_URL` to `models.py`.
- `provider=litellm` selects `settings.litellm.toml` for the CUGA agent or `settings.openai.toml` for non-CUGA agents, requires `OPENAI_API_KEY`, and passes `OPENAI_BASE_URL` to `models.py`. Unless `model_name` is explicitly set in the PR comment, it uses `aws/gpt-oss-120b`.
- For `provider=rits`, overriding `model_name` in the PR command requires `RITS_BASE_URL` to be configured so the model name and endpoint cannot silently diverge.

## Run PR Evaluations

Create a comment on a pull request in `cuga-agent`:

```text
/run-pr-eval sha=<PR_HEAD_SHA>
```

The `sha` value must be the current 40-character PR head commit SHA. The workflow validates it before checkout and does not forward it to the evaluation process. By default, the forwarded evaluation runs:

- `benchmark=appworld`
- `agent=react`
- `provider=rits`
- `model_name=openai/gpt-oss-120b-a100`
- `num_tasks=4`
- default AppWorld task IDs: `9aae7da_1 365e0a3_1 eb5ad85_1 5e27cd7_1`

For `provider=litellm`, the default model changes to `aws/gpt-oss-120b` unless `model_name` is explicitly provided.

## Command Parameters

The command accepts whitespace-separated `key=value` parameters:

- `sha`: required by the GitHub workflow; must be the current 40-character PR head SHA.
- `model_name`: model name to evaluate.
- `task_id`: one task ID, or comma-separated task IDs.
- `task_ids`: alias for `task_id`.
- `eval_key`: AppWorld task group from `benchmarks/appworld/eval_config.toml`, such as `test_easy`, `test_med`, or `test_hard`.
- `benchmark`: `appworld` or `m3`; defaults to `appworld`.
- `num_tasks`: positive integer; defaults to `4`.
- `agent`: `react`, `cuga`, or `codeact`; defaults to `react`.
- `provider`: `rits` or `litellm`; defaults to `rits`.

Unsupported parameters cause the workflow or runner script to fail early with a list of supported parameters.

The workflow parser tolerates spaces around `=`, markdown code ticks, mixed-case values for `agent`, `benchmark`, and `provider`, and spaces after commas in task lists. For example, `provider = litellm` and `task_id = 9aae7da_1, 365e0a3_1` are accepted. The runner script also accepts sanitized CLI-style arguments such as `--benchmark appworld --agent react --provider rits`.

Useful AppWorld `eval_key` values:

- `test_easy`
- `test_med`
- `test_hard`
- `test_challenge_easy`
- `test_challenge_med`
- `test_challenge_hard`
- `test_normal_easy`
- `test_normal_med`
- `test_normal_hard`

## Examples

Run the default AppWorld React-agent evaluation on RITS:

```text
/run-pr-eval sha=<PR_HEAD_SHA>
```

Run one AppWorld task with the React agent on RITS:

```text
/run-pr-eval sha=<PR_HEAD_SHA> provider=rits agent=react benchmark=appworld task_id=9aae7da_1 num_tasks=1
```

Run one AppWorld task with the CUGA agent on LiteLLM:

```text
/run-pr-eval sha=<PR_HEAD_SHA> provider=litellm agent=cuga benchmark=appworld task_id=9aae7da_1 num_tasks=1
```

Run AppWorld with two explicit tasks:

```text
/run-pr-eval sha=<PR_HEAD_SHA> benchmark=appworld task_id=9aae7da_1,365e0a3_1 num_tasks=2
```

Run AppWorld easy tasks from `eval_config.toml`:

```text
/run-pr-eval sha=<PR_HEAD_SHA> benchmark=appworld eval_key=test_easy
```

Run AppWorld medium tasks from `eval_config.toml`:

```text
/run-pr-eval sha=<PR_HEAD_SHA> benchmark=appworld eval_key=test_med
```

Run AppWorld hard tasks from `eval_config.toml`:

```text
/run-pr-eval sha=<PR_HEAD_SHA> benchmark=appworld eval_key=test_hard
```

Run M3 with the default React agent:

```text
/run-pr-eval sha=<PR_HEAD_SHA> benchmark=m3 num_tasks=1
```

Run M3 with the CUGA agent and LiteLLM:

```text
/run-pr-eval sha=<PR_HEAD_SHA> benchmark=m3 agent=cuga provider=litellm num_tasks=1
```

Override the model:

```text
/run-pr-eval sha=<PR_HEAD_SHA> provider=litellm agent=cuga benchmark=appworld model_name=aws/glm-5 task_id=9aae7da_1 num_tasks=1
```

## Output

The workflow posts a PR comment containing:

- trusted run metadata;
- requested command and SHA;
- the evaluation report markdown emitted by the PR regression runner;
- a link to the uploaded workflow artifact.

The full output is also uploaded as a GitHub Actions artifact. During the workflow run, logs are written under the checked-out workspace in `pr-eval-logs/`.
