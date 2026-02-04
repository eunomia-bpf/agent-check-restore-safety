"""
Session/Checkpoint Manager for Semantic Rollback Experiments.

This module manages the mapping between:
- Checkpoint-Restore concepts
- Claude Code's session mechanisms (--session-id, --resume)
"""
import uuid
import json
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Any
from datetime import datetime
from pathlib import Path

from ..config import RESULTS_DIR


@dataclass
class Checkpoint:
    """Represents a checkpoint (saved agent state)."""
    checkpoint_id: str
    session_id: str
    created_at: str
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    # State tracking
    agent_state: str = "active"  # active, restored, abandoned
    restore_count: int = 0
    last_restored_at: Optional[str] = None


@dataclass
class SessionState:
    """Tracks the state of an experiment session."""
    session_id: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Checkpoints created during this session
    checkpoints: List[Checkpoint] = field(default_factory=list)

    # External state references (for tracking divergence)
    external_state_refs: Dict[str, Any] = field(default_factory=dict)

    # Actions performed
    actions: List[Dict[str, Any]] = field(default_factory=list)


class SessionManager:
    """
    Manages experiment sessions and checkpoints.

    CR Mapping:
    ┌─────────────────────────────────────────────────────────────┐
    │ CR Concept      │ Claude Code Mechanism  │ Effect           │
    ├─────────────────┼────────────────────────┼──────────────────┤
    │ Checkpoint      │ --session-id <uuid>    │ Save dialog      │
    │ Restore         │ --resume <session-id>  │ Restore dialog   │
    │ Agent State     │ Conversation history   │ ROLLED BACK      │
    │ External State  │ MCP server state       │ NOT AFFECTED     │
    └─────────────────┴────────────────────────┴──────────────────┘
    """

    def __init__(self, results_dir: Optional[Path] = None):
        self.results_dir = results_dir or RESULTS_DIR
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self._sessions: Dict[str, SessionState] = {}
        self._checkpoints: Dict[str, Checkpoint] = {}

    def create_session(self, description: str = "") -> str:
        """
        Create a new session ID for tracking.

        Returns:
            New session_id (UUID)
        """
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = SessionState(
            session_id=session_id,
        )

        if description:
            self._sessions[session_id].external_state_refs["description"] = description

        return session_id

    def create_checkpoint(
        self,
        session_id: str,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Checkpoint:
        """
        Create a checkpoint for a session.

        In Claude Code terms, this means we'll use --session-id to create
        a point we can later --resume from.

        Args:
            session_id: The session to checkpoint
            description: Human-readable description
            metadata: Additional data to store

        Returns:
            Checkpoint object
        """
        checkpoint_id = f"cp_{uuid.uuid4().hex[:12]}"

        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            session_id=session_id,
            created_at=datetime.now().isoformat(),
            description=description,
            metadata=metadata or {},
        )

        self._checkpoints[checkpoint_id] = checkpoint

        if session_id in self._sessions:
            self._sessions[session_id].checkpoints.append(checkpoint)

        return checkpoint

    def restore_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        """
        Mark a checkpoint as restored.

        Note: Actual restore happens via --resume in ClaudeAgentRunner.
        This method tracks the restore for analysis.

        Args:
            checkpoint_id: The checkpoint to restore

        Returns:
            Updated Checkpoint object
        """
        if checkpoint_id not in self._checkpoints:
            raise ValueError(f"Unknown checkpoint: {checkpoint_id}")

        checkpoint = self._checkpoints[checkpoint_id]
        checkpoint.restore_count += 1
        checkpoint.last_restored_at = datetime.now().isoformat()
        checkpoint.agent_state = "restored"

        return checkpoint

    def record_action(
        self,
        session_id: str,
        action_type: str,
        details: Dict[str, Any],
    ) -> None:
        """
        Record an action performed during a session.

        Used for tracking state divergence between agent and external services.
        """
        if session_id not in self._sessions:
            return

        self._sessions[session_id].actions.append({
            "timestamp": datetime.now().isoformat(),
            "type": action_type,
            **details,
        })

    def record_external_state(
        self,
        session_id: str,
        key: str,
        value: Any,
    ) -> None:
        """
        Record external state reference for divergence tracking.

        This helps us verify that external state is NOT rolled back
        when agent state IS rolled back.
        """
        if session_id not in self._sessions:
            return

        self._sessions[session_id].external_state_refs[key] = {
            "value": value,
            "recorded_at": datetime.now().isoformat(),
        }

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """Get session state by ID."""
        return self._sessions.get(session_id)

    def get_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Get checkpoint by ID."""
        return self._checkpoints.get(checkpoint_id)

    def save_state(self, filename: str = "session_state.json") -> Path:
        """Save all session and checkpoint state to file."""
        output_file = self.results_dir / filename

        state = {
            "saved_at": datetime.now().isoformat(),
            "sessions": {
                sid: asdict(session) for sid, session in self._sessions.items()
            },
            "checkpoints": {
                cid: asdict(cp) for cid, cp in self._checkpoints.items()
            },
        }

        with open(output_file, 'w') as f:
            json.dump(state, f, indent=2)

        return output_file

    def load_state(self, filename: str = "session_state.json") -> None:
        """Load session and checkpoint state from file."""
        input_file = self.results_dir / filename

        if not input_file.exists():
            return

        with open(input_file, 'r') as f:
            state = json.load(f)

        # Reconstruct sessions
        for sid, session_data in state.get("sessions", {}).items():
            # Handle nested checkpoints
            checkpoints = []
            for cp_data in session_data.pop("checkpoints", []):
                cp = Checkpoint(**cp_data)
                checkpoints.append(cp)

            session = SessionState(**session_data)
            session.checkpoints = checkpoints
            self._sessions[sid] = session

        # Reconstruct checkpoints
        for cid, cp_data in state.get("checkpoints", {}).items():
            self._checkpoints[cid] = Checkpoint(**cp_data)

    def clear(self) -> None:
        """Clear all session state (for fresh experiment runs)."""
        self._sessions.clear()
        self._checkpoints.clear()


# Convenience functions for experiment scripts
def create_experiment_session(description: str = "") -> tuple:
    """
    Create a new experiment session with manager.

    Returns:
        (SessionManager, session_id)
    """
    manager = SessionManager()
    session_id = manager.create_session(description)
    return manager, session_id
