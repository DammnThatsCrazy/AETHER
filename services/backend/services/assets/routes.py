"""Universal asset registry API — /v1/assets.

Read endpoints expose the canonical reference registry (global rows); write
endpoints register reference data / canonicalize native payloads. INVARIANT:
the registry is reference + observational data only — it never originates,
signs, or settles transfers. The one tenant-scoped write (canonicalize) records
UNRESOLVED references on registry_unresolved_asset_refs (execution_by_aether
always False). AETHER OBSERVES. AETHER DOES NOT EXECUTE.

Gating mirrors the stablecoin domain: every route fail-closes on
``settings.assets.api_enabled`` (default OFF) so the surface is absent until
enabled. Reads require the base READ permission; register/seed are platform
reference-data writes gated to ADMIN. shared/auth has no ``assets:*`` scope yet,
so these reuse existing constants rather than inventing one out of scope.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict

from config.settings import settings
from repositories.registry_repos import (
    RegistryAliasRepo,
    RegistryAssetRepo,
    RegistryUnresolvedAssetRepo,
)
from shared.auth.auth import Permissions
from services.assets.models import (
    AssetAlias,
    AssetDeployment,
    AssetSupportCapability,
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

router = APIRouter(prefix="/v1/assets", tags=["assets"])


def _gate(request: Request, permission: str = Permissions.READ) -> str:
    require_flag(settings.assets.api_enabled, "Universal Asset Registry")
    _require_perm(request, permission)
    return _tenant_id(request)


def _gate_ingestion(request: Request) -> str:
    require_flag(settings.assets.api_enabled, "Universal Asset Registry")
    require_flag(settings.assets.ingestion_enabled, "Asset registry ingestion")
    return _tenant_id(request)


def _stringify(rows: list[dict]) -> list[dict]:
    """Decimal-safe response encoding (registry rows currently carry no money,
    but data JSONB payloads may; canonical amounts must stay strings)."""
    from decimal import Decimal

    out = []
    for row in rows:
        encoded = {}
        for key, value in row.items():
            encoded[key] = str(value) if isinstance(value, Decimal) else value
        out.append(encoded)
    return out


class NativePayloadRequest(BaseModel):
    """A value.ts-style native payload to canonicalize/resolve.

    The registry treats native as opaque observational input and preserves it
    verbatim in the report (it never rewrites observed amount/currency).
    """

    model_config = ConfigDict(extra="ignore")

    native: dict[str, Any]


# ── Reference reads (global registry rows) ───────────────────────────────────

@router.get("/assets")
async def list_assets(
    request: Request,
    kind: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = 0,
):
    _gate(request)
    filters: dict[str, Any] = {}
    if kind:
        filters["kind"] = kind
    if symbol:
        filters["symbol"] = symbol
    rows = await RegistryAssetRepo().find_many(filters or None, limit=limit, offset=offset)
    assets = [UniversalAssetRegistry._asset_to_contract(r) for r in rows]
    return {"items": _stringify(assets), "count": len(assets)}


@router.get("/assets/{asset_id}")
async def get_asset(asset_id: str, request: Request):
    _gate(request)
    asset = await UniversalAssetRegistry().get_asset(asset_id)
    if asset is None:
        return {"asset_id": asset_id, "found": False}
    return {"asset_id": asset_id, "found": True, "asset": asset}


@router.get("/by-symbol/{symbol}")
async def resolve_asset_by_symbol(symbol: str, request: Request):
    _gate(request)
    candidates = await UniversalAssetRegistry().resolve_asset(symbol)
    return {"symbol": symbol, "candidates": _stringify(candidates), "count": len(candidates)}


@router.get("/chains")
async def list_chains(
    request: Request,
    vm: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = 0,
):
    _gate(request)
    filters: dict[str, Any] = {"vm": vm} if vm else None
    rows = await UniversalAssetRegistry().chains.find_many(filters, limit=limit, offset=offset)
    return {"items": _stringify(rows), "count": len(rows)}


@router.get("/chains/{chain_id}")
async def get_chain(chain_id: str, request: Request):
    _gate(request)
    chain = await UniversalAssetRegistry().resolve_chain(chain_id)
    if chain is None:
        return {"chain_id": chain_id, "found": False}
    return {"chain_id": chain_id, "found": True, "chain": chain}


@router.get("/deployments")
async def list_deployments(
    request: Request,
    asset_id: Optional[str] = None,
    chain_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = 0,
):
    _gate(request)
    filters: dict[str, Any] = {}
    if asset_id:
        filters["asset_id"] = asset_id
    if chain_id:
        filters["chain_id"] = chain_id
    rows = await UniversalAssetRegistry().deployments.find_many(filters or None, limit=limit, offset=offset)
    return {"items": _stringify(rows), "count": len(rows)}


@router.get("/deployments/{deployment_id}")
async def get_deployment(deployment_id: str, request: Request):
    _gate(request)
    dep = await UniversalAssetRegistry().get_deployment(deployment_id)
    if dep is None:
        return {"deployment_id": deployment_id, "found": False}
    return {"deployment_id": deployment_id, "found": True, "deployment": dep}


@router.get("/aliases")
async def list_aliases(
    request: Request,
    target_asset_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = 0,
):
    _gate(request)
    filters: dict[str, Any] = {"target_asset_id": target_asset_id} if target_asset_id else None
    rows = await RegistryAliasRepo().find_many(filters, limit=limit, offset=offset)
    return {"items": _stringify(rows), "count": len(rows)}


@router.get("/aliases/{alias}")
async def resolve_alias(alias: str, request: Request):
    _gate(request)
    row = await UniversalAssetRegistry().resolve_alias(alias)
    if row is None:
        return {"alias": alias, "found": False}
    return {"alias": alias, "found": True, "target": row}


@router.get("/meta")
async def get_registry_meta(request: Request):
    _gate(request)
    meta = await UniversalAssetRegistry().get_meta()
    return {
        "registry_version": UniversalAssetRegistry.current_registry_version(),
        "ledger": meta,
    }


# ── Tenant-scoped observational reads ────────────────────────────────────────

@router.get("/unresolved")
async def list_unresolved(
    request: Request,
    reason: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = 0,
):
    tenant_id = _gate(request)
    filters: dict[str, Any] = {"tenant_id": tenant_id}
    if reason:
        filters["reason"] = reason
    rows = await RegistryUnresolvedAssetRepo().find_many(filters, limit=limit, offset=offset)
    return {"items": _stringify(rows), "count": len(rows)}


# ── Canonicalization (observational; records unresolved refs) ────────────────
# canonicalize may write a tenant-scoped unresolved-reference record, so it
# carries the same ADMIN authorization as the sibling mutation routes (flag +
# ingestion flag + permission), not a bare READ/flag gate.

@router.post("/canonicalize", status_code=200)
async def canonicalize(payload: NativePayloadRequest, request: Request):
    tenant_id = _gate_ingestion(request)
    _require_perm(request, Permissions.ADMIN)
    report = await UniversalAssetRegistry().canonicalize(
        payload.native, tenant_id=tenant_id,
    )
    return report


# ── Reference-data registration (global rows; ADMIN-scoped writes) ───────────

@router.post("/assets", status_code=201)
async def register_asset(payload: CanonicalAsset, request: Request):
    _gate_ingestion(request)
    _require_perm(request, Permissions.ADMIN)
    return await UniversalAssetRegistry().register_asset(payload)


@router.post("/chains", status_code=201)
async def register_chain(payload: ChainReference, request: Request):
    _gate_ingestion(request)
    _require_perm(request, Permissions.ADMIN)
    return await UniversalAssetRegistry().register_chain(payload)


@router.post("/fiat", status_code=201)
async def register_fiat(payload: FiatCurrencyMetadata, request: Request):
    _gate_ingestion(request)
    _require_perm(request, Permissions.ADMIN)
    return await UniversalAssetRegistry().register_fiat(payload)


@router.post("/deployments", status_code=201)
async def register_deployment(payload: AssetDeployment, request: Request):
    _gate_ingestion(request)
    _require_perm(request, Permissions.ADMIN)
    return await UniversalAssetRegistry().register_deployment(payload)


@router.post("/aliases", status_code=201)
async def register_alias(payload: AssetAlias, request: Request):
    _gate_ingestion(request)
    _require_perm(request, Permissions.ADMIN)
    return await UniversalAssetRegistry().register_alias(payload)


@router.post("/capabilities", status_code=201)
async def register_capability(payload: AssetSupportCapability, request: Request):
    _gate_ingestion(request)
    _require_perm(request, Permissions.ADMIN)
    return await UniversalAssetRegistry().register_capability(payload)


@router.post("/seed", status_code=201)
async def seed_registry(request: Request):
    """Run the full canonical seed (fiat -> chains -> stablecoins -> aliases).

    Idempotent; the deterministic registry_version ledger row is rewritten from
    the digest. ADMIN-scoped platform operation.
    """
    _gate_ingestion(request)
    _require_perm(request, Permissions.ADMIN)
    return await UniversalAssetRegistry().seed_all()
