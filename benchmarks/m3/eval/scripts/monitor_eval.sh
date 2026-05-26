#!/bin/bash
# M3 Evaluation Monitor
#
# Monitors a running evaluation and reports progress every 30 minutes
#
# Usage:
#   ./monitor_eval.sh <status_file> [log_file]
#
# Example:
#   ./monitor_eval.sh logs/eval_20260227_001234.status logs/eval_20260227_001234.log

set -e

STATUS_FILE=${1}
LOG_FILE=${2}

if [ -z "${STATUS_FILE}" ]; then
    echo "Error: Status file required"
    echo "Usage: $0 <status_file> [log_file]"
    echo ""
    echo "Available status files:"
    ls -t ../logs/*.status 2>/dev/null | head -5 || echo "  No status files found"
    exit 1
fi

if [ ! -f "${STATUS_FILE}" ]; then
    echo "Error: Status file not found: ${STATUS_FILE}"
    exit 1
fi

# Function to calculate duration
calculate_duration() {
    local start_time=$1
    local current_time=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    if command -v python3 &> /dev/null; then
        python3 -c "
from datetime import datetime
start = datetime.fromisoformat('${start_time}'.replace('Z', '+00:00'))
end = datetime.fromisoformat('${current_time}'.replace('Z', '+00:00'))
delta = end - start
hours = int(delta.total_seconds() // 3600)
minutes = int((delta.total_seconds() % 3600) // 60)
seconds = int(delta.total_seconds() % 60)
print(f'{hours}h {minutes}m {seconds}s')
" 2>/dev/null || echo "unknown"
    else
        echo "unknown"
    fi
}

# Function to count completed domains
count_completed_domains() {
    local log_file=$1
    if [ -f "${log_file}" ]; then
        # Count "Completed domain:" messages
        grep -c "Completed domain:" "${log_file}" 2>/dev/null || echo "0"
    else
        echo "0"
    fi
}

# Function to get total domains
get_total_domains() {
    local log_file=$1
    if [ -f "${log_file}" ]; then
        # Each task logs "Domains: <name>" on its own line — count total lines
        grep -c "Domains:" "${log_file}" 2>/dev/null || echo "0"
    else
        echo "unknown"
    fi
}

# Function to display status
display_status() {
    local status_file=$1
    local log_file=$2

    # Read status file
    if [ ! -f "${status_file}" ]; then
        echo "Status file not found"
        return
    fi

    local status=$(grep '"status":' "${status_file}" | cut -d'"' -f4)
    local start_time=$(grep '"start_time":' "${status_file}" | cut -d'"' -f4)
    local start_time_local=$(grep '"start_time_local":' "${status_file}" | cut -d'"' -f4)
    local batch_size=$(grep '"batch_size":' "${status_file}" | cut -d'"' -f4)

    # Calculate duration
    local duration=$(calculate_duration "${start_time}")

    # Count completed domains
    local completed=0
    local total="unknown"
    if [ -n "${log_file}" ] && [ -f "${log_file}" ]; then
        completed=$(count_completed_domains "${log_file}")
        total=$(get_total_domains "${log_file}")
    fi

    # Display status
    echo "=================================================="
    echo "M3 Evaluation Status - $(date +"%Y-%m-%d %H:%M:%S")"
    echo "=================================================="
    echo "Status:              ${status}"
    echo "Start Time:          ${start_time_local}"
    echo "Execution Time:      ${duration}"
    echo "Batch Size:          ${batch_size}"
    if [ "${total}" != "unknown" ]; then
        echo "Progress:            ${completed}/${total} domains completed"
        if [ "${total}" != "0" ] && [ "${total}" != "unknown" ]; then
            local percent=$((completed * 100 / total))
            echo "Completion:          ${percent}%"
        fi
    else
        echo "Progress:            ${completed} domains completed"
    fi
    echo "=================================================="
    echo ""
}

# Main monitoring loop
echo "Starting M3 Evaluation Monitor"
echo "Status File: ${STATUS_FILE}"
if [ -n "${LOG_FILE}" ]; then
    echo "Log File:    ${LOG_FILE}"
fi
echo ""
echo "Monitoring every 30 minutes (press Ctrl+C to stop)"
echo ""

# Display initial status
display_status "${STATUS_FILE}" "${LOG_FILE}"

# Monitor loop
while true; do
    # Check if evaluation is still running
    status=$(grep '"status":' "${STATUS_FILE}" 2>/dev/null | cut -d'"' -f4 || echo "unknown")

    if [ "${status}" = "completed" ] || [ "${status}" = "failed" ]; then
        echo "Evaluation ${status}!"
        display_status "${STATUS_FILE}" "${LOG_FILE}"

        # Show final summary from status file
        if [ -f "${STATUS_FILE}" ]; then
            echo "Final Status:"
            cat "${STATUS_FILE}"
        fi
        break
    fi

    # Wait 30 minutes
    sleep 1800

    # Display status update
    display_status "${STATUS_FILE}" "${LOG_FILE}"
done

# Made with Bob
