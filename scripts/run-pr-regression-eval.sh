#!/usr/bin/env bash
set -Eeuo pipefail

START_EPOCH="$(date +%s)"
START_TIME="$(date -u +"%Y-%m-%d %H:%M:%S UTC")"

log() {
  printf '[%s] %s\n' "$(date -u +"%Y-%m-%d %H:%M:%S UTC")" "$*"
}

on_exit() {
  status=$?
  end_epoch="$(date +%s)"
  end_time="$(date -u +"%Y-%m-%d %H:%M:%S UTC")"
  duration=$((end_epoch - START_EPOCH
  
  minutes=$((duration / 60))
  seconds=$((duration % 60))))
  

  echo "######## REPORT START ########"
  echo
  echo "## Run summary"
  echo "- Started: ${START_TIME}"
  echo "- Finished: ${end_time}"
  echo "- Duration: ${minutes}m ${seconds}s"
  echo "- Exit code: ${status}"

  if [[ ${status} -eq 0 ]]; then
    echo "- Result: SUCCESS"
  else
    echo "- Result: FAILED"
  fi
  echo "######## REPORT END ########"
}
trap on_exit EXIT

: "${OPENAI_API_KEY:?OPENAI_API_KEY is required}"

DEFAULT_MODEL_NAME="openai/gpt-oss-120b-a100"
DEFAULT_TASK_IDS="9aae7da_1 365e0a3_1 eb5ad85_1 5e27cd7_1"
DEFAULT_SPLIT_NAME="default"
DEFAULT_NUM_TASKS="4"

MODEL_NAME="${MODEL_NAME:-$DEFAULT_MODEL_NAME}"
TASK_IDS="${TASK_IDS:-$DEFAULT_TASK_IDS}"
SPLIT_NAME="${SPLIT_NAME:-$DEFAULT_SPLIT_NAME}"
NUM_TASKS="${NUM_TASKS:-$DEFAULT_NUM_TASKS}"

# Parse whitespace-separated key=value parameters from the PR comment.
# Supported aliases:
#   model_name=...
#   task_id=id1,id2
#   task_ids=id1,id2
#   split_name=...
#   num_tasks=...
COMMENT_BODY="${1:-}"

# Remove Windows carriage returns and newlines.
COMMENT_BODY="${COMMENT_BODY//$'\r'/ }"
COMMENT_BODY="${COMMENT_BODY//$'\n'/ }"

read -r -a TOKENS <<< "${COMMENT_BODY}"
echo "######## REPORT START ########"
for token in "${TOKENS[@]}"; do
  case "${token}" in
    /run-eval|/appworld-eval)
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

    "")
      ;;

    *)
      echo "ERROR: Unsupported parameter: ${token}"
      echo "Supported parameters: model_name, task_id, task_ids, split_name, num_tasks"
      exit 2
      ;;
  esac
done

if [[ -z "${MODEL_NAME}" ]]; then
  echo "ERROR: model_name cannot be empty."
  exit 2
fi

if [[ ! "${NUM_TASKS}" =~ ^[0-9]+$ ]] || [[ "${NUM_TASKS}" -lt 1 ]]; then
  echo "ERROR: num_tasks must be a positive integer."
  exit 2
fi

read -r -a TASK_ID_ARRAY <<< "${TASK_IDS}"

if [[ ${#TASK_ID_ARRAY[@]} -eq 0 ]]; then
  echo "ERROR: At least one task_id is required."
  exit 2
fi
echo "######## REPORT END ########"

# num_tasks is currently a dummy input, but limit the supplied task list to make
# the mock behavior predictable.
if [[ ${NUM_TASKS} -lt ${#TASK_ID_ARRAY[@]} ]]; then
  TASK_ID_ARRAY=("${TASK_ID_ARRAY[@]:0:${NUM_TASKS}}")
fi

export DYNACONF_SERVER_PORTS__REGISTRY="${DYNACONF_SERVER_PORTS__REGISTRY:-8100}"
export AGENT_SETTING_CONFIG="${AGENT_SETTING_CONFIG:-settings.rits.toml}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://inference-3scale-apicast-production.apps.rits.fmaas.res.ibm.com/gpt-oss-120b-a100}"
export MODEL_NAME
export ENVIRONMENT_URL="${ENVIRONMENT_URL:-http://127.0.0.1:8000}"
export APIS_URL="${APIS_URL:-http://127.0.0.1:9000}"

EVAL_REPO="/proj/cuga_models/cuga-eval"

if [[ ! -d "${EVAL_REPO}" ]]; then
  echo "ERROR: Evaluation repo not found: ${EVAL_REPO}"
  exit 1
fi

cd "${EVAL_REPO}"

echo "######## REPORT START ########"
echo "# PR Evaluation"
echo
echo "## Run metadata"
echo "- Repository: ${GITHUB_REPOSITORY:-unknown}"
echo "- PR: ${PR_NUMBER:-unknown}"
echo "- Commit: ${PR_HEAD_SHA:-$(git rev-parse HEAD 2>/dev/null || echo unknown)}"
echo "- Runner: ${RUNNER_NAME:-$(hostname)}"
echo
echo "## Evaluation configuration"
echo "- Model: ${MODEL_NAME}"
echo "- Split: ${SPLIT_NAME}"
echo "- Requested num_tasks: ${NUM_TASKS}"
echo "- Effective task count: ${#TASK_ID_ARRAY[@]}"
echo "- Task IDs:"
for task_id in "${TASK_ID_ARRAY[@]}"; do
  echo "  - ${task_id}"
done
echo
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

log "Verifying local benchmark services"
for endpoint in "${ENVIRONMENT_URL}" "${APIS_URL}"; do
  if ! curl --silent --show-error --fail --max-time 5 "${endpoint}" >/dev/null; then
    echo "ERROR: Required service is unavailable at ${endpoint}"
    exit 1
  fi
done

log "Starting AppWorld React evaluation"

uv run --no-sync python -m benchmarks.appworld.appworld_eval_react \
  --agent react \
  --task-id "${TASK_ID_ARRAY[@]}" \
  --environment-url "${ENVIRONMENT_URL}" \
  --apis-url "${APIS_URL}"
