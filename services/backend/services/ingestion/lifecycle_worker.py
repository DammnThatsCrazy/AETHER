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

_AUTHORITATIVE_X402_SOURCES = {
    "aether.commerce.challenge.issued": ("x402.control_plane", "x402_payment_required"),
    "aether.commerce.payment.submitted": ("x402.control_plane", "x402_payment_submitted"),
    "aether.commerce.settlement.completed": ("x402.settlement", "x402_payment_settled"),
    "aether.commerce.settlement.failed": ("x402.settlement", "x402_payment_failed"),
    "aether.commerce.access.granted": ("x402.control_plane", "x402_access_granted"),
}


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
        "source_event_id": event_id,
        "source_event_type": event_type,
    }

    from services.x402.lifecycle_mapper import X402LifecycleMapper

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
    """Project server-owned commerce transitions through the x402 mapper.

    The stage and producer must match a closed registry. For transitions whose
    event contains only a store key, tenant-scoped control-plane records supply
    the linked intent facts; a client payload never reaches this path.
    """
    topic = str(getattr(event.topic, "value", event.topic))
    authority = _AUTHORITATIVE_X402_SOURCES.get(topic)
    if authority is None or event.source_service != authority[0]:
        metrics.increment("lifecycle_observation_deferred_total", labels={"family": "x402", "reason": "source_authority_required"})
        return
    tenant_id = str(event.tenant_id or "").strip()
    event_id = str(event.event_id or "").strip()
    if not tenant_id or not event_id:
        return
    payload = dict(event.payload or {})
    from services.x402.commerce_store import get_commerce_store

    store = get_commerce_store()
    stage = authority[1]
    mapped: dict = {
        "event_id": event_id,
        "metadata": {"evidence_status": "server_observed", "source_event_id": event_id,
                     "source_topic": topic, "source_service": event.source_service},
    }
    if stage == "x402_payment_required":
        challenge_id = str(payload.get("challenge_id") or "")
        requirement = await store.get_requirement(tenant_id, challenge_id) if challenge_id else None
        if requirement is None:
            return
        mapped.update({
            "payment_intent_id": requirement.challenge_id,
            "agent_id": requirement.requester_id if requirement.requester_type == "agent" else "",
            "amount": str(requirement.amount_usd), "currency": requirement.asset_symbol,
            "provider": "x402", "protocol": requirement.protocol_version,
            "resource_id": requirement.resource_id,
            "timestamp": requirement.issued_at,
        })
    elif stage == "x402_payment_submitted":
        auth_id = str(payload.get("authorization_id") or "")
        auth = await store.get_authorization(tenant_id, auth_id) if auth_id else None
        requirement = await store.get_requirement(tenant_id, auth.challenge_id) if auth else None
        if auth is None or requirement is None:
            return
        mapped.update({
            "payment_intent_id": requirement.challenge_id,
            "settlement_event_id": event_id,
            "agent_id": requirement.requester_id if requirement.requester_type == "agent" else "",
            "amount": str(auth.amount_usd), "currency": auth.asset_symbol,
            "provider": "x402", "protocol": "x402-v2", "tx_hash": payload.get("tx_hash"),
        })
    elif stage in ("x402_payment_settled", "x402_payment_failed"):
        settlement_id = str(payload.get("settlement_id") or "")
        settlement = await store.get_settlement(tenant_id, settlement_id) if settlement_id else None
        requirement = await store.get_requirement(tenant_id, settlement.challenge_id) if settlement else None
        if settlement is None or requirement is None:
            return
        mapped.update({
            "payment_intent_id": requirement.challenge_id,
            "settlement_event_id": settlement.settlement_id,
            "agent_id": requirement.requester_id if requirement.requester_type == "agent" else "",
            "amount": str(settlement.amount_usd), "currency": requirement.asset_symbol,
            "provider": "x402", "protocol": requirement.protocol_version,
            "tx_hash": settlement.tx_hash,
            "timestamp": settlement.updated_at,
        })
    else:  # access granted
        entitlement_id = str(payload.get("entitlement_id") or "")
        entitlement = await store.get_entitlement(tenant_id, entitlement_id) if entitlement_id else None
        settlement = await store.get_settlement(tenant_id, entitlement.settlement_id) if entitlement else None
        mapped.update({"payment_intent_id": getattr(settlement, "challenge_id", "")})
        if not mapped["payment_intent_id"]:
            return

    from services.x402.lifecycle_mapper import X402LifecycleMapper
    result = await X402LifecycleMapper().handle_event(stage, mapped, tenant_id)
    if mapped.get("agent_id") and mapped.get("payment_intent_id"):
        # The repositories remain the source of truth; this is an additive
        # projection into the existing PaymentIntent/SettlementEvent graph
        # types. Client SDK claims never enter this graph writer.
        from repositories.repos import PaymentIntentRepository, SettlementEventRepository
        from services.x402.economic_mutations import EconomicGraphMutations

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

