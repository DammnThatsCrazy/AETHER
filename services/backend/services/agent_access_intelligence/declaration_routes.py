"""Agent Access Intelligence — capability declaration API (PR 2, Phase B2, §9.3).

``/v1/capability-declarations``  declare / list / read / withdraw the capabilities a
tenant asserts it intends to have. The declared side of the identity picture; the
observed side is ``/v1/capability-catalog``.

Mirrors the conventions of ``authority_routes.py``: read ``request.state.tenant``, call
``require_permission(...)``, scope every query by ``tenant.tenant_id``, return
``APIResponse``. Service-layer errors (``BadRequestError``/``NotFoundError``) propagate to
the shared handlers rather than being re-mapped here, so a cross-tenant read fails
identically to an absent one.

**Nothing on this router verifies a publisher.** A declaration records what the tenant
asserted and who asserted it; it is not evidence about the artifact's origin, and there is
deliberately no endpoint or field that would let it be read as one (see ``identity.py``).

No lifecycle event is published: a declaration is a tenant's own statement of intent, not
a grant of authority to anyone, and inventing a new event type for it would add an
unconsumed topic to the registry. The ``declared_by_entity_id`` on the row plus the
platform audit trail are the record of who declared what.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse
from shared.logger.logger import get_logger, metrics

from services.agent_access_intelligence.declarations import capability_declaration_service

logger = get_logger("aether.service.agent_access_intelligence.declaration_routes")

capability_declarations_router = APIRouter(
    prefix="/v1/capability-declarations",
    tags=["Agent Access Intelligence"],
)


# ── Request models ────────────────────────────────────────────────────────────

class CapabilityDeclarationRequest(BaseModel):
    """At least one of ``server_name`` / ``server_url`` / ``tool_name`` is required — a
    declaration that identifies nothing is rejected by the service."""

    provider: Optional[str] = None
    server_name: Optional[str] = None
    server_url: Optional[str] = Field(
        default=None,
        description="Sanitized before storage — credentials/tokens in the URL are stripped.",
    )
    tool_name: Optional[str] = None
    protocol_version: Optional[str] = None
    capability_kind: Optional[str] = None
    notes: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# CAPABILITY DECLARATIONS
# ══════════════════════════════════════════════════════════════════════════════

@capability_declarations_router.post("")
async def declare_capability(body: CapabilityDeclarationRequest, request: Request):
    """Declare a capability the tenant intends to have (upsert).

    Re-declaring the same ``(provider, server, tool)`` updates that declaration instead of
    creating a second one, so a capability never carries two competing declared digests."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    declared_by = tenant.user_id or tenant.tenant_id

    record = await capability_declaration_service.declare(
        tenant_id=tenant.tenant_id,
        declared_by_entity_id=declared_by,
        provider=body.provider,
        server_name=body.server_name,
        server_url=body.server_url,
        tool_name=body.tool_name,
        protocol_version=body.protocol_version,
        capability_kind=body.capability_kind,
        notes=body.notes,
    )
    metrics.increment(
        "capability_declarations_written",
        labels={"has_publisher_ref": "true" if record.get("publisher_ref") else "false"},
    )
    return APIResponse(data=record).to_dict()


@capability_declarations_router.get("")
async def list_declarations(
    request: Request,
    provider: Optional[str] = Query(default=None),
    server_name: Optional[str] = Query(default=None),
    capability_id: Optional[str] = Query(
        default=None,
        description="The observed-catalog capability id this declaration is keyed to.",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    tenant = request.state.tenant
    tenant.require_permission("read")
    rows = await capability_declaration_service.list(
        tenant_id=tenant.tenant_id,
        provider=provider,
        server_name=server_name,
        capability_id=capability_id,
        limit=limit,
        offset=offset,
    )
    return APIResponse(data={"items": rows, "count": len(rows)}).to_dict()


@capability_declarations_router.get("/{declaration_id}")
async def read_declaration(declaration_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    return APIResponse(
        data=await capability_declaration_service.get(
            tenant_id=tenant.tenant_id, declaration_id=declaration_id
        )
    ).to_dict()


@capability_declarations_router.delete("/{declaration_id}")
async def withdraw_declaration(declaration_id: str, request: Request):
    """Withdraw a declaration (hard delete); returns the record that was removed.

    A withdrawn declaration stops contributing a drift verdict immediately — it is
    removed rather than flagged, so no later reader can mistake it for a live assertion."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    record = await capability_declaration_service.withdraw(
        tenant_id=tenant.tenant_id, declaration_id=declaration_id
    )
    metrics.increment("capability_declarations_withdrawn")
    return APIResponse(data=record).to_dict()
