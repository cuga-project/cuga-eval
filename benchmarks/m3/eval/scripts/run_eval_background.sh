#!/bin/bash
# M3 Evaluation Background Runner
#
# Runs M3 evaluation in the background with configurable batch size
# Logs start/end times and captures all output
#
# Usage:
#   ./run_eval_background.sh [batch_size] [data_dir] [model_name]
#
# Examples:
#   ./run_eval_background.sh 10                              # Run with batch size 10
#   ./run_eval_background.sh 10 /path/to/data               # Run with custom data directory
#   ./run_eval_background.sh "" /path/to/data               # No batching, custom data dir
#   ./run_eval_background.sh "" "" meta-llama/llama-3-70b   # No batching, custom model
#   ./run_eval_background.sh 10 "" meta-llama/llama-3-70b   # Batch size 10, custom model
#   ./run_eval_background.sh                                 # Run without batching (all in parallel)
#
# Environment Variables:
#   M3_DATA_DIR:  Custom directory for input JSON files (can also be passed as 2nd arg)
#   MODEL_NAME:   Model identifier to use for evaluation (can also be passed as 3rd arg)

set -e

# Configuration
BATCH_SIZE=${1:-""}   # Optional: batch size (empty = no batching)
DATA_DIR=${2:-""}     # Optional: custom data directory
# 3rd arg takes priority; falls back to MODEL_NAME env var if already exported
MODEL_NAME=${3:-${MODEL_NAME:-""}}

# Get absolute paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
M3_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
EVAL_DIR="${M3_ROOT}/eval"
LOG_DIR="${EVAL_DIR}/logs"

CONFIG_FILE="${M3_ROOT}/config/m3_registry.yaml"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="${LOG_DIR}/eval_${TIMESTAMP}.log"
PID_FILE="${LOG_DIR}/eval_${TIMESTAMP}.pid"
STATUS_FILE="${LOG_DIR}/eval_${TIMESTAMP}.status"

# Create logs directory if it doesn't exist
mkdir -p "${LOG_DIR}"

# Set M3_DATA_DIR if provided as argument (overrides environment variable)
if [ -n "${DATA_DIR}" ]; then
    export M3_DATA_DIR="${DATA_DIR}"
fi

# Set MODEL_NAME if provided as argument (overrides environment variable)
if [ -n "${MODEL_NAME}" ]; then
    export MODEL_NAME="${MODEL_NAME}"
fi

# Build command (will run from M3 root directory)
# Prepend MODEL_NAME env var so the agent picks it up at runtime
if [ -n "${MODEL_NAME}" ]; then
    CMD="cd ${M3_ROOT} && MODEL_NAME=${MODEL_NAME} uv run python eval_m3.py --from-config ${CONFIG_FILE}"
else
    CMD="cd ${M3_ROOT} && uv run python eval_m3.py --from-config ${CONFIG_FILE}"
fi

if [ -n "${BATCH_SIZE}" ]; then
    CMD="${CMD} --batch-size ${BATCH_SIZE}"
fi

# Print configuration
echo "=================================================="
echo "M3 Evaluation - Background Runner"
echo "=================================================="
echo "Timestamp:       ${TIMESTAMP}"
echo "Config:          ${CONFIG_FILE}"
echo "Batch Size:      ${BATCH_SIZE:-"No batching (run all in parallel)"}"
echo "Data Directory:  ${M3_DATA_DIR:-"${M3_ROOT}/data (default)"}"
echo "Model:           ${MODEL_NAME:-"default (from .env / m3.env)"}"
echo "Log File:        ${LOG_FILE}"
echo "PID File:        ${PID_FILE}"
echo "Status File:     ${STATUS_FILE}"
echo "=================================================="
echo ""

# Write initial status
cat > "${STATUS_FILE}" << EOF
{
  "status": "starting",
  "start_time": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "start_time_local": "$(date +"%Y-%m-%d %H:%M:%S %Z")",
  "batch_size": "${BATCH_SIZE:-"none"}",
  "data_dir": "${M3_DATA_DIR:-"default"}",
  "model_name": "${MODEL_NAME:-"default"}",
  "config_file": "${CONFIG_FILE}",
  "log_file": "${LOG_FILE}",
  "pid_file": "${PID_FILE}"
}
EOF

# Function to update status on completion
update_status_on_exit() {
    local exit_code=$?
    local end_time=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    local end_time_local=$(date +"%Y-%m-%d %H:%M:%S %Z")

    if [ $exit_code -eq 0 ]; then
        status="completed"
    else
        status="failed"
    fi

    # Calculate duration if start time exists
    if [ -f "${STATUS_FILE}" ]; then
        start_time=$(grep '"start_time":' "${STATUS_FILE}" | cut -d'"' -f4)
        if command -v python3 &> /dev/null; then
            duration=$(python3 -c "
from datetime import datetime
start = datetime.fromisoformat('${start_time}'.replace('Z', '+00:00'))
end = datetime.fromisoformat('${end_time}'.replace('Z', '+00:00'))
delta = end - start
hours = int(delta.total_seconds() // 3600)
minutes = int((delta.total_seconds() % 3600) // 60)
seconds = int(delta.total_seconds() % 60)
print(f'{hours}h {minutes}m {seconds}s')
" 2>/dev/null || echo "unknown")
        else
            duration="unknown"
        fi
    else
        duration="unknown"
    fi

    # Update status file
    cat > "${STATUS_FILE}" << EOF
{
  "status": "${status}",
  "exit_code": ${exit_code},
  "start_time": "$(grep '"start_time":' "${STATUS_FILE}" 2>/dev/null | cut -d'"' -f4 || echo "unknown")",
  "start_time_local": "$(grep '"start_time_local":' "${STATUS_FILE}" 2>/dev/null | cut -d'"' -f4 || echo "unknown")",
  "end_time": "${end_time}",
  "end_time_local": "${end_time_local}",
  "duration": "${duration}",
  "batch_size": "${BATCH_SIZE:-"none"}",
  "config_file": "${CONFIG_FILE}",
  "log_file": "${LOG_FILE}",
  "pid_file": "${PID_FILE}"
}
EOF

    echo ""
    echo "=================================================="
    echo "Evaluation ${status}"
    echo "=================================================="
    echo "Start Time:  $(grep '"start_time_local":' "${STATUS_FILE}" | cut -d'"' -f4)"
    echo "End Time:    ${end_time_local}"
    echo "Duration:    ${duration}"
    echo "Exit Code:   ${exit_code}"
    echo "Log File:    ${LOG_FILE}"
    echo "Status File: ${STATUS_FILE}"
    echo "=================================================="
}

# Run in background with output redirection
echo "Starting evaluation in background..."
echo "Command: ${CMD}"
echo ""

# Start the evaluation
(
    # Set trap to update status on exit
    trap update_status_on_exit EXIT

    # Update status to running
    sed -i.bak 's/"status": "starting"/"status": "running"/' "${STATUS_FILE}" 2>/dev/null || true

    # Run the evaluation (go to m3 root directory)
    cd "$(dirname "$0")/../.."
    eval "${CMD}" > "${LOG_FILE}" 2>&1
) > /dev/null 2>&1 &

# Save PID
EVAL_PID=$!
echo "${EVAL_PID}" > "${PID_FILE}"

echo "✅ Evaluation started in background"
echo "   PID: ${EVAL_PID}"
echo "   Log: tail -f ${LOG_FILE}"
echo "   Status: cat ${STATUS_FILE}"
echo ""
echo "To check if still running:"
echo "   ps -p ${EVAL_PID}"
echo ""
echo "To stop the evaluation:"
echo "   kill ${EVAL_PID}"
echo ""
echo "To view live output:"
echo "   tail -f ${LOG_FILE}"
echo ""

# Made with Bob
