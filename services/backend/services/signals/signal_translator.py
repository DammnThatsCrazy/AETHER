"""
Aether — Signal Translator
Maps ML model feature importance vectors and computed gold-tier metrics
into human-readable BehavioralSignal instances.

20 signal templates organized by sentiment:
  positive: DeFi power user, early adopter, governance participant, etc.
  informational: high crypto exposure, agent activity, stablecoin dominant, etc.
  caution: at-risk of churn, location anomaly, discount sensitive, etc.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from shared.logger.logger import get_logger

logger = get_logger("aether.signals.translator")

Sentiment = str  # 'positive' | 'caution' | 'negative' | 'informational'


@dataclass
class SignalTemplate:
    signal_id: str
    signal_type: str
    family: str
    severity: str
    sentiment: Sentiment
    explanation_template: str


# ── 20 signal templates ────────────────────────────────────────────────────────

SIGNAL_TEMPLATES: list[SignalTemplate] = [
    SignalTemplate(
        signal_id="CONSISTENT_INCOME_PATTERN",
        signal_type="MISSING_EXPECTED_EDGE",
        family="continuity",
        severity="info",
        sentiment="positive",
        explanation_template="Entity shows regular inflow pattern: consistent {frequency} transactions averaging ${avg_amount_usd:.0f} USD.",
    ),
    SignalTemplate(
        signal_id="HIGH_CRYPTO_EXPOSURE",
        signal_type="MISSING_EXPECTED_EDGE",
        family="intent_residue",
        severity="info",
        sentiment="informational",
        explanation_template="Altcoin allocation is {altcoin_pct:.0f}% of portfolio — above typical diversification thresholds.",
    ),
    SignalTemplate(
        signal_id="YIELD_FARMER",
        signal_type="MISSING_EXPECTED_ACTION",
        family="intent_residue",
        severity="info",
        sentiment="positive",
        explanation_template="Active LP positions across {lp_protocol_count} protocols plus staking activity in {staking_protocol_count} protocol(s).",
    ),
    SignalTemplate(
        signal_id="EARLY_ADOPTER",
        signal_type="MISSING_EXPECTED_EDGE",
        family="continuity",
        severity="info",
        sentiment="positive",
        explanation_template="First interaction with {protocol_name} occurred before the protocol reached 1,000 active users.",
    ),
    SignalTemplate(
        signal_id="AT_RISK_OF_CHURN",
        signal_type="MISSING_EXPECTED_ACTION",
        family="sequence_scars",
        severity="high",
        sentiment="caution",
        explanation_template="Churn model probability {churn_probability:.0%} — entity hasn't been active in {days_since_last_visit} days.",
    ),
    SignalTemplate(
        signal_id="HIGH_SLIPPAGE_TOLERANCE",
        signal_type="MISSING_EXPECTED_EDGE",
        family="intent_residue",
        severity="info",
        sentiment="informational",
        explanation_template="Average swap slippage is {avg_slippage_pct:.1f}% — above the median for this cohort.",
    ),
    SignalTemplate(
        signal_id="GOVERNANCE_PARTICIPANT",
        signal_type="MISSING_EXPECTED_ACTION",
        family="continuity",
        severity="info",
        sentiment="positive",
        explanation_template="Cast {vote_count} governance votes across {space_count} DAO space(s) in the last 90 days.",
    ),
    SignalTemplate(
        signal_id="CROSS_CHAIN_POWER_USER",
        signal_type="MISSING_EXPECTED_EDGE",
        family="continuity",
        severity="info",
        sentiment="positive",
        explanation_template="Active on {chain_count} chains — bridges across {bridge_count} bridge protocol(s).",
    ),
    SignalTemplate(
        signal_id="WALLET_CLUSTER_DETECTED",
        signal_type="IDENTITY_CONTRADICTION",
        family="identity_deltas",
        severity="medium",
        sentiment="informational",
        explanation_template="Entity is part of a wallet bundle with {cluster_size} addresses (confidence: {bundle_confidence:.0%}).",
    ),
    SignalTemplate(
        signal_id="LOCATION_ANOMALY",
        signal_type="TEMPORAL_CONTRADICTION",
        family="identity_deltas",
        severity="high",
        sentiment="caution",
        explanation_template="New primary location detected: {city}, {country}. Previous primary was {previous_city}, {previous_country}.",
    ),
    SignalTemplate(
        signal_id="AGENT_ASSISTED_ACTIVITY",
        signal_type="MISSING_EXPECTED_EDGE",
        family="source_shadow",
        severity="info",
        sentiment="informational",
        explanation_template="{agent_pct:.0%} of transactions executed via owned agent(s) in the last 30 days.",
    ),
    SignalTemplate(
        signal_id="NEW_TO_PROTOCOL",
        signal_type="MISSING_EXPECTED_EDGE",
        family="intent_residue",
        severity="info",
        sentiment="informational",
        explanation_template="First interaction with {protocol_name} was {days_ago} day(s) ago.",
    ),
    SignalTemplate(
        signal_id="DISCOUNT_SENSITIVE",
        signal_type="MISSING_EXPECTED_ACTION",
        family="intent_residue",
        severity="medium",
        sentiment="caution",
        explanation_template="Discount usage rate of {discount_rate:.0%} — entity converts primarily on promotional offers.",
    ),
    SignalTemplate(
        signal_id="HIGH_REFERRAL_GENERATOR",
        signal_type="MISSING_EXPECTED_EDGE",
        family="continuity",
        severity="info",
        sentiment="positive",
        explanation_template="Generated {referral_count} successful referrals in the last 90 days.",
    ),
    SignalTemplate(
        signal_id="BRIDGE_POWER_USER",
        signal_type="MISSING_EXPECTED_EDGE",
        family="continuity",
        severity="info",
        sentiment="positive",
        explanation_template="{bridge_transfer_count} cross-chain bridge transfers in the last 30 days.",
    ),
    SignalTemplate(
        signal_id="STABLECOIN_DOMINANT",
        signal_type="MISSING_EXPECTED_EDGE",
        family="intent_residue",
        severity="info",
        sentiment="informational",
        explanation_template="Stablecoin allocation is {stablecoin_pct:.0f}% of portfolio — entity is holding predominantly stable assets.",
    ),
    SignalTemplate(
        signal_id="DEFI_NATIVE",
        signal_type="MISSING_EXPECTED_EDGE",
        family="continuity",
        severity="info",
        sentiment="positive",
        explanation_template="Active across {unique_protocol_count} unique DeFi protocols.",
    ),
    SignalTemplate(
        signal_id="POTENTIAL_WHALE",
        signal_type="MISSING_EXPECTED_EDGE",
        family="continuity",
        severity="info",
        sentiment="positive",
        explanation_template="Portfolio value ${tvl_usd:,.0f} USD places entity in the {percentile:.1f}th percentile of the cohort.",
    ),
    SignalTemplate(
        signal_id="GEOGRAPHIC_FOCUS",
        signal_type="MISSING_EXPECTED_EDGE",
        family="identity_deltas",
        severity="info",
        sentiment="informational",
        explanation_template="{country_pct:.0f}% of sessions originate from {country} — entity has a single-country geographic focus.",
    ),
    SignalTemplate(
        signal_id="CONCENTRATED_PORTFOLIO",
        signal_type="MISSING_EXPECTED_EDGE",
        family="wallet_friction",
        severity="medium",
        sentiment="caution",
        explanation_template="Top holding ({symbol}) represents {top_holding_pct:.0f}% of portfolio — high concentration risk.",
    ),
]

_TEMPLATE_INDEX: dict[str, SignalTemplate] = {t.signal_id: t for t in SIGNAL_TEMPLATES}


def translate_signal(
    signal_id: str,
    entity_id: str,
    confidence: float,
    evidence_refs: list[str],
    template_vars: dict[str, Any],
    last_detected: datetime | None = None,
) -> dict[str, Any] | None:
    """
    Translate a signal_id + template variables into a BehavioralSignal dict.

    Args:
        signal_id: One of the 20 signal template IDs.
        entity_id: The entity this signal applies to.
        confidence: 0–1 engine confidence.
        evidence_refs: Event IDs or metric names that triggered this signal.
        template_vars: Variables to interpolate into the explanation template.
        last_detected: When the signal was last detected (defaults to now).

    Returns:
        BehavioralSignal dict or None if the signal_id is not recognized.
    """
    template = _TEMPLATE_INDEX.get(signal_id)
    if not template:
        logger.warning(f"Unknown signal_id: {signal_id}")
        return None

    now = datetime.now(timezone.utc)
    detected_at = last_detected or now
    is_stale = (now - detected_at).days > 30

    try:
        explanation = template.explanation_template.format(**template_vars)
    except (KeyError, ValueError) as exc:
        logger.error(f"Signal template formatting failed for {signal_id}: {exc}")
        explanation = template.explanation_template

    return {
        "signal_id": f"{signal_id}:{entity_id}:{uuid.uuid4().hex[:8]}",
        "signal_type": template.signal_type,
        "family": template.family,
        "severity": template.severity,
        "sentiment": template.sentiment,
        "confidence": confidence,
        "explanation": explanation,
        "is_source_silence": False,
        "entity_id": entity_id,
        "evidence_refs": evidence_refs,
        "last_detected": detected_at.isoformat(),
        "is_stale": is_stale,
        "created_at": now.isoformat(),
    }


def signals_from_churn_model(
    entity_id: str,
    features: dict[str, float],
    churn_probability: float,
) -> list[dict[str, Any]]:
    """Derive behavioral signals from the ChurnPrediction model output."""
    signals = []

    if churn_probability >= 0.7:
        sig = translate_signal(
            signal_id="AT_RISK_OF_CHURN",
            entity_id=entity_id,
            confidence=churn_probability,
            evidence_refs=["churn_model_output"],
            template_vars={
                "churn_probability": churn_probability,
                "days_since_last_visit": int(features.get("days_since_last_visit", 0)),
            },
        )
        if sig:
            signals.append(sig)

    if features.get("discount_usage_rate", 0) > 0.5:
        sig = translate_signal(
            signal_id="DISCOUNT_SENSITIVE",
            entity_id=entity_id,
            confidence=min(features["discount_usage_rate"], 1.0),
            evidence_refs=["ltv_model_features"],
            template_vars={"discount_rate": features["discount_usage_rate"]},
        )
        if sig:
            signals.append(sig)

    if features.get("referral_count", 0) > 5:
        sig = translate_signal(
            signal_id="HIGH_REFERRAL_GENERATOR",
            entity_id=entity_id,
            confidence=0.9,
            evidence_refs=["ltv_model_features"],
            template_vars={"referral_count": int(features["referral_count"])},
        )
        if sig:
            signals.append(sig)

    return signals


def signals_from_asset_composition(
    entity_id: str,
    stablecoin_pct: float,
    altcoin_pct: float,
    top_symbol: str,
    top_holding_pct: float,
) -> list[dict[str, Any]]:
    """Derive behavioral signals from asset composition data."""
    signals = []

    if altcoin_pct > 60:
        sig = translate_signal(
            signal_id="HIGH_CRYPTO_EXPOSURE",
            entity_id=entity_id,
            confidence=min(altcoin_pct / 100, 1.0),
            evidence_refs=["gold_asset_composition"],
            template_vars={"altcoin_pct": altcoin_pct},
        )
        if sig:
            signals.append(sig)

    if stablecoin_pct > 70:
        sig = translate_signal(
            signal_id="STABLECOIN_DOMINANT",
            entity_id=entity_id,
            confidence=min(stablecoin_pct / 100, 1.0),
            evidence_refs=["gold_asset_composition"],
            template_vars={"stablecoin_pct": stablecoin_pct},
        )
        if sig:
            signals.append(sig)

    if top_holding_pct > 80:
        sig = translate_signal(
            signal_id="CONCENTRATED_PORTFOLIO",
            entity_id=entity_id,
            confidence=min(top_holding_pct / 100, 1.0),
            evidence_refs=["gold_asset_composition"],
            template_vars={"symbol": top_symbol, "top_holding_pct": top_holding_pct},
        )
        if sig:
            signals.append(sig)

    return signals


def signals_from_location_history(
    entity_id: str,
    locations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Derive behavioral signals from location history data."""
    signals = []

    # Check for new primary location anomaly
    new_primary = next(
        (loc for loc in locations if loc.get("is_new_primary") and loc.get("classification") == "primary"),
        None,
    )
    if new_primary:
        # Find previous primary to include in explanation
        other_primaries = [
            loc for loc in locations
            if loc.get("classification") == "primary" and not loc.get("is_new_primary")
        ]
        previous = other_primaries[0] if other_primaries else {"city": "unknown", "country": "unknown"}
        sig = translate_signal(
            signal_id="LOCATION_ANOMALY",
            entity_id=entity_id,
            confidence=0.85,
            evidence_refs=["gold_location_history"],
            template_vars={
                "city": new_primary.get("city", ""),
                "country": new_primary.get("country", ""),
                "previous_city": previous.get("city", "unknown"),
                "previous_country": previous.get("country", "unknown"),
            },
        )
        if sig:
            signals.append(sig)

    # Single-country geographic focus
    if locations:
        total_sessions = sum(loc.get("session_count", 0) for loc in locations)
        if total_sessions > 0:
            countries: dict[str, int] = {}
            for loc in locations:
                c = loc.get("country", "")
                countries[c] = countries.get(c, 0) + loc.get("session_count", 0)
            top_country, top_count = max(countries.items(), key=lambda x: x[1])
            country_pct = (top_count / total_sessions) * 100
            if country_pct >= 90:
                sig = translate_signal(
                    signal_id="GEOGRAPHIC_FOCUS",
                    entity_id=entity_id,
                    confidence=0.8,
                    evidence_refs=["gold_location_history"],
                    template_vars={"country_pct": country_pct, "country": top_country},
                )
                if sig:
                    signals.append(sig)

    return signals
