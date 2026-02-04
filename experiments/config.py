"""
Configuration for Semantic Rollback Experiments.

This module handles:
- Local LLM configuration (llama-server)
- Environment variable setup for Claude Code CLI
- Health checks for the local LLM server
"""
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import os
import sys
import urllib.request
import urllib.error
import json


# Base paths
EXPERIMENTS_DIR = Path(__file__).parent
PROJECT_ROOT = EXPERIMENTS_DIR.parent
RESULTS_DIR = EXPERIMENTS_DIR / "results"
MCP_LOG_FILE = RESULTS_DIR / "mcp_requests.jsonl"


@dataclass
class LLMConfig:
    """Configuration for local LLM (llama-server)."""
    base_url: str = "http://localhost:8080"
    auth_token: str = "llama"
    api_key: str = ""  # Must be empty for local LLM
    model: str = "qwen3"
    timeout: int = 120  # seconds


def check_local_llm_running(base_url: str = "http://localhost:8080") -> Tuple[bool, str]:
    """
    Check if the local LLM server (llama-server) is running and ready.

    Returns:
        (is_running, message)
    """
    health_url = f"{base_url}/health"
    try:
        req = urllib.request.Request(health_url, method='GET')
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                # Check response content for "ok" status
                content = response.read().decode('utf-8')
                try:
                    data = json.loads(content)
                    if data.get("status") == "ok":
                        return True, "Local LLM server is running and ready"
                    else:
                        return False, f"Server not ready: {content}"
                except json.JSONDecodeError:
                    # If it's 200 but not JSON, assume it's ok
                    return True, "Local LLM server is running"
    except urllib.error.HTTPError as e:
        if e.code == 503:
            # Server is up but model is loading
            try:
                content = e.read().decode('utf-8')
                data = json.loads(content)
                msg = data.get("error", {}).get("message", "Service unavailable")
                return False, f"Server is starting: {msg}"
            except Exception:
                return False, "Server is starting, model loading..."
        return False, f"HTTP error {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return False, f"Cannot connect to {base_url}: {e.reason}"
    except Exception as e:
        return False, f"Error checking LLM server: {e}"

    return False, "Unknown error"


def setup_local_llm_env(config: Optional[LLMConfig] = None) -> None:
    """
    Setup environment variables for Claude Code to use local LLM.

    This sets the environment variables in the current process,
    which will be inherited by subprocess calls to Claude Code CLI.
    """
    if config is None:
        config = LLMConfig()

    # Set environment variables for local LLM
    os.environ['ANTHROPIC_BASE_URL'] = config.base_url
    os.environ['ANTHROPIC_AUTH_TOKEN'] = config.auth_token
    os.environ['ANTHROPIC_API_KEY'] = config.api_key  # Must be empty!

    # Disable any proxy that might interfere
    os.environ['NO_PROXY'] = 'localhost,127.0.0.1'


def ensure_local_llm_ready(config: Optional[LLMConfig] = None) -> bool:
    """
    Ensure local LLM is ready for use.

    1. Setup environment variables
    2. Check if server is running
    3. Print helpful error message if not

    Returns:
        True if ready, False otherwise
    """
    if config is None:
        config = LLMConfig()

    # Setup environment variables
    setup_local_llm_env(config)

    # Check if server is running
    is_running, message = check_local_llm_running(config.base_url)

    if not is_running:
        print("\n" + "=" * 70)
        print("ERROR: Local LLM server is not running!")
        print("=" * 70)
        print(f"\n{message}")
        print("\nPlease start llama-server first:")
        print()
        print("  cd /home/yunwei37/workspace/gpu/llama.cpp")
        print("  build/bin/llama-server \\")
        print("      -hf unsloth/Qwen3-Next-80B-A3B-Instruct-GGUF:Q4_K_M \\")
        print("      -c 65536 --port 8080 --jinja")
        print()
        print("=" * 70)
        return False

    print(f"[OK] {message}")
    print(f"[OK] Environment configured for local LLM at {config.base_url}")
    return True


def verify_env_setup() -> None:
    """Print current environment setup for debugging."""
    print("\nEnvironment Variables:")
    print(f"  ANTHROPIC_BASE_URL:   {os.environ.get('ANTHROPIC_BASE_URL', '(not set)')}")
    print(f"  ANTHROPIC_AUTH_TOKEN: {os.environ.get('ANTHROPIC_AUTH_TOKEN', '(not set)')}")
    print(f"  ANTHROPIC_API_KEY:    {'(empty)' if os.environ.get('ANTHROPIC_API_KEY') == '' else os.environ.get('ANTHROPIC_API_KEY', '(not set)')}")


@dataclass
class ExperimentConfig:
    """Configuration for experiments."""
    # Number of trials per scenario
    n_trials: int = 5

    # LLM configuration
    llm: LLMConfig = field(default_factory=LLMConfig)

    # MCP tools to allow (empty list = allow all MCP tools)
    # Tool names follow pattern: mcp__<server-name>__<tool-name>
    allowed_tools: List[str] = field(default_factory=list)

    # Output settings
    results_dir: Path = RESULTS_DIR
    verbose: bool = True
    save_results: bool = True

    # Experiment-specific settings
    payment_amount_cents: int = 4999  # $49.99
    token_expiry_seconds: int = 3600

    # Async validation delays (seconds)
    async_propagation_delays: List[int] = field(default_factory=lambda: [5, 30])


# Default configuration
DEFAULT_CONFIG = ExperimentConfig()


def get_claude_env(config: Optional[LLMConfig] = None) -> dict:
    """Get environment variables for Claude Code CLI."""
    if config is None:
        config = DEFAULT_CONFIG.llm

    env = os.environ.copy()
    env['ANTHROPIC_BASE_URL'] = config.base_url
    env['ANTHROPIC_AUTH_TOKEN'] = config.auth_token
    env['ANTHROPIC_API_KEY'] = config.api_key
    return env


# Success thresholds for vulnerability confirmation
THRESHOLDS = {
    # V1 Action Replay
    "key_instability_rate": 0.50,  # > 50% means keys are unstable
    "duplicate_rate": 0.50,        # > 50% means duplicates occur
    "baseline_duplicate_rate": 0.05,  # < 5% means baseline is clean

    # V2 Authority Resurrection
    "stateless_unauthorized_rate": 0.80,  # > 80% for stateless vulnerability
    "stateful_unauthorized_rate": 0.0,    # Should be ~0% for proper protection
}
