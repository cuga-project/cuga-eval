#!/usr/bin/env bash
set -Eeuo pipefail

START_EPOCH="$(date +%s)"
START_TIME="$(date -u +"%Y-%m-%d %H:%M:%S UTC")"

log() {
  printf '[%s] %s\n' "$(date -u +"%Y-%m-%d %H:%M:%S UTC")" "$*"
}

open_details() {
  local title="$1"
  echo "<details>"
  echo "<summary>${title}</summary>"
  echo
}

close_details() {
  echo
  echo "</details>"
}

on_exit() {
  status=$?
  end_epoch="$(date +%s)"
  end_time="$(date -u +"%Y-%m-%d %H:%M:%S UTC")"
  duration=$((end_epoch - START_EPOCH))
  minutes=$((duration / 60))
  seconds=$((duration % 60))

  echo "######## REPORT START ########"
  echo
  open_details "Run summary"
  echo "- Started: ${START_TIME}"
  echo "- Finished: ${end_time}"
  echo "- Duration: ${minutes}m ${seconds}s"
  echo "- Exit code: ${status}"

  if [[ ${status} -eq 0 ]]; then
    echo "- Result: SUCCESS"
  else
    echo "- Result: FAILED"
  fi
  close_details
  echo "######## REPORT END ########"
}
trap on_exit EXIT

DEFAULT_MODEL_NAME="openai/gpt-oss-120b-a100"
DEFAULT_LITELLM_MODEL_NAME="aws/gpt-oss-120b"
DEFAULT_APPWORLD_TASK_IDS="9aae7da_1 365e0a3_1 eb5ad85_1 5e27cd7_1"
DEFAULT_BENCHMARK="appworld"
DEFAULT_NUM_TASKS="4"
DEFAULT_AGENT="react"
DEFAULT_PROVIDER="rits"

MODEL_NAME="${MODEL_NAME:-$DEFAULT_MODEL_NAME}"
TASK_IDS="${TASK_IDS:-}"
EVAL_KEY="${EVAL_KEY:-}"
BENCHMARK="${BENCHMARK:-$DEFAULT_BENCHMARK}"
NUM_TASKS="${NUM_TASKS:-$DEFAULT_NUM_TASKS}"
AGENT="${AGENT:-$DEFAULT_AGENT}"
PROVIDER="${PROVIDER:-$DEFAULT_PROVIDER}"
MODEL_NAME_FROM_COMMENT=false

# Parse whitespace-separated key=value parameters from the PR comment.
# Supported aliases:
#   model_name=...
#   task_id=id1,id2
#   task_ids=id1,id2
#   eval_key=test_easy|test_med|test_hard|...
#   benchmark=appworld|m3
#   num_tasks=...
#   agent=react|cuga|codeact
#   provider=rits|litellm
COMMENT_BODY="${1:-}"

# Remove Windows carriage returns and newlines.
COMMENT_BODY="${COMMENT_BODY//$'\r'/ }"
COMMENT_BODY="${COMMENT_BODY//$'\n'/ }"

read -r -a TOKENS <<< "${COMMENT_BODY}"
echo "######## REPORT START ########"
open_details "Requested parameters"
for token in "${TOKENS[@]}"; do
  case "${token}" in
    /run-pr-eval)
      ;;

    model_name=*)
      MODEL_NAME="${token#model_name=}"
      MODEL_NAME_FROM_COMMENT=true
      ;;

    task_id=*|task_ids=*)
      TASK_IDS="${token#*=}"
      TASK_IDS="${TASK_IDS//,/ }"
      ;;

    eval_key=*|eval-key=*)
      EVAL_KEY="${token#*=}"
      ;;

    benchmark=*)
      BENCHMARK="${token#benchmark=}"
      ;;

    num_tasks=*)
      NUM_TASKS="${token#num_tasks=}"
      ;;

    agent=*|agent_type=*)
      AGENT="${token#*=}"
      ;;

    provider=*)
      PROVIDER="${token#provider=}"
      ;;

    "")
      ;;

    *)
      echo "ERROR: Unsupported parameter: ${token}"
      echo "Supported parameters: model_name, task_id, task_ids, eval_key, benchmark, num_tasks, agent, provider"
      close_details
      echo "######## REPORT END ########"
      exit 2
      ;;
  esac
done

if [[ -z "${MODEL_NAME}" ]]; then
  echo "ERROR: model_name cannot be empty."
  close_details
  echo "######## REPORT END ########"
  exit 2
fi

if [[ ! "${NUM_TASKS}" =~ ^[0-9]+$ ]] || [[ "${NUM_TASKS}" -lt 1 ]]; then
  echo "ERROR: num_tasks must be a positive integer."
  close_details
  echo "######## REPORT END ########"
  exit 2
fi

AGENT="$(printf '%s' "${AGENT}" | tr '[:upper:]' '[:lower:]')"
BENCHMARK="$(printf '%s' "${BENCHMARK}" | tr '[:upper:]' '[:lower:]')"
PROVIDER="$(printf '%s' "${PROVIDER}" | tr '[:upper:]' '[:lower:]')"
EVAL_KEY="$(printf '%s' "${EVAL_KEY}" | tr '[:upper:]' '[:lower:]')"

case "${AGENT}" in
  react|cuga|codeact)
    ;;
  *)
    echo "ERROR: agent must be one of: react, cuga, codeact."
    close_details
    echo "######## REPORT END ########"
    exit 2
    ;;
esac

case "${BENCHMARK}" in
  appworld|m3)
    ;;
  *)
    echo "ERROR: benchmark must be one of: appworld, m3."
    close_details
    echo "######## REPORT END ########"
    exit 2
    ;;
esac

if [[ -n "${EVAL_KEY}" && "${BENCHMARK}" != "appworld" ]]; then
  echo "ERROR: eval_key is only supported for benchmark=appworld."
  close_details
  echo "######## REPORT END ########"
  exit 2
fi

case "${PROVIDER}" in
  rits)
    AGENT_SETTING_CONFIG="settings.rits.toml"
    if [[ -z "${RITS_API_KEY:-}" ]]; then
      echo "ERROR: RITS_API_KEY is required when provider=rits."
      close_details
      echo "######## REPORT END ########"
      exit 2
    fi
    ;;
  litellm)
    if [[ "${AGENT}" == "cuga" ]]; then
      AGENT_SETTING_CONFIG="settings.litellm.toml"
    else
      AGENT_SETTING_CONFIG="settings.openai.toml"
    fi
    if [[ "${MODEL_NAME_FROM_COMMENT}" == "false" ]]; then
      MODEL_NAME="${DEFAULT_LITELLM_MODEL_NAME}"
    fi
    OPENAI_BASE_URL="${LITE_LLM_URL:-${OPENAI_BASE_URL:-https://ete-litellm.ai-models.vpc-int.res.ibm.com/}}"
    OPENAI_API_KEY="${LITE_LLM_KEY:-${OPENAI_API_KEY:-}}"
    if [[ -z "${OPENAI_API_KEY:-}" ]]; then
      echo "ERROR: LITE_LLM_KEY or OPENAI_API_KEY is required when provider=litellm."
      close_details
      echo "######## REPORT END ########"
      exit 2
    fi
    if [[ -z "${OPENAI_BASE_URL:-}" ]]; then
      echo "ERROR: LITE_LLM_URL or OPENAI_BASE_URL is required when provider=litellm."
      close_details
      echo "######## REPORT END ########"
      exit 2
    fi
    export OPENAI_API_KEY OPENAI_BASE_URL
    ;;
  *)
    echo "ERROR: provider must be one of: rits, litellm."
    close_details
    echo "######## REPORT END ########"
    exit 2
    ;;
esac

if [[ "${PROVIDER}" == "rits" ]]; then
  export OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://inference-3scale-apicast-production.apps.rits.fmaas.res.ibm.com/gpt-oss-120b-a100}"
  if [[ -z "${RITS_BASE_URL:-}" ]]; then
    RITS_BASE_URL="${OPENAI_BASE_URL%/}"
    [[ "${RITS_BASE_URL}" == */v1 ]] || RITS_BASE_URL="${RITS_BASE_URL}/v1"
    export RITS_BASE_URL
  fi
else
  :
fi

if [[ -z "${TASK_IDS}" && -z "${EVAL_KEY}" && "${BENCHMARK}" == "appworld" ]]; then
  TASK_IDS="${DEFAULT_APPWORLD_TASK_IDS}"
fi

read -r -a TASK_ID_ARRAY <<< "${TASK_IDS}"

if [[ ${#TASK_ID_ARRAY[@]} -eq 0 && -z "${EVAL_KEY}" && "${BENCHMARK}" == "appworld" ]]; then
  echo "ERROR: At least one task_id or eval_key is required for benchmark=appworld."
  close_details
  echo "######## REPORT END ########"
  exit 2
fi
echo "- Model: ${MODEL_NAME}"
echo "- Agent: ${AGENT}"
echo "- Benchmark: ${BENCHMARK}"
echo "- Provider: ${PROVIDER}"
if [[ -n "${EVAL_KEY}" ]]; then
  echo "- Eval key: ${EVAL_KEY}"
fi
echo "- Num tasks: ${NUM_TASKS}"
if [[ ${#TASK_ID_ARRAY[@]} -gt 0 ]]; then
  echo "- Task IDs: ${TASK_IDS}"
else
  echo "- Task IDs: benchmark default"
fi
close_details
echo "######## REPORT END ########"

# For AppWorld, num_tasks limits the explicit task list. M3 maps num_tasks to
# --max-samples-per-domain below.
if [[ "${BENCHMARK}" == "appworld" && ${NUM_TASKS} -lt ${#TASK_ID_ARRAY[@]} ]]; then
  TASK_ID_ARRAY=("${TASK_ID_ARRAY[@]:0:${NUM_TASKS}}")
fi

export AGENT_SETTING_CONFIG
export DYNACONF_ADVANCED_FEATURES__LANGFUSE_TRACING="${DYNACONF_ADVANCED_FEATURES__LANGFUSE_TRACING:-false}"
export MODEL_NAME

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "${EVAL_REPO:-}" ]]; then
  if [[ -f "${SCRIPT_DIR}/../../scripts/eval.sh" ]]; then
    EVAL_REPO="$(cd "${SCRIPT_DIR}/../.." && pwd)"
  else
    EVAL_REPO="$(cd "${SCRIPT_DIR}/.." && pwd)"
  fi
fi

if [[ ! -d "${EVAL_REPO}" ]]; then
  echo "ERROR: Evaluation repo not found: ${EVAL_REPO}"
  exit 1
fi

if [[ ! -f "${EVAL_REPO}/scripts/eval.sh" ]]; then
  echo "ERROR: Evaluation script not found: ${EVAL_REPO}/scripts/eval.sh"
  exit 1
fi

cd "${EVAL_REPO}"

echo "######## REPORT START ########"
echo "## Evaluation Metrics"
echo
open_details "Run metadata"
echo "- Repository: ${GITHUB_REPOSITORY:-unknown}"
echo "- PR: ${PR_NUMBER:-unknown}"
echo "- Commit: ${PR_HEAD_SHA:-$(git rev-parse HEAD 2>/dev/null || echo unknown)}"
echo "- Runner: ${RUNNER_NAME:-$(hostname)}"
echo "- Agent: ${AGENT}"
echo "- Benchmark: ${BENCHMARK}"
echo "- Provider: ${PROVIDER}"
close_details
echo
open_details "Evaluation configuration"
echo "- Agent: ${AGENT}"
echo "- Benchmark: ${BENCHMARK}"
echo "- Provider: ${PROVIDER}"
echo "- Agent setting config: ${AGENT_SETTING_CONFIG}"
echo "- Model: ${MODEL_NAME}"
echo "- Requested num_tasks: ${NUM_TASKS}"
if [[ "${BENCHMARK}" == "appworld" ]]; then
  if [[ -n "${EVAL_KEY}" ]]; then
    echo "- Eval key: ${EVAL_KEY}"
  fi
  if [[ ${#TASK_ID_ARRAY[@]} -gt 0 ]]; then
    echo "- Effective task count: ${#TASK_ID_ARRAY[@]}"
    echo "- Task IDs:"
    for task_id in "${TASK_ID_ARRAY[@]}"; do
      echo "  - ${task_id}"
    done
  else
    echo "- Task IDs: selected by eval_key"
  fi
else
  echo "- M3 max samples per domain: ${NUM_TASKS}"
  if [[ ${#TASK_ID_ARRAY[@]} -gt 0 ]]; then
    echo "- M3 task filters:"
    for task_id in "${TASK_ID_ARRAY[@]}"; do
      echo "  - ${task_id}"
    done
  else
    echo "- M3 task filters: benchmark default"
  fi
fi
close_details
echo "######## REPORT END ########"

log "Verifying required commands"
command -v uv >/dev/null 2>&1 || {
  echo "ERROR: uv is not installed or is not in PATH."
  exit 127
}

command -v curl >/dev/null 2>&1 || {
  echo "ERROR: curl is not installed or is not in PATH."
  exit 127
}

log "Starting ${BENCHMARK} ${AGENT} evaluation"

EVAL_ARGS=(
  --benchmark "${BENCHMARK}"
  --agent "${AGENT}"
)

if [[ "${BENCHMARK}" == "appworld" ]]; then
  if [[ -n "${EVAL_KEY}" ]]; then
    EVAL_ARGS+=(--eval-key "${EVAL_KEY}")
  fi
  if [[ ${#TASK_ID_ARRAY[@]} -gt 0 ]]; then
    EVAL_ARGS+=(--task "${TASK_ID_ARRAY[@]}")
  fi
else
  EVAL_ARGS+=(--m3-data --max-samples-per-domain "${NUM_TASKS}")
  if [[ ${#TASK_ID_ARRAY[@]} -gt 0 ]]; then
    EVAL_ARGS+=(--task "${TASK_ID_ARRAY[@]}")
  fi
fi

bash scripts/eval.sh "${EVAL_ARGS[@]}"
