"""Tenant-contextual integration readiness routes (WS-4, additive).

Tenant surface (read-only)::

    GET /v1/tenant/integration-readiness[?experience_category=..&state=..]
        The joined readiness projection for the calling tenant: every
        connectable catalog manifest (plus any tenant-configured connector a
        manifest still covers) joined with the tenant's connection record facts
        into an honest per-integration ``tenant_state``.

This is the *joined* graph R1 deferred (catalog_endpoints.py docstring): the
catalog-level matrix (/v1/integration-readiness) stays provider/capability
truth, /v1/tenant-integrations stays record facts, and this projection combines
the two under the honesty law in :mod:`.tenant_integration_readiness` — every
``tenant_state`` is derived from evidence, provider readiness is always the
manifest's catalog baseline, and no integration can read ``ready`` without proof
on both the provider and the connection axes.

Cycle safety: like ``catalog_endpoints.py``, this module imports the connector
service + catalog + certification readiness, so it must NOT be part of the
eagerly-imported package surface (``services/readiness_graph/__init__.py`` and
``routes.py`` are imported at main.py top-level). Keep it out of that surface;
the integrator includes this router lazily under the connectors feature flag
alongside ``catalog_endpoints.catalog_router`` in main.py.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query, Request

from shared.common.common import APIResponse
from shared.integration_contracts.catalog import ALL_MANIFESTS, manifest_by_family
from shared.integration_contracts.experience import EXPERIENCE_CATEGORIES

from services.integrations.connectors.routes import _tenant_id
from services.integrations.connectors.service import connector_service

from .tenant_integration_readiness import (
    TenantIntegrationState,
    project_tenant_integration,
)

router = APIRouter(
    prefix="/v1/tenant/integration-readiness",
    tags=["Integrations — Tenant-Contextual Readiness"],
)

#: Experience presentation order (mirrors the Settings→Integrations grouping).
_EXPERIENCE_ORDER: dict[str, int] = {
    cat.value: i for i, cat in enumerate(EXPERIENCE_CATEGORIES)
}

_STATE_VALUES = {s.value for s in TenantIntegrationState}


def _visible_manifests() -> list:
    """Connectable catalog manifests (enabled in at least one environment)."""
    return [
        m for m in ALL_MANIFESTS if m.availability.environments.any_enabled()
    ]


def _experience_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    exp = item.get("experience_category")
    return (_EXPERIENCE_ORDER.get(exp, 99), str(item["display_name"]).lower())


def build_tenant_readiness_items(
    tenant_id: str,
    rows_by_family: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assemble the joined readiness graph over the tenant's stored records.

    Pure assembly (no I/O): ``rows_by_family`` maps connector family ->
    ConnectorConfig-shaped dict (the tenant's stored record facts).

    Item universe:
    * every *visible* catalog manifest (drives coverage + contextual CTAs for
      integrations the tenant has not yet connected), joined with any stored
      record for its family;
    * plus any tenant-configured family whose manifest exists but is NOT visible
      today (e.g. a provider pulled to an off-ramp) — an existing tenant
      integration is still reported even when the provider is no longer
      connectable, honestly flagged by its manifest's off-ramp readiness.
    """
    visible = _visible_manifests()
    visible_families: set[str] = {m.provider_family for m in visible}
    items = [
        project_tenant_integration(m, rows_by_family.get(m.provider_family))
        for m in visible
    ]
    # Tenant-configured families a manifest covers but the connectable catalog
    # no longer shows (provider pulled / scaffolded / deprecated).
    extras = [
        project_tenant_integration(
            manifest_by_family[fam], rows_by_family[fam]
        )
        for fam in rows_by_family
        if fam in manifest_by_family and fam not in visible_families
    ]
    items.sort(key=_experience_sort_key)
    extras.sort(key=lambda e: str(e["display_name"]).lower())
    items.extend(extras)
    return items


@router.get("")
async def tenant_integration_readiness(
    request: Request,
    experience_category: Optional[str] = Query(
        default=None, description="Restrict to one customer experience category"
    ),
    state: Optional[str] = Query(
        default=None, description="Restrict to one tenant-contextual state"
    ),
):
    """The tenant-contextual integration readiness projection (read-only).

    Every item carries the manifest's canonical catalog readiness (provider
    truth), the tenant's connection record facts (never a readiness claim), and
    an evidence-derived ``tenant_state``. ``connected`` is a record fact;
    ``needs_attention`` lists the concrete attention signals; ``ready`` is only
    emitted when BOTH the provider catalog is sandbox-validated or better AND
    the tenant connection is currently healthy.
    """
    tenant_id = _tenant_id(request)
    if state is not None and state not in _STATE_VALUES:
        return APIResponse(
            data={
                "tenant_id": tenant_id,
                "count": 0,
                "error": f"unknown tenant_state {state!r}",
                "items": [],
            }
        ).to_dict()
    stored = await connector_service.repo.find_many(
        filters={"tenant_id": tenant_id}, limit=1000
    )
    rows_by_family: dict[str, dict[str, Any]] = {
        r["connector_type"]: r for r in stored
    }
    items = build_tenant_readiness_items(tenant_id, rows_by_family)
    if experience_category is not None:
        items = [
            it for it in items if it.get("experience_category") == experience_category
        ]
    if state is not None:
        items = [it for it in items if it.get("tenant_state") == state]
    return APIResponse(
        data={
            "tenant_id": tenant_id,
            "count": len(items),
            "states_present": sorted(
                {it["tenant_state"] for it in items}, key=_state_order
            ),
            "items": items,
        }
    ).to_dict()


def _state_order(state: str) -> int:
    return _STATE_ORDER.get(state, 99)


#: Stable display order for states_present (forward progression first).
_STATE_ORDER: dict[str, int] = {
    TenantIntegrationState.AVAILABLE.value: 0,
    TenantIntegrationState.CONNECTED.value: 1,
    TenantIntegrationState.READY.value: 2,
    TenantIntegrationState.CONNECTION_DISABLED.value: 3,
    TenantIntegrationState.NEEDS_ATTENTION.value: 4,
}
