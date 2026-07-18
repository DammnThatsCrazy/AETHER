"""Read-only counterfactual scenarios for the comparison workbench.

A scenario answers "what would this comparison look like if the baseline
were X?" by recomputing alignment, deltas, and materiality with substituted
baseline parameters. It NEVER writes anything: no runs, no findings, no
baselines are persisted — the result exists only in the response. Every
scenario delta is labeled ``counterfactual_estimate`` on the causal-claim
ladder; a scenario can never mint an "observed" difference.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.common.common import utc_now

from services.intelligence.comparison.alignment import (
    align_dimension,
    overall_alignment,
)
from services.intelligence.comparison.baselines import BaselineResolver
from services.intelligence.comparison.collection import (
    AnalyticsDimensionCollector,
    DimensionObservations,
)
from services.intelligence.comparison.contracts import BaselineSpec, ComparisonDefinition
from services.intelligence.comparison.engine import (
    DataTruthEntry,
    preflight_dimension,
    validate_definition,
)
from services.intelligence.comparison.materiality import score_materiality

SCENARIO_CAUSAL_CLAIM = "counterfactual_estimate"
SCENARIO_EVIDENCE_BASIS = "counterfactual_scenario"


class ScenarioDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str
    metric: str
    unit: str
    observed_value: float
    scenario_baseline_value: float
    delta: float
    normalized_delta: float
    materiality: float
    severity: str
    causal_claim: str = SCENARIO_CAUSAL_CLAIM


class ScenarioResult(BaseModel):
    """The full counterfactual readout — computed, returned, never stored."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: Optional[str] = None
    definition_id: str
    tenant_id: str
    baseline_version: str
    read_only: bool = True
    causal_claim: str = SCENARIO_CAUSAL_CLAIM
    evidence_basis: str = SCENARIO_EVIDENCE_BASIS
    data_truth: list[DataTruthEntry] = Field(default_factory=list)
    alignment_outcome: Optional[str] = None
    deltas: list[ScenarioDelta] = Field(default_factory=list)
    refusal_reasons: list[str] = Field(default_factory=list)
    computed_at: datetime = Field(default_factory=utc_now)


class ScenarioRunner:
    """Computes counterfactuals from live reads + inline parameters only."""

    def __init__(
        self,
        collector: AnalyticsDimensionCollector,
        resolver: Optional[BaselineResolver] = None,
    ) -> None:
        self._collector = collector
        self._resolver = resolver or BaselineResolver(collector)

    async def run(
        self,
        tenant_id: str,
        definition: ComparisonDefinition,
        scenario_params: dict[str, Any],
        *,
        scenario_id: Optional[str] = None,
        as_of: Optional[datetime] = None,
    ) -> ScenarioResult:
        """Recompute the comparison with the substituted baseline parameters.

        ``scenario_params`` maps dimension → list of metric dicts
        (``{"name", "value", "unit"}``) that REPLACE the definition's
        baseline for this computation only.
        """
        scenario_definition = definition.model_copy(
            update={
                "baseline": BaselineSpec(
                    baseline_type="scenario",
                    scenario_id=scenario_id or definition.baseline.scenario_id,
                )
            }
        )
        # Validate against the same rules a durable run would face, with the
        # scenario baseline substituted (mode stays whatever was defined —
        # scenario_vs_current is the canonical mode for this path).
        if definition.mode == "scenario_vs_current":
            validate_definition(scenario_definition)

        dimensions = definition.dimensions or ["behavior"]
        end = as_of or utc_now()
        resolution = await self._resolver.resolve(
            tenant_id,
            scenario_definition.baseline,
            definition.subject,
            dimensions,
            as_of=end,
            scenario_params=scenario_params,
        )
        if not resolution.resolved:
            return ScenarioResult(
                scenario_id=scenario_id,
                definition_id=definition.definition_id,
                tenant_id=tenant_id,
                baseline_version=resolution.baseline_version,
                refusal_reasons=[resolution.reason or "scenario_baseline_unresolved"],
            )

        window_start = end - timedelta(days=30)
        subject_obs: dict[str, DimensionObservations] = {}
        for dimension in dimensions:
            subject_obs[dimension] = await self._collector.collect(
                tenant_id, definition.subject, dimension,
                window_start=window_start, window_end=end,
            )

        data_truth = [
            preflight_dimension(subject_obs[d], resolution.observations[d])
            for d in dimensions
        ]
        refusal_reasons = [
            f"{e.dimension}:{e.refusal_reason}"
            for e in data_truth
            if e.decision == "refuse" and e.refusal_reason
        ]
        comparable = [e.dimension for e in data_truth if e.decision == "compare"]

        decisions = [
            align_dimension(subject_obs[d], resolution.observations[d])
            for d in comparable
        ]
        deltas: list[ScenarioDelta] = []
        for decision in decisions:
            if not decision.comparable:
                refusal_reasons.append(f"{decision.dimension}:{decision.outcome}")
                continue
            for pair in decision.pairs:
                baseline_magnitude = max(abs(pair.baseline_value), 1e-9)
                delta = pair.subject_value - pair.baseline_value
                normalized = delta / baseline_magnitude
                materiality = score_materiality(
                    {
                        # Counterfactuals cap confidence: estimates, not facts.
                        "confidence": 0.5,
                        "historical_deviation": min(abs(normalized), 1.0),
                        "data_quality": min(
                            subject_obs[decision.dimension].observation_count / 30.0, 1.0
                        ),
                    }
                )
                deltas.append(
                    ScenarioDelta(
                        dimension=decision.dimension,
                        metric=pair.name,
                        unit=pair.unit,
                        observed_value=pair.subject_value,
                        scenario_baseline_value=pair.baseline_value,
                        delta=delta,
                        normalized_delta=normalized,
                        materiality=materiality.score,
                        severity=materiality.severity,
                    )
                )

        return ScenarioResult(
            scenario_id=scenario_id,
            definition_id=definition.definition_id,
            tenant_id=tenant_id,
            baseline_version=resolution.baseline_version,
            data_truth=data_truth,
            alignment_outcome=overall_alignment(decisions),
            deltas=deltas,
            refusal_reasons=refusal_reasons,
        )


__all__ = [
    "SCENARIO_CAUSAL_CLAIM",
    "SCENARIO_EVIDENCE_BASIS",
    "ScenarioDelta",
    "ScenarioResult",
    "ScenarioRunner",
]
