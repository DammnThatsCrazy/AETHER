"""
External Account Observability Routes.

INVARIANT: These routes never trade, execute orders, or manage external accounts.
They observe and record external agentic and brokerage account activity.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

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
from services.external_account_observability.graph_mutations import (
    build_account_mutations, build_brokerage_mutations,
    build_trade_intent_mutations, build_order_mutations, build_portfolio_mutations,
)

router = APIRouter()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _check_no_execution(data: dict) -> None:
    if data.get("execution_by_aether") is True:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="execution_by_aether must be false. AETHER does not execute.",
        )


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
    total_value: Optional[float] = None
    positions: list[dict[str, Any]] = Field(default_factory=list)
    observed_at: Optional[str] = None


class OrderObsRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    brokerage_obs_id: Optional[str] = None
    agent_id: Optional[str] = None
    symbol: str
    side: str = "buy"
    quantity: float
    status: str = "pending"
    external_order_id: Optional[str] = None
    executed_externally: Literal[True] = True
    execution_by_aether: Literal[False] = False
    observed_at: Optional[str] = None


class BudgetObsRequest(BaseModel):
    schema_version: str = "1.0"
    tenant_id: str
    account_obs_id: Optional[str] = None
    total_budget: Optional[float] = None
    used_budget: Optional[float] = None
    available_budget: Optional[float] = None
    currency: str = "USD"
    observed_at: Optional[str] = None


class ExtAccountResponse(BaseModel):
    observation_id: str
    received_at: str
    graph_mutations_queued: int = 0
    tenant_id: str


@router.post("/v1/observability/external-accounts", response_model=ExtAccountResponse, status_code=201)
async def observe_external_account(req: ExtAccountRequest) -> ExtAccountResponse:
    """Observe an external agentic account linkage."""
    _check_no_execution(req.model_dump())
    obs_id = _new_id()
    record = ExternalAgenticAccountObservedRecord(
        account_obs_id=obs_id,
        agent_id=req.agent_id,
        provider=req.provider,
        external_account_id=req.external_account_id,
        account_type=req.account_type,
        permissions_observed=req.permissions_observed,
        tenant_id=req.tenant_id,
    )
    repo = ExternalAccountRepository()
    await repo.insert(obs_id, record.model_dump(mode="json"))
    mutations = build_account_mutations(req.tenant_id, obs_id, req.agent_id)
    return ExtAccountResponse(
        observation_id=obs_id, received_at=_utc_now(),
        graph_mutations_queued=len(mutations), tenant_id=req.tenant_id,
    )


@router.post("/v1/observability/external-accounts/brokerage", response_model=ExtAccountResponse, status_code=201)
async def observe_brokerage_account(req: BrokerageRequest) -> ExtAccountResponse:
    """Observe an external brokerage account."""
    _check_no_execution(req.model_dump())
    obs_id = _new_id()
    record = ExternalBrokerageAccountObservedRecord(
        brokerage_obs_id=obs_id,
        agent_id=req.agent_id,
        provider=req.provider,
        external_account_id=req.external_account_id,
        account_type=req.account_type,
        tenant_id=req.tenant_id,
    )
    repo = ExternalBrokerageRepository()
    await repo.insert(obs_id, record.model_dump(mode="json"))
    mutations = build_brokerage_mutations(req.tenant_id, obs_id, req.agent_id)
    return ExtAccountResponse(
        observation_id=obs_id, received_at=_utc_now(),
        graph_mutations_queued=len(mutations), tenant_id=req.tenant_id,
    )


@router.post("/v1/observability/external-accounts/portfolio-snapshots", response_model=ExtAccountResponse, status_code=201)
async def observe_portfolio_snapshot(req: PortfolioSnapshotRequest) -> ExtAccountResponse:
    """Observe a portfolio snapshot from an external brokerage."""
    obs_id = _new_id()
    record = PortfolioSnapshotObservedRecord(
        portfolio_obs_id=obs_id,
        brokerage_obs_id=req.brokerage_obs_id,
        total_value=req.total_value,
        positions=req.positions,
        tenant_id=req.tenant_id,
        snapshot_at=req.observed_at or _utc_now(),
    )
    repo = PortfolioSnapshotRepository()
    await repo.insert(obs_id, record.model_dump(mode="json"))
    mutations = build_portfolio_mutations(req.tenant_id, obs_id, req.brokerage_obs_id)
    return ExtAccountResponse(
        observation_id=obs_id, received_at=_utc_now(),
        graph_mutations_queued=len(mutations), tenant_id=req.tenant_id,
    )


@router.post("/v1/observability/external-accounts/order-observations", response_model=ExtAccountResponse, status_code=201)
async def observe_trade_order(req: OrderObsRequest) -> ExtAccountResponse:
    """Observe a trade order (executed externally, not by AETHER)."""
    _check_no_execution(req.model_dump())
    obs_id = _new_id()
    record = TradeOrderObservedRecord(
        order_obs_id=obs_id,
        external_order_id=req.external_order_id,
        status=req.status,
        symbol=req.symbol,
        quantity=req.quantity,
        executed_externally=True,
        execution_by_aether=False,
        tenant_id=req.tenant_id,
        observed_at=req.observed_at or _utc_now(),
    )
    repo = TradeObservationRepository()
    await repo.insert(obs_id, record.model_dump(mode="json"))
    mutations = build_order_mutations(req.tenant_id, obs_id, req.brokerage_obs_id)
    return ExtAccountResponse(
        observation_id=obs_id, received_at=_utc_now(),
        graph_mutations_queued=len(mutations), tenant_id=req.tenant_id,
    )


@router.post("/v1/observability/external-accounts/budget-observations", response_model=ExtAccountResponse, status_code=201)
async def observe_agent_budget(req: BudgetObsRequest) -> ExtAccountResponse:
    """Observe an agent budget state from an external platform."""
    obs_id = _new_id()
    record = AgentBudgetObservedRecord(
        budget_obs_id=obs_id,
        account_obs_id=req.account_obs_id,
        total_budget=req.total_budget,
        used_budget=req.used_budget,
        available_budget=req.available_budget,
        currency=req.currency,
        tenant_id=req.tenant_id,
        observed_at=req.observed_at or _utc_now(),
    )
    repo = AgentBudgetRepository()
    await repo.insert(obs_id, record.model_dump(mode="json"))
    return ExtAccountResponse(
        observation_id=obs_id, received_at=_utc_now(),
        graph_mutations_queued=0, tenant_id=req.tenant_id,
    )


@router.get("/v1/admin/kyber/agentic-observability/external-accounts")
async def kyber_external_accounts() -> dict:
    """Kyber operator: external account observability overview."""
    return {"status": "ok", "external_accounts": []}
