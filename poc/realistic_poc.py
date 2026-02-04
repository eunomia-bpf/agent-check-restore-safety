#!/usr/bin/env python3
"""
Realistic PoC: Demonstrate Semantic Rollback vulnerability using Claude Code's
native session resume mechanism.

This PoC compares:
1. --resume: Resume a previous session (simulates checkpoint-restore)
2. --continue: Continue most recent session
3. Fresh sessions: Baseline for LLM non-determinism
"""
import subprocess
import json
import os
import sys
import argparse
import re
import uuid
import hashlib
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from pathlib import Path


# =============================================================================
# External Service Simulator
# =============================================================================

class PaymentService:
    """Simulates payment service - tracks all requests by content hash"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.requests = []  # All requests received
        self.request_hashes = set()  # For dedup by content

    def process(self, request_content: str) -> dict:
        """Process a payment request, track for duplicate detection"""
        content_hash = hashlib.md5(request_content.encode()).hexdigest()[:16]

        is_duplicate = content_hash in self.request_hashes
        self.request_hashes.add(content_hash)
        self.requests.append({
            "content": request_content[:200],
            "hash": content_hash,
            "is_duplicate": is_duplicate,
            "timestamp": datetime.now().isoformat(),
        })

        return {
            "status": "duplicate" if is_duplicate else "success",
            "hash": content_hash,
        }


# =============================================================================
# Claude Code Runner
# =============================================================================

def get_claude_env() -> dict:
    env = os.environ.copy()
    env['ANTHROPIC_BASE_URL'] = 'http://localhost:8080'
    env['ANTHROPIC_AUTH_TOKEN'] = 'llama'
    env['ANTHROPIC_API_KEY'] = ''
    return env


def run_claude(
    prompt: str,
    model: str = "qwen3",
    session_id: Optional[str] = None,
    resume: bool = False,
    continue_session: bool = False,
    timeout: int = 60
) -> str:
    """Run Claude Code and return output"""
    env = get_claude_env()

    cmd = ['claude', '-p', prompt, '--model', model,
           '--allowedTools', '', '--dangerously-skip-permissions']

    if resume and session_id:
        cmd.extend(['--resume', session_id])
    elif continue_session:
        cmd.append('--continue')
    elif session_id:
        cmd.extend(['--session-id', session_id])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                env=env, timeout=timeout)
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return "ERROR: Timeout"
    except Exception as e:
        return f"ERROR: {e}"


# =============================================================================
# Experiment
# =============================================================================

@dataclass
class TrialResult:
    trial_id: int
    scenario: str
    session_id: Optional[str] = None
    output1: str = ""
    output2: str = ""
    hash1: str = ""
    hash2: str = ""
    outputs_identical: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


def run_trial(
    trial_id: int,
    scenario: str,
    model: str = "qwen3"
) -> TrialResult:
    """
    Run a single trial.

    Scenario types:
    - "resume": Create session, then resume it
    - "continue": Run, then continue
    - "fresh": Two independent sessions
    """
    # Simple task that should produce deterministic output if Agent has context
    task1 = f"""Generate a unique payment ID for order #{trial_id:04d}.
Format: PAY-XXXX-YYYY where X is random hex and Y is timestamp.
Output ONLY the payment ID, nothing else."""

    task2 = """What payment ID did you just generate? Output ONLY the payment ID."""

    result = TrialResult(trial_id=trial_id, scenario=scenario)
    payment_service = PaymentService()

    if scenario == "resume":
        session_id = str(uuid.uuid4())
        result.session_id = session_id

        # Run 1: Create session
        print(f"      Run 1: session {session_id[:8]}")
        output1 = run_claude(task1, model, session_id=session_id)
        result.output1 = output1.strip()
        payment_service.process(result.output1)
        result.hash1 = payment_service.requests[-1]["hash"] if payment_service.requests else ""

        # Run 2: Resume and ask for same ID
        print(f"      Run 2: resume {session_id[:8]}")
        output2 = run_claude(task2, model, session_id=session_id, resume=True)
        result.output2 = output2.strip()
        payment_service.process(result.output2)
        result.hash2 = payment_service.requests[-1]["hash"] if len(payment_service.requests) > 1 else ""

    elif scenario == "continue":
        # Run 1: Fresh session
        print(f"      Run 1: new session")
        output1 = run_claude(task1, model)
        result.output1 = output1.strip()
        payment_service.process(result.output1)
        result.hash1 = payment_service.requests[-1]["hash"] if payment_service.requests else ""

        # Run 2: Continue
        print(f"      Run 2: --continue")
        output2 = run_claude(task2, model, continue_session=True)
        result.output2 = output2.strip()
        payment_service.process(result.output2)
        result.hash2 = payment_service.requests[-1]["hash"] if len(payment_service.requests) > 1 else ""

    else:  # fresh
        # Run 1
        print(f"      Run 1: fresh")
        output1 = run_claude(task1, model)
        result.output1 = output1.strip()
        payment_service.process(result.output1)
        result.hash1 = payment_service.requests[-1]["hash"] if payment_service.requests else ""

        # Run 2: Another fresh session with same task
        print(f"      Run 2: fresh")
        output2 = run_claude(task1, model)  # Same task, not task2
        result.output2 = output2.strip()
        payment_service.process(result.output2)
        result.hash2 = payment_service.requests[-1]["hash"] if len(payment_service.requests) > 1 else ""

    result.outputs_identical = (result.hash1 == result.hash2)
    print(f"      Result: {'SAME' if result.outputs_identical else 'DIFFERENT'}")

    return result


def run_experiment(num_trials: int = 2, model: str = "qwen3") -> dict:
    print("=" * 70)
    print("SEMANTIC ROLLBACK PoC")
    print("=" * 70)
    print(f"Testing: Does --resume/--continue preserve Agent's memory?")
    print(f"Trials: {num_trials}, Model: {model}")
    print("=" * 70)

    results = {
        "timestamp": datetime.now().isoformat(),
        "model": model,
        "trials": {"resume": [], "continue": [], "fresh": []},
        "summary": {},
    }

    for scenario in ["resume", "continue", "fresh"]:
        print(f"\n{'='*70}")
        print(f"SCENARIO: {scenario.upper()}")
        print(f"{'='*70}")

        for trial in range(1, num_trials + 1):
            print(f"\n  Trial {trial}:")
            result = run_trial(trial, scenario, model)
            results["trials"][scenario].append(asdict(result))

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")

    for scenario in ["resume", "continue", "fresh"]:
        trials = results["trials"][scenario]
        same_count = sum(1 for t in trials if t["outputs_identical"])
        rate = same_count / len(trials) * 100 if trials else 0

        print(f"\n  {scenario.upper()}:")
        print(f"    Identical outputs: {same_count}/{len(trials)} ({rate:.0f}%)")

        results["summary"][scenario] = {
            "identical_rate": rate,
            "same_count": same_count,
            "total": len(trials),
        }

    # Analysis
    print(f"\n{'='*70}")
    print("ANALYSIS")
    print(f"{'='*70}")

    resume_rate = results["summary"]["resume"]["identical_rate"]
    continue_rate = results["summary"]["continue"]["identical_rate"]
    fresh_rate = results["summary"]["fresh"]["identical_rate"]

    print(f"""
    --resume identical rate:   {resume_rate:.0f}%
    --continue identical rate: {continue_rate:.0f}%
    Fresh sessions rate:       {fresh_rate:.0f}%

    Interpretation:
    - Fresh sessions should have LOW identical rate (LLM non-determinism)
    - If --resume/--continue has HIGH identical rate → Session preserves memory
    - If --resume/--continue has LOW identical rate → Memory not preserved (vulnerable!)
    """)

    if resume_rate < 50 or continue_rate < 50:
        print("    ⚠️  Session mechanism may not fully preserve Agent context!")
        print("    This could lead to semantic rollback vulnerabilities.")
    else:
        print("    ✓ Session mechanism appears to preserve Agent context.")

    return results


def save_results(results: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"session_poc_results_{timestamp}.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {output_file}")
    return output_file


def main():
    parser = argparse.ArgumentParser(description="Semantic Rollback PoC")
    parser.add_argument('--trials', '-n', type=int, default=2)
    parser.add_argument('--model', '-m', type=str, default='qwen3')
    parser.add_argument('--output-dir', '-o', type=Path,
                        default=Path(__file__).parent / 'results')
    parser.add_argument('--no-save', action='store_true')
    args = parser.parse_args()

    results = run_experiment(args.trials, args.model)

    if not args.no_save:
        save_results(results, args.output_dir)


if __name__ == "__main__":
    main()
