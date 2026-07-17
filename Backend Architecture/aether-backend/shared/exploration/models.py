"""Exploration Fabric contract models (Python twins of exploration-contract.ts).

Field-for-field mirrors, parity-tested by
``tests/contracts/test_exploration_contract_parity.py``. Every response
envelope reports one applicability entry per requested filter — surfaces can
refuse or translate a filter, but never silently drop one.
"""

from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts_models.filters import FilterGroup
from shared.dimension_state import DimensionEnvelope

FilterDisposition = Literal[
    "applied",
    "translated",
    "unsupported",
    "suppressed",
    "not_applicable",
]

FILTER_DISPOSITIONS: tuple[str, ...] = (
    "applied",
    "translated",
    "unsupported",
    "suppressed",
    "not_applicable",
)

ExplorationView = Literal["graph", "table", "map", "timeline", "flow", "comparison"]

EXPLORATION_VIEWS: tuple[str, ...] = (
    "graph",
    "table",
    "map",
    "timeline",
    "flow",
    "comparison",
)

ExplorationTemporalMode = Literal["window", "as_of", "compare", "relative"]

EXPLORATION_TEMPORAL_MODES: tuple[str, ...] = ("window", "as_of", "compare", "relative")

ExplorationTemporalField = Literal[
    "occurred_at", "observed_at", "ingested_at", "valid_time", "computed_at"
]

EXPLORATION_TEMPORAL_FIELDS: tuple[str, ...] = (
    "occurred_at",
    "observed_at",
    "ingested_at",
    "valid_time",
    "computed_at",
)

EXPLORATION_CONTRACT_VERSION = "1"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExplorationAnchor(_Model):
    kind: str
    id: str


class TemporalSelection(_Model):
    mode: ExplorationTemporalMode
    field: ExplorationTemporalField
    range: Optional[dict[str, Any]] = None
    as_of: Optional[str] = None
    compare_to: Optional[str] = None
    timezone: str
    authority: Optional[str] = None


class GraphConstraints(_Model):
    layers: Optional[list[str]] = None
    edge_types: Optional[list[str]] = None
    direction: Optional[Literal["in", "out", "both"]] = None
    depth: Optional[int] = None
    traversal_mode: Optional[Literal["shortest", "strongest", "k_shortest"]] = None
    k: Optional[int] = None


class ExplorationSort(_Model):
    field: str
    direction: Literal["asc", "desc"]


class PresentationSpec(_Model):
    view: ExplorationView
    group_by: Optional[list[str]] = None
    sort: Optional[list[ExplorationSort]] = None
    columns: Optional[list[str]] = None
    page_size: Optional[int] = None


class SelectionSet(_Model):
    focused: Optional[ExplorationAnchor] = None
    selected: Optional[list[ExplorationAnchor]] = None


class TruthRequirements(_Model):
    minimum_confidence: Optional[float] = None
    allowed_dimension_states: Optional[list[str]] = None
    include_evidence: Optional[bool] = None
    include_provenance: Optional[bool] = None


class ExplorationScope(_Model):
    tenant_id: str
    surface: str


class ExplorationContextV1(_Model):
    """The versioned, shareable exploration state (composes FilterGroup)."""

    version: Literal["1"] = "1"
    scope: ExplorationScope
    anchors: Optional[list[ExplorationAnchor]] = None
    population: Optional[FilterGroup] = None
    temporal: TemporalSelection
    graph: Optional[GraphConstraints] = None
    dimensions: Optional[list[str]] = None
    overlays: Optional[list[str]] = None
    presentation: Optional[PresentationSpec] = None
    selection: Optional[SelectionSet] = None
    truth: Optional[TruthRequirements] = None


class FilterApplicabilityEntry(_Model):
    field: str
    disposition: FilterDisposition
    reason: Optional[str] = None
    translated_to: Optional[str] = None


class ApplicabilityReport(_Model):
    """One entry per requested filter — completeness is the contract."""

    entries: list[FilterApplicabilityEntry] = Field(default_factory=list)


class ExplorationCompleteness(_Model):
    complete: bool
    sampled: bool = False
    truncated: bool = False
    truncation_reason: Optional[str] = None
    coverage_percent: Optional[float] = None


class ExplorationTruth(_Model):
    overall_state: str
    dimensions: list[DimensionEnvelope] = Field(default_factory=list)
    freshness_watermark: Optional[str] = None


class ExplorationExecution(_Model):
    duration_ms: float
    cache_status: Literal["hit", "miss", "bypass"]
    adapters: list[str] = Field(default_factory=list)


class ExplorationPagination(_Model):
    cursor: Optional[str] = None
    has_more: bool = False
    total_estimate: Optional[int] = None


class ExplorationResultEnvelope(_Model):
    """The canonical envelope every exploration result returns."""

    contract_version: str = EXPLORATION_CONTRACT_VERSION
    query_id: str
    normalized_context: ExplorationContextV1
    data: Any = None
    pagination: Optional[ExplorationPagination] = None
    completeness: ExplorationCompleteness
    truth: ExplorationTruth
    applicability: ApplicabilityReport
    execution: ExplorationExecution
    warnings: list[str] = Field(default_factory=list)


class ContextLink(_Model):
    """A context-preserving navigation edge to another surface."""

    to: str
    context: ExplorationContextV1
    focus: Optional[ExplorationAnchor] = None


__all__ = [
    "EXPLORATION_CONTRACT_VERSION",
    "FilterDisposition",
    "FILTER_DISPOSITIONS",
    "ExplorationView",
    "EXPLORATION_VIEWS",
    "ExplorationTemporalMode",
    "EXPLORATION_TEMPORAL_MODES",
    "ExplorationTemporalField",
    "EXPLORATION_TEMPORAL_FIELDS",
    "ExplorationAnchor",
    "TemporalSelection",
    "GraphConstraints",
    "ExplorationSort",
    "PresentationSpec",
    "SelectionSet",
    "TruthRequirements",
    "ExplorationScope",
    "ExplorationContextV1",
    "FilterApplicabilityEntry",
    "ApplicabilityReport",
    "ExplorationCompleteness",
    "ExplorationTruth",
    "ExplorationExecution",
    "ExplorationPagination",
    "ExplorationResultEnvelope",
    "ContextLink",
    "Union",
]
