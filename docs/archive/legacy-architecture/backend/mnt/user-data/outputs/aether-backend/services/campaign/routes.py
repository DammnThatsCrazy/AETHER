"""
Aether Service — Campaign
Campaign management, attribution calculation, and reporting.
Tech: Node.js (Fastify). Scaling: Standard autoscaling.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from repositories.repos import CampaignRepository
from shared.common.common import APIResponse, PaginatedResponse, PaginationMeta
from shared.events.events import EventProducer
from shared.logger.logger import get_logger

logger = get_logger("aether.service.campaign")
router = APIRouter(prefix="/v1/campaigns", tags=["Campaigns"])

_repo = CampaignRepository()
_producer = EventProducer()


class CampaignCreate(BaseModel):
    name: str
    channel: str = Field(..., description="e.g. email, social, paid_search, organic")
    start_date: str
    end_date: Optional[str] = None
    budget_usd: Optional[float] = None
    utm_params: dict[str, str] = Field(default_factory=dict)
    properties: dict[str, Any] = Field(default_factory=dict)


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    end_date: Optional[str] = None
    budget_usd: Optional[float] = None
    status: Optional[str] = None


# ── CRUD Routes ───────────────────────────────────────────────────────

@router.get("")
async def list_campaigns(request: Request, limit: int = 50, offset: int = 0):
    tenant = request.state.tenant
    campaigns = await _repo.find_many(
        filters={"tenant_id": tenant.tenant_id}, limit=limit, offset=offset
    )
    total = await _repo.count(filters={"tenant_id": tenant.tenant_id})
    return PaginatedResponse(
        data=campaigns,
        pagination=PaginationMeta(total=total, limit=limit, offset=offset, has_more=offset + limit < total),
    ).to_dict()


@router.post("")
async def create_campaign(body: CampaignCreate, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("campaign:manage")
    import uuid
    campaign = await _repo.insert(str(uuid.uuid4()), {
        "tenant_id": tenant.tenant_id,
        **body.model_dump(),
        "status": "active",
    })
    return APIResponse(data=campaign).to_dict()


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str, request: Request):
    campaign = await _repo.find_by_id_or_fail(campaign_id)
    return APIResponse(data=campaign).to_dict()


@router.patch("/{campaign_id}")
async def update_campaign(campaign_id: str, body: CampaignUpdate, request: Request):
    request.state.tenant.require_permission("campaign:manage")
    campaign = await _repo.update(campaign_id, body.model_dump(exclude_none=True))
    return APIResponse(data=campaign).to_dict()


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: str, request: Request):
    request.state.tenant.require_permission("campaign:manage")
    await _repo.delete(campaign_id)
    return APIResponse(data={"deleted": True}).to_dict()


# ── Attribution ───────────────────────────────────────────────────────

@router.get("/{campaign_id}/attribution")
async def get_attribution(campaign_id: str, request: Request):
    """Get attribution results for a campaign."""
    return APIResponse(data={
        "campaign_id": campaign_id,
        "model": "multi_touch",
        "conversions": 0,
        "revenue_attributed_usd": 0.0,
        "touchpoints": [],
    }).to_dict()
