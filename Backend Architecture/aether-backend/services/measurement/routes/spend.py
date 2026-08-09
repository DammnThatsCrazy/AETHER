"""Spend ingestion, reconciliation, and list endpoints."""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError
from shared.logger.logger import get_logger
from services.measurement.repositories.spend_repo import SpendRepository

logger = get_logger("aether.measurement.routes.spend")
router = APIRouter(prefix="/v1/spend", tags=["Spend"])

_spend_repo = SpendRepository()


def _require_tenant(request: Request):
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        from shared.common.common import UnauthorizedError
        raise UnauthorizedError("Authentication required")
    return tenant


class SpendRecordInput(BaseModel):
    platform: str
    campaign_id: Optional[str] = None
    ad_account_id: Optional[str] = None
    ad_group_id: Optional[str] = None
    ad_set_id: Optional[str] = None
    creative_id: Optional[str] = None
    ad_id: Optional[str] = None
    period_start: str = Field(..., description="ISO datetime")
    period_end: str = Field(..., description="ISO datetime")
    billing_currency: str = "USD"
    impressions: int = 0
    reach: int = 0
    clicks: int = 0
    engagements: int = 0
    video_views: int = 0
    viewable_impressions: int = 0
    media_spend: str = "0"
    platform_fees: str = "0"
    agency_fees: str = "0"
    creative_cost: str = "0"
    affiliate_cost: str = "0"
    other_cost: str = "0"
    total_cost: Optional[str] = None
    source_record_id: Optional[str] = None
    idempotency_key: Optional[str] = None


class SpendImportRequest(BaseModel):
    records: list[SpendRecordInput] = Field(..., min_length=1, max_length=500)


@router.get("")
async def list_spend(
    request: Request,
    platform: Optional[str] = Query(None),
    period_start: Optional[str] = Query(None),
    period_end: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    cursor: Optional[str] = Query(None),
):
    tenant = _require_tenant(request)
    start_dt = _parse_ts(period_start) if period_start else None
    end_dt = _parse_ts(period_end) if period_end else None

    rows = await _spend_repo.list_by_tenant(
        tenant.tenant_id,
        platform=platform,
        period_start=start_dt,
        period_end=end_dt,
        limit=limit,
        cursor=cursor,
    )
    next_cursor = rows[-1].get("period_start") if len(rows) == limit else None
    return {
        "data": rows,
        "pagination": {
            "limit": limit,
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None,
        },
    }


@router.post("/imports")
async def import_spend(request: Request, body: SpendImportRequest):
    tenant = _require_tenant(request)
    imported = 0
    errors: list[str] = []

    for rec in body.records:
        try:
            ps = _parse_ts(rec.period_start)
            pe = _parse_ts(rec.period_end)
            if ps is None or pe is None:
                errors.append(f"Invalid period for source_record_id={rec.source_record_id}")
                continue

            total = rec.total_cost
            if total is None:
                total = str(
                    Decimal(rec.media_spend) + Decimal(rec.platform_fees)
                    + Decimal(rec.agency_fees) + Decimal(rec.creative_cost)
                    + Decimal(rec.affiliate_cost) + Decimal(rec.other_cost)
                )

            idem_key = rec.idempotency_key or hashlib.sha256(
                f"{tenant.tenant_id}:{rec.platform}:{rec.campaign_id}:{rec.period_start}:{rec.source_record_id}".encode()
            ).hexdigest()

            await _spend_repo.upsert({
                "tenant_id": tenant.tenant_id,
                "platform": rec.platform,
                "campaign_id": rec.campaign_id,
                "ad_account_id": rec.ad_account_id,
                "ad_group_id": rec.ad_group_id,
                "ad_set_id": rec.ad_set_id,
                "creative_id": rec.creative_id,
                "ad_id": rec.ad_id,
                "period_start": rec.period_start,
                "period_end": rec.period_end,
                "billing_currency": rec.billing_currency,
                # normalized_currency + exchange_rate are computed by the repo
                # from billing_currency via the FX seam — never hardcoded USD.
                "impressions": rec.impressions,
                "reach": rec.reach,
                "clicks": rec.clicks,
                "engagements": rec.engagements,
                "video_views": rec.video_views,
                "viewable_impressions": rec.viewable_impressions,
                "media_spend": rec.media_spend,
                "platform_fees": rec.platform_fees,
                "agency_fees": rec.agency_fees,
                "creative_cost": rec.creative_cost,
                "affiliate_cost": rec.affiliate_cost,
                "other_cost": rec.other_cost,
                "total_cost": total,
                "source_record_id": rec.source_record_id,
                "idempotency_key": idem_key,
            })
            imported += 1
        except Exception as exc:
            errors.append(str(exc)[:200])

    return APIResponse(data={
        "imported": imported,
        "total": len(body.records),
        "errors": errors,
    }).to_dict()


@router.get("/reconciliation")
async def spend_reconciliation(
    request: Request,
    campaign_id: str = Query(...),
    period_start: str = Query(...),
    period_end: str = Query(...),
):
    tenant = _require_tenant(request)
    start_dt = _parse_ts(period_start)
    end_dt = _parse_ts(period_end)
    if start_dt is None or end_dt is None:
        raise BadRequestError("Invalid period_start or period_end")

    report = await _spend_repo.reconciliation_report(
        tenant.tenant_id, campaign_id, start_dt, end_dt,
    )
    return APIResponse(data=report).to_dict()


def _parse_ts(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
