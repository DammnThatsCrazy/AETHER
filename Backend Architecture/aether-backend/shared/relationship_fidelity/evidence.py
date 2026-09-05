"""Independent-observation accounting for relationship fidelity (M7).

Relationship fidelity may only strengthen on INDEPENDENT evidence; correlated
evidence is not independent evidence. This module declares the evidence
independence interface the M7 engine expects from the Milestone M6 evidence
engine, and the honest fallback when that engine is not yet present:

* When Milestone M6's evidence engine exists, the engine consumes it through
  ``services.relationship_promotion.evidence_independence.resolve_independent_groups``
  (imported defensively via :func:`load_m6_independence_resolver`).
* When that module does NOT exist (M6 not started), independence is UNKNOWN:
  ``independent_evidence_count`` / ``independent_source_count`` surface as
  ``None`` and every independence-gated fidelity dimension stays null
  (``insufficient_data``). UNKNOWN is never fabricated into a number and is
  never read as 0.

Correlation damping reuses the platform's 0.4 discipline
(``services/fraud/evaluation.py::_CORRELATED_SIGNAL_DAMPING``): the first member
of a correlated family counts in full; each additional correlated sibling counts
at :data:`CORRELATION_DAMPING`, so duplicated / structurally-correlated evidence
is never naively additive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Sequence

# The correlation-damping discipline reused from fraud evaluation
# (services/fraud/evaluation.py::_CORRELATED_SIGNAL_DAMPING == 0.4). The first
# member of a correlated family contributes full weight; every additional
# correlated sibling contributes at this factor.
CORRELATION_DAMPING: float = 0.4
CORRELATION_DAMPING_REFERENCE: str = "services/fraud/evaluation.py::_CORRELATED_SIGNAL_DAMPING"

# The M6 module the M7 engine expects to provide independent-observation
# grouping. Imported defensively: when it is absent, independence stays UNKNOWN.
M6_EVIDENCE_INDEPENDENCE_MODULE: str = "services.relationship_promotion.evidence_independence"
M6_RESOLVE_FACTORY: str = "resolve_independent_groups"


@dataclass(frozen=True)
class Observation:
    """A single raw relationship observation (one evidence item).

    ``correlation_family`` is an optional, non-authoritative hint that two
    observations are structurally correlated (same underlying cause). Only the
    M6 grouping is authoritative for independence; the hint is used purely to
    damp correlated evidence once grouping is available.
    """

    observation_id: str
    predicate: str  # canonical predicate ref, e.g. FOLLOWS
    direction: str  # "outgoing" | "incoming" | "undirected"
    source_key: str  # provider / source identity
    observed_at: str  # ISO-8601 timestamp
    intensity: Optional[float] = None  # optional observed intensity in [0, 1]
    source_reliability: Optional[float] = None  # optional source reliability in [0, 1]
    incentive_context: bool = False  # observation occurred under an incentive
    incentive_assessed: bool = False  # incentive presence/absence actually assessed
    correlation_family: Optional[str] = None
    context_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceGroup:
    """One independent-evidence group produced by M6 (an independent unit).

    Observations inside one group are NOT independent of each other (same
    underlying cause); distinct groups are the independent units. A
    ``correlation_family`` label on a group marks structurally-correlated
    siblings across groups for damping.
    """

    group_id: str
    observation_ids: tuple[str, ...] = ()
    source_key: Optional[str] = None
    correlation_family: Optional[str] = None


@dataclass(frozen=True)
class IndependentEvidenceAccount:
    """Independent-observation accounting.

    ``provided_by`` names the producer so provenance is honest (the M6 module
    import path when present, or an explicit caller-supplied account).
    ``independent_evidence_count`` is the number of independent groups (a
    measurement once grouping succeeded). ``independent_source_count`` is the
    number of distinct sources across the groups, or ``None`` when group sources
    are not labelled (unknown, never 0).
    """

    groups: tuple[EvidenceGroup, ...]
    provided_by: str
    independent_evidence_count: Optional[int] = None
    independent_source_count: Optional[int] = None

    def __post_init__(self) -> None:
        if self.independent_evidence_count is None:
            object.__setattr__(self, "independent_evidence_count", len(self.groups))
        if self.independent_source_count is None:
            sources = {g.source_key for g in self.groups if g.source_key}
            object.__setattr__(
                self,
                "independent_source_count",
                len(sources) if sources else None,
            )


class EvidenceIndependenceResolver(Protocol):
    """The interface M7 expects from the M6 evidence engine.

    M6 implements this contract to group raw observations into independent
    evidence. Returning ``None`` means independence could NOT be determined
    (independent counts stay UNKNOWN); it must never fabricate a number.
    """

    def resolve(
        self,
        *,
        relationship_ref: str,
        tenant_id: str,
        observations: Sequence[Observation],
    ) -> Optional[IndependentEvidenceAccount]:
        """Return the independent-observation account, or None when unknown."""
        ...


def load_m6_independence_resolver() -> Optional[EvidenceIndependenceResolver]:
    """Import the M6 evidence engine defensively.

    Returns the M6 factory callable when the module exists and exposes
    ``resolve_independent_groups``, otherwise ``None``. Importing M6 must never
    crash the fidelity path; when M6 is absent, independence is UNKNOWN and the
    engine degrades honestly (never a fabricated number).
    """
    try:
        import importlib

        module = importlib.import_module(M6_EVIDENCE_INDEPENDENCE_MODULE)
        factory = getattr(module, M6_RESOLVE_FACTORY, None)
    except Exception:
        return None
    if factory is None:
        return None
    return factory


def damped_evidence_weight(counts: Sequence[int], *, damping: float = CORRELATION_DAMPING) -> float:
    """Correlation-aware effective evidence weight (reuses the 0.4 discipline).

    Each family's first member counts 1.0; every additional correlated sibling
    counts at ``damping`` (0.4). Three genuinely independent families of size 1
    therefore weight 3.0, while one family of 3 correlated siblings weighs
    1.0 + 0.4 * 2 = 1.8 — correlated evidence is never naively additive.
    """
    total = 0.0
    for n in counts:
        n = max(0, int(n))
        if n == 0:
            continue
        total += 1.0 + damping * (n - 1)
    return round(total, 6)


def family_histogram(
    groups: Optional[Sequence[EvidenceGroup]],
) -> Optional[dict[str, int]]:
    """Map independent groups into correlation-family sizes.

    Each group is one independent unit; its ``correlation_family`` (when
    labelled) binds correlated siblings for damping, and an unlabelled group is
    its own family. Returns ``None`` when grouping is unavailable (independence
    unknown) — callers must NOT fall back to treating raw observations as
    independent.
    """
    if groups is None:
        return None
    histogram: dict[str, int] = {}
    for group in groups:
        family = group.correlation_family or group.group_id
        histogram[family] = histogram.get(family, 0) + 1
    return histogram


@dataclass(frozen=True)
class EffectiveEvidence:
    """Facts the scoring layer may honestly use, derived from raw observations.

    Fields whose value is unknown are ``None`` — never a fabricated 0.
    """

    observations: tuple[Observation, ...]
    account: Optional[IndependentEvidenceAccount]
    observation_count: int
    distinct_sources: Optional[int]
    independent_evidence_count: Optional[int]
    independent_source_count: Optional[int]
    damped_support: Optional[float]
    outgoing_count: int
    incoming_count: int
    undirected_count: int
    bidirectional_raw: bool
    incentive_assessed_count: int
    incentive_present_count: int
    distinct_context_tags: Optional[int]
    distinct_observation_days: Optional[int]
    first_observed_at: Optional[str]
    last_observed_at: Optional[str]

    @property
    def independence_unknown(self) -> bool:
        return self.account is None or self.independent_evidence_count is None


def _distinct_days(timestamps: Sequence[str]) -> Optional[int]:
    days: set[str] = set()
    for ts in timestamps:
        if not ts:
            continue
        try:
            days.add(ts[:10])  # ISO date portion (YYYY-MM-DD)
        except Exception:
            continue
    return len(days) if days else None


def build_effective_evidence(
    observations: Sequence[Observation],
    account: Optional[IndependentEvidenceAccount],
) -> EffectiveEvidence:
    """Derive honest evidence facts from raw observations + optional grouping."""
    obs = tuple(observations)
    account = account if (account is not None and len(account.groups) > 0) else None
    if account is not None:
        independent_count: Optional[int] = account.independent_evidence_count
        independent_sources: Optional[int] = account.independent_source_count
        hist = family_histogram(account.groups)
        damped = damped_evidence_weight(list(hist.values())) if hist else 0.0
    else:
        independent_count = None
        independent_sources = None
        hist = None
        damped = None

    sources: Optional[set[str]] = set()
    for o in obs:
        if not o.source_key:
            sources = None
            break
        sources.add(o.source_key)
    distinct_sources = len(sources) if sources is not None else None

    outgoing = incoming = undirected = 0
    assessed = present = 0
    tags: set[str] = set()
    for o in obs:
        if o.direction == "outgoing":
            outgoing += 1
        elif o.direction == "incoming":
            incoming += 1
        else:
            undirected += 1
        if o.incentive_assessed:
            assessed += 1
            if o.incentive_context:
                present += 1
        tags.update(o.context_tags)

    ts = [o.observed_at for o in obs if o.observed_at]
    ordered = sorted(ts)
    return EffectiveEvidence(
        observations=obs,
        account=account,
        observation_count=len(obs),
        distinct_sources=distinct_sources,
        independent_evidence_count=independent_count,
        independent_source_count=independent_sources,
        damped_support=damped,
        outgoing_count=outgoing,
        incoming_count=incoming,
        undirected_count=undirected,
        bidirectional_raw=(outgoing > 0 and incoming > 0),
        incentive_assessed_count=assessed,
        incentive_present_count=present,
        distinct_context_tags=len(tags) if tags else None,
        distinct_observation_days=_distinct_days(ts),
        first_observed_at=ordered[0] if ordered else None,
        last_observed_at=ordered[-1] if ordered else None,
    )


__all__ = [
    "CORRELATION_DAMPING",
    "CORRELATION_DAMPING_REFERENCE",
    "M6_EVIDENCE_INDEPENDENCE_MODULE",
    "M6_RESOLVE_FACTORY",
    "Observation",
    "EvidenceGroup",
    "IndependentEvidenceAccount",
    "EvidenceIndependenceResolver",
    "load_m6_independence_resolver",
    "damped_evidence_weight",
    "family_histogram",
    "EffectiveEvidence",
    "build_effective_evidence",
]
