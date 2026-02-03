#!/bin/bash

# ============================================
# Run the PoC experiment
# ============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Default values
TRIALS=10
LLM_URL="http://localhost:8080/v1/chat/completions"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --trials)
            TRIALS="$2"
            shift 2
            ;;
        --llm-url)
            LLM_URL="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [--trials N] [--llm-url URL]"
            echo ""
            echo "Options:"
            echo "  --trials N      Number of trials (default: 10)"
            echo "  --llm-url URL   LLM server URL (default: http://localhost:8080/v1/chat/completions)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "============================================"
echo "AgentRollback PoC Experiment"
echo "============================================"
echo ""

# Check if LLM server is running
echo "Checking LLM server..."
HEALTH_URL=$(echo "$LLM_URL" | sed 's|/v1/chat/completions|/health|')

if ! curl -s "$HEALTH_URL" > /dev/null 2>&1; then
    echo -e "${YELLOW}LLM server not responding at $HEALTH_URL${NC}"
    echo ""
    read -p "Start LLM server? (Y/n): " answer
    if [[ ! "$answer" =~ ^[Nn]$ ]]; then
        echo "Starting LLM server..."
        "$SCRIPT_DIR/start_llm_server.sh"
        echo ""
    else
        echo -e "${RED}Cannot run experiment without LLM server${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}LLM server is running${NC}"
fi

echo ""
echo "Running experiment with $TRIALS trials..."
echo ""

cd "$PROJECT_DIR"
python poc/simple_test.py --trials "$TRIALS" --llm-url "$LLM_URL"
