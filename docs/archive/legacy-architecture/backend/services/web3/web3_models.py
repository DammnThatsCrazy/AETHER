"""
Aether — Web3 Analytics Pydantic Models
Data models for all Web3 analytics API endpoints.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class VMType(str, Enum):
    EVM = "evm"
    SVM = "svm"
    BITCOIN = "bitcoin"
    MOVEVM = "movevm"
    NEAR = "near"
    TVM = "tvm"
    COSMOS = "cosmos"


class WalletClassification(str, Enum):
    HOT = "hot"
    COLD = "cold"
    SMART = "smart"
    EXCHANGE = "exchange"
    PROTOCOL = "protocol"
    MULTISIG = "multisig"


class DeFiCategory(str, Enum):
    DEX = "dex"
    ROUTER = "router"
    LENDING = "lending"
    STAKING = "staking"
    RESTAKING = "restaking"
    PERPETUALS = "perpetuals"
    OPTIONS = "options"
    BRIDGE = "bridge"
    CEX = "cex"
    YIELD = "yield"
    NFT_MARKETPLACE = "nft_marketplace"
    GOVERNANCE = "governance"
    PAYMENTS = "payments"
    INSURANCE = "insurance"
    LAUNCHPAD = "launchpad"


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------

class TokenHolding(BaseModel):
    symbol: str
    name: str
    contract_address: str
    balance: str
    decimals: int
    usd_value: Optional[float] = None
    vm: VMType
    chain_id: str


class DeFiPositionView(BaseModel):
    protocol: str
    category: DeFiCategory
    position_type: str
    value_usd: Optional[float] = None
    apy: Optional[float] = None
    health_factor: Optional[float] = None
    pnl: Optional[float] = None
    vm: VMType
    chain_id: str


class WalletActivity(BaseModel):
    address: str
    vm: VMType
    chain_id: str
    wallet_type: str
    classification: WalletClassification
    display_name: Optional[str] = None
    first_seen: datetime
    last_active: datetime
    transaction_count: int = 0
    total_volume_usd: Optional[float] = None
    defi_interactions: int = 0
    connected_sessions: int = 0


class ChainDistribution(BaseModel):
    vm: VMType
    chain_id: str
    chain_name: str
    unique_wallets: int = 0
    transaction_count: int = 0
    total_volume_usd: Optional[float] = None
    defi_interactions: int = 0
    percentage: float = 0.0


class TransactionSummary(BaseModel):
    tx_hash: str
    vm: VMType
    chain_id: str
    from_address: str
    to_address: str
    value: Optional[str] = None
    status: str
    tx_type: Optional[str] = None
    protocol: Optional[str] = None
    defi_category: Optional[DeFiCategory] = None
    gas_cost_native: Optional[str] = None
    gas_cost_usd: Optional[float] = None
    timestamp: datetime


class DeFiSummary(BaseModel):
    category: DeFiCategory
    protocol: str
    vm: VMType
    chain_id: str
    interaction_count: int = 0
    unique_wallets: int = 0
    total_volume_usd: Optional[float] = None
    avg_position_size_usd: Optional[float] = None
    top_action: Optional[str] = None


class PortfolioView(BaseModel):
    user_id: str
    wallets: list[WalletActivity] = Field(default_factory=list)
    total_value_usd: Optional[float] = None
    chains_active: int = 0
    vms_active: int = 0
    tokens: list[TokenHolding] = Field(default_factory=list)
    defi_positions: list[DeFiPositionView] = Field(default_factory=list)
    last_updated: datetime


class WhaleEvent(BaseModel):
    tx_hash: str
    vm: VMType
    chain_id: str
    from_address: str
    to_address: str
    value: str
    value_usd: Optional[float] = None
    from_label: Optional[str] = None
    to_label: Optional[str] = None
    token: Optional[str] = None
    timestamp: datetime


class BridgeEvent(BaseModel):
    source_tx_hash: Optional[str] = None
    dest_tx_hash: Optional[str] = None
    bridge: str
    source_chain: str
    dest_chain: str
    source_vm: VMType
    dest_vm: VMType
    token: str
    amount: str
    fee: Optional[str] = None
    status: str
    timestamp: datetime


class ExchangeFlow(BaseModel):
    exchange: str
    direction: str  # "deposit" or "withdrawal"
    vm: VMType
    chain_id: str
    total_volume_usd: Optional[float] = None
    transaction_count: int = 0
    unique_wallets: int = 0
    period_start: datetime
    period_end: datetime


class PerpetualActivity(BaseModel):
    protocol: str
    vm: VMType
    chain_id: str
    action: str  # open_position, close_position, liquidation, etc.
    market: Optional[str] = None
    side: Optional[str] = None
    size: Optional[str] = None
    leverage: Optional[float] = None
    pnl: Optional[float] = None
    tx_hash: str
    timestamp: datetime
