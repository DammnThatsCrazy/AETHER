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
from value.x402.provenance import is_server_authoritative_x402_metadata

logger = get_logger("aether.service.x402.lifecycle_mapper")

_AUTHORITATIVE_INTENT_STATUS_ORDER = {
    "intent_created": 10,
    "pending": 10,
    "quoted": 20,
    "authorization_requested": 30,
    "authorization_denied": 35,
    "authorized": 40,
    "submitted": 50,
    "failed": 60,
    "timeout": 60,
    "settled": 70,
    "access_denied": 80,
    "access_granted": 80,
    "reversed": 90,
}
_SERVER_ONLY_LIFECYCLE_EVENTS = frozenset({
    "x402_payment_settled",
    "x402_payment_failed",
    "x402_payment_timeout",
    "x402_receipt_verified",
    "x402_access_granted",
    "x402_access_denied",
    "x402_refund_or_reversal",
})


class X402LifecycleMapper:
    """Routes x402 lifecycle events to repository operations.

    Designed to be called from an event consumer or route handler. All
    mutations are tenant-scoped. Repository record IDs make repeated writes
    idempotent. Server-authoritative x402 facts are protected from later
    public-SDK observations, while exact server events can promote earlier
    SDK-only rows to server-observed provenance.
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
        if (
            event_type in _SERVER_ONLY_LIFECYCLE_EVENTS
            and not is_server_authoritative_x402_metadata(payload.get("metadata"))
        ):
            return {
                "status": "deferred",
                "reason": "source_authority_required",
                "event_type": event_type,
            }

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
        existing = await self._payment_intents.find_for_tenant(intent_id, tenant_id)
        if (
            existing
            and is_server_authoritative_x402_metadata(existing.get("metadata"))
            and not is_server_authoritative_x402_metadata(payload.get("metadata"))
        ):
            return {"status": "existing_authoritative", "intent_id": intent_id, "record": existing}
        if is_server_authoritative_x402_metadata(payload.get("metadata")):
            record = await self._record_authoritative_intent(
                payload, tenant_id, intent_id, settlement_status="pending",
            )
            return {
                "status": "updated" if existing else "created",
                "intent_id": intent_id,
                "record": record,
            }
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
            if (
                is_server_authoritative_x402_metadata(existing.get("metadata"))
                and not is_server_authoritative_x402_metadata(payload.get("metadata"))
            ):
                return {"status": "observation_only", "intent_id": intent_id, "record": existing}
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
            if (
                is_server_authoritative_x402_metadata(existing.get("metadata"))
                and not is_server_authoritative_x402_metadata(payload.get("metadata"))
            ):
                return {"status": "observation_only", "intent_id": intent_id, "record": existing}
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
                authorization_id=(
                    str(payload["authorization_id"])
                    if payload.get("authorization_id")
                    else None
                ),
                execution_id=(
                    str(payload["execution_id"])
                    if payload.get("execution_id")
                    else None
                ),
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
        payload_is_authoritative = is_server_authoritative_x402_metadata(payload.get("metadata"))
        intent = await self._payment_intents.find_for_tenant(intent_id, tenant_id)
        authorization_id = str(payload.get("authorization_id") or "")
        if (
            intent is not None
            and authorization_id
            and not payload_is_authoritative
            and not is_server_authoritative_x402_metadata(intent.get("metadata"))
        ):
            # A public observation may repeat an authorization identifier, but
            # only the tenant-scoped x402 source record whose challenge exactly
            # matches this intent is retained as an authoritative link.
            from .commerce_store import get_commerce_store

            authorization = await get_commerce_store().get_authorization(
                tenant_id, authorization_id
            )
            if authorization is not None and authorization.challenge_id == intent_id:
                await self._payment_intents.update_status(
                    intent_id=intent_id,
                    tenant_id=tenant_id,
                    status="submitted",
                    authorization_id=authorization_id,
                )
        if payload_is_authoritative:
            await self._record_authoritative_intent(
                payload, tenant_id, intent_id, settlement_status="submitted",
            )
        existing_settlement = await self._settlements.find_by_id(event_id)
        if (
            existing_settlement
            and existing_settlement.get("tenant_id") == tenant_id
            and is_server_authoritative_x402_metadata(existing_settlement.get("metadata"))
            and not payload_is_authoritative
        ):
            return {
                "status": "observation_only",
                "settlement_event_id": event_id,
                "record": existing_settlement,
            }
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
        # The server settlement may arrive before an authoritative intent
        # event, or after an SDK-only observation created the row. Rebuild the
        # intent from this closed server event so correlation does not inherit
        # caller-authored agent, amount, currency, or status fields.
        intent_record = await self._record_authoritative_intent(
            payload, tenant_id, intent_id, settlement_status="settled",
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
        if is_server_authoritative_x402_metadata(payload.get("metadata")):
            intent_record = await self._record_authoritative_intent(
                payload, tenant_id, intent_id, settlement_status=status,
            )
        else:
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

    async def _record_authoritative_intent(
        self,
        payload: dict[str, Any],
        tenant_id: str,
        intent_id: str,
        *,
        settlement_status: str,
    ) -> Optional[dict[str, Any]]:
        """Upsert an intent only from a closed server x402 lifecycle event.

        When an SDK observation created the row first, none of its economic
        fields are carried forward. Fields absent from a later server event
        are preserved only from an already server-authoritative row.
        """
        if not is_server_authoritative_x402_metadata(payload.get("metadata")):
            return None
        existing = await self._payment_intents.find_for_tenant(intent_id, tenant_id)
        trusted_existing = (
            existing is not None
            and is_server_authoritative_x402_metadata(existing.get("metadata"))
        )
        prior = existing if trusted_existing else {}
        if trusted_existing:
            previous_status = str(prior.get("settlement_status") or "").lower()
            previous_order = _AUTHORITATIVE_INTENT_STATUS_ORDER.get(previous_status, -1)
            incoming_order = _AUTHORITATIVE_INTENT_STATUS_ORDER.get(settlement_status, -1)
            if previous_order > incoming_order:
                settlement_status = previous_status
        metadata = dict(prior.get("metadata") or {})
        if isinstance(payload.get("metadata"), dict):
            metadata.update(payload["metadata"])
        return await self._payment_intents.record_intent(
            intent_id=intent_id,
            tenant_id=tenant_id,
            agent_id=str(payload.get("agent_id") or prior.get("agent_id") or ""),
            amount=str(payload.get("amount", prior.get("amount", "0"))),
            currency=str(payload.get("currency", prior.get("currency", "USD"))),
            provider=str(payload.get("provider", prior.get("provider", ""))),
            protocol=str(payload.get("protocol", prior.get("protocol", ""))),
            endpoint=str(payload.get("endpoint", prior.get("endpoint", ""))),
            capability_requested=str(
                payload.get("capability_requested", prior.get("capability_requested", ""))
            ),
            settlement_status=settlement_status,
            retry_count=int(prior.get("retry_count") or 0),
            resource_id=payload.get("resource_id", prior.get("resource_id")),
            facilitator_id=payload.get("facilitator_id", prior.get("facilitator_id")),
            quote_id=prior.get("quote_id"),
            authorization_id=payload.get("authorization_id", prior.get("authorization_id")),
            execution_id=payload.get("execution_id", prior.get("execution_id")),
            abandoned_reason=prior.get("abandoned_reason"),
            metadata=metadata,
            occurred_at=prior.get("occurred_at") or payload.get("timestamp"),
        )


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
