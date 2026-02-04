"""
Claude Code CLI Wrapper for Semantic Rollback Experiments.

This module provides a clean interface to run Claude Code with:
- Session management (--session-id, --resume)
- Local LLM configuration
- MCP tool access
"""
import subprocess
import json
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path

from ..config import get_claude_env, LLMConfig, DEFAULT_CONFIG


@dataclass
class AgentResponse:
    """Response from a Claude Code invocation."""
    stdout: str = ""
    stderr: str = ""
    return_code: int = 0
    session_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    duration_ms: int = 0
    error: Optional[str] = None

    @property
    def output(self) -> str:
        """Combined stdout and stderr."""
        return self.stdout + self.stderr

    @property
    def success(self) -> bool:
        """Whether the command succeeded."""
        return self.return_code == 0 and self.error is None

    def extract_tool_calls(self) -> List[Dict[str, Any]]:
        """Extract tool call information from output (if available)."""
        # This is a simplified extraction - actual format may vary
        tool_calls = []
        # Look for JSON tool call patterns in output
        json_pattern = r'\{[^{}]*"tool"[^{}]*\}'
        matches = re.findall(json_pattern, self.output)
        for match in matches:
            try:
                tool_calls.append(json.loads(match))
            except json.JSONDecodeError:
                pass
        return tool_calls


class ClaudeAgentRunner:
    """
    Wrapper for Claude Code CLI with session management.

    Key features:
    - Create new sessions with --session-id
    - Resume sessions with --resume (simulates checkpoint-restore)
    - Configure local LLM endpoint
    - Specify allowed MCP tools
    """

    def __init__(
        self,
        llm_config: Optional[LLMConfig] = None,
        allowed_tools: Optional[List[str]] = None,
        verbose: bool = False,
    ):
        self.llm_config = llm_config or DEFAULT_CONFIG.llm
        self.allowed_tools = allowed_tools or DEFAULT_CONFIG.allowed_tools
        self.verbose = verbose
        self._env = get_claude_env(self.llm_config)

    def run_task(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        resume: bool = False,
        timeout: Optional[int] = None,
        extra_args: Optional[List[str]] = None,
        max_turns: Optional[int] = None,
    ) -> AgentResponse:
        """
        Run a task with Claude Code.

        Args:
            prompt: The task prompt to execute
            session_id: Session ID for persistence
            resume: If True, resume from session_id (simulates restore)
            timeout: Command timeout in seconds
            extra_args: Additional CLI arguments
            max_turns: Maximum number of agentic turns (tool calls)

        Returns:
            AgentResponse with output and metadata

        CR Mapping:
        - session_id alone = Create checkpoint
        - resume=True with session_id = Restore from checkpoint
        """
        cmd = self._build_command(prompt, session_id, resume, extra_args, max_turns)

        if self.verbose:
            print(f"  [CMD] {' '.join(cmd[:6])}...")

        start_time = datetime.now()
        timeout = timeout or self.llm_config.timeout

        # Run from project root to ensure .mcp.json is found
        from ..config import PROJECT_ROOT

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=self._env,
                timeout=timeout,
                cwd=str(PROJECT_ROOT),  # Run from project root for .mcp.json
            )

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            response = AgentResponse(
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                session_id=session_id,
                duration_ms=duration_ms,
            )

        except subprocess.TimeoutExpired:
            response = AgentResponse(
                error=f"Timeout after {timeout}s",
                session_id=session_id,
            )

        except Exception as e:
            response = AgentResponse(
                error=str(e),
                session_id=session_id,
            )

        if self.verbose:
            status = "OK" if response.success else "FAIL"
            print(f"  [{status}] {response.duration_ms}ms")

        return response

    def _build_command(
        self,
        prompt: str,
        session_id: Optional[str],
        resume: bool,
        extra_args: Optional[List[str]],
        max_turns: Optional[int] = None,
    ) -> List[str]:
        """Build the claude CLI command."""
        cmd = [
            'claude',
            '-p', prompt,
            '--model', self.llm_config.model,
            '--dangerously-skip-permissions',
        ]

        # Session management
        if resume and session_id:
            # RESTORE: Resume from checkpoint
            cmd.extend(['--resume', session_id])
        elif session_id:
            # CHECKPOINT: Create new session with ID
            cmd.extend(['--session-id', session_id])

        # Max turns (for controlling checkpoint timing)
        if max_turns is not None:
            cmd.extend(['--max-turns', str(max_turns)])

        # MCP tools (if empty, Claude Code will use all available MCP tools)
        if self.allowed_tools:
            cmd.extend(['--allowedTools', ','.join(self.allowed_tools)])
        # Note: If allowed_tools is empty, we don't pass --allowedTools
        # This allows Claude Code to use all configured MCP tools

        # Extra arguments
        if extra_args:
            cmd.extend(extra_args)

        return cmd

    def create_session(self, prompt: str, session_id: str) -> AgentResponse:
        """
        Create a new session (CHECKPOINT operation).

        This is equivalent to creating a checkpoint that can be restored later.
        """
        return self.run_task(prompt, session_id=session_id, resume=False)

    def resume_session(self, prompt: str, session_id: str) -> AgentResponse:
        """
        Resume an existing session (RESTORE operation).

        This simulates restoring from a checkpoint. The agent's conversation
        history is restored, but external service state is NOT restored,
        creating the state divergence that leads to vulnerabilities.
        """
        return self.run_task(prompt, session_id=session_id, resume=True)

    def fresh_session(self, prompt: str) -> AgentResponse:
        """Run without session persistence (for baseline comparisons)."""
        return self.run_task(prompt, session_id=None, resume=False)


def extract_idempotency_key(output: str) -> Optional[str]:
    """
    Extract idempotency key from agent output.

    Looks for patterns like:
    - idempotency_key: "xxx"
    - "idempotency_key": "xxx"
    - key_xxx, payment_xxx, etc.
    """
    patterns = [
        r'idempotency_key["\s:]+([a-zA-Z0-9_-]+)',
        r'"idempotency_key"\s*:\s*"([^"]+)"',
        r'(key_[a-zA-Z0-9_-]+)',
        r'(payment_[a-zA-Z0-9_-]+)',
        r'(order_[a-zA-Z0-9_-]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def extract_token(output: str) -> Optional[str]:
    """
    Extract authorization token from agent output.

    Looks for patterns like:
    - token: "xxx"
    - "token": "xxx"
    - token_xxx, auth_xxx, etc.
    """
    patterns = [
        r'token["\s:]+([a-zA-Z0-9_-]+)',
        r'"token"\s*:\s*"([^"]+)"',
        r'(token_[a-zA-Z0-9_-]+)',
        r'(auth_[a-zA-Z0-9_-]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            return match.group(1)

    return None
