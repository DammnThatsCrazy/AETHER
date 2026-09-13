"""
External Account Observability Routes.

INVARIANT: These routes never trade, execute orders, or manage external accounts.
They observe and record external agentic and brokerage account activity.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, ValidationInfo, field_validator

from config.settings import settings
from repositories.agentic_observability_repos import (
    ExternalAccountRepository, ExternalBrokerageRepository,
    TradeObservationRepository, PortfolioSnapshotRepository,
    AgentBudgetRepository,
)
from services.external_account_observability.account_models import ExternalAgenticAccountObservedRecord
from services.external_account_observability.brokerage_models import (
    ExternalBrokerageAccountObservedRecord, TradeIntentObservedRecord,
    TradeOrderObservedRecord, PortfolioSnapshotObservedRecord,
)
from services.external_account_observability.budget_models import AgentBudgetObservedRecord
from services.agentic_observability.event_normalizer import resolve_provider
from services.agentic_observability.foundation import (
    active_tenant_id as _tenant_id,
    check_no_execution as _check_no_execution,
    persist_mutations as _persist_mutations,
    require_permission as _require_perm,
    validate_payload_tenant,
)
from services.agentic_observability.models import decimal_str_from_provider
from services.agentic_observability.pipeline import ingest_observation
from services.external_account_observability.graph_mutations import (
    build_account_mutations, build_brokerage_mutations,
    build_trade_intent_mutations, build_order_mutations, build_portfolio_mutations,
)
from services.security.request_context import require_kyber_operator

router = APIRouter()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_POSITION_MONEY_KEYS = frozenset({
    "value", "current_value", "market_value", "avg_cost", "average_cost",
    "cost_basis", "quantity", "qty", "price", "unrealized_pnl", "realized_pnl",
    "notional", "amount", "market_price",
})


def _decimalize_positions(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize known money fields inside free-form observed position dicts to
    decimal strings so per-position values are not persisted (and propagated
    downstream) as authoritative binary floats.

    Positions arrive as provider-shaped dicts, so this coerces rather than
    rejects (unknown keys pass through untouched); top-level money fields on the
    request models remain strict (reject binary float).
    """
    normalized: list[dict[str, Any]] = []
    for pos in positions or []:
        if not isinstance(pos, dict):
            normalized.append(pos)
            continue
        row = dict(pos)
        for key, value in pos.items():
            if (
                key.lower() in _POSITION_MONEY_KEYS
                and value is not None
                and not isinstance(value, bool)
            ):
                try:
                    row[key] = str(Decimal(str(value)))
                except (InvalidOperation, ValueError, TypeError):
                    row[key] = value
        normalized.append(row)
    return normalized


def _new_id() -> str:
    return str(uuid.uuid4())


def _use_canonical_spine(tenant_id: str) -> bool:
    """Route this observation through the canonical durable spine?

    Default OFF: only when the flag is enabled globally or the tenant is a
    declared canary. Every other tenant keeps the synchronous legacy path
    (repo.insert + build_*_mutations + persist_mutations) byte-for-byte.
    """
    cfg = settings.agentic_observability_ingestion
    return cfg.canonical_spine_enabled or tenant_id in cfg.canary_tenant_ids


def _prune_none(props: dict) -> dict:
    return {k: v for k, v in props.items() if v is not None}


class ExtAccountRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    agent_id: Optional[str] = None
    provider: str
    external_account_id: str
    account_type: Optional[str] = None
    permissions_observed: list[str] = Field(default_factory=list)
    execution_by_aether: Literal[False] = False


class BrokerageRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    agent_id: Optional[str] = None
    provider: str
    external_account_id: str
    account_type: Optional[str] = None
    execution_by_aether: Literal[False] = False


class PortfolioSnapshotRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    brokerage_obs_id: Optional[str] = None
    # Decimal-safe money: accept str/int/Decimal, REJECT binary float.
    total_value: Optional[str] = None
    positions: list[dict[str, Any]] = Field(default_factory=list)
    observed_at: Optional[str] = None
    execution_by_aether: Literal[False] = False

    @field_validator("total_value", mode="before")
    @classmethod
    def _decimal_money(cls, v: Any, info: ValidationInfo) -> Any:
        return decimal_str_from_provider(v, info.field_name)


class OrderObsRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    brokerage_obs_id: Optional[str] = None
    agent_id: Optional[str] = None
    symbol: str
    side: str = "buy"
    # Decimal-safe money: accept str/int/Decimal, REJECT binary float.
    quantity: str
    status: str = "pending"
    external_order_id: Optional[str] = None
    executed_externally: Literal[True] = True
    execution_by_aether: Literal[False] = False
    observed_at: Optional[str] = None

    @field_validator("quantity", mode="before")
    @classmethod
    def _decimal_money(cls, v: Any, info: ValidationInfo) -> Any:
        return decimal_str_from_provider(v, info.field_name)


class BudgetObsRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    account_obs_id: Optional[str] = None
    # Decimal-safe money: accept str/int/Decimal, REJECT binary float.
    total_budget: Optional[str] = None
    used_budget: Optional[str] = None
    available_budget: Optional[str] = None
    currency: str = "USD"
    observed_at: Optional[str] = None
    execution_by_aether: Literal[False] = False

    @field_validator("total_budget", "used_budget", "available_budget", mode="before")
    @classmethod
    def _decimal_money(cls, v: Any, info: ValidationInfo) -> Any:
        return decimal_str_from_provider(v, info.field_name)


class ExtAccountResponse(BaseModel):
    observation_id: str
    received_at: str
    graph_mutations_queued: int = 0
    tenant_id: str


@router.post("/v1/observability/external-accounts", response_model=ExtAccountResponse, status_code=201)
async def observe_external_account(req: ExtAccountRequest, request: Request) -> ExtAccountResponse:
    """Observe an external agentic account linkage."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    validate_payload_tenant(req, tenant_id)
    _check_no_execution(req.model_dump())
    obs_id = _new_id()
    record = ExternalAgenticAccountObservedRecord(
        account_obs_id=obs_id,
        agent_id=req.agent_id,
        provider=req.provider,
        external_account_id=req.external_account_id,
        account_type=req.account_type,
        permissions_observed=req.permissions_observed,
        tenant_id=tenant_id,
    )
    repo = ExternalAccountRepository()
    await repo.insert(obs_id, record.model_dump(mode="json"))
    if _use_canonical_spine(tenant_id):
        provider_id = resolve_provider(req.model_dump())
        result = await ingest_observation(
            tenant_id=tenant_id,
            event_name="agentic_account_observed",
            provider_id=provider_id,
            provider_event_id=req.external_account_id,
            agent_id=req.agent_id,
            actor_id=req.agent_id,
            properties=_prune_none({
                "agentId": req.agent_id,
                "provider": provider_id,
                "objectType": "account",
                "objectId": req.external_account_id,
                "accountType": req.account_type,
            }),
        )
        graph_mutations_queued = result.outbox_written
    else:
        mutations = build_account_mutations(tenant_id, obs_id, req.agent_id)
        projection = await _persist_mutations(mutations, tenant_id=tenant_id, trace_id=obs_id)
        graph_mutations_queued = projection.graph_mutations_persisted
    return ExtAccountResponse(
        observation_id=obs_id, received_at=_utc_now(),
        graph_mutations_queued=graph_mutations_queued, tenant_id=tenant_id,
    )


@router.post("/v1/observability/external-accounts/brokerage", response_model=ExtAccountResponse, status_code=201)
async def observe_brokerage_account(req: BrokerageRequest, request: Request) -> ExtAccountResponse:
    """Observe an external brokerage account."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    validate_payload_tenant(req, tenant_id)
    _check_no_execution(req.model_dump())
    obs_id = _new_id()
    record = ExternalBrokerageAccountObservedRecord(
        brokerage_obs_id=obs_id,
        agent_id=req.agent_id,
        provider=req.provider,
        external_account_id=req.external_account_id,
        account_type=req.account_type,
        tenant_id=tenant_id,
    )
    repo = ExternalBrokerageRepository()
    await repo.insert(obs_id, record.model_dump(mode="json"))
    if _use_canonical_spine(tenant_id):
        provider_id = resolve_provider(req.model_dump())
        result = await ingest_observation(
            tenant_id=tenant_id,
            event_name="agentic_account_observed",
            provider_id=provider_id,
            # Distinct facet from the plain account observation (same event_name,
            # same external_account_id) so the two do not collide at the Bronze
            # uniqueness boundary and drop the brokerage observation.
            provider_event_id=f"brokerage:{req.external_account_id}",
            agent_id=req.agent_id,
            actor_id=req.agent_id,
            properties=_prune_none({
                "agentId": req.agent_id,
                "provider": provider_id,
                "accountKind": "brokerage",
                "objectType": "account",
                "objectId": req.external_account_id,
                "accountType": req.account_type,
            }),
        )
        graph_mutations_queued = result.outbox_written
    else:
        mutations = build_brokerage_mutations(tenant_id, obs_id, req.agent_id)
        projection = await _persist_mutations(mutations, tenant_id=tenant_id, trace_id=obs_id)
        graph_mutations_queued = projection.graph_mutations_persisted
    return ExtAccountResponse(
        observation_id=obs_id, received_at=_utc_now(),
        graph_mutations_queued=graph_mutations_queued, tenant_id=tenant_id,
    )


@router.post("/v1/observability/external-accounts/portfolio-snapshots", response_model=ExtAccountResponse, status_code=201)
async def observe_portfolio_snapshot(req: PortfolioSnapshotRequest, request: Request) -> ExtAccountResponse:
    """Observe a portfolio snapshot from an external brokerage."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    validate_payload_tenant(req, tenant_id)
    _check_no_execution(req.model_dump())
    obs_id = _new_id()
    record = PortfolioSnapshotObservedRecord(
        portfolio_obs_id=obs_id,
        brokerage_obs_id=req.brokerage_obs_id,
        total_value=req.total_value,
        positions=_decimalize_positions(req.positions),
        tenant_id=tenant_id,
        snapshot_at=req.observed_at or _utc_now(),
    )
    repo = PortfolioSnapshotRepository()
    await repo.insert(obs_id, record.model_dump(mode="json"))
    if _use_canonical_spine(tenant_id):
        # Portfolio snapshots carry no external provider / event id → provider
        # "unknown" and no provider_event_id (idempotency falls back to a fresh id).
        result = await ingest_observation(
            tenant_id=tenant_id,
            event_name="agent_portfolio_snapshot_observed",
            provider_id="unknown",
            observed_at=req.observed_at,
            properties=_prune_none({
                "provider": "unknown",
                "objectType": "portfolio",
                "objectId": obs_id,
                "totalValue": req.total_value,  # decimal string
                "brokerageObsId": req.brokerage_obs_id,
            }),
        )
        graph_mutations_queued = result.outbox_written
    else:
        mutations = build_portfolio_mutations(tenant_id, obs_id, req.brokerage_obs_id)
        projection = await _persist_mutations(mutations, tenant_id=tenant_id, trace_id=obs_id)
        graph_mutations_queued = projection.graph_mutations_persisted
    return ExtAccountResponse(
        observation_id=obs_id, received_at=_utc_now(),
        graph_mutations_queued=graph_mutations_queued, tenant_id=tenant_id,
    )


@router.post("/v1/observability/external-accounts/order-observations", response_model=ExtAccountResponse, status_code=201)
async def observe_trade_order(req: OrderObsRequest, request: Request) -> ExtAccountResponse:
    """Observe a trade order (executed externally, not by AETHER)."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    validate_payload_tenant(req, tenant_id)
    _check_no_execution(req.model_dump())
    obs_id = _new_id()
    record = TradeOrderObservedRecord(
        order_obs_id=obs_id,
        external_order_id=req.external_order_id,
        status=req.status,
        symbol=req.symbol,
        side=req.side,
        quantity=req.quantity,
        executed_externally=True,
        execution_by_aether=False,
        tenant_id=tenant_id,
        observed_at=req.observed_at or _utc_now(),
    )
    repo = TradeObservationRepository()
    await repo.insert(obs_id, record.model_dump(mode="json"))
    if _use_canonical_spine(tenant_id):
        # Order requests carry no provider hint → provider "unknown"; the external
        # order id (when present) is the provider_event_id so retries dedupe.
        result = await ingest_observation(
            tenant_id=tenant_id,
            event_name="agent_trade_order_observed",
            provider_id="unknown",
            # Namespace by the observed brokerage so the same external_order_id
            # from two brokerages does not collide; include status so lifecycle
            # transitions (pending -> filled) are distinct, projected events while
            # identical (order, status) resends still dedupe.
            integration_id=req.brokerage_obs_id,
            provider_event_id=(f"{req.external_order_id}:{req.status}" if req.external_order_id else None),
            agent_id=req.agent_id,
            actor_id=req.agent_id,
            observed_at=req.observed_at,
            properties=_prune_none({
                "agentId": req.agent_id,
                "provider": "unknown",
                "objectType": "order",
                "objectId": req.external_order_id,
                "externalOrderId": req.external_order_id,
                "symbol": req.symbol,
                "side": req.side,
                "quantity": req.quantity,  # decimal string
                "status": req.status,
            }),
        )
        graph_mutations_queued = result.outbox_written
    else:
        mutations = build_order_mutations(tenant_id, obs_id, req.brokerage_obs_id)
        projection = await _persist_mutations(mutations, tenant_id=tenant_id, trace_id=obs_id)
        graph_mutations_queued = projection.graph_mutations_persisted
    return ExtAccountResponse(
        observation_id=obs_id, received_at=_utc_now(),
        graph_mutations_queued=graph_mutations_queued, tenant_id=tenant_id,
    )


@router.post("/v1/observability/external-accounts/budget-observations", response_model=ExtAccountResponse, status_code=201)
async def observe_agent_budget(req: BudgetObsRequest, request: Request) -> ExtAccountResponse:
    """Observe an agent budget state from an external platform."""
    _require_perm(request, "write")
    tenant_id = _tenant_id(request)
    validate_payload_tenant(req, tenant_id)
    _check_no_execution(req.model_dump())
    obs_id = _new_id()
    record = AgentBudgetObservedRecord(
        budget_obs_id=obs_id,
        account_obs_id=req.account_obs_id,
        total_budget=req.total_budget,
        used_budget=req.used_budget,
        available_budget=req.available_budget,
        currency=req.currency,
        tenant_id=tenant_id,
        observed_at=req.observed_at or _utc_now(),
    )
    repo = AgentBudgetRepository()
    await repo.insert(obs_id, record.model_dump(mode="json"))
    # TODO(AAI): budget delegation deferred — agent_budget_observed maps to
    # agent_cost_facts (no projector yet). Decimal-money hardening applies here
    # via AgentBudgetObservedRecord / BudgetObsRequest, but this route stays on
    # the legacy path (no canonical-spine ingest) until the cost projector lands.
    return ExtAccountResponse(
        observation_id=obs_id, received_at=_utc_now(),
        graph_mutations_queued=0, tenant_id=tenant_id,
    )


@router.get("/v1/admin/kyber/agentic-observability/external-accounts", dependencies=[Depends(require_kyber_operator)])
async def kyber_external_accounts(request: Request) -> dict:
    """Kyber operator: external account observability overview."""
    _require_perm(request, "admin")
    repo = ExternalAccountRepository()
    items = await repo.find_many(limit=100)
    return {"status": "ok", "external_accounts": items, "count": len(items)}
