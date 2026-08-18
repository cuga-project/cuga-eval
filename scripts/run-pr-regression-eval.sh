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
DEFAULT_TASK_IDS="9aae7da_1 365e0a3_1 eb5ad85_1 5e27cd7_1"
DEFAULT_SPLIT_NAME="default"
DEFAULT_NUM_TASKS="4"
DEFAULT_AGENT="react"
DEFAULT_AGENT_SETTING_CONFIG="settings.rits.toml"

MODEL_NAME="${MODEL_NAME:-$DEFAULT_MODEL_NAME}"
TASK_IDS="${TASK_IDS:-$DEFAULT_TASK_IDS}"
SPLIT_NAME="${SPLIT_NAME:-$DEFAULT_SPLIT_NAME}"
NUM_TASKS="${NUM_TASKS:-$DEFAULT_NUM_TASKS}"
AGENT="${AGENT:-$DEFAULT_AGENT}"
AGENT_SETTING_CONFIG="${AGENT_SETTING_CONFIG:-$DEFAULT_AGENT_SETTING_CONFIG}"

# Parse whitespace-separated key=value parameters from the PR comment.
# Supported aliases:
#   model_name=...
#   task_id=id1,id2
#   task_ids=id1,id2
#   split_name=...
#   num_tasks=...
#   agent=react|cuga|codeact
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
      ;;

    task_id=*|task_ids=*)
      TASK_IDS="${token#*=}"
      TASK_IDS="${TASK_IDS//,/ }"
      ;;

    split_name=*)
      SPLIT_NAME="${token#split_name=}"
      ;;

    num_tasks=*)
      NUM_TASKS="${token#num_tasks=}"
      ;;

    agent=*|agent_type=*)
      AGENT="${token#*=}"
      ;;

    "")
      ;;

    *)
      echo "ERROR: Unsupported parameter: ${token}"
      echo "Supported parameters: model_name, task_id, task_ids, split_name, num_tasks, agent"
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

case "${AGENT_SETTING_CONFIG}" in
  settings.rits.toml|settings.rits.proxy.toml)
    if [[ -z "${RITS_API_KEY:-}" ]]; then
      echo "ERROR: RITS_API_KEY is required when AGENT_SETTING_CONFIG=${AGENT_SETTING_CONFIG}."
      close_details
      echo "######## REPORT END ########"
      exit 2
    fi
    ;;
  *)
    if [[ -z "${OPENAI_API_KEY:-}" ]]; then
      echo "ERROR: OPENAI_API_KEY is required when AGENT_SETTING_CONFIG=${AGENT_SETTING_CONFIG}."
      close_details
      echo "######## REPORT END ########"
      exit 2
    fi
    ;;
esac

read -r -a TASK_ID_ARRAY <<< "${TASK_IDS}"

if [[ ${#TASK_ID_ARRAY[@]} -eq 0 ]]; then
  echo "ERROR: At least one task_id is required."
  close_details
  echo "######## REPORT END ########"
  exit 2
fi
echo "- Model: ${MODEL_NAME}"
echo "- Agent: ${AGENT}"
echo "- Split: ${SPLIT_NAME}"
echo "- Num tasks: ${NUM_TASKS}"
echo "- Task IDs: ${TASK_IDS}"
close_details
echo "######## REPORT END ########"

# num_tasks is currently a dummy input, but limit the supplied task list to make
# the mock behavior predictable.
if [[ ${NUM_TASKS} -lt ${#TASK_ID_ARRAY[@]} ]]; then
  TASK_ID_ARRAY=("${TASK_ID_ARRAY[@]:0:${NUM_TASKS}}")
fi

export AGENT_SETTING_CONFIG
export DYNACONF_ADVANCED_FEATURES__LANGFUSE_TRACING="${DYNACONF_ADVANCED_FEATURES__LANGFUSE_TRACING:-false}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://inference-3scale-apicast-production.apps.rits.fmaas.res.ibm.com/gpt-oss-120b-a100}"
if [[ -z "${RITS_BASE_URL:-}" ]]; then
  RITS_BASE_URL="${OPENAI_BASE_URL%/}"
  [[ "${RITS_BASE_URL}" == */v1 ]] || RITS_BASE_URL="${RITS_BASE_URL}/v1"
  export RITS_BASE_URL
fi
export MODEL_NAME

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVAL_REPO="${EVAL_REPO:-$(cd "${SCRIPT_DIR}/.." && pwd)}"

if [[ ! -d "${EVAL_REPO}" ]]; then
  echo "ERROR: Evaluation repo not found: ${EVAL_REPO}"
  exit 1
fi

cd "${EVAL_REPO}"

echo "######## REPORT START ########"
echo "# PR Evaluation"
echo
open_details "Run metadata"
echo "- Repository: ${GITHUB_REPOSITORY:-unknown}"
echo "- PR: ${PR_NUMBER:-unknown}"
echo "- Commit: ${PR_HEAD_SHA:-$(git rev-parse HEAD 2>/dev/null || echo unknown)}"
echo "- Runner: ${RUNNER_NAME:-$(hostname)}"
echo "- Agent: ${AGENT}"
close_details
echo
open_details "Evaluation configuration"
echo "- Agent: ${AGENT}"
echo "- Model: ${MODEL_NAME}"
echo "- Split: ${SPLIT_NAME}"
echo "- Requested num_tasks: ${NUM_TASKS}"
echo "- Effective task count: ${#TASK_ID_ARRAY[@]}"
echo "- Task IDs:"
for task_id in "${TASK_ID_ARRAY[@]}"; do
  echo "  - ${task_id}"
done
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

log "Starting AppWorld ${AGENT} evaluation"

EVAL_ARGS=(
  --agent "${AGENT}"
  --task "${TASK_ID_ARRAY[@]}"
)

bash benchmarks/appworld/eval.sh "${EVAL_ARGS[@]}"
