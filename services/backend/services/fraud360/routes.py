"""Fraud360 — read-only projection routes at ``/v1/fraud360`` (Phase 4).

The fraud360 projection is a **read-only domain-synthesis intelligence
projection** over canonical Aether truth (ADR-010). These routes expose that
projection as a tenant-scoped API under the ``/v1/fraud360`` prefix:

* ``GET /v1/fraud360/{subject_kind}/{subject_id}`` — run the fraud360 projection
  for the requesting tenant over one subject. Tenant scope is
  server-authoritative (the handler derives ``tenantId`` from the authenticated
  tenant, never from the path), and the route is gated on the canonical ``read``
  permission plus the projection's ``fraud360.read`` capability key (declared in
  the projection registry and asserted honestly here). Subject kinds are
  restricted to the fraud360 registry row's set — ``entity`` / ``relationship`` /
  ``agent`` — and anything else fails closed.
* ``GET /v1/fraud360/health`` — read-only plane probe: whether the fraud360
  provider is registered and contract-compatible.

The handler composes a :class:`ProjectionRequest
<shared.intelligence_projections.contracts.ProjectionRequest>` (via the
provider's :func:`build_projection_request
<services.fraud360.provider.build_projection_request>`) and executes it through
the fail-isolated :class:`ProviderRegistry
<shared.intelligence_projections.registry.ProviderRegistry>` (defaults to the
plane's global ``projection_registry``; a registry may be injected via
:func:`create_router` for tests / alternate wiring). There is NO write path —
every route is a GET.
"""

from __future__ import annotations

from typing import Any, Final

from fastapi import APIRouter, HTTPException, Request

from shared.common.common import ForbiddenError
from shared.intelligence_projections.contracts import ProjectionSubject
from shared.intelligence_projections.errors import (
    ProjectionError,
    ProjectionNotFound,
)
from shared.intelligence_projections.generated_registry import (
    PROJECTION_CAPABILITY_MAP,
)
from shared.intelligence_projections.registry import projection_registry
from services.fraud360.provider import (
    PROJECTION_ID,
    build_projection_request,
)

__all__ = [
    "EXPLORE_CAPABILITY",
    "PROJECTION_ID",
    "READ_CAPABILITY",
    "create_router",
    "router",
]

READ_CAPABILITY = "fraud360.read"
EXPLORE_CAPABILITY = "fraud360.explore"

# The fraud360 registry row projects over exactly these subject kinds (do NOT
# invent new ones here). A request for any other kind fails closed.
_SUBJECT_KINDS: Final[frozenset[str]] = frozenset(
    {"entity", "relationship", "agent"}
)


def _require_fraud360_read(request: Request) -> str:
    """Tenant-scoped read gate for the fraud360 surface.

    Enforces the canonical tenant read permission and asserts the projection's
    ``fraud360.read`` capability key is genuinely declared for the projection
    (a contradiction fails closed). Returns the authenticated tenant id — the
    only tenant the projection may be asked about.
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
    """Read-only plane probe for the fraud360 provider.

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
    """Build the ``/v1/fraud360`` router bound to ``registry``.

    ``registry`` is a :class:`ProviderRegistry
    <shared.intelligence_projections.registry.ProviderRegistry>`-shaped object
    (defaults to the plane's global ``projection_registry``). Tests inject a
    double to exercise the handlers without a live plane.
    """
    r = APIRouter(prefix="/v1/fraud360", tags=["Fraud 360"])

    @r.get(
        "/{subject_kind}/{subject_id}",
        summary="Run the Fraud360 projection for the requesting tenant",
    )
    async def get_fraud360_projection(
        subject_kind: str,
        subject_id: str,
        request: Request,
    ) -> dict[str, Any]:
        tenant_id = _require_fraud360_read(request)
        # Fail closed on subject kinds fraud360 does not project over — an empty
        # projection for a kind this 360 does not own would be misleading.
        if subject_kind not in _SUBJECT_KINDS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"fraud360 does not project over subject_kind={subject_kind!r}; "
                    "supported kinds are entity, relationship, agent"
                ),
            )
        projection_request = build_projection_request(
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
                detail="fraud360 projection unavailable",
            ) from exc
        return result.model_dump(mode="json")

    @r.get(
        "/health",
        summary="Fraud360 provider plane probe (read-only)",
    )
    async def fraud360_health() -> dict[str, Any]:
        return _registry_health(registry)

    return r


# Module-level router (mountable by app wiring) bound to the plane's global
# registry.
router = create_router()
