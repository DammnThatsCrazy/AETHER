"""Card-linked payment rail tenant API.

Nested under the payment-rails integration surface:
``/v1/integrations/providers/payment-rails/card-linked``. Flag-gated,
tenant-scoped, observation-only. All list endpoints accept the shared
filter set (program/issuer/network/basis/source/confidence/chain/asset/
campaign/journey/volume/time) and every payload carries basis + source +
confidence so no surface can conflate top-up with spend.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from config.settings import settings
from shared.common.common import APIResponse
from shared.logger.logger import get_logger

from services.card_linked_payments.gold import (
    campaign_card_linked_outcomes,
    program_issuer_benchmarks,
)
from services.card_linked_payments.profile_summary import (
    FILTERABLE_FIELDS,
    apply_flow_filters,
)
from services.card_linked_payments.repositories import get_card_linked_repositories
from services.payment_catalog.catalog import PAYMENTSCAN_CATALOG_SEED

logger = get_logger("aether.card_linked.routes")

router = APIRouter(
    prefix="/v1/integrations/providers/payment-rails/card-linked",
    tags=["Card-Linked Payment Rails"],
)


def _gate(request: Request) -> str:
    if not settings.card_linked_payment_rails.enabled:
        raise HTTPException(status_code=404, detail="Card-linked payment rails is not enabled")
    tenant = request.state.tenant
    tenant.require_permission("read")
    return tenant.tenant_id


def _filters(request: Request) -> dict:
    params = request.query_params
    filters = {name: params.get(name) for name in FILTERABLE_FIELDS}
    for extra in ("volume_min", "volume_max", "since", "until"):
        filters[extra] = params.get(extra)
    return filters


@router.get("/catalog")
async def get_catalog(request: Request, entity_type: str | None = None):
    """The PaymentScan-seeded catalog (programs/issuers/networks/chains/currencies)."""
    _gate(request)
    if not settings.card_linked_payment_rails.paymentscan_catalog_enabled:
        raise HTTPException(status_code=404, detail="PaymentScan catalog is not enabled")
    entities = [
        {
            "id": e.id, "entity_type": e.entity_type, "display_name": e.display_name,
            "slug": e.slug, "aliases": list(e.aliases), "status": e.status,
            "source": e.source, "source_url": e.source_url,
        }
        for e in PAYMENTSCAN_CATALOG_SEED
        if entity_type is None or e.entity_type == entity_type
    ]
    return APIResponse(data={"items": entities, "count": len(entities)}).to_dict()


@router.get("/flows")
async def list_flows(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
):
    tenant_id = _gate(request)
    repos = get_card_linked_repositories()
    rows = await repos.flows.list_for_tenant(tenant_id, limit=500)
    rows = [r for r in rows if r.get("reconciliation_state") != "benchmark_only"]
    filtered = apply_flow_filters(rows, _filters(request))
    return APIResponse(data={
        "items": filtered[:limit],
        "count": len(filtered[:limit]),
        "available_filters": list(FILTERABLE_FIELDS) + ["volume_min", "volume_max", "since", "until"],
    }).to_dict()


@router.get("/benchmarks")
async def list_benchmarks(request: Request, limit: int = Query(default=100, ge=1, le=500)):
    """PaymentScan benchmarks — aggregate intelligence, never user truth."""
    tenant_id = _gate(request)
    if not settings.card_linked_payment_rails.paymentscan_benchmarks_enabled:
        raise HTTPException(status_code=404, detail="PaymentScan benchmarks are not enabled")
    repos = get_card_linked_repositories()
    rows = await repos.benchmarks.list_for_tenant(tenant_id, limit=limit)
    return APIResponse(data={
        "items": rows, "count": len(rows),
        "notice": "PaymentScan benchmarks are catalog/market intelligence — not user-level card spend.",
    }).to_dict()


@router.get("/summary")
async def coverage_summary(request: Request):
    tenant_id = _gate(request)
    data = await program_issuer_benchmarks(tenant_id)
    return APIResponse(data=data).to_dict()


@router.get("/campaigns/{campaign_id}/outcomes")
async def campaign_outcomes(campaign_id: str, request: Request):
    """Campaign360 card-linked outcomes with an explicit attribution basis
    (direct/temporal/probabilistic/benchmark_only/insufficient_evidence) —
    correlation is never presented as causality."""
    tenant_id = _gate(request)
    if not settings.card_linked_payment_rails.campaign_attribution_enabled:
        raise HTTPException(status_code=404, detail="Card-linked campaign attribution is not enabled")
    data = await campaign_card_linked_outcomes(tenant_id, campaign_id)
    return APIResponse(data=data).to_dict()
