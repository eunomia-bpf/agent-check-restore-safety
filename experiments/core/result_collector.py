"""
Result Collection and Analysis for Semantic Rollback Experiments.

This module provides utilities for:
- Collecting experiment trial results
- Computing metrics (rates, gains)
- Generating reports
- Saving results to files
"""
import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from collections import defaultdict

from ..config import RESULTS_DIR, THRESHOLDS


@dataclass
class TrialResult:
    """Result of a single experiment trial."""
    trial_id: int
    scenario: str  # e.g., "S1_TM1_DoW", "S2_TM2_Fraud", "S3_Token"
    threat_model: str  # "TM1", "TM2", "None"

    # Session info
    session_id: Optional[str] = None
    checkpoint_id: Optional[str] = None

    # Timing
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    duration_ms: int = 0

    # V1 specific fields
    key_before: Optional[str] = None
    key_after: Optional[str] = None
    key_changed: bool = False
    duplicate_action: bool = False

    # V2 specific fields
    token: Optional[str] = None
    token_consumed: bool = False
    token_accepted_after_consume: bool = False
    validation_mode: Optional[str] = None

    # Common fields
    attacker_gain_usd: float = 0.0
    notes: str = ""
    raw_output: str = ""

    # For S2 (TM2) - service delivery tracking
    service_delivered: bool = False
    payment_completed: bool = False
    free_service: bool = False


@dataclass
class ScenarioMetrics:
    """Aggregated metrics for a scenario."""
    scenario: str
    threat_model: str
    total_trials: int = 0

    # V1 metrics
    key_instability_rate: float = 0.0
    duplicate_rate: float = 0.0

    # V2 metrics
    unauthorized_rate: float = 0.0

    # Common metrics
    total_attacker_gain: float = 0.0
    avg_attacker_gain: float = 0.0

    # Vulnerability confirmed?
    vulnerability_confirmed: bool = False
    confirmation_reason: str = ""


class ResultCollector:
    """
    Collects and analyzes experiment results.
    """

    def __init__(self, experiment_name: str, results_dir: Optional[Path] = None):
        self.experiment_name = experiment_name
        self.results_dir = results_dir or RESULTS_DIR
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self.trials: List[TrialResult] = []
        self.start_time = datetime.now()
        self.metadata: Dict[str, Any] = {}

    def add_trial(self, result: TrialResult) -> None:
        """Add a trial result."""
        self.trials.append(result)

    def add_metadata(self, key: str, value: Any) -> None:
        """Add metadata about the experiment."""
        self.metadata[key] = value

    def compute_metrics(self) -> Dict[str, ScenarioMetrics]:
        """
        Compute metrics grouped by scenario.

        Returns:
            Dict mapping scenario name to ScenarioMetrics
        """
        # Group trials by scenario
        by_scenario: Dict[str, List[TrialResult]] = defaultdict(list)
        for trial in self.trials:
            by_scenario[trial.scenario].append(trial)

        metrics = {}

        for scenario, trials in by_scenario.items():
            if not trials:
                continue

            m = ScenarioMetrics(
                scenario=scenario,
                threat_model=trials[0].threat_model,
                total_trials=len(trials),
            )

            # V1 metrics (key instability, duplicates)
            key_changes = sum(1 for t in trials if t.key_changed)
            duplicates = sum(1 for t in trials if t.duplicate_action)

            m.key_instability_rate = key_changes / len(trials) if trials else 0
            m.duplicate_rate = duplicates / len(trials) if trials else 0

            # V2 metrics (unauthorized actions)
            unauthorized = sum(1 for t in trials if t.token_accepted_after_consume)
            m.unauthorized_rate = unauthorized / len(trials) if trials else 0

            # Attacker gain
            m.total_attacker_gain = sum(t.attacker_gain_usd for t in trials)
            m.avg_attacker_gain = m.total_attacker_gain / len(trials) if trials else 0

            # Check vulnerability confirmation
            m.vulnerability_confirmed, m.confirmation_reason = \
                self._check_vulnerability(scenario, m)

            metrics[scenario] = m

        return metrics

    def _check_vulnerability(
        self,
        scenario: str,
        metrics: ScenarioMetrics
    ) -> tuple:
        """
        Check if vulnerability is confirmed based on thresholds.

        Returns:
            (is_confirmed, reason)
        """
        # V1 scenarios
        if scenario in ("S1_TM1_DoW", "S2_TM2_Fraud"):
            if (metrics.key_instability_rate > THRESHOLDS["key_instability_rate"] and
                metrics.duplicate_rate > THRESHOLDS["duplicate_rate"]):
                return True, (
                    f"Key instability ({metrics.key_instability_rate:.1%}) and "
                    f"duplicate rate ({metrics.duplicate_rate:.1%}) exceed thresholds"
                )
            return False, "Rates below threshold"

        # V1 baseline
        if scenario == "No_CR_Baseline":
            if metrics.duplicate_rate < THRESHOLDS["baseline_duplicate_rate"]:
                return True, f"Baseline clean ({metrics.duplicate_rate:.1%} < 5%)"
            return False, f"Baseline shows duplicates ({metrics.duplicate_rate:.1%})"

        # V2 scenarios
        if "stateless" in scenario.lower():
            if metrics.unauthorized_rate > THRESHOLDS["stateless_unauthorized_rate"]:
                return True, f"Stateless vulnerable ({metrics.unauthorized_rate:.1%})"
            return False, "Stateless shows protection"

        if "stateful_sync" in scenario.lower():
            if metrics.unauthorized_rate <= THRESHOLDS["stateful_unauthorized_rate"]:
                return True, f"Stateful sync secure ({metrics.unauthorized_rate:.1%})"
            return False, "Stateful sync shows vulnerability"

        if "stateful_async" in scenario.lower():
            if metrics.unauthorized_rate > 0:
                return True, f"Async has attack window ({metrics.unauthorized_rate:.1%})"
            return False, "Async appears secure"

        return False, "Unknown scenario"

    def generate_report(self) -> str:
        """Generate a human-readable report."""
        metrics = self.compute_metrics()

        lines = [
            "=" * 70,
            f"EXPERIMENT: {self.experiment_name}",
            "=" * 70,
            f"Started: {self.start_time.isoformat()}",
            f"Total trials: {len(self.trials)}",
            "",
        ]

        # Per-scenario results
        for scenario, m in sorted(metrics.items()):
            lines.append(f"\n{'-' * 50}")
            lines.append(f"Scenario: {scenario} ({m.threat_model})")
            lines.append(f"{'-' * 50}")
            lines.append(f"  Trials: {m.total_trials}")

            # V1 metrics
            if m.key_instability_rate > 0 or m.duplicate_rate > 0:
                lines.append(f"  Key Instability Rate: {m.key_instability_rate:.1%}")
                lines.append(f"  Duplicate Rate: {m.duplicate_rate:.1%}")

            # V2 metrics
            if m.unauthorized_rate > 0 or "stateless" in scenario.lower() or "stateful" in scenario.lower():
                lines.append(f"  Unauthorized Rate: {m.unauthorized_rate:.1%}")

            # Attacker gain
            if m.total_attacker_gain > 0:
                lines.append(f"  Total Attacker Gain: ${m.total_attacker_gain:.2f}")
                lines.append(f"  Avg Attacker Gain: ${m.avg_attacker_gain:.2f}")

            # Confirmation
            status = "CONFIRMED" if m.vulnerability_confirmed else "NOT CONFIRMED"
            symbol = "✓" if m.vulnerability_confirmed else "✗"
            lines.append(f"\n  {symbol} Vulnerability {status}")
            lines.append(f"    Reason: {m.confirmation_reason}")

        # Overall summary
        lines.append("\n" + "=" * 70)
        lines.append("SUMMARY")
        lines.append("=" * 70)

        confirmed = [s for s, m in metrics.items() if m.vulnerability_confirmed]
        total_gain = sum(m.total_attacker_gain for m in metrics.values())

        if confirmed:
            lines.append(f"\nVulnerabilities confirmed in: {', '.join(confirmed)}")
        lines.append(f"Total attacker gain: ${total_gain:.2f}")

        return "\n".join(lines)

    def save_results(self, filename: Optional[str] = None) -> Path:
        """Save results to JSON file."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.experiment_name}_{timestamp}.json"

        output_file = self.results_dir / filename

        data = {
            "experiment_name": self.experiment_name,
            "start_time": self.start_time.isoformat(),
            "end_time": datetime.now().isoformat(),
            "metadata": self.metadata,
            "trials": [asdict(t) for t in self.trials],
            "metrics": {
                k: asdict(v) for k, v in self.compute_metrics().items()
            },
        }

        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)

        return output_file

    def print_report(self) -> None:
        """Print the report to stdout."""
        print(self.generate_report())


def read_mcp_log(log_file: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Read and parse the MCP request log.

    Returns:
        List of log entries
    """
    from ..config import MCP_LOG_FILE

    log_file = log_file or MCP_LOG_FILE

    if not log_file.exists():
        return []

    entries = []
    with open(log_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    return entries


def verify_tool_called(tool_name: str, log_file: Optional[Path] = None) -> bool:
    """
    Verify that a specific tool was called.

    Args:
        tool_name: Name of the tool (e.g., "create_payment")
        log_file: Optional path to log file

    Returns:
        True if tool was called
    """
    logs = read_mcp_log(log_file)
    return any(log.get("tool") == tool_name for log in logs)


def count_tool_calls(tool_name: str, log_file: Optional[Path] = None) -> int:
    """Count how many times a tool was called."""
    logs = read_mcp_log(log_file)
    return sum(1 for log in logs if log.get("tool") == tool_name)


def get_tool_calls_with_key(
    tool_name: str,
    key_field: str,
    log_file: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """
    Get all calls to a tool, extracting a specific field.

    Useful for analyzing idempotency key patterns.
    """
    logs = read_mcp_log(log_file)
    return [
        {
            "timestamp": log.get("timestamp"),
            key_field: log.get(key_field),
            "result": log.get("result"),
        }
        for log in logs
        if log.get("tool") == tool_name
    ]
