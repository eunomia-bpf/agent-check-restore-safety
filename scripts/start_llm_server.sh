#!/bin/bash

# ============================================
# Start llama-server for AgentRollback experiments
# ============================================

set -e

LLAMA_DIR="/home/yunwei37/workspace/gpu/llama.cpp"
MODEL="unsloth/Qwen3-Next-80B-A3B-Instruct-GGUF:Q4_K_M"
CONTEXT_SIZE=65536
PORT=8080

# Log setup
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/llama_server_$(date +%Y%m%d_%H%M%S).log"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "============================================"
echo "AgentRollback LLM Server Startup"
echo "============================================"
echo ""

# Check if llama-server binary exists
if [ ! -f "$LLAMA_DIR/build/bin/llama-server" ]; then
    echo -e "${RED}ERROR: llama-server not found at $LLAMA_DIR/build/bin/llama-server${NC}"
    echo "Please build llama.cpp first:"
    echo "  cd $LLAMA_DIR"
    echo "  cmake -B build"
    echo "  cmake --build build --config Release -j"
    exit 1
fi

# Check if already running
check_running() {
    pgrep -f "llama-server" > /dev/null 2>&1
}

if check_running; then
    echo -e "${YELLOW}WARNING: llama-server is already running!${NC}"
    echo "PID: $(pgrep -f 'llama-server')"
    echo ""

    # Check if it's responding
    if curl -s "http://localhost:$PORT/health" > /dev/null 2>&1; then
        echo -e "${GREEN}Server is healthy and responding on port $PORT${NC}"
        echo "You can proceed with experiments."
        exit 0
    else
        echo -e "${YELLOW}Server process exists but not responding${NC}"
        read -p "Kill and restart? (y/N): " answer
        if [[ "$answer" =~ ^[Yy]$ ]]; then
            echo "Killing existing process..."
            pkill -f "llama-server"
            sleep 3
        else
            echo "Exiting."
            exit 1
        fi
    fi
fi

# Start server
echo "Starting llama-server..."
echo "  Model: $MODEL"
echo "  Context: $CONTEXT_SIZE"
echo "  Port: $PORT"
echo "  Log: $LOG_FILE"
echo ""

cd "$LLAMA_DIR"

# Start in background
# --jinja is required for tool calling support (Claude Code compatibility)
nohup build/bin/llama-server \
    -hf "$MODEL" \
    -c "$CONTEXT_SIZE" \
    --port "$PORT" \
    --jinja \
    > "$LOG_FILE" 2>&1 &

SERVER_PID=$!
disown $SERVER_PID

echo "Server starting with PID: $SERVER_PID"
echo ""

# Wait for server to be ready
echo "Waiting for server to initialize..."
MAX_WAIT=120
WAITED=0

while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -s "http://localhost:$PORT/health" > /dev/null 2>&1; then
        echo ""
        echo -e "${GREEN}Server is ready!${NC}"
        echo ""
        echo "============================================"
        echo "LLM Server Information"
        echo "============================================"
        echo "  URL: http://localhost:$PORT"
        echo "  OpenAI-compatible endpoint: http://localhost:$PORT/v1/chat/completions"
        echo "  Health check: http://localhost:$PORT/health"
        echo "  Log file: $LOG_FILE"
        echo ""
        echo "To run experiments:"
        echo "  python poc/simple_test.py --trials 10"
        echo ""
        echo "To stop the server:"
        echo "  pkill -f llama-server"
        echo "  # or use: $SCRIPT_DIR/stop_llm_server.sh"
        echo "============================================"
        exit 0
    fi

    sleep 2
    WAITED=$((WAITED + 2))
    echo -n "."
done

echo ""
echo -e "${RED}ERROR: Server failed to start within $MAX_WAIT seconds${NC}"
echo "Check log file: $LOG_FILE"
echo ""
echo "Last 20 lines of log:"
tail -20 "$LOG_FILE"
exit 1
