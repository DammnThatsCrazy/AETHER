"""Optional read-only DSR propagation route (prompt §3.11).

NOT wired into main.py. Integrator: mount ``services.dsr_propagation.routes:router``
(prefix ``/v1/dsr``). Read-only status lookup, gated by ``tenant_actor`` +
``require_permission("consent:manage")`` and tenant-scoped fail-closed (a
cross-tenant request_id reads as 404).
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from shared.common.common import APIResponse
from shared.logger.logger import get_logger

from services.security.request_context import tenant_actor

from .service import DSRPropagationService

logger = get_logger("aether.dsr_propagation.routes")
router = APIRouter(prefix="/v1/dsr", tags=["DSR Propagation"])

_service = DSRPropagationService()

# Permission required to read DSR propagation records — matches the existing
# consent DSR endpoints (services/consent/routes.py uses "consent:manage").
_DSR_READ_PERMISSION = "consent:manage"


@router.get("/propagation/{request_id}")
async def get_propagation_status(request_id: str, request: Request) -> dict:
    """Return the per-component propagation status for a DSR request."""
    actor = tenant_actor(request)
    request.state.tenant.require_permission(_DSR_READ_PERMISSION)
    result = await _service.status(request_id, tenant_id=actor.tenant_id)
    return APIResponse(data=result).to_dict()
