"""Product Catalog API — /v1/product-catalog.

Tenant-scoped catalog + instrumentation mapping registry. Flag-gated INSIDE
every handler via ``settings.product_intelligence.catalog_enabled``: when the
flag is off the surface answers 404 (NotFoundError), indistinguishable from an
unmounted route. Reads require the ``read`` permission, writes ``write``.
POST /manifest/validate never persists — validate + dry-run diff only.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict

from config.settings import settings
from shared.auth.auth import TenantContext
from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger

from services.product_catalog.manifest import dry_run_diff, manifest_to_nodes, validate_manifest
from services.product_catalog.models import CatalogNode, MappingProposal, MappingRule
from services.product_catalog.store import (
    ProductCatalogNodeRepository,
    ProductMappingProposalRepository,
    ProductMappingRuleRepository,
)

logger = get_logger("aether.service.product_catalog")
router = APIRouter(prefix="/v1/product-catalog", tags=["Product Catalog"])

_nodes = ProductCatalogNodeRepository()
_rules = ProductMappingRuleRepository()
_proposals = ProductMappingProposalRepository()


def _require_enabled() -> None:
    if not settings.product_intelligence.catalog_enabled:
        raise NotFoundError("product catalog (feature not enabled)")


def _tenant(request: Request, permission: str) -> TenantContext:
    _require_enabled()
    tenant: TenantContext = request.state.tenant
    tenant.require_permission(permission)
    return tenant


def _bind_tenant(payload_tenant_id: Optional[str], tenant: TenantContext) -> str:
    if payload_tenant_id and payload_tenant_id != tenant.tenant_id:
        raise ForbiddenError("tenant_id does not match authenticated tenant")
    return tenant.tenant_id


# ── Catalog nodes ───────────────────────────────────────────────────────────

@router.get("/nodes")
async def list_nodes(
    request: Request,
    kind: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> APIResponse:
    tenant = _tenant(request, "read")
    nodes = await _nodes.list_nodes(tenant.tenant_id, kind=kind, status=status, limit=limit, offset=offset)
    return APIResponse(data={"nodes": [n.model_dump() for n in nodes]})


@router.post("/nodes")
async def upsert_node(request: Request, payload: CatalogNode) -> APIResponse:
    tenant = _tenant(request, "write")
    tenant_id = _bind_tenant(payload.tenant_id, tenant)
    node = payload.model_copy(update={"tenant_id": tenant_id})
    stored = await _nodes.upsert_node(tenant_id, node)
    return APIResponse(data={"node": stored.model_dump()})


@router.get("/nodes/{stable_id}")
async def get_node(request: Request, stable_id: str) -> APIResponse:
    tenant = _tenant(request, "read")
    node = await _nodes.get_node(tenant.tenant_id, stable_id)
    if node is None:
        raise NotFoundError("catalog node")
    return APIResponse(data={"node": node.model_dump()})


# ── Mapping rules ───────────────────────────────────────────────────────────

@router.get("/mapping-rules")
async def list_mapping_rules(
    request: Request,
    match_kind: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> APIResponse:
    tenant = _tenant(request, "read")
    rules = await _rules.list_rules(tenant.tenant_id, match_kind=match_kind, limit=limit, offset=offset)
    return APIResponse(data={"rules": [r.model_dump() for r in rules]})


@router.post("/mapping-rules")
async def upsert_mapping_rule(request: Request, payload: MappingRule) -> APIResponse:
    tenant = _tenant(request, "write")
    tenant_id = _bind_tenant(payload.tenant_id, tenant)
    rule = payload.model_copy(update={"tenant_id": tenant_id})
    stored = await _rules.upsert_rule(tenant_id, rule)
    return APIResponse(data={"rule": stored.model_dump()})


# ── Mapping proposals ───────────────────────────────────────────────────────

@router.get("/proposals")
async def list_proposals(
    request: Request,
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> APIResponse:
    tenant = _tenant(request, "read")
    proposals = await _proposals.list_proposals(tenant.tenant_id, status=status, limit=limit, offset=offset)
    return APIResponse(data={"proposals": [p.model_dump() for p in proposals]})


@router.post("/proposals")
async def upsert_proposal(request: Request, payload: MappingProposal) -> APIResponse:
    tenant = _tenant(request, "write")
    tenant_id = _bind_tenant(payload.tenant_id, tenant)
    proposal = payload.model_copy(update={"tenant_id": tenant_id})
    stored = await _proposals.upsert_proposal(tenant_id, proposal)
    return APIResponse(data={"proposal": stored.model_dump()})


# ── Manifest (instrumentation-as-code) ──────────────────────────────────────

class ManifestValidateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: dict[str, Any]


@router.post("/manifest/validate")
async def validate_manifest_route(request: Request, payload: ManifestValidateIn) -> APIResponse:
    """Validate a manifest and dry-run diff it against the stored catalog.

    Never persists anything — this is the pre-flight for instrumentation-as-code.
    """
    tenant = _tenant(request, "read")
    errors = validate_manifest(payload.manifest)
    if errors:
        return APIResponse(data={"valid": False, "errors": errors, "diff": None})
    desired = manifest_to_nodes(payload.manifest, tenant.tenant_id)
    existing = await _nodes.list_nodes(tenant.tenant_id, limit=500)
    diff = dry_run_diff(desired, existing)
    return APIResponse(data={"valid": True, "errors": [], "diff": diff})
