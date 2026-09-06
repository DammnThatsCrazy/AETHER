"""Unified integration catalog read-model endpoints (additive, R1 spine).

Read-only projection of the one-customer catalog
(shared.integration_contracts.catalog — the derived manifests) + tenant
connector state onto the Settings→Integrations surface.

Projection principle: reuse the canonical manifest + readiness vocabulary
(never a parallel state token or readiness word), and claim no tenant readiness
that evidence does not support — each tenant integration carries its manifest's
catalog readiness plus the raw connection facts; the joined "Connected ≠ Ready"
graph is a later workstream.

Why this lives in its own module (not routes.py): ``connectors/__init__``
eagerly imports routes, and ``shared.certification.readiness`` imports
``connectors.base``; a top-level readiness/catalog import in routes.py would
therefore re-enter routes while readiness is still loading on a readiness-first
import path (circular import). Keeping this module out of the eager package
import surface breaks that cycle while leaving routes.py untouched.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request

from shared.certification.readiness import readiness_rank
from shared.common.common import APIResponse, NotFoundError
from shared.integration_contracts.catalog import ALL_MANIFESTS, manifest_by_family
from shared.integration_contracts.experience import (
    EXPERIENCE_CATEGORIES,
    experience_category_for,
)

from services.integrations.connectors.routes import _tenant_id
from services.integrations.connectors.service import connector_service

catalog_router = APIRouter(
    prefix="/v1", tags=["Integrations — Unified Catalog"]
)

# product_id → catalog group token (mirrors catalog.py's four projection groups).
_CATALOG_SOURCE_BY_PRODUCT: dict[str, str] = {
    "ingestion": "byod_connector",
    "ads": "ad_platform",
    "payment_rails": "payment_rail",
    "credit": "credit_bureau",
}


def _enabled_environments(manifest) -> list[str]:
    envs = manifest.availability.environments
    return [
        name
        for name, enabled in (
            ("local", envs.local),
            ("integration", envs.integration),
            ("staging", envs.staging),
            ("production", envs.production),
        )
        if enabled
    ]


def _experience_value(manifest) -> Optional[str]:
    """Experience token for a manifest, or None (derived, never hand-synced)."""
    category = experience_category_for(manifest)
    return category.value if category is not None else None


def _manifest_entry(manifest) -> dict[str, Any]:
    """Project one manifest onto the flat catalog-entry wire shape."""
    return {
        "key": manifest.identity_key,
        "family": manifest.provider_family,
        "product": manifest.product_id,
        "capability": manifest.capability_id,
        "display_name": manifest.display_name,
        "category": manifest.category,
        "experience_category": _experience_value(manifest),
        "source": _CATALOG_SOURCE_BY_PRODUCT.get(
            manifest.product_id, manifest.product_id
        ),
        "tenant_self_service": manifest.availability.tenant_self_service,
        "environments": _enabled_environments(manifest),
        "authentication": manifest.authentication.type,
        "accounts_discovery": manifest.accounts.discovery_supported,
        "accounts_selection_required": manifest.accounts.selection_required,
        "webhooks_supported": manifest.webhooks.supported,
        "sync_incremental": manifest.sync.incremental,
        "sync_initial_backfill": manifest.sync.initial_backfill,
        "readiness": {
            "state": manifest.readiness.state.value,
            "rank": readiness_rank(manifest.readiness.state),
            "level": manifest.readiness.level,
        },
        "data_outputs": list(manifest.data_outputs),
        "product_destinations": list(manifest.product_destinations),
    }


def _visible_catalog_entries() -> list[dict[str, Any]]:
    """The tenant-connectable catalog: manifests enabled in some environment.

    Deferred credit bureaus are scaffolded/enabled-nowhere and stay out, which
    keeps the customer-facing catalog honest about what can actually be
    connected today. Each manifest passes validate_manifest at import, so the
    readiness tokens below are already honest.
    """
    entries = [
        _manifest_entry(m)
        for m in ALL_MANIFESTS
        if m.availability.environments.any_enabled()
    ]
    # Experience-grouping order the tenant UI uses (stable, never alphabetical).
    entries.sort(key=lambda e: _EXPERIENCE_SORT.get(e["experience_category"], 99))
    return entries


# Presentation order for the customer catalog: advertising, commerce, customer,
# comms, analytics, social, support, work — unclassified last.
_EXPERIENCE_SORT: dict[str, int] = {
    cat.value: i for i, cat in enumerate(EXPERIENCE_CATEGORIES)
}


def _tenant_integration_entry(
    connector_type: str, row: dict[str, Any]
) -> dict[str, Any]:
    """Project one tenant connector record onto the tenant-integration shape.

    ``connected`` is a fact about the tenant record (enabled or a credential is
    configured or a sync has ever run), NOT a readiness claim. Readiness on a
    tenant integration is the manifest's catalog readiness (credential-waiting
    material); the joined tenant readiness graph is a later workstream.
    """
    manifest = manifest_by_family.get(connector_type)
    sync_status = row.get("sync_status") or "never_synced"
    connected = bool(
        row.get("enabled")
        or row.get("secret_configured")
        or sync_status != "never_synced"
    )
    entry: dict[str, Any] = {
        "id": connector_type,
        "family": connector_type,
        "name": row.get("name"),
        "display_name": (
            manifest.display_name if manifest is not None else row.get("label")
        ),
        "experience_category": (
            _experience_value(manifest) if manifest is not None else None
        ),
        "connected": connected,
        "enabled": bool(row.get("enabled")),
        "secret_configured": bool(row.get("secret_configured")),
        "sync_status": sync_status,
        "last_synced_at": row.get("last_synced_at"),
    }
    if manifest is not None:
        entry["readiness"] = {
            "state": manifest.readiness.state.value,
            "rank": readiness_rank(manifest.readiness.state),
            "level": manifest.readiness.level,
        }
    return entry


@catalog_router.get("/integration-catalog")
async def integration_catalog(request: Request):
    """The derived one-customer catalog (Settings→Integrations read model).

    Tenant-scoped read. Every connectable manifest as a flat entry, plus the
    canonical experience-category order for stable grouping.
    """
    tenant_id = _tenant_id(request)
    entries = _visible_catalog_entries()
    return APIResponse(
        data={
            "tenant_id": tenant_id,
            "count": len(entries),
            "experience_categories": [c.value for c in EXPERIENCE_CATEGORIES],
            "entries": entries,
        }
    ).to_dict()


@catalog_router.get("/tenant-integrations")
async def list_tenant_integrations(request: Request):
    """The tenant's configured integrations with manifest + connection facts.

    Only connectors with a stored tenant record are returned (an un-configured
    descriptor is "available", not a tenant integration). ``connected`` is a
    record fact, never a readiness claim.
    """
    tenant_id = _tenant_id(request)
    stored = await connector_service.repo.find_many(
        filters={"tenant_id": tenant_id}, limit=1000
    )
    configured = {r["connector_type"] for r in stored}
    rows = await connector_service.list_for_tenant(tenant_id)
    items = [
        _tenant_integration_entry(r["connector_type"], r)
        for r in rows
        if r["connector_type"] in configured
    ]
    items.sort(key=lambda e: str(e["display_name"]).lower())
    return APIResponse(
        data={"tenant_id": tenant_id, "count": len(items), "items": items}
    ).to_dict()


@catalog_router.get("/tenant-integrations/{integration_id}")
async def get_tenant_integration(integration_id: str, request: Request):
    """One tenant integration (404 unless the tenant has a record for it)."""
    tenant_id = _tenant_id(request)
    stored = await connector_service.repo.find_many(
        filters={"tenant_id": tenant_id}, limit=1000
    )
    configured = {r["connector_type"] for r in stored}
    if integration_id not in configured:
        raise NotFoundError("integration")
    rows = await connector_service.list_for_tenant(tenant_id)
    row = next(
        (r for r in rows if r["connector_type"] == integration_id), None
    )
    if row is None:
        raise NotFoundError("integration")
    return APIResponse(data=_tenant_integration_entry(integration_id, row)).to_dict()


@catalog_router.get("/integration-readiness")
async def integration_readiness(request: Request):
    """Catalog-level readiness matrix over the existing readiness engine.

    Projection of every connectable manifest's CredentialReadiness token +
    rank (the canonical ladder single source) — no parallel readiness word.
    """
    tenant_id = _tenant_id(request)
    items = []
    seen_states: set[str] = set()
    for m in ALL_MANIFESTS:
        if not m.availability.environments.any_enabled():
            continue
        state = m.readiness.state.value
        seen_states.add(state)
        items.append(
            {
                "key": m.identity_key,
                "family": m.provider_family,
                "display_name": m.display_name,
                "experience_category": _experience_value(m),
                "readiness": {
                    "state": state,
                    "rank": readiness_rank(m.readiness.state),
                    "level": m.readiness.level,
                },
            }
        )
    items.sort(key=lambda e: e["readiness"]["rank"])
    return APIResponse(
        data={
            "tenant_id": tenant_id,
            "count": len(items),
            "states_present": sorted(seen_states),
            "items": items,
        }
    ).to_dict()
