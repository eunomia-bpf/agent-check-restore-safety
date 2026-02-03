#!/usr/bin/env python3
"""
Minimal PoC: Verify semantic rollback vulnerability (Action Duplication)

This script demonstrates that LLM agents generate different idempotency keys
when given the same task after a simulated "restore", causing duplicate actions.

Usage:
    1. Start llama-server:
       cd /home/yunwei37/workspace/gpu/llama.cpp
       build/bin/llama-server -hf unsloth/Qwen3-Next-80B-A3B-Instruct-GGUF:Q4_K_M -c 65536

    2. Run this script:
       python poc/simple_test.py
"""

import json
import requests
from dataclasses import dataclass
from typing import Optional
import copy

# ============================================================================
# Configuration
# ============================================================================

LLAMA_SERVER_URL = "http://localhost:8080/v1/chat/completions"
MODEL_NAME = "qwen3"  # llama.cpp uses this as model name

# ============================================================================
# Simple Payment Service (in-memory)
# ============================================================================

class PaymentService:
    """Simple payment service with idempotency key support"""

    def __init__(self):
        self.charges = {}  # idempotency_key -> charge_record
        self.request_log = []  # append-only log

    def create_charge(self, order_id: str, amount: int, idempotency_key: str) -> dict:
        """Create a charge with idempotency protection"""

        # Log the request (append-only)
        self.request_log.append({
            "order_id": order_id,
            "amount": amount,
            "idempotency_key": idempotency_key,
        })

        # Check idempotency
        if idempotency_key in self.charges:
            return {
                "status": "duplicate",
                "charge_id": self.charges[idempotency_key]["charge_id"],
                "message": "Idempotency key already used"
            }

        # Create new charge
        charge_id = f"ch_{len(self.charges) + 1:04d}"
        self.charges[idempotency_key] = {
            "charge_id": charge_id,
            "order_id": order_id,
            "amount": amount,
        }

        return {
            "status": "succeeded",
            "charge_id": charge_id,
            "message": "Charge created"
        }

    def get_stats(self) -> dict:
        """Get statistics for analysis"""
        return {
            "total_requests": len(self.request_log),
            "unique_charges": len(self.charges),
            "duplicate_requests": len(self.request_log) - len(self.charges),
        }


# ============================================================================
# Simple LLM Agent
# ============================================================================

@dataclass
class AgentState:
    """Agent state that would be checkpointed"""
    conversation_history: list
    task: str
    completed: bool = False


class SimpleAgent:
    """Simple agent that calls LLM to generate tool calls"""

    def __init__(self, llm_url: str = LLAMA_SERVER_URL):
        self.llm_url = llm_url
        self.state = None

    def init_task(self, task: str):
        """Initialize agent with a task"""
        self.state = AgentState(
            conversation_history=[],
            task=task,
            completed=False
        )

    def checkpoint(self) -> AgentState:
        """Save agent state (simulated checkpoint)"""
        return copy.deepcopy(self.state)

    def restore(self, state: AgentState):
        """Restore agent state (simulated restore)"""
        self.state = copy.deepcopy(state)

    def generate_tool_call(self) -> dict:
        """Call LLM to generate a payment tool call"""

        system_prompt = """You are a payment processing agent. When asked to process a payment,
you must generate a JSON tool call with the following format:

{
    "tool": "create_charge",
    "order_id": "<order_id from the request>",
    "amount": <amount in cents>,
    "idempotency_key": "<generate a unique key for this transaction>"
}

IMPORTANT: Generate a unique idempotency_key for each transaction. The key should be
a string that uniquely identifies this specific payment request.

Respond ONLY with the JSON, no other text. Do not use markdown or code block. Enable no_think mode."""

        user_prompt = f"Process this payment request: {self.state.task}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # Call LLM
        try:
            response = requests.post(
                self.llm_url,
                json={
                    "model": MODEL_NAME,
                    "messages": messages,
                    "temperature": 0.7,  # Non-zero for demonstration
                    "max_tokens": 256,
                },
                timeout=60
            )
            response.raise_for_status()

            result = response.json()
            content = result["choices"][0]["message"]["content"]

            # Parse JSON from response
            # Handle potential markdown code blocks
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])

            tool_call = json.loads(content)
            return tool_call

        except requests.exceptions.RequestException as e:
            print(f"Error calling LLM: {e}")
            raise
        except json.JSONDecodeError as e:
            print(f"Error parsing LLM response: {e}")
            print(f"Raw response: {content}")
            raise


# ============================================================================
# Experiment
# ============================================================================

def run_experiment(num_trials: int = 10):
    """
    Run the experiment:
    1. For each trial, give agent a task
    2. Checkpoint before generating tool call
    3. Generate tool call (get idempotency_key_1)
    4. Simulate crash & restore
    5. Generate tool call again (get idempotency_key_2)
    6. Check if keys differ (vulnerability confirmed if they do)
    """

    print("=" * 60)
    print("Semantic Rollback PoC: Action Duplication")
    print("=" * 60)
    print()

    payment_service = PaymentService()
    agent = SimpleAgent()

    results = []

    for trial in range(num_trials):
        order_id = f"order_{trial + 1:04d}"
        amount = 4999  # $49.99
        task = f"Process a payment of ${amount/100:.2f} for order #{order_id}"

        print(f"Trial {trial + 1}/{num_trials}: {task}")

        # Initialize agent with task
        agent.init_task(task)

        # === CHECKPOINT ===
        saved_state = agent.checkpoint()
        print(f"  [Checkpoint] State saved")

        # Generate first tool call
        try:
            tool_call_1 = agent.generate_tool_call()
            key_1 = tool_call_1.get("idempotency_key", "MISSING")
            print(f"  [Before restore] idempotency_key = {key_1}")

            # Execute the tool call
            result_1 = payment_service.create_charge(
                order_id=tool_call_1.get("order_id", order_id),
                amount=tool_call_1.get("amount", amount),
                idempotency_key=key_1
            )
            print(f"  [Payment Service] {result_1['status']}: {result_1['charge_id']}")

        except Exception as e:
            print(f"  [Error] First call failed: {e}")
            continue

        # === SIMULATE CRASH & RESTORE ===
        agent.restore(saved_state)
        print(f"  [Restore] State restored from checkpoint")

        # Generate second tool call (after restore)
        try:
            tool_call_2 = agent.generate_tool_call()
            key_2 = tool_call_2.get("idempotency_key", "MISSING")
            print(f"  [After restore] idempotency_key = {key_2}")

            # Execute the tool call
            result_2 = payment_service.create_charge(
                order_id=tool_call_2.get("order_id", order_id),
                amount=tool_call_2.get("amount", amount),
                idempotency_key=key_2
            )
            print(f"  [Payment Service] {result_2['status']}: {result_2['charge_id']}")

        except Exception as e:
            print(f"  [Error] Second call failed: {e}")
            continue

        # Record result
        key_changed = (key_1 != key_2)
        duplicate_created = (result_2["status"] == "succeeded")  # New charge created

        results.append({
            "trial": trial + 1,
            "order_id": order_id,
            "key_1": key_1,
            "key_2": key_2,
            "key_changed": key_changed,
            "duplicate_created": duplicate_created,
        })

        status = "VULNERABLE" if duplicate_created else "PROTECTED"
        print(f"  [Result] Key changed: {key_changed}, Duplicate: {duplicate_created} -> {status}")
        print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    total = len(results)
    key_changes = sum(1 for r in results if r["key_changed"])
    duplicates = sum(1 for r in results if r["duplicate_created"])

    print(f"Total trials: {total}")
    print(f"Key instability rate: {key_changes}/{total} ({100*key_changes/total:.1f}%)")
    print(f"Duplicate rate: {duplicates}/{total} ({100*duplicates/total:.1f}%)")
    print()
    print("Payment Service Stats:")
    stats = payment_service.get_stats()
    print(f"  Total requests: {stats['total_requests']}")
    print(f"  Unique charges: {stats['unique_charges']}")
    print(f"  Duplicates blocked: {stats['duplicate_requests']}")
    print()

    if duplicates > 0:
        print("CONCLUSION: Semantic rollback vulnerability CONFIRMED!")
        print("LLM non-determinism causes different idempotency keys after restore,")
        print("bypassing idempotency protection and creating duplicate charges.")
    else:
        print("CONCLUSION: No duplicates observed in this run.")
        print("Try increasing trials or temperature for more variation.")

    return results


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Semantic Rollback PoC")
    parser.add_argument("--trials", type=int, default=10, help="Number of trials")
    parser.add_argument("--llm-url", type=str, default=LLAMA_SERVER_URL, help="LLM server URL")
    args = parser.parse_args()

    # Check if LLM server is running
    print(f"Checking LLM server at {args.llm_url}...")
    try:
        health_url = args.llm_url.replace("/v1/chat/completions", "/health")
        resp = requests.get(health_url, timeout=5)
        print(f"LLM server is running (status: {resp.status_code})")
    except requests.exceptions.RequestException:
        print("WARNING: Cannot reach LLM server. Make sure llama-server is running:")
        print("  cd /home/yunwei37/workspace/gpu/llama.cpp")
        print("  build/bin/llama-server -hf unsloth/Qwen3-Next-80B-A3B-Instruct-GGUF:Q4_K_M -c 65536")
        print()
        input("Press Enter to continue anyway, or Ctrl+C to exit...")

    print()
    run_experiment(num_trials=args.trials)
