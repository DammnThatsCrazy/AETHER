"""Card-linked cluster cohorts — review/intelligence outputs only.

Clusters group entities/wallets by observed card-linked behavior. They
feed Cluster360 and review queues; they NEVER drive enforcement actions
(no access denial, reward denial, fraud finality, pricing, or campaign
suppression). Suspicious cohorts are flagged for human review only.
"""

from __future__ import annotations

from typing import Any

from shared.logger.logger import get_logger

from services.card_linked_payments.gold import cluster_features

logger = get_logger("aether.card_linked.clusters")

_PROGRAM_CLUSTERS = ("redotpay", "kast", "gnosis", "metamask")
_ASSET_TOPUP_CLUSTERS = ("USDC", "USDT")
_HIGH_VOLUME_THRESHOLD_USD = 10_000.0
_REPEAT_SPEND_THRESHOLD = 3


def _cluster(cluster_id: str, label: str, kind: str, members: list[str],
             advisory: str | None = None) -> dict[str, Any]:
    return {
        "cluster_id": cluster_id,
        "label": label,
        "kind": kind,
        "member_count": len(members),
        "members": sorted(members),
        "enforcement": "never",  # intelligence output, not an action
        **({"advisory": advisory} if advisory else {}),
    }


async def build_card_linked_clusters(tenant_id: str) -> list[dict[str, Any]]:
    """Derive the V1 cohort set from per-entity gold features."""
    features = await cluster_features(tenant_id)
    clusters: list[dict[str, Any]] = []

    for program in _PROGRAM_CLUSTERS:
        members = [f["entity_id"] for f in features if program in f["programs"]]
        if members:
            clusters.append(_cluster(
                f"card_program:{program}", f"{program} card users",
                "card_program_users", members,
            ))

    for asset in _ASSET_TOPUP_CLUSTERS:
        members = [f["entity_id"] for f in features
                   if asset in f["assets"] and f["topup_count"] > 0]
        if members:
            clusters.append(_cluster(
                f"card_topup_asset:{asset.lower()}", f"{asset} card top-up users",
                "card_topup_asset_users", members,
            ))

    base_members = [f["entity_id"] for f in features
                    if "base" in [str(c).lower() for c in f["chains"]] and f["topup_count"] > 0]
    if base_members:
        clusters.append(_cluster(
            "card_funding_chain:base", "Base card-funding users",
            "card_funding_chain_users", base_members,
        ))

    def _volume(f: dict) -> float:
        try:
            return float(f["topup_volume_usd"]) + float(f["spend_volume_usd"])
        except (TypeError, ValueError):
            return 0.0

    high_volume = [f["entity_id"] for f in features if _volume(f) >= _HIGH_VOLUME_THRESHOLD_USD]
    if high_volume:
        clusters.append(_cluster(
            "card_high_volume", "High-volume card-linked users",
            "card_high_volume_users", high_volume,
        ))

    repeat_spend = [f["entity_id"] for f in features
                    if f["spend_count"] >= _REPEAT_SPEND_THRESHOLD]
    if repeat_spend:
        clusters.append(_cluster(
            "card_repeat_spend", "Repeat card-spend users",
            "card_repeat_spend_users", repeat_spend,
        ))

    campaign_converted = [f["entity_id"] for f in features if f["campaign_converted"]]
    if campaign_converted:
        clusters.append(_cluster(
            "card_campaign_converted", "Campaign-converted card users",
            "card_campaign_converted_users", campaign_converted,
        ))

    issuers = sorted({issuer for f in features for issuer in f["issuers"]})
    for issuer in issuers:
        members = [f["entity_id"] for f in features if issuer in f["issuers"]]
        clusters.append(_cluster(
            f"card_issuer_exposure:{issuer}", f"{issuer} issuer exposure",
            "issuer_exposure", members,
        ))

    refund_loops = [f["entity_id"] for f in features if f["refund_loop_suspect"]]
    if refund_loops:
        clusters.append(_cluster(
            "card_refund_loop_suspect", "Suspicious top-up/refund loop users",
            "suspicious_refund_loop", refund_loops,
            advisory="Review-only signal: stage for human investigation; never auto-deny.",
        ))

    agent_influenced = [f["entity_id"] for f in features if f["agent_influenced"]]
    if agent_influenced:
        clusters.append(_cluster(
            "card_agent_influenced", "Agent-influenced card activity",
            "agent_influenced_card_activity", agent_influenced,
        ))

    return clusters
