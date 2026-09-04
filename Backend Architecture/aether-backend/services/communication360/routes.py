"""Communication360 — read-only projection routes at ``/v1/communication360``.

The communication360 projection is a **read-only intelligence projection** over
the shipped comms silver path (``services/comms`` → ``silver_comms_facts``) and
the ratified information / knowledge / participant authorities (Phase 2 R1–R5).
These routes expose that projection as a tenant-scoped API under the
``/v1/communication360`` prefix:

* ``GET /v1/communication360/{subject_kind}/{subject_id}`` — run the
  communication360 projection for the requesting tenant. Tenant scope is
  server-authoritative (the handler derives ``tenantId`` from the authenticated
  tenant, never from the path), and the route is gated on the canonical ``read``
  permission plus the projection's ``communication360.read`` capability key
  (declared in the projection registry; enforced at the platform
  route-classification boundary — ``config/route_registry.yaml`` — and asserted
  honestly here).
* ``GET /v1/communication360/health`` — read-only plane probe: whether the
  communication360 provider is registered and contract-compatible.

The handler composes a :class:`ProjectionRequest
<shared.intelligence_projections.contracts.ProjectionRequest>` and executes it
through the fail-isolated :class:`ProviderRegistry
<shared.intelligence_projections.registry.ProviderRegistry>` (defaults to the
plane's global ``projection_registry``; a registry may be injected via
:func:`create_router` for tests / alternate wiring). There is NO write path —
every route is a GET. The router is mounted flag-gated
(``AETHER_COMMUNICATION360_ENABLED``, default OFF) so the surface costs nothing
while disabled and is registered + reachable only when the plane is wired.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from shared.common.common import ForbiddenError
from shared.intelligence_projections.contracts import (
    ProjectionRequest,
    ProjectionSubject,
)
from shared.intelligence_projections.errors import (
    ProjectionError,
    ProjectionNotFound,
)
from shared.intelligence_projections.generated_registry import (
    PROJECTION_CAPABILITY_MAP,
)
from shared.intelligence_projections.registry import projection_registry

__all__ = [
    "EXPLORE_CAPABILITY",
    "PROJECTION_ID",
    "READ_CAPABILITY",
    "create_router",
    "router",
]

PROJECTION_ID = "communication360"
READ_CAPABILITY = "communication360.read"
EXPLORE_CAPABILITY = "communication360.explore"


def _only_projection_id_literal_errors(exc: ValidationError) -> bool:
    """True when every error is the projectionId Literal rejection only."""
    errors = exc.errors()
    if not errors:
        return False
    for err in errors:
        if err.get("type") != "literal_error" or err.get("loc") != ("projectionId",):
            return False
    return True


def _build_projection_request(
    *,
    projection_id: str,
    tenant_id: str,
    subject: ProjectionSubject,
) -> ProjectionRequest:
    """Build a strict :class:`ProjectionRequest`, tolerating a not-yet-registered id."""
    try:
        return ProjectionRequest(
            projectionId=projection_id,
            tenantId=tenant_id,
            subject=subject,
        )
    except ValidationError as exc:
        if not _only_projection_id_literal_errors(exc):
            raise
        return ProjectionRequest.model_construct(
            projectionId=projection_id,
            tenantId=tenant_id,
            subject=subject,
        )


def _require_communication360_read(request: Request) -> str:
    """Tenant-scoped read gate for the communication360 surface.

    Enforces the canonical tenant read permission and asserts the projection's
    ``communication360.read`` capability key is genuinely declared for the
    projection (a contradiction fails closed). Returns the authenticated
    tenant id — the only tenant the projection may be asked about.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")

    declared = PROJECTION_CAPABILITY_MAP.get(PROJECTION_ID)
    # Fail CLOSED on absence, not just contradiction: a projection whose
    # capabilityKeys are not declared in the registry (e.g. the generated map
    # predates the row) must not silently open a read gate.
    if declared is None or READ_CAPABILITY not in declared:
        raise ForbiddenError(
            f"{READ_CAPABILITY!r} is not a declared capability for "
            f"{PROJECTION_ID!r}"
        )
    return tenant.tenant_id


def _registry_health(registry: Any) -> dict[str, Any]:
    """Read-only plane probe for the communication360 provider.

    Uses the registry's pure ``availability()`` introspection — never infers
    readiness from import or registration success.
    """
    availability = {}
    if hasattr(registry, "availability"):
        availability = registry.availability().get(PROJECTION_ID, {})
    return {
        "projectionId": PROJECTION_ID,
        "graphMutationPolicy": "read_only",
        "availability": availability,
        "capabilityKeys": [READ_CAPABILITY, EXPLORE_CAPABILITY],
    }


def create_router(registry: Any = projection_registry) -> APIRouter:
    """Build the ``/v1/communication360`` router bound to ``registry``.

    ``registry`` is a :class:`ProviderRegistry
    <shared.intelligence_projections.registry.ProviderRegistry>`-shaped object
    (defaults to the plane's global ``projection_registry``). Tests inject a
    double to exercise the handlers without a live plane.
    """
    r = APIRouter(prefix="/v1/communication360", tags=["Communication 360"])

    @r.get(
        "/{subject_kind}/{subject_id}",
        summary="Run the Communication360 projection for the requesting tenant",
    )
    async def get_communication360_projection(
        subject_kind: str,
        subject_id: str,
        request: Request,
    ) -> dict[str, Any]:
        tenant_id = _require_communication360_read(request)
        projection_request = _build_projection_request(
            projection_id=PROJECTION_ID,
            tenant_id=tenant_id,
            subject=ProjectionSubject(kind=subject_kind, id=subject_id),
        )
        try:
            result = await registry.project(PROJECTION_ID, projection_request)
        except ProjectionNotFound as exc:
            raise HTTPException(
                status_code=503,
                detail=f"{PROJECTION_ID} projection provider is not registered",
            ) from exc
        except ProjectionError as exc:
            raise HTTPException(
                status_code=503,
                detail="communication360 projection unavailable",
            ) from exc
        return result.model_dump(mode="json")

    @r.get(
        "/health",
        summary="Communication360 provider plane probe (read-only)",
    )
    async def communication360_health() -> dict[str, Any]:
        return _registry_health(registry)

    return r


# Module-level router (mountable by app wiring) bound to the plane's global
# registry.
router = create_router()
