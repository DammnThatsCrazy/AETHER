"""
Aether Service — Financial Flows (Profile 360)

Records asset movements between entities, attributed to actor, agent, event,
and (optionally) the delegation under which the movement was authorized.

This is additive — the existing on-chain action recorder
(/v1/onchain/actions) continues to operate as the authoritative source for
chain-native events. Flows here unify on-chain transfers, off-chain transfers,
and credit movements under one ledger keyed by entity_id.

Endpoints:
    POST /v1/flows/transfers                 Record a transfer
    GET  /v1/flows/transfers                 List by entity
    POST /v1/flows/wallets                   Link a wallet to an entity
    GET  /v1/flows/wallets                   List wallets for an entity
    POST /v1/flows/assets                    Register an asset
    GET  /v1/flows/assets/{asset_id}         Read an asset
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.events.events import Event, EventProducer, Topic
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.logger.logger import get_logger, metrics
from dependencies.providers import get_graph, get_producer
from repositories.repos import (
    AssetRepository,
    TransferRepository,
    WalletRepository,
)

logger = get_logger("aether.service.flows")
router = APIRouter(prefix="/v1/flows", tags=["Profile 360 / Flows"])

_wallets = WalletRepository()
_assets = AssetRepository()
_transfers = TransferRepository()


# ── Request models ─────────────────────────────────────────────────────

class TransferCreate(BaseModel):
    transfer_id: str = ""
    from_entity_id: str
    to_entity_id: str
    asset_id: str
    amount: str = Field(..., description="Decimal as string for precision")
    attributed_agent_id: Optional[str] = None
    attributed_event_id: Optional[str] = None
    delegation_id: Optional[str] = None
    tx_hash: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WalletLink(BaseModel):
    wallet_id: str = ""
    owner_entity_id: str
    chain: str
    address: str = Field(..., min_length=1)


class AssetCreate(BaseModel):
    asset_id: str = ""
    asset_type: str = Field(..., pattern="^(token|nft|fiat|credit)$")
    chain: Optional[str] = None
    symbol: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("/transfers")
async def record_transfer(
    body: TransferCreate,
    request: Request,
    graph: GraphClient = Depends(get_graph),
    producer: EventProducer = Depends(get_producer),
):
    tenant = request.state.tenant
    tenant.require_permission("write")
    transfer_id = body.transfer_id or str(uuid.uuid4())
    record = await _transfers.record_transfer(
        transfer_id=transfer_id,
        tenant_id=tenant.tenant_id,
        from_entity_id=body.from_entity_id,
        to_entity_id=body.to_entity_id,
        asset_id=body.asset_id,
        amount=body.amount,
        attributed_agent_id=body.attributed_agent_id,
        attributed_event_id=body.attributed_event_id,
        delegation_id=body.delegation_id,
        tx_hash=body.tx_hash,
        metadata=body.metadata,
    )

    try:
        await graph.add_edge(Edge(
            edge_type=EdgeType.TRANSFERRED,
            from_vertex_id=body.from_entity_id,
            to_vertex_id=body.to_entity_id,
            properties={
                "tenant_id": tenant.tenant_id,
                "transfer_id": transfer_id,
                "asset_id": body.asset_id,
                "amount": str(body.amount),
                "attributed_agent_id": body.attributed_agent_id or "",
                "attributed_event_id": body.attributed_event_id or "",
            },
        ))
    except Exception as e:  # pragma: no cover
        logger.warning(f"Graph projection failed for transfer {transfer_id}: {e}")

    await producer.publish(Event(
        topic=Topic.FLOW_TRANSFER,
        tenant_id=tenant.tenant_id,
        source_service="flows",
        payload={
            "transfer_id": transfer_id,
            "from_entity_id": body.from_entity_id,
            "to_entity_id": body.to_entity_id,
            "asset_id": body.asset_id,
            "amount": body.amount,
        },
    ))
    metrics.increment("flow_transfers_recorded")
    return APIResponse(data=record).to_dict()


@router.get("/transfers")
async def list_transfers(
    request: Request,
    entity_id: str = Query(..., description="Entity to look up flows for"),
    limit: int = Query(100, ge=1, le=500),
):
    tenant = request.state.tenant
    tenant.require_permission("read")
    rows = await _transfers.list_for_entity(entity_id, limit=limit)
    rows = [r for r in rows if r.get("tenant_id") == tenant.tenant_id]
    return APIResponse(data={
        "entity_id": entity_id,
        "transfers": rows,
        "count": len(rows),
    }).to_dict()


@router.post("/wallets")
async def link_wallet(
    body: WalletLink,
    request: Request,
    graph: GraphClient = Depends(get_graph),
    producer: EventProducer = Depends(get_producer),
):
    tenant = request.state.tenant
    tenant.require_permission("write")
    wallet_id = body.wallet_id or str(uuid.uuid4())
    record = await _wallets.link_wallet(
        wallet_id=wallet_id,
        owner_entity_id=body.owner_entity_id,
        tenant_id=tenant.tenant_id,
        chain=body.chain,
        address=body.address,
    )
    # Project: ensure wallet vertex exists, then OWNS edge.
    await graph.upsert_vertex(Vertex(
        vertex_type=VertexType.WALLET,
        vertex_id=wallet_id,
        properties={
            "tenant_id": tenant.tenant_id,
            "chain": body.chain,
            "address": body.address,
        },
    ))
    await graph.add_edge(Edge(
        edge_type=EdgeType.OWNS,
        from_vertex_id=body.owner_entity_id,
        to_vertex_id=wallet_id,
        properties={"tenant_id": tenant.tenant_id, "kind": "wallet"},
    ))
    await producer.publish(Event(
        topic=Topic.FLOW_WALLET_LINKED,
        tenant_id=tenant.tenant_id,
        source_service="flows",
        payload={
            "wallet_id": wallet_id,
            "owner_entity_id": body.owner_entity_id,
            "chain": body.chain,
        },
    ))
    return APIResponse(data=record).to_dict()


@router.get("/wallets")
async def list_wallets(
    request: Request,
    entity_id: str = Query(...),
    limit: int = Query(100, ge=1, le=500),
):
    tenant = request.state.tenant
    tenant.require_permission("read")
    rows = await _wallets.find_many(
        filters={"owner_entity_id": entity_id}, limit=limit,
    )
    rows = [r for r in rows if r.get("tenant_id") == tenant.tenant_id]
    return APIResponse(data={
        "entity_id": entity_id,
        "wallets": rows,
        "count": len(rows),
    }).to_dict()


@router.post("/assets")
async def register_asset(body: AssetCreate, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    asset_id = body.asset_id or str(uuid.uuid4())
    record = await _assets.insert(asset_id, {
        "asset_id": asset_id,
        "tenant_id": tenant.tenant_id,
        "asset_type": body.asset_type,
        "chain": body.chain,
        "symbol": body.symbol,
        "metadata": body.metadata,
    })
    return APIResponse(data=record).to_dict()


@router.get("/assets/{asset_id}")
async def read_asset(asset_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    record = await _assets.find_by_id(asset_id)
    if record is None or record.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Asset")
    return APIResponse(data=record).to_dict()
