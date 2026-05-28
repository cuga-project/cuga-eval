#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration (clone cuga-agent next to this repo — matches pyproject.toml path "../cuga-agent")
REPO_URL="https://github.com/cuga-project/cuga-agent.git"
REPO_BRANCH="main"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PARENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_NAME="cuga-agent"
REPO_PATH="${PARENT_DIR}/${REPO_NAME}"

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

# Function to check if git is installed
check_git() {
    if ! command -v git &> /dev/null; then
        print_error "Git is not installed. Please install git and try again."
        exit 1
    fi
}

# Function to clone repository
clone_repo() {
    print_status "Cloning repository from $REPO_URL (branch: $REPO_BRANCH)..."

    if git clone -b "$REPO_BRANCH" "$REPO_URL" "$REPO_PATH"; then
        print_success "Repository cloned successfully to $REPO_PATH (branch: $REPO_BRANCH)"
        return 0
    else
        print_error "Failed to clone repository. Please check your SSH keys and network connection."
        return 1
    fi
}

# Function to update existing repository
update_repo() {
    print_status "Repository already exists. Pulling latest changes from branch: $REPO_BRANCH..."
    cd "$REPO_PATH" || exit 1

    # Fetch and checkout the specific branch
    if git fetch origin && git checkout "$REPO_BRANCH" && git pull origin "$REPO_BRANCH"; then
        print_success "Repository updated successfully (branch: $REPO_BRANCH)"
    else
        print_warning "Could not update repository. You may need to resolve conflicts manually."
    fi

    cd - > /dev/null || exit 1
}

# Function to export environment variables to current terminal session
export_env_vars() {
    print_status "Exporting environment variables to current terminal session..."

    # Define environment variables to export
    export ENV_FILE="./.env"
    export MCP_SERVERS_FILE="./mcp_servers.yaml"
    export CUGA_LOGGING_DIR="./logging"

    print_status "Exported ENV_FILE=./.env"
    print_status "Exported MCP_SERVERS_FILE=./mcp_servers.yaml"
    print_status "Exported CUGA_LOGGING_DIR=./logging"

    print_success "Environment variables exported to current terminal session"
}


# Function to create logging directory
create_logging_dir() {
    if [ ! -d "./logging" ]; then
        print_status "Creating logging directory..."
        mkdir -p "./logging"
        print_success "Logging directory created"
    fi
}

# Main execution
main() {
    local pull_branch="$1"

    echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║                    CUGA Agent Setup Script                   ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""

    # Check prerequisites
    check_git

    # Clone or update repository
    if [ -d "$REPO_PATH" ]; then
        if [ -d "$REPO_PATH/.git" ]; then
            print_status "Repository already exists at $REPO_PATH"
            update_repo "$pull_branch"
        else
            print_warning "Directory exists but is not a git repository. Removing and cloning fresh..."
            rm -rf "$REPO_PATH"
            clone_repo || exit 1
        fi
    else
        clone_repo || exit 1
    fi

    # Export environment variables to current terminal
    export_env_vars

    # Create logging directory
    create_logging_dir

    echo ""
    print_success "Setup completed successfully!"
    echo ""
    echo -e "${YELLOW}Next steps:${NC}"
    echo "  1. Check the cloned repository at: $REPO_PATH"
    echo "  2. Environment variables are now available in this terminal session"
    echo "  3. Note: Variables will only persist for this terminal session"
    echo ""
}

# Run main function
main "$@"
