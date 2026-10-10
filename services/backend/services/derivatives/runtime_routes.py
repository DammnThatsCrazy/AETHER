"""Derivatives Intelligence tenant API — /v1/derivatives.

Read-only intelligence plus canonical observation intake. INVARIANT: no
endpoint places, amends, cancels, or closes anything; account links carry
read-only credential authority only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from config.settings import settings
from repositories.derivatives_repos import (
    FillRepo,
    InstrumentRepo,
    MarketRepo,
    OrderRepo,
    PnlSnapshotRepo,
    PositionRepo,
    ReconciliationVarianceRepo,
    TradingAccountRepo,
    VenueRepo,
)
from shared.auth.auth import Permissions
from services.derivatives.foundation import (
    active_tenant_id as _tenant_id,
    check_no_execution as _check_no_execution,
    deterministic_idempotency_key,
    require_flag,
    require_permission as _require_perm,
    require_read_only_authority,
    utc_now_iso,
    validate_payload_tenant,
)
from services.derivatives.runtime_models import AccountLinkRequest, DerivativesObservationIn
from services.derivatives.state_machines import OrderStateMachine, PositionStateMachine


async def _require_entitlement(tenant_id: str) -> None:
    """Resolve derivatives access from the billing authority; missing means deny."""
    from services.billing.revops import TenantEntitlementRepository

    rows = await TenantEntitlementRepository().list_for_tenant(tenant_id)
    if not any(
        row.get("feature_key") == "derivatives.enabled" and row.get("enabled") is True
        for row in rows
    ):
        raise HTTPException(status_code=403, detail={"code": "derivatives_not_entitled"})


async def _record_usage(tenant_id: str, source_id: str, event_name: str) -> None:
    """Durable, idempotent usage record through the canonical billing service."""
    from services.billing.revops import MeteringService, UsageMeteringEvent

    await MeteringService().record_event(UsageMeteringEvent(
        tenant_id=tenant_id,
        event_type="derivatives_event_ingested",
        source_type="derivatives_runtime",
        source_id=source_id,
        metadata={"event_name": event_name},
    ))


async def _project_graph_account(account: dict) -> None:
    from shared.graph.graph import get_graph_client
    from shared.graph.mutation_gateway import GraphMutationGateway
    from shared.graph.mutation_intents import edge_intent, vertex_intent
    from services.derivatives.graph_mutations import build_account_mutations

    vertices, edges = build_account_mutations(account)
    gateway = GraphMutationGateway(graph_client=get_graph_client())
    for vertex in vertices:
        await gateway.apply(vertex_intent(
            vertex, operation="node_versioned", tenant_id=account["tenant_id"],
            actor_kind="service", actor_id="derivatives_runtime",
            source_event_id=account["idempotency_key"],
        ))
    for edge in edges:
        await gateway.apply(edge_intent(
            edge, operation="edge_created", tenant_id=account["tenant_id"],
            actor_kind="service", actor_id="derivatives_runtime",
            source_event_id=account["idempotency_key"],
        ))


async def _project_graph_position(position: dict) -> None:
    if not position.get("trading_account_id") or not position.get("canonical_market_id"):
        return
    from shared.graph.graph import get_graph_client
    from shared.graph.mutation_gateway import GraphMutationGateway
    from shared.graph.mutation_intents import edge_intent, vertex_intent
    from services.derivatives.graph_mutations import build_position_mutations

    vertices, edges = build_position_mutations(position)
    gateway = GraphMutationGateway(graph_client=get_graph_client())
    for vertex in vertices:
        await gateway.apply(vertex_intent(
            vertex, operation="node_versioned", tenant_id=position["tenant_id"],
            actor_kind="service", actor_id="derivatives_runtime",
            source_event_id=position.get("idempotency_key") or position["position_id"],
        ))
    for edge in edges:
        await gateway.apply(edge_intent(
            edge, operation="edge_created", tenant_id=position["tenant_id"],
            actor_kind="service", actor_id="derivatives_runtime",
            source_event_id=position.get("idempotency_key") or position["position_id"],
        ))

router = APIRouter(prefix="/v1/derivatives/runtime", tags=["derivatives"])

# Event intake routing: canonical event name -> (repo factory, id field)
_FACT_ROUTES = {
    "derivatives_order_observed": (OrderRepo, "order_id"),
    "derivatives_order_updated_observed": (OrderRepo, "order_id"),
    "derivatives_order_cancelled_observed": (OrderRepo, "order_id"),
    "derivatives_order_rejected_observed": (OrderRepo, "order_id"),
    "derivatives_order_expired_observed": (OrderRepo, "order_id"),
    "derivatives_fill_observed": (FillRepo, "fill_id"),
    "derivatives_position_opened_observed": (PositionRepo, "position_id"),
    "derivatives_position_increased_observed": (PositionRepo, "position_id"),
    "derivatives_position_reduced_observed": (PositionRepo, "position_id"),
    "derivatives_position_closed_observed": (PositionRepo, "position_id"),
    "derivatives_position_liquidated_observed": (PositionRepo, "position_id"),
}


def _gate(request: Request, permission: str = Permissions.DERIVATIVES_READ) -> str:
    require_flag(settings.derivatives.api_enabled, "Derivatives Intelligence")
    _require_perm(request, permission)
    return _tenant_id(request)


def _meter(name: str) -> None:
    try:
        from shared.logger.logger import metrics
        metrics.increment(name)
    except Exception:
        pass


def _stringify(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        out.append({
            key: str(value) if isinstance(value, Decimal) else value
            for key, value in row.items()
        })
    return out


async def _tenant_list(
    repo_cls, request: Request, filters: Optional[dict], limit: int, offset: int,
):
    tenant_id = _gate(request)
    merged = {"tenant_id": tenant_id, **(filters or {})}
    rows = await repo_cls().find_many(merged, limit=limit, offset=offset)
    return {"items": _stringify(rows), "count": len(rows)}


# ── Global reference reads ───────────────────────────────────────────────────

@router.get("/venues")
async def list_venues(request: Request, limit: int = Query(default=50, ge=1, le=200), offset: int = 0):
    _gate(request)
    rows = await VenueRepo().find_many(limit=limit, offset=offset)
    return {"items": _stringify(rows), "count": len(rows)}


@router.get("/instruments")
async def list_instruments(request: Request, limit: int = Query(default=50, ge=1, le=200), offset: int = 0):
    _gate(request)
    rows = await InstrumentRepo().find_many(limit=limit, offset=offset)
    return {"items": _stringify(rows), "count": len(rows)}


@router.get("/markets")
async def list_markets(
    request: Request, venue_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = 0,
):
    _gate(request)
    filters = {"venue_id": venue_id} if venue_id else None
    rows = await MarketRepo().find_many(filters, limit=limit, offset=offset)
    return {"items": _stringify(rows), "count": len(rows)}


# ── Tenant-scoped reads ──────────────────────────────────────────────────────

@router.get("/accounts")
async def list_accounts(request: Request, limit: int = Query(default=50, ge=1, le=200), offset: int = 0):
    return await _tenant_list(TradingAccountRepo, request, None, limit, offset)


@router.get("/orders")
async def list_orders(
    request: Request, trading_account_id: Optional[str] = None,
    order_status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = 0,
):
    filters: dict = {}
    if trading_account_id:
        filters["trading_account_id"] = trading_account_id
    if order_status:
        filters["order_status"] = order_status
    return await _tenant_list(OrderRepo, request, filters, limit, offset)


@router.get("/fills")
async def list_fills(
    request: Request, trading_account_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = 0,
):
    filters = {"trading_account_id": trading_account_id} if trading_account_id else None
    return await _tenant_list(FillRepo, request, filters, limit, offset)


@router.get("/positions")
async def list_positions(
    request: Request, trading_account_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = 0,
):
    filters: dict = {}
    if trading_account_id:
        filters["trading_account_id"] = trading_account_id
    if status:
        filters["status"] = status
    return await _tenant_list(PositionRepo, request, filters, limit, offset)


@router.get("/pnl")
async def list_pnl_snapshots(
    request: Request, trading_account_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = 0,
):
    require_flag(settings.derivatives.pnl_enabled, "Derivatives P&L")
    filters = {"trading_account_id": trading_account_id} if trading_account_id else None
    return await _tenant_list(PnlSnapshotRepo, request, filters, limit, offset)


@router.get("/reconciliation/variances")
async def list_variances(
    request: Request, status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = 0,
):
    filters = {"status": status} if status else None
    return await _tenant_list(ReconciliationVarianceRepo, request, filters, limit, offset)


# ── Intake ───────────────────────────────────────────────────────────────────

@router.post("/accounts/link", status_code=201)
async def link_account(payload: AccountLinkRequest, request: Request):
    """Observe a read-only account link. Aether stores a credential
    REFERENCE at most — never a secret, never trade/withdraw authority."""
    tenant_id = _gate(request, Permissions.DERIVATIVES_CONNECT)
    await _require_entitlement(tenant_id)
    validate_payload_tenant(payload, tenant_id)
    _check_no_execution(payload)
    require_read_only_authority(payload.authority_type)

    basis = f"{tenant_id}|{payload.venue_id}|{payload.external_account_ref}"
    record = {
        "tenant_id": tenant_id,
        "trading_account_id": f"dacct_{deterministic_idempotency_key(basis)[:24]}",
        "venue_id": payload.venue_id,
        "venue_deployment_id": payload.venue_deployment_id,
        "external_account_ref": payload.external_account_ref,
        "owner_entity_kind": payload.owner_entity_kind,
        "owner_entity_id": payload.owner_entity_id,
        "credential_reference_id": payload.credential_reference_id,
        "connector_state": "configured",
        "data_quality_state": "complete",
        "idempotency_key": deterministic_idempotency_key(basis),
        "execution_by_aether": False,
        "created_at": utc_now_iso(),
    }
    inserted = await TradingAccountRepo().insert(record)
    # Re-run projections on duplicate intake too: a previous request may have
    # persisted the source fact and failed before the graph/meter side effects.
    await _project_graph_account(record)
    await _record_usage(tenant_id, record["idempotency_key"], "account_linked")
    return {
        "inserted": inserted,
        "trading_account_id": record["trading_account_id"],
        "authority_type": "read_only",
    }


async def _classify_transition(
    repo: Any, tenant_id: str, id_field: str, entity_id: str, record: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """Where an incoming order/position status sits against what is already stored.

    Classification only: the observation is stored either way (the tables are
    append-only evidence), but the response says whether it advanced the entity,
    repeated it, arrived out of order, or is not a legal step. ``None`` for facts
    that carry no lifecycle status (fills).
    """
    if "order_status" in record:
        machine, status_field = OrderStateMachine, "order_status"
    elif "status" in record and id_field == "position_id":
        machine, status_field = PositionStateMachine, "status"
    else:
        return None
    incoming = str(record[status_field] or "")
    rows = await repo.find_many({"tenant_id": tenant_id, id_field: entity_id})
    if not rows:
        return {"classification": "first_observation", "status": incoming}
    # Judge against the furthest-advanced status already held, so a late low-rank
    # observation can never be mistaken for progress.
    held = max(
        (str(r.get(status_field) or "unknown") for r in rows),
        key=machine.rank,
    )
    result = machine.apply(held, incoming, str(record.get("observed_at") or ""))
    if result.applied:
        classification = "reapplied" if incoming == held else "advanced"
    elif result.reason == "stale_out_of_order":
        classification = "stale"
    elif result.reason == "duplicate_evidence":
        classification = "duplicate"
    else:
        classification = "rejected_transition"
    return {
        "classification": classification,
        "status": incoming,
        "held_status": held,
        "reason": result.reason,
    }


@router.post("/observations", status_code=201)
async def ingest_observation(payload: DerivativesObservationIn, request: Request):
    """Canonical derivatives event intake (order/fill/position facts)."""
    tenant_id = _gate(request)
    await _require_entitlement(tenant_id)
    require_flag(settings.derivatives.runtime_enabled, "Derivatives runtime")
    validate_payload_tenant(payload, tenant_id)
    _check_no_execution(payload)
    _check_no_execution(payload.payload)

    from services.ingestion.generated_registry import CANONICAL_EVENT_TYPES

    if payload.event_name not in CANONICAL_EVENT_TYPES:
        raise HTTPException(status_code=422, detail=f"unknown event type: {payload.event_name}")
    route = _FACT_ROUTES.get(payload.event_name)
    if route is None:
        raise HTTPException(
            status_code=422,
            detail=f"{payload.event_name} is not ingestable via /observations",
        )
    repo_cls, id_field = route
    entity_id = payload.payload.get(id_field)
    if not entity_id:
        raise HTTPException(status_code=422, detail=f"payload missing {id_field}")

    basis = f"{tenant_id}|{payload.event_name}|{entity_id}|{payload.payload.get('order_status') or payload.payload.get('status') or ''}"
    record = {
        "tenant_id": tenant_id,
        "idempotency_key": deterministic_idempotency_key(basis),
        "execution_by_aether": False,
        **{k: v for k, v in payload.payload.items() if k != "execution_by_aether"},
    }
    repo = repo_cls()
    record = {k: v for k, v in record.items() if k in repo.columns}
    record.setdefault(id_field, entity_id)
    transition = await _classify_transition(repo, tenant_id, id_field, entity_id, record)
    inserted = await repo.insert(record)
    # Idempotent projections and metering make retries repair partial fan-out.
    if id_field == "position_id":
        await _project_graph_position(record)
    await _record_usage(tenant_id, record["idempotency_key"], payload.event_name)
    body: dict[str, Any] = {"inserted": inserted, id_field: entity_id, "event_name": payload.event_name}
    if transition is not None:
        body["transition"] = transition
    return body
