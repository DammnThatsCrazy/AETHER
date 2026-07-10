from __future__ import annotations
from fastapi import APIRouter, Query, Request
from config.settings import settings
from shared.common.common import APIResponse, BadRequestError, NotFoundError
from services.card_linked_payments.campaign import get_campaign_card_linked_outcomes
from services.card_linked_payments.clusters import generate_card_linked_clusters
from services.card_linked_payments.diagnostics import card_linked_diagnostics
from services.card_linked_payments.graph_projector import project_card_linked_graph
from services.card_linked_payments.normalizer import normalize_onchain_observation, normalize_provider_webhook
from services.card_linked_payments.profile import get_profile_card_linked_activity
from services.card_linked_payments.repositories import get_card_linked_repositories

router = APIRouter(prefix="/v1/card-linked-payment-rails", tags=["Card-linked payment rails"])
profile_router = APIRouter(prefix="/v1/profile", tags=["Profile 360"])
kyber_router = APIRouter(prefix="/v1/admin/kyber/payment-rails/card-linked", tags=["Admin — Kyber Payment Rails"])

def _require_enabled() -> None:
    if not settings.card_linked_payment_rails.enabled:
        raise NotFoundError("Card-linked payment rail activity")

def _filters(card_program: str | None = None, issuer: str | None = None, payment_network: str | None = None, source: str | None = None, basis: str | None = None, rail: str | None = None, chain: str | None = None, asset: str | None = None, campaign: str | None = None, journey: str | None = None, session: str | None = None, device: str | None = None, confidence: str | None = None, region_policy: str | None = None, volume_min: float | None = None, volume_max: float | None = None):
    return {"card_program": card_program, "issuer_id": issuer, "payment_network": payment_network, "source": source, "basis": basis, "rail": rail, "chain": chain, "asset_currency": asset, "campaign_id": campaign, "journey_id": journey, "session_id": session, "device_id": device, "confidence": confidence, "region_policy": region_policy, "volume_min": volume_min, "volume_max": volume_max}

@router.post("/ingest/provider-webhook")
async def ingest_provider_webhook(payload: dict, request: Request):
    _require_enabled(); request.state.tenant.require_permission("write")
    flow = normalize_provider_webhook({**payload, "tenant_id": request.state.tenant.tenant_id})
    record = await get_card_linked_repositories().flows.upsert(flow)
    return APIResponse(data={"flow": record}).to_dict()

@router.post("/ingest/onchain")
async def ingest_onchain(payload: dict, request: Request):
    _require_enabled(); request.state.tenant.require_permission("write")
    flow = normalize_onchain_observation({**payload, "tenant_id": request.state.tenant.tenant_id})
    record = await get_card_linked_repositories().flows.upsert(flow)
    return APIResponse(data={"flow": record}).to_dict()

@profile_router.get("/{entity_id}/card-linked-activity")
@profile_router.get("/{entity_id}/economic/card-linked")
async def profile_card_linked_activity(request: Request, entity_id: str, card_program: str | None = None, issuer: str | None = None, payment_network: str | None = None, source: str | None = None, basis: str | None = None, rail: str | None = None, chain: str | None = None, asset: str | None = None, campaign: str | None = None, journey: str | None = None, session: str | None = None, device: str | None = None, confidence: str | None = None, region_policy: str | None = None, volume_min: float | None = None, volume_max: float | None = None):
    if not settings.card_linked_payment_rails.profile360_enabled: raise NotFoundError("Card-linked Profile360 activity")
    request.state.tenant.require_permission("read")
    data = await get_profile_card_linked_activity(request.state.tenant.tenant_id, entity_id, **_filters(card_program, issuer, payment_network, source, basis, rail, chain, asset, campaign, journey, session, device, confidence, region_policy, volume_min, volume_max))
    return APIResponse(data=data).to_dict()

@profile_router.get("/{entity_id}/drill/card-linked/{object_id}")
async def profile_card_linked_drill(request: Request, entity_id: str, object_id: str):
    if not settings.card_linked_payment_rails.profile360_enabled: raise NotFoundError("Card-linked Profile360 activity")
    request.state.tenant.require_permission("read")
    flow = await get_card_linked_repositories().flows.get(request.state.tenant.tenant_id, object_id)
    if not flow: raise NotFoundError("Card-linked flow")
    return APIResponse(data={"entity_id": entity_id, "flow": flow, "provenance": flow.get("evidence_refs", []), "basis_warning": "topup is not spend" if flow.get("basis") in {"topup", "funding"} else None}).to_dict()

@router.get("/campaigns/{campaign_id}/outcomes")
async def campaign_outcomes(request: Request, campaign_id: str):
    if not settings.card_linked_payment_rails.campaign_attribution_enabled: raise NotFoundError("Card-linked campaign outcomes")
    request.state.tenant.require_permission("read")
    return APIResponse(data=await get_campaign_card_linked_outcomes(request.state.tenant.tenant_id, campaign_id)).to_dict()

@router.get("/graph")
async def graph(request: Request, campaign: str | None = Query(None), card_program: str | None = Query(None), basis: str | None = Query(None), chain: str | None = Query(None), volume_min: float | None = Query(None)):
    _require_enabled(); request.state.tenant.require_permission("read")
    flows = await get_card_linked_repositories().flows.list_for_tenant(request.state.tenant.tenant_id, **_filters(card_program=card_program, basis=basis, chain=chain, campaign=campaign, volume_min=volume_min))
    return APIResponse(data=project_card_linked_graph(request.state.tenant.tenant_id, flows)).to_dict()

@router.get("/clusters")
async def clusters(request: Request):
    if not settings.card_linked_payment_rails.clustering_enabled: raise NotFoundError("Card-linked clusters")
    request.state.tenant.require_permission("read")
    flows = await get_card_linked_repositories().flows.list_for_tenant(request.state.tenant.tenant_id)
    return APIResponse(data={"clusters": generate_card_linked_clusters(flows)}).to_dict()

@kyber_router.get("/diagnostics")
async def kyber_diagnostics(request: Request, tenant_id: str | None = None):
    from services.security.request_context import require_kyber_operator
    if not settings.card_linked_payment_rails.kyber_enabled: raise BadRequestError("Kyber card-linked payment rails are disabled")
    require_kyber_operator(request)
    return APIResponse(data=await card_linked_diagnostics(tenant_id)).to_dict()
