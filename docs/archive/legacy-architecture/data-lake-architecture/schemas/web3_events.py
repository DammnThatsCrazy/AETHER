"""
Aether — Data Lake Web3 Event Schemas
Expanded Silver/Gold tier schemas for multi-VM + DeFi events.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

# ---------------------------------------------------------------------------
# Schema definitions
# ---------------------------------------------------------------------------

class VMType(str, Enum):
    EVM = "evm"
    SVM = "svm"
    BITCOIN = "bitcoin"
    MOVEVM = "movevm"
    NEAR = "near"
    TVM = "tvm"
    COSMOS = "cosmos"


# ---------------------------------------------------------------------------
# Silver Tier — Deduplicated, typed Web3 events
# ---------------------------------------------------------------------------

SILVER_WEB3_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS silver_web3_events (
    -- Event identifiers
    event_id        String,
    event_type      String,         -- wallet, transaction, defi_interaction, whale_alert, etc.
    timestamp       DateTime64(3),
    project_id      String,
    session_id      String,
    anonymous_id    String,
    user_id         Nullable(String),

    -- Multi-VM fields
    vm              LowCardinality(String),  -- evm, svm, bitcoin, movevm, near, tvm, cosmos
    chain_id        String,
    chain_name      Nullable(String),

    -- Wallet fields
    wallet_address  Nullable(String),
    wallet_type     Nullable(String),
    wallet_classification  Nullable(String),  -- hot, cold, smart, exchange, protocol, multisig
    wallet_action   Nullable(String),         -- connect, disconnect, sign, approve, etc.

    -- Transaction fields
    tx_hash         Nullable(String),
    tx_from         Nullable(String),
    tx_to           Nullable(String),
    tx_value        Nullable(String),
    tx_status       Nullable(String),         -- pending, confirmed, failed
    tx_type         Nullable(String),         -- transfer, swap, stake, bridge, etc.

    -- Gas/fee fields
    gas_used        Nullable(String),
    gas_price       Nullable(String),
    gas_cost_native Nullable(String),
    gas_cost_usd    Nullable(Float64),
    compute_units   Nullable(UInt64),         -- Solana
    energy_used     Nullable(UInt64),         -- TRON
    bandwidth_used  Nullable(UInt64),         -- TRON

    -- DeFi fields
    protocol_name   Nullable(String),
    defi_category   Nullable(String),         -- dex, lending, staking, perpetuals, etc.
    defi_action     Nullable(String),         -- swap, supply, borrow, open_position, etc.

    -- Token fields
    token_symbol    Nullable(String),
    token_address   Nullable(String),
    token_amount    Nullable(String),
    token_standard  Nullable(String),         -- erc20, spl, trc20, etc.

    -- NFT fields
    nft_contract    Nullable(String),
    nft_token_id    Nullable(String),
    nft_standard    Nullable(String),         -- erc721, erc1155, metaplex, ordinal

    -- Bridge fields
    bridge_name     Nullable(String),
    source_chain    Nullable(String),
    dest_chain      Nullable(String),
    bridge_status   Nullable(String),

    -- Perpetuals fields
    perp_market     Nullable(String),
    perp_side       Nullable(String),         -- long, short
    perp_leverage   Nullable(Float64),
    perp_size       Nullable(String),
    perp_pnl        Nullable(Float64),

    -- Labels
    from_label      Nullable(String),
    to_label        Nullable(String),

    -- Whale alert
    whale_threshold Nullable(String),
    value_usd       Nullable(Float64),

    -- Context
    sdk_version     String DEFAULT '',
    ip_country      Nullable(String),
    device_type     Nullable(String),
    browser         Nullable(String)
)
ENGINE = MergeTree()
PARTITION BY (project_id, toYYYYMM(timestamp))
ORDER BY (project_id, vm, event_type, timestamp, event_id)
TTL timestamp + INTERVAL 365 DAY
SETTINGS index_granularity = 8192;
"""


# ---------------------------------------------------------------------------
# Gold Tier — Daily Web3 metrics
# ---------------------------------------------------------------------------

GOLD_WEB3_DAILY_METRICS_DDL = """
CREATE TABLE IF NOT EXISTS gold_web3_daily_metrics (
    date            Date,
    project_id      String,

    -- Overall Web3 metrics
    wallets_connected        UInt64 DEFAULT 0,
    wallets_by_vm            Map(String, UInt64),      -- {evm: 100, svm: 50, ...}
    wallets_by_classification Map(String, UInt64),     -- {hot: 80, cold: 20, ...}
    unique_active_wallets    UInt64 DEFAULT 0,

    -- Transaction metrics
    total_transactions       UInt64 DEFAULT 0,
    transactions_by_vm       Map(String, UInt64),
    transactions_by_status   Map(String, UInt64),      -- {confirmed: 900, failed: 50, pending: 50}
    total_volume_usd         Float64 DEFAULT 0,

    -- Gas/fee metrics
    total_gas_cost_usd       Float64 DEFAULT 0,
    avg_gas_cost_usd         Float64 DEFAULT 0,
    gas_cost_by_vm           Map(String, Float64),

    -- DeFi metrics
    defi_interactions        UInt64 DEFAULT 0,
    defi_by_category         Map(String, UInt64),      -- {dex: 200, lending: 50, ...}
    defi_by_protocol         Map(String, UInt64),      -- {uniswap: 100, aave: 30, ...}
    unique_defi_users        UInt64 DEFAULT 0,

    -- Perpetuals metrics
    perp_positions_opened    UInt64 DEFAULT 0,
    perp_positions_closed    UInt64 DEFAULT 0,
    perp_liquidations        UInt64 DEFAULT 0,
    perp_total_volume_usd    Float64 DEFAULT 0,

    -- Bridge metrics
    bridge_transfers         UInt64 DEFAULT 0,
    bridge_volume_usd        Float64 DEFAULT 0,
    bridge_by_protocol       Map(String, UInt64),

    -- CEX metrics
    cex_deposits             UInt64 DEFAULT 0,
    cex_withdrawals          UInt64 DEFAULT 0,
    cex_by_exchange          Map(String, UInt64),

    -- Token metrics
    unique_tokens_tracked    UInt64 DEFAULT 0,
    token_transfers          UInt64 DEFAULT 0,

    -- NFT metrics
    nft_interactions         UInt64 DEFAULT 0,
    nft_mints                UInt64 DEFAULT 0,
    nft_trades               UInt64 DEFAULT 0,

    -- Whale metrics
    whale_alerts             UInt64 DEFAULT 0,
    whale_total_volume_usd   Float64 DEFAULT 0,

    -- Cross-chain metrics
    cross_chain_users        UInt64 DEFAULT 0,  -- Users active on 2+ VMs
    multi_wallet_users       UInt64 DEFAULT 0,  -- Users with 2+ wallets

    -- Staking metrics
    staking_deposits         UInt64 DEFAULT 0,
    staking_withdrawals      UInt64 DEFAULT 0,
    restaking_deposits       UInt64 DEFAULT 0,

    -- Governance metrics
    governance_votes         UInt64 DEFAULT 0,
    governance_proposals     UInt64 DEFAULT 0
)
ENGINE = SummingMergeTree()
PARTITION BY (project_id, toYYYYMM(date))
ORDER BY (project_id, date)
TTL date + INTERVAL 730 DAY
SETTINGS index_granularity = 8192;
"""


# ---------------------------------------------------------------------------
# ETL transformation functions
# ---------------------------------------------------------------------------

@dataclass
class Web3EventTransformer:
    """Transforms raw Bronze events into Silver-tier Web3 events."""

    @staticmethod
    def extract_vm(properties: dict) -> str:
        return properties.get("vm", "evm")

    @staticmethod
    def extract_chain_id(properties: dict) -> str:
        return str(properties.get("chainId", "1"))

    @staticmethod
    def extract_defi_category(properties: dict) -> Optional[str]:
        return properties.get("category") or properties.get("defiCategory")

    @staticmethod
    def extract_wallet_classification(properties: dict) -> Optional[str]:
        return properties.get("classification")

    @staticmethod
    def is_web3_event(event_type: str) -> bool:
        web3_types = {
            "wallet", "transaction", "token_balance", "nft_detection",
            "whale_alert", "portfolio_update", "defi_interaction",
            "bridge_transfer", "cex_transfer", "perpetual_trade",
            "options_trade", "governance_vote", "yield_harvest",
            "nft_trade", "staking_action", "insurance_action",
            "launchpad_action", "payment_stream",
        }
        return event_type in web3_types

    @staticmethod
    def transform(event: dict) -> Optional[dict]:
        """Transform a raw event into Silver-tier Web3 event format."""
        event_type = event.get("type", "")
        if not Web3EventTransformer.is_web3_event(event_type):
            return None

        props = event.get("properties", {})
        return {
            "event_id": event.get("id"),
            "event_type": event_type,
            "timestamp": event.get("timestamp"),
            "project_id": event.get("project_id", ""),
            "session_id": event.get("sessionId", ""),
            "anonymous_id": event.get("anonymousId", ""),
            "user_id": event.get("userId"),
            "vm": Web3EventTransformer.extract_vm(props),
            "chain_id": Web3EventTransformer.extract_chain_id(props),
            "wallet_address": props.get("address"),
            "wallet_type": props.get("walletType"),
            "wallet_classification": Web3EventTransformer.extract_wallet_classification(props),
            "wallet_action": props.get("action"),
            "tx_hash": props.get("txHash"),
            "tx_from": props.get("from"),
            "tx_to": props.get("to"),
            "tx_value": props.get("value"),
            "tx_status": props.get("status"),
            "tx_type": props.get("type"),
            "gas_used": props.get("gasUsed"),
            "gas_price": props.get("gasPrice"),
            "gas_cost_native": props.get("gasCostNative"),
            "protocol_name": props.get("protocol"),
            "defi_category": Web3EventTransformer.extract_defi_category(props),
            "defi_action": props.get("action"),
            "token_symbol": props.get("symbol"),
            "token_address": props.get("contractAddress"),
            "bridge_name": props.get("bridge"),
            "source_chain": str(props.get("sourceChain", "")),
            "dest_chain": str(props.get("destChain", "")),
            "perp_market": props.get("market"),
            "perp_side": props.get("side"),
            "perp_leverage": props.get("leverage"),
            "from_label": props.get("fromLabel"),
            "to_label": props.get("toLabel"),
            "whale_threshold": props.get("threshold"),
            "value_usd": props.get("valueUSD"),
        }
