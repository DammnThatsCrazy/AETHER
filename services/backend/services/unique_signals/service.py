"""
Aether — Unique Signal Service (Stubs)

All 5 unique signal computations are NOT_YET_IMPLEMENTED.

Each method raises NotImplementedError with the specific external credentials
required to activate it. This service is scaffolded so routes, docs, and
tests can be written before the credentials are available.
"""
from __future__ import annotations

from services.unique_signals.models import (
    CEXFundingBehavioralPredictionInput,
    CEXFundingBehavioralPredictionOutput,
    GitHubAbandonmentRiskInput,
    GitHubAbandonmentRiskOutput,
    PredictionMarketOnChainCorrelationInput,
    PredictionMarketOnChainCorrelationOutput,
    SocialWhaleCoordinationDetectionInput,
    SocialWhaleCoordinationDetectionOutput,
    UNIQUE_SIGNAL_DESCRIPTORS,
    UniqueSignalDescriptor,
    Web3SocialIdentityGraphInput,
    Web3SocialIdentityGraphOutput,
)
from shared.logger.logger import get_logger

logger = get_logger("aether.service.unique_signals")


class UniqueSignalService:

    async def prediction_market_onchain_correlation(
        self,
        inp: PredictionMarketOnChainCorrelationInput,
    ) -> PredictionMarketOnChainCorrelationOutput:
        # TODO: Requires POLYMARKET_API_KEY, KALSHI_API_KEY, DUNE_API_KEY
        raise NotImplementedError(
            "prediction_market_onchain_correlation requires: "
            "POLYMARKET_API_KEY, KALSHI_API_KEY, DUNE_API_KEY. "
            "See services/provider_catalog/catalog.py for source manifests."
        )

    async def web3_social_identity_graph(
        self,
        inp: Web3SocialIdentityGraphInput,
    ) -> Web3SocialIdentityGraphOutput:
        # TODO: Requires NEYNAR_API_KEY
        raise NotImplementedError(
            "web3_social_identity_graph requires: NEYNAR_API_KEY. "
            "See manifest_farcaster_neynar, manifest_lens_protocol."
        )

    async def cex_funding_behavioral_prediction(
        self,
        inp: CEXFundingBehavioralPredictionInput,
    ) -> CEXFundingBehavioralPredictionOutput:
        # TODO: Requires DUNE_API_KEY, COINGECKO_PRO_API_KEY
        raise NotImplementedError(
            "cex_funding_behavioral_prediction requires: "
            "DUNE_API_KEY, COINGECKO_PRO_API_KEY. "
            "Public Binance/OKX/Bybit endpoints available but Dune on-chain correlation requires Dune API."
        )

    async def github_abandonment_risk(
        self,
        inp: GitHubAbandonmentRiskInput,
    ) -> GitHubAbandonmentRiskOutput:
        # TODO: Requires GITHUB_OAUTH_APP_CLIENT_ID, GITHUB_OAUTH_APP_CLIENT_SECRET
        raise NotImplementedError(
            "github_abandonment_risk requires: "
            "GITHUB_OAUTH_APP_CLIENT_ID, GITHUB_OAUTH_APP_CLIENT_SECRET."
        )

    async def social_whale_coordination_detection(
        self,
        inp: SocialWhaleCoordinationDetectionInput,
    ) -> SocialWhaleCoordinationDetectionOutput:
        # TODO: Disabled pending compliance review for Twitter/Reddit/Telegram/Discord
        raise NotImplementedError(
            "social_whale_coordination_detection is DISABLED_COMPLIANCE_REVIEW. "
            "Social providers (Twitter/Reddit/Telegram/Discord) require compliance "
            "review before activation. Contact compliance@aether before enabling."
        )

    def list_signals(self) -> list[UniqueSignalDescriptor]:
        return UNIQUE_SIGNAL_DESCRIPTORS


unique_signal_service = UniqueSignalService()
