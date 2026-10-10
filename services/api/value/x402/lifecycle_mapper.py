"""
Aether Service — x402 Lifecycle Mapper

Routes canonical x402 lifecycle events to the appropriate repository operations.
Supports both new granular event types and the legacy x402_payment event.

Event flow:
  x402_resource_requested
    → x402_payment_required
    → x402_quote_received
    → x402_authorization_requested
    → x402_authorization_resolved
    → x402_payment_intent_created
    → x402_payment_submitted
    → x402_payment_settled | x402_payment_failed | x402_payment_timeout
    → x402_receipt_verified
    → x402_access_granted | x402_access_denied
    → x402_refund_or_reversal  (optional)
"""

from __future__ import annotations

from typing import Any, Optional

from repositories.repos import (
    AgentEconomicIdentityRepository,
    EconomicResourceRepository,
    FacilitatorRepository,
    PaymentIntentRepository,
    SettlementEventRepository,
)
from shared.common.common import utc_now
from shared.logger.logger import get_logger

logger = get_logger("aether.service.x402.lifecycle_mapper")


class X402LifecycleMapper:
    """Routes x402 lifecycle events to repository operations.

    Designed to be called from an event consumer or route handler. All
    mutations are tenant-scoped. Idempotency is enforced via ``event_id``
    or ``payment_intent_id`` — if a record for the given ID already exists
    the call is a no-op for insert paths (``record_intent`` / ``record_event``
    are backed by ``insert`` which is idempotent on duplicate IDs in the
    underlying store).
    """

    def __init__(
        self,
        payment_intents: Optional[PaymentIntentRepository] = None,
        settlements: Optional[SettlementEventRepository] = None,
        resources: Optional[EconomicResourceRepository] = None,
        facilitators: Optional[FacilitatorRepository] = None,
        identities: Optional[AgentEconomicIdentityRepository] = None,
    ) -> None:
        self._payment_intents = payment_intents or PaymentIntentRepository()
        self._settlements = settlements or SettlementEventRepository()
        self._resources = resources or EconomicResourceRepository()
        self._facilitators = facilitators or FacilitatorRepository()
        self._identities = identities or AgentEconomicIdentityRepository()

    # ─────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────

    async def handle_event(
        self, event_type: str, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        """Dispatch a single x402 lifecycle event to the correct handler.

        Returns a dict describing the resulting repository operation(s).
        """
        handlers = {
            # New granular lifecycle events
            "x402_resource_requested": self._handle_resource_requested,
            "x402_payment_required": self._handle_payment_required,
            "x402_quote_received": self._handle_quote_received,
            "x402_authorization_requested": self._handle_authorization_requested,
            "x402_authorization_resolved": self._handle_authorization_resolved,
            "x402_payment_intent_created": self._handle_payment_intent_created,
            "x402_payment_submitted": self._handle_payment_submitted,
            "x402_payment_settled": self._handle_payment_settled,
            "x402_payment_failed": self._handle_payment_failed,
            "x402_payment_timeout": self._handle_payment_timeout,
            "x402_receipt_verified": self._handle_receipt_verified,
            "x402_access_granted": self._handle_access_granted,
            "x402_access_denied": self._handle_access_denied,
            "x402_refund_or_reversal": self._handle_refund_or_reversal,
            # Legacy event — normalize to settled path
            "x402_payment": self._handle_legacy_payment,
        }
        handler = handlers.get(event_type)
        if handler is None:
            logger.warning(f"Unknown x402 event type: {event_type!r}")
            return {"status": "ignored", "event_type": event_type}

        try:
            result = await handler(payload, tenant_id)
            logger.info(f"x402 lifecycle event handled: {event_type}", extra={"tenant_id": tenant_id})
            return result
        except Exception as exc:
            logger.error(
                f"x402 lifecycle event failed: {event_type}: {exc}",
                extra={"tenant_id": tenant_id},
                exc_info=True,
            )
            raise

    # ─────────────────────────────────────────────────────────────────────
    # Handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_resource_requested(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        resource_id = payload.get("resource_id") or payload.get("event_id", "")
        if not resource_id:
            return {"status": "skipped", "reason": "no resource_id"}

        record = await self._resources.upsert_resource(
            resource_id=resource_id,
            tenant_id=tenant_id,
            resource_type=payload.get("resource_type", "api_access"),
            provider=payload.get("provider", ""),
            capability=payload.get("capability_requested", ""),
            protocol=payload.get("protocol", ""),
            endpoint=payload.get("endpoint", ""),
            metadata=payload.get("metadata"),
        )
        return {"status": "upserted", "resource_id": resource_id, "record": record}

    async def _handle_payment_required(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        intent_id = _require_intent_id(payload)
        record = await self._payment_intents.record_intent(
            intent_id=intent_id,
            tenant_id=tenant_id,
            agent_id=payload.get("agent_id", ""),
            amount=payload.get("amount", "0"),
            currency=payload.get("currency", "USD"),
            provider=payload.get("provider", ""),
            protocol=payload.get("protocol", ""),
            endpoint=payload.get("endpoint", ""),
            capability_requested=payload.get("capability_requested", ""),
            settlement_status="pending",
            resource_id=payload.get("resource_id"),
            facilitator_id=payload.get("facilitator_id"),
            metadata=payload.get("metadata"),
            occurred_at=payload.get("timestamp"),
        )
        return {"status": "created", "intent_id": intent_id, "record": record}

    async def _handle_quote_received(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        intent_id = _require_intent_id(payload)
        # Attempt to update existing intent; if not found, create it
        existing = await self._payment_intents.find_for_tenant(intent_id, tenant_id)
        if existing:
            record = await self._payment_intents.update_status(
                intent_id=intent_id,
                tenant_id=tenant_id,
                status="quoted",
                metadata={**payload.get("metadata", {}), "quote_id": payload.get("quote_id", "")},
            )
        else:
            record = await self._payment_intents.record_intent(
                intent_id=intent_id,
                tenant_id=tenant_id,
                agent_id=payload.get("agent_id", ""),
                amount=payload.get("amount", "0"),
                currency=payload.get("currency", "USD"),
                provider=payload.get("provider", ""),
                protocol=payload.get("protocol", ""),
                settlement_status="quoted",
                quote_id=payload.get("quote_id"),
                metadata=payload.get("metadata"),
                occurred_at=payload.get("timestamp"),
            )
        return {"status": "updated", "intent_id": intent_id, "record": record}

    async def _handle_authorization_requested(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        intent_id = _require_intent_id(payload)
        existing = await self._payment_intents.find_for_tenant(intent_id, tenant_id)
        if existing:
            record = await self._payment_intents.update_status(
                intent_id=intent_id, tenant_id=tenant_id, status="authorization_requested"
            )
            return {"status": "updated", "intent_id": intent_id, "record": record}
        return {"status": "skipped", "reason": "intent not found", "intent_id": intent_id}

    async def _handle_authorization_resolved(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        intent_id = _require_intent_id(payload)
        decision = payload.get("decision", "approved")
        new_status = "authorized" if decision == "approved" else "authorization_denied"
        existing = await self._payment_intents.find_for_tenant(intent_id, tenant_id)
        if existing:
            record = await self._payment_intents.update_status(
                intent_id=intent_id,
                tenant_id=tenant_id,
                status=new_status,
                metadata={
                    **payload.get("metadata", {}),
                    "authorization_id": payload.get("authorization_id", ""),
                    "decision": decision,
                },
            )
            return {"status": "updated", "intent_id": intent_id, "record": record}
        return {"status": "skipped", "reason": "intent not found", "intent_id": intent_id}

    async def _handle_payment_intent_created(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        intent_id = _require_intent_id(payload)
        # Idempotency: skip if already exists
        existing = await self._payment_intents.find_for_tenant(intent_id, tenant_id)
        if existing:
            return {"status": "exists", "intent_id": intent_id}
        record = await self._payment_intents.record_intent(
            intent_id=intent_id,
            tenant_id=tenant_id,
            agent_id=payload.get("agent_id", ""),
            amount=payload.get("amount", "0"),
            currency=payload.get("currency", "USD"),
            provider=payload.get("provider", ""),
            protocol=payload.get("protocol", ""),
            endpoint=payload.get("endpoint", ""),
            capability_requested=payload.get("capability_requested", ""),
            settlement_status="intent_created",
            resource_id=payload.get("resource_id"),
            facilitator_id=payload.get("facilitator_id"),
            authorization_id=payload.get("authorization_id"),
            execution_id=payload.get("execution_id"),
            metadata=payload.get("metadata"),
            occurred_at=payload.get("timestamp"),
        )
        return {"status": "created", "intent_id": intent_id, "record": record}

    async def _handle_payment_submitted(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        event_id = _require_settlement_event_id(payload)
        intent_id = _require_intent_id(payload)
        record = await self._settlements.record_event(
            settlement_event_id=event_id,
            tenant_id=tenant_id,
            intent_id=intent_id,
            agent_id=payload.get("agent_id", ""),
            status="pending",
            amount=payload.get("amount", "0"),
            currency=payload.get("currency", "USD"),
            provider=payload.get("provider", ""),
            protocol=payload.get("protocol", ""),
            facilitator_id=payload.get("facilitator_id"),
            metadata=payload.get("metadata"),
            occurred_at=payload.get("timestamp"),
        )
        return {"status": "created", "settlement_event_id": event_id, "record": record}

    async def _handle_payment_settled(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        event_id = _require_settlement_event_id(payload)
        intent_id = _require_intent_id(payload)
        settlement_record = await self._settlements.record_event(
            settlement_event_id=event_id,
            tenant_id=tenant_id,
            intent_id=intent_id,
            agent_id=payload.get("agent_id", ""),
            status="settled",
            amount=payload.get("amount", "0"),
            currency=payload.get("currency", "USD"),
            provider=payload.get("provider", ""),
            protocol=payload.get("protocol", ""),
            facilitator_id=payload.get("facilitator_id"),
            tx_hash=payload.get("tx_hash"),
            metadata=payload.get("metadata"),
            occurred_at=payload.get("timestamp"),
        )
        # Update intent status
        intent_record = None
        existing_intent = await self._payment_intents.find_for_tenant(intent_id, tenant_id)
        if existing_intent:
            intent_record = await self._payment_intents.update_status(
                intent_id=intent_id, tenant_id=tenant_id, status="settled"
            )
        return {
            "status": "settled",
            "settlement_event_id": event_id,
            "intent_id": intent_id,
            "settlement_record": settlement_record,
            "intent_record": intent_record,
        }

    async def _handle_payment_failed(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        return await self._record_terminal_settlement(payload, tenant_id, "failed")

    async def _handle_payment_timeout(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        return await self._record_terminal_settlement(payload, tenant_id, "timeout")

    async def _handle_receipt_verified(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        settlement_event_id = payload.get("settlement_event_id", "")
        receipt_id = payload.get("receipt_id", "")
        if not settlement_event_id:
            return {"status": "skipped", "reason": "no settlement_event_id"}
        record = await self._settlements.mark_receipt_verified(
            settlement_event_id=settlement_event_id,
            tenant_id=tenant_id,
            receipt_id=receipt_id,
            metadata=payload.get("metadata"),
        )
        return {"status": "verified", "settlement_event_id": settlement_event_id, "record": record}

    async def _handle_access_granted(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        intent_id = payload.get("payment_intent_id", payload.get("intent_id", ""))
        if intent_id:
            existing = await self._payment_intents.find_for_tenant(intent_id, tenant_id)
            if existing:
                record = await self._payment_intents.update_status(
                    intent_id=intent_id, tenant_id=tenant_id, status="access_granted"
                )
                return {"status": "updated", "intent_id": intent_id, "record": record}
        return {"status": "noted", "event_type": "x402_access_granted"}

    async def _handle_access_denied(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        intent_id = payload.get("payment_intent_id", payload.get("intent_id", ""))
        if intent_id:
            existing = await self._payment_intents.find_for_tenant(intent_id, tenant_id)
            if existing:
                record = await self._payment_intents.update_status(
                    intent_id=intent_id, tenant_id=tenant_id, status="access_denied"
                )
                return {"status": "updated", "intent_id": intent_id, "record": record}
        return {"status": "noted", "event_type": "x402_access_denied"}

    async def _handle_refund_or_reversal(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        return await self._record_terminal_settlement(payload, tenant_id, "reversed")

    async def _handle_legacy_payment(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        """Normalize legacy x402_payment event to the settled path."""
        normalized = dict(payload)
        normalized.setdefault("settlement_event_id", payload.get("capture_id", utc_now().isoformat()))
        normalized.setdefault("payment_intent_id", payload.get("capture_id", utc_now().isoformat()))
        result = await self._handle_payment_settled(normalized, tenant_id)
        result["normalized_from"] = "x402_payment"
        return result

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────

    async def _record_terminal_settlement(
        self, payload: dict[str, Any], tenant_id: str, status: str
    ) -> dict[str, Any]:
        event_id = _require_settlement_event_id(payload)
        intent_id = _require_intent_id(payload)
        settlement_record = await self._settlements.record_event(
            settlement_event_id=event_id,
            tenant_id=tenant_id,
            intent_id=intent_id,
            agent_id=payload.get("agent_id", ""),
            status=status,
            amount=payload.get("amount", "0"),
            currency=payload.get("currency", "USD"),
            provider=payload.get("provider", ""),
            protocol=payload.get("protocol", ""),
            facilitator_id=payload.get("facilitator_id"),
            failure_reason=payload.get("failure_reason"),
            metadata=payload.get("metadata"),
            occurred_at=payload.get("timestamp"),
        )
        intent_record = None
        existing_intent = await self._payment_intents.find_for_tenant(intent_id, tenant_id)
        if existing_intent:
            intent_record = await self._payment_intents.update_status(
                intent_id=intent_id, tenant_id=tenant_id, status=status,
                metadata={"failure_reason": payload.get("failure_reason", "")},
            )
        return {
            "status": status,
            "settlement_event_id": event_id,
            "intent_id": intent_id,
            "settlement_record": settlement_record,
            "intent_record": intent_record,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _require_intent_id(payload: dict[str, Any]) -> str:
    """Extract payment_intent_id from payload, falling back to intent_id."""
    return (
        payload.get("payment_intent_id")
        or payload.get("intent_id")
        or payload.get("event_id")
        or utc_now().isoformat()
    )


def _require_settlement_event_id(payload: dict[str, Any]) -> str:
    """Extract settlement_event_id from payload, falling back to capture_id / event_id."""
    return (
        payload.get("settlement_event_id")
        or payload.get("capture_id")
        or payload.get("event_id")
        or utc_now().isoformat()
    )
