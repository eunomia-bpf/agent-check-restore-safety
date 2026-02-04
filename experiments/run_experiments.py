#!/usr/bin/env python3
"""
Main runner script for Semantic Rollback Experiments.

Usage:
    # Run all experiments
    python -m experiments.run_experiments

    # Run specific experiment
    python -m experiments.run_experiments --exp 1
    python -m experiments.run_experiments --exp 2

    # Configure trials
    python -m experiments.run_experiments --trials 10

    # Quiet mode
    python -m experiments.run_experiments -q
"""
import argparse
import sys
import json
from datetime import datetime
from pathlib import Path

from .exp1_action_replay import ActionReplayExperiment
from .exp2_authority_resurrection import AuthorityResurrectionExperiment
from .config import (
    DEFAULT_CONFIG, RESULTS_DIR, THRESHOLDS,
    ensure_local_llm_ready, verify_env_setup
)


def print_banner():
    """Print experiment banner."""
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║         SEMANTIC ROLLBACK VULNERABILITY EXPERIMENTS                  ║
║                                                                      ║
║  Testing checkpoint-restore vulnerabilities in LLM agents:           ║
║  • V1: Action Replay - Duplicate operations via key instability      ║
║  • V2: Authority Resurrection - Token reuse after state rollback     ║
╚══════════════════════════════════════════════════════════════════════╝
""")


def run_experiment_1(n_trials: int, verbose: bool) -> dict:
    """Run Experiment 1: Action Replay."""
    print("\n" + "=" * 70)
    print("STARTING EXPERIMENT 1: ACTION REPLAY (V1)")
    print("=" * 70)

    experiment = ActionReplayExperiment(
        n_trials=n_trials,
        verbose=verbose,
    )
    return experiment.run_all()


def run_experiment_2(n_trials: int, verbose: bool) -> dict:
    """Run Experiment 2: Authority Resurrection."""
    print("\n" + "=" * 70)
    print("STARTING EXPERIMENT 2: AUTHORITY RESURRECTION (V2)")
    print("=" * 70)

    experiment = AuthorityResurrectionExperiment(
        n_trials=n_trials,
        verbose=verbose,
    )
    return experiment.run_all()


def summarize_results(exp1_metrics: dict, exp2_metrics: dict) -> dict:
    """Generate overall summary of all experiments."""
    summary = {
        "timestamp": datetime.now().isoformat(),
        "vulnerabilities_confirmed": [],
        "exp1_summary": {},
        "exp2_summary": {},
    }

    # Analyze Experiment 1
    if exp1_metrics:
        s1_results = exp1_metrics.get("S1_TM1_DoW", {})
        s2_results = exp1_metrics.get("S2_TM2_Fraud", {})
        baseline = exp1_metrics.get("No_CR_Baseline", {})

        v1_confirmed = (
            getattr(s1_results, 'duplicate_rate', 0) > THRESHOLDS["duplicate_rate"] and
            getattr(baseline, 'duplicate_rate', 1) < THRESHOLDS["baseline_duplicate_rate"]
        )

        if v1_confirmed:
            summary["vulnerabilities_confirmed"].append("V1: Action Replay")

        summary["exp1_summary"] = {
            "s1_duplicate_rate": getattr(s1_results, 'duplicate_rate', 0),
            "s1_key_instability": getattr(s1_results, 'key_instability_rate', 0),
            "s2_free_service_rate": getattr(s2_results, 'duplicate_rate', 0),
            "baseline_duplicate_rate": getattr(baseline, 'duplicate_rate', 0),
            "v1_confirmed": v1_confirmed,
        }

    # Analyze Experiment 2
    if exp2_metrics:
        stateless_vulnerable = False
        stateful_secure = True

        for scenario, metrics in exp2_metrics.items():
            if "stateless" in scenario.lower():
                if getattr(metrics, 'unauthorized_rate', 0) > THRESHOLDS["stateless_unauthorized_rate"]:
                    stateless_vulnerable = True
            if "stateful_sync" in scenario.lower():
                if getattr(metrics, 'unauthorized_rate', 0) > THRESHOLDS["stateful_unauthorized_rate"]:
                    stateful_secure = False

        if stateless_vulnerable:
            summary["vulnerabilities_confirmed"].append("V2: Authority Resurrection (stateless)")

        summary["exp2_summary"] = {
            "stateless_vulnerable": stateless_vulnerable,
            "stateful_secure": stateful_secure,
            "v2_confirmed": stateless_vulnerable,
        }

    return summary


def print_final_summary(summary: dict):
    """Print final summary of all experiments."""
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║" + " FINAL SUMMARY ".center(68) + "║")
    print("╚" + "═" * 68 + "╝")

    confirmed = summary.get("vulnerabilities_confirmed", [])

    if confirmed:
        print("\n✓ VULNERABILITIES CONFIRMED:")
        for v in confirmed:
            print(f"  • {v}")
    else:
        print("\n✗ No vulnerabilities confirmed in this run")
        print("  (This may be due to LLM behavior or configuration)")

    # Experiment 1 details
    exp1 = summary.get("exp1_summary", {})
    if exp1:
        print("\n─── Experiment 1: Action Replay (V1) ───")
        print(f"  S1 (DoW) Duplicate Rate:     {exp1.get('s1_duplicate_rate', 0):.1%}")
        print(f"  S1 (DoW) Key Instability:    {exp1.get('s1_key_instability', 0):.1%}")
        print(f"  Baseline Duplicate Rate:     {exp1.get('baseline_duplicate_rate', 0):.1%}")
        print(f"  V1 Confirmed:                {'YES' if exp1.get('v1_confirmed') else 'NO'}")

    # Experiment 2 details
    exp2 = summary.get("exp2_summary", {})
    if exp2:
        print("\n─── Experiment 2: Authority Resurrection (V2) ───")
        print(f"  Stateless Mode Vulnerable:   {'YES' if exp2.get('stateless_vulnerable') else 'NO'}")
        print(f"  Stateful Sync Secure:        {'YES' if exp2.get('stateful_secure') else 'NO'}")
        print(f"  V2 Confirmed:                {'YES' if exp2.get('v2_confirmed') else 'NO'}")

    print("\n" + "─" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Run Semantic Rollback Vulnerability Experiments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all experiments with 5 trials each
  python -m experiments.run_experiments

  # Run only Experiment 1 (Action Replay)
  python -m experiments.run_experiments --exp 1

  # Run with more trials for statistical significance
  python -m experiments.run_experiments --trials 20

  # Quiet mode (less output)
  python -m experiments.run_experiments -q
        """
    )

    parser.add_argument('--exp', '-e', type=int, choices=[1, 2], default=None,
                        help='Run specific experiment (1 or 2). Default: run both')
    parser.add_argument('--trials', '-n', type=int, default=5,
                        help='Number of trials per scenario (default: 5)')
    parser.add_argument('--verbose', '-v', action='store_true', default=True,
                        help='Verbose output (default: True)')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='Minimal output')
    parser.add_argument('--output', '-o', type=Path, default=None,
                        help='Output file for summary JSON')

    args = parser.parse_args()

    verbose = args.verbose and not args.quiet

    print_banner()

    # Check and setup local LLM environment
    print("Checking local LLM server...")
    if not ensure_local_llm_ready(DEFAULT_CONFIG.llm):
        sys.exit(1)

    if verbose:
        verify_env_setup()

    print(f"\nConfiguration:")
    print(f"  Model: {DEFAULT_CONFIG.llm.model}")
    print(f"  LLM URL: {DEFAULT_CONFIG.llm.base_url}")
    print(f"  Trials per scenario: {args.trials}")
    print(f"  Results directory: {RESULTS_DIR}")

    exp1_metrics = None
    exp2_metrics = None

    try:
        if args.exp is None or args.exp == 1:
            exp1_metrics = run_experiment_1(args.trials, verbose)

        if args.exp is None or args.exp == 2:
            exp2_metrics = run_experiment_2(args.trials, verbose)

    except KeyboardInterrupt:
        print("\n\nExperiment interrupted by user.")
        sys.exit(1)

    except Exception as e:
        print(f"\nError during experiment: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Generate and print summary
    summary = summarize_results(exp1_metrics or {}, exp2_metrics or {})
    print_final_summary(summary)

    # Save summary if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"\nSummary saved to: {args.output}")

    # Also save to default location
    summary_file = RESULTS_DIR / f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"Summary saved to: {summary_file}")


if __name__ == "__main__":
    main()
