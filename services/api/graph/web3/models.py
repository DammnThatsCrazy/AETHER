"""
Aether Web3 Coverage — Registry Models

All Web3 objects share a common provenance envelope:
  source, source_tag, observed_at, normalized_at, chain, classification_confidence,
  identity_confidence, freshness, replay/backfill status.

Registry objects support:
  stable_id, canonical_name, aliases, chain linkage, versioning, source/source_tag,
  confidence, completeness_status, timestamps, active/deprecated/migrated state.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════════
# COMPLETENESS & CONFIDENCE
# ═══════════════════════════════════════════════════════════════════════════


class CompletenessStatus(str, Enum):
    """Tracks classification/mapping progress for any Web3 object."""
    RAW_OBSERVED = "raw_observed"
    MINIMALLY_NORMALIZED = "minimally_normalized"
    PARTIALLY_CLASSIFIED = "partially_classified"
    PROTOCOL_MAPPED = "protocol_mapped"
    APP_MAPPED = "app_mapped"
    DOMAIN_MAPPED = "domain_mapped"
    HIGH_CONFIDENCE = "high_confidence"
    DEPRECATED = "deprecated"
    MIGRATED = "migrated"
    UNKNOWN_CONTRACT_SYSTEM = "unknown_contract_system"


class ObjectStatus(str, Enum):
    """Lifecycle status for registry objects."""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    MIGRATED = "migrated"
    PAUSED = "paused"
    DESTROYED = "destroyed"
    UNKNOWN = "unknown"


class MigrationType(str, Enum):
    """How a protocol/contract migrated."""
    UPGRADE = "upgrade"
    FORK = "fork"
    REDEPLOY = "redeploy"
    PROXY_UPDATE = "proxy_update"
    CHAIN_MIGRATION = "chain_migration"


# ═══════════════════════════════════════════════════════════════════════════
# CHAIN FAMILY / VM TYPE
# ═══════════════════════════════════════════════════════════════════════════


class VMFamily(str, Enum):
    """Virtual machine / execution environment family."""
    EVM = "evm"
    SVM = "svm"
    BITCOIN = "bitcoin"
    MOVEVM = "movevm"
    NEAR = "near"
    TVM = "tvm"
    COSMOS = "cosmos"
    UNKNOWN = "unknown"


class ChainType(str, Enum):
    """Chain operational type."""
    L1 = "l1"
    L2 = "l2"
    L3 = "l3"
    SIDECHAIN = "sidechain"
    APPCHAIN = "appchain"
    ROLLUP = "rollup"
    TESTNET = "testnet"


# ═══════════════════════════════════════════════════════════════════════════
# PROTOCOL FAMILIES / VERTICALS
# ═══════════════════════════════════════════════════════════════════════════


class ProtocolFamily(str, Enum):
    """High-level protocol vertical/category."""
    DEX = "dex"
    LENDING = "lending"
    BRIDGE = "bridge"
    STAKING = "staking"
    RESTAKING = "restaking"
    STABLECOIN = "stablecoin"
    GOVERNANCE = "governance"
    NFT_MARKETPLACE = "nft_marketplace"
    GAMING = "gaming"
    DEPIN = "depin"
    AGENT_AUTOMATION = "agent_automation"
    PAYMENTS = "payments"
    PREDICTION_MARKET = "prediction_market"
    RWA = "rwa"
    YIELD_AGGREGATOR = "yield_aggregator"
    DERIVATIVES = "derivatives"
    INSURANCE = "insurance"
    LAUNCHPAD = "launchpad"
    ORACLE = "oracle"
    INFRASTRUCTURE = "infrastructure"
    WALLET = "wallet"
    ANALYTICS = "analytics"
    OTHER = "other"


class ContractRole(str, Enum):
    """Role of a contract within a protocol system."""
    ROUTER = "router"
    FACTORY = "factory"
    VAULT = "vault"
    POOL = "pool"
    TOKEN = "token"
    GOVERNANCE = "governance"
    PROXY = "proxy"
    IMPLEMENTATION = "implementation"
    REGISTRY = "registry"
    ORACLE = "oracle"
    BRIDGE = "bridge"
    STAKING = "staking"
    REWARDS = "rewards"
    TREASURY = "treasury"
    TIMELOCK = "timelock"
    MULTISIG = "multisig"
    NFT = "nft"
    UNKNOWN = "unknown"


class TokenStandard(str, Enum):
    """Token interface standard."""
    ERC20 = "erc20"
    ERC721 = "erc721"
    ERC1155 = "erc1155"
    ERC4626 = "erc4626"
    SPL = "spl"
    BEP20 = "bep20"
    NATIVE = "native"
    OTHER = "other"


class AppCategory(str, Enum):
    """Application/dApp category."""
    WALLET_APP = "wallet"
    EXCHANGE = "exchange"
    DEX_AGGREGATOR = "dex_aggregator"
    PORTFOLIO_TRACKER = "portfolio_tracker"
    GOVERNANCE_DASHBOARD = "governance_dashboard"
    NFT_MARKETPLACE = "nft_marketplace"
    BRIDGE_UI = "bridge_ui"
    EXPLORER = "explorer"
    ANALYTICS_DASHBOARD = "analytics"
    LENDING_UI = "lending_ui"
    STAKING_UI = "staking_ui"
    MULTI_PURPOSE = "multi_purpose"
    OTHER = "other"


class VenueType(str, Enum):
    """Market venue type."""
    CEX = "cex"
    DEX = "dex"
    DEX_AGGREGATOR = "dex_aggregator"
    OTC = "otc"
    DERIVATIVES = "derivatives"
    NFT_MARKETPLACE = "nft_marketplace"


class DeployerType(str, Enum):
    """Deployer entity classification."""
    TEAM = "team"
    MULTISIG = "multisig"
    DAO = "dao"
    INDIVIDUAL = "individual"
    UNKNOWN = "unknown"


class GovernancePlatform(str, Enum):
    """Where governance is hosted."""
    SNAPSHOT = "snapshot"
    TALLY = "tally"
    ONCHAIN = "onchain"
    COMPOUND_GOVERNOR = "compound_governor"
    OTHER = "other"


# ═══════════════════════════════════════════════════════════════════════════
# CANONICAL ACTION FAMILIES (normalized across VMs)
# ═══════════════════════════════════════════════════════════════════════════


class CanonicalAction(str, Enum):
    """Chain-family-normalized action types."""
    TRANSFER = "transfer"
    SWAP = "swap"
    ADD_LIQUIDITY = "add_liquidity"
    REMOVE_LIQUIDITY = "remove_liquidity"
    LEND = "lend"
    BORROW = "borrow"
    REPAY = "repay"
    STAKE = "stake"
    UNSTAKE = "unstake"
    BRIDGE = "bridge"
    VOTE = "vote"
    DELEGATE = "delegate"
    MINT = "mint"
    BURN = "burn"
    CLAIM = "claim"
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"
    DEPLOY_CONTRACT = "deploy_contract"
    CALL_CONTRACT = "call_contract"
    APPROVE = "approve"
    LIST = "list"
    TRADE = "trade"
    REDEEM = "redeem"
    WRAP = "wrap"
    UNWRAP = "unwrap"
    FLASH_LOAN = "flash_loan"
    LIQUIDATE = "liquidate"
    CREATE_POSITION = "create_position"
    CLOSE_POSITION = "close_position"
    UNKNOWN = "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# PROVENANCE ENVELOPE (shared by all registry objects)
# ═══════════════════════════════════════════════════════════════════════════


class Provenance(BaseModel):
    """Provenance metadata attached to every Web3 observation."""
    source: str = Field(..., description="Provider or system that observed this data")
    source_tag: str = Field(default="", description="Unique batch/run identifier for rollback")
    observed_at: str = Field(default="", description="ISO8601 timestamp of first observation")
    normalized_at: str = Field(default="", description="ISO8601 timestamp of normalization")
    chain: str = Field(default="", description="Chain ID or canonical chain name")
    classification_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    identity_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    freshness_seconds: int = Field(default=0, description="Seconds since last observation")
    is_backfill: bool = Field(default=False, description="True if from historical replay")


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY MODELS — CHAIN
# ═══════════════════════════════════════════════════════════════════════════


class ChainCreate(BaseModel):
    """Register a new chain in the registry."""
    chain_id: str = Field(..., description="Stable canonical ID (e.g., 'ethereum', 'base', 'solana')")
    canonical_name: str = Field(..., description="Human-readable name")
    aliases: list[str] = Field(default_factory=list)
    vm_family: VMFamily = VMFamily.EVM
    chain_type: ChainType = ChainType.L1
    evm_chain_id: Optional[int] = Field(default=None, description="Numeric EVM chain ID (1 for Ethereum, 8453 for Base, etc.)")
    native_token_symbol: str = Field(default="ETH")
    block_explorer_url: str = Field(default="")
    rpc_default: str = Field(default="")
    genesis_date: str = Field(default="")
    parent_chain_id: Optional[str] = Field(default=None, description="L2s/L3s reference parent")
    status: ObjectStatus = ObjectStatus.ACTIVE
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class ChainRecord(ChainCreate):
    """Full chain record with provenance."""
    registered_at: str = Field(default="")
    updated_at: str = Field(default="")
    completeness: CompletenessStatus = CompletenessStatus.MINIMALLY_NORMALIZED
    protocol_count: int = Field(default=0)
    contract_count: int = Field(default=0)


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY MODELS — PROTOCOL
# ═══════════════════════════════════════════════════════════════════════════


class ProtocolCreate(BaseModel):
    """Register a protocol in the registry."""
    protocol_id: str = Field(..., description="Stable canonical ID (e.g., 'uniswap', 'aave', 'lido')")
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    protocol_family: ProtocolFamily = ProtocolFamily.OTHER
    protocol_version: str = Field(default="v1")
    chains: list[str] = Field(default_factory=list, description="Chain IDs where deployed")
    primary_chain: str = Field(default="ethereum")
    contract_systems: list[str] = Field(default_factory=list, description="Contract system IDs")
    website: str = Field(default="")
    docs_url: str = Field(default="")
    governance_space_id: Optional[str] = None
    deployer_entity_id: Optional[str] = None
    tvl_source: str = Field(default="defillama", description="Where to fetch TVL data")
    defillama_slug: str = Field(default="", description="DeFiLlama protocol slug")
    coingecko_id: str = Field(default="", description="CoinGecko token ID")
    status: ObjectStatus = ObjectStatus.ACTIVE
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class ProtocolRecord(ProtocolCreate):
    """Full protocol record with provenance."""
    registered_at: str = Field(default="")
    updated_at: str = Field(default="")
    completeness: CompletenessStatus = CompletenessStatus.MINIMALLY_NORMALIZED
    classification_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    tvl_usd: Optional[float] = None
    tvl_updated_at: str = Field(default="")


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY MODELS — CONTRACT SYSTEM
# ═══════════════════════════════════════════════════════════════════════════


class ContractSystemCreate(BaseModel):
    """Register a contract system (group of related contracts for a protocol)."""
    system_id: str = Field(..., description="Stable ID (e.g., 'uniswap-v3-ethereum')")
    canonical_name: str
    protocol_id: str = Field(..., description="Parent protocol")
    chain_id: str = Field(..., description="Chain deployed on")
    contract_roles: list[ContractRole] = Field(default_factory=list)
    verified_source: bool = Field(default=False)
    deployer_address: str = Field(default="")
    status: ObjectStatus = ObjectStatus.ACTIVE
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class ContractSystemRecord(ContractSystemCreate):
    """Full contract system record."""
    registered_at: str = Field(default="")
    updated_at: str = Field(default="")
    completeness: CompletenessStatus = CompletenessStatus.MINIMALLY_NORMALIZED
    instance_count: int = Field(default=0)


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY MODELS — CONTRACT INSTANCE
# ═══════════════════════════════════════════════════════════════════════════


class ContractInstanceCreate(BaseModel):
    """Register a specific deployed contract."""
    address: str = Field(..., description="On-chain contract address")
    chain_id: str
    system_id: str = Field(default="", description="Parent contract system (empty if unknown)")
    protocol_id: str = Field(default="", description="Parent protocol (empty if unknown)")
    role: ContractRole = ContractRole.UNKNOWN
    deployed_at: str = Field(default="")
    deployed_by: str = Field(default="", description="Deployer address")
    bytecode_hash: str = Field(default="")
    is_proxy: bool = Field(default=False)
    implementation_address: str = Field(default="")
    name: str = Field(default="")
    status: ObjectStatus = ObjectStatus.ACTIVE
    migrated_to: str = Field(default="", description="Address of successor contract")
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class ContractInstanceRecord(ContractInstanceCreate):
    """Full contract instance record."""
    instance_id: str = Field(default="")
    registered_at: str = Field(default="")
    updated_at: str = Field(default="")
    completeness: CompletenessStatus = CompletenessStatus.RAW_OBSERVED
    classification_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    call_count: int = Field(default=0)
    risk_score: float = Field(default=0.0)


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY MODELS — TOKEN
# ═══════════════════════════════════════════════════════════════════════════


class TokenCreate(BaseModel):
    """Register a token."""
    token_id: str = Field(..., description="Stable ID (e.g., 'eth-ethereum', 'usdc-ethereum')")
    symbol: str
    name: str
    chain_id: str
    address: str = Field(default="", description="Contract address (empty for native tokens)")
    standard: TokenStandard = TokenStandard.ERC20
    decimals: int = Field(default=18)
    protocol_id: str = Field(default="", description="Associated protocol if any")
    is_stablecoin: bool = False
    is_wrapped: bool = False
    underlying_token_id: str = Field(default="", description="For wrapped tokens")
    coingecko_id: str = Field(default="")
    total_supply: str = Field(default="")
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class TokenRecord(TokenCreate):
    """Full token record."""
    registered_at: str = Field(default="")
    updated_at: str = Field(default="")
    completeness: CompletenessStatus = CompletenessStatus.MINIMALLY_NORMALIZED
    price_usd: Optional[float] = None
    price_updated_at: str = Field(default="")
    market_cap_usd: Optional[float] = None


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY MODELS — APP / DAPP
# ═══════════════════════════════════════════════════════════════════════════


class AppCreate(BaseModel):
    """Register an app or dApp."""
    app_id: str = Field(..., description="Stable ID (e.g., 'uniswap-app', 'metamask')")
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    category: AppCategory = AppCategory.OTHER
    protocols: list[str] = Field(default_factory=list, description="Protocol IDs this app fronts")
    frontend_domains: list[str] = Field(default_factory=list, description="Domains serving this app")
    chains: list[str] = Field(default_factory=list)
    deployer_entity_id: str = Field(default="")
    website: str = Field(default="")
    status: ObjectStatus = ObjectStatus.ACTIVE
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class AppRecord(AppCreate):
    """Full app record."""
    registered_at: str = Field(default="")
    updated_at: str = Field(default="")
    completeness: CompletenessStatus = CompletenessStatus.MINIMALLY_NORMALIZED


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY MODELS — FRONTEND DOMAIN
# ═══════════════════════════════════════════════════════════════════════════


class FrontendDomainCreate(BaseModel):
    """Register a frontend domain."""
    domain: str = Field(..., description="e.g., 'app.uniswap.org'")
    app_id: str = Field(default="")
    protocol_ids: list[str] = Field(default_factory=list)
    chain_ids: list[str] = Field(default_factory=list)
    verified: bool = False
    first_seen: str = Field(default="")
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class FrontendDomainRecord(FrontendDomainCreate):
    """Full frontend domain record."""
    domain_id: str = Field(default="")
    registered_at: str = Field(default="")
    updated_at: str = Field(default="")
    last_seen: str = Field(default="")
    completeness: CompletenessStatus = CompletenessStatus.RAW_OBSERVED


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY MODELS — GOVERNANCE SPACE
# ═══════════════════════════════════════════════════════════════════════════


class GovernanceSpaceCreate(BaseModel):
    """Register a governance space."""
    space_id: str = Field(..., description="e.g., 'uniswap.eth' for Snapshot")
    canonical_name: str
    protocol_id: str = Field(default="")
    platform: GovernancePlatform = GovernancePlatform.SNAPSHOT
    chain_id: str = Field(default="ethereum")
    voting_token_id: str = Field(default="")
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class GovernanceSpaceRecord(GovernanceSpaceCreate):
    """Full governance space record."""
    registered_at: str = Field(default="")
    updated_at: str = Field(default="")
    delegate_count: int = Field(default=0)
    proposal_count: int = Field(default=0)
    completeness: CompletenessStatus = CompletenessStatus.MINIMALLY_NORMALIZED


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY MODELS — MARKET VENUE
# ═══════════════════════════════════════════════════════════════════════════


class MarketVenueCreate(BaseModel):
    """Register a market venue (CEX/DEX)."""
    venue_id: str = Field(..., description="e.g., 'binance', 'uniswap-v3-ethereum'")
    canonical_name: str
    venue_type: VenueType = VenueType.CEX
    chains: list[str] = Field(default_factory=list, description="For DEXs")
    protocol_id: str = Field(default="", description="For DEXs")
    api_provider: str = Field(default="", description="Provider adapter name")
    website: str = Field(default="")
    status: ObjectStatus = ObjectStatus.ACTIVE
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class MarketVenueRecord(MarketVenueCreate):
    """Full market venue record."""
    registered_at: str = Field(default="")
    updated_at: str = Field(default="")
    supported_pairs_count: int = Field(default=0)
    completeness: CompletenessStatus = CompletenessStatus.MINIMALLY_NORMALIZED


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY MODELS — BRIDGE ROUTE
# ═══════════════════════════════════════════════════════════════════════════


class BridgeRouteCreate(BaseModel):
    """Register a bridge route."""
    route_id: str = Field(..., description="e.g., 'stargate-ethereum-arbitrum'")
    bridge_protocol_id: str
    source_chain_id: str
    destination_chain_id: str
    supported_tokens: list[str] = Field(default_factory=list, description="Token IDs")
    avg_time_seconds: int = Field(default=0)
    status: ObjectStatus = ObjectStatus.ACTIVE
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class BridgeRouteRecord(BridgeRouteCreate):
    """Full bridge route record."""
    registered_at: str = Field(default="")
    updated_at: str = Field(default="")
    completeness: CompletenessStatus = CompletenessStatus.MINIMALLY_NORMALIZED


# ═══════════════════════════════════════════════════════════════════════════
# REGISTRY MODELS — DEPLOYER ENTITY
# ═══════════════════════════════════════════════════════════════════════════


class DeployerEntityCreate(BaseModel):
    """Register a deployer/team/multisig entity."""
    entity_id: str = Field(..., description="Stable ID")
    canonical_name: str
    entity_type: DeployerType = DeployerType.UNKNOWN
    addresses: list[str] = Field(default_factory=list, description="Known on-chain addresses")
    protocols: list[str] = Field(default_factory=list, description="Protocols controlled")
    known_members: list[str] = Field(default_factory=list)
    source: str = Field(default="manual")
    source_tag: str = Field(default="")


class DeployerEntityRecord(DeployerEntityCreate):
    """Full deployer entity record."""
    registered_at: str = Field(default="")
    updated_at: str = Field(default="")
    completeness: CompletenessStatus = CompletenessStatus.MINIMALLY_NORMALIZED


# ═══════════════════════════════════════════════════════════════════════════
# MIGRATION RECORD
# ═══════════════════════════════════════════════════════════════════════════


class MigrationCreate(BaseModel):
    """Record a protocol/contract migration."""
    protocol_id: str
    from_version: str
    to_version: str
    from_contracts: list[str] = Field(default_factory=list, description="Old contract addresses")
    to_contracts: list[str] = Field(default_factory=list, description="New contract addresses")
    migration_type: MigrationType = MigrationType.UPGRADE
    chain_id: str = Field(default="")
    confirmed: bool = False
    detected_by: str = Field(default="manual")
    source_tag: str = Field(default="")


class MigrationRecord(MigrationCreate):
    """Full migration record."""
    migration_id: str = Field(default="")
    detected_at: str = Field(default="")
    lineage_preserved: bool = Field(default=True)


# ═══════════════════════════════════════════════════════════════════════════
# COVERAGE STATUS
# ═══════════════════════════════════════════════════════════════════════════


class CoverageQuery(BaseModel):
    """Query coverage status across registries."""
    registry: str = Field(default="all", description="chain/protocol/contract/token/app/domain/all")
    chain_id: str = Field(default="")
    status: str = Field(default="")
    completeness: str = Field(default="")
    limit: int = Field(default=100, ge=1, le=1000)


class CoverageStatus(BaseModel):
    """Aggregated coverage status."""
    chains: int = 0
    protocols: int = 0
    contract_systems: int = 0
    contract_instances: int = 0
    tokens: int = 0
    apps: int = 0
    frontend_domains: int = 0
    governance_spaces: int = 0
    market_venues: int = 0
    bridge_routes: int = 0
    deployer_entities: int = 0
    migrations: int = 0
    completeness_distribution: dict[str, int] = Field(default_factory=dict)
    computed_at: str = Field(default="")


# ═══════════════════════════════════════════════════════════════════════════
# WEB3 OBSERVATION EVENT (for lake ingestion)
# ═══════════════════════════════════════════════════════════════════════════


class Web3Observation(BaseModel):
    """A single Web3 observation from any source, destined for Bronze lake tier."""
    observation_type: str = Field(..., description="tx/transfer/swap/contract_deploy/token_event/governance_vote/bridge/etc.")
    chain_id: str
    tx_hash: str = Field(default="")
    block_number: int = Field(default=0)
    from_address: str = Field(default="")
    to_address: str = Field(default="")
    contract_address: str = Field(default="")
    method_selector: str = Field(default="", description="First 4 bytes of calldata (hex)")
    canonical_action: CanonicalAction = CanonicalAction.UNKNOWN
    value_raw: str = Field(default="0")
    value_usd: Optional[float] = None
    token_address: str = Field(default="")
    token_symbol: str = Field(default="")
    protocol_id: str = Field(default="", description="Classified protocol (empty if unknown)")
    app_id: str = Field(default="", description="Classified app (empty if unknown)")
    domain: str = Field(default="", description="Frontend domain if from SDK")
    raw_data: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance = Field(default_factory=lambda: Provenance(source="unknown"))
