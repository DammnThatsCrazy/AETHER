"""Provider canonical events enter the shared Bronze and outbox transaction.

Pull and webhook ingress persist ``RawProviderRecord`` before calling this
bridge. For each consent-admitted canonical event, ``ingest_many`` commits a
typed Bronze row and an ``SDK_EVENTS_VALIDATED`` outbox row together. The
existing supervised relay retries delivery when ``OUTBOX_RELAY_ENABLED`` is
active. The Bronze row retains the canonical payload for governed replay.
This bridge does not assign graph or Silver fact authority: tenant
connector route admission and downstream writer fencing are separate gates.
"""

from __future__ import annotations

from collections.abc import Iterable

from shared.events.events import Topic
from shared.integration_contracts.events import (
    AetherEvent,
    deterministic_v1_event_id_for_source_record,
)
from shared.logger.logger import get_logger, metrics
from services.ingestion.bronze_bulk import BronzeSDKEvent, OutboxEvent, ingest_many

logger = get_logger("aether.provider_runtime.bridge")


class EventBridge:
    """Consent-gated provider event writer using the shared durable outbox."""

    async def ingest_events(self, tenant_id: str, events: Iterable[AetherEvent]) -> int:
        """Return the count of newly persisted canonical events.

        Provider raw records have already been stored by the caller. A denied
        canonical event leaves that raw input available for governed replay.
        Any Bronze/outbox failure propagates so pull cursors and webhook inbox
        receipts cannot advance past a missing canonical event. A duplicate
        event keeps its original outbox row and is not queued twice.
        """
        if not tenant_id.strip():
            raise ValueError("tenant_id is required")

        bronze_rows: list[BronzeSDKEvent] = []
        outbox_rows: list[OutboxEvent] = []
        commerce_orders: list[AetherEvent] = []
        for candidate in events:
            event = candidate
            if event.schema_version == "2":
                # Event models are mutable. Revalidate at the durable boundary
                # so an in-memory mutation cannot break event_id == revision_id.
                event = AetherEvent.model_validate(event.model_dump())
            elif event.schema_version == "1" and event.event_id_needs_stable_fallback:
                event = event.model_copy(
                    update={
                        "event_id": deterministic_v1_event_id_for_source_record(
                            tenant_id=event.tenant_id,
                            provider_identity=event.provider_identity,
                            event_type=event.event_type,
                            source_record_id=event.source_record_id,
                        )
                    }
                )
            if event.tenant_id != tenant_id:
                raise ValueError("provider event tenant does not match ingress tenant")
            if not event.event_id or not event.source_record_id:
                raise ValueError("provider event requires replay-stable identity")
            if await self._consent_allows(tenant_id, event) is False:
                continue

            if event.provider == "shopify" and event.event_type.startswith("commerce.order."):
                commerce_orders.append(event)

            # The outbox transports the original AetherEvent envelope. Both
            # Bronze and outbox apply the shared acquisition sanitizer again;
            # the ingress scrub below runs before this durable dump.
            payload = event.model_dump()
            payload["source"] = event.provider
            payload["source_type"] = "provider"
            bronze_rows.append(
                BronzeSDKEvent(
                    tenant_id=tenant_id,
                    event_id=event.event_id,
                    schema_version=event.schema_version,
                    batch_id=f"provider:{event.provider_identity}",
                    event_type=event.event_type,
                    event_family=event.event_family,
                    event_timestamp=event.occurred_at,
                    received_at=event.observed_at,
                    session_id="",
                    anonymous_id="",
                    user_id=None,
                    entity_id=event.source_record_id,
                    payload=payload,
                    source=event.provider,
                    source_tag=f"provider:{event.provider_identity}:{event.account_id}",
                )
            )
            outbox_rows.append(
                OutboxEvent(
                    tenant_id=tenant_id,
                    event_id=event.event_id,
                    topic=Topic.SDK_EVENTS_VALIDATED.value,
                    partition_key=event.account_id or tenant_id,
                    payload=payload,
                )
            )

        if not bronze_rows:
            return 0
        result = await ingest_many(bronze_rows, outbox_rows)
        # Persist reconciliation evidence only after the canonical event and
        # outbox commit succeeds. This remains a side ledger; it does not write
        # graph/Silver facts or infer payment settlement from Shopify status.
        if commerce_orders:
            from services.commerce.order_payment_reconciliation import (
                CommerceOrderPaymentLedger,
            )

            ledger = CommerceOrderPaymentLedger()
            for event in commerce_orders:
                reference = str((event.context or {}).get("commerce_order_ref") or "")
                total = (event.data or {}).get("total") or {}
                if not reference or not isinstance(total, dict):
                    continue
                amount = total.get("amount")
                currency = total.get("currency") or (event.data or {}).get("currency")
                order_id = (event.data or {}).get("order_id")
                if amount is None or currency is None or order_id is None:
                    continue
                await ledger.record_order(
                    tenant_id,
                    commerce_order_ref=reference,
                    provider="shopify",
                    provider_order_id=str(order_id),
                    amount=str(amount),
                    currency=str(currency),
                    revision_id=str(event.revision_id or event.event_id),
                    source_revision_at=(
                        str((event.data or {}).get("updated_at"))
                        if (event.data or {}).get("updated_at")
                        else None
                    ),
                    occurred_at=event.occurred_at,
                )
        metrics.increment(
            "provider_runtime_bridge_accepted_total",
            value=result.accepted_count,
        )
        if result.duplicate_count:
            metrics.increment(
                "provider_runtime_bridge_duplicate_total",
                value=result.duplicate_count,
            )
        return result.accepted_count

    async def _consent_allows(self, tenant_id: str, event: AetherEvent) -> bool:
        """Scrub every event and apply the existing provider ingress decision.

        The per-subject receipt check remains flag-gated; the unconditional
        scrub and tenant data-policy decision are never flag-gated.
        """
        from config.settings import settings
        from services.ingestion.generated_registry import EVENT_CONSENT_PURPOSE
        from services.ingestion.validation import (
            evaluate_ingress_decision,
            scrub_sensitive_fields,
        )

        event.data, _ = scrub_sensitive_fields(event.data or {})
        event.context, _ = scrub_sensitive_fields(event.context or {})
        subject = str(event.subject_id or "").strip() or None
        purpose = EVENT_CONSENT_PURPOSE.get(event.event_type)
        if not settings.ingress_consent.provider_runtime_consent_enforcement_enabled:
            subject = purpose = None
        allowed, reason_code, _decisions = await evaluate_ingress_decision(
            tenant_id=tenant_id,
            subject_id=subject,
            anonymous_id=None,
            purpose=purpose,
            fingerprint_obj={"data": event.data, "context": event.context},
        )
        if not allowed:
            logger.warning(
                "provider_runtime_consent_denied event=%s tenant=%s type=%s reason=%s",
                event.event_id,
                tenant_id,
                event.event_type,
                reason_code,
            )
            metrics.increment(
                "provider_runtime_consent_blocked_total",
                labels={"reason": reason_code or "unknown"},
            )
            return False
        return True


__all__ = ["EventBridge"]
