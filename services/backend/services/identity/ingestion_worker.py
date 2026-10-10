"""Durable SDK observation to canonical identity resolution worker.

Every accepted SDK event is delivered on ``SDK_EVENTS_VALIDATED`` after V1
publish or the V2 transactional outbox relay. This worker registers the
source-scoped observation first, then sends the same normalized evidence to the
canonical resolver. Broker retries are safe because source identities, claims,
aliases, and event observations are idempotent on their source event identity.
"""

from __future__ import annotations

from typing import Any

from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.identity.ingestion_worker")


def _first(mapping: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = mapping.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


async def resolve_sdk_observation(event: Event, producer: EventProducer) -> None:
    """Register and resolve one accepted identity-bearing SDK observation.

    Errors deliberately propagate to the stream consumer so its configured
    retry/DLQ policy owns recovery. Request handlers only acknowledge durable
    Bronze/outbox work and never start resolver tasks.
    """
    from config.settings import settings

    if not settings.identity_continuity.resolution_enabled:
        return

    payload = dict(event.payload or {})
    from services.ingestion.workers import _defer_provider_canonical

    if _defer_provider_canonical(event, "identity_resolution"):
        return

    tenant_id = str(event.tenant_id or payload.get("tenant_id") or "").strip()
    event_id = str(payload.get("event_id") or "").strip()
    if not tenant_id or not event_id:
        logger.warning("identity observation missing tenant or event id")
        return

    context = dict(payload.get("context") or {})
    properties = dict(payload.get("properties") or {})
    event_type = str(payload.get("event_type") or "")
    user_id = _first(payload, "user_id", "userId")
    anonymous_id = _first(payload, "anonymous_id", "anonymousId")
    session_id = _first(payload, "session_id", "sessionId")
    device_context = context.get("device") if isinstance(context.get("device"), dict) else {}
    application_context = (
        context.get("application")
        if isinstance(context.get("application"), dict)
        else {}
    )
    device_id = _first(properties, "device_id", "deviceId") or _first(
        device_context, "id", "device_id", "deviceId"
    )
    installation_id = _first(properties, "installation_id", "installationId") or _first(
        application_context, "installation_id", "installationId"
    )
    account_id = _first(properties, "account_id", "accountId") or _first(
        context, "orgId", "tenantId"
    )
    namespace = str(context.get("identity_namespace") or f"tenant:{tenant_id}")

    wallet_address = _first(properties, "wallet_address", "walletAddress", "address")
    has_source_identity = any((user_id, anonymous_id, device_id, installation_id))

    # A wallet-only SDK observation is registered as an unresolved wallet
    # source identity. Its hash is tenant and chain/VM scoped, and it is never
    # promoted into a human profile: connect context does not prove ownership.
    if not has_source_identity and wallet_address:
        from services.identity.hashing import hash_value
        from services.identity.normalization import (
            extract_chain_namespace,
            normalize_wallet_address,
        )
        from services.identity.routes import get_identity_resolver
        from services.identity.source_identity_registry import SourceIdentityRegistry

        chain_namespace = extract_chain_namespace(properties)
        normalized_wallet = normalize_wallet_address(wallet_address, chain_namespace)
        if normalized_wallet:
            resolver = get_identity_resolver()
            repo = getattr(resolver, "_repo", None)
            if repo is None:
                raise RuntimeError("canonical identity repository is unavailable")
            registry = SourceIdentityRegistry(repo)
            wallet_scope = f"{namespace}:wallet:{chain_namespace}"
            wallet_external_id = hash_value(
                normalized_wallet,
                scope=f"wallet:{tenant_id}:{chain_namespace}",
            )
            await registry.register_source_identity(
                tenant_id=tenant_id,
                source_system_id="aether-sdk",
                source_kind="sdk_wallet",
                source_namespace=wallet_scope,
                external_id=wallet_external_id,
                idempotency_key=f"{tenant_id}:{event_id}:wallet-source-v1",
                source_record_id=event_id,
            )
        return

    # Events without a stable identity-bearing identifier remain immutable
    # observations in Bronze and do not manufacture a person.
    if not has_source_identity:
        return

    if event_type == "identify" and (
        not settings.identity_continuity.sdk_late_binding_enabled
        or (
            anonymous_id
            and user_id
            and not settings.identity_continuity.anonymous_to_known_binding_enabled
        )
    ):
        return

    from services.identity.routes import get_identity_resolver
    from services.identity.source_identity_registry import SourceIdentityRegistry

    resolver = get_identity_resolver()
    repo = getattr(resolver, "_repo", None)
    if repo is None:
        raise RuntimeError("canonical identity repository is unavailable")
    registry = SourceIdentityRegistry(repo)
    source = await registry.register_source_identity(
        tenant_id=tenant_id,
        source_system_id="aether-sdk",
        source_kind="sdk",
        source_namespace=namespace,
        anonymous_id=anonymous_id,
        user_id=user_id,
        device_id=device_id,
        installation_id=installation_id,
        session_id=session_id,
        account_id=account_id,
        idempotency_key=f"{tenant_id}:{event_id}:identity-v1",
        source_record_id=event_id,
    )

    # Keep source claims in the registry with tenant-keyed hashes. The resolver
    # receives the original accepted envelope and applies its own signal policy;
    # these claim records preserve provenance without storing raw email/phone.
    for claim_type in ("email", "phone"):
        claim_value = _first(properties, claim_type)
        if claim_value:
            await registry.upsert_identity_claim(
                tenant_id=tenant_id,
                source_identity_id=source.id,
                claim_type=claim_type,
                raw_value=claim_value,
                verification_status="observed",
                occurred_at=payload.get("timestamp"),
                source_record_id=event_id,
                hash_sensitive_value=True,
            )

    from services.identity.schemas import IdentityResolveRequest

    request = IdentityResolveRequest(
        event_id=event_id,
        tenant_id=tenant_id,
        user_id=user_id,
        anonymous_id=anonymous_id,
        session_id=session_id,
        email=_first(properties, "email"),
        phone=_first(properties, "phone"),
        wallet_address=wallet_address,
        external_id=_first(properties, "external_id", "customer_id"),
        agent_id=_first(payload, "agent_id") or _first(properties, "agent_id"),
        org_id=_first(context, "orgId", "tenantId"),
        properties=properties,
        context=context,
    )
    resolution_event = request.model_dump()
    # Private worker-only field: public resolver routes cannot supply or
    # override the source identity's current canonical owner.
    if source.canonical_entity_id:
        resolution_event["_source_canonical_entity_id"] = source.canonical_entity_id
    decision = await resolver.resolve_event(resolution_event, tenant_id)
    canonical_entity_id = str(getattr(decision, "canonical_entity_id", "") or "")
    outcome = str(getattr(getattr(decision, "decision", None), "value", ""))
    reason_codes = list(getattr(decision, "reason_codes", []) or [])
    if "internal_error" in reason_codes:
        # The resolver converts unexpected infrastructure errors into NOOP.
        # Propagate that failure so the broker retries instead of acknowledging
        # a delivery whose canonical decision did not run.
        raise RuntimeError("canonical identity resolver reported an internal error")
    owner_outcomes = {"create", "link", "merge", "noop"}

    if canonical_entity_id and outcome in owner_outcomes:
        source.canonical_entity_id = canonical_entity_id
        source.status = "resolved"
        await repo.update_source_identity(source)
        await _invalidate_activity_queries(tenant_id)
        resolution_event = Event(
            topic=Topic.IDENTITY_RESOLVED,
            tenant_id=tenant_id,
            source_service="identity.ingestion_worker",
            correlation_id=event.correlation_id,
            payload={
                "tenant_id": tenant_id,
                "event_id": event_id,
                "source_identity_id": source.id,
                "canonical_entity_id": canonical_entity_id,
                "resolution_outcome": outcome,
                "reason_codes": list(getattr(decision, "reason_codes", []) or []),
                "policy_version": getattr(decision, "policy_version", None),
            },
        )
        await producer.publish(resolution_event)
    else:
        if not source.canonical_entity_id:
            if canonical_entity_id and bool(getattr(decision, "is_new_entity", False)):
                # The resolver created this event's own entity rather than
                # selecting an existing candidate; it is safe to retain as a
                # provisional source owner even when policy requests review.
                source.canonical_entity_id = canonical_entity_id
            else:
                source.canonical_entity_id = await registry.ensure_provisional_profile(
                    tenant_id=tenant_id,
                    source_identity_id=source.id,
                )
            source.status = (
                "review_required"
                if outcome in {"candidate", "conflict", "review_required"}
                else "provisional"
            )
            await repo.update_source_identity(source)
        elif outcome in {"candidate", "conflict", "review_required"}:
            source.status = "review_required"
            await repo.update_source_identity(source)
        # The resolver can return an existing candidate ID for review. Activity
        # remains owned by this source's provisional profile until policy
        # authorizes the link; do not expose ambiguous history on that candidate.
        if source.canonical_entity_id:
            await repo.set_observations_canonical_entity(
                tenant_id, event_id, str(source.canonical_entity_id)
            )
            await _invalidate_activity_queries(tenant_id)

    metrics.increment(
        "identity_resolution_worker_processed_total",
        labels={"outcome": outcome or "unknown"},
    )


async def _invalidate_activity_queries(tenant_id: str) -> None:
    """Retire analytics timeline cache after event ownership is assigned."""
    from dependencies.providers import get_cache
    from repositories.repos import AnalyticsRepository

    await AnalyticsRepository(get_cache()).invalidate_query_cache(tenant_id)
