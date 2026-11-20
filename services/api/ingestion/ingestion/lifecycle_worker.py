"""Project safe SDK lifecycle observations into their canonical mappers.

Public SDK events are source assertions. In particular, an SDK event cannot
prove that a payment settled, an authorization was granted, or access was
delivered. This worker therefore projects only x402 request and intent stages
into the existing durable lifecycle store. Settlement and terminal outcomes
remain with source-authoritative verification paths.
"""

from __future__ import annotations

from shared.events.events import Event
from shared.logger.logger import get_logger, metrics
from value.x402.provenance import AUTHORITATIVE_X402_SOURCES

logger = get_logger("aether.ingestion.lifecycle_worker")

# These stages describe requests or submitted intent. They do not establish a
# completed payment, verified authorization, or fulfilled resource access.
SDK_X402_OBSERVATION_EVENTS = frozenset(
    {
        "x402_resource_requested",
        "x402_payment_required",
        "x402_quote_received",
        "x402_authorization_requested",
        "x402_payment_intent_created",
        "x402_payment_submitted",
    }
)

async def project_sdk_lifecycle_observation(event: Event) -> None:
    """Persist an accepted SDK x402 observation through the canonical mapper.

    The tenant comes from the validated event envelope. The event ID is kept
    with the observation for replay-safe identity and lineage. Agent authority
    events and x402 terminal claims are deliberately not projected from this
    public-SDK channel.
    """
    payload = dict(event.payload or {})
    event_type = str(payload.get("event_type") or "").strip()
    if event_type not in SDK_X402_OBSERVATION_EVENTS:
        if event_type.startswith("x402_"):
            metrics.increment(
                "lifecycle_observation_deferred_total",
                labels={"family": "x402", "reason": "source_authority_required"},
            )
        return

    tenant_id = str(event.tenant_id or payload.get("tenant_id") or "").strip()
    event_id = str(payload.get("event_id") or event.event_id or "").strip()
    if not tenant_id or not event_id:
        logger.warning("x402 lifecycle observation missing tenant or event id")
        metrics.increment(
            "lifecycle_observation_skipped_total",
            labels={"family": "x402", "reason": "missing_identity"},
        )
        return

    properties = payload.get("properties")
    properties = dict(properties) if isinstance(properties, dict) else {}
    # Lifecycle mapper contracts use a flat payload, while the public SDK
    # envelope stores event-specific fields under properties. Keep the envelope
    # authoritative where both contain a value.
    mapped = {**properties, **payload}
    mapped["event_id"] = event_id
    if event_type != "x402_resource_requested" and not (
        mapped.get("payment_intent_id") or mapped.get("intent_id")
    ):
        logger.warning(
            "x402 lifecycle observation missing payment intent id",
            extra={"tenant_id": tenant_id, "event_id": event_id, "event_type": event_type},
        )
        metrics.increment(
            "lifecycle_observation_skipped_total",
            labels={"family": "x402", "reason": "missing_payment_intent_id"},
        )
        return
    mapped["metadata"] = {
        **(dict(mapped.get("metadata")) if isinstance(mapped.get("metadata"), dict) else {}),
        "evidence_status": "observed",
        "source_kind": "public_sdk",
        "source_authority": "public_sdk_observation",
        "source_event_id": event_id,
        "source_event_type": event_type,
    }

    from value.x402.lifecycle_mapper import X402LifecycleMapper

    result = await X402LifecycleMapper().handle_event(event_type, mapped, tenant_id)
    metrics.increment(
        "lifecycle_observation_projected_total",
        labels={"family": "x402", "event_type": event_type},
    )
    logger.info(
        "x402 lifecycle observation projected",
        extra={"tenant_id": tenant_id, "event_id": event_id, "result_status": result.get("status")},
    )


async def project_authoritative_x402_lifecycle(event: Event) -> None:
    """Project an on-chain-verified x402 settlement through the x402 mapper.

    The topic and producer must match the closed registry, whose only live
    producer is the settlement observer (ADR-012): it verified the payment on
    the chain before publishing. A client payload never reaches this path.
    The intent and settlement identities are derived from the observation id,
    which is deterministic per (tenant, chain, transaction hash), so a repeated
    observation projects idempotently. The agent reference is kept exactly as
    reported (``agent_ref_source``); this path does not resolve it.
    """
    topic = str(getattr(event.topic, "value", event.topic))
    authority = AUTHORITATIVE_X402_SOURCES.get(topic)
    if authority is None or event.source_service != authority[0]:
        metrics.increment("lifecycle_observation_deferred_total", labels={"family": "x402", "reason": "source_authority_required"})
        return
    tenant_id = str(event.tenant_id or "").strip()
    event_id = str(event.event_id or "").strip()
    if not tenant_id or not event_id:
        return
    payload = dict(event.payload or {})
    stage = authority[1]
    observation_id = str(payload.get("observation_id") or "").strip()
    tx_hash = str(payload.get("tx_hash") or "").strip()
    amount = str(payload.get("amount") or "").strip()
    currency = str(payload.get("asset_symbol") or "").strip()
    if not observation_id or not tx_hash or not amount or not currency:
        metrics.increment("lifecycle_observation_deferred_total", labels={"family": "x402", "reason": "incomplete_observation"})
        return
    mapped: dict = {
        "event_id": event_id,
        "payment_intent_id": observation_id,
        "settlement_event_id": f"{observation_id}:{stage}",
        "agent_id": str(payload.get("agent_id") or ""),
        "amount": amount,
        "currency": currency,
        "provider": "x402",
        "protocol": "x402",
        "tx_hash": tx_hash,
        "receipt_id": payload.get("receipt_id"),
        "timestamp": payload.get("verified_at") or getattr(event, "timestamp", None),
        "metadata": {"evidence_status": "server_observed", "source_authority": "x402_commerce",
                     "source_event_id": event_id,
                     "source_topic": topic, "source_service": event.source_service,
                     "verification": "on_chain", "verdict": payload.get("verdict"),
                     "chain": payload.get("chain"),
                     "agent_ref_source": payload.get("agent_ref_source") or "unknown"},
    }

    from value.x402.lifecycle_mapper import X402LifecycleMapper
    result = await X402LifecycleMapper().handle_event(stage, mapped, tenant_id)
    if mapped.get("agent_id") and mapped.get("payment_intent_id"):
        # The repositories remain the source of truth; this is an additive
        # projection into the existing PaymentIntent/SettlementEvent graph
        # types. Client SDK claims never enter this graph writer.
        from repositories.repos import PaymentIntentRepository, SettlementEventRepository
        from value.x402.economic_mutations import EconomicGraphMutations

        intent_id = str(mapped["payment_intent_id"])
        intent = await PaymentIntentRepository().find_for_tenant(intent_id, tenant_id)
        if intent is not None:
            settlements = await SettlementEventRepository().list_for_intent(
                intent_id, tenant_id
            )
            await EconomicGraphMutations().write_agent_payment_operation(
                intent, settlements
            )
    metrics.increment("lifecycle_observation_projected_total", labels={"family": "x402", "event_type": stage})
    logger.info("authoritative x402 lifecycle projected", extra={
        "tenant_id": tenant_id, "event_id": event_id, "event_type": stage,
        "result_status": result.get("status"),
    })

