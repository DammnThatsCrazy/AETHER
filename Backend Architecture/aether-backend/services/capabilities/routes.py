"""
Capability discovery — GET /v1/capabilities

Returns which Profile360 sub-resources, provider integrations, consent
purposes, and feature flags are active for the calling tenant. Designed
for SDK integration-time discovery so callers don't need to guess.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from config.settings import get_settings
from shared.decorators import api_response
from shared.logger.logger import get_logger
from shared.privacy.consent_enforcement import CONSENT_PURPOSES

logger = get_logger("aether.service.capabilities")

router = APIRouter(prefix="/v1/capabilities", tags=["capabilities"])

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

    # ── Feature flags ──────────────────────────────────────────────────
    sug = settings.suggestions
    feature_flags = {
        "suggestions_enabled": sug.enabled,
        "suggestions_execution_enabled": sug.execution_enabled,
        "connectors_enabled": settings.connectors.enabled,
        "data_quality_enabled": settings.data_quality.enabled,
    }

    return {
        "tenant_id": tenant_id,
        "profile_sub_resources": available_sub_resources,
        "providers": providers,
        "consent_purposes_granted": granted_purposes,
        "consent_purposes_all": sorted(CONSENT_PURPOSES),
        "feature_flags": feature_flags,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
