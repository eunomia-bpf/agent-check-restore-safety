#!/bin/bash

# ============================================
# Stop llama-server
# ============================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "Stopping llama-server..."

if pgrep -f "llama-server" > /dev/null 2>&1; then
    PID=$(pgrep -f "llama-server")
    echo "Found llama-server with PID: $PID"

    kill $PID
    sleep 2

    if pgrep -f "llama-server" > /dev/null 2>&1; then
        echo -e "${YELLOW}Process still running, sending SIGKILL...${NC}"
        kill -9 $PID
        sleep 1
    fi

    if pgrep -f "llama-server" > /dev/null 2>&1; then
        echo -e "${RED}ERROR: Failed to stop llama-server${NC}"
        exit 1
    else
        echo -e "${GREEN}llama-server stopped successfully${NC}"
    fi
else
    echo -e "${YELLOW}llama-server is not running${NC}"
fi
