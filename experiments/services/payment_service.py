"""
Payment Service Simulation for V1 Action Replay Testing.

This service demonstrates the vulnerability where:
1. Agent generates idempotency_key for payment
2. Checkpoint-Restore causes agent to "forget" the key
3. Agent regenerates a DIFFERENT key (LLM non-determinism)
4. Service processes as new payment (key changed!)
5. Result: Duplicate charge

The service has CORRECT idempotency protection - the vulnerability
is in the agent's key instability, not the service's logic.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Set
from datetime import datetime
import uuid

from .base_service import BaseService, ServiceRequest


@dataclass
class Payment:
    """Record of a processed payment."""
    charge_id: str
    order_id: str
    amount_cents: int
    idempotency_key: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "completed"


class PaymentService(BaseService):
    """
    Simulated payment service with idempotency protection.

    Key behavior:
    - Same idempotency_key → Return cached result (no duplicate charge)
    - Different idempotency_key → Process as new payment

    The vulnerability is NOT in this service - it correctly implements
    idempotency. The problem is that the agent generates different keys
    after checkpoint-restore.
    """

    def __init__(self):
        super().__init__("payment_service")

        # Idempotency tracking (by key)
        self._idempotency_cache: Dict[str, Payment] = {}

        # All payments (by charge_id)
        self._payments: Dict[str, Payment] = {}

        # Track by order_id for duplicate detection
        self._orders_charged: Dict[str, list] = {}

    def _on_reset(self) -> None:
        """Reset payment-specific state."""
        self._idempotency_cache.clear()
        self._payments.clear()
        self._orders_charged.clear()

    def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Process a payment request.

        Required kwargs:
            order_id: Order identifier
            amount_cents: Amount in cents
            idempotency_key: Client-generated unique key

        Returns:
            Dict with status, charge_id, etc.
        """
        return self.create_payment(
            order_id=kwargs.get("order_id", ""),
            amount_cents=kwargs.get("amount_cents", 0),
            idempotency_key=kwargs.get("idempotency_key", ""),
        )

    def create_payment(
        self,
        order_id: str,
        amount_cents: int,
        idempotency_key: str,
    ) -> Dict[str, Any]:
        """
        Create a payment charge.

        Idempotency behavior:
        - If idempotency_key was seen before → return cached result
        - If new key → process payment and cache result

        This is CORRECT behavior. The vulnerability is that the agent
        generates different keys after restore.
        """
        request_id = self._generate_request_id()

        # Check idempotency cache
        if idempotency_key in self._idempotency_cache:
            cached = self._idempotency_cache[idempotency_key]

            request = ServiceRequest(
                request_id=request_id,
                request_type="create_payment",
                parameters={
                    "order_id": order_id,
                    "amount_cents": amount_cents,
                    "idempotency_key": idempotency_key,
                },
                result="duplicate",
                metadata={
                    "cached_charge_id": cached.charge_id,
                    "note": "Idempotency key already used - returning cached result",
                },
            )
            self._log_request(request)

            return {
                "status": "duplicate",
                "message": f"Idempotency key '{idempotency_key}' already used",
                "original_charge_id": cached.charge_id,
                "order_id": cached.order_id,
                "amount_cents": cached.amount_cents,
            }

        # Process new payment
        charge_id = f"ch_{uuid.uuid4().hex[:12]}"

        payment = Payment(
            charge_id=charge_id,
            order_id=order_id,
            amount_cents=amount_cents,
            idempotency_key=idempotency_key,
        )

        # Store payment
        self._idempotency_cache[idempotency_key] = payment
        self._payments[charge_id] = payment

        # Track by order_id
        if order_id not in self._orders_charged:
            self._orders_charged[order_id] = []
        self._orders_charged[order_id].append(charge_id)

        # Log request
        request = ServiceRequest(
            request_id=request_id,
            request_type="create_payment",
            parameters={
                "order_id": order_id,
                "amount_cents": amount_cents,
                "idempotency_key": idempotency_key,
            },
            result="success",
            metadata={
                "charge_id": charge_id,
            },
        )
        self._log_request(request)

        return {
            "status": "success",
            "charge_id": charge_id,
            "order_id": order_id,
            "amount_cents": amount_cents,
            "message": f"Payment of ${amount_cents/100:.2f} processed successfully",
        }

    def get_charges_for_order(self, order_id: str) -> list:
        """
        Get all charges for an order.

        Multiple charges for the same order indicates duplicate payments
        (the vulnerability we're testing).
        """
        charge_ids = self._orders_charged.get(order_id, [])
        return [self._payments[cid] for cid in charge_ids if cid in self._payments]

    def count_charges_for_order(self, order_id: str) -> int:
        """Count how many times an order was charged."""
        return len(self._orders_charged.get(order_id, []))

    def get_unique_keys_for_order(self, order_id: str) -> Set[str]:
        """
        Get all idempotency keys used for an order.

        If len > 1, agent generated different keys for same order.
        """
        charges = self.get_charges_for_order(order_id)
        return {c.idempotency_key for c in charges}

    def detect_key_instability(self, order_id: str) -> bool:
        """
        Detect if different idempotency keys were used for same order.

        Returns True if multiple different keys were used (vulnerability!).
        """
        keys = self.get_unique_keys_for_order(order_id)
        return len(keys) > 1

    def _compute_metrics(self) -> Dict[str, Any]:
        """Compute payment-specific metrics."""
        base_metrics = super()._compute_metrics()

        # Count orders with multiple charges (duplicates)
        orders_with_duplicates = [
            oid for oid, charges in self._orders_charged.items()
            if len(charges) > 1
        ]

        # Count orders with key instability
        orders_with_key_instability = [
            oid for oid in self._orders_charged.keys()
            if self.detect_key_instability(oid)
        ]

        # Calculate total duplicate charges
        duplicate_charges = sum(
            len(charges) - 1  # Extra charges beyond the first
            for charges in self._orders_charged.values()
            if len(charges) > 1
        )

        # Calculate financial impact
        total_overcharge = sum(
            self._payments[cid].amount_cents
            for oid, charges in self._orders_charged.items()
            for cid in charges[1:]  # All charges after the first
            if cid in self._payments
        )

        base_metrics.update({
            "unique_orders": len(self._orders_charged),
            "orders_with_duplicates": len(orders_with_duplicates),
            "orders_with_key_instability": len(orders_with_key_instability),
            "duplicate_charges": duplicate_charges,
            "total_overcharge_cents": total_overcharge,
            "total_overcharge_usd": total_overcharge / 100,
        })

        return base_metrics

    def verify_idempotency_works(self, idempotency_key: str) -> bool:
        """
        Verify that idempotency protection is working.

        If the same key is used twice, only one charge should exist.
        """
        if idempotency_key not in self._idempotency_cache:
            return True  # Key not used yet

        # Key exists - check that only one payment was processed
        payment = self._idempotency_cache[idempotency_key]
        return payment.charge_id in self._payments
