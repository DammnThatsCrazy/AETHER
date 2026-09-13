"""
Aether — Web3 Analytics Service
Multi-VM wallet tracking, DeFi protocol analytics, and cross-chain portfolio queries.

Endpoints:
    GET /v1/web3/wallets/{project_id}         — Tracked wallets with classification + activity
    GET /v1/web3/chains/{project_id}          — Chain distribution + volume
    GET /v1/web3/transactions/{project_id}    — Multi-VM transaction history
    GET /v1/web3/defi/{project_id}            — DeFi interaction analytics
    GET /v1/web3/portfolio/{project_id}/{uid} — Cross-chain portfolio for user
    GET /v1/web3/whales/{project_id}          — Whale activity feed
    GET /v1/web3/bridges/{project_id}         — Bridge transaction tracking
    GET /v1/web3/exchanges/{project_id}       — CEX deposit/withdrawal flows
    GET /v1/web3/perpetuals/{project_id}      — Perpetuals/derivatives activity
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from .web3_models import (
    BridgeEvent,
    ChainDistribution,
    DeFiCategory,
    DeFiSummary,
    ExchangeFlow,
    PerpetualActivity,
    PortfolioView,
    TransactionSummary,
    VMType,
    WalletActivity,
    WalletClassification,
    WhaleEvent,
)
from .web3_queries import Web3QueryEngine

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/v1/web3", tags=["web3"])
query_engine = Web3QueryEngine()

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/wallets/{project_id}", response_model=list[WalletActivity])
async def get_wallets(
    project_id: str,
    vm: Optional[VMType] = None,
    classification: Optional[WalletClassification] = None,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Get tracked wallets with activity metrics."""
    since = datetime.utcnow() - timedelta(days=days)
    return query_engine.get_wallets(project_id, since, vm=vm, classification=classification, limit=limit)


@router.get("/chains/{project_id}", response_model=list[ChainDistribution])
async def get_chain_distribution(
    project_id: str,
    days: int = Query(default=30, ge=1, le=365),
):
    """Get chain distribution analytics (wallets, transactions, volume per chain)."""
    since = datetime.utcnow() - timedelta(days=days)
    return query_engine.get_chain_distribution(project_id, since)


@router.get("/transactions/{project_id}", response_model=list[TransactionSummary])
async def get_transactions(
    project_id: str,
    vm: Optional[VMType] = None,
    chain_id: Optional[str] = None,
    status: Optional[str] = None,
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Get multi-VM transaction history."""
    since = datetime.utcnow() - timedelta(days=days)
    return query_engine.get_transactions(
        project_id, since, vm=vm, chain_id=chain_id, status=status, limit=limit,
    )


@router.get("/defi/{project_id}", response_model=list[DeFiSummary])
async def get_defi_analytics(
    project_id: str,
    category: Optional[DeFiCategory] = None,
    protocol: Optional[str] = None,
    days: int = Query(default=30, ge=1, le=365),
):
    """Get DeFi interaction analytics by category and protocol."""
    since = datetime.utcnow() - timedelta(days=days)
    return query_engine.get_defi_analytics(project_id, since, category=category, protocol=protocol)


@router.get("/portfolio/{project_id}/{user_id}", response_model=PortfolioView)
async def get_portfolio(project_id: str, user_id: str):
    """Get cross-chain portfolio for a specific user."""
    portfolio = query_engine.get_portfolio(project_id, user_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail="User not found")
    return portfolio


@router.get("/whales/{project_id}", response_model=list[WhaleEvent])
async def get_whale_activity(
    project_id: str,
    vm: Optional[VMType] = None,
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=500),
):
    """Get whale activity feed (large-value transactions)."""
    since = datetime.utcnow() - timedelta(days=days)
    return query_engine.get_whale_activity(project_id, since, vm=vm, limit=limit)


@router.get("/bridges/{project_id}", response_model=list[BridgeEvent])
async def get_bridge_activity(
    project_id: str,
    bridge: Optional[str] = None,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Get bridge transaction tracking."""
    since = datetime.utcnow() - timedelta(days=days)
    return query_engine.get_bridge_activity(project_id, since, bridge=bridge, limit=limit)


@router.get("/exchanges/{project_id}", response_model=list[ExchangeFlow])
async def get_exchange_flows(
    project_id: str,
    exchange: Optional[str] = None,
    days: int = Query(default=30, ge=1, le=365),
):
    """Get CEX deposit/withdrawal flow analytics."""
    since = datetime.utcnow() - timedelta(days=days)
    return query_engine.get_exchange_flows(project_id, since, exchange=exchange)


@router.get("/perpetuals/{project_id}", response_model=list[PerpetualActivity])
async def get_perpetuals_activity(
    project_id: str,
    protocol: Optional[str] = None,
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Get perpetuals/derivatives trading activity."""
    since = datetime.utcnow() - timedelta(days=days)
    return query_engine.get_perpetuals_activity(project_id, since, protocol=protocol, limit=limit)
