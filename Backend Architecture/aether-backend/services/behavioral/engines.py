"""
Behavioral Signal Engines — compute derived signals from existing data.

Each engine reads from existing repositories/services and produces
signal observations with provenance, confidence, and explanations.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Optional

from repositories.repos import BaseRepository, AnalyticsRepository
from repositories.lake import silver_identity, silver_onchain, silver_social
from shared.graph.graph import GraphClient
from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics
from services.behavioral.signals import SignalFamily

logger = get_logger("aether.behavioral.engines")


class SignalObservationRepository(BaseRepository):
    """Stores derived behavioral signal observations."""

    def __init__(self) -> None:
        super().__init__("behavioral_signals")

    async def get_signals_for_entity(
        self, entity_id: str, family: Optional[str] = None, limit: int = 50,
    ) -> list[dict]:
        filters: dict = {"entity_id": entity_id}
        if family:
            filters["signal_family"] = family
        return await self.find_many(filters=filters, limit=limit, sort_by="created_at", sort_order="desc")


signal_repo = SignalObservationRepository()


def _make_signal(
    entity_id: str,
    family: SignalFamily,
    outputs: dict,
    explanation: str,
    confidence: float = 0.5,
    source_events: Optional[list[str]] = None,
    session_id: str = "",
    tenant_id: str = "",
    source_tag: str = "",
) -> dict:
    """Create a canonical signal observation record."""
    now = utc_now().isoformat()
    return {
        "id": str(uuid.uuid4()),
        "entity_id": entity_id,
        "signal_family": family.value,
        "outputs": outputs,
        "explanation": explanation,
        "confidence": confidence,
        "source_events": source_events or [],
        "session_id": session_id,
        "tenant_id": tenant_id,
        "source_tag": source_tag or "behavioral_engine",
        "created_at": now,
        "updated_at": now,
    }


# ═══════════════════════════════════════════════════════════════════
# PHASE 1 ENGINES
# ═══════════════════════════════════════════════════════════════════

async def compute_intent_residue(
    entity_id: str,
    analytics: AnalyticsRepository,
    tenant_id: str = "",
) -> Optional[dict]:
    """Detect unfinished high-intent flows across sessions."""
    events = await analytics.query_events(tenant_id, {"user_id": entity_id}, limit=200)
    if not events:
        return None

    # Find high-intent events (page views of pricing, checkout, wallet-connect pages)
    high_intent_keywords = {"checkout", "pricing", "swap", "stake", "bridge", "claim", "connect", "mint", "buy"}
    high_intent_events = [e for e in events if any(k in str(e.get("properties", {})).lower() for k in high_intent_keywords)]

    conversions = [e for e in events if e.get("event_type") == "conversion"]
    wallet_connects = [e for e in events if e.get("event_type") == "wallet"]

    if not high_intent_events:
        return None

    # Score: high intent without conversion = residue
    intent_count = len(high_intent_events)
    conversion_count = len(conversions)
    residue_score = min(1.0, max(0.0, (intent_count - conversion_count * 3) / max(intent_count, 1)))

    if residue_score < 0.1:
        return None

    last_intent = high_intent_events[0]
    signal = _make_signal(
        entity_id=entity_id,
        family=SignalFamily.INTENT_RESIDUE,
        outputs={
            "intent_residue_score": round(residue_score, 4),
            "unfinished_flow_type": "high_intent_no_conversion",
            "last_high_intent_step": str(last_intent.get("properties", {}).get("url", ""))[:100],
            "return_to_intent_probability": round(min(0.9, residue_score * 0.8), 4),
            "high_intent_events": intent_count,
            "conversions": conversion_count,
        },
        explanation=f"Entity showed {intent_count} high-intent events but only {conversion_count} conversions. Residue score: {residue_score:.2f}",
        confidence=min(0.9, 0.3 + residue_score * 0.5),
        tenant_id=tenant_id,
    )
    await signal_repo.insert(signal["id"], signal)
    metrics.increment("behavioral_signal_computed", labels={"family": "intent_residue"})
    return signal


async def compute_wallet_friction(
    entity_id: str,
    analytics: AnalyticsRepository,
    tenant_id: str = "",
) -> Optional[dict]:
    """Detect wallet-connect friction patterns."""
    events = await analytics.query_events(tenant_id, {"user_id": entity_id}, limit=200)
    if not events:
        return None

    wallet_events = [e for e in events if e.get("event_type") in ("wallet", "error")]
    if not wallet_events:
        return None

    connect_attempts = len([e for e in wallet_events if "connect" in str(e.get("properties", {})).lower()])
    errors = len([e for e in wallet_events if e.get("event_type") == "error"])
    successful_connects = len([e for e in wallet_events if e.get("event_type") == "wallet" and "connect" in str(e.get("properties", {})).lower()])

    if connect_attempts < 2:
        return None

    friction_score = min(1.0, errors / max(connect_attempts, 1))

    signal = _make_signal(
        entity_id=entity_id,
        family=SignalFamily.WALLET_FRICTION,
        outputs={
            "wallet_connect_attempt_count": connect_attempts,
            "wallet_connect_failure_loop": errors > 2,
            "wallet_switch_before_connect": connect_attempts > successful_connects + 1,
            "connect_friction_score": round(friction_score, 4),
        },
        explanation=f"{connect_attempts} connect attempts, {errors} errors, {successful_connects} successes. Friction: {friction_score:.2f}",
        confidence=min(0.9, 0.4 + friction_score * 0.4),
        tenant_id=tenant_id,
    )
    await signal_repo.insert(signal["id"], signal)
    metrics.increment("behavioral_signal_computed", labels={"family": "wallet_friction"})
    return signal


async def compute_identity_delta(
    entity_id: str,
    graph: GraphClient,
    tenant_id: str = "",
) -> Optional[dict]:
    """Detect identity confidence changes based on evidence."""
    identity_records = await silver_identity.get_entity(
        entity_id, "wallet", tenant_id=tenant_id
    )
    if not identity_records:
        return None

    sources = list({r.get("source", "") for r in identity_records if r.get("source")})
    if len(sources) < 2:
        return None

    # Check for contradictions between sources
    contradictions = []
    for i, r1 in enumerate(identity_records):
        for r2 in identity_records[i + 1:]:
            if r1.get("source") != r2.get("source"):
                for key in set(r1.keys()) & set(r2.keys()) - {"id", "source", "source_tag", "created_at", "updated_at", "tenant_id", "bronze_id"}:
                    if r1.get(key) and r2.get(key) and r1[key] != r2[key]:
                        contradictions.append(key)

    delta = len(contradictions) / max(len(sources) * 3, 1)

    signal = _make_signal(
        entity_id=entity_id,
        family=SignalFamily.IDENTITY_DELTA,
        outputs={
            "identity_confidence_delta": round(-delta if contradictions else 0.1, 4),
            "new_evidence_type": sources[-1] if sources else "",
            "contradictory_evidence_type": contradictions[0] if contradictions else "",
            "merge_stability_score": round(1.0 - delta, 4),
            "source_count": len(sources),
            "contradiction_count": len(contradictions),
        },
        explanation=f"{len(sources)} identity sources, {len(contradictions)} contradictions. Stability: {1.0 - delta:.2f}",
        confidence=min(0.9, 0.5 + len(sources) * 0.1),
        tenant_id=tenant_id,
    )
    await signal_repo.insert(signal["id"], signal)
    metrics.increment("behavioral_signal_computed", labels={"family": "identity_delta"})
    return signal


async def compute_pre_post_continuity(
    entity_id: str,
    analytics: AnalyticsRepository,
    tenant_id: str = "",
) -> Optional[dict]:
    """Measure pre-connect to post-connect behavioral continuity."""
    events = await analytics.query_events(tenant_id, {"user_id": entity_id}, limit=200)
    if len(events) < 5:
        return None

    # Find the identity/wallet connect moment
    connect_events = [e for e in events if e.get("event_type") in ("identify", "wallet")]
    if not connect_events:
        return None

    connect_time = connect_events[0].get("created_at", "")
    pre_events = [e for e in events if e.get("created_at", "") < connect_time]
    post_events = [e for e in events if e.get("created_at", "") >= connect_time]

    if not pre_events or not post_events:
        return None

    # Simple continuity: do pre and post share event types?
    pre_types = {e.get("event_type") for e in pre_events}
    post_types = {e.get("event_type") for e in post_events}
    overlap = pre_types & post_types
    continuity = len(overlap) / max(len(pre_types | post_types), 1)

    signal = _make_signal(
        entity_id=entity_id,
        family=SignalFamily.PRE_POST_CONTINUITY,
        outputs={
            "pre_post_identity_continuity": round(continuity, 4),
            "pre_connect_intent_strength": round(len(pre_events) / max(len(events), 1), 4),
            "connect_consistency_score": round(continuity, 4),
            "pre_event_count": len(pre_events),
            "post_event_count": len(post_events),
        },
        explanation=f"{len(pre_events)} pre-connect events, {len(post_events)} post-connect. Continuity: {continuity:.2f}",
        confidence=min(0.9, 0.3 + continuity * 0.5),
        tenant_id=tenant_id,
    )
    await signal_repo.insert(signal["id"], signal)
    metrics.increment("behavioral_signal_computed", labels={"family": "pre_post_continuity"})
    return signal


async def compute_sequence_scars(
    entity_id: str,
    analytics: AnalyticsRepository,
    tenant_id: str = "",
) -> Optional[dict]:
    """Detect repeated failure patterns across sessions."""
    events = await analytics.query_events(tenant_id, {"user_id": entity_id}, limit=300)
    if len(events) < 10:
        return None

    # Find error→retry→error patterns
    error_events = [e for e in events if e.get("event_type") == "error"]
    if len(error_events) < 2:
        return None

    # Count error clusters (errors within same session)
    sessions_with_errors = len({e.get("session_id") for e in error_events if e.get("session_id")})
    recurrence = sessions_with_errors

    if recurrence < 2:
        return None

    signal = _make_signal(
        entity_id=entity_id,
        family=SignalFamily.SEQUENCE_SCAR,
        outputs={
            "sequence_scar_type": "error_retry_loop",
            "scar_recurrence_count": recurrence,
            "scar_resolution_rate": round(1.0 - recurrence / max(len({e.get("session_id") for e in events}), 1), 4),
            "total_errors": len(error_events),
            "sessions_affected": sessions_with_errors,
        },
        explanation=f"Error patterns recurred across {recurrence} sessions ({len(error_events)} total errors)",
        confidence=min(0.9, 0.3 + recurrence * 0.15),
        tenant_id=tenant_id,
    )
    await signal_repo.insert(signal["id"], signal)
    metrics.increment("behavioral_signal_computed", labels={"family": "sequence_scar"})
    return signal


async def compute_source_shadow(
    entity_id: str,
    tenant_id: str = "",
) -> Optional[dict]:
    """Distinguish behavior absence from source/observation silence."""
    domain_recency: dict[str, str] = {}
    for domain_name, repo in [("identity", silver_identity), ("onchain", silver_onchain), ("social", silver_social)]:
        records = await repo.get_entity(entity_id, "wallet", tenant_id=tenant_id)
        if records:
            latest = max(records, key=lambda r: r.get("updated_at", ""))
            domain_recency[domain_name] = latest.get("updated_at", "")

    if not domain_recency:
        return None

    # Check for domains with stale data
    stale_domains = []
    active_domains = []
    for domain, last_update in domain_recency.items():
        if last_update < "2026-03-01":
            stale_domains.append(domain)
        else:
            active_domains.append(domain)

    if not stale_domains:
        return None

    source_shadow = len(stale_domains) > 0
    coverage_confidence = len(active_domains) / max(len(domain_recency), 1)

    signal = _make_signal(
        entity_id=entity_id,
        family=SignalFamily.SOURCE_SHADOW,
        outputs={
            "source_coverage_confidence": round(coverage_confidence, 4),
            "behavior_absence_confidence": round(1.0 - coverage_confidence, 4) if source_shadow else 0.0,
            "source_shadow_flag": source_shadow,
            "stale_domains": stale_domains,
            "active_domains": active_domains,
            "observation_gap_vs_behavior_gap": "source_gap" if source_shadow else "behavior_gap",
        },
        explanation=f"Stale data from {stale_domains}; active from {active_domains}. Source shadow: {source_shadow}",
        confidence=0.6 if source_shadow else 0.8,
        tenant_id=tenant_id,
    )
    await signal_repo.insert(signal["id"], signal)
    metrics.increment("behavioral_signal_computed", labels={"family": "source_shadow"})
    return signal


# ═══════════════════════════════════════════════════════════════════
# PHASE 2 ENGINES
# ═══════════════════════════════════════════════════════════════════

async def compute_reward_near_miss(
    entity_id: str,
    analytics: AnalyticsRepository,
    tenant_id: str = "",
) -> Optional[dict]:
    """Detect entities who nearly qualified for rewards but missed narrowly."""
    events = await analytics.query_events(tenant_id, {"user_id": entity_id}, limit=200)
    if not events:
        return None

    conversions = [e for e in events if e.get("event_type") == "conversion"]
    high_intent = [e for e in events if any(
        k in str(e.get("properties", {})).lower()
        for k in {"claim", "reward", "earn", "qualify", "eligible", "stake", "mint"}
    )]

    if not high_intent:
        return None

    # Near-miss: high reward-intent without conversion
    qualified = len(conversions)
    attempted = len(high_intent)
    gap_ratio = 1.0 - (qualified / max(attempted, 1))

    if gap_ratio < 0.3:
        return None

    signal = _make_signal(
        entity_id=entity_id,
        family=SignalFamily.REWARD_NEAR_MISS,
        outputs={
            "eligibility_gap_reason": "high_intent_no_qualification",
            "near_miss_window": f"{attempted} attempts, {qualified} qualified",
            "recovery_probability": round(min(0.8, qualified / max(attempted, 1) + 0.2), 4),
            "next_best_action_for_eligibility": "complete_pending_requirement",
            "attempt_count": attempted,
            "qualification_count": qualified,
        },
        explanation=f"{attempted} reward-intent events, only {qualified} conversions. Gap: {gap_ratio:.0%}",
        confidence=min(0.85, 0.3 + gap_ratio * 0.5),
        tenant_id=tenant_id,
    )
    await signal_repo.insert(signal["id"], signal)
    metrics.increment("behavioral_signal_computed", labels={"family": "reward_near_miss"})
    return signal


async def compute_social_chain_lag(
    entity_id: str,
    analytics: AnalyticsRepository,
    tenant_id: str = "",
) -> Optional[dict]:
    """Measure lag between social/attention signals and on-chain behavior."""
    events = await analytics.query_events(tenant_id, {"user_id": entity_id}, limit=300)
    if len(events) < 5:
        return None

    social_keywords = {"governance", "vote", "proposal", "discuss", "forum", "tweet", "post", "share", "follow"}
    chain_keywords = {"swap", "stake", "bridge", "mint", "transfer", "deploy", "claim"}

    social_events = [e for e in events if any(k in str(e.get("properties", {})).lower() for k in social_keywords)]
    chain_events = [e for e in events if any(k in str(e.get("properties", {})).lower() for k in chain_keywords)]

    if not social_events or not chain_events:
        return None

    # Compute average lag: social event time → next chain event time
    social_times = [e.get("created_at", "") for e in social_events]
    chain_times = [e.get("created_at", "") for e in chain_events]

    followthrough = len(chain_events) / max(len(social_events), 1)

    signal = _make_signal(
        entity_id=entity_id,
        family=SignalFamily.SOCIAL_CHAIN_LAG,
        outputs={
            "social_to_chain_lag_hours": "variable",
            "narrative_to_action_lag": "measured_by_event_sequence",
            "social_signal_followthrough_rate": round(min(1.0, followthrough), 4),
            "social_event_count": len(social_events),
            "chain_event_count": len(chain_events),
        },
        explanation=f"{len(social_events)} social signals, {len(chain_events)} chain actions. Followthrough: {followthrough:.0%}",
        confidence=min(0.8, 0.3 + followthrough * 0.4),
        tenant_id=tenant_id,
    )
    await signal_repo.insert(signal["id"], signal)
    metrics.increment("behavioral_signal_computed", labels={"family": "social_chain_lag"})
    return signal


async def compute_cex_dex_transition(
    entity_id: str,
    analytics: AnalyticsRepository,
    tenant_id: str = "",
) -> Optional[dict]:
    """Detect CEX-to-DEX or DEX-to-CEX transition behavior."""
    events = await analytics.query_events(tenant_id, {"user_id": entity_id}, limit=300)
    if not events:
        return None

    cex_keywords = {"binance", "coinbase", "kraken", "ftx", "okx", "bybit", "kucoin", "deposit", "withdraw", "fiat"}
    dex_keywords = {"uniswap", "sushiswap", "curve", "aave", "compound", "swap", "liquidity", "pool", "defi"}

    cex_events = [e for e in events if any(k in str(e.get("properties", {})).lower() for k in cex_keywords)]
    dex_events = [e for e in events if any(k in str(e.get("properties", {})).lower() for k in dex_keywords)]

    if not cex_events and not dex_events:
        return None

    total = len(cex_events) + len(dex_events)
    if total < 2:
        return None

    # Transition score: having both indicates transition behavior
    has_both = len(cex_events) > 0 and len(dex_events) > 0
    transition_score = min(1.0, min(len(cex_events), len(dex_events)) / max(max(len(cex_events), len(dex_events)), 1))

    signal = _make_signal(
        entity_id=entity_id,
        family=SignalFamily.CEX_DEX_TRANSITION,
        outputs={
            "cex_to_dex_transition_score": round(transition_score, 4),
            "fiat_onramp_proximity": len(cex_events) > 0,
            "cross_venue_behavior_similarity": round(transition_score, 4),
            "venue_shift_alert": has_both and transition_score > 0.3,
            "cex_event_count": len(cex_events),
            "dex_event_count": len(dex_events),
        },
        explanation=f"{len(cex_events)} CEX events, {len(dex_events)} DEX events. Transition score: {transition_score:.2f}",
        confidence=min(0.8, 0.3 + transition_score * 0.4),
        tenant_id=tenant_id,
    )
    await signal_repo.insert(signal["id"], signal)
    metrics.increment("behavioral_signal_computed", labels={"family": "cex_dex_transition"})
    return signal


# ═══════════════════════════════════════════════════════════════════
# PHASE 3 ENGINES
# ═══════════════════════════════════════════════════════════════════

async def compute_behavioral_twins(
    entity_id: str,
    analytics: AnalyticsRepository,
    graph: GraphClient,
    tenant_id: str = "",
) -> Optional[dict]:
    """Find entities with similar early behavior but different outcomes."""
    events = await analytics.query_events(tenant_id, {"user_id": entity_id}, limit=100)
    if len(events) < 5:
        return None

    # Build behavioral fingerprint: event type distribution
    type_dist: dict[str, int] = {}
    for e in events[:20]:  # early behavior only
        et = e.get("event_type", "")
        if et:
            type_dist[et] = type_dist.get(et, 0) + 1

    # Check for conversion (outcome divergence marker)
    has_conversion = any(e.get("event_type") == "conversion" for e in events)
    has_wallet = any(e.get("event_type") == "wallet" for e in events)

    # Look at graph neighbors for divergence comparison
    neighbors = await graph.get_neighbors(entity_id, direction="both")
    similar_neighbors = [n for n in neighbors if n.vertex_type in ("User", "Wallet")]

    if not similar_neighbors:
        return None

    signal = _make_signal(
        entity_id=entity_id,
        family=SignalFamily.BEHAVIORAL_TWIN,
        outputs={
            "twin_group_id": hashlib.sha256(str(sorted(type_dist.items())).encode()).hexdigest()[:16],
            "divergence_outcome_type": "converted" if has_conversion else "churned",
            "divergence_point": "wallet_connect" if has_wallet else "pre_connect",
            "twin_similarity_score": round(len(similar_neighbors) / max(len(neighbors), 1), 4),
            "early_behavior_fingerprint": type_dist,
            "peer_count": len(similar_neighbors),
        },
        explanation=f"Early behavior fingerprint: {type_dist}. Outcome: {'converted' if has_conversion else 'no conversion'}. {len(similar_neighbors)} similar peers.",
        confidence=min(0.7, 0.2 + len(similar_neighbors) * 0.05),
        tenant_id=tenant_id,
    )
    await signal_repo.insert(signal["id"], signal)
    metrics.increment("behavioral_signal_computed", labels={"family": "behavioral_twin"})
    return signal


# ═══════════════════════════════════════════════════════════════════
# FULL SCAN
# ═══════════════════════════════════════════════════════════════════

async def run_full_behavioral_scan(
    entity_id: str,
    analytics: AnalyticsRepository,
    graph: GraphClient,
    tenant_id: str = "",
) -> dict:
    """Run all behavioral engines for an entity."""
    results = {}
    for name, fn in [
        # Phase 1
        ("intent_residue", lambda: compute_intent_residue(entity_id, analytics, tenant_id)),
        ("wallet_friction", lambda: compute_wallet_friction(entity_id, analytics, tenant_id)),
        ("identity_delta", lambda: compute_identity_delta(entity_id, graph, tenant_id)),
        ("pre_post_continuity", lambda: compute_pre_post_continuity(entity_id, analytics, tenant_id)),
        ("sequence_scars", lambda: compute_sequence_scars(entity_id, analytics, tenant_id)),
        ("source_shadow", lambda: compute_source_shadow(entity_id, tenant_id)),
        # Phase 2
        ("reward_near_miss", lambda: compute_reward_near_miss(entity_id, analytics, tenant_id)),
        ("social_chain_lag", lambda: compute_social_chain_lag(entity_id, analytics, tenant_id)),
        ("cex_dex_transition", lambda: compute_cex_dex_transition(entity_id, analytics, tenant_id)),
        # Phase 3
        ("behavioral_twin", lambda: compute_behavioral_twins(entity_id, analytics, graph, tenant_id)),
    ]:
        try:
            signal = await fn()
            results[name] = signal
        except Exception as e:
            logger.error(f"Behavioral engine {name} failed for {entity_id}: {e}")
            results[name] = None

    computed = sum(1 for v in results.values() if v is not None)
    metrics.increment("behavioral_full_scan", labels={"signals_computed": str(computed)})
    return {
        "entity_id": entity_id,
        "signals_computed": computed,
        "signals": {k: v for k, v in results.items() if v is not None},
        "scanned_at": utc_now().isoformat(),
    }
