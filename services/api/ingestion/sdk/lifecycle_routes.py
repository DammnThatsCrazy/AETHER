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
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, utc_now
from shared.cache.cache import CacheClient, TTL
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger
from dependencies.providers import get_cache, get_producer
from identity.identity.integration import IdentityIngestionWire
from identity.identity.repository import IdentityResolutionRepository
from identity.identity.source_identity_registry import SourceIdentityRegistry

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
    canonical_entity_id: Optional[str] = None


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
    idempotency_key: str = Field(..., min_length=1, max_length=255, description="Tenant-scoped retry key")


class IdentifyResponse(BaseModel):
    identified: bool
    user_id: str
    anonymous_id: Optional[str] = None
    resolution_outcome: Optional[str] = None
    canonical_entity_id: Optional[str] = None
    confidence: Optional[float] = None
    reason_codes: list[str] = Field(default_factory=list)
    resolution_event_publish_succeeded: Optional[bool] = Field(
        None,
        description="Whether the producer publish call returned successfully; not a durable delivery receipt",
    )
    requires_restatement: bool = False
    idempotency_status: str = Field(
        "completed", description="completed, replayed, in_progress, or stale"
    )


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

    authorized_site_ids = getattr(tenant, "site_ids", None)
    if authorized_site_ids is not None and body.tenant_app_key not in authorized_site_ids:
        raise HTTPException(status_code=403, detail="SDK app is not authorized for this credential")

    now_iso = utc_now().isoformat()

    # Persist only tenant/app/SDK metadata for activation status. User, device,
    # installation, and session identifiers remain in the identity registry
    # only after current server-authoritative identity-link consent is present.
    from repositories.sdk_heartbeat_status import get_sdk_heartbeat_status_repository

    await get_sdk_heartbeat_status_repository().record(
        tenant_id=tenant_id,
        sdk_name=body.sdk_name,
        tenant_app_key=body.tenant_app_key,
        sdk_version=body.sdk_version,
        received_at=utc_now(),
    )

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
    from identity.identity.observability import IdentityTrace, identity_metrics

    identity_metrics.record_sdk_heartbeat()
    trace = IdentityTrace(
        tenant_id=tenant_id,
        source_system_id=source_namespace,
        correlation_id=body.idempotency_key,
    )
    trace.ingestion_receive()

    # Create source identity via SourceIdentityRegistry only after server-side
    # consent. Client consent_state is only a hint and cannot authorize storage.
    try:
        from governance.consent.authority import evaluate_identity_link_consent

        consent_allowed, _, _ = await evaluate_identity_link_consent(
            tenant_id, body.anonymous_id
        )
        if consent_allowed:
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
        logger.warning(
            "sdk.heartbeat.source_identity_failed",
            extra={"tenant_id": tenant_id, "error_type": type(e).__name__},
        )

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
    """Claim a durable retry key before running identify side effects."""
    tenant_id = request.state.tenant.tenant_id
    key = body.idempotency_key.strip()
    if not key:
        raise HTTPException(status_code=422, detail="idempotency_key must not be blank")
    payload = body.dict(exclude={"idempotency_key"})
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    from repositories.sdk_identify_idempotency import get_sdk_identify_idempotency_repository

    idempotency = get_sdk_identify_idempotency_repository()
    claim = await idempotency.claim(tenant_id, key, fingerprint)
    if claim["status"] == "conflict":
        raise HTTPException(status_code=409, detail="Idempotency key reused with a different identify payload")
    if claim["status"] == "replay":
        replay_fields = dict(claim["response"])
        replay_fields.pop("identified", None)
        return IdentifyResponse(
            identified=True,
            user_id=body.user_id,
            anonymous_id=body.anonymous_id,
            **replay_fields,
            idempotency_status="replayed",
        )
    if claim["status"] == "in_progress":
        return IdentifyResponse(
            identified=True,
            user_id=body.user_id,
            anonymous_id=body.anonymous_id,
            resolution_outcome="pending_resolution",
            reason_codes=["idempotent_request_in_progress"],
            resolution_event_publish_succeeded=None,
            requires_restatement=False,
            idempotency_status="in_progress",
        )
    if claim["status"] == "stale":
        return IdentifyResponse(
            identified=True,
            user_id=body.user_id,
            anonymous_id=body.anonymous_id,
            resolution_outcome="pending_resolution",
            reason_codes=["idempotent_request_stale_reconciliation_required"],
            resolution_event_publish_succeeded=None,
            requires_restatement=False,
            idempotency_status="stale",
        )
    if claim["status"] != "claimed":
        raise HTTPException(status_code=503, detail="Unable to claim identify idempotency key")

    response = await _execute_sdk_identify(body, request, cache=cache, producer=producer)
    safe_response = response.dict(exclude={"user_id", "anonymous_id", "idempotency_status"})
    try:
        completed = await idempotency.complete(
            tenant_id, key, claim["claim_token"], safe_response
        )
    except Exception as exc:
        logger.error(
            "sdk.identify.idempotency_completion_failed",
            extra={"tenant_id": tenant_id, "error_type": type(exc).__name__},
        )
        completed = False
    if not completed:
        # Side effects may already have committed. The durable pending claim
        # prevents a retry from executing them a second time.
        raise HTTPException(status_code=503, detail="Identify outcome is pending; retry with the same idempotency key")
    response.idempotency_status = "completed"
    return response


async def _execute_sdk_identify(
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
    from config.settings import settings

    # Publishable SDK credentials carry durable site bindings in the
    # authenticated tenant context. Never accept a caller-selected app scope
    # that is outside that allowlist; private tenant credentials may be
    # intentionally unscoped and still operate within their tenant boundary.
    authorized_site_ids = getattr(tenant, "site_ids", None)
    if authorized_site_ids is not None and body.tenant_app_key not in authorized_site_ids:
        return IdentifyResponse(
            identified=True,
            user_id=body.user_id,
            anonymous_id=body.anonymous_id,
            resolution_outcome="blocked",
            canonical_entity_id=None,
            reason_codes=["sdk_app_not_authorized"],
            resolution_event_publish_succeeded=None,
            requires_restatement=False,
        )

    identity_flags = settings.identity_continuity
    if not identity_flags.resolution_enabled:
        return IdentifyResponse(
            identified=True,
            user_id=body.user_id,
            anonymous_id=body.anonymous_id,
            resolution_outcome="blocked",
            canonical_entity_id=None,
            reason_codes=["identity_resolution_disabled"],
            resolution_event_publish_succeeded=None,
            requires_restatement=False,
        )
    if not identity_flags.sdk_late_binding_enabled:
        return IdentifyResponse(
            identified=True,
            user_id=body.user_id,
            anonymous_id=body.anonymous_id,
            resolution_outcome="blocked",
            canonical_entity_id=None,
            reason_codes=["sdk_late_binding_disabled"],
            resolution_event_publish_succeeded=None,
            requires_restatement=False,
        )
    # Refuse to persist even provisional source bindings or trait claims until
    # the server has current identity-link consent for this anonymous subject.
    # Client consent snapshots and the supplied user_id are not authorization.
    server_consent_context = None
    consent_reason = "consent_receipt_missing"
    try:
        from governance.consent.authority import evaluate_identity_link_consent

        consent_allowed, consent_reason, server_consent_context = (
            await evaluate_identity_link_consent(tenant_id, body.anonymous_id)
        )
    except Exception as exc:
        logger.warning(
            "sdk.identify.identity_link_consent_lookup_failed",
            extra={"tenant_id": tenant_id, "error_type": type(exc).__name__},
        )
        consent_allowed = False
        consent_reason = "identity_link_consent_lookup_failed"
    if not consent_allowed:
        publish_succeeded = None
        if producer:
            try:
                await producer.publish(Event(
                    topic=Topic.RESOLUTION_EVALUATED,
                    payload={
                        "tenant_id": tenant_id,
                        "source_system": f"{body.sdk_name}:{body.tenant_app_key}",
                        "source_identity_id": None,
                        "claim_count": 0,
                        "sdk_name": body.sdk_name,
                        "sdk_version": body.sdk_version,
                        "resolution_outcome": "blocked",
                        "canonical_entity_id": None,
                        "confidence": None,
                        "reason_codes": ["identity_link_consent_required", consent_reason],
                        "occurred_at": utc_now().isoformat(),
                    },
                ))
                publish_succeeded = True
            except Exception as exc:
                logger.warning(
                    "sdk.identify.event_publish_failed",
                    extra={"tenant_id": tenant_id, "error_type": type(exc).__name__},
                )
                publish_succeeded = False
        return IdentifyResponse(
            identified=True,
            user_id=body.user_id,
            anonymous_id=body.anonymous_id,
            resolution_outcome="blocked",
            canonical_entity_id=None,
            reason_codes=["identity_link_consent_required", consent_reason],
            resolution_event_publish_succeeded=publish_succeeded,
            requires_restatement=False,
        )

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
    from identity.identity.observability import IdentityTrace, identity_metrics

    identity_metrics.record_sdk_identify()
    trace = IdentityTrace(
        tenant_id=tenant_id,
        source_system_id=source_namespace,
        correlation_id=body.idempotency_key,
    )
    trace.ingestion_receive()
    trace.claims_normalize(len(claims))

    # Source identity: create via SourceIdentityRegistry (identity continuity runtime)
    _identify_source_identity_id = None
    _source_claims_complete = True
    try:
        _repo = IdentityResolutionRepository()
        _registry = SourceIdentityRegistry(_repo)
        _wire = IdentityIngestionWire(_registry)
        _source_ns = source_namespace
        _normalized_identify = {
            "anonymous_id": (
                body.anonymous_id
                if identity_flags.anonymous_to_known_binding_enabled or not body.user_id
                else None
            ),
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
                anonymous_id=(
                    body.anonymous_id
                    if identity_flags.anonymous_to_known_binding_enabled or not body.user_id
                    else None
                ),
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
                        hash_sensitive_value=claim["claim_type"] in {"email", "phone"},
                    )
                    if hasattr(identity_metrics, "record_claim_created"):
                        identity_metrics.record_claim_created()
                except Exception:
                    _source_claims_complete = False
                    logger.warning(
                        "sdk.identify.source_claim_failed",
                        extra={"tenant_id": tenant_id, "claim_type": claim["claim_type"]},
                    )
    except Exception as e:
        _source_claims_complete = False
        logger.warning(
            "sdk.identify.source_identity_failed",
            extra={"tenant_id": tenant_id, "error_type": type(e).__name__},
        )

    logger.info(
        "sdk.identify.received",
        extra={
            "tenant_id": tenant_id,
            "has_user_id": bool(body.user_id),
            "has_anonymous_id": bool(body.anonymous_id),
            "has_traits": bool(body.traits),
            "traits_keys": list(body.traits.keys()) if body.traits else [],
        },
    )

    # Resolve through the canonical identity service. Source identities and
    # claims above are continuity evidence; they do not choose a canonical
    # profile. The resolver owns tenant-scoped matching, consent checks,
    # conflict handling, and graph mutations.
    resolution_outcome = "pending_resolution"
    canonical_entity_id = None
    confidence = None
    reason_codes: list[str] = []
    import_candidate_decision = None
    import_candidate_lookup_failed = False
    # The resolver decision does not prove that a downstream projection
    # restatement was durably accepted, so this response never claims one.
    requires_restatement = False
    if not _identify_source_identity_id:
        resolution_outcome = "source_identity_unavailable"
        reason_codes = ["source_identity_unavailable"]
    elif not _source_claims_complete:
        resolution_outcome = "source_claims_incomplete"
        reason_codes = ["source_claims_incomplete"]
    else:
        # Link authorization is derived from a durable server receipt bound to
        # the anonymous identity. The request's consent_state and user_id are
        # client claims and cannot authorize lookup or graph mutation.
        try:
            from identity.identity.import_candidate_adapter import (
                ImportIdentityCandidateAdapter,
            )

            if identity_flags.sdk_late_binding_enabled:
                import_candidate_decision = await ImportIdentityCandidateAdapter(
                    _repo
                ).evaluate(
                    tenant_id=tenant_id,
                    claims={
                        key: body.traits[key]
                        for key in ("email", "phone")
                        if body.traits and body.traits.get(key)
                    },
                    include_connectors=identity_flags.connector_backfill_enabled,
                )
        except Exception as exc:
            # Candidate lookup is an identity safety input. Keep failure details
            # private and do not treat it as evidence that no import match exists.
            import_candidate_lookup_failed = True
            logger.warning(
                "sdk.identify.import_candidate_lookup_failed",
                extra={"tenant_id": tenant_id, "error_type": type(exc).__name__},
            )

        if import_candidate_lookup_failed:
            resolution_outcome = "blocked"
            reason_codes = ["import_identity_candidate_lookup_failed"]
        elif import_candidate_decision is not None and import_candidate_decision.outcome in {
            "candidate", "blocked"
        }:
            # A matching imported identity is not safe evidence for either a
            # canonical link or a new canonical profile. Stop before resolver
            # mutation until server-verified identity-link consent/review exists.
            resolution_outcome = import_candidate_decision.outcome
            reason_codes = list(import_candidate_decision.reason_codes)
        else:
            try:
                from identity.identity.routes import get_identity_resolver

                # This is an observation ID, not a request idempotency key. The
                # canonical repository currently inserts signal observations by
                # fresh row ID and does not deduplicate them by source_event_id.
                identity_event_id = str(uuid.uuid4())
                identity_event = {
                    "event_id": identity_event_id,
                    # Internal telemetry linkage only. IdentityTrace hashes this
                    # tenant-scoped request key before emitting it; event_id
                    # remains the independent observation/idempotency identity.
                    "trace_correlation_id": body.idempotency_key,
                    "tenant_id": tenant_id,
                    "user_id": body.user_id,
                    "anonymous_id": body.anonymous_id,
                    "properties": {
                        key: body.traits[key]
                        for key in ("email", "phone")
                        if body.traits and body.traits.get(key)
                    },
                    # Only the durable server receipt is forwarded as resolver
                    # consent context. Client snapshots are never copied here.
                    "context": {
                        "consent": server_consent_context,
                        # This app scope comes from the authenticated tenant
                        # request plus the site allowlist check above. SDK name
                        # is deliberately excluded so web/iOS/Android converge.
                        "identity_namespace": body.tenant_app_key,
                    },
                    "source": "sdk_identify",
                    "timestamp": now_iso,
                }
                decision = await get_identity_resolver().resolve_event(
                    identity_event, tenant_id
                )
                resolved_entity_id = decision.canonical_entity_id or None
                confidence = decision.confidence
                reason_codes = list(decision.reason_codes or [])
                decision_name = getattr(decision.decision, "value", str(decision.decision))
                if decision_name in {"create", "link", "merge"}:
                    if resolved_entity_id:
                        canonical_entity_id = resolved_entity_id
                        resolution_outcome = decision_name
                    else:
                        resolution_outcome = "resolution_incomplete"
                        reason_codes.append("canonical_id_missing")
                elif decision_name == "noop":
                    resolution_outcome = (
                        "resolution_failed"
                        if "internal_error" in decision.reason_codes
                        else "pending_resolution"
                    )
                else:
                    # Candidate, blocked, reject, and unknown policy decisions do
                    # not establish a canonical identity for this SDK request.
                    resolution_outcome = decision_name
            except Exception as exc:
                # Resolution is deliberately fail-soft after identify evidence has
                # been accepted. Keep logs free of traits and exception payloads.
                logger.warning(
                    "sdk.identify.resolution_failed",
                    extra={"tenant_id": tenant_id, "error_type": type(exc).__name__},
                )
                resolution_outcome = "resolution_failed"
                canonical_entity_id = None
                confidence = None
                reason_codes = ["resolver_error"]

        # Imported evidence only creates a candidate/blocked review result. A
        # canonical create/link/merge returned by the resolver remains the
        # authoritative decision and is never downgraded by this adapter.
        if canonical_entity_id is None:
            if not import_candidate_lookup_failed and import_candidate_decision is not None:
                if import_candidate_decision.outcome in {"candidate", "blocked"}:
                    resolution_outcome = import_candidate_decision.outcome
                    reason_codes = list(import_candidate_decision.reason_codes)

    # Persist unresolved imported-identity candidates into a tenant-scoped
    # review queue. This is review context only; it never grants merge/link
    # authority. The repository derives an idempotent key from tenant and
    # source-identity references, so duplicate identify requests converge.
    if (
        canonical_entity_id is None
        and import_candidate_decision is not None
        and import_candidate_decision.outcome in {"candidate", "blocked"}
        and (
            not identity_flags.manual_review_enabled
            or not identity_flags.conflict_detection_enabled
        )
    ):
        resolution_outcome = "blocked"
        canonical_entity_id = None
        reason_codes = [
            "identity_manual_review_disabled"
            if not identity_flags.manual_review_enabled
            else "identity_conflict_detection_disabled"
        ]

    if (
        canonical_entity_id is None
        and import_candidate_decision is not None
        and import_candidate_decision.outcome in {"candidate", "blocked"}
        and identity_flags.manual_review_enabled
        and identity_flags.conflict_detection_enabled
        and _identify_source_identity_id
        and import_candidate_decision.candidate_source_identity_ids
    ):
        try:
            from identity.identity.pending_review import PendingIdentityReviewRepository

            await PendingIdentityReviewRepository().upsert_candidate(
                tenant_id=tenant_id,
                identify_source_identity_id=_identify_source_identity_id,
                candidate_source_identity_ids=(
                    import_candidate_decision.candidate_source_identity_ids
                ),
                reason_codes=import_candidate_decision.reason_codes,
                evidence=import_candidate_decision.evidence,
            )
        except Exception as exc:
            logger.warning(
                "sdk.identify.pending_review_persist_failed",
                extra={"tenant_id": tenant_id, "error_type": type(exc).__name__},
            )
            resolution_outcome = "blocked"
            canonical_entity_id = None
            reason_codes = ["identity_review_queue_persistence_failed"]

    # Keep the SDK lifecycle trace joined across ingress, source identity
    # registration, normalized claims, and the final resolver/review outcome.
    # The trace helper emits only a bounded outcome and numeric confidence;
    # raw traits and identifiers never enter these details.
    try:
        trace.identity_resolve(resolution_outcome, confidence or 0.0)
    except Exception:
        pass

    # Publish an identity-resolved event only when the resolver selected a
    # canonical entity. Candidate, blocked, and failed decisions are evaluation
    # outcomes, not successful identity bindings. Keep traits out of either
    # event; the resolver hashes sensitive values before observation storage.
    resolution_event_publish_succeeded = None
    if producer:
        topic = (
            Topic.IDENTITY_RESOLVED
            if canonical_entity_id
            else Topic.RESOLUTION_EVALUATED
        )
        try:
            await producer.publish(Event(
                topic=topic,
                payload={
                    "tenant_id": tenant_id,
                    "source_system": source_namespace,
                    "source_identity_id": _identify_source_identity_id,
                    "claim_count": len(claims),
                    "sdk_name": body.sdk_name,
                    "sdk_version": body.sdk_version,
                    "resolution_outcome": resolution_outcome,
                    "canonical_entity_id": canonical_entity_id,
                    "confidence": confidence,
                    "reason_codes": reason_codes,
                    "occurred_at": now_iso,
                },
            ))
            resolution_event_publish_succeeded = True
        except Exception as exc:
            # Identity evidence and the resolver decision are already committed.
            # Do not turn a notification error into an ambiguous request failure.
            logger.warning(
                "sdk.identify.event_publish_failed",
                extra={"tenant_id": tenant_id, "error_type": type(exc).__name__},
            )
            resolution_event_publish_succeeded = False

    return IdentifyResponse(
        identified=True,
        user_id=body.user_id,
        anonymous_id=body.anonymous_id,
        resolution_outcome=resolution_outcome,
        canonical_entity_id=canonical_entity_id,
        confidence=confidence,
        reason_codes=reason_codes,
        resolution_event_publish_succeeded=resolution_event_publish_succeeded,
        requires_restatement=requires_restatement,
    )


@router_lifecycle.post("/alias", response_model=AliasResponse)
async def sdk_alias(
    body: AliasRequest,
    request: Request,
    cache: CacheClient = Depends(get_cache),
    producer: EventProducer = Depends(get_producer),
):
    """Resolve a legacy alias() call through the canonical identify path.

    The source pair is only a claim. Durable consent, app authorization,
    candidate policy, and canonical graph mutations are owned by sdk_identify.
    """
    tenant = request.state.tenant
    tenant_id = tenant.tenant_id
    from config.settings import settings

    identity_flags = settings.identity_continuity
    if (
        not identity_flags.resolution_enabled
        or not identity_flags.anonymous_to_known_binding_enabled
    ):
        return AliasResponse(
            aliased=False,
            previous_id=body.previous_id,
            user_id=body.user_id,
            resolution_outcome=(
                "identity_resolution_disabled"
                if not identity_flags.resolution_enabled
                else "anonymous_to_known_binding_disabled"
            ),
        )
    payload = {
        "tenant_id": tenant_id,
        "tenant_app_key": body.tenant_app_key,
        "previous_id": body.previous_id,
        "user_id": body.user_id,
        "sdk_name": body.sdk_name,
        "sdk_version": body.sdk_version,
    }
    key = (body.idempotency_key or "").strip()
    if not key:
        key = "alias:" + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    identify = await sdk_identify(
        IdentifyRequest(
            tenant_app_key=body.tenant_app_key,
            user_id=body.user_id,
            anonymous_id=body.previous_id,
            sdk_name=body.sdk_name,
            sdk_version=body.sdk_version,
            idempotency_key=key,
        ),
        request,
        cache=cache,
        producer=producer,
    )
    accepted = (
        identify.resolution_outcome in {"create", "link", "merge"}
        and bool(identify.canonical_entity_id)
    )
    return AliasResponse(
        aliased=accepted,
        previous_id=body.previous_id,
        user_id=body.user_id,
        source_identity_id=None,
        resolution_outcome=identify.resolution_outcome,
        canonical_entity_id=identify.canonical_entity_id if accepted else None,
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

    from identity.identity.observability import identity_metrics

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
