"""Conversion CRUD + attribution endpoint — canonical_conversions."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, NotFoundError, BadRequestError
from shared.logger.logger import get_logger
from services.measurement.repositories.conversion_repo import ConversionRepository
from services.measurement.repositories.adjustment_repo import AdjustmentRepository
from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
from services.measurement.engine.attribution_engine import AttributionEngine
from services.measurement.engine.subscription_ltv import SubscriptionLTVService

logger = get_logger("aether.measurement.routes.conversions")
router = APIRouter(prefix="/v1/conversions", tags=["Conversions"])

_conversion_repo = ConversionRepository()
_adjustment_repo = AdjustmentRepository()
_run_repo = AttributionRunRepository()
_engine = AttributionEngine()
_ltv_service = SubscriptionLTVService()


def _require_tenant(request: Request):
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        from shared.common.common import UnauthorizedError
        raise UnauthorizedError("Authentication required")
    return tenant


class RecomputeRequest(BaseModel):
    model_type: str = "last_touch"
    lookback_hours: int = Field(720, ge=1, le=8760)


class RenewalAttributionRequest(BaseModel):
    pass  # body reserved for future options


@router.get("")
async def list_conversions(
    request: Request,
    conversion_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    profile_id: Optional[str] = Query(None),
    after: Optional[str] = Query(None, description="ISO datetime lower bound on occurred_at"),
    before: Optional[str] = Query(None, description="ISO datetime upper bound on occurred_at"),
    attribution_eligible_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    cursor: Optional[str] = Query(None),
):
    tenant = _require_tenant(request)
    after_dt = _parse_ts(after) if after else None
    before_dt = _parse_ts(before) if before else None

    if profile_id:
        rows = await _conversion_repo.list_by_profile(
            tenant.tenant_id, profile_id,
            conversion_type=conversion_type,
            status=status,
            after_occurred=after_dt,
            before_occurred=before_dt,
            attribution_eligible_only=attribution_eligible_only,
            limit=limit,
            cursor=cursor,
        )
    else:
        rows = await _conversion_repo.list_by_tenant(
            tenant.tenant_id,
            after_occurred=after_dt,
            before_occurred=before_dt,
            attribution_eligible_only=attribution_eligible_only,
            limit=limit,
            cursor=cursor,
        )

    next_cursor = rows[-1].get("occurred_at") if len(rows) == limit else None
    return {
        "data": rows,
        "pagination": {
            "limit": limit,
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None,
        },
    }


@router.get("/{conversion_id}")
async def get_conversion(conversion_id: str, request: Request):
    tenant = _require_tenant(request)
    row = await _conversion_repo.get(tenant.tenant_id, conversion_id)
    if row is None:
        raise NotFoundError("Conversion")
    return APIResponse(data=row).to_dict()


@router.get("/{conversion_id}/journey")
async def get_conversion_journey(conversion_id: str, request: Request):
    tenant = _require_tenant(request)
    conversion = await _conversion_repo.get(tenant.tenant_id, conversion_id)
    if conversion is None:
        raise NotFoundError("Conversion")

    from services.measurement.repositories.journey_repo import JourneyRepository
    journey_repo = JourneyRepository()
    profile_id = conversion.get("profile_id") or conversion.get("cluster_id")
    if not profile_id:
        return APIResponse(data=None, meta={"reason": "no_profile"}).to_dict()

    journeys = await journey_repo.find_current_for_profile(tenant.tenant_id, profile_id)
    return APIResponse(data=journeys[0] if journeys else None).to_dict()


@router.get("/{conversion_id}/attribution")
async def get_conversion_attribution(conversion_id: str, request: Request):
    tenant = _require_tenant(request)
    conversion = await _conversion_repo.get(tenant.tenant_id, conversion_id)
    if conversion is None:
        raise NotFoundError("Conversion")

    active_run = await _run_repo.get_active_run(tenant.tenant_id, conversion_id)
    credits = []
    if active_run:
        credits = await _run_repo.list_credits_for_run(tenant.tenant_id, active_run["attribution_run_id"])

    return APIResponse(data={
        "conversion": conversion,
        "active_run": active_run,
        "credits": credits,
        "credit_count": len(credits),
    }).to_dict()


@router.get("/{conversion_id}/adjustments")
async def get_conversion_adjustments(conversion_id: str, request: Request):
    tenant = _require_tenant(request)
    conversion = await _conversion_repo.get(tenant.tenant_id, conversion_id)
    if conversion is None:
        raise NotFoundError("Conversion")

    adjustments = await _adjustment_repo.list_for_conversion(tenant.tenant_id, conversion_id)
    net = await _adjustment_repo.net_adjustment(tenant.tenant_id, conversion_id)
    return APIResponse(data={
        "conversion_id": conversion_id,
        "adjustments": adjustments,
        "net_adjustment": str(net),
    }).to_dict()


@router.post("/{conversion_id}/recompute")
async def recompute_attribution(conversion_id: str, request: Request, body: RecomputeRequest):
    tenant = _require_tenant(request)
    try:
        run = await _engine.run_for_conversion(
            tenant.tenant_id,
            conversion_id,
            model_type=body.model_type,
            lookback_hours=body.lookback_hours,
            trigger_reason="manual_recompute",
        )
    except ValueError as exc:
        raise BadRequestError(str(exc))

    return APIResponse(data=run, meta={"triggered": True}).to_dict()


@router.post("/{conversion_id}/attribute-renewal")
async def attribute_renewal_conversion(conversion_id: str, request: Request):
    """Attribute a renewal conversion by inheriting acquisition touchpoint weights.

    For subscription_renewed and invoice_paid conversions, this endpoint finds the
    original acquisition conversion (subscription_started/trial_converted) for the
    same subscription_id and propagates its attribution credits — scaled to this
    renewal's net_value — without re-running the full attribution engine.

    Returns the new attribution run with inherited credits.
    """
    tenant = _require_tenant(request)
    try:
        run = await _ltv_service.attribute_renewal(tenant.tenant_id, conversion_id)
    except ValueError as exc:
        raise BadRequestError(str(exc))
    return APIResponse(data=run, meta={"triggered": True, "method": "subscription_renewal"}).to_dict()


@router.get("/subscriptions/{subscription_id}/ltv")
async def get_subscription_ltv(
    subscription_id: str,
    request: Request,
    include_pending: bool = Query(False),
):
    """Return cumulative LTV metrics for a subscription.

    Aggregates net_value across all conversions sharing the same subscription_id,
    from acquisition through renewals to cancellation. Excludes pending conversions
    unless include_pending=true.
    """
    tenant = _require_tenant(request)
    ltv = await _ltv_service.compute_ltv(
        tenant.tenant_id, subscription_id, include_pending=include_pending
    )
    return APIResponse(data=ltv).to_dict()


@router.get("/cohort-ltv")
async def get_cohort_ltv(
    request: Request,
    cohort_month: str = Query(..., description="Cohort acquisition month in YYYY-MM format"),
    conversion_type: str = Query("subscription_started"),
    limit: int = Query(1000, ge=1, le=5000),
):
    """Return aggregate LTV metrics for a subscription acquisition cohort.

    Identifies all subscriptions that started in the given cohort_month and
    computes cohort-level LTV: total, average, median, avg renewals.
    """
    tenant = _require_tenant(request)
    try:
        cohort = await _ltv_service.compute_cohort_ltv(
            tenant.tenant_id,
            cohort_month,
            conversion_type=conversion_type,
            limit=limit,
        )
    except ValueError as exc:
        raise BadRequestError(str(exc))
    return APIResponse(data=cohort).to_dict()


def _parse_ts(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
