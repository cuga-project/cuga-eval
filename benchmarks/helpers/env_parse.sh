#!/bin/bash
# Shared .env parser used by both load_env.sh (no-override base load) and
# common.sh (force-export --dotenv overrides). A single implementation keeps the
# two passes from drifting on quoting / inline-comment edge cases.

# Idempotent source guard.
[[ -n "${_ENV_PARSE_SH_SOURCED:-}" ]] && return 0
_ENV_PARSE_SH_SOURCED=1

# Parse one env file and export its KEY=VALUE assignments.
#   $1 file       path to the env file
#   $2 override   "true"  (default) → always export (force);
#                 "false"           → skip keys already set in the environment
#                                     (lets profile exports win over .env defaults)
#   $3 echo_vars  "true"            → print "  ↳ KEY=VALUE" for each exported var
#                 anything else (default) → silent
# Mirrors python-dotenv: strips inline comments on unquoted values and surrounding
# single/double quotes. Lines that are not assignments are skipped.
_parse_env_file() {
    local file="$1" override="${2:-true}" echo_vars="${3:-false}"
    local line key val
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${line//[[:space:]]/}" ]] && continue
        if [[ "$line" =~ ^[[:space:]]*export[[:space:]]+([A-Za-z_][A-Za-z0-9_]*)=(.*) ]]; then
            key="${BASH_REMATCH[1]}"
            val="${BASH_REMATCH[2]}"
        elif [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*) ]]; then
            key="${BASH_REMATCH[1]}"
            val="${BASH_REMATCH[2]}"
        else
            continue
        fi
        # In no-override mode, an already-set variable wins (e.g. profile exports).
        if [[ "$override" != "true" && -n "${!key+x}" ]]; then
            continue
        fi
        # Strip inline comments from unquoted values (python-dotenv parity).
        if [[ "$val" != \"*\" && "$val" != \'*\' ]]; then
            val="${val%%[[:space:]]#*}"
            val="${val%"${val##*[![:space:]]}"}"
        fi
        # Strip surrounding quotes
        val="${val#\"}" ; val="${val%\"}"
        val="${val#\'}" ; val="${val%\'}"
        export "$key=$val"
        if [[ "$echo_vars" == "true" ]]; then
            echo -e "  ${GREEN:-}↳${NC:-} $key=$val"
        fi
    done < "$file"
}
