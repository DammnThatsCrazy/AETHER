"""
Capability discovery — GET /v1/capabilities

Returns which Profile360 sub-resources, provider integrations, consent
purposes, and feature flags are active for the calling tenant. Designed
for SDK integration-time discovery so callers don't need to guess.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from config.settings import get_settings
from services.capabilities.release_surface import resolve_release_surface
from services.capabilities.schema import (
    CapabilitiesResponse,
    EnforcementState,
    OperatorCapabilitiesResponse,
    ReleaseCapabilities,
)
from services.security.request_context import require_kyber_operator
from shared.decorators import api_response
from shared.logger.logger import get_logger
from shared.privacy.consent_enforcement import CONSENT_PURPOSES

logger = get_logger("aether.service.capabilities")

router = APIRouter(prefix="/v1/capabilities", tags=["capabilities"])
# Kyber operator capability read — release posture + enforcement, no tenant data.
kyber_router = APIRouter(
    prefix="/v1/kyber/capabilities",
    tags=["Kyber Capabilities"],
    dependencies=[Depends(require_kyber_operator)],
)


def _resolve_release(settings) -> ReleaseCapabilities:
    """Build the non-secret release-capabilities block from settings + config."""
    surface = resolve_release_surface(settings.runtime.deployment_profile)
    rr = settings.route_registry
    return ReleaseCapabilities(
        deployment_profile=surface["deployment_profile"],
        environment=getattr(settings.env, "value", str(settings.env)),
        release_class=surface["release_class"],
        enforcement=EnforcementState(
            policy_enforcement=rr.policy_enforcement_enabled,
            route_registry_enforced=rr.route_registry_enforced,
            kyber_operator_gate=rr.kyber_operator_gate_enforced,
        ),
        enabled_route_prefixes=surface["enabled_route_prefixes"],
        excluded_domains=surface["excluded_domains"],
    )


def _feature_flags(settings) -> dict[str, bool]:
    """Non-secret, per-domain feature-flag view used by the frontends to gate nav."""
    sug = settings.suggestions
    return {
        "suggestions_enabled": sug.enabled,
        "suggestions_execution_enabled": sug.execution_enabled,
        "connectors_enabled": settings.connectors.enabled,
        "data_quality_enabled": settings.data_quality.enabled,
        "stablecoin_intelligence_enabled": settings.stablecoin.api_enabled,
        "stablecoin_profile360_enabled": settings.stablecoin.profile360_enabled,
        "derivatives_intelligence_enabled": settings.derivatives.api_enabled,
        "derivatives_profile360_enabled": settings.derivatives.profile360_enabled,
        "interoperability_intelligence_enabled": settings.interop.api_enabled,
        "interoperability_profile360_enabled": settings.interop.profile360_enabled,
        "data_exchange_enabled": settings.data_exchange.enabled,
    }

# Profile360 sub-resources that Aether can surface per tenant.
# A sub-resource is available when at least one provider in its category
# is configured and healthy.  Unconfigured tenants see only the core set.
_CORE_SUB_RESOURCES = [
    "identity",
    "behavioral",
    "journey",
    "intelligence",
    "temporal",
    "geo",
]

_PROVIDER_SUB_RESOURCE_MAP: dict[str, list[str]] = {
    # social category → unlocks social sub-resource
    "social": ["social"],
    # open_banking / credit_bureau → unlocks financial sub-resource
    "open_banking": ["financial"],
    "credit_bureau": ["financial", "credit"],
    # brokerage → trading profile
    "brokerage": ["financial", "trading_profile"],
    # ad platforms → attribution
    "ad_platform": ["attribution"],
    # market_data → asset_composition / pnl
    "market_data": ["asset_composition", "pnl"],
    # on-chain categories
    "blockchain_rpc": ["onchain"],
    "block_explorer": ["onchain"],
    "dex_intelligence": ["onchain"],
}


def _staleness_label(last_sync_iso: str | None) -> str:
    if not last_sync_iso:
        return "stale"
    try:
        last = datetime.fromisoformat(last_sync_iso.replace("Z", "+00:00"))
        age_minutes = (datetime.now(timezone.utc) - last).total_seconds() / 60
        if age_minutes < 5:
            return "live"
        if age_minutes < 30:
            return "recent"
        return "stale"
    except (ValueError, TypeError):
        return "stale"


@router.get("")
@api_response
async def get_capabilities(request: Request):
    """
    Discover which Profile360 sub-resources, providers, and consent purposes
    are active for this tenant.  Always returns HTTP 200 with a capabilities
    envelope; missing features appear with status 'unconfigured'.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    tenant_id = tenant.tenant_id

    settings = get_settings()

    # ── Provider health ────────────────────────────────────────────────
    gateway = getattr(request.app.state, "provider_gateway", None)
    raw_health: dict = {}
    if gateway is not None:
        try:
            raw_health = await gateway.router.health()
        except Exception as exc:
            logger.warning(f"capabilities: provider health unavailable: {exc}")

    # Normalise raw_health to a flat list of provider dicts.
    # gateway.router.health() returns varying shapes; we handle both list and dict.
    provider_entries: list[dict] = []
    if isinstance(raw_health, list):
        provider_entries = raw_health
    elif isinstance(raw_health, dict):
        # Typically {"providers": [...]} or {"data": {"providers": [...]}}
        entries = raw_health.get("providers") or raw_health.get("data", {}).get("providers", [])
        if isinstance(entries, list):
            provider_entries = entries

    # Build provider list with freshness enrichment
    providers: list[dict] = []
    configured_categories: set[str] = set()
    for entry in provider_entries:
        if not isinstance(entry, dict):
            continue
        category = entry.get("category", "unknown")
        last_sync = entry.get("last_sync") or entry.get("last_successful_sync")
        status = entry.get("status", "unconfigured")
        configured = status not in ("unconfigured", "disabled")
        if configured:
            configured_categories.add(category)
        providers.append({
            "id": entry.get("provider_name") or entry.get("id", ""),
            "category": category,
            "status": status,
            "last_successful_sync": last_sync,
            "error_count": entry.get("error_count", 0),
            "staleness_label": _staleness_label(last_sync) if configured else "stale",
            "circuit_breaker": entry.get("circuit_breaker", "closed"),
        })

    # ── Profile360 sub-resources ───────────────────────────────────────
    available_sub_resources: list[str] = list(_CORE_SUB_RESOURCES)
    for category, sub_resources in _PROVIDER_SUB_RESOURCE_MAP.items():
        if category in configured_categories:
            for sr in sub_resources:
                if sr not in available_sub_resources:
                    available_sub_resources.append(sr)

    # ── Consent purposes ───────────────────────────────────────────────
    # The tenant-level consent configuration specifies which purposes are
    # permitted for processing.  We expose the full canonical set with a
    # flag indicating whether the tenant has granted each purpose.
    # In local/test mode, or when no consent record exists, all purposes
    # default to granted for backward compatibility.
    consent_repo = getattr(request.app.state, "consent_repository", None)
    granted_purposes: list[str] = []
    if consent_repo is not None:
        try:
            record = await consent_repo.get_tenant_consent(tenant_id)
            if record:
                granted_purposes = record.get("purposes", list(CONSENT_PURPOSES))
            else:
                granted_purposes = list(CONSENT_PURPOSES)
        except Exception as exc:
            logger.warning(f"capabilities: consent lookup failed: {exc}")
            granted_purposes = list(CONSENT_PURPOSES)
    else:
        granted_purposes = list(CONSENT_PURPOSES)

    # ── Feature flags + release surface (typed contract) ───────────────
    response = CapabilitiesResponse(
        tenant_id=tenant_id,
        release=_resolve_release(settings),
        profile_sub_resources=available_sub_resources,
        providers=providers,
        consent_purposes_granted=granted_purposes,
        consent_purposes_all=sorted(CONSENT_PURPOSES),
        feature_flags=_feature_flags(settings),
        evaluated_at=datetime.now(timezone.utc).isoformat(),
    )
    return response.model_dump()


@kyber_router.get("")
@api_response
async def get_operator_capabilities(request: Request):
    """Kyber operator capability read: release posture + enforcement + flags.

    No tenant-scoped data — this reflects what the deployment profile supports,
    for operator-console navigation and diagnostics. Gated by the Kyber
    operator dependency on the router.
    """
    settings = get_settings()
    extraction_mode = None
    try:  # lazy import — avoid a module-load cycle with the middleware
        from middleware.middleware import resolve_extraction_defense_mode

        extraction_mode = resolve_extraction_defense_mode()
    except Exception:  # pragma: no cover - diagnostics are best-effort
        extraction_mode = None

    response = OperatorCapabilitiesResponse(
        release=_resolve_release(settings),
        feature_flags=_feature_flags(settings),
        extraction_defense_mode=extraction_mode,
        evaluated_at=datetime.now(timezone.utc).isoformat(),
    )
    return response.model_dump()


# ═══════════════════════════════════════════════════════════════════════════
# Capability activation lifecycle (persisted, machine-enforced)
# ═══════════════════════════════════════════════════════════════════════════

from typing import Optional  # noqa: E402

from pydantic import BaseModel, Field  # noqa: E402

from shared.certification.readiness import CredentialReadiness  # noqa: E402
from services.capabilities.lifecycle import (  # noqa: E402
    IllegalTransitionError,
    PromotionPreconditionError,
    get_lifecycle_authority,
)


def _actor(request: Request) -> tuple[str, str]:
    tenant = request.state.tenant
    principal = (
        getattr(tenant, "principal_id", None)
        or getattr(tenant, "user_id", None)
        or tenant.tenant_id
    )
    return "user", str(principal)


def _parse_state(value: str) -> CredentialReadiness:
    try:
        return CredentialReadiness(value)
    except ValueError:
        from shared.common.common import BadRequestError

        raise BadRequestError(f"unknown readiness state {value!r}")


class ActivationTransitionRequest(BaseModel):
    environment: str = "sandbox"
    target_state: Optional[str] = None
    reason: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    credential_slot: Optional[str] = None
    domain: str = ""


@router.get("/activation")
@api_response
async def list_activation_states(request: Request):
    """Current persisted lifecycle state of every capability for this tenant."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    return await get_lifecycle_authority().states_for_tenant(tenant.tenant_id)


@router.get("/activation/{provider}/{capability}")
@api_response
async def get_activation_state(
    provider: str, capability: str, request: Request, environment: str = "sandbox"
):
    """Current state + full promotion/demotion history for one coordinate."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    authority = get_lifecycle_authority()
    return {
        "current": await authority.get_state(
            tenant.tenant_id, provider, environment, capability
        ),
        "history": await authority.history(
            tenant.tenant_id, provider, environment, capability
        ),
    }


@router.post("/activation/{provider}/{capability}/promote")
@api_response
async def promote_activation(
    provider: str, capability: str, body: ActivationTransitionRequest, request: Request
):
    """Request a fail-closed promotion along the canonical lifecycle."""
    tenant = request.state.tenant
    tenant.require_permission("admin")
    if not body.target_state:
        from shared.common.common import BadRequestError

        raise BadRequestError("target_state is required")
    actor_type, actor_id = _actor(request)
    try:
        return await get_lifecycle_authority().promote(
            tenant_id=tenant.tenant_id,
            provider=provider,
            environment=body.environment,
            capability=capability,
            target=_parse_state(body.target_state),
            actor_type=actor_type,
            actor_id=actor_id,
            domain=body.domain,
            reason=body.reason,
            evidence_refs=body.evidence_refs,
            credential_slot=body.credential_slot,
        )
    except (IllegalTransitionError, PromotionPreconditionError) as exc:
        from shared.common.common import BadRequestError

        raise BadRequestError(str(exc))


@router.post("/activation/{provider}/{capability}/suspend")
@api_response
async def suspend_activation(
    provider: str, capability: str, body: ActivationTransitionRequest, request: Request
):
    """Suspend a capability (reversible; resume restores the certified level)."""
    tenant = request.state.tenant
    tenant.require_permission("admin")
    actor_type, actor_id = _actor(request)
    try:
        return await get_lifecycle_authority().suspend(
            tenant_id=tenant.tenant_id,
            provider=provider,
            environment=body.environment,
            capability=capability,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=body.reason or "tenant suspend",
        )
    except IllegalTransitionError as exc:
        from shared.common.common import BadRequestError

        raise BadRequestError(str(exc))


@router.post("/activation/{provider}/{capability}/resume")
@api_response
async def resume_activation(
    provider: str, capability: str, body: ActivationTransitionRequest, request: Request
):
    """Resume a suspended/degraded capability to the state it interrupted."""
    tenant = request.state.tenant
    tenant.require_permission("admin")
    actor_type, actor_id = _actor(request)
    try:
        return await get_lifecycle_authority().resume(
            tenant_id=tenant.tenant_id,
            provider=provider,
            environment=body.environment,
            capability=capability,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=body.reason,
        )
    except IllegalTransitionError as exc:
        from shared.common.common import BadRequestError

        raise BadRequestError(str(exc))


@kyber_router.get("/activation")
@api_response
async def operator_activation_states(request: Request):
    """Cross-tenant current lifecycle states (operator readiness view), paged.

    KEYSET pagination: ``limit`` (default 500, max 1000) and an opaque ``cursor``
    (the last row's id from the previous page). A keyset cursor — not a numeric
    offset — keeps the readiness/kill-switch view from duplicating or skipping
    states while transitions concurrently supersede and insert rows. ``has_more``
    flags truncation and ``next_cursor`` drives the next page.
    """
    try:
        limit = int(request.query_params.get("limit", "500"))
    except (TypeError, ValueError):
        limit = 500
    limit = max(1, min(limit, 1000))
    cursor = request.query_params.get("cursor") or None
    # Fetch one extra row to detect truncation deterministically.
    rows = await get_lifecycle_authority().states_all_tenants(limit=limit + 1, after_id=cursor)
    has_more = len(rows) > limit
    page = rows[:limit]
    return {
        "states": page,
        "limit": limit,
        "cursor": cursor,
        "has_more": has_more,
        "next_cursor": page[-1].get("id") if (has_more and page) else None,
    }


@kyber_router.post("/activation/{tenant_id}/{provider}/{capability}/suspend")
@api_response
async def operator_suspend_activation(
    tenant_id: str,
    provider: str,
    capability: str,
    body: ActivationTransitionRequest,
    request: Request,
):
    """Operator emergency suspend of a tenant capability (audited)."""
    principal = getattr(request.state, "kyber_principal", None)
    actor_id = getattr(principal, "principal_id", None) or "kyber-operator"
    try:
        return await get_lifecycle_authority().suspend(
            tenant_id=tenant_id,
            provider=provider,
            environment=body.environment,
            capability=capability,
            actor_type="operator",
            actor_id=str(actor_id),
            reason=body.reason or "operator emergency suspend",
            kill_switch=True,
        )
    except IllegalTransitionError as exc:
        from shared.common.common import BadRequestError

        raise BadRequestError(str(exc))
