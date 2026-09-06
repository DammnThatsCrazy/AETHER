"""Evidence grouping + contradiction for relationship-predicate candidates.

Milestone M6 (Social360 + Relationship Fidelity, blueprint §§29-30, §66). Raw
social/communication/economic observations are grouped into bounded
relationship-predicate candidates. For each candidate the group reports:

* (a) INDEPENDENT-SOURCE counting -- how many genuinely independent sources
      observed the candidate (duplicates from one source/lineage are one
      source, never counted many times);
* (b) CORRELATION damping -- the 0.4 diminishing-returns discipline reused from
      ``services/fraud/evaluation.py`` (``_CORRELATED_SIGNAL_DAMPING = 0.4``):
      structurally-correlated sources (same device / same campaign / same
      provider surface) do not add as independent evidence;
* (c) CONTRADICTION detection -- supporting AND contradicting observations of
      the same candidate are surfaced together; a candidate with contradiction
      is never silently resolved to "clean";
* (d) dimension-style HONEST output following ``shared/dimension_state.py``:
      unknown is never zero -- a candidate with no supporting observations is
      reported as insufficient/unknown, never as evidence of absence.

This module is pure and dependency-light: it performs no graph writes. Promotion
(``promotion.py``) consumes the produced :class:`EvidenceGroup` and decides
whether a candidate crosses its predicate's registry evidence floor.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Optional

# Correlation damping discipline reused from services/fraud/evaluation.py:
# the 2nd, 3rd, ... structurally-correlated sibling within a family contributes
# 0.4 of a genuinely independent source instead of a full 1.0.
CORRELATION_DAMPING = 0.4

# Canonical honest states for a relationship candidate.
class CandidateState(str, Enum):
    UNKNOWN = "unknown"                  # no observations collected at all
    INSUFFICIENT = "insufficient_data"   # supporting evidence below the floor
    SUPPORTED = "supported"              # floor met, no contradiction
    CONTRADICTED = "contradicted"        # supporting AND contradicting present
    CONTESTED = "contested"              # only contradicting observations present
    STALE = "stale"                      # evidence present but outside freshness


# Reason codes (dimension-style) mirroring shared/dimension_state.py vocabulary.
REASON_NO_DATA = "no_data"
REASON_BELOW_MIN_EVENTS = "below_min_events"
REASON_CONTRADICTION = "contradiction_present"
REASON_OK = "ok"
REASON_PAST_FRESHNESS_SLA = "past_freshness_sla"


@dataclass(frozen=True)
class Observation:
    """One raw observation already bound to a relationship-predicate candidate.

    ``source_key`` is the independent-source lineage identity (an event id, a
    provider surface id, ...). Multiple observations sharing a ``source_key``
    are treated as ONE independent source. ``correlation_family`` optionally
    marks structural correlation shared across otherwise-independent sources
    (same device / same campaign / same provider bundle), which the grouping
    discounts via :data:`CORRELATION_DAMPING`.

    ``supports_predicate=False`` marks a CONTRADICTING observation (e.g. a
    provider state that reports the pair is NOT connected, or an unfollow).
    """

    observation_id: str
    predicate: str
    source_entity_id: str
    target_entity_id: str
    source_key: str
    observed_at: str  # ISO-8601
    supports_predicate: bool = True
    correlation_family: Optional[str] = None
    proof_level: str = "provider_observed"
    evidence_basis: str = "provider_observed"

    def _ts(self) -> Optional[_dt.datetime]:
        try:
            return _dt.datetime.fromisoformat(str(self.observed_at))
        except (TypeError, ValueError):
            return None


def effective_independent_sources(observations: Iterable[Observation]) -> float:
    """Correlation-damped independent-source count for supporting observations.

    Distinct ``source_key`` values are bucketed by ``correlation_family``
    (observations without an explicit family are their own bucket). Within a
    family the first source contributes 1.0 and each additional correlated
    sibling contributes :data:`CORRELATION_DAMPING` (0.4) -- the same
    diminishing-returns discipline as ``services/fraud/evaluation.py``.
    Genuinely independent families sum at full weight.
    """
    by_family: dict[Optional[str], set[str]] = {}
    for obs in observations:
        family = obs.correlation_family or obs.source_key
        by_family.setdefault(family, set()).add(obs.source_key)
    total = 0.0
    for keys in by_family.values():
        # A family with n distinct sources: first at 1.0, siblings damped.
        total += 1.0 + CORRELATION_DAMPING * (len(keys) - 1)
    return round(total, 4)


def distinct_independent_sources(observations: Iterable[Observation]) -> int:
    """Count genuinely distinct independent source keys (no correlation damp)."""
    return len({obs.source_key for obs in observations})


def _day(obs: Observation) -> Optional[str]:
    ts = obs._ts()
    if ts is None:
        return None
    return ts.date().isoformat()


def distinct_active_days(observations: Iterable[Observation]) -> int:
    """Distinct calendar days with supporting evidence (temporal dispersion)."""
    days = {d for d in (_day(o) for o in observations) if d is not None}
    return len(days)


def temporal_span_days(observations: Iterable[Observation]) -> Optional[int]:
    """Days between the earliest and latest supporting observation (None when <2)."""
    stamps = sorted(o._ts() for o in observations if o._ts() is not None)
    if len(stamps) < 2:
        return None
    return max(1, int((stamps[-1] - stamps[0]).total_seconds() // 86400))


@dataclass
class EvidenceGroup:
    """All observations grouped under one (source, predicate, target) candidate.

    ``effective_independent_sources`` is the correlation-damped independence
    count over SUPPORTING observations (contradicting observations are never
    counted as support). ``contradiction_state`` summarises support vs. counter
    evidence honestly.
    """

    predicate: str
    source_entity_id: str
    target_entity_id: str
    supporting: list[Observation] = field(default_factory=list)
    contradicting: list[Observation] = field(default_factory=list)

    # ── Supporting-evidence summary ─────────────────────────────────────────
    @property
    def raw_support_count(self) -> int:
        return len(self.supporting)

    @property
    def contradicting_count(self) -> int:
        return len(self.contradicting)

    @property
    def distinct_support_sources(self) -> int:
        return distinct_independent_sources(self.supporting)

    @property
    def effective_independent_sources(self) -> float:
        return effective_independent_sources(self.supporting)

    @property
    def distinct_active_days(self) -> int:
        return distinct_active_days(self.supporting)

    @property
    def span_days(self) -> Optional[int]:
        return temporal_span_days(self.supporting)

    # ── Contradiction ───────────────────────────────────────────────────────
    @property
    def has_contradiction(self) -> bool:
        """True when there is BOTH supporting and contradicting evidence."""
        return bool(self.supporting) and bool(self.contradicting)

    def contradiction_state(self) -> str:
        """Honest contradiction classification (never auto-resolves to clean)."""
        if self.has_contradiction:
            return CandidateState.CONTRADICTED.value
        if self.contradicting and not self.supporting:
            return CandidateState.CONTESTED.value
        if not self.supporting:
            return CandidateState.UNKNOWN.value
        return CandidateState.SUPPORTED.value

    # ── Dimension-style envelope ────────────────────────────────────────────
    def evidence_state(self, minimum_independent_sources: float = 1.0) -> str:
        """Honest candidate state given a predicate's independence floor.

        Follows ``shared/dimension_state.py`` honesty: an unsupported candidate
        is ``insufficient_data``/``unknown`` (never zero evidence of absence)
        and a contested candidate is surfaced as such instead of auto-resolving.
        """
        if self.has_contradiction:
            return CandidateState.CONTRADICTED.value
        if not self.supporting:
            return CandidateState.UNKNOWN.value
        if self.effective_independent_sources < minimum_independent_sources:
            return CandidateState.INSUFFICIENT.value
        return CandidateState.SUPPORTED.value

    def reason_code(self, minimum_independent_sources: float = 1.0) -> str:
        if self.has_contradiction:
            return REASON_CONTRADICTION
        if not self.supporting:
            return REASON_NO_DATA
        if self.effective_independent_sources < minimum_independent_sources:
            return REASON_BELOW_MIN_EVENTS
        return REASON_OK

    def to_dict(self) -> dict[str, Any]:
        return {
            "predicate": self.predicate,
            "source_entity_id": self.source_entity_id,
            "target_entity_id": self.target_entity_id,
            "supporting_count": self.raw_support_count,
            "contradicting_count": self.contradicting_count,
            "distinct_independent_sources": self.distinct_support_sources,
            "effective_independent_sources": self.effective_independent_sources,
            "distinct_active_days": self.distinct_active_days,
            "span_days": self.span_days,
            "contradiction_state": self.contradiction_state(),
        }


def group_observations(observations: Iterable[Observation]) -> dict[tuple[str, str, str], EvidenceGroup]:
    """Group observations into (predicate, source, target) candidate buckets.

    Missing candidates -- a (source, target) pair never observed for a predicate
    -- are intentionally ABSENT from the result. Absence is ``unknown``, never a
    ``0`` that reads as "no relationship"; callers must represent unknown
    candidates explicitly and not treat a missing key as a negative fact.
    """
    groups: dict[tuple[str, str, str], EvidenceGroup] = {}
    for obs in observations:
        key = (obs.predicate, obs.source_entity_id, obs.target_entity_id)
        group = groups.get(key)
        if group is None:
            group = EvidenceGroup(
                predicate=obs.predicate,
                source_entity_id=obs.source_entity_id,
                target_entity_id=obs.target_entity_id,
            )
            groups[key] = group
        (group.supporting if obs.supports_predicate else group.contradicting).append(obs)
    return groups


def candidate_groups_for_pair(
    observations: Iterable[Observation],
    predicate: str,
    source_entity_id: str,
    target_entity_id: str,
) -> EvidenceGroup:
    """Return the candidate group for one directed (source, predicate, target).

    Returns an EMPTY group when no observations exist (all counters zero) so
    callers can distinguish "evidence collected and contradicts" from "no
    evidence yet" through :meth:`EvidenceGroup.contradiction_state`, which
    reports ``unknown`` for an empty group rather than implying absence.
    """
    groups = group_observations(observations)
    return groups.get((predicate, source_entity_id, target_entity_id), EvidenceGroup(
        predicate=predicate,
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
    ))


__all__ = [
    "CORRELATION_DAMPING",
    "CandidateState",
    "REASON_NO_DATA",
    "REASON_BELOW_MIN_EVENTS",
    "REASON_CONTRADICTION",
    "REASON_OK",
    "REASON_PAST_FRESHNESS_SLA",
    "Observation",
    "EvidenceGroup",
    "effective_independent_sources",
    "distinct_independent_sources",
    "distinct_active_days",
    "temporal_span_days",
    "group_observations",
    "candidate_groups_for_pair",
]
