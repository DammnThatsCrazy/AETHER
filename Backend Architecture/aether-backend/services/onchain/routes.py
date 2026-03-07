"""
Aether Service — On-Chain Action Routes (L0/L6)
Action recording, contract querying, chain listener configuration.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from shared.common.common import APIResponse, NotFoundError
from shared.logger.logger import get_logger

from .action_recorder import ActionRecorder
from .chain_listener import ChainListener
from .models import ActionRecord, ChainListenerConfig
from .rpc_gateway import RPCGateway

logger = get_logger("aether.service.onchain.routes")
router = APIRouter(prefix="/v1/onchain", tags=["On-Chain"])

_recorder = ActionRecorder()
_listener = ChainListener()
_rpc = RPCGateway()


@router.post("/actions")
async def record_action(body: ActionRecord, request: Request):
    """Record an on-chain action and create graph entities."""
    request.state.tenant.require_permission("onchain:write")
    result = await _recorder.record(body)
    return APIResponse(data=result.model_dump()).to_dict()


@router.get("/actions/{agent_id}")
async def get_agent_actions(agent_id: str, request: Request):
    """Get all on-chain actions for a specific agent."""
    request.state.tenant.require_permission("onchain:read")
    actions = await _recorder.get_agent_actions(agent_id)
    return APIResponse(data={"agent_id": agent_id, "actions": actions, "count": len(actions)}).to_dict()


@router.get("/contracts/{address}")
async def get_contract(address: str, request: Request):
    """Get contract details and call graph."""
    request.state.tenant.require_permission("onchain:read")
    info = await _recorder.get_contract_info(address)
    if not info:
        raise NotFoundError(f"Contract {address}")
    return APIResponse(data=info.model_dump()).to_dict()


@router.post("/listener/configure")
async def configure_listener(body: ChainListenerConfig, request: Request):
    """Configure a chain event listener stream."""
    request.state.tenant.require_permission("admin")
    config = await _listener.configure(body)
    return APIResponse(data=config.model_dump()).to_dict()


@router.get("/rpc/health")
async def rpc_health(request: Request):
    """Get RPC gateway health status."""
    request.state.tenant.require_permission("onchain:read")
    health = await _rpc.health_check()
    return APIResponse(data=health).to_dict()
