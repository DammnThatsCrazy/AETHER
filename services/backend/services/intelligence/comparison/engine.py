"""Comparison run orchestration across the 12 registry run states.

The engine executes one ``ComparisonRun`` through its lifecycle::

    queued → resolving → collecting → aligning → computing → scoring
           → completed | completed_degraded | suppressed | failed
    (cancelled / expired are entered from the control plane or on stale runs)

Data-truth preflight is the load-bearing invariant: missing data is NEVER
equality. Every run records a per-dimension, per-side data-truth entry; a
dimension that is empty on both sides yields an explicit REFUSAL (typed
reason + fact-linkage states) — never a finding of "no difference". A run
whose every dimension refuses completes as ``suppressed``, not ``completed``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.common.common import BadRequestError, NotFoundError, utc_now
from shared.logger.logger import get_logger, metrics
from shared.temporal import ensure_aware_utc

from services.intelligence.comparison.alignment import (
    AlignmentDecision,
    align_dimension,
    overall_alignment,
)
from services.intelligence.comparison.baselines import (
    BaselineResolution,
    BaselineResolver,
)
from services.intelligence.comparison.collection import (
    AnalyticsDimensionCollector,
    DimensionObservations,
    validate_dimensions,
)
from services.intelligence.comparison.contracts import ComparisonDefinition
from services.intelligence.comparison.findings import FindingRecord, FindingsService
from services.intelligence.comparison.generated_vocabulary import (
    BASELINE_TYPES,
    COMPARISON_MODES,
    COMPARISON_RUN_STATES,
)
from services.intelligence.comparison.materiality import score_materiality
from services.intelligence.comparison.store import (
    ComparisonDefinitionRepository,
    ComparisonRunRepository,
)
from services.intelligence.comparison.watchlists import WatchlistRepository

logger = get_logger("aether.intelligence.comparison.engine")

# Legal state transitions — the ONLY way a run changes state.
RUN_STATE_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"resolving", "cancelled", "expired", "failed"}),
    "resolving": frozenset({"collecting", "failed", "cancelled"}),
    "collecting": frozenset({"aligning", "suppressed", "failed", "cancelled"}),
    "aligning": frozenset({"computing", "suppressed", "failed", "cancelled"}),
    "computing": frozenset({"scoring", "failed", "cancelled"}),
    "scoring": frozenset({"completed", "completed_degraded", "failed"}),
    "completed": frozenset(),
    "completed_degraded": frozenset(),
    "suppressed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "expired": frozenset(),
}

TERMINAL_RUN_STATES: frozenset[str] = frozenset(
    s for s, targets in RUN_STATE_TRANSITIONS.items() if not targets
)

# Which baseline types each registry mode accepts.
MODE_BASELINE_COMPATIBILITY: dict[str, frozenset[str]] = {
    "entity_vs_entity": frozenset({"entity", "manual"}),
    "entity_vs_history": frozenset({"historical", "rolling_history"}),
    "entity_vs_cohort": frozenset({"cohort"}),
    "entity_vs_expected": frozenset({"predicted", "policy", "manual"}),
    "cohort_vs_cohort": frozenset({"cohort", "manual"}),
    "scenario_vs_current": frozenset({"scenario"}),
}

# Baseline type → (evidence basis, causal-claim level) for produced findings.
# Ceilings in findings.EVIDENCE_CLAIM_CEILING make over-claiming impossible.
BASELINE_EVIDENCE: dict[str, tuple[str, str]] = {
    "entity": ("direct_observation", "observed"),
    "historical": ("direct_observation", "observed"),
    "rolling_history": ("direct_observation", "observed"),
    "cohort": ("statistical_correlation", "correlated"),
    "policy": ("direct_observation", "observed"),
    "predicted": ("model_inference", "inferred"),
    "manual": ("direct_observation", "observed"),
    "scenario": ("counterfactual_scenario", "counterfactual_estimate"),
}

# A normalized delta below this is not a finding-worthy difference.
DEFAULT_DELTA_THRESHOLD = 0.10

# Runs untouched for this long are expired instead of executed.
RUN_EXPIRY_HOURS = 24

_ALIGNMENT_CONFIDENCE = {
    "aligned": 0.9,
    "aligned_after_conversion": 0.75,
    "partially_aligned": 0.6,
}


class DataTruthEntry(BaseModel):
    """Per-dimension preflight record: what each side truly has."""

    model_config = ConfigDict(extra="forbid")

    dimension: str
    subject_state: str  # ready | empty | uncollectable
    baseline_state: str
    subject_observations: int = 0
    baseline_observations: int = 0
    subject_fact_linkage: str
    baseline_fact_linkage: str
    decision: str  # "compare" | "refuse"
    refusal_reason: Optional[str] = None


def _side_state(obs: DimensionObservations) -> tuple[str, str]:
    """(data state, fact-linkage state) for one side of one dimension."""
    if not obs.collectable:
        return "uncollectable", "suppressed"
    if obs.is_empty:
        return "empty", "pending"
    return "ready", "deterministically_linked"


def preflight_dimension(
    subject: DimensionObservations, baseline: DimensionObservations
) -> DataTruthEntry:
    """Decide, per dimension, whether comparing is honest at all."""
    s_state, s_link = _side_state(subject)
    b_state, b_link = _side_state(baseline)

    decision, reason = "compare", None
    if s_state == "uncollectable" or b_state == "uncollectable":
        decision = "refuse"
        reason = "dimension_has_no_observation_source"
    elif s_state == "empty" and b_state == "empty":
        # THE invariant: empty vs empty is a refusal, never "no difference".
        decision = "refuse"
        reason = "empty_vs_empty_no_evidence_on_either_side"

    return DataTruthEntry(
        dimension=subject.dimension,
        subject_state=s_state,
        baseline_state=b_state,
        subject_observations=subject.observation_count,
        baseline_observations=baseline.observation_count,
        subject_fact_linkage=s_link,
        baseline_fact_linkage=b_link,
        decision=decision,
        refusal_reason=reason,
    )


def validate_definition(definition: ComparisonDefinition) -> None:
    """Mode, baseline-type compatibility, and dimension vocabulary checks."""
    if definition.mode not in COMPARISON_MODES:
        raise BadRequestError(
            f"Unknown comparison mode {definition.mode!r}; "
            f"expected one of {list(COMPARISON_MODES)}"
        )
    if definition.baseline.baseline_type not in BASELINE_TYPES:
        raise BadRequestError(
            f"Unknown baseline type {definition.baseline.baseline_type!r}"
        )
    allowed = MODE_BASELINE_COMPATIBILITY[definition.mode]
    if definition.baseline.baseline_type not in allowed:
        raise BadRequestError(
            f"Mode {definition.mode!r} does not accept baseline type "
            f"{definition.baseline.baseline_type!r} (allowed: {sorted(allowed)})"
        )
    if definition.dimensions:
        validate_dimensions(definition.dimensions)


class ComparisonEngine:
    """Executes comparison runs on stored definitions."""

    def __init__(
        self,
        collector: AnalyticsDimensionCollector,
        *,
        definitions: Optional[ComparisonDefinitionRepository] = None,
        runs: Optional[ComparisonRunRepository] = None,
        findings: Optional[FindingsService] = None,
        watchlists: Optional[WatchlistRepository] = None,
        baseline_resolver: Optional[BaselineResolver] = None,
        delta_threshold: float = DEFAULT_DELTA_THRESHOLD,
    ) -> None:
        self._collector = collector
        self._definitions = definitions or ComparisonDefinitionRepository()
        self._runs = runs or ComparisonRunRepository()
        self._findings = findings or FindingsService()
        self._watchlists = watchlists or WatchlistRepository()
        self._resolver = baseline_resolver or BaselineResolver(collector)
        self._delta_threshold = delta_threshold

    # ── Run lifecycle ────────────────────────────────────────────────────

    async def create_run(
        self, tenant_id: str, definition_id: str, *, as_of: Optional[datetime] = None
    ) -> dict[str, Any]:
        definition = await self._load_definition(tenant_id, definition_id)
        run_id = str(uuid.uuid4())
        run = {
            "run_id": run_id,
            "definition_id": definition.definition_id,
            "tenant_id": tenant_id,
            "state": "queued",
            "requested_at": utc_now().isoformat(),
            "as_of": ensure_aware_utc(as_of).isoformat() if as_of else None,
            "state_history": [{"state": "queued", "at": utc_now().isoformat()}],
            "schema_version": "1",
        }
        return await self._runs.upsert_scoped(tenant_id, run_id, run)

    async def _transition(
        self, tenant_id: str, run: dict[str, Any], new_state: str, **extra: Any
    ) -> dict[str, Any]:
        current = run["state"]
        if new_state not in COMPARISON_RUN_STATES:
            raise ValueError(f"Not a registry run state: {new_state!r}")
        if new_state not in RUN_STATE_TRANSITIONS[current]:
            raise ValueError(f"Illegal run transition {current!r} → {new_state!r}")
        patch = {
            "state": new_state,
            "state_history": [
                *run.get("state_history", []),
                {"state": new_state, "at": utc_now().isoformat()},
            ],
            **extra,
        }
        updated = await self._runs.update_scoped(tenant_id, run["run_id"], patch)
        if updated is None:
            raise NotFoundError("comparison run")
        return updated

    async def execute_run(self, tenant_id: str, run_id: str) -> dict[str, Any]:
        """Drive one queued run to a terminal state. Returns the final record."""
        run = await self._runs.get_scoped(tenant_id, run_id)
        if run is None:
            raise NotFoundError("comparison run")
        if run["state"] in TERMINAL_RUN_STATES:
            return run  # idempotent re-delivery
        if run["state"] != "queued":
            raise ValueError(f"Run {run_id!r} is {run['state']!r}, not queued")

        requested_at = _parse_dt(run.get("requested_at"))
        if requested_at and utc_now() - requested_at > timedelta(hours=RUN_EXPIRY_HOURS):
            return await self._transition(
                tenant_id, run, "expired",
                degraded_reason=f"run_older_than_{RUN_EXPIRY_HOURS}h_at_pickup",
            )

        metrics.increment("comparison_runs_total", labels={"phase": "started"})
        try:
            return await self._execute(tenant_id, run)
        except Exception as exc:  # noqa: BLE001 — terminal state must be recorded
            logger.exception("comparison_run_failed", extra={"run_id": run_id})
            metrics.increment("comparison_runs_total", labels={"phase": "failed"})
            run = await self._runs.get_scoped(tenant_id, run_id) or run
            if run["state"] in TERMINAL_RUN_STATES:
                return run
            return await self._transition(
                tenant_id, run, "failed",
                error_code=type(exc).__name__,
                degraded_reason=str(exc)[:500],
                completed_at=utc_now().isoformat(),
            )

    # ── Pipeline stages ──────────────────────────────────────────────────

    async def _execute(self, tenant_id: str, run: dict[str, Any]) -> dict[str, Any]:
        definition = await self._load_definition(tenant_id, run["definition_id"])
        validate_definition(definition)
        dimensions = definition.dimensions or ["behavior"]
        as_of = _parse_dt(run.get("as_of")) or utc_now()

        # resolving — baseline resolution (versioned, typed).
        run = await self._transition(tenant_id, run, "resolving")
        resolution = await self._resolver.resolve(
            tenant_id, definition.baseline, definition.subject, dimensions, as_of=as_of
        )
        if not resolution.resolved:
            metrics.increment("comparison_runs_total", labels={"phase": "failed"})
            return await self._transition(
                tenant_id, run, "failed",
                error_code="baseline_unresolved",
                degraded_reason=resolution.reason,
                baseline_version=resolution.baseline_version,
                completed_at=utc_now().isoformat(),
            )

        # collecting — subject observations + data-truth preflight.
        run = await self._transition(
            tenant_id, run, "collecting", baseline_version=resolution.baseline_version
        )
        window_start = as_of - timedelta(days=30)
        subject_obs: dict[str, DimensionObservations] = {}
        for dimension in dimensions:
            subject_obs[dimension] = await self._collector.collect(
                tenant_id, definition.subject, dimension,
                window_start=window_start, window_end=as_of,
            )

        data_truth = [
            preflight_dimension(subject_obs[d], resolution.observations[d])
            for d in dimensions
        ]
        refusals = [e for e in data_truth if e.decision == "refuse"]
        for entry in refusals:
            metrics.increment(
                "comparison_refusals_total",
                labels={"reason": entry.refusal_reason or "unknown"},
            )
        truth_payload = {"data_truth": [e.model_dump(mode="json") for e in data_truth]}
        if len(refusals) == len(data_truth):
            # Nothing is honestly comparable → the run is suppressed with the
            # full refusal record. This is NOT a "no differences" result.
            metrics.increment("comparison_runs_total", labels={"phase": "suppressed"})
            return await self._transition(
                tenant_id, run, "suppressed",
                degraded_reason="all_dimensions_refused_by_data_truth_preflight",
                finding_count=0,
                completed_at=utc_now().isoformat(),
                **truth_payload,
            )

        # aligning — typed outcomes only.
        run = await self._transition(tenant_id, run, "aligning", **truth_payload)
        comparable_dims = [e.dimension for e in data_truth if e.decision == "compare"]
        decisions: list[AlignmentDecision] = [
            align_dimension(subject_obs[d], resolution.observations[d])
            for d in comparable_dims
        ]
        alignment_payload = {
            "alignment_decisions": [d.model_dump(mode="json") for d in decisions],
        }
        computable = [d for d in decisions if d.comparable]
        if not computable:
            metrics.increment("comparison_runs_total", labels={"phase": "suppressed"})
            return await self._transition(
                tenant_id, run, "suppressed",
                degraded_reason="no_dimension_could_be_aligned",
                alignment_outcome=overall_alignment(decisions),
                finding_count=0,
                completed_at=utc_now().isoformat(),
                **alignment_payload,
            )

        # computing — metric deltas on aligned pairs only.
        run = await self._transition(tenant_id, run, "computing", **alignment_payload)
        deltas = self._compute_deltas(computable)

        # scoring — materiality + findings (through watchlist noise controls).
        run = await self._transition(tenant_id, run, "scoring")
        watchlists = await self._watchlists.list_for_tenant(tenant_id)
        evidence_basis, causal_claim = BASELINE_EVIDENCE[definition.baseline.baseline_type]
        finding_count = 0
        for delta in deltas:
            if abs(delta["normalized_delta"]) < self._delta_threshold:
                continue
            finding = self._build_finding(
                run, definition, delta, resolution,
                subject_obs[delta["dimension"]],
                evidence_basis=evidence_basis,
                causal_claim=causal_claim,
            )
            await self._findings.create(
                finding, definition_id=definition.definition_id, watchlists=watchlists
            )
            finding_count += 1

        degraded = bool(refusals) or any(not d.comparable for d in decisions)
        final_state = "completed_degraded" if degraded else "completed"
        metrics.increment("comparison_runs_total", labels={"phase": final_state})
        return await self._transition(
            tenant_id, run, final_state,
            alignment_outcome=overall_alignment(decisions),
            finding_count=finding_count,
            degraded_reason=(
                "some_dimensions_refused_or_unaligned" if degraded else None
            ),
            completed_at=utc_now().isoformat(),
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    def _compute_deltas(self, decisions: list[AlignmentDecision]) -> list[dict[str, Any]]:
        deltas: list[dict[str, Any]] = []
        for decision in decisions:
            for pair in decision.pairs:
                baseline_magnitude = max(abs(pair.baseline_value), 1e-9)
                delta = pair.subject_value - pair.baseline_value
                # Clamp: against a zero/near-zero baseline the ratio is
                # unbounded; ±100 (i.e. 10000%) keeps it honest and finite.
                normalized = max(min(delta / baseline_magnitude, 100.0), -100.0)
                deltas.append(
                    {
                        "dimension": decision.dimension,
                        "metric": pair.name,
                        "unit": pair.unit,
                        "observed_value": pair.subject_value,
                        "baseline_value": pair.baseline_value,
                        "delta": delta,
                        "normalized_delta": normalized,
                        "alignment_outcome": decision.outcome,
                    }
                )
        return deltas

    def _build_finding(
        self,
        run: dict[str, Any],
        definition: ComparisonDefinition,
        delta: dict[str, Any],
        resolution: BaselineResolution,
        subject_obs: DimensionObservations,
        *,
        evidence_basis: str,
        causal_claim: str,
    ) -> FindingRecord:
        normalized = delta["normalized_delta"]
        deviation = min(abs(normalized), 1.0)
        confidence = _ALIGNMENT_CONFIDENCE.get(delta["alignment_outcome"], 0.5)
        if resolution.statistical_quality is not None:
            confidence *= max(min(resolution.statistical_quality, 1.0), 0.0)

        components: dict[str, float] = {
            "confidence": confidence,
            "data_quality": min(subject_obs.observation_count / 30.0, 1.0),
        }
        if definition.baseline.baseline_type == "cohort":
            components["cohort_deviation"] = deviation
        else:
            components["historical_deviation"] = deviation
        if subject_obs.window_end is not None:
            age_days = max(
                (utc_now() - ensure_aware_utc(subject_obs.window_end)).total_seconds()
                / 86400.0,
                0.0,
            )
            components["freshness"] = max(1.0 - age_days / 30.0, 0.0)

        result = score_materiality(components)
        direction = "increase" if delta["delta"] > 0 else "decrease"
        now = utc_now()
        return FindingRecord(
            id=str(uuid.uuid4()),
            comparison_run_id=run["run_id"],
            tenant_id=run["tenant_id"],
            finding_type="metric_deviation",
            title=(
                f"{delta['dimension']}.{delta['metric']} {direction} vs "
                f"{definition.baseline.baseline_type} baseline"
            ),
            narrative=(
                f"Observed {delta['observed_value']:.4g} {delta['unit']} vs baseline "
                f"{delta['baseline_value']:.4g} {delta['unit']} "
                f"(normalized delta {normalized:+.2%}). Evidence basis: "
                f"{evidence_basis}; this supports at most the "
                f"{causal_claim!r} causal-claim level."
            ),
            subject_refs=[definition.subject.subject_id],
            dimension=delta["dimension"],
            metric=delta["metric"],
            observed_value=delta["observed_value"],
            baseline_value=delta["baseline_value"],
            delta=delta["delta"],
            normalized_delta=normalized,
            direction=direction,
            severity=result.severity,
            materiality=result.score,
            confidence=confidence,
            evidence_status="deterministically_linked",
            first_observed_at=now,
            last_observed_at=now,
            recommended_disposition=_recommend_disposition(result.severity),
            causal_claim=causal_claim,
            evidence_basis=evidence_basis,
            fact_linkage="deterministically_linked"
            if resolution.source == "analytics_events"
            else "probabilistically_linked",
        )

    async def _load_definition(
        self, tenant_id: str, definition_id: str
    ) -> ComparisonDefinition:
        record = await self._definitions.get_scoped(tenant_id, definition_id)
        if record is None:
            raise NotFoundError("comparison definition")
        return ComparisonDefinition(**record)


def _recommend_disposition(severity: str) -> str:
    return {
        "info": "informational",
        "low": "monitor",
        "medium": "monitor",
        "high": "investigate",
        "critical": "investigate",
    }[severity]


def _parse_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return ensure_aware_utc(value)
    if not value:
        return None
    try:
        from shared.temporal import parse_instant_strict

        return parse_instant_strict(str(value))
    except Exception:
        return None


__all__ = [
    "BASELINE_EVIDENCE",
    "DEFAULT_DELTA_THRESHOLD",
    "MODE_BASELINE_COMPATIBILITY",
    "RUN_STATE_TRANSITIONS",
    "TERMINAL_RUN_STATES",
    "ComparisonEngine",
    "DataTruthEntry",
    "preflight_dimension",
    "validate_definition",
]
