"""
Session/Checkpoint Manager for Semantic Rollback Experiments.

This module manages the mapping between:
- Checkpoint-Restore concepts
- Claude Code's session mechanisms (--session-id, --resume)

Key breakthrough: True checkpoint-restore via session file truncation.
Claude Code stores sessions in ~/.claude/projects/<project>/<session-id>.jsonl
By truncating the file, we can roll back agent state to any point.
"""
import uuid
import json
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime
from pathlib import Path

from ..config import RESULTS_DIR, PROJECT_ROOT


# Claude Code session storage location
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
# Project path encoded (replace / with -)
# Note: Claude Code uses leading dash (e.g., "-home-user-project" not "home-user-project")
PROJECT_PATH_ENCODED = str(PROJECT_ROOT).replace("/", "-")
PROJECT_SESSION_DIR = CLAUDE_PROJECTS_DIR / PROJECT_PATH_ENCODED


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

    # ========================================================================
    # TRUE CHECKPOINT-RESTORE via Session File Truncation
    # ========================================================================

    def get_session_file(self, session_id: str) -> Path:
        """Get path to Claude Code session file."""
        return PROJECT_SESSION_DIR / f"{session_id}.jsonl"

    def read_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """Read all messages from session file."""
        session_file = self.get_session_file(session_id)
        if not session_file.exists():
            return []

        messages = []
        with open(session_file) as f:
            for line in f:
                if line.strip():
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return messages

    def find_checkpoint_line(
        self,
        session_id: str,
        after_tool: str = "get_server_stats",
    ) -> int:
        """
        Find the line number to truncate at (checkpoint point).

        Looks for the assistant message AFTER the specified tool's result.
        This is the point where Agent has completed Step 1 but not Step 2.

        Args:
            session_id: The session to analyze
            after_tool: The tool name that marks checkpoint (e.g., get_server_stats)

        Returns:
            Line number to truncate at, or -1 if not found
        """
        messages = self.read_session_messages(session_id)

        for i, msg in enumerate(messages):
            # Look for tool_result containing reference to the tool
            if msg.get("type") == "user":
                content = msg.get("message", {}).get("content", [])
                if isinstance(content, list):
                    for item in content:
                        if item.get("type") == "tool_result":
                            # Check the content for tool indication
                            text = ""
                            if item.get("content"):
                                if isinstance(item["content"], list) and item["content"]:
                                    text = item["content"][0].get("text", "")
                                elif isinstance(item["content"], str):
                                    text = item["content"]

                            # Identify checkpoint tool result
                            if self._is_checkpoint_tool_result(text, after_tool):
                                # Return index after the next assistant response
                                for j in range(i + 1, len(messages)):
                                    if messages[j].get("type") == "assistant":
                                        return j + 1
        return -1

    def _is_checkpoint_tool_result(self, text: str, tool_name: str) -> bool:
        """Check if the tool result text matches the checkpoint tool."""
        # Match common patterns in MCP tool results
        patterns = [
            "payment_service",  # get_server_stats result
            "token_service",    # issue_token related
            f'"{tool_name}"',
            tool_name,
        ]
        return any(p.lower() in text.lower() for p in patterns)

    def find_checkpoint_after_tool(
        self,
        session_id: str,
        tool_name: str,
    ) -> int:
        """
        Find checkpoint line after a specific tool call completes.

        This searches for the tool call in assistant message and finds
        the point after its result is processed.
        """
        messages = self.read_session_messages(session_id)

        for i, msg in enumerate(messages):
            if msg.get("type") == "assistant":
                content = msg.get("message", {}).get("content", [])
                if isinstance(content, list):
                    for item in content:
                        if item.get("type") == "tool_use":
                            if item.get("name", "").endswith(tool_name):
                                # Found the tool call, find the result
                                for j in range(i + 1, len(messages)):
                                    # Find the tool_result, then the next assistant
                                    if messages[j].get("type") == "user":
                                        user_content = messages[j].get("message", {}).get("content", [])
                                        if isinstance(user_content, list):
                                            for uc in user_content:
                                                if uc.get("type") == "tool_result":
                                                    # Now find the assistant response after this
                                                    for k in range(j + 1, len(messages)):
                                                        if messages[k].get("type") == "assistant":
                                                            return k + 1
        return -1

    def truncate_session(
        self,
        session_id: str,
        checkpoint_line: int,
        new_session_id: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Create a truncated session file at checkpoint point.

        THIS IS THE KEY TO TRUE CHECKPOINT-RESTORE:
        - Original session: [msg1, msg2, ..., checkpoint, msg_after_checkpoint, ...]
        - Truncated session: [msg1, msg2, ..., checkpoint]
        - Agent resumes with NO knowledge of what happened after checkpoint

        Args:
            session_id: Original session ID
            checkpoint_line: Line number to truncate at (1-indexed, keep lines 0 to checkpoint_line-1)
            new_session_id: New session ID (defaults to new UUID)

        Returns:
            (success, new_session_id or error message)
        """
        messages = self.read_session_messages(session_id)

        if checkpoint_line <= 0 or checkpoint_line > len(messages):
            return False, f"Invalid checkpoint line: {checkpoint_line} (total: {len(messages)})"

        new_session_id = new_session_id or str(uuid.uuid4())
        new_session_file = self.get_session_file(new_session_id)

        # Ensure directory exists
        new_session_file.parent.mkdir(parents=True, exist_ok=True)

        with open(new_session_file, 'w') as f:
            for i, msg in enumerate(messages[:checkpoint_line]):
                # Update session ID in each message
                if "sessionId" in msg:
                    msg["sessionId"] = new_session_id
                f.write(json.dumps(msg) + "\n")

        return True, new_session_id

    def create_truncated_checkpoint(
        self,
        session_id: str,
        after_tool: str = "get_server_stats",
        description: str = "",
    ) -> Tuple[Optional[Checkpoint], str]:
        """
        Create a TRUE checkpoint by truncating the session file.

        This is the complete workflow:
        1. Find the checkpoint line (after specified tool completes)
        2. Create a new session file truncated at that point
        3. Return checkpoint info for later resume

        Args:
            session_id: The session to checkpoint
            after_tool: Tool name that marks the checkpoint point
            description: Human-readable description

        Returns:
            (Checkpoint, new_session_id) or (None, error_message)
        """
        # Find checkpoint line
        checkpoint_line = self.find_checkpoint_after_tool(session_id, after_tool)
        if checkpoint_line <= 0:
            # Try alternative method
            checkpoint_line = self.find_checkpoint_line(session_id, after_tool)

        if checkpoint_line <= 0:
            return None, f"Could not find checkpoint point after tool: {after_tool}"

        # Create truncated session
        success, result = self.truncate_session(session_id, checkpoint_line)
        if not success:
            return None, result

        new_session_id = result

        # Create checkpoint record
        checkpoint = self.create_checkpoint(
            session_id=new_session_id,  # New truncated session
            description=f"Truncated from {session_id} at line {checkpoint_line}. {description}",
            metadata={
                "original_session_id": session_id,
                "checkpoint_line": checkpoint_line,
                "truncation_method": "session_file",
                "after_tool": after_tool,
            }
        )

        return checkpoint, new_session_id


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
