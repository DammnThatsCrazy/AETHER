"""
Aether Service — SDK identity utilities.

The legacy cross-device resolve endpoint is retained for SDK compatibility,
but canonical identity resolution is owned by IdentityResolutionService. SDK
claims and device fingerprints are evidence only; this endpoint does not turn
them into a journey-resume decision.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import utc_now
from shared.logger.logger import get_logger

logger = get_logger("aether.service.sdk")
router = APIRouter(prefix="/sdk", tags=["SDK"])


class WalletRef(BaseModel):
    address: str = Field(..., description="Wallet address (any VM)")
    vm: str = Field(default="evm", description="VM type: evm, svm, btc, move, near, tron, cosmos")


class FingerprintSignals(BaseModel):
    canvas_hash: Optional[str] = None
    webgl_renderer: Optional[str] = None
    timezone: Optional[str] = None
    language: Optional[str] = None


class IdentityResolveRequest(BaseModel):
    wallets: list[WalletRef] = Field(default_factory=list, max_length=20)
    anonymous_id: str = Field(..., description="The calling device's current anonymousId")
    # Accepted for compatibility, but fingerprint evidence is intentionally
    # excluded from this endpoint's canonical resolver input.
    device_fingerprint: Optional[str] = None
    fingerprint_signals: Optional[FingerprintSignals] = None
    user_id: Optional[str] = None
    email_hash: Optional[str] = None
    platform: Optional[str] = None
    tenant_app_key: Optional[str] = Field(
        None, description="App/site scope; checked against the authenticated API key's site bindings"
    )


class ResolvedIdentity(BaseModel):
    anonymous_id: str
    user_id: Optional[str] = None
    wallet_addresses: list[str] = Field(default_factory=list)
    wallet_refs: list[dict] = Field(default_factory=list)
    resolved_at: str
    confidence: float = 0.0
    confidence_signals: list[str] = Field(default_factory=list)


class IdentityResolveResponse(BaseModel):
    resolved: bool
    identity: Optional[ResolvedIdentity] = None
    resolution_outcome: Optional[str] = None
    reason_codes: list[str] = Field(default_factory=list)


def _blocked(reason: str) -> IdentityResolveResponse:
    return IdentityResolveResponse(
        resolved=False,
        identity=None,
        resolution_outcome="blocked",
        reason_codes=[reason],
    )


def _authenticated_app_scope(request: Request, requested_app: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Return the authenticated app namespace or a fail-closed reason."""
    tenant = request.state.tenant
    site_ids = getattr(tenant, "site_ids", None)
    supplied = (requested_app or "").strip()

    if site_ids is None:
        return None, "sdk_app_scope_unavailable"

    allowed = {str(site).strip() for site in site_ids if str(site).strip()}
    if supplied:
        if supplied not in allowed:
            return None, "sdk_app_not_authorized"
        return supplied, None
    if len(allowed) == 1:
        return next(iter(allowed)), None
    return None, "sdk_app_scope_required"


def _stable_event_id(tenant_id: str, anonymous_id: str, namespace: str, user_id: Optional[str]) -> str:
    material = json.dumps(
        [tenant_id, anonymous_id, namespace, user_id or ""],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"aether:sdk-identity-resolve:{digest}"))


@router.post("/identity/resolve", response_model=IdentityResolveResponse)
async def resolve_identity(body: IdentityResolveRequest, request: Request) -> IdentityResolveResponse:
    """Resolve SDK evidence through the canonical identity service.

    This compatibility endpoint intentionally returns ``resolved=True`` only
    when it can name a proven prior anonymous identity for SDK journey resume.
    The legacy payload has no verified ownership proof or source-identity map
    for that response, so caller user IDs, email hashes, wallets, and
    fingerprints are never reported as an authoritative prior-profile match.
    A consented first-seen app user ID may create a new app-scoped identity
    alias, but does not trigger the legacy ``onJourneyResumed`` callback.
    """
    tenant = request.state.tenant
    tenant_id = str(tenant.tenant_id)
    anonymous_id = body.anonymous_id.strip()
    if not anonymous_id:
        return _blocked("anonymous_id_required")

    namespace, scope_error = _authenticated_app_scope(request, body.tenant_app_key)
    if scope_error:
        return _blocked(scope_error)

    from config.settings import settings

    flags = settings.identity_continuity
    if not flags.resolution_enabled:
        return _blocked("identity_resolution_disabled")
    if not flags.sdk_late_binding_enabled:
        return _blocked("sdk_late_binding_disabled")
    if not flags.anonymous_to_known_binding_enabled:
        return _blocked("anonymous_to_known_binding_disabled")

    from governance.consent.authority import evaluate_identity_link_consent

    try:
        consent_allowed, consent_reason, consent_context = await evaluate_identity_link_consent(
            tenant_id, anonymous_id
        )
    except Exception as exc:  # fail closed if the durable authority is unavailable
        logger.warning(
            "sdk.identity_resolve.consent_lookup_failed",
            extra={"tenant_id": tenant_id, "error_type": type(exc).__name__},
        )
        return _blocked("identity_link_consent_lookup_failed")
    if not consent_allowed or not consent_context:
        return _blocked(consent_reason or "identity_link_consent_required")

    resolver = _get_identity_resolver()
    resolver_repo = getattr(resolver, "_repo", None)
    user_id = body.user_id.strip() if body.user_id else ""
    resolver_user_id: Optional[str] = None

    # A client-selected user ID may establish a first-seen app-scoped alias,
    # but may never select an existing profile. Look for an existing canonical
    # USER_ID alias first; if it exists, omit that unverified claim entirely.
    if user_id and resolver_repo is not None:
        from identity.identity.hashing import hash_value
        from identity.identity.models import IdentitySignalType

        scoped_user_id = f"{namespace}:{user_id}"
        alias_hash = hash_value(scoped_user_id, scope=f"user:{tenant_id}")
        try:
            existing_user_entities = await resolver_repo.find_subjects_by_alias(
                tenant_id, IdentitySignalType.USER_ID, alias_hash
            )
        except Exception as exc:
            logger.warning(
                "sdk.identity_resolve.user_alias_lookup_failed",
                extra={"tenant_id": tenant_id, "error_type": type(exc).__name__},
            )
            return _blocked("identity_registry_unavailable")
        if not existing_user_entities:
            resolver_user_id = user_id

    if not resolver_user_id:
        # Anonymous-only traffic and repeat claims for an already-known
        # client-selected user ID are not sufficient to create or select a
        # canonical subject. In particular, do not pass the anonymous ID to
        # the resolver here: doing so would materialize a profile on every
        # SDK resume despite having no new authorized binding evidence.
        return IdentityResolveResponse(
            resolved=False,
            identity=None,
            resolution_outcome="insufficient_authoritative_evidence",
            reason_codes=["unverified_identity_claims_ignored"],
        )

    # Unverified wallet/email/fingerprint claims are deliberately excluded.
    # They remain supported by the SDK payload for compatibility and must use
    # source-verified ingestion paths before they can influence a link.
    event_id = _stable_event_id(tenant_id, anonymous_id, namespace or "", resolver_user_id)
    event = {
        "event_id": event_id,
        "tenant_id": tenant_id,
        "user_id": resolver_user_id,
        "anonymous_id": anonymous_id,
        "timestamp": utc_now().isoformat(),
        "source": "sdk_identity_resolve",
        "context": {
            "source": "sdk",
            "platform": (body.platform or "unknown")[:32],
            "identity_namespace": namespace,
            "consent": consent_context,
        },
        "properties": {},
    }

    try:
        decision = await resolver.resolve_event(event, tenant_id)
    except Exception as exc:
        logger.warning(
            "sdk.identity_resolve.canonical_resolution_failed",
            extra={"tenant_id": tenant_id, "error_type": type(exc).__name__},
        )
        return IdentityResolveResponse(
            resolved=False,
            identity=None,
            resolution_outcome="resolution_failed",
            reason_codes=["resolver_error"],
        )

    # Even when the resolver creates or binds the current anonymous subject,
    # the legacy callback requires the ID of a different, proven prior SDK
    # identity. No legacy cluster lookup is used to manufacture that answer.
    return IdentityResolveResponse(
        resolved=False,
        identity=None,
        resolution_outcome=decision.decision.value,
        reason_codes=list(decision.reason_codes),
    )


def _get_identity_resolver():
    from identity.identity.routes import get_identity_resolver

    return get_identity_resolver()
