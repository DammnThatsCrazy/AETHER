"""Silver projector — card-linked context on existing payment/commerce events.

V1 deliberately reuses existing SDK event types (payment_initiated,
payment_completed, payment_failed, transaction, conversion,
reward_action_queued) instead of new registry entries: an event is
card-linked when its properties carry ``card_program``/``card_program_id``.
Events without card-linked context are skipped — this projector never
invents card activity.

Rows land in ``card_linked_flow_facts`` with basis/source/confidence so
downstream surfaces can separate top-up, funding, spend, and unknown.
SDK evidence alone may never claim off-chain spend — spend-basis claims
from SDK events are downgraded to ``unknown`` (the audit trail in the
ingestion service captures the same rule for the durable stores).
"""

from __future__ import annotations

import hashlib
from typing import Any

from services.silver.projectors.base import BaseProjector, ProjectionResult

_CARD_LINKED_EVENT_TYPES = frozenset({
    "payment_initiated", "payment_completed", "payment_failed",
    "transaction", "conversion", "reward_action_queued",
})

_ALLOWED_SDK_BASES = frozenset({
    "topup", "funding", "refund", "reversal", "mixed", "unknown",
})


class CardLinkedProjector(BaseProjector):
    handles: frozenset[str] = _CARD_LINKED_EVENT_TYPES

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        props = event.get("properties") or {}
        ctx = event.get("context") or {}
        card_program = props.get("card_program") or props.get("card_program_id")
        if not card_program:
            return ProjectionResult(
                table="card_linked_flow_facts", rows=[], skipped=True,
                skip_reason="no_card_linked_context",
            )

        tenant_id = ctx.get("tenantId") or event.get("tenantId") or "default"
        source_event_id = event.get("messageId") or event.get("id") or ""
        basis = str(props.get("basis") or "unknown")
        if basis not in _ALLOWED_SDK_BASES:
            basis = "unknown"  # SDK evidence cannot prove off-chain spend

        idempotency_key = hashlib.sha256(
            f"{tenant_id}:card_linked:{source_event_id}".encode()
        ).hexdigest()

        row = {
            "idempotency_key": idempotency_key,
            "source_event_id": source_event_id,
            "tenant_id": tenant_id,
            "event_type": event.get("type"),
            "user_id": event.get("userId") or event.get("user_id"),
            "session_id": ctx.get("sessionId") or event.get("session_id"),
            "card_program_id": str(card_program),
            "issuer_id": props.get("issuer_id"),
            "payment_network": props.get("payment_network", "unknown"),
            "basis": basis,
            "rail": "card",
            "chain": props.get("chain"),
            "asset": props.get("asset"),
            "amount_usd": props.get("amount_usd"),
            "campaign_id": props.get("campaign_id"),
            "journey_id": props.get("journey_id"),
            "source": "sdk",
            "confidence": "probable",
            "occurred_at": event.get("timestamp"),
        }
        return ProjectionResult(table="card_linked_flow_facts", rows=[row])
