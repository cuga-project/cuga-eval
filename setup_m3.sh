#!/bin/bash
#
# M3 (Vakra) one-time setup: clone vendor/vakra, install its Python deps into the
# project .venv (from README: uv venv && uv sync), download data, build/start
# Docker containers. Does NOT create vendor/vakra/.venv.

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
PROJECT_VENV="${PROJECT_ROOT}/.venv"
PROJECT_PYTHON="${PROJECT_VENV}/bin/python"
REPO_URL="https://github.com/IBM/vakra.git"
VENDOR_DIR="${PROJECT_ROOT}/vendor"
REPO_NAME="vakra"
REPO_PATH="${VENDOR_DIR}/${REPO_NAME}"
DATA_DIR="${REPO_PATH}/data"

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if command exists
command_exists() {
    command -v "$1" &> /dev/null
}

# Require the uv-managed project venv from README steps 3–4 (uv venv && uv sync).
ensure_project_venv() {
    if ! command_exists uv; then
        print_error "uv is required. Install it from https://github.com/astral-sh/uv"
        return 1
    fi

    if [ ! -x "$PROJECT_PYTHON" ]; then
        print_error "Project virtualenv not found at ${PROJECT_VENV}"
        print_error "Run these first (see README.md):"
        print_error "  uv venv"
        print_error "  uv sync"
        return 1
    fi

    if ! "$PROJECT_PYTHON" -c 'import sys; exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
        print_error "Project venv must use Python 3.12 or 3.13 (found: $("$PROJECT_PYTHON" --version))"
        print_error "Recreate it with: uv venv --python 3.13 && uv sync"
        return 1
    fi

    return 0
}

# Upstream vakra still lists the abandoned PyPI package "dotenv".
patch_vakra_dotenv() {
    local pyproject="${REPO_PATH}/pyproject.toml"

    if [ ! -f "$pyproject" ]; then
        return 0
    fi

    if grep -q '"dotenv"' "$pyproject"; then
        print_status "Patching vakra dependency: dotenv -> python-dotenv"
        sed -i.bak 's/"dotenv"/"python-dotenv"/' "$pyproject"
        rm -f "${pyproject}.bak"
    fi
}

# Function to check prerequisites
check_prerequisites() {
    print_status "Checking prerequisites..."

    local missing_deps=()

    if ! command_exists git; then
        missing_deps+=("git")
    fi

    if ! command_exists docker && ! command_exists podman; then
        missing_deps+=("docker or podman")
    fi

    if [ ${#missing_deps[@]} -gt 0 ]; then
        print_error "Missing required dependencies: ${missing_deps[*]}"
        echo "Please install the missing dependencies and try again."
        exit 1
    fi

    print_success "All prerequisites satisfied"
}

# Function to detect container runtime
detect_container_runtime() {
    if command_exists docker; then
        echo "docker"
    elif command_exists podman; then
        echo "podman"
    else
        echo ""
    fi
}

# Function to create vendor directory
create_vendor_dir() {
    if [ ! -d "$VENDOR_DIR" ]; then
        print_status "Creating vendor directory..."
        mkdir -p "$VENDOR_DIR"
        print_success "Vendor directory created"
    fi
}

# Function to clone repository
clone_repo() {
    print_status "Cloning enterprise-benchmark repository..."

    if git clone "$REPO_URL" "$REPO_PATH"; then
        print_success "Repository cloned successfully to $REPO_PATH"
        return 0
    else
        print_error "Failed to clone repository. Please check your SSH keys and network connection."
        print_error "Make sure you have access to: $REPO_URL"
        return 1
    fi
}

# Function to update existing repository
update_repo() {
    print_status "Repository already exists. Pulling latest changes..."
    cd "$REPO_PATH" || exit 1

    if git pull origin main 2>/dev/null || git pull origin master 2>/dev/null; then
        print_success "Repository updated successfully"
    else
        print_warning "Could not update repository. You may need to resolve conflicts manually."
    fi

    cd - > /dev/null || exit 1
}

# Function to setup Python environment and install dependencies
setup_python_env() {
    print_status "Setting up Python environment and installing dependencies..."

    if [ ! -d "$REPO_PATH" ]; then
        print_error "Repository not found at $REPO_PATH"
        return 1
    fi

    ensure_project_venv || return 1

    print_status "Using project venv ($("$PROJECT_PYTHON" --version))"

    patch_vakra_dotenv

    # Older setup_m3.sh versions created vendor/vakra/.venv with system python3.
    if [ -d "${REPO_PATH}/.venv" ]; then
        print_warning "Removing legacy vendor/vakra/.venv (use the project .venv from 'uv venv' instead)"
        rm -rf "${REPO_PATH}/.venv"
    fi

    cd "$PROJECT_ROOT" || exit 1

    print_status "Installing vakra package with init dependencies..."
    if uv pip install -e "${REPO_PATH}[init]"; then
        print_success "Vakra package installed successfully"
    else
        print_error "Failed to install vakra package"
        return 1
    fi

    print_status "Installing benchmark dependencies..."
    if uv pip install -r "${REPO_PATH}/requirements_benchmark.txt"; then
        print_success "Benchmark dependencies installed successfully"
    else
        print_error "Failed to install benchmark dependencies"
        return 1
    fi
}

# Function to download data from HuggingFace
download_data() {
    print_status "Downloading benchmark data from HuggingFace (~30 GB)..."

    if [ ! -d "$REPO_PATH" ]; then
        print_error "Repository not found at $REPO_PATH"
        return 1
    fi

    # Check for HF_TOKEN
    if [ -z "$HF_TOKEN" ]; then
        print_error "HF_TOKEN environment variable is not set"
        print_error "Please set it with: export HF_TOKEN=hf_your_token_here"
        print_error "Get your token from: https://huggingface.co/settings/tokens"
        return 1
    fi

    cd "$REPO_PATH" || exit 1

    # Download using make
    if command_exists make; then
        print_status "Using make to download data..."
        if PYTHON="$PROJECT_PYTHON" make download; then
            print_success "Data downloaded successfully"
        else
            print_error "Failed to download data"
            cd - > /dev/null
            return 1
        fi
    else
        print_status "Using Python script to download data..."
        if uv run --project "$PROJECT_ROOT" python "$REPO_PATH/benchmark_setup.py" --download-data; then
            print_success "Data downloaded successfully"
        else
            print_error "Failed to download data"
            cd - > /dev/null
            return 1
        fi
    fi

    cd - > /dev/null
}

# Function to build Docker image
build_image() {
    local runtime="$1"

    print_status "Building vakra Docker image using $runtime..."

    if [ ! -d "$REPO_PATH" ]; then
        print_error "Repository not found at $REPO_PATH"
        return 1
    fi

    cd "$REPO_PATH" || exit 1

    # Build using Makefile if available, otherwise use docker directly
    if command_exists make; then
        print_status "Using make to build image..."
        if DOCKER=$runtime make build; then
            print_success "Image built successfully via make"
        else
            print_error "Failed to build image via make"
            cd - > /dev/null
            return 1
        fi
    else
        print_status "Building image directly with $runtime..."
        if $runtime build -t m3_environ -f docker/Dockerfile.unified .; then
            print_success "Image built successfully"
        else
            print_error "Failed to build image"
            cd - > /dev/null
            return 1
        fi
    fi

    cd - > /dev/null
}

# Function to start containers via docker compose
start_containers() {
    local runtime="$1"

    print_status "Starting containers using docker compose..."

    if [ ! -d "$REPO_PATH" ]; then
        print_error "Repository not found at $REPO_PATH"
        return 1
    fi

    cd "$REPO_PATH" || exit 1

    # Use make if available, otherwise docker compose directly
    if command_exists make; then
        print_status "Using make to start containers..."
        if DOCKER=$runtime make start; then
            print_success "Containers started successfully via make"
        else
            print_error "Failed to start containers via make"
            cd - > /dev/null
            return 1
        fi
    else
        print_status "Starting containers with docker compose..."
        if [ "$runtime" = "podman" ]; then
            if podman compose up -d; then
                print_success "Containers started successfully"
            else
                print_error "Failed to start containers"
                cd - > /dev/null
                return 1
            fi
        else
            if docker compose up -d; then
                print_success "Containers started successfully"
            else
                print_error "Failed to start containers"
                cd - > /dev/null
                return 1
            fi
        fi
    fi

    cd - > /dev/null
}

# Function to verify containers are running
verify_containers() {
    local runtime="$1"

    print_status "Verifying containers..."

    if [ ! -d "$REPO_PATH" ]; then
        print_error "Repository not found at $REPO_PATH"
        return 1
    fi

    cd "$REPO_PATH" || exit 1

    # Check container status
    print_status "Checking container status..."
    $runtime ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

    # Count running containers
    local running_count=$($runtime ps --format "{{.Names}}" | grep -c "capability_")

    if [ "$running_count" -ge 4 ]; then
        print_success "✓ Found $running_count capability containers running"
        cd - > /dev/null
        return 0
    else
        print_warning "Only $running_count capability containers running (expected 4)"
        cd - > /dev/null
        return 1
    fi
}

# Function to show usage
show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --download-only Download data only (no build/start)"
    echo "  --build-only    Only build image, don't start containers"
    echo "  --start-only    Only start containers (assumes already built)"
    echo "  --verify        Only verify containers are running"
    echo "  --skip-download Skip data download step"
    echo "  --help          Show this help message"
    echo ""
    echo "Default: Clone/update repo, download data, build image, and start containers"
}

# Main execution
main() {
    local download_only=false
    local build_only=false
    local start_only=false
    local verify_only=false
    local skip_download=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --download-only)
                download_only=true
                shift
                ;;
            --build-only)
                build_only=true
                shift
                ;;
            --start-only)
                start_only=true
                shift
                ;;
            --verify)
                verify_only=true
                shift
                ;;
            --skip-download)
                skip_download=true
                shift
                ;;
            --help)
                show_usage
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done

    echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║              Vakra Benchmark Setup Script                    ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""

    # Check prerequisites
    check_prerequisites

    # Detect container runtime
    local runtime=$(detect_container_runtime)
    print_status "Using container runtime: $runtime"

    # Verify only mode
    if [ "$verify_only" = true ]; then
        verify_containers "$runtime"
        exit $?
    fi

    # Start only mode
    if [ "$start_only" = true ]; then
        start_containers "$runtime"
        verify_containers "$runtime"
        exit $?
    fi

    # Step 1: Clone or update repository
    create_vendor_dir

    if [ -d "$REPO_PATH" ]; then
        if [ -d "$REPO_PATH/.git" ]; then
            print_status "Repository already exists at $REPO_PATH"
            update_repo
        else
            print_warning "Directory exists but is not a git repository. Removing and cloning fresh..."
            rm -rf "$REPO_PATH"
            clone_repo || exit 1
        fi
    else
        clone_repo || exit 1
    fi

    # Step 2: Setup Python environment and install dependencies
    print_status "Step 2: Installing Python dependencies..."
    setup_python_env || exit 1

    # Step 3: Download data (unless skipped)
    if [ "$skip_download" = false ]; then
        if [ ! -d "$DATA_DIR" ] || [ -z "$(ls -A "$DATA_DIR" 2>/dev/null)" ]; then
            print_status "Step 3: Downloading benchmark data..."
            download_data || exit 1
        else
            print_status "Data directory exists and is not empty, skipping download"
            print_warning "Use --skip-download to suppress this check, or delete $DATA_DIR to re-download"
        fi
    fi

    # Exit if download-only
    if [ "$download_only" = true ]; then
        print_success "Setup and data download completed!"
        exit 0
    fi

    # Build image
    build_image "$runtime" || exit 1

    # Start containers (unless build-only)
    if [ "$build_only" = false ]; then
        start_containers "$runtime"
        verify_containers "$runtime"
    fi

    echo ""
    print_success "Vakra setup completed successfully!"
    echo ""
    echo -e "${YELLOW}Container Information:${NC}"
    echo "  • capability_1_bi_apis - Tool Chaining MCP Server"
    echo "  • capability_2_dashboard_apis - Tool Selection MCP Server"
    echo "  • capability_3_multihop_reasoning - Multi-hop Reasoning MCP Server"
    echo "  • capability_4_multiturn - Multi-hop Multi-Source MCP Server"
    echo ""
    echo -e "${YELLOW}Next steps:${NC}"
    echo "  1. Verify containers: docker ps -a, or podman related commands"
    echo "  2. Check logs: docker logs capability_2_dashboard_apis, or podman related commands"
}

# Run main function
main "$@"
