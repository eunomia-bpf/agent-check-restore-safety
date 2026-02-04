"""
Base Service Class for Simulated External Services.

External services maintain state that is NOT checkpointed by the agent,
creating the state divergence that enables semantic rollback attacks.
"""
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path

from ..config import RESULTS_DIR


@dataclass
class ServiceRequest:
    """Record of a request to an external service."""
    request_id: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    request_type: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    result: str = ""  # "success", "duplicate", "rejected", "error"
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseService(ABC):
    """
    Base class for simulated external services.

    Key concept: These services maintain state that persists across
    agent checkpoint-restore cycles, enabling state divergence detection.
    """

    def __init__(self, service_name: str, log_dir: Optional[Path] = None):
        self.service_name = service_name
        self.log_dir = log_dir or RESULTS_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self._requests: List[ServiceRequest] = []
        self._state: Dict[str, Any] = {}
        self._request_counter = 0

    @property
    def request_count(self) -> int:
        """Total number of requests received."""
        return len(self._requests)

    def reset(self) -> None:
        """
        Reset service state.

        Note: In real scenarios, external services CANNOT be reset.
        This is only for clean experiment runs.
        """
        self._requests.clear()
        self._state.clear()
        self._request_counter = 0
        self._on_reset()

    def _on_reset(self) -> None:
        """Hook for subclasses to reset additional state."""
        pass

    def _generate_request_id(self) -> str:
        """Generate a unique request ID."""
        self._request_counter += 1
        return f"{self.service_name}_{self._request_counter:06d}"

    def _log_request(self, request: ServiceRequest) -> None:
        """Log a request to memory and optionally to file."""
        self._requests.append(request)

    @abstractmethod
    def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute a service request.

        Returns:
            Dict with at least "status" key
        """
        pass

    def get_state_snapshot(self) -> Dict[str, Any]:
        """
        Get a snapshot of current service state.

        Useful for detecting state divergence.
        """
        return {
            "service_name": self.service_name,
            "timestamp": datetime.now().isoformat(),
            "request_count": self.request_count,
            "state": self._state.copy(),
        }

    def get_requests(
        self,
        request_type: Optional[str] = None,
        result: Optional[str] = None,
    ) -> List[ServiceRequest]:
        """
        Get requests matching criteria.

        Args:
            request_type: Filter by request type
            result: Filter by result status

        Returns:
            List of matching ServiceRequest objects
        """
        requests = self._requests

        if request_type:
            requests = [r for r in requests if r.request_type == request_type]

        if result:
            requests = [r for r in requests if r.result == result]

        return requests

    def save_log(self, filename: Optional[str] = None) -> Path:
        """Save request log to file."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.service_name}_log_{timestamp}.json"

        output_file = self.log_dir / filename

        data = {
            "service_name": self.service_name,
            "saved_at": datetime.now().isoformat(),
            "total_requests": self.request_count,
            "requests": [asdict(r) for r in self._requests],
            "final_state": self._state,
        }

        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)

        return output_file

    def export_for_analysis(self) -> Dict[str, Any]:
        """Export data for analysis."""
        return {
            "service_name": self.service_name,
            "total_requests": self.request_count,
            "requests": [asdict(r) for r in self._requests],
            "state": self._state.copy(),
            "metrics": self._compute_metrics(),
        }

    def _compute_metrics(self) -> Dict[str, Any]:
        """Compute service-specific metrics. Override in subclasses."""
        return {
            "total_requests": self.request_count,
            "success_count": len([r for r in self._requests if r.result == "success"]),
            "duplicate_count": len([r for r in self._requests if r.result == "duplicate"]),
            "rejected_count": len([r for r in self._requests if r.result == "rejected"]),
        }
