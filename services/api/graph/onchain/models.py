"""
Aether Service — On-Chain Action Models
ActionRecord schema, chain listener config, RPC request types.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


class ActionType:
    DEPLOY = "DEPLOY"
    CALL = "CALL"
    TRANSFER = "TRANSFER"
    UPGRADE = "UPGRADE"
    PAUSE = "PAUSE"
    DESTROY = "DESTROY"


class ActionRecord(BaseModel):
    """On-chain action record — the core schema for L0."""
    action_id: str = ""
    agent_id: str
    action_type: str = Field(..., pattern="^(DEPLOY|CALL|TRANSFER|UPGRADE|PAUSE|DESTROY)$")
    chain_id: str
    vm_type: str = Field(default="evm", pattern="^(evm|svm|movevm|near|tvm|cosmos)$")
    tx_hash: Optional[str] = None
    contract_address: Optional[str] = None
    method_name: Optional[str] = None
    intent_description: str = ""
    bytecode_hash: Optional[str] = None
    risk_score: float = 0.0
    gas_used: Optional[int] = None
    value_wei: Optional[str] = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChainListenerConfig(BaseModel):
    """Configuration for a chain event listener stream."""
    config_id: str = ""
    chain_id: str
    vm_type: str = "evm"
    rpc_endpoint: str = ""
    stream_id: Optional[str] = None
    filter_addresses: list[str] = Field(default_factory=list)
    event_signatures: list[str] = Field(default_factory=list)
    enabled: bool = True


class ContractInfo(BaseModel):
    """Contract metadata stored in the graph."""
    address: str
    chain_id: str
    vm_type: str = "evm"
    deployer_agent_id: Optional[str] = None
    bytecode_hash: Optional[str] = None
    name: Optional[str] = None
    risk_score: float = 0.0
    deployed_at: Optional[str] = None
    call_count: int = 0


class RPCRequest(BaseModel):
    """A single RPC request to the gateway."""
    chain_id: str
    method: str
    params: list[Any] = Field(default_factory=list)
    vm_type: str = "evm"
