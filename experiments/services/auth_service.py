"""
Authentication Service Simulation for V2 Authority Resurrection Testing.

This service demonstrates the vulnerability where:
1. Agent receives single-use token T
2. Agent uses token T → service marks T as "consumed"
3. Checkpoint-Restore causes agent state to roll back
4. Agent still has T in conversation history, uses it again
5. Result depends on validation mode:
   - stateless: Token accepted (VULNERABLE!)
   - stateful_sync: Token rejected (secure)
   - stateful_async: Race condition (partially vulnerable)

Unlike V1 (key instability), V2 uses the SAME token - the issue is that
the agent's knowledge of "token consumed" is lost on restore.
"""
import time
import hmac
import hashlib
import base64
import json
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Set, List
from datetime import datetime, timedelta
from enum import Enum
import uuid
import threading

from .base_service import BaseService, ServiceRequest


class ValidationMode(Enum):
    """Token validation modes with different security properties."""
    STATELESS = "stateless"        # Only verify signature (vulnerable)
    STATEFUL_SYNC = "stateful_sync"  # Realtime consumed check (secure)
    STATEFUL_ASYNC = "stateful_async"  # Delayed propagation (partial vulnerability)


@dataclass
class Token:
    """Authorization token."""
    token_id: str
    token_value: str  # The actual token string
    operation: str    # Allowed operation
    single_use: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    expires_at: Optional[str] = None

    # Consumption tracking
    consumed: bool = False
    consumed_at: Optional[str] = None
    consumed_by_request: Optional[str] = None


class AuthService(BaseService):
    """
    Simulated authentication/authorization service with multiple validation modes.

    Validation modes:
    - STATELESS: Only verifies token signature, doesn't check consumption
      → VULNERABLE to token resurrection
    - STATEFUL_SYNC: Realtime check of consumption status
      → SECURE against token resurrection
    - STATEFUL_ASYNC: Check consumption with propagation delay
      → PARTIALLY VULNERABLE (attack window during delay)
    """

    # Secret for token signing (in real systems, this would be secure)
    SECRET_KEY = b"experiment_secret_key_for_testing"

    def __init__(self, validation_mode: ValidationMode = ValidationMode.STATELESS):
        super().__init__("auth_service")

        self._validation_mode = validation_mode
        self._tokens: Dict[str, Token] = {}
        self._consumed_tokens: Set[str] = set()

        # For async mode: simulated propagation delay
        self._async_delay_seconds = 5
        self._pending_consumptions: Dict[str, float] = {}  # token_id -> timestamp

        # Track operations performed
        self._operations_performed: List[Dict[str, Any]] = []

    def _on_reset(self) -> None:
        """Reset auth-specific state."""
        self._tokens.clear()
        self._consumed_tokens.clear()
        self._pending_consumptions.clear()
        self._operations_performed.clear()

    @property
    def validation_mode(self) -> ValidationMode:
        return self._validation_mode

    def set_validation_mode(self, mode: ValidationMode) -> None:
        """Change validation mode."""
        if isinstance(mode, str):
            mode = ValidationMode(mode)
        self._validation_mode = mode

    def set_async_delay(self, seconds: int) -> None:
        """Set propagation delay for async mode."""
        self._async_delay_seconds = seconds

    def issue_token(
        self,
        operation: str,
        single_use: bool = True,
        expires_in_seconds: int = 3600,
    ) -> str:
        """
        Issue a new authorization token.

        Args:
            operation: The operation this token authorizes
            single_use: If True, token can only be used once
            expires_in_seconds: Token validity period

        Returns:
            Token string
        """
        token_id = f"tok_{uuid.uuid4().hex[:16]}"

        # Create signed token value
        payload = {
            "id": token_id,
            "op": operation,
            "single": single_use,
            "exp": (datetime.now() + timedelta(seconds=expires_in_seconds)).isoformat(),
        }
        payload_json = json.dumps(payload, sort_keys=True)
        signature = hmac.new(
            self.SECRET_KEY,
            payload_json.encode(),
            hashlib.sha256
        ).digest()

        token_value = base64.urlsafe_b64encode(
            payload_json.encode() + b"." + signature
        ).decode()

        token = Token(
            token_id=token_id,
            token_value=token_value,
            operation=operation,
            single_use=single_use,
            expires_at=(datetime.now() + timedelta(seconds=expires_in_seconds)).isoformat(),
        )

        self._tokens[token_id] = token

        return token_value

    def execute(self, **kwargs) -> Dict[str, Any]:
        """Execute a token-based action."""
        return self.use_token(
            token=kwargs.get("token", ""),
            action=kwargs.get("action", ""),
        )

    def use_token(self, token: str, action: str) -> Dict[str, Any]:
        """
        Use an authorization token to perform an action.

        The behavior depends on validation_mode:
        - STATELESS: Only verify signature → ACCEPTS resurrected tokens
        - STATEFUL_SYNC: Check consumed status → REJECTS resurrected tokens
        - STATEFUL_ASYNC: Delayed check → MAY ACCEPT within delay window

        Args:
            token: Token string
            action: Action to perform

        Returns:
            Dict with status and details
        """
        request_id = self._generate_request_id()

        # Parse and verify token signature
        valid, token_id, operation, error = self._verify_token_signature(token)

        if not valid:
            request = ServiceRequest(
                request_id=request_id,
                request_type="use_token",
                parameters={"token": token[:20] + "...", "action": action},
                result="rejected",
                metadata={"reason": error, "validation_mode": self._validation_mode.value},
            )
            self._log_request(request)
            return {"status": "rejected", "reason": error}

        # Check consumption based on validation mode
        is_consumed = self._check_consumption(token_id)

        if is_consumed:
            request = ServiceRequest(
                request_id=request_id,
                request_type="use_token",
                parameters={"token": token[:20] + "...", "action": action},
                result="rejected",
                metadata={
                    "reason": "Token already consumed",
                    "token_id": token_id,
                    "validation_mode": self._validation_mode.value,
                },
            )
            self._log_request(request)
            return {
                "status": "rejected",
                "reason": "Token has already been consumed",
                "token_id": token_id,
            }

        # Token is valid and not consumed - mark as consumed and execute
        self._mark_consumed(token_id, request_id)

        # Record operation
        self._operations_performed.append({
            "timestamp": datetime.now().isoformat(),
            "token_id": token_id,
            "action": action,
            "request_id": request_id,
        })

        request = ServiceRequest(
            request_id=request_id,
            request_type="use_token",
            parameters={"token": token[:20] + "...", "action": action},
            result="success",
            metadata={
                "token_id": token_id,
                "operation": operation,
                "validation_mode": self._validation_mode.value,
            },
        )
        self._log_request(request)

        return {
            "status": "success",
            "message": f"Token consumed successfully for action: {action}",
            "token_id": token_id,
            "operation": operation,
        }

    def _verify_token_signature(self, token: str) -> tuple:
        """
        Verify token signature.

        Returns:
            (valid, token_id, operation, error_message)
        """
        try:
            decoded = base64.urlsafe_b64decode(token.encode())
            payload_json, provided_sig = decoded.rsplit(b".", 1)

            expected_sig = hmac.new(
                self.SECRET_KEY,
                payload_json,
                hashlib.sha256
            ).digest()

            if not hmac.compare_digest(provided_sig, expected_sig):
                return False, None, None, "Invalid signature"

            payload = json.loads(payload_json.decode())
            token_id = payload.get("id")
            operation = payload.get("op")

            # Check expiration
            exp = payload.get("exp")
            if exp and datetime.fromisoformat(exp) < datetime.now():
                return False, token_id, operation, "Token expired"

            return True, token_id, operation, None

        except Exception as e:
            return False, None, None, f"Invalid token format: {e}"

    def _check_consumption(self, token_id: str) -> bool:
        """
        Check if token has been consumed.

        Behavior depends on validation mode:
        - STATELESS: Never checks → always returns False (vulnerable!)
        - STATEFUL_SYNC: Realtime check → returns actual status
        - STATEFUL_ASYNC: Delayed check → may return False during delay
        """
        if self._validation_mode == ValidationMode.STATELESS:
            # Stateless mode: only verify signature, don't track consumption
            # This is VULNERABLE - resurrected tokens will be accepted
            return False

        elif self._validation_mode == ValidationMode.STATEFUL_SYNC:
            # Sync mode: realtime check of consumption status
            # This is SECURE - resurrected tokens will be rejected
            return token_id in self._consumed_tokens

        elif self._validation_mode == ValidationMode.STATEFUL_ASYNC:
            # Async mode: consumption propagates with delay
            # Check if token is in consumed set
            if token_id in self._consumed_tokens:
                return True

            # Check if pending consumption has propagated
            if token_id in self._pending_consumptions:
                consumed_time = self._pending_consumptions[token_id]
                if time.time() - consumed_time >= self._async_delay_seconds:
                    # Propagation complete
                    self._consumed_tokens.add(token_id)
                    return True
                # Still within delay window - token appears unconsumed
                return False

            return False

        return False

    def _mark_consumed(self, token_id: str, request_id: str) -> None:
        """Mark token as consumed."""
        if token_id in self._tokens:
            token = self._tokens[token_id]
            token.consumed = True
            token.consumed_at = datetime.now().isoformat()
            token.consumed_by_request = request_id

        if self._validation_mode == ValidationMode.STATEFUL_SYNC:
            self._consumed_tokens.add(token_id)
        elif self._validation_mode == ValidationMode.STATEFUL_ASYNC:
            self._pending_consumptions[token_id] = time.time()

    def is_consumed(self, token: str) -> bool:
        """
        Check if a token has been consumed (public method).

        This checks the actual state, regardless of validation mode.
        Useful for experiment verification.
        """
        try:
            valid, token_id, _, _ = self._verify_token_signature(token)
            if not valid:
                return False

            # Check actual consumption state (not validation mode logic)
            if token_id in self._tokens:
                return self._tokens[token_id].consumed

            return False
        except Exception:
            return False

    def get_operation_count(self, action: Optional[str] = None) -> int:
        """Count operations performed."""
        if action is None:
            return len(self._operations_performed)
        return sum(1 for op in self._operations_performed if op["action"] == action)

    def _compute_metrics(self) -> Dict[str, Any]:
        """Compute auth-specific metrics."""
        base_metrics = super()._compute_metrics()

        # Count token reuse attempts
        token_uses = {}
        for op in self._operations_performed:
            tid = op["token_id"]
            token_uses[tid] = token_uses.get(tid, 0) + 1

        tokens_used_multiple_times = [tid for tid, count in token_uses.items() if count > 1]
        total_unauthorized = sum(count - 1 for count in token_uses.values() if count > 1)

        base_metrics.update({
            "validation_mode": self._validation_mode.value,
            "tokens_issued": len(self._tokens),
            "tokens_consumed": len([t for t in self._tokens.values() if t.consumed]),
            "operations_performed": len(self._operations_performed),
            "tokens_used_multiple_times": len(tokens_used_multiple_times),
            "unauthorized_operations": total_unauthorized,
        })

        return base_metrics
