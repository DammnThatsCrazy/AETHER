"""Aether SDK — heartbeat and identity lifecycle routes (blueprint §14).

Extends the existing SDK routes with:
- heartbeat (source identity creation)
- alias (anonymous-to-known binding)
- reset (clear local anonymous context)
- setConsent (update consent state)
- batch ingestion with source identity + claim extraction
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, utc_now
from shared.cache.cache import CacheClient, TTL
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger
from dependencies.providers import get_cache, get_producer
from services.identity.integration import IdentityIngestionWire
from services.identity.repository import IdentityResolutionRepository
from services.identity.source_identity_registry import SourceIdentityRegistry

logger = get_logger("aether.service.sdk.lifecycle")

router_lifecycle = APIRouter(prefix="/sdk", tags=["SDK-Lifecycle"])


# ── Models ────────────────────────────────────────────────────────────

class HeartbeatRequest(BaseModel):
    sdk_name: str = Field(..., description="SDK name (aether-web, aether-ios, etc.)")
    sdk_version: str = Field(..., description="SDK version string")
    tenant_app_key: str = Field(..., description="Tenant/app key")
    anonymous_id: Optional[str] = Field(None, description="Current anonymous ID")
    installation_id: Optional[str] = Field(None, description="Mobile installation ID")
    device_id: Optional[str] = Field(None, description="Device ID")
    session_id: Optional[str] = Field(None, description="Session ID")
    consent_state: Optional[dict] = Field(None, description="Current consent state")
    idempotency_key: Optional[str] = Field(None, description="Idempotency key for retry")


class HeartbeatResponse(BaseModel):
    received: bool
    source_identity_id: Optional[str] = None
    anonymous_id: Optional[str] = None
    received_at: str


class AliasRequest(BaseModel):
    previous_id: str = Field(..., description="Previous anonymous ID")
    user_id: str = Field(..., description="New user ID")
    tenant_app_key: str = Field(..., description="Tenant/app key")
    sdk_name: str = Field(default="aether-web", description="SDK name")
    sdk_version: str = Field(default="1.0.0", description="SDK version")
    idempotency_key: Optional[str] = Field(None, description="Idempotency key")


class AliasResponse(BaseModel):
    aliased: bool
    previous_id: str
    user_id: str
    source_identity_id: Optional[str] = None
    resolution_outcome: Optional[str] = None


class ResetRequest(BaseModel):
    tenant_app_key: str = Field(..., description="Tenant/app key")
    anonymous_id: str = Field(..., description="Current anonymous ID to clear")
    idempotency_key: Optional[str] = Field(None, description="Idempotency key")


class ResetResponse(BaseModel):
    reset: bool
    anonymous_id: str
    cleared_at: str


class SetConsentRequest(BaseModel):
    tenant_app_key: str = Field(..., description="Tenant/app key")
    anonymous_id: Optional[str] = Field(None, description="Current anonymous ID")
    user_id: Optional[str] = Field(None, description="Current user ID")
    consent_state: dict = Field(..., description="Consent state {purposes: {purpose: bool}}")
    idempotency_key: Optional[str] = Field(None, description="Idempotency key")


class SetConsentResponse(BaseModel):
    consent_updated: bool
    anonymous_id: Optional[str] = None
    user_id: Optional[str] = None


class IdentifyRequest(BaseModel):
    """identify() call from SDK — binds anonymous to known user."""
    tenant_app_key: str = Field(..., description="Tenant/app key")
    user_id: str = Field(..., description="User ID to identify as")
    anonymous_id: Optional[str] = Field(None, description="Previous anonymous ID")
    traits: Optional[dict] = Field(None, description="User traits: {email, phone, name, ...}")
    sdk_name: str = Field(default="aether-web", description="SDK name")
    sdk_version: str = Field(default="1.0.0", description="SDK version")
    consent_state: Optional[dict] = Field(None, description="Consent state")


class IdentifyResponse(BaseModel):
    identified: bool
    user_id: str
    anonymous_id: Optional[str] = None
    resolution_outcome: Optional[str] = None
    canonical_entity_id: Optional[str] = None
    confidence: Optional[float] = None
    requires_restatement: bool = False


# ── Routes ────────────────────────────────────────────────────────────

@router_lifecycle.post("/heartbeat", response_model=HeartbeatResponse)
async def sdk_heartbeat(
    body: HeartbeatRequest,
    request: Request,
    cache: CacheClient = Depends(get_cache),
    producer: EventProducer = Depends(get_producer),
):
    """SDK heartbeat — creates/updates source identity for the SDK instance.

    Blueprint §14.1, §7.2: heartbeat received → source system validated →
    anonymous source identity created/updated.
    """
    tenant = request.state.tenant
    tenant_id = tenant.tenant_id

    now_iso = utc_now().isoformat()

    # Track SDK health
    await cache.incr(f"sdk.heartbeat:{tenant_id}:{body.sdk_name}", 1)

    # Determine source identity identifiers
    source_kind = "web_sdk" if body.sdk_name in ("aether-web", "aether-react") else "mobile_sdk"
    source_namespace = f"{body.sdk_name}:{body.tenant_app_key}"

    # Build source identity record
    source_identity_id = None
    identifiers = {}

    if body.anonymous_id:
        identifiers["anonymous_id"] = body.anonymous_id
    if body.installation_id:
        identifiers["installation_id"] = body.installation_id
    if body.device_id:
        identifiers["device_id"] = body.device_id
    if body.session_id:
        identifiers["session_id"] = body.session_id

    # Emit heartbeat metric + observability trace
    from services.identity.observability import IdentityTrace, identity_metrics

    identity_metrics.record_sdk_heartbeat()
    trace = IdentityTrace(tenant_id=tenant_id, source_system_id=source_namespace)
    trace.ingestion_receive()

    # Create source identity via SourceIdentityRegistry (identity continuity runtime)
    try:
        repo = IdentityResolutionRepository()
        registry = SourceIdentityRegistry(repo)
        wire = IdentityIngestionWire(registry)
        normalized_for_identity = {
            "anonymous_id": body.anonymous_id,
            "installation_id": body.installation_id,
            "device_id": body.device_id,
            "session_id": body.session_id,
            "sdk_name": body.sdk_name,
            "source_namespace": source_namespace,
            "idempotency_key": body.idempotency_key,
        }
        rec = await wire.extract_and_register_from_sdk_event(
            tenant_id=tenant_id,
            source_system_id=source_namespace,
            normalized_event=normalized_for_identity,
        )
        if rec is not None:
            source_identity_id = rec.id
            trace.source_identity_register(source_identity_id)
            identity_metrics.record_source_identity_created()
        elif identifiers:
            # Fallback: direct registration when extract returns None (e.g. missing anonymous_id)
            rec2 = await wire.ensure_source_identity(
                tenant_id=tenant_id,
                source_system_id=source_namespace,
                source_kind=source_kind,
                source_namespace=source_namespace,
                anonymous_id=body.anonymous_id,
                installation_id=body.installation_id,
                device_id=body.device_id,
                session_id=body.session_id,
                idempotency_key=body.idempotency_key,
            )
            source_identity_id = rec2.id
            trace.source_identity_register(source_identity_id)
            identity_metrics.record_source_identity_created()
    except Exception as e:
        logger.warning("sdk.heartbeat.source_identity_failed: %s", e)

    logger.info(
        "sdk.heartbeat.received",
        extra={
            "tenant_id": tenant_id,
            "sdk_name": body.sdk_name,
            "sdk_version": body.sdk_version,
            "source_namespace": source_namespace,
            "has_anonymous_id": bool(body.anonymous_id),
            "has_installation_id": bool(body.installation_id),
        },
    )

    return HeartbeatResponse(
        received=True,
        source_identity_id=source_identity_id,
        anonymous_id=body.anonymous_id,
        received_at=now_iso,
    )


@router_lifecycle.post("/identify", response_model=IdentifyResponse)
async def sdk_identify(
    body: IdentifyRequest,
    request: Request,
    cache: CacheClient = Depends(get_cache),
    producer: EventProducer = Depends(get_producer),
):
    """SDK identify() call — binds anonymous to known user.

    Blueprint §14.3, §7.3: identify call received → user source identity created →
    identity claims extracted → resolver checks imported identities →
    safe match auto-merges, unsafe match creates conflict/review.

    The SDK must NOT decide the canonical profile — the backend resolves.
    """
    tenant = request.state.tenant
    tenant_id = tenant.tenant_id

    now_iso = utc_now().isoformat()

    # Build source identity for the user
    source_kind = "web_sdk" if body.sdk_name in ("aether-web", "aether-react") else "mobile_sdk"
    source_namespace = f"{body.sdk_name}:{body.tenant_app_key}"

    # Extract identity claims from traits
    claims = []
    if body.traits:
        if "email" in body.traits:
            claims.append({
                "claim_type": "email",
                "value": body.traits["email"],
                "verification_status": "unknown",
                "pii_classification": "sensitive",
            })
        if "phone" in body.traits:
            claims.append({
                "claim_type": "phone",
                "value": body.traits["phone"],
                "verification_status": "unknown",
                "pii_classification": "sensitive",
            })
        if "name" in body.traits:
            claims.append({
                "claim_type": "name",
                "value": body.traits["name"],
                "verification_status": "unknown",
                "pii_classification": "moderate",
            })

    # Track identify metric + source identity continuity
    from services.identity.observability import IdentityTrace, identity_metrics

    identity_metrics.record_sdk_identify()
    trace = IdentityTrace(tenant_id=tenant_id, source_system_id=source_namespace)
    trace.ingestion_receive()

    # Source identity: create via SourceIdentityRegistry (identity continuity runtime)
    _identify_source_identity_id = None
    try:
        _repo = IdentityResolutionRepository()
        _registry = SourceIdentityRegistry(_repo)
        _wire = IdentityIngestionWire(_registry)
        _source_ns = source_namespace
        _normalized_identify = {
            "anonymous_id": body.anonymous_id,
            "user_id": body.user_id,
            "sdk_name": body.sdk_name,
            "source_namespace": _source_ns,
        }
        _rec = await _wire.extract_and_register_from_sdk_event(
            tenant_id=tenant_id,
            source_system_id=_source_ns,
            normalized_event=_normalized_identify,
        )
        if _rec is not None:
            _identify_source_identity_id = _rec.id
            trace.source_identity_register(_identify_source_identity_id)
            identity_metrics.record_source_identity_created()
        else:
            _rec2 = await _wire.ensure_source_identity(
                tenant_id=tenant_id,
                source_system_id=_source_ns,
                source_kind=source_kind,
                source_namespace=source_namespace,
                anonymous_id=body.anonymous_id,
                user_id=body.user_id,
                idempotency_key=None,
            )
            _identify_source_identity_id = _rec2.id
            trace.source_identity_register(_identify_source_identity_id)
            identity_metrics.record_source_identity_created()
        # Also store identity claims from traits for the source identity
        if _identify_source_identity_id and body.traits:
            for claim in claims:
                try:
                    await _registry.upsert_identity_claim(
                        tenant_id=tenant_id,
                        source_identity_id=_identify_source_identity_id,
                        claim_type=claim["claim_type"],
                        raw_value=claim["value"],
                        verification_status=claim.get("verification_status", "observed"),
                        pii_classification=claim.get("pii_classification", "none"),
                    )
                    if hasattr(identity_metrics, "record_claim_created"):
                        identity_metrics.record_claim_created()
                except Exception:
                    pass
    except Exception as e:
        logger.warning("sdk.identify.source_identity_failed: %s", e)

    logger.info(
        "sdk.identify.received",
        extra={
            "tenant_id": tenant_id,
            "user_id": body.user_id[:8] if body.user_id else None,
            "has_anonymous_id": bool(body.anonymous_id),
            "has_traits": bool(body.traits),
            "traits_keys": list(body.traits.keys()) if body.traits else [],
        },
    )

    # Emit IDENTITY_RESOLVED event for downstream processing
    if producer:
        await producer.publish(Event(
            topic=Topic.IDENTITY_RESOLVED,
            payload={
                "tenant_id": tenant_id,
                "source_system": source_namespace,
                "user_id": body.user_id,
                "anonymous_id": body.anonymous_id,
                "claim_count": len(claims),
                "sdk_name": body.sdk_name,
                "sdk_version": body.sdk_version,
                "consent_state": body.consent_state,
                "occurred_at": now_iso,
            },
        ))

    # Resolution outcome — would be determined by the resolver in production
    # For now, return the identify confirmation
    return IdentifyResponse(
        identified=True,
        user_id=body.user_id,
        anonymous_id=body.anonymous_id,
        resolution_outcome="pending_resolution",
        canonical_entity_id=None,
        confidence=None,
        requires_restatement=False,
    )


@router_lifecycle.post("/alias", response_model=AliasResponse)
async def sdk_alias(
    body: AliasRequest,
    request: Request,
    cache: CacheClient = Depends(get_cache),
):
    """SDK alias() call — binds previousId to userId (backward compatibility).

    Blueprint §14.1: alias(previousId, userId) — binds anonymous history to known user.
    """
    tenant = request.state.tenant
    tenant_id = tenant.tenant_id

    now_iso = utc_now().isoformat()

    logger.info(
        "sdk.alias.received",
        extra={
            "tenant_id": tenant_id,
            "previous_id": body.previous_id[:8] if body.previous_id else None,
            "user_id": body.user_id[:8] if body.user_id else None,
        },
    )

    # Source identity continuity: alias creates/updates source identity binding anonymous→known
    source_identity_id = None
    try:
        from services.identity.observability import IdentityTrace, identity_metrics

        trace = IdentityTrace(tenant_id=tenant_id, source_system_id=f"{body.sdk_name}:{body.tenant_app_key}")
        trace.ingestion_receive()
        repo = IdentityResolutionRepository()
        registry = SourceIdentityRegistry(repo)
        wire = IdentityIngestionWire(registry)
        source_ns = f"{body.sdk_name}:{body.tenant_app_key}"
        source_kind = "web_sdk" if body.sdk_name in ("aether-web", "aether-react") else "mobile_sdk"
        # Use previous_id as anonymous_id and user_id as known binding
        rec = await wire.ensure_source_identity(
            tenant_id=tenant_id,
            source_system_id=source_ns,
            source_kind=source_kind,
            source_namespace=source_ns,
            anonymous_id=body.previous_id,
            user_id=body.user_id,
            idempotency_key=body.idempotency_key,
        )
        source_identity_id = rec.id
        trace.source_identity_register(source_identity_id)
        identity_metrics.record_source_identity_created()
    except Exception as e:
        logger.warning("sdk.alias.source_identity_failed: %s", e)

    return AliasResponse(
        aliased=True,
        previous_id=body.previous_id,
        user_id=body.user_id,
        source_identity_id=source_identity_id,
        resolution_outcome="pending_resolution",
    )


@router_lifecycle.post("/reset", response_model=ResetResponse)
async def sdk_reset(
    body: ResetRequest,
    request: Request,
    cache: CacheClient = Depends(get_cache),
):
    """SDK reset() call — clears local anonymous context.

    Blueprint §14.1: reset() clears local anonymous context.
    Shared device handling: after reset, a new anonymous_id is generated,
    preventing automatic merge of different users on the same device.
    """
    tenant = request.state.tenant
    tenant_id = tenant.tenant_id

    now_iso = utc_now().isoformat()

    logger.info(
        "sdk.reset.received",
        extra={
            "tenant_id": tenant_id,
            "anonymous_id": body.anonymous_id[:8] if body.anonymous_id else None,
        },
    )

    # Clear any cached anonymous context
    if body.anonymous_id:
        await cache.delete(f"anon:{tenant_id}:{body.anonymous_id}")

    return ResetResponse(
        reset=True,
        anonymous_id=body.anonymous_id,
        cleared_at=now_iso,
    )


@router_lifecycle.post("/consent", response_model=SetConsentResponse)
async def sdk_set_consent(
    body: SetConsentRequest,
    request: Request,
    cache: CacheClient = Depends(get_cache),
):
    """SDK setConsent() call — updates consent state.

    Blueprint §20.2: consent status checked before resolution.
    Revoked consent blocks future merge. Deleted identity cannot resolve.
    """
    tenant = request.state.tenant
    tenant_id = tenant.tenant_id

    now_iso = utc_now().isoformat()

    logger.info(
        "sdk.consent.updated",
        extra={
            "tenant_id": tenant_id,
            "anonymous_id": body.anonymous_id[:8] if body.anonymous_id else None,
            "user_id": body.user_id[:8] if body.user_id else None,
            "consent_purposes": list(body.consent_state.get("purposes", {}).keys()),
        },
    )

    # Store consent state in cache for resolution checks
    if body.anonymous_id:
        await cache.set_json(
            f"consent:{tenant_id}:{body.anonymous_id}",
            {"state": body.consent_state, "updated_at": now_iso},
            TTL.DAY,
        )
    if body.user_id:
        await cache.set_json(
            f"consent:{tenant_id}:{body.user_id}",
            {"state": body.consent_state, "updated_at": now_iso},
            TTL.DAY,
        )

    return SetConsentResponse(
        consent_updated=True,
        anonymous_id=body.anonymous_id,
        user_id=body.user_id,
    )


@router_lifecycle.get("/health", response_model=dict)
async def sdk_health(
    request: Request,
    cache: CacheClient = Depends(get_cache),
):
    """SDK health check — returns SDK status, heartbeat counts, and manifest diagnostics."""
    tenant = request.state.tenant
    tenant_id = tenant.tenant_id

    from services.identity.observability import identity_metrics

    # Manifest diagnostic counters from cache
    manifest_healthy = int(await cache.get(f"sdk.manifest_healthy:{tenant_id}", default=0))
    manifest_forbidden = int(await cache.get(f"sdk.manifest_forbidden:{tenant_id}", default=0))
    manifest_expired = int(await cache.get(f"sdk.manifest_expired:{tenant_id}", default=0))
    manifest_signature_invalid = int(await cache.get(f"sdk.manifest_signature_invalid:{tenant_id}", default=0))
    manifest_unavailable = int(await cache.get(f"sdk.manifest_unavailable:{tenant_id}", default=0))
    local_fallback_active = int(await cache.get(f"sdk.local_fallback:{tenant_id}", default=0))

    return {
        "status": "healthy",
        "tenant_id": tenant_id,
        "sdk_heartbeats": identity_metrics.sdk_heartbeat_received,
        "sdk_identifies": identity_metrics.sdk_identify_received,
        "manifest": {
            "healthy": manifest_healthy,
            "forbidden": manifest_forbidden,
            "expired": manifest_expired,
            "signature_invalid": manifest_signature_invalid,
            "unavailable": manifest_unavailable,
            "local_fallback_active": local_fallback_active,
        },
        "timestamp": utc_now().isoformat(),
    }
