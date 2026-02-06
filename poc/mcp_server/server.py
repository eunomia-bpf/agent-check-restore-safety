#!/usr/bin/env python3
"""
MCP Tool Server for Semantic Rollback Experiments

This server provides tools that demonstrate the semantic rollback vulnerability:
- create_payment: Payment tool with idempotency key tracking
- use_token: Single-use token consumption tracking

The server maintains state that is NOT tracked by Claude Code's checkpoint mechanism,
allowing us to observe state divergence when sessions are replayed.
"""
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import json
import sys
from datetime import datetime
from pathlib import Path

# Global state (NOT tracked by Claude Code checkpoint)
request_log = []
idempotency_keys = {}
consumed_tokens = set()

# Log file for persistence across runs
LOG_FILE = Path(__file__).parent.parent / "results" / "mcp_requests.jsonl"

server = Server("experiment-tools")


def append_to_log(entry: dict):
    """Append entry to both in-memory log and file"""
    request_log.append(entry)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="create_payment",
            description="Create a payment charge. Requires order_id, amount (in cents), and a unique idempotency_key to prevent duplicate charges.",
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
                        "description": "A unique key to prevent duplicate charges. Must be unique per payment attempt."
                    },
                },
                "required": ["order_id", "amount", "idempotency_key"]
            }
        ),
        Tool(
            name="use_token",
            description="Use a single-use authorization token. The token can only be used once.",
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
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    global request_log, idempotency_keys, consumed_tokens

    timestamp = datetime.now().isoformat()

    if name == "create_payment":
        order_id = arguments.get("order_id", "")
        amount = arguments.get("amount", 0)
        key = arguments.get("idempotency_key", "")

        entry = {
            "timestamp": timestamp,
            "tool": name,
            "order_id": order_id,
            "amount": amount,
            "idempotency_key": key,
        }

        # Check for duplicate
        if key in idempotency_keys:
            entry["result"] = "duplicate"
            append_to_log(entry)
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "duplicate",
                    "message": f"Idempotency key '{key}' was already used",
                    "original_charge_id": idempotency_keys[key]["charge_id"]
                })
            )]

        # Process new payment
        charge_id = f"ch_{len(idempotency_keys) + 1:06d}"
        idempotency_keys[key] = {
            "order_id": order_id,
            "amount": amount,
            "charge_id": charge_id,
            "timestamp": timestamp
        }
        entry["result"] = "success"
        entry["charge_id"] = charge_id
        append_to_log(entry)

        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "success",
                "charge_id": charge_id,
                "order_id": order_id,
                "amount": amount,
                "message": f"Payment of ${amount/100:.2f} processed successfully"
            })
        )]

    elif name == "use_token":
        token = arguments.get("token", "")
        action = arguments.get("action", "")

        entry = {
            "timestamp": timestamp,
            "tool": name,
            "token": token,
            "action": action,
        }

        # Check if token already consumed
        if token in consumed_tokens:
            entry["result"] = "rejected"
            append_to_log(entry)
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "rejected",
                    "reason": "Token has already been consumed",
                    "token": token
                })
            )]

        # Consume token
        consumed_tokens.add(token)
        entry["result"] = "success"
        append_to_log(entry)

        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "success",
                "message": f"Token consumed successfully for action: {action}",
                "token": token
            })
        )]

    elif name == "get_server_stats":
        stats = {
            "total_requests": len(request_log),
            "unique_idempotency_keys": len(idempotency_keys),
            "consumed_tokens": len(consumed_tokens),
            "recent_requests": request_log[-10:] if request_log else [],
        }
        return [TextContent(type="text", text=json.dumps(stats, indent=2))]

    elif name == "reset_server_state":
        request_log = []
        idempotency_keys = {}
        consumed_tokens = set()
        # Also clear the log file
        if LOG_FILE.exists():
            LOG_FILE.unlink()
        return [TextContent(
            type="text",
            text=json.dumps({"status": "reset", "message": "All server state cleared"})
        )]

    return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


async def main():
    """Run the MCP server using stdio transport"""
    async with stdio_server() as streams:
        await server.run(
            streams[0],
            streams[1],
            server.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
