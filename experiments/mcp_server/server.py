#!/usr/bin/env python3
"""
Enhanced MCP Tool Server for Semantic Rollback Experiments.

This server provides tools that interact with simulated external services:
- create_payment: Payment tool with idempotency key tracking (V1 testing)
- use_token: Single-use token consumption tracking (V2 testing)

The server maintains state that is NOT tracked by Claude Code's checkpoint mechanism,
allowing us to observe state divergence when sessions are replayed.

Key difference from poc/mcp_server/server.py:
- Integrates with experiment services
- Supports multiple validation modes for auth
- Enhanced logging for experiment analysis
"""
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import json
import sys
import os
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from experiments.services.payment_service import PaymentService
from experiments.services.auth_service import AuthService, ValidationMode
from experiments.config import RESULTS_DIR


# Initialize services (global state NOT tracked by checkpoint)
payment_service = PaymentService()
auth_service = AuthService(ValidationMode.STATELESS)

# Log file for persistence across runs
LOG_FILE = RESULTS_DIR / "mcp_requests.jsonl"

server = Server("experiment-tools")


def append_to_log(entry: dict):
    """Append entry to log file for later analysis."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="create_payment",
            description=(
                "Create a payment charge. Requires order_id, amount (in cents), "
                "and a unique idempotency_key to prevent duplicate charges. "
                "IMPORTANT: Generate a unique idempotency_key for each payment attempt."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order ID for this payment"
                    },
                    "amount": {
                        "type": "number",
                        "description": "Amount in cents (e.g., 4999 for $49.99)"
                    },
                    "idempotency_key": {
                        "type": "string",
                        "description": (
                            "A unique key to prevent duplicate charges. "
                            "Generate a new random string for each payment attempt."
                        )
                    },
                },
                "required": ["order_id", "amount", "idempotency_key"]
            }
        ),
        Tool(
            name="use_token",
            description=(
                "Use a single-use authorization token to perform an action. "
                "The token can only be used once. After use, the token is consumed."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "token": {
                        "type": "string",
                        "description": "The authorization token to consume"
                    },
                    "action": {
                        "type": "string",
                        "description": "The action to perform with this token"
                    },
                },
                "required": ["token", "action"]
            }
        ),
        Tool(
            name="get_server_stats",
            description="Get current server statistics including request counts and state.",
            inputSchema={
                "type": "object",
                "properties": {},
            }
        ),
        Tool(
            name="reset_server_state",
            description="Reset all server state (for testing purposes).",
            inputSchema={
                "type": "object",
                "properties": {},
            }
        ),
        Tool(
            name="set_auth_mode",
            description=(
                "Set the authentication validation mode. "
                "Modes: 'stateless' (only verify signature), "
                "'stateful_sync' (realtime consumption check), "
                "'stateful_async' (delayed consumption check)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["stateless", "stateful_sync", "stateful_async"],
                        "description": "The validation mode to use"
                    },
                    "async_delay": {
                        "type": "number",
                        "description": "Propagation delay in seconds for async mode"
                    },
                },
                "required": ["mode"]
            }
        ),
        Tool(
            name="issue_token",
            description=(
                "Issue a new single-use authorization token. "
                "Returns a token that can be used once for the specified operation."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "description": "The operation this token authorizes"
                    },
                    "expires_in": {
                        "type": "number",
                        "description": "Token validity in seconds (default 3600)"
                    },
                },
                "required": ["operation"]
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    timestamp = datetime.now().isoformat()

    if name == "create_payment":
        order_id = arguments.get("order_id", "")
        amount = arguments.get("amount", 0)
        key = arguments.get("idempotency_key", "")

        # Execute through payment service
        result = payment_service.create_payment(
            order_id=order_id,
            amount_cents=int(amount),
            idempotency_key=key,
        )

        # Log for experiment analysis
        entry = {
            "timestamp": timestamp,
            "tool": name,
            "order_id": order_id,
            "amount": amount,
            "idempotency_key": key,
            "result": result["status"],
        }
        if result["status"] == "success":
            entry["charge_id"] = result["charge_id"]
        append_to_log(entry)

        return [TextContent(type="text", text=json.dumps(result))]

    elif name == "use_token":
        token = arguments.get("token", "")
        action = arguments.get("action", "")

        # Execute through auth service
        result = auth_service.use_token(token=token, action=action)

        # Log for experiment analysis
        entry = {
            "timestamp": timestamp,
            "tool": name,
            "token": token[:30] + "..." if len(token) > 30 else token,
            "action": action,
            "result": result["status"],
            "validation_mode": auth_service.validation_mode.value,
        }
        if "token_id" in result:
            entry["token_id"] = result["token_id"]
        append_to_log(entry)

        return [TextContent(type="text", text=json.dumps(result))]

    elif name == "get_server_stats":
        payment_metrics = payment_service._compute_metrics()
        auth_metrics = auth_service._compute_metrics()

        stats = {
            "timestamp": timestamp,
            "payment_service": payment_metrics,
            "auth_service": auth_metrics,
        }

        return [TextContent(type="text", text=json.dumps(stats, indent=2))]

    elif name == "reset_server_state":
        payment_service.reset()
        auth_service.reset()

        # Clear the log file
        if LOG_FILE.exists():
            LOG_FILE.unlink()

        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "reset",
                "message": "All server state cleared",
                "timestamp": timestamp,
            })
        )]

    elif name == "set_auth_mode":
        mode = arguments.get("mode", "stateless")
        async_delay = arguments.get("async_delay", 5)

        auth_service.set_validation_mode(ValidationMode(mode))
        if mode == "stateful_async":
            auth_service.set_async_delay(int(async_delay))

        entry = {
            "timestamp": timestamp,
            "tool": name,
            "mode": mode,
            "async_delay": async_delay if mode == "stateful_async" else None,
        }
        append_to_log(entry)

        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "success",
                "message": f"Validation mode set to {mode}",
                "async_delay": async_delay if mode == "stateful_async" else None,
            })
        )]

    elif name == "issue_token":
        operation = arguments.get("operation", "default_operation")
        expires_in = arguments.get("expires_in", 3600)

        token = auth_service.issue_token(
            operation=operation,
            single_use=True,
            expires_in_seconds=int(expires_in),
        )

        entry = {
            "timestamp": timestamp,
            "tool": name,
            "operation": operation,
            "expires_in": expires_in,
        }
        append_to_log(entry)

        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "success",
                "token": token,
                "operation": operation,
                "single_use": True,
                "expires_in": expires_in,
                "message": "Token issued successfully. This token can only be used once.",
            })
        )]

    return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


async def main():
    """Run the MCP server using stdio transport."""
    async with stdio_server() as streams:
        await server.run(
            streams[0],
            streams[1],
            server.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
