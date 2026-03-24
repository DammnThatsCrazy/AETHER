"""
Aether — Feature Materialization Jobs

Reads from Silver/Gold lake tiers and materializes features for:
- ML training (offline features → PostgreSQL/S3)
- Online serving (hot features → Redis)
- Graph mutations (entity relationships → Neptune)

Runs as scheduled jobs or on-demand via API.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.cache.cache import CacheClient, TTL
from shared.logger.logger import get_logger, metrics
from shared.common.common import utc_now
from repositories.lake import (
    silver_market, silver_onchain, silver_social, silver_identity,
    gold_market, gold_onchain, gold_identity,
)

logger = get_logger("aether.lake.features")


async def materialize_wallet_features(
    wallet_address: str,
    cache: Optional[CacheClient] = None,
) -> dict:
    """
    Compute features for a wallet from Silver/Gold data.
    Writes to Gold tier and optionally to Redis for online serving.
    """
    features: dict[str, Any] = {
        "wallet_address": wallet_address,
        "materialized_at": utc_now().isoformat(),
    }

    # Gather from Silver tiers
    onchain_records = await silver_onchain.get_entity(wallet_address, "wallet")
    market_records = await silver_market.get_entity(wallet_address, "wallet")
    social_records = await silver_social.get_entity(wallet_address, "wallet")
    identity_records = await silver_identity.get_entity(wallet_address, "wallet")

    # Transaction features
    features["tx_count"] = len(onchain_records)
    features["unique_protocols"] = len({r.get("protocol", "") for r in onchain_records if r.get("protocol")})
    features["has_social_link"] = len(social_records) > 0
    features["identity_sources"] = len(identity_records)

    # Persist to Gold
    await gold_identity.materialize(
        metric_name="wallet_features",
        entity_id=wallet_address,
        entity_type="wallet",
        value=features,
        source_tag="feature_materialization",
    )

    # Online serving via Redis
    if cache:
        cache_key = f"aether:features:wallet:{wallet_address}"
        await cache.set_json(cache_key, features, ttl=TTL.LONG)

    metrics.increment("features_materialized", labels={"entity_type": "wallet"})
    return features


async def materialize_protocol_features(
    protocol_id: str,
    cache: Optional[CacheClient] = None,
) -> dict:
    """Compute features for a protocol from Silver/Gold data."""
    features: dict[str, Any] = {
        "protocol_id": protocol_id,
        "materialized_at": utc_now().isoformat(),
    }

    market_records = await silver_market.get_entity(protocol_id, "protocol")
    features["data_points"] = len(market_records)

    await gold_market.materialize(
        metric_name="protocol_features",
        entity_id=protocol_id,
        entity_type="protocol",
        value=features,
        source_tag="feature_materialization",
    )

    if cache:
        await cache.set_json(f"aether:features:protocol:{protocol_id}", features, ttl=TTL.LONG)

    metrics.increment("features_materialized", labels={"entity_type": "protocol"})
    return features
