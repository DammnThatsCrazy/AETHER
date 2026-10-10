"""Per-dimension derivation for the relationship-fidelity vector (M7).

Honesty contract (release-blocking):

* Unknown is never 0: every derivation returns ``None`` (dimension null /
  ``insufficient_data``) unless the required evidence is actually present.
* Correlated evidence is not independent evidence: every dimension that depends
  on recurring/repeated evidence consumes M6 independent grouping and damped
  support, never a naive raw sum.
* Absence of a detected incentive is never read as organic.
* Unidirectional observations never yield a low reciprocity value.
* Every value is an UNcalibrated heuristic in [0, 1] with a documented formula —
  never a probability, never a "universal strength" scalar.

``ctx`` is a read-only dict carrying execution context (currently
``window_seconds`` for frequency normalization and any upstream measured
pass-through values under the ``measured`` key).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from shared.relationship_fidelity.evidence import EffectiveEvidence

# Documented heuristic saturation thresholds / windows. These are handcrafted
# and versioned with the definitions; changing them requires a definition
# version bump (substrate immutability).
PERSISTENCE_HORIZON_DAYS: float = 90.0
PERSISTENCE_SUPPORT_BAR: float = 6.0
REFERENCE_FREQUENCY_PER_DAY: float = 1.0

_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _span_days(first: Optional[str], last: Optional[str]) -> Optional[float]:
    a = _parse_ts(first)
    b = _parse_ts(last)
    if a is None or b is None:
        return None
    seconds = (b - a).total_seconds()
    if seconds <= 0:
        return None
    return seconds / 86400.0


def passthrough_value(value: object) -> Optional[float]:
    """Validate an upstream measured pass-through into [0, 1] (or drop to None)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not (0.0 <= v <= 1.0):
        return None
    return round(v, 4)


def _group_direction_counts(eff: EffectiveEvidence) -> tuple[Optional[int], Optional[int]]:
    """Count independent groups containing outgoing / incoming observations."""
    if eff.account is None:
        return None, None
    by_id = {o.observation_id: o for o in eff.observations}
    outgoing = 0
    incoming = 0
    for group in eff.account.groups:
        has_out = has_in = False
        for oid in group.observation_ids:
            obs = by_id.get(oid)
            if obs is None:
                continue
            if obs.direction == "outgoing":
                has_out = True
            elif obs.direction == "incoming":
                has_in = True
        if has_out:
            outgoing += 1
        if has_in:
            incoming += 1
    return outgoing, incoming


# --------------------------------------------------------------------------- #
# Count derivations
# --------------------------------------------------------------------------- #
def derive_observation_count(eff: EffectiveEvidence, ctx: dict) -> Optional[int]:
    return eff.observation_count


def derive_independent_evidence_count(eff: EffectiveEvidence, ctx: dict) -> Optional[int]:
    if eff.independence_unknown:
        return None
    return eff.independent_evidence_count


def derive_independent_source_count(eff: EffectiveEvidence, ctx: dict) -> Optional[int]:
    if eff.independence_unknown:
        return None
    return eff.independent_source_count


# --------------------------------------------------------------------------- #
# Confidence / reliability
# --------------------------------------------------------------------------- #
def derive_evidence_confidence(eff: EffectiveEvidence, ctx: dict) -> Optional[float]:
    """Existence confidence (separate from relationship strength).

    Requires >=1 observation and a known corroboration basis: M6 independent
    group count when grouping is present, else distinct raw source count (raw
    sources are only a proxy — never claimed as full independence). Value grows
    monotonically with corroboration: ``1 - 0.4/(1 + corroboration)``.
    """
    if eff.observation_count < 1:
        return None
    if eff.independence_unknown:
        corroboration = eff.distinct_sources
    else:
        corroboration = eff.independent_evidence_count
    if corroboration is None or corroboration <= 0:
        return None
    value = 1.0 - 0.4 / (1.0 + corroboration)
    return round(max(0.0, min(1.0, value)), 4)


def derive_source_reliability(eff: EffectiveEvidence, ctx: dict) -> Optional[float]:
    reliabilities = [
        o.source_reliability for o in eff.observations if o.source_reliability is not None
    ]
    if not reliabilities:
        return None
    return round(sum(reliabilities) / len(reliabilities), 4)


# --------------------------------------------------------------------------- #
# Independence-gated strength dimensions
# --------------------------------------------------------------------------- #
def derive_persistence(eff: EffectiveEvidence, ctx: dict) -> Optional[float]:
    """Durability: independent recurring evidence across time.

    INDEPENDENCE-GATED: when M6 grouping is absent this returns None (duplicated
    raw reports can never manufacture durability).
    """
    if eff.independence_unknown or eff.independent_evidence_count is None:
        return None
    k = eff.independent_evidence_count
    if k < 2:
        return None
    span_days = _span_days(eff.first_observed_at, eff.last_observed_at)
    if span_days is None or span_days <= 0:
        return None
    time_score = min(1.0, span_days / PERSISTENCE_HORIZON_DAYS)
    support_score = min(1.0, k / PERSISTENCE_SUPPORT_BAR)
    return round(min(1.0, 0.5 * time_score + 0.5 * support_score), 4)


def derive_reciprocity(eff: EffectiveEvidence, ctx: dict) -> Optional[float]:
    """Independent bidirectional reciprocity.

    Returns the harmonic proportion ``2*min(o,i)/(o+i)`` over independent groups
    containing outgoing (o) / incoming (i) observations — ONLY when both
    directions are independently observed. Unidirectional evidence is unknown,
    never low reciprocity (never 0).
    """
    if eff.independence_unknown:
        return None
    outgoing, incoming = _group_direction_counts(eff)
    if outgoing is None or incoming is None:
        return None
    if outgoing == 0 or incoming == 0:
        return None
    return round(2.0 * min(outgoing, incoming) / (outgoing + incoming), 4)


def derive_incentive_independence_support(eff: EffectiveEvidence, ctx: dict) -> Optional[float]:
    """Share of independent groups whose assessed members carry no incentive.

    Requires M6 grouping AND that incentive presence/absence was actually
    assessed. Unassessed observations are never counted as incentive-free.
    """
    if eff.independence_unknown or eff.account is None:
        return None
    if eff.incentive_assessed_count == 0:
        return None
    by_id = {o.observation_id: o for o in eff.observations}
    free_groups = 0
    assessed_groups = 0
    for group in eff.account.groups:
        free = True
        assessed = False
        for oid in group.observation_ids:
            obs = by_id.get(oid)
            if obs is None or not obs.incentive_assessed:
                continue
            assessed = True
            if obs.incentive_context:
                free = False
        if assessed:
            assessed_groups += 1
            if free:
                free_groups += 1
    if assessed_groups == 0:
        return None
    return round(free_groups / assessed_groups, 4)


def derive_coordination_indicator_strength(eff: EffectiveEvidence, ctx: dict) -> Optional[float]:
    """Observed coordination structure across independent groups.

    Present ONLY when at least two groups share a correlation family (a
    coordination structure is actually observed); otherwise None — absence of a
    detected coordination indicator is not a low indicator.
    """
    if eff.independence_unknown or eff.account is None:
        return None
    family_counts: Counter = Counter()
    for group in eff.account.groups:
        if group.correlation_family:
            family_counts[group.correlation_family] += 1
    correlated_families = {f: n for f, n in family_counts.items() if n > 1}
    if not correlated_families:
        return None
    correlated_groups = sum(correlated_families.values())
    total = len(eff.account.groups)
    if total == 0:
        return None
    return round(min(1.0, correlated_groups / total), 4)


# --------------------------------------------------------------------------- #
# Raw-evidence dimensions (no independence claim)
# --------------------------------------------------------------------------- #
def derive_interaction_frequency(eff: EffectiveEvidence, ctx: dict) -> Optional[float]:
    """Observed interaction frequency normalized by the observation window.

    Units are the damped effective support when grouping is present, else the raw
    observation count (disclosed, in the definition description, as
    independence-unverified). Requires a caller-supplied ``window_seconds``.
    """
    window_seconds = ctx.get("window_seconds")
    if not window_seconds or window_seconds <= 0:
        return None
    if eff.observation_count == 0:
        return None
    window_days = float(window_seconds) / 86400.0
    units = eff.damped_support if eff.damped_support is not None else float(eff.observation_count)
    rate_per_day = units / window_days
    return round(min(1.0, rate_per_day / REFERENCE_FREQUENCY_PER_DAY), 4)


def derive_interaction_depth(eff: EffectiveEvidence, ctx: dict) -> Optional[float]:
    intensities = [o.intensity for o in eff.observations if o.intensity is not None]
    if not intensities:
        return None
    return round(sum(intensities) / len(intensities), 4)


def derive_context_diversity(eff: EffectiveEvidence, ctx: dict) -> Optional[float]:
    if eff.observation_count == 0 or eff.distinct_context_tags is None:
        return None
    return round(min(1.0, eff.distinct_context_tags / eff.observation_count), 4)


def derive_temporal_continuity(eff: EffectiveEvidence, ctx: dict) -> Optional[float]:
    """Fraction of the observed span days that carry an observation."""
    if eff.distinct_observation_days is None or eff.distinct_observation_days < 2:
        return None
    span_days = _span_days(eff.first_observed_at, eff.last_observed_at)
    if span_days is None or span_days <= 0:
        return None
    return round(min(1.0, (eff.distinct_observation_days - 1) / span_days), 4)


def derive_incentive_exposure(eff: EffectiveEvidence, ctx: dict) -> Optional[float]:
    """Fraction of INCENTIVE-ASSESSED observations under an incentive.

    A returned 0 is evidence-backed (assessed and none incentivized); unassessed
    observations are never read as organic.
    """
    if eff.incentive_assessed_count == 0:
        return None
    return round(eff.incentive_present_count / eff.incentive_assessed_count, 4)


# Measured pass-through (dimension values owned by upstream domain systems).
def measured_passthrough(eff: EffectiveEvidence, ctx: dict) -> Optional[float]:
    measured = ctx.get("measured") or {}
    dimension = ctx.get("dimension")
    if dimension is None or dimension not in measured:
        return None
    return passthrough_value(measured.get(dimension))


DERIVERS: dict[str, object] = {
    "observation_count": derive_observation_count,
    "independent_evidence_count": derive_independent_evidence_count,
    "independent_source_count": derive_independent_source_count,
    "evidence_confidence": derive_evidence_confidence,
    "source_reliability": derive_source_reliability,
    "persistence": derive_persistence,
    "reciprocity": derive_reciprocity,
    "incentive_independence_support": derive_incentive_independence_support,
    "coordination_indicator_strength": derive_coordination_indicator_strength,
    "interaction_frequency": derive_interaction_frequency,
    "interaction_depth": derive_interaction_depth,
    "context_diversity": derive_context_diversity,
    "temporal_continuity": derive_temporal_continuity,
    "incentive_exposure": derive_incentive_exposure,
}


__all__ = [
    "passthrough_value",
    "derive_observation_count",
    "derive_independent_evidence_count",
    "derive_independent_source_count",
    "derive_evidence_confidence",
    "derive_source_reliability",
    "derive_persistence",
    "derive_reciprocity",
    "derive_incentive_independence_support",
    "derive_coordination_indicator_strength",
    "derive_interaction_frequency",
    "derive_interaction_depth",
    "derive_context_diversity",
    "derive_temporal_continuity",
    "derive_incentive_exposure",
    "measured_passthrough",
    "DERIVERS",
]
