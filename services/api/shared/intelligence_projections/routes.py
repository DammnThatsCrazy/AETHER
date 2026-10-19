"""Tenant-scoped API for composing catalogued product 360 frames.

This route is the single backend entry point for all 18 product surfaces. It
derives tenant scope from authenticated request state, evaluates policy before
projection reads, and delegates the frame to the projection plane. Until the
application installs an alternate policy evaluator, requests use the central
AccessControlService through a request-bound adapter. Malformed policy wiring
or unclassified catalog authorities fail closed before any provider reads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, ValidationError

from graph.operational_intelligence.models import PageRequest, TimeRangeFilter
from shared.intelligence_projections.contracts import (
    Experience360FrameRequest,
    Experience360PolicyDisposition,
    Experience360PolicyEvaluation,
    Experience360SurfaceId,
    ProjectionSubject,
)
from shared.intelligence_projections.errors import ProjectionError, ProjectionNotFound
from shared.intelligence_projections.frame_runtime import build_experience360_frame
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTION_DEFINITIONS,
    PRODUCT_360_SURFACE_CATALOG_VERSION,
    PRODUCT_360_SURFACE_DEFINITIONS,
    PRODUCT_360_SURFACE_IDS,
)
from shared.intelligence_projections.policy import RequestAccessPolicyEvaluator
from shared.intelligence_projections.registry import projection_registry

router = APIRouter(prefix="/v1/experience360", tags=["Experience 360"])


class Experience360FrameBody(BaseModel):
    """Caller-controlled request fields; tenant identity is auth-derived."""

    model_config = ConfigDict(extra="forbid")

    surfaceId: Experience360SurfaceId
    subject: ProjectionSubject
    requestedSlotIds: Optional[list[str]] = None
    asOf: Optional[str] = None
    timeRange: Optional[TimeRangeFilter] = None
    includeEvidence: bool = True
    lensIds: Optional[list[str]] = None
    page: Optional[PageRequest] = None
    purpose: Optional[str] = None
    authorizationContextRef: Optional[str] = None


class _UnavailablePolicyEvaluator:
    """Fail-closed adapter used when the configured evaluator is malformed."""

    async def evaluate(self, request: Experience360FrameRequest) -> Experience360PolicyEvaluation:
        evaluated_at = datetime.now(timezone.utc).isoformat()
        return Experience360PolicyEvaluation(
            surfaceId=request.surfaceId,
            tenantId=request.tenantId,
            evaluatedAt=evaluated_at,
            frameDisposition=Experience360PolicyDisposition(
                state="unknown",
                evaluatedAt=evaluated_at,
                reasonCodes=["policy_evaluator_unavailable"],
            ),
        )


_unavailable_policy_evaluator = _UnavailablePolicyEvaluator()


def _tenant_id_for_read(request: Request) -> str:
    tenant = request.state.tenant
    tenant.require_permission("read")
    return str(tenant.tenant_id)


def _assert_surface_bindings_are_declared(surface_id: str) -> None:
    """Reject catalog drift where a bound projection is absent from the registry."""

    surface = PRODUCT_360_SURFACE_DEFINITIONS.get(surface_id)
    if not isinstance(surface, dict):
        raise ProjectionNotFound("unknown product 360 surface", context={"surfaceId": surface_id})
    known_projections = {
        binding.get("projectionId")
        for slot in surface.get("domainSlots", [])
        if isinstance(slot, dict)
        for binding in slot.get("projectionBindings", [])
        if isinstance(binding, dict)
    }
    unknown_projections = sorted(
        projection_id
        for projection_id in known_projections
        if projection_id not in INTELLIGENCE_PROJECTION_DEFINITIONS
    )
    if unknown_projections:
        raise ProjectionError(
            "360 catalog binds a projection missing from the technical registry",
            context={"surfaceId": surface_id, "projectionIds": unknown_projections},
        )


@router.post("/frames", summary="Compose a governed product 360 frame")
async def post_experience360_frame(
    body: Experience360FrameBody,
    request: Request,
) -> dict[str, Any]:
    """Build any catalogued 360 surface for the authenticated tenant."""

    tenant_id = _tenant_id_for_read(request)
    surface_id = str(body.surfaceId)
    surface = PRODUCT_360_SURFACE_DEFINITIONS.get(surface_id)
    if not isinstance(surface, dict):
        raise HTTPException(status_code=404, detail="unknown 360 surface")
    supported_subject_kinds = surface.get("subjectKinds", [])
    if supported_subject_kinds and body.subject.kind not in supported_subject_kinds:
        raise HTTPException(
            status_code=422, detail="subject kind is not supported by this 360 surface"
        )
    known_slot_ids = {
        slot.get("id")
        for slot in surface.get("domainSlots", [])
        if isinstance(slot, dict) and isinstance(slot.get("id"), str)
    }
    if body.requestedSlotIds is not None and set(body.requestedSlotIds) - known_slot_ids:
        raise HTTPException(status_code=422, detail="request names an unknown 360 slot")
    _assert_surface_bindings_are_declared(surface_id)
    try:
        frame_request = Experience360FrameRequest(
            surfaceId=body.surfaceId,
            tenantId=tenant_id,
            subject=body.subject,
            requestedSlotIds=body.requestedSlotIds,
            asOf=body.asOf,
            timeRange=body.timeRange,
            includeEvidence=body.includeEvidence,
            lensIds=body.lensIds,
            page=body.page,
            purpose=body.purpose,
            authorizationContextRef=body.authorizationContextRef,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="invalid 360 frame request") from exc
    policy_evaluator = getattr(request.app.state, "experience360_policy_evaluator", None)
    if policy_evaluator is None:
        # Reuse the repository's central role/domain/scope authorization
        # authority. It evaluates every catalog authority domain before the
        # frame runtime begins any projection read.
        policy_evaluator = RequestAccessPolicyEvaluator(request)
    if not callable(getattr(policy_evaluator, "evaluate", None)):
        # A malformed or untrusted app-state value must not open a read path.
        policy_evaluator = _unavailable_policy_evaluator

    try:
        frame = await build_experience360_frame(
            frame_request,
            policy_evaluator=policy_evaluator,
            projection_runtime=getattr(request.app.state, "experience360_projection_runtime", None),
            account360_provider=getattr(
                request.app.state, "experience360_account360_provider", None
            ),
            identity360_provider=getattr(
                request.app.state, "experience360_identity360_provider", None
            ),
            freshness_by_slot=getattr(request.app.state, "experience360_freshness_by_slot", None),
            quality_by_slot=getattr(request.app.state, "experience360_quality_by_slot", None),
            actor_attribution_by_slot=getattr(
                request.app.state, "experience360_actor_attribution_by_slot", None
            ),
        )
    except ProjectionNotFound as exc:
        raise HTTPException(status_code=404, detail="360 surface or provider not found") from exc
    except ProjectionError as exc:
        raise HTTPException(status_code=503, detail="360 frame unavailable") from exc
    return frame.model_dump(mode="json", exclude_none=True)


@router.get("/catalog", summary="List the registered product 360 surfaces")
async def get_experience360_catalog(request: Request) -> dict[str, Any]:
    """Expose catalog contracts alongside actual provider registration state."""

    _tenant_id_for_read(request)
    availability = projection_registry.availability()
    return {
        "catalogVersion": PRODUCT_360_SURFACE_CATALOG_VERSION,
        "surfaces": [
            {
                "id": surface_id,
                "definition": PRODUCT_360_SURFACE_DEFINITIONS[surface_id],
                "providerAvailability": {
                    projection_id: availability.get(
                        projection_id,
                        {"registered": False, "contractCompatible": False},
                    )
                    for projection_id in sorted(
                        {
                            binding["projectionId"]
                            for slot in PRODUCT_360_SURFACE_DEFINITIONS[surface_id].get(
                                "domainSlots", []
                            )
                            for binding in slot.get("projectionBindings", [])
                        }
                    )
                },
            }
            for surface_id in PRODUCT_360_SURFACE_IDS
        ],
    }


__all__ = ["Experience360FrameBody", "post_experience360_frame", "router"]
