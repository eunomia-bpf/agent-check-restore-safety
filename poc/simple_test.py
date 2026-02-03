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
from dataclasses import dataclass, asdict
from typing import Optional, List
from datetime import datetime
from pathlib import Path
import copy
import os

# ============================================================================
# Configuration
# ============================================================================

LLAMA_SERVER_URL = "http://localhost:8080/v1/chat/completions"
MODEL_NAME = "qwen3"  # llama.cpp uses this as model name

# Prompts (stored as constants for logging)
SYSTEM_PROMPT = """You are a payment processing agent. When asked to process a payment,
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

USER_PROMPT_TEMPLATE = "Process this payment request: {task}"

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

        timestamp = datetime.now().isoformat()

        # Log the request (append-only)
        self.request_log.append({
            "timestamp": timestamp,
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
            "created_at": timestamp,
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

    def get_full_log(self) -> List[dict]:
        """Get full request log"""
        return self.request_log.copy()

    def get_all_charges(self) -> dict:
        """Get all charges"""
        return self.charges.copy()


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

    def __init__(self, llm_url: str = LLAMA_SERVER_URL, temperature: float = 0.7):
        self.llm_url = llm_url
        self.temperature = temperature
        self.state = None
        self.last_raw_response = None  # Store for logging

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

        user_prompt = USER_PROMPT_TEMPLATE.format(task=self.state.task)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

        # Call LLM
        try:
            response = requests.post(
                self.llm_url,
                json={
                    "model": MODEL_NAME,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_tokens": 256,
                },
                timeout=60
            )
            response.raise_for_status()

            result = response.json()
            self.last_raw_response = result  # Store for logging
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
# Experiment Result Storage
# ============================================================================

@dataclass
class TrialResult:
    """Result of a single trial"""
    trial_id: int
    order_id: str
    task: str

    # Before restore
    key_before: str
    tool_call_before: dict
    raw_response_before: dict
    service_result_before: dict

    # After restore
    key_after: str
    tool_call_after: dict
    raw_response_after: dict
    service_result_after: dict

    # Analysis
    key_changed: bool
    duplicate_created: bool

    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class ExperimentConfig:
    """Experiment configuration"""
    llm_url: str
    model_name: str
    temperature: float
    max_tokens: int
    num_trials: int
    system_prompt: str
    user_prompt_template: str


@dataclass
class ExperimentResult:
    """Full experiment result"""
    experiment_id: str
    start_time: str
    end_time: str
    config: ExperimentConfig
    trials: List[TrialResult]
    summary: dict
    payment_service_log: List[dict]
    payment_service_charges: dict


def save_experiment_result(result: ExperimentResult, output_dir: str = "results"):
    """Save experiment result to JSON file"""

    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate filename
    filename = f"experiment_{result.experiment_id}.json"
    filepath = output_path / filename

    # Convert to dict (handle dataclasses)
    def to_dict(obj):
        if hasattr(obj, '__dataclass_fields__'):
            return {k: to_dict(v) for k, v in asdict(obj).items()}
        elif isinstance(obj, list):
            return [to_dict(item) for item in obj]
        elif isinstance(obj, dict):
            return {k: to_dict(v) for k, v in obj.items()}
        else:
            return obj

    result_dict = to_dict(result)

    # Save to file
    with open(filepath, 'w') as f:
        json.dump(result_dict, f, indent=2, ensure_ascii=False)

    print(f"Results saved to: {filepath}")
    return filepath


# ============================================================================
# Experiment
# ============================================================================

def run_experiment(num_trials: int = 10, temperature: float = 0.7,
                   llm_url: str = LLAMA_SERVER_URL, output_dir: str = "results"):
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

    # Experiment setup
    experiment_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    start_time = datetime.now().isoformat()

    config = ExperimentConfig(
        llm_url=llm_url,
        model_name=MODEL_NAME,
        temperature=temperature,
        max_tokens=256,
        num_trials=num_trials,
        system_prompt=SYSTEM_PROMPT,
        user_prompt_template=USER_PROMPT_TEMPLATE,
    )

    print(f"Experiment ID: {experiment_id}")
    print(f"LLM URL: {llm_url}")
    print(f"Temperature: {temperature}")
    print(f"Trials: {num_trials}")
    print()

    payment_service = PaymentService()
    agent = SimpleAgent(llm_url=llm_url, temperature=temperature)

    trial_results = []

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
            raw_response_1 = copy.deepcopy(agent.last_raw_response)
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
            raw_response_2 = copy.deepcopy(agent.last_raw_response)
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

        trial_result = TrialResult(
            trial_id=trial + 1,
            order_id=order_id,
            task=task,
            key_before=key_1,
            tool_call_before=tool_call_1,
            raw_response_before=raw_response_1,
            service_result_before=result_1,
            key_after=key_2,
            tool_call_after=tool_call_2,
            raw_response_after=raw_response_2,
            service_result_after=result_2,
            key_changed=key_changed,
            duplicate_created=duplicate_created,
        )
        trial_results.append(trial_result)

        status = "VULNERABLE" if duplicate_created else "PROTECTED"
        print(f"  [Result] Key changed: {key_changed}, Duplicate: {duplicate_created} -> {status}")
        print()

    # Summary
    end_time = datetime.now().isoformat()

    total = len(trial_results)
    key_changes = sum(1 for r in trial_results if r.key_changed)
    duplicates = sum(1 for r in trial_results if r.duplicate_created)

    summary = {
        "total_trials": total,
        "key_changes": key_changes,
        "key_instability_rate": key_changes / total if total > 0 else 0,
        "duplicates": duplicates,
        "duplicate_rate": duplicates / total if total > 0 else 0,
        "payment_service_stats": payment_service.get_stats(),
    }

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    print(f"Total trials: {total}")
    print(f"Key instability rate: {key_changes}/{total} ({100*summary['key_instability_rate']:.1f}%)")
    print(f"Duplicate rate: {duplicates}/{total} ({100*summary['duplicate_rate']:.1f}%)")
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

    # Save results
    experiment_result = ExperimentResult(
        experiment_id=experiment_id,
        start_time=start_time,
        end_time=end_time,
        config=config,
        trials=trial_results,
        summary=summary,
        payment_service_log=payment_service.get_full_log(),
        payment_service_charges=payment_service.get_all_charges(),
    )

    # Determine output directory (relative to script location)
    script_dir = Path(__file__).parent.parent
    results_dir = script_dir / output_dir

    saved_path = save_experiment_result(experiment_result, str(results_dir))

    return experiment_result


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Semantic Rollback PoC")
    parser.add_argument("--trials", type=int, default=10, help="Number of trials")
    parser.add_argument("--temperature", type=float, default=0.7, help="LLM temperature")
    parser.add_argument("--llm-url", type=str, default=LLAMA_SERVER_URL, help="LLM server URL")
    parser.add_argument("--output-dir", type=str, default="results", help="Output directory for results")
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
    run_experiment(
        num_trials=args.trials,
        temperature=args.temperature,
        llm_url=args.llm_url,
        output_dir=args.output_dir,
    )
