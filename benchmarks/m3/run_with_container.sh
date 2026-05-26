#!/bin/bash

# run_with_container.sh - Run M3 benchmark using enterprise-benchmark FastAPI container
# This script integrates cuga-eval with the FastAPI container from enterprise-benchmark

set -e

# Detect container runtime (Docker or Podman)
CONTAINER_RUNTIME=""
if command -v docker &> /dev/null; then
    CONTAINER_RUNTIME="docker"
elif command -v podman &> /dev/null; then
    CONTAINER_RUNTIME="podman"
    # Create alias for this script
    shopt -s expand_aliases
    alias docker='podman'
else
    echo "Error: Neither Docker nor Podman found"
    echo "Please install Docker or Podman to continue"
    exit 1
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
ENTERPRISE_BENCHMARK_DIR="${ENTERPRISE_BENCHMARK_DIR:-/Users/hamidadebayo/dev/enterprise-benchmark}"
CONTAINER_NAME="fastapi-mcp-server"
FASTAPI_PORT=8000

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}M3 Benchmark with FastAPI Container${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "Container Runtime:        ${GREEN}$CONTAINER_RUNTIME${NC}"
echo -e "Enterprise Benchmark Dir: ${GREEN}$ENTERPRISE_BENCHMARK_DIR${NC}"
echo -e "Container Name:           ${GREEN}$CONTAINER_NAME${NC}"
echo -e "FastAPI Port:             ${GREEN}$FASTAPI_PORT${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Function to check if container is running
check_container() {
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        return 0
    else
        return 1
    fi
}

# Function to check if container exists (running or stopped)
container_exists() {
    if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        return 0
    else
        return 1
    fi
}

# Step 1: Check if enterprise-benchmark directory exists
if [ ! -d "$ENTERPRISE_BENCHMARK_DIR" ]; then
    echo -e "${RED}Error: Enterprise benchmark directory not found: $ENTERPRISE_BENCHMARK_DIR${NC}"
    echo -e "${YELLOW}Please set ENTERPRISE_BENCHMARK_DIR environment variable${NC}"
    echo -e "${YELLOW}Example: export ENTERPRISE_BENCHMARK_DIR=/path/to/enterprise-benchmark${NC}"
    exit 1
fi

COMPOSE_DIR="$ENTERPRISE_BENCHMARK_DIR/apis/m3/rest"
if [ ! -d "$COMPOSE_DIR" ]; then
    echo -e "${RED}Error: M3 REST directory not found: $COMPOSE_DIR${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Found enterprise-benchmark directory${NC}\n"

# Step 2: Check/start the FastAPI container
echo -e "${YELLOW}Checking FastAPI container status...${NC}"

if check_container; then
    echo -e "${GREEN}✓ Container '$CONTAINER_NAME' is already running${NC}"
else
    echo -e "${YELLOW}Container '$CONTAINER_NAME' is not running${NC}"

    if container_exists; then
        echo -e "${YELLOW}Starting existing container...${NC}"
        docker start "$CONTAINER_NAME"
    else
        echo -e "${YELLOW}Building and starting container...${NC}"
        cd "$COMPOSE_DIR"

        if [ ! -f "docker-compose.yml" ]; then
            echo -e "${RED}Error: docker-compose.yml not found in $COMPOSE_DIR${NC}"
            exit 1
        fi

        docker-compose up -d --build
        cd - > /dev/null
    fi

    # Wait for container to be ready
    echo -e "${YELLOW}Waiting for FastAPI to be ready...${NC}"
    max_attempts=30
    attempt=1

    while [ $attempt -le $max_attempts ]; do
        if curl -sf http://localhost:$FASTAPI_PORT/health > /dev/null 2>&1; then
            echo -e "${GREEN}✓ FastAPI is ready${NC}"
            break
        fi
        echo -e "${YELLOW}Waiting... (attempt $attempt/$max_attempts)${NC}"
        sleep 2
        attempt=$((attempt + 1))
    done

    if [ $attempt -gt $max_attempts ]; then
        echo -e "${RED}✗ FastAPI failed to start after $max_attempts attempts${NC}"
        echo -e "${YELLOW}Check logs with: docker logs $CONTAINER_NAME${NC}"
        exit 1
    fi
fi

# Step 3: Verify FastAPI is accessible
echo -e "\n${YELLOW}Verifying FastAPI endpoints...${NC}"
if curl -sf http://localhost:$FASTAPI_PORT/openapi.json > /dev/null 2>&1; then
    echo -e "${GREEN}✓ OpenAPI spec accessible${NC}"
else
    echo -e "${RED}✗ Cannot access OpenAPI spec${NC}"
    exit 1
fi

# Step 4: Start the registry server
echo -e "\n${YELLOW}Starting MCP registry server...${NC}"

# Kill any existing registry server
lsof -ti:8001 | xargs kill -9 2>/dev/null || true

# Start registry in background
cd benchmarks/m3
bash run_registry.sh > /tmp/m3_registry.log 2>&1 &
REGISTRY_PID=$!

# Wait for registry to be ready
echo -e "${YELLOW}Waiting for registry server...${NC}"
max_attempts=30
attempt=1

while [ $attempt -le $max_attempts ]; do
    if curl -sf http://localhost:8001/applications > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Registry server is ready${NC}"
        break
    fi
    if [ $((attempt % 5)) -eq 0 ]; then
        echo -e "${YELLOW}Still waiting... (attempt $attempt/$max_attempts)${NC}"
    fi
    sleep 2
    attempt=$((attempt + 1))
done

if [ $attempt -gt $max_attempts ]; then
    echo -e "${RED}✗ Registry server failed to start after $max_attempts attempts${NC}"
    echo -e "${YELLOW}Check logs: tail -f /tmp/m3_registry.log${NC}"
    echo -e "${YELLOW}Last 20 lines of log:${NC}"
    tail -20 /tmp/m3_registry.log
    exit 1
fi

# Step 5: Verify registry loaded the hockey tools
echo -e "\n${YELLOW}Verifying registry loaded tools...${NC}"
TOOL_COUNT=$(curl -s http://localhost:8001/applications/hockey/apis 2>/dev/null | python3 -c "import sys, json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

if [ "$TOOL_COUNT" -gt "0" ]; then
    echo -e "${GREEN}✓ Registry loaded $TOOL_COUNT hockey tools${NC}"
else
    echo -e "${RED}✗ Registry did not load any tools${NC}"
    echo -e "${YELLOW}Check logs: tail -f /tmp/m3_registry.log${NC}"
    exit 1
fi

# Step 6: Run the evaluation
echo -e "\n${BLUE}========================================${NC}"
echo -e "${BLUE}Running M3 Evaluation${NC}"
echo -e "${BLUE}========================================${NC}\n"

cd ../..
uv run python benchmarks/m3/eval_m3.py "$@"

EVAL_EXIT_CODE=$?

# Step 7: Summary
echo -e "\n${BLUE}========================================${NC}"
if [ $EVAL_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ Evaluation completed successfully${NC}"
else
    echo -e "${RED}✗ Evaluation failed with exit code $EVAL_EXIT_CODE${NC}"
fi
echo -e "${BLUE}========================================${NC}\n"

# Show results location
RESULTS_DIR="benchmarks/m3/results"
if [ -d "$RESULTS_DIR" ]; then
    LATEST_RESULT=$(ls -t "$RESULTS_DIR"/m3_*.json 2>/dev/null | head -1)
    if [ -n "$LATEST_RESULT" ]; then
        echo -e "${GREEN}Results saved to: $LATEST_RESULT${NC}"
        echo -e "\nTo view results:"
        echo -e "  ${YELLOW}cat $LATEST_RESULT | jq '.'${NC}"
    fi
fi

echo -e "\n${YELLOW}Registry logs: tail -f /tmp/m3_registry.log${NC}"
echo -e "${YELLOW}Container logs: docker logs $CONTAINER_NAME -f${NC}"

exit $EVAL_EXIT_CODE
