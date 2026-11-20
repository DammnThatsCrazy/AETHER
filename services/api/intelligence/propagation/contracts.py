"""Propagation & Diffusion contracts (Python mirror).

Canonical JSON Schema: ``packages/shared/contracts/propagation-run.schema.json``.
TypeScript mirror: ``packages/shared/propagation-contract.ts``. Tests validate
every serialized run against the schema so the three cannot drift.

Honesty rules carried by these types:

* Unknown is never zero. A metric that cannot be computed is ``None`` with a
  reason code; a measured zero is a real zero.
* No collapsed "influence" or "contagion" score. Reach, depth, breadth,
  velocity, lag, and lift stay separate fields.
* Every path and episode names its claim type. ``causally_supported`` exists in
  the vocabulary but this computation never emits it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Optional

ALGORITHM = "aether.propagation.exposure_adoption"
ALGORITHM_VERSION = "1.0.0"
SCHEMA_VERSION = "propagation.run.v1"


class ExposureChannel(StrEnum):
    SOCIAL = "social"
    ONCHAIN = "onchain"
    IN_APP = "in_app"
    RELATIONSHIP = "relationship"


class ClaimType(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    CAUSALLY_SUPPORTED = "causally_supported"  # reserved; never emitted here


class EpisodeClassification(StrEnum):
    ORGANIC = "organic"
    VIRAL = "viral"
    COORDINATED = "coordinated"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True)
class PropagationQuery:
    """A bounded, tenant-scoped propagation request."""

    tenant_id: str
    window_start: str
    window_end: str
    instrument_keys: tuple[str, ...] = ()
    channels: tuple[ExposureChannel, ...] = tuple(ExposureChannel)
    exposure_window_seconds: int = 72 * 3600
    max_hops: int = 4
    # Defaults mirror pattern discovery's DetectorConfig so lockstep and lift
    # mean the same thing in both places.
    lockstep_window_seconds: int = 60
    lockstep_min_entities: int = 5
    viral_lift_threshold: float = 2.0
    min_exposed_for_baseline: int = 3
    as_of: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id is required")
        if self.exposure_window_seconds <= 0:
            raise ValueError("exposure_window_seconds must be positive")
        if not 1 <= self.max_hops <= 16:
            raise ValueError("max_hops must be within [1, 16]")


@dataclass(frozen=True)
class AdoptionEvent:
    """A subject's first position in an instrument (first flat -> open epoch)."""

    tenant_id: str
    subject_id: str
    instrument_key: str
    side: str
    adopted_at: str
    venue: str
    account_ref: str
    canonical_market_id: str
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExposureRef:
    """Evidence that ``to_subject`` could have observed ``from_subject``."""

    exposure_id: str
    tenant_id: str
    from_subject: str
    to_subject: str
    channel: ExposureChannel
    predicate: str
    observed_at: Optional[str]
    valid_to: Optional[str] = None
    evidence_refs: tuple[str, ...] = ()
    graph_edge: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class PropagationHop:
    from_subject: str
    to_subject: str
    exposure_id: str
    channel: ExposureChannel
    predicate: str
    lag_seconds: int
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class InfluenceAssessment:
    """Coverage summary from ``decompose_influence_propagation`` (no values)."""

    decision: str
    propagation_certified: bool
    available_component_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    algorithm: str
    version: str


@dataclass(frozen=True)
class PropagationPath:
    path_id: str
    seed_subject: str
    target_subject: str
    hops: tuple[PropagationHop, ...]
    depth: int
    certified_depth: int
    claim_type: ClaimType
    influence: Optional[InfluenceAssessment] = None


@dataclass(frozen=True)
class EpisodeMetrics:
    adopters: int
    exposed_adopters: int
    independent_adopters: int
    propagation_radius: Optional[int]
    certified_radius: Optional[int]
    max_breadth: Optional[int]
    velocity_per_hour: Optional[float]
    median_lag_seconds: Optional[int]
    repeated_exposure_adopters: int
    channels: dict[str, int] = field(default_factory=dict)
    unknown_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class BaselineComparison:
    population: int
    exposed: int
    exposed_adopters: int
    unexposed: int
    unexposed_adopters: int
    exposed_rate: Optional[float]
    unexposed_rate: Optional[float]
    lift: Optional[float]
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CoordinationSignal:
    lockstep_groups: tuple[tuple[str, ...], ...]
    shared_funding_pairs: tuple[tuple[str, str], ...]
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiffusionEpisode:
    episode_id: str
    tenant_id: str
    instrument_key: str
    side: str
    seed_subject: str
    started_at: str
    ended_at: str
    classification: EpisodeClassification
    claim_type: ClaimType
    classification_reasons: tuple[str, ...]
    metrics: EpisodeMetrics
    baseline: BaselineComparison
    coordination: CoordinationSignal
    paths: tuple[PropagationPath, ...]
    adopters: tuple[AdoptionEvent, ...]


@dataclass(frozen=True)
class PropagationRun:
    run_id: str
    tenant_id: str
    query: PropagationQuery
    computed_at: str
    episodes: tuple[DiffusionEpisode, ...]
    input_digest: str
    limitations: tuple[str, ...]
    algorithm: str = ALGORITHM
    algorithm_version: str = ALGORITHM_VERSION
    schema_version: str = SCHEMA_VERSION
    execution_by_aether: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _plain(asdict(self))


def _plain(value: Any) -> Any:
    """Recursively convert enums/tuples into JSON-safe values."""
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


__all__ = [
    "ALGORITHM",
    "ALGORITHM_VERSION",
    "SCHEMA_VERSION",
    "AdoptionEvent",
    "BaselineComparison",
    "ClaimType",
    "CoordinationSignal",
    "DiffusionEpisode",
    "EpisodeClassification",
    "EpisodeMetrics",
    "ExposureChannel",
    "ExposureRef",
    "InfluenceAssessment",
    "PropagationHop",
    "PropagationPath",
    "PropagationQuery",
    "PropagationRun",
]
