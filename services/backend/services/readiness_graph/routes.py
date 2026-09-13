"""Capability readiness-graph routes.

Tenant surface (read-only)::

    GET /v1/tenant/readiness-graph/{capability}
        The calling tenant's dependency-graph readiness for one capability,
        returned with BOTH machine-readable fields (``overall``, ``nodes``,
        ``blockers``) and operator-readable text (``summary``, ``operator_text``).

Operator surface (Kyber-gated, no tenant data beyond what is asked for)::

    GET /v1/kyber/readiness-graph/{capability}?tenant_id=<optional>
        The same graph for any tenant id (empty = global/unscoped state).

Neither route mutates state — the graph is a pure read. Mutation (promotion/
demotion) is the job of the evidence paths and the revalidation worker.

NOT wired into ``main.py`` — the integrator should ``include_router`` the
``router`` and ``kyber_router`` (see wiringNeeds).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from shared.auth.auth import TenantContext
from shared.common.common import APIResponse
from shared.decorators import require_permission
from shared.logger.logger import get_logger

from services.security.request_context import require_kyber_operator, tenant_actor

from .graph import ReadinessGraphEngine, build_default_engine

logger = get_logger("aether.readiness_graph.routes")

router = APIRouter(
    prefix="/v1/tenant/readiness-graph",
    tags=["Capability Readiness Graph"],
)
kyber_router = APIRouter(
    prefix="/v1/kyber/readiness-graph",
    tags=["Kyber Readiness Graph"],
    dependencies=[Depends(require_kyber_operator)],
)

#: Default engine wired with the canonical resolvers. The integration pass may
#: replace this with a factory that injects a live worker-health provider.
_engine: ReadinessGraphEngine = build_default_engine()


@router.get("/{capability}")
async def get_capability_readiness_graph(
    capability: str,
    request: Request,
    _tenant: TenantContext = Depends(require_permission("read")),
) -> dict:
    """Return the calling tenant's readiness graph for ``capability``.

    Read-only. The tenant id is always taken from the authenticated request
    context — never from the path or query.
    """
    actor = tenant_actor(request)
    tenant_id = actor.tenant_id or ""
    result = await _engine.resolve(capability, tenant_id)
    return APIResponse(data=result.to_view()).to_dict()


@kyber_router.get("/{capability}")
async def get_operator_readiness_graph(
    capability: str,
    request: Request,
    tenant_id: str = "",
) -> dict:
    """Kyber operator view of the readiness graph for any ``tenant_id``.

    Returns the same machine-readable + operator-readable representation as the
    tenant route; ``tenant_id`` may be omitted for global/unscoped state.
    """
    result = await _engine.resolve(capability, tenant_id or "")
    return APIResponse(data=result.to_view()).to_dict()
