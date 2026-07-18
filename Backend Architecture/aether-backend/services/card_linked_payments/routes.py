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


# ── ingestion (write paths — previously the pipeline had no runtime entry) ──


def _write_gate(request: Request) -> str:
    if not settings.card_linked_payment_rails.enabled:
        raise HTTPException(status_code=404, detail="Card-linked payment rails is not enabled")
    tenant = request.state.tenant
    tenant.require_permission("write")
    return tenant.tenant_id


@router.post("/ingest/provider-webhook")
async def ingest_provider_webhook(request: Request):
    """Issuer/provider card-spend evidence (server-to-server, tenant-authenticated).

    Body: the provider payload, optionally wrapped with ``region_hint`` and
    ``consent_snapshot``. All fail-closed guards (PII rejection, basis
    enforcement, region policy, consent) run inside the ingestion service.
    """
    from services.card_linked_payments.ingestion import get_ingestion_service

    tenant_id = _write_gate(request)
    body = await request.json()
    payload = body.get("payload", body)
    try:
        record, disposition = await get_ingestion_service().ingest_provider_webhook(
            tenant_id,
            payload,
            region_hint=body.get("region_hint"),
            consent_snapshot=body.get("consent_snapshot"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return APIResponse(data={"flow_id": record.get("id"), "disposition": disposition}).to_dict()


@router.post("/ingest/onchain")
async def ingest_onchain(request: Request):
    """Wallet/on-chain top-up, funding, or settlement evidence."""
    from services.card_linked_payments.ingestion import get_ingestion_service

    tenant_id = _write_gate(request)
    body = await request.json()
    payload = body.get("payload", body)
    try:
        record, disposition = await get_ingestion_service().ingest_onchain_observation(
            tenant_id, payload
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return APIResponse(data={"flow_id": record.get("id"), "disposition": disposition}).to_dict()


@router.post("/import")
async def ingest_import(request: Request):
    """Tenant bulk import of card-linked activity rows.

    Body: ``{"rows": [...], "region_hint": "..."}`` — each row must carry a
    supported ``basis``; unsupported bases fail the whole batch (422) before
    any row is persisted.
    """
    from services.card_linked_payments.ingestion import get_ingestion_service

    tenant_id = _write_gate(request)
    body = await request.json()
    rows = body.get("rows")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=422, detail="body.rows must be a non-empty list")
    try:
        results = await get_ingestion_service().ingest_tenant_import(
            tenant_id, rows,
            region_hint=body.get("region_hint"),
            consent_snapshot=body.get("consent_snapshot"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    created = sum(1 for _, disposition in results if disposition == "created")
    return APIResponse(
        data={
            "accepted": created,
            "duplicates": len(results) - created,
            "flow_ids": [record.get("id") for record, _ in results],
        }
    ).to_dict()
