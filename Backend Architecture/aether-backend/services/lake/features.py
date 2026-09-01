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
    gold_market, gold_identity,
)
from services.ingestion.rights import authorize_derivation, rights_context_from_result
from shared.rights_authority.pep import rights_mode
from shared.rights_authority.contracts import lineage_hash

logger = get_logger("aether.lake.features")


def _source_receipts(records: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    envelopes: set[str] = set()
    grants: set[str] = set()
    for record in records:
        rights = record.get("rights") or {}
        if not isinstance(rights, dict):
            continue
        envelopes.update(rights.get("envelope_refs") or [])
        if rights.get("envelope_ref"):
            envelopes.add(str(rights["envelope_ref"]))
        grants.update(rights.get("source_grant_refs") or [])
        if rights.get("source_grant_ref"):
            grants.add(str(rights["source_grant_ref"]))
    return sorted(envelopes), sorted(grants)


async def _authorize_feature_materialization(
    tenant_id: Optional[str],
    records: list[dict[str, Any]],
    artifact_id: str,
) -> dict[str, Any]:
    """Authorize a Gold feature plus its cache write from Silver receipts."""
    if rights_mode() == "off":
        return {}
    if not tenant_id:
        raise ValueError("rights_feature_materialization_blocked: tenant_id required")
    envelope_refs, grant_refs = _source_receipts(records)
    if not envelope_refs:
        raise ValueError("rights_feature_materialization_blocked: source lineage missing")
    decision = await authorize_derivation(
        tenant_id,
        artifact={"kind": "gold_feature", "id": artifact_id, "tenant_id": tenant_id},
        input_envelope_refs=envelope_refs,
        source_grant_refs=grant_refs,
        transform="feature_extraction",
        evidence={"lineage": envelope_refs},
    )
    if not decision.proceed and rights_mode() == "enforce":
        raise ValueError(
            "rights_feature_materialization_blocked: "
            + ",".join(decision.reason_codes)
        )
    return rights_context_from_result(
        decision,
        extra={
            "source_grant_refs": grant_refs,
            "lineage_set_hash": lineage_hash(envelope_refs),
        },
    )


async def materialize_wallet_features(
    wallet_address: str,
    cache: Optional[CacheClient] = None,
    tenant_id: Optional[str] = None,
) -> dict:
    """
    Compute features for a wallet from Silver/Gold data.
    Writes to Gold tier and optionally to Redis for online serving.
    """
    features: dict[str, Any] = {
        "wallet_address": wallet_address,
        "materialized_at": utc_now().isoformat(),
    }

    # Gather from Silver tiers. This is a global feature job with no single
    # owning tenant, so it reads cross-tenant explicitly (tenant_id=None).
    read_tenant = tenant_id if tenant_id is not None else None
    onchain_records = await silver_onchain.get_entity(wallet_address, "wallet", tenant_id=read_tenant)
    market_records = await silver_market.get_entity(wallet_address, "wallet", tenant_id=read_tenant)
    social_records = await silver_social.get_entity(wallet_address, "wallet", tenant_id=read_tenant)
    identity_records = await silver_identity.get_entity(wallet_address, "wallet", tenant_id=read_tenant)
    source_records = onchain_records + market_records + social_records + identity_records
    rights = await _authorize_feature_materialization(
        tenant_id, source_records, f"wallet:{wallet_address}",
    )

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
        tenant_id=tenant_id or "",
        rights=rights,
    )

    # Online serving via Redis
    if cache:
        cache_key = f"aether:features:wallet:{tenant_id or 'unscoped'}:{wallet_address}"
        await cache.set_json(cache_key, {"features": features, "rights": rights}, ttl=TTL.LONG)

    metrics.increment("features_materialized", labels={"entity_type": "wallet"})
    return features


async def materialize_protocol_features(
    protocol_id: str,
    cache: Optional[CacheClient] = None,
    tenant_id: Optional[str] = None,
) -> dict:
    """Compute features for a protocol from Silver/Gold data."""
    features: dict[str, Any] = {
        "protocol_id": protocol_id,
        "materialized_at": utc_now().isoformat(),
    }

    # Global protocol feature job — explicit cross-tenant read.
    market_records = await silver_market.get_entity(protocol_id, "protocol", tenant_id=tenant_id)
    features["data_points"] = len(market_records)
    rights = await _authorize_feature_materialization(
        tenant_id, market_records, f"protocol:{protocol_id}",
    )

    await gold_market.materialize(
        metric_name="protocol_features",
        entity_id=protocol_id,
        entity_type="protocol",
        value=features,
        source_tag="feature_materialization",
        tenant_id=tenant_id or "",
        rights=rights,
    )

    if cache:
        await cache.set_json(
            f"aether:features:protocol:{tenant_id or 'unscoped'}:{protocol_id}",
            {"features": features, "rights": rights}, ttl=TTL.LONG,
        )

    metrics.increment("features_materialized", labels={"entity_type": "protocol"})
    return features
