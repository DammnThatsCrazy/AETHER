"""
Aether — Unique Signal Feature Models

5 cross-source signal combinations that require Olympus provider data.

NOT_YET_IMPLEMENTED: All signals are scaffolded. Full implementation
requires the listed external credentials and data source activation.

Source manifest IDs reference entries in services/provider_catalog/catalog.py.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class UniqueSignalStatus(str, Enum):
    NOT_YET_IMPLEMENTED = "not_yet_implemented"
    IN_DEVELOPMENT = "in_development"
    CREDENTIAL_GATED = "credential_gated"
    STAGING_VALIDATION = "staging_validation"
    PRODUCTION = "production"
    DISABLED_COMPLIANCE_REVIEW = "disabled_compliance_review"


# ── Signal 1: Prediction Market On-Chain Correlation ──────────────────────────

class PredictionMarketOnChainCorrelationInput(BaseModel):
    wallet_address: str
    event_id: Optional[str] = None
    chain_id: str = "ethereum"
    lookback_hours: int = 24


class PredictionMarketOnChainCorrelationOutput(BaseModel):
    wallet_address: str
    event_probability_shift: float
    capital_flow_response: float
    correlation_confidence: float
    event_id: Optional[str] = None
    source_manifests_used: List[str] = []
    model_training_eligible: bool = True
    computed_at: str = ""


# ── Signal 2: Web3 Social Identity Graph ──────────────────────────────────────

class Web3SocialIdentityGraphInput(BaseModel):
    wallet_address: str
    include_governance: bool = True
    include_social_edges: bool = True


class Web3SocialIdentityGraphOutput(BaseModel):
    wallet_address: str
    wallet_social_edge_count: int
    governance_participation_edge_count: int
    social_identity_confidence: float
    farcaster_handle: Optional[str] = None
    lens_handle: Optional[str] = None
    ens_name: Optional[str] = None
    source_manifests_used: List[str] = []
    model_training_eligible: bool = True
    computed_at: str = ""


# ── Signal 3: CEX Funding Behavioral Prediction ───────────────────────────────

class CEXFundingBehavioralPredictionInput(BaseModel):
    asset: str
    chain_id: str = "ethereum"
    wallet_address: Optional[str] = None
    lookback_hours: int = 8


class CEXFundingBehavioralPredictionOutput(BaseModel):
    asset: str
    funding_extreme_signal: float
    liquidation_risk_context: float
    open_interest_delta: float
    funding_rate_percentile: float
    source_manifests_used: List[str] = []
    model_training_eligible: bool = True
    computed_at: str = ""


# ── Signal 4: GitHub Developer Abandonment Risk ───────────────────────────────

class GitHubAbandonmentRiskInput(BaseModel):
    protocol_name: str
    github_repo: Optional[str] = None
    chain_id: str = "ethereum"
    lookback_days: int = 30


class GitHubAbandonmentRiskOutput(BaseModel):
    protocol_name: str
    developer_activity_score: float
    protocol_abandonment_risk: float
    commit_velocity_delta: float
    active_contributor_count: int
    tvl_correlation: float
    source_manifests_used: List[str] = []
    model_training_eligible: bool = True
    computed_at: str = ""


# ── Signal 5: Social + Whale Coordination Detection ──────────────────────────

class SocialWhaleCoordinationDetectionInput(BaseModel):
    asset: str
    wallet_address: Optional[str] = None
    lookback_hours: int = 4


class SocialWhaleCoordinationDetectionOutput(BaseModel):
    asset: str
    sentiment_spike: float
    whale_cluster_movement: float
    coordination_confidence: float
    signal_sources: List[str] = []
    source_manifests_used: List[str] = []
    model_training_eligible: bool = False
    computed_at: str = ""


# ── Generic signal registry ───────────────────────────────────────────────────

class UniqueSignalDescriptor(BaseModel):
    signal_id: str
    signal_name: str
    status: UniqueSignalStatus
    required_providers: List[str]
    required_credentials: List[str]
    output_schema: Dict[str, Any]
    model_training_eligible: bool
    source_manifest_ids: List[str]
    blocking_reason: Optional[str] = None


UNIQUE_SIGNAL_DESCRIPTORS: List[UniqueSignalDescriptor] = [
    UniqueSignalDescriptor(
        signal_id="prediction_market_onchain_correlation",
        signal_name="Prediction Market On-Chain Correlation",
        status=UniqueSignalStatus.NOT_YET_IMPLEMENTED,
        required_providers=["polymarket_gamma", "kalshi", "dune_api", "defi_llama"],
        required_credentials=["POLYMARKET_API_KEY", "KALSHI_API_KEY", "DUNE_API_KEY"],
        output_schema={
            "event_probability_shift": "float",
            "capital_flow_response": "float",
            "correlation_confidence": "float",
        },
        model_training_eligible=True,
        source_manifest_ids=[
            "manifest_polymarket_gamma", "manifest_kalshi",
            "manifest_dune_api", "manifest_defi_llama",
        ],
        blocking_reason="Requires Polymarket + Kalshi API credentials",
    ),
    UniqueSignalDescriptor(
        signal_id="web3_social_identity_graph",
        signal_name="Web3 Social Identity Graph",
        status=UniqueSignalStatus.NOT_YET_IMPLEMENTED,
        required_providers=["farcaster_neynar", "lens_protocol", "ens_public", "snapshot"],
        required_credentials=["NEYNAR_API_KEY"],
        output_schema={
            "wallet_social_edge_count": "int",
            "governance_participation_edge_count": "int",
            "social_identity_confidence": "float",
        },
        model_training_eligible=True,
        source_manifest_ids=[
            "manifest_farcaster_neynar", "manifest_lens_protocol",
            "manifest_ens_public", "manifest_snapshot",
        ],
        blocking_reason="Requires Neynar API key",
    ),
    UniqueSignalDescriptor(
        signal_id="cex_funding_behavioral_prediction",
        signal_name="CEX Funding Behavioral Prediction",
        status=UniqueSignalStatus.NOT_YET_IMPLEMENTED,
        required_providers=["binance_public", "okx", "bybit", "coingecko", "dune_api"],
        required_credentials=["DUNE_API_KEY", "COINGECKO_PRO_API_KEY"],
        output_schema={
            "funding_extreme_signal": "float",
            "liquidation_risk_context": "float",
            "open_interest_delta": "float",
        },
        model_training_eligible=True,
        source_manifest_ids=[
            "manifest_binance_public", "manifest_okx", "manifest_bybit",
            "manifest_coingecko", "manifest_dune_api",
        ],
        blocking_reason="Requires Dune API key + CoinGecko Pro",
    ),
    UniqueSignalDescriptor(
        signal_id="github_abandonment_risk",
        signal_name="GitHub Developer Abandonment Risk",
        status=UniqueSignalStatus.NOT_YET_IMPLEMENTED,
        required_providers=["github_api", "defi_llama", "dune_api"],
        required_credentials=["GITHUB_OAUTH_APP_CLIENT_ID", "GITHUB_OAUTH_APP_CLIENT_SECRET"],
        output_schema={
            "developer_activity_score": "float",
            "protocol_abandonment_risk": "float",
            "commit_velocity_delta": "float",
        },
        model_training_eligible=True,
        source_manifest_ids=["manifest_github_api", "manifest_defi_llama", "manifest_dune_api"],
        blocking_reason="Requires GitHub OAuth app registration",
    ),
    UniqueSignalDescriptor(
        signal_id="social_whale_coordination_detection",
        signal_name="Social + Whale Coordination Detection",
        status=UniqueSignalStatus.DISABLED_COMPLIANCE_REVIEW,
        required_providers=["twitter_x", "reddit", "telegram_bot", "discord_bot", "dune_api", "covalent_goldrush"],
        required_credentials=[
            "TWITTER_BEARER_TOKEN", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET",
            "TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN", "COVALENT_API_KEY",
        ],
        output_schema={
            "sentiment_spike": "float",
            "whale_cluster_movement": "float",
            "coordination_confidence": "float",
        },
        model_training_eligible=False,
        source_manifest_ids=[
            "manifest_twitter_x", "manifest_reddit",
            "manifest_telegram_bot", "manifest_discord_bot",
            "manifest_dune_api", "manifest_covalent_goldrush",
        ],
        blocking_reason="Social providers disabled pending compliance review",
    ),
]
