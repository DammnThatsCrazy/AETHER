"""Universal asset registry admin console — /v1/admin/assets.

Registry-admin + automated-discovery surface (financial-normalization W5,
C5-ADMIN). Returns registry reference data and suggested discovery candidates
(unresolved → candidate → verified → active), and applies ONLY what a global
admin explicitly posts — every route is global-ADMIN gated and the write routes
additionally require the ``admin_mode`` apply capability. INVARIANT: this is
reference + observational data only — nothing here originates, signs, or
settles a transfer, and ``execution_by_aether`` is always False. AETHER
OBSERVES. AETHER DOES NOT EXECUTE.

Gating mirrors services/assets/routes.py: the router mounts in main.py only
behind ``settings.assets.admin_enabled`` (default OFF). Every route fail-closes
on that flag; writes additionally require ``settings.assets.admin_mode``
(default OFF). The discovery pipeline produces suggested mappings for a human to
apply — it never auto-writes a registration.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from config.settings import settings
from services.assets.admin import (
    AdminActor,
    AssetDiscoveryPipeline,
    RegistryAdminFacade,
)
from services.assets.models import (
    AssetAlias,
    AssetDeployment,
    CanonicalAsset,
    ChainReference,
    FiatCurrencyMetadata,
)
from services.assets.registry import UniversalAssetRegistry
from services.stablecoin.foundation import (
    active_tenant_id as _tenant_id,
    require_flag,
    require_permission as _require_perm,
)
from shared.auth.auth import Permissions

admin_router = APIRouter(prefix="/v1/admin/assets", tags=["assets-admin"])


def _gate(request: Request, permission: str = Permissions.ADMIN) -> str:
    """Global-ADMIN gate for the admin console (mirrors /v1/assets ``_gate``)."""
    require_flag(settings.assets.admin_enabled, "Universal Asset Registry admin")
    _require_perm(request, permission)
    return _tenant_id(request)


def _gate_apply(request: Request) -> str:
    """Admin gate PLUS the apply capability (``admin_mode``).

    Discovery reads/candidates are available on the mounted admin surface;
    actually writing an applied alias/registration additionally requires the
    apply capability so the console can be reviewed in observe-only mode.
    """
    require_flag(settings.assets.admin_enabled, "Universal Asset Registry admin")
    require_flag(settings.assets.admin_mode, "Universal Asset Registry admin apply")
    _require_perm(request, Permissions.ADMIN)
    return _tenant_id(request)


def _actor(request: Request) -> AdminActor:
    """Build the service-layer admin actor after the route gate has passed."""
    return AdminActor.from_tenant(request.state.tenant)


def _safe(rows: list[dict]) -> list[dict]:
    """Decimal-safe response encoding (evidence JSONB may carry decimals)."""
    out = []
    for row in rows:
        encoded: dict[str, Any] = {}
        for key, value in row.items():
            encoded[key] = str(value) if isinstance(value, Decimal) else value
        out.append(encoded)
    return out


def _asset_rows(rows: list[dict]) -> list[dict]:
    return [UniversalAssetRegistry._asset_to_contract(r) for r in rows]


class DiscoveryMappingRequest(BaseModel):
    """A discovery mapping a human/global-admin confirms and applies.

    ``raw_reference`` is the originally-unresolved spelling, preserved verbatim
    (never rewritten). The canonical target must match what a resolver seam
    currently suggests — a mapping that no seam can verify is rejected, never
    fabricated.
    """

    model_config = ConfigDict(extra="forbid")

    raw_reference: str = Field(min_length=1)
    canonical_asset_id: str = Field(min_length=1)
    canonical_deployment_id: Optional[str] = None
    resolution_method: Optional[str] = None


def _seam_suggests(payload: DiscoveryMappingRequest) -> Optional[dict]:
    """Re-run the resolver seam for the posted mapping (defense in depth).

    Stateless skeleton: a mapping is applied only when a resolver seam verifies
    it against the CURRENT registry state. None => no seam currently maps the
    reference; a mismatch => the posted target diverges from the suggestion.
    """
    pipeline = AssetDiscoveryPipeline()
    return pipeline.candidate_for({"raw_reference": payload.raw_reference})


def _require_seam_match(
    payload: DiscoveryMappingRequest, candidate: Optional[dict],
) -> None:
    if candidate is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"reference {payload.raw_reference!r} is not currently resolvable "
                "by any resolver seam; no candidate to confirm/apply"
            ),
        )
    target_matches = candidate.get("canonical_asset_id") == payload.canonical_asset_id
    dep = candidate.get("canonical_deployment_id")
    deployment_matches = (
        payload.canonical_deployment_id is None
        or dep == payload.canonical_deployment_id
    )
    if not target_matches or not deployment_matches:
        raise HTTPException(
            status_code=409,
            detail=(
                "posted canonical target diverges from the resolver seam's current "
                "suggestion; a mapping is never fabricated"
            ),
        )


# ── Reference-data review (global-ADMIN reads) ───────────────────────────────

@admin_router.get("/status")
async def admin_status(request: Request):
    _gate(request)
    facade = RegistryAdminFacade()
    return await facade.status(_actor(request))


@admin_router.get("/assets")
async def list_assets(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = 0,
):
    _gate(request)
    rows = await RegistryAdminFacade().list_assets(
        _actor(request), limit=limit, offset=offset,
    )
    return {"items": _safe(_asset_rows(rows)), "count": len(rows)}


@admin_router.get("/assets/{asset_id}")
async def get_asset(asset_id: str, request: Request):
    _gate(request)
    asset = await RegistryAdminFacade().get_asset(_actor(request), asset_id)
    if asset is None:
        return {"asset_id": asset_id, "found": False}
    return {"asset_id": asset_id, "found": True, "asset": asset}


@admin_router.get("/aliases")
async def list_aliases(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = 0,
):
    _gate(request)
    rows = await RegistryAdminFacade().list_aliases(
        _actor(request), limit=limit, offset=offset,
    )
    return {"items": _safe(rows), "count": len(rows)}


@admin_router.get("/unresolved")
async def list_unresolved(
    request: Request,
    tenant_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = 0,
):
    """Recorded unresolved references (tenant-scoped; default platform scope)."""
    _gate(request)
    return await RegistryAdminFacade().list_unresolved(
        _actor(request), tenant_id=tenant_id, limit=limit, offset=offset,
    )


@admin_router.get("/discovery/candidates")
async def discovery_candidates(
    request: Request,
    tenant_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = 0,
):
    """Suggested mappings a resolver seam can now surface (never auto-applied)."""
    _gate(request)
    return await AssetDiscoveryPipeline().suggest_candidates(
        tenant_id=tenant_id, limit=limit, offset=offset,
    )


# ── Discovery lifecycle (human confirms; human applies) ──────────────────────

@admin_router.post("/discovery/confirm", status_code=200)
async def confirm_mapping(payload: DiscoveryMappingRequest, request: Request):
    """Confirm one candidate (unresolved → verified). NO write happens here.

    The mapping is re-verified against the current registry state before being
    marked ``verified`` for the reviewer; a mapping no seam supports is 409.
    """
    _gate(request)
    candidate = _seam_suggests(payload)
    _require_seam_match(payload, candidate)
    return AssetDiscoveryPipeline.confirm(candidate, reviewer=_actor(request).principal)


@admin_router.post("/discovery/apply", status_code=201)
async def apply_mapping(payload: DiscoveryMappingRequest, request: Request):
    """Apply one VERIFIED mapping (verified → active) as an alias row.

    Requires the apply capability (``admin_mode``). The mapping is re-verified
    against the current registry state and applied through the registry with
    ``execution_by_aether`` False — the write is reference data recorded by
    Aether, never an executed transfer. Idempotent on the lowercased alias.
    """
    _gate_apply(request)
    actor = _actor(request)
    candidate = _seam_suggests(payload)
    _require_seam_match(payload, candidate)
    verified = AssetDiscoveryPipeline.confirm(candidate, reviewer=actor.principal)
    return await AssetDiscoveryPipeline().apply(verified, actor=actor)


# ── Explicit reference-data apply (global-ADMIN + admin_mode writes) ─────────

@admin_router.post("/assets", status_code=201)
async def register_asset(payload: CanonicalAsset, request: Request):
    _gate_apply(request)
    return await RegistryAdminFacade().register_asset(_actor(request), payload)


@admin_router.post("/chains", status_code=201)
async def register_chain(payload: ChainReference, request: Request):
    _gate_apply(request)
    return await RegistryAdminFacade().register_chain(_actor(request), payload)


@admin_router.post("/fiat", status_code=201)
async def register_fiat(payload: FiatCurrencyMetadata, request: Request):
    _gate_apply(request)
    return await RegistryAdminFacade().register_fiat(_actor(request), payload)


@admin_router.post("/deployments", status_code=201)
async def register_deployment(payload: AssetDeployment, request: Request):
    _gate_apply(request)
    return await RegistryAdminFacade().register_deployment(_actor(request), payload)


@admin_router.post("/aliases", status_code=201)
async def register_alias(payload: AssetAlias, request: Request):
    _gate_apply(request)
    return await RegistryAdminFacade().register_alias(_actor(request), payload)
