#!/bin/bash
# =============================================================================
# M3 Benchmark - Evaluation Environment Setup Script
#
# This script prepares the environment for running the M3 evaluation:
#   1. Detects and configures the container runtime (podman/docker)
#   2. Prompts for required API keys and writes them to .env
#   3. Installs cuga-agent (clone in parent directory next to this repo) via setup_cuga.sh
#   4. Verifies the setup is ready to run
#
# Usage (run from project root):
#   bash benchmarks/m3/eval/scripts/setup_m3_eval.sh
#
# After setup, run the evaluation with:
#   cd benchmarks/m3
#   uv run python eval_m3.py --from-config config/m3_registry.yaml
# =============================================================================

set -e

# =============================================================================
# Configuration — edit these values to customise the setup
# =============================================================================

# Path to the enterprise-benchmark repo (cloned into vendor/ if not present)
# Override with: ENTERPRISE_BENCHMARK_DIR=/path/to/repo bash setup_m3_eval.sh
ENTERPRISE_BENCHMARK_DIR="${ENTERPRISE_BENCHMARK_DIR:-}"   # resolved after PROJECT_ROOT is known

# Git SSH URL for the enterprise-benchmark repo (IBM internal)
ENTERPRISE_BENCHMARK_REPO="${ENTERPRISE_BENCHMARK_REPO:-git@github.ibm.com:AI4BA/enterprise-benchmark.git}"

# Seconds to wait after starting containers before verifying they are healthy
CONTAINER_INIT_WAIT="${CONTAINER_INIT_WAIT:-60}"

# =============================================================================
# Helpers
# =============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}    $1"; }
success() { echo -e "${GREEN}[OK]${NC}      $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}    $1"; }
error()   { echo -e "${RED}[ERROR]${NC}   $1"; }
prompt()  { echo -e "${YELLOW}[INPUT]${NC}   $1"; }

# ---------------------------------------------------------------------------
# Resolve project root (works whether called from any directory)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
M3_DIR="$PROJECT_ROOT/benchmarks/m3"
M3_ENV_FILE="$M3_DIR/config/m3.env"
DOT_ENV_FILE="$PROJECT_ROOT/.env"

# Resolve ENTERPRISE_BENCHMARK_DIR now that PROJECT_ROOT is known
if [ -z "$ENTERPRISE_BENCHMARK_DIR" ]; then
    ENTERPRISE_BENCHMARK_DIR="$PROJECT_ROOT/vendor/enterprise-benchmark"
fi

# cuga-agent lives next to this repo (sibling: ../cuga-agent). Override with: CUGA_AGENT_DIR=...
CUGA_AGENT_DIR="${CUGA_AGENT_DIR:-$(cd "$PROJECT_ROOT/.." && pwd)/cuga-agent}"

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║              M3 Benchmark - Environment Setup                ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
info "Project root: $PROJECT_ROOT"
info "M3 config:    $M3_ENV_FILE"
info "Secrets file: $DOT_ENV_FILE"
info "cuga-agent:   $CUGA_AGENT_DIR (override with CUGA_AGENT_DIR=...)"
echo ""

# ---------------------------------------------------------------------------
# STEP 1 — Detect container runtime and update m3.env
# ---------------------------------------------------------------------------
echo -e "${BLUE}── Step 1: Container runtime ──────────────────────────────────${NC}"

detect_runtime() {
    # Check common locations in order of preference
    for candidate in \
        "$(command -v podman 2>/dev/null)" \
        "/opt/podman/bin/podman" \
        "/usr/bin/podman" \
        "/usr/local/bin/podman" \
        "$(command -v docker 2>/dev/null)" \
        "/usr/bin/docker" \
        "/usr/local/bin/docker"; do
        if [ -n "$candidate" ] && [ -x "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done
    echo ""
}

DETECTED_RUNTIME="$(detect_runtime)"

if [ -n "$DETECTED_RUNTIME" ]; then
    info "Auto-detected container runtime: $DETECTED_RUNTIME"
    prompt "Press Enter to use '$DETECTED_RUNTIME', or type a custom path:"
    read -r USER_RUNTIME
    CONTAINER_RUNTIME="${USER_RUNTIME:-$DETECTED_RUNTIME}"
else
    warn "No container runtime (podman/docker) found in common locations."
    prompt "Enter the full path to your container runtime (e.g. /usr/bin/podman):"
    read -r CONTAINER_RUNTIME
    if [ -z "$CONTAINER_RUNTIME" ]; then
        error "Container runtime is required. Exiting."
        exit 1
    fi
fi

# Verify the binary exists and is executable
if [ ! -x "$CONTAINER_RUNTIME" ]; then
    # Maybe it's just a name like "podman" — check PATH
    if command -v "$CONTAINER_RUNTIME" &>/dev/null; then
        CONTAINER_RUNTIME="$(command -v "$CONTAINER_RUNTIME")"
    else
        error "Cannot find or execute: $CONTAINER_RUNTIME"
        exit 1
    fi
fi

success "Using container runtime: $CONTAINER_RUNTIME"

# Update CONTAINER_RUNTIME in m3.env (in-place sed, macOS + Linux compatible)
if grep -q "^CONTAINER_RUNTIME=" "$M3_ENV_FILE"; then
    sed -i.bak "s|^CONTAINER_RUNTIME=.*|CONTAINER_RUNTIME=${CONTAINER_RUNTIME}|" "$M3_ENV_FILE"
    rm -f "${M3_ENV_FILE}.bak"
    success "Updated CONTAINER_RUNTIME in $M3_ENV_FILE"
else
    echo "CONTAINER_RUNTIME=${CONTAINER_RUNTIME}" >> "$M3_ENV_FILE"
    success "Added CONTAINER_RUNTIME to $M3_ENV_FILE"
fi

echo ""

# ---------------------------------------------------------------------------
# STEP 2 — Configure API keys / secrets in .env
# ---------------------------------------------------------------------------
echo -e "${BLUE}── Step 2: API keys and secrets ───────────────────────────────${NC}"

# Create .env from example if it doesn't exist
if [ ! -f "$DOT_ENV_FILE" ]; then
    if [ -f "$PROJECT_ROOT/.env.example" ]; then
        cp "$PROJECT_ROOT/.env.example" "$DOT_ENV_FILE"
        info "Created $DOT_ENV_FILE from .env.example"
    else
        touch "$DOT_ENV_FILE"
        info "Created empty $DOT_ENV_FILE"
    fi
fi

# Helper: read or update a key in .env
set_env_key() {
    local key="$1"
    local description="$2"
    local current_val
    current_val="$(grep "^${key}=" "$DOT_ENV_FILE" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'")"

    if [ -n "$current_val" ] && [ "$current_val" != "XXXXXX" ] && [[ "$current_val" != *"XXXX"* ]]; then
        success "$key already set (${current_val:0:6}...)"
        return
    fi

    prompt "$description"
    prompt "  Enter value for $key (or press Enter to skip):"
    read -r new_val
    if [ -n "$new_val" ]; then
        if grep -q "^${key}=" "$DOT_ENV_FILE"; then
            sed -i.bak "s|^${key}=.*|${key}=${new_val}|" "$DOT_ENV_FILE"
            rm -f "${DOT_ENV_FILE}.bak"
        else
            echo "${key}=${new_val}" >> "$DOT_ENV_FILE"
        fi
        success "$key set"
    else
        warn "$key skipped — you can set it later in $DOT_ENV_FILE"
    fi
}

# Detect which LLM backend is configured
AGENT_CONFIG="$(grep "^AGENT_SETTING_CONFIG=" "$DOT_ENV_FILE" 2>/dev/null | cut -d'=' -f2- | tr -d '"')"

echo ""
info "Which LLM backend will you use?"
echo "  1) OpenAI"
echo "  2) WatsonX (IBM)"
echo "  3) Azure OpenAI"
echo "  4) Skip (already configured)"
prompt "Enter choice [1-4]:"
read -r LLM_CHOICE

case "$LLM_CHOICE" in
    1)
        set_env_key "AGENT_SETTING_CONFIG" "OpenAI config file (e.g. settings.openai.toml)"
        # Pre-fill if not set
        if ! grep -q "^AGENT_SETTING_CONFIG=" "$DOT_ENV_FILE"; then
            echo "AGENT_SETTING_CONFIG=settings.openai.toml" >> "$DOT_ENV_FILE"
        fi
        set_env_key "OPENAI_API_KEY" "Your OpenAI API key"
        ;;
    2)
        if ! grep -q "^AGENT_SETTING_CONFIG=" "$DOT_ENV_FILE"; then
            echo "AGENT_SETTING_CONFIG=settings.watsonx.toml" >> "$DOT_ENV_FILE"
        fi
        set_env_key "WATSONX_PROJECT_ID" "Your WatsonX project ID"
        set_env_key "WATSONX_URL"        "Your WatsonX URL (e.g. https://us-south.ml.cloud.ibm.com)"
        set_env_key "WATSONX_APIKEY"     "Your WatsonX API key"
        ;;
    3)
        if ! grep -q "^AGENT_SETTING_CONFIG=" "$DOT_ENV_FILE"; then
            echo "AGENT_SETTING_CONFIG=settings.azure.toml" >> "$DOT_ENV_FILE"
        fi
        set_env_key "AZURE_OPENAI_API_KEY"  "Your Azure OpenAI API key"
        set_env_key "AZURE_OPENAI_ENDPOINT" "Your Azure OpenAI endpoint URL"
        ;;
    4)
        info "Skipping LLM configuration."
        ;;
    *)
        warn "Invalid choice — skipping LLM configuration."
        ;;
esac

echo ""

# ---------------------------------------------------------------------------
# STEP 3 — Install cuga-agent
# ---------------------------------------------------------------------------
echo -e "${BLUE}── Step 3: Install cuga-agent ─────────────────────────────────${NC}"

cd "$PROJECT_ROOT"

if [ -d "$CUGA_AGENT_DIR/.git" ]; then
    info "cuga-agent already cloned. Running setup_cuga.sh to update..."
else
    info "Cloning cuga-agent via setup_cuga.sh (into parent directory)..."
fi

if bash "$PROJECT_ROOT/setup_cuga.sh"; then
    success "cuga-agent installed/updated successfully"
else
    error "setup_cuga.sh failed. Check the output above."
    exit 1
fi

echo ""

# ---------------------------------------------------------------------------
# STEP 4 — Install Python dependencies
# ---------------------------------------------------------------------------
echo -e "${BLUE}── Step 4: Install Python dependencies ────────────────────────${NC}"

if command -v uv &>/dev/null; then
    info "Installing dependencies with uv sync..."
    cd "$PROJECT_ROOT"
    if uv sync; then
        success "Python dependencies installed"
    else
        error "uv sync failed. Check pyproject.toml."
        exit 1
    fi
else
    warn "uv not found — skipping dependency install."
    warn "Install uv: https://docs.astral.sh/uv/getting-started/installation/"
fi

echo ""

# ---------------------------------------------------------------------------
# STEP 5 — Create required directories
# ---------------------------------------------------------------------------
echo -e "${BLUE}── Step 5: Create required directories ────────────────────────${NC}"

mkdir -p "$M3_DIR/logging"
mkdir -p "$M3_DIR/results"
mkdir -p "$M3_DIR/eval/logs"
success "Directories ready: logging/, results/, eval/logs/"

echo ""

# ---------------------------------------------------------------------------
# STEP 6 — Check M3 containers are running
# ---------------------------------------------------------------------------
echo -e "${BLUE}── Step 6: Check M3 containers ────────────────────────────────${NC}"

REGISTRY_YAML="$M3_DIR/config/m3_registry.yaml"
UNIQUE_CONTAINERS=()
CONTAINER_ERRORS=0

if [ -f "$REGISTRY_YAML" ]; then
    # Extract values of 'container:' keys (skip commented lines)
    while IFS= read -r line; do
        if echo "$line" | grep -qE '^\s+container:\s+'; then
            cname="$(echo "$line" | sed -E 's/.*container:[[:space:]]+"?([^"#[:space:]]+)"?.*/\1/')"
            if [ -n "$cname" ]; then
                UNIQUE_CONTAINERS+=("$cname")
            fi
        fi
    done < "$REGISTRY_YAML"
    # Deduplicate
    if [ "${#UNIQUE_CONTAINERS[@]}" -gt 0 ]; then
        mapfile -t UNIQUE_CONTAINERS < <(printf '%s\n' "${UNIQUE_CONTAINERS[@]}" | sort -u)
    fi
fi

if [ "${#UNIQUE_CONTAINERS[@]}" -eq 0 ]; then
    warn "Could not detect container names from $REGISTRY_YAML"
    warn "Skipping container check — verify manually with: $CONTAINER_RUNTIME ps"
else
    info "Containers required by m3_registry.yaml: ${UNIQUE_CONTAINERS[*]}"
    echo ""
    for cname in "${UNIQUE_CONTAINERS[@]}"; do
        if "$CONTAINER_RUNTIME" ps --format '{{.Names}}' 2>/dev/null | grep -q "^${cname}$"; then
            success "Container running: $cname"
        elif "$CONTAINER_RUNTIME" ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${cname}$"; then
            warn "Container exists but is STOPPED: $cname"
            warn "  Start it with: $CONTAINER_RUNTIME start $cname"
            CONTAINER_ERRORS=$((CONTAINER_ERRORS + 1))
        else
            error "Container NOT FOUND: $cname"
            CONTAINER_ERRORS=$((CONTAINER_ERRORS + 1))
        fi
    done
    echo ""
    if [ "$CONTAINER_ERRORS" -gt 0 ]; then
        warn "⚠️  $CONTAINER_ERRORS container(s) not running. Setting up enterprise-benchmark containers..."
        echo ""

        # ── Locate or clone enterprise-benchmark ──────────────────────────────
        if [ ! -d "$ENTERPRISE_BENCHMARK_DIR/.git" ]; then
            info "Cloning enterprise-benchmark to: $ENTERPRISE_BENCHMARK_DIR"
            git clone "$ENTERPRISE_BENCHMARK_REPO" "$ENTERPRISE_BENCHMARK_DIR"
            success "Cloned enterprise-benchmark"
        else
            info "enterprise-benchmark already cloned at: $ENTERPRISE_BENCHMARK_DIR"
        fi

        cd "$ENTERPRISE_BENCHMARK_DIR"

        # ── Python environment ─────────────────────────────────────────────────
        if [ ! -d "$ENTERPRISE_BENCHMARK_DIR/.venv" ]; then
            info "Creating Python virtual environment..."
            python3 -m venv .venv
            success "Virtual environment created"
        fi
        # shellcheck disable=SC1091
        source "$ENTERPRISE_BENCHMARK_DIR/.venv/bin/activate"

        info "Installing Python dependencies..."
        pip install -e ".[init]" --quiet
        pip install -r requirements_benchmark.txt --quiet
        success "Python dependencies installed"

        # ── Download benchmark data ────────────────────────────────────────────
        if [ ! -d "$ENTERPRISE_BENCHMARK_DIR/data" ] || [ -z "$(ls -A "$ENTERPRISE_BENCHMARK_DIR/data" 2>/dev/null)" ]; then
            info "Downloading benchmark data (~30 GB)."
            info "You will be prompted for a Hugging Face token."
            info "Get your token at: https://huggingface.co/settings/tokens"
            make download
            success "Benchmark data downloaded"
        else
            info "Benchmark data already present, skipping download"
        fi

        # ── Build and start containers ─────────────────────────────────────────
        info "Stopping any existing containers..."
        "$CONTAINER_RUNTIME" compose down 2>/dev/null || true

        info "Building container image (this may take several minutes)..."
        make build
        success "Container image built"

        info "Starting containers..."
        "$CONTAINER_RUNTIME" compose up -d
        success "Containers started"

        # ── Wait for containers to initialize ─────────────────────────────────
        info "Waiting ${CONTAINER_INIT_WAIT} seconds for internal services to initialize..."
        sleep "$CONTAINER_INIT_WAIT"

        info "Verifying containers:"
        "$CONTAINER_RUNTIME" compose ps

        # Re-check that required containers are now running
        CONTAINER_ERRORS=0
        for cname in "${UNIQUE_CONTAINERS[@]}"; do
            if "$CONTAINER_RUNTIME" ps --format '{{.Names}}' 2>/dev/null | grep -q "^${cname}$"; then
                success "Container running: $cname"
            else
                error "Container still not running after setup: $cname"
                CONTAINER_ERRORS=$((CONTAINER_ERRORS + 1))
            fi
        done

        cd "$PROJECT_ROOT"

        if [ "$CONTAINER_ERRORS" -eq 0 ]; then
            success "All required M3 containers are now running ✅"
        else
            error "$CONTAINER_ERRORS container(s) failed to start."
            error "Check logs with: $CONTAINER_RUNTIME compose logs"
        fi
    else
        success "All required M3 containers are running ✅"
    fi
fi

echo ""

# ---------------------------------------------------------------------------
# STEP 7 — Verify setup
# ---------------------------------------------------------------------------
echo -e "${BLUE}── Step 7: Verify setup ───────────────────────────────────────${NC}"

ERRORS=0

# Carry forward any container errors into the final error count
ERRORS=$((ERRORS + CONTAINER_ERRORS))

# Check container runtime
if [ -x "$CONTAINER_RUNTIME" ]; then
    RUNTIME_VERSION="$("$CONTAINER_RUNTIME" --version 2>/dev/null | head -1)"
    success "Container runtime: $RUNTIME_VERSION"
else
    error "Container runtime not executable: $CONTAINER_RUNTIME"
    ERRORS=$((ERRORS + 1))
fi

# Check .env has at least one API key set
if grep -qE "^(OPENAI_API_KEY|WATSONX_APIKEY|AZURE_OPENAI_API_KEY)=.+" "$DOT_ENV_FILE" 2>/dev/null; then
    success ".env has API key configured"
else
    warn ".env has no LLM API key set — evaluation will fail without one"
fi

# Check cuga-agent is installed
if [ -d "$CUGA_AGENT_DIR/src/cuga" ]; then
    success "cuga-agent source found at $CUGA_AGENT_DIR"
else
    error "cuga-agent not found at $CUGA_AGENT_DIR (run setup_cuga.sh or clone cuga-agent next to this repo)"
    ERRORS=$((ERRORS + 1))
fi

# Check uv is available
if command -v uv &>/dev/null; then
    success "uv available: $(uv --version)"
else
    warn "uv not found — install from https://docs.astral.sh/uv/"
fi

echo ""

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
if [ "$ERRORS" -eq 0 ]; then
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                  ✅  Setup complete!                         ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
else
    echo -e "${RED}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║           ⚠️  Setup completed with $ERRORS error(s)             ║${NC}"
    echo -e "${RED}╚══════════════════════════════════════════════════════════════╝${NC}"
fi

echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Review/edit secrets:  $DOT_ENV_FILE"
echo "  2. Review M3 config:     $M3_ENV_FILE"
echo "  3. Edit task domains:    $M3_DIR/config/m3_registry.yaml"
echo ""
echo -e "${YELLOW}Run the evaluation (from project root):${NC}"
echo "  cd benchmarks/m3"
echo "  uv run python eval_m3.py --from-config config/m3_registry.yaml"
echo ""
