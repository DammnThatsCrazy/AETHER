"""Hand-authored comparison workbench models.

TS twins: the ``ComparisonSubject``, ``BaselineSpec``, ``ComparisonDefinition``,
``ComparisonRun``, and ``ComparisonFinding`` interfaces in
``packages/shared/comparison-contract.ts`` (emitted by
``scripts/generate_platform_contracts.py``). The vocabulary tuples live in
``services.intelligence.comparison.generated_vocabulary`` — regenerate, never
edit. Field-level parity is enforced by
``tests/contracts/test_comparison_contract_parity.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ComparisonSubject(BaseModel):
    """One side of a comparison (entity, cohort, or scenario reference)."""

    model_config = ConfigDict(extra="forbid")

    subject_type: str
    subject_id: str
    tenant_id: Optional[str] = None
    label: Optional[str] = None
    as_of: Optional[datetime] = None


class BaselineSpec(BaseModel):
    """How the baseline side of a comparison is resolved."""

    model_config = ConfigDict(extra="forbid")

    baseline_type: str
    subject: Optional[ComparisonSubject] = None
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    rolling_window_days: Optional[int] = None
    cohort_definition_id: Optional[str] = None
    policy_id: Optional[str] = None
    scenario_id: Optional[str] = None


class ComparisonDefinition(BaseModel):
    """Saved definition of a comparison (subject vs baseline over dimensions)."""

    model_config = ConfigDict(extra="forbid")

    definition_id: str
    tenant_id: str
    name: Optional[str] = None
    mode: str
    subject: ComparisonSubject
    baseline: BaselineSpec
    dimensions: Optional[list[str]] = None
    temporal_mode: Optional[str] = None
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None
    schema_version: Optional[str] = None


class ComparisonRun(BaseModel):
    """One execution of a comparison definition."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    definition_id: str
    tenant_id: str
    state: str
    requested_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    as_of: Optional[datetime] = None
    graph_watermark: Optional[str] = None
    alignment_outcome: Optional[str] = None
    finding_count: Optional[int] = None
    degraded_reason: Optional[str] = None
    error_code: Optional[str] = None
    schema_version: Optional[str] = None


class ComparisonFinding(BaseModel):
    """One materiality-scored difference surfaced by a comparison run."""

    model_config = ConfigDict(extra="forbid")

    id: str
    comparison_run_id: str
    tenant_id: str
    finding_type: str
    title: Optional[str] = None
    narrative: Optional[str] = None
    subject_refs: Optional[list[str]] = None
    dimension: Optional[str] = None
    metric: Optional[str] = None
    observed_value: Optional[float] = None
    baseline_value: Optional[float] = None
    delta: Optional[float] = None
    normalized_delta: Optional[float] = None
    direction: Optional[str] = None
    severity: Optional[str] = None
    materiality: Optional[float] = None
    confidence: Optional[float] = None
    evidence_status: Optional[str] = None
    reconciliation_state: Optional[str] = None
    first_observed_at: Optional[datetime] = None
    last_observed_at: Optional[datetime] = None
    persistence: Optional[float] = None
    affected_entity_count: Optional[int] = None
    economic_impact: Optional[float] = None
    risk_impact: Optional[float] = None
    policy_impact: Optional[float] = None
    recommended_disposition: Optional[str] = None
    recommendation_id: Optional[str] = None
    investigation_id: Optional[str] = None
    suppression_reason: Optional[str] = None


__all__ = [
    "ComparisonSubject",
    "BaselineSpec",
    "ComparisonDefinition",
    "ComparisonRun",
    "ComparisonFinding",
]
