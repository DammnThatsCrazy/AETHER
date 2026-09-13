"""Versioned baseline resolution for the comparison engine.

Resolves a ``BaselineSpec`` (one of the 8 registry baseline types) into
per-dimension observations the alignment stage can consume.

Statistical baselines are NOT reimplemented here: ``rolling_history``,
``predicted``, and ``cohort`` delegate to the existing expectations plane
(``services.expectations.baseline_builder.BaselineBuilder``). Stored
``manual``/``policy`` baselines live in a versioned JSONB store. A baseline
that cannot be resolved yields an EXPLICIT unresolved result with a typed
reason — never a fabricated empty baseline.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.common.common import utc_now

from services.expectations.baseline_builder import BaselineBuilder
from services.intelligence.comparison.collection import (
    COLLECTABLE_DIMENSIONS,
    AnalyticsDimensionCollector,
    DimensionObservations,
    MetricValue,
    UNCOLLECTABLE_REASON,
)
from services.intelligence.comparison.contracts import BaselineSpec, ComparisonSubject
from services.intelligence.comparison.generated_vocabulary import BASELINE_TYPES
from services.intelligence.comparison.store import TenantScopedComparisonRepository

DEFAULT_WINDOW_DAYS = 30

# Subject type that references a stored (manual) baseline record.
STORED_BASELINE_SUBJECT_TYPE = "stored_baseline"

# Minimum self-history sample before a statistical projection is trusted at
# all — below this the baseline is explicitly unresolved, never guessed.
MIN_PREDICTION_SAMPLE = 5


class StoredBaselineRepository(TenantScopedComparisonRepository):
    """Versioned manual/policy baseline records (JSONB store, no migrations).

    Record shape::

        {
          "baseline_id": str, "version": int, "kind": "manual" | "policy",
          "metrics": {dimension: [{"name", "value", "unit"}, ...]},
          "created_by": str, "tenant_id": str
        }
    """

    natural_id_key = "record_key"

    def __init__(self) -> None:
        super().__init__("comparison_baselines")

    @staticmethod
    def _key(baseline_id: str, version: int) -> str:
        return f"{baseline_id}@v{version}"

    async def put_version(
        self, tenant_id: str, baseline_id: str, kind: str,
        metrics: dict[str, list[dict[str, Any]]], created_by: str = "",
    ) -> dict[str, Any]:
        latest = await self.latest(tenant_id, baseline_id)
        version = (latest["version"] + 1) if latest else 1
        record = {
            "baseline_id": baseline_id,
            "version": version,
            "kind": kind,
            "metrics": metrics,
            "created_by": created_by,
            "stored_at": utc_now().isoformat(),
        }
        return await self.upsert_scoped(tenant_id, self._key(baseline_id, version), record)

    async def get_version(
        self, tenant_id: str, baseline_id: str, version: int
    ) -> Optional[dict[str, Any]]:
        return await self.get_scoped(tenant_id, self._key(baseline_id, version))

    async def latest(self, tenant_id: str, baseline_id: str) -> Optional[dict[str, Any]]:
        rows = await self.list_scoped(tenant_id, {"baseline_id": baseline_id}, limit=500)
        if not rows:
            return None
        return max(rows, key=lambda r: int(r.get("version", 0)))


class BaselineResolution(BaseModel):
    """Outcome of resolving a BaselineSpec — resolved or explicitly not."""

    model_config = ConfigDict(extra="forbid")

    resolved: bool
    baseline_type: str
    baseline_version: str
    source: str
    reason: Optional[str] = None
    observations: dict[str, DimensionObservations] = Field(default_factory=dict)
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    statistical_quality: Optional[float] = None
    resolved_at: datetime = Field(default_factory=utc_now)


def _unresolved(baseline_type: str, reason: str) -> BaselineResolution:
    return BaselineResolution(
        resolved=False,
        baseline_type=baseline_type,
        baseline_version=_version_hash({"type": baseline_type, "unresolved": reason}),
        source="none",
        reason=reason,
    )


def _version_hash(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    )
    return digest.hexdigest()[:16]


def _spec_fingerprint(spec: BaselineSpec, extra: Optional[dict[str, Any]] = None) -> str:
    return _version_hash({**spec.model_dump(mode="json"), **(extra or {})})


def _rate_observations(
    dimensions: list[str],
    events_per_day: float,
    *,
    sample_size: int,
    source: str,
    window_days: float,
) -> dict[str, DimensionObservations]:
    """Wrap an expectations-plane rate into per-dimension observations.

    The expectations builders summarise overall behaviour, so only the
    dimensions the analytics collector could also observe are populated;
    other dimensions stay honestly uncollectable from this source.
    """
    observations: dict[str, DimensionObservations] = {}
    for dimension in dimensions:
        if dimension not in COLLECTABLE_DIMENSIONS:
            observations[dimension] = DimensionObservations(
                dimension=dimension,
                collectable=False,
                reason=UNCOLLECTABLE_REASON,
                source="none",
            )
            continue
        observations[dimension] = DimensionObservations(
            dimension=dimension,
            collectable=True,
            observation_count=sample_size,
            metrics=[
                MetricValue(
                    name="events_per_day",
                    value=events_per_day,
                    unit="count_per_day",
                    window_days=window_days,
                    provenance=source,
                ),
            ],
            source=source,
            reason=None if sample_size else "no_events_in_window",
        )
    return observations


class BaselineResolver:
    """Resolves the baseline side of a comparison, versioned and typed."""

    def __init__(
        self,
        collector: AnalyticsDimensionCollector,
        stored_baselines: Optional[StoredBaselineRepository] = None,
    ) -> None:
        self._collector = collector
        self._stored = stored_baselines or StoredBaselineRepository()

    async def resolve(
        self,
        tenant_id: str,
        spec: BaselineSpec,
        subject: ComparisonSubject,
        dimensions: list[str],
        *,
        as_of: Optional[datetime] = None,
        scenario_params: Optional[dict[str, Any]] = None,
    ) -> BaselineResolution:
        if spec.baseline_type not in BASELINE_TYPES:
            raise ValueError(f"Unknown baseline type: {spec.baseline_type!r}")
        end = as_of or utc_now()

        if spec.baseline_type == "entity":
            return await self._resolve_entity(tenant_id, spec, dimensions, end)
        if spec.baseline_type == "historical":
            return await self._resolve_historical(tenant_id, spec, subject, dimensions)
        if spec.baseline_type == "rolling_history":
            return await self._resolve_rolling(tenant_id, spec, subject, dimensions, end)
        if spec.baseline_type == "cohort":
            return self._resolve_cohort(tenant_id, spec, dimensions, end)
        if spec.baseline_type == "predicted":
            return await self._resolve_predicted(tenant_id, spec, subject, dimensions, end)
        if spec.baseline_type in ("policy", "manual"):
            return await self._resolve_stored(tenant_id, spec, dimensions)
        # scenario: parameters are supplied inline by the read-only scenario
        # path; a durable run can never resolve one on its own.
        if scenario_params:
            return self._resolve_scenario(spec, dimensions, scenario_params, end)
        return _unresolved(
            "scenario",
            "scenario baselines resolve only through the read-only scenario path "
            "with inline parameters",
        )

    # ── Per-type resolution ──────────────────────────────────────────────

    async def _resolve_entity(
        self, tenant_id: str, spec: BaselineSpec, dimensions: list[str], end: datetime
    ) -> BaselineResolution:
        if spec.subject is None:
            return _unresolved("entity", "entity baseline requires a baseline subject")
        start = end - timedelta(days=DEFAULT_WINDOW_DAYS)
        observations = {
            d: await self._collector.collect(
                tenant_id, spec.subject, d, window_start=start, window_end=end
            )
            for d in dimensions
        }
        return BaselineResolution(
            resolved=True,
            baseline_type="entity",
            baseline_version=_spec_fingerprint(spec, {"end": end}),
            source="analytics_events",
            observations=observations,
            window_start=start,
            window_end=end,
        )

    async def _resolve_historical(
        self,
        tenant_id: str,
        spec: BaselineSpec,
        subject: ComparisonSubject,
        dimensions: list[str],
    ) -> BaselineResolution:
        if spec.window_start is None or spec.window_end is None:
            return _unresolved(
                "historical", "historical baseline requires window_start and window_end"
            )
        if spec.window_end <= spec.window_start:
            return _unresolved("historical", "window_end must be after window_start")
        target = spec.subject or subject
        observations = {
            d: await self._collector.collect(
                tenant_id, target, d,
                window_start=spec.window_start, window_end=spec.window_end,
            )
            for d in dimensions
        }
        return BaselineResolution(
            resolved=True,
            baseline_type="historical",
            baseline_version=_spec_fingerprint(spec),
            source="analytics_events",
            observations=observations,
            window_start=spec.window_start,
            window_end=spec.window_end,
        )

    async def _resolve_rolling(
        self,
        tenant_id: str,
        spec: BaselineSpec,
        subject: ComparisonSubject,
        dimensions: list[str],
        end: datetime,
    ) -> BaselineResolution:
        days = spec.rolling_window_days
        if not days or days < 1:
            return _unresolved(
                "rolling_history", "rolling_history baseline requires rolling_window_days >= 1"
            )
        start = end - timedelta(days=days)
        target = spec.subject or subject
        observations = {
            d: await self._collector.collect(
                tenant_id, target, d, window_start=start, window_end=end
            )
            for d in dimensions
        }
        return BaselineResolution(
            resolved=True,
            baseline_type="rolling_history",
            baseline_version=_spec_fingerprint(spec, {"end": end}),
            source="analytics_events",
            observations=observations,
            window_start=start,
            window_end=end,
        )

    def _resolve_cohort(
        self, tenant_id: str, spec: BaselineSpec, dimensions: list[str], end: datetime
    ) -> BaselineResolution:
        if not spec.cohort_definition_id:
            return _unresolved("cohort", "cohort baseline requires cohort_definition_id")
        # Delegate the statistical cohort profile to the expectations plane.
        peer = BaselineBuilder.build_peer_baseline(
            tenant_id=tenant_id, tier=spec.cohort_definition_id
        )
        events_per_day = peer.avg_rpm * 60 * 24
        observations = _rate_observations(
            dimensions,
            events_per_day,
            sample_size=peer.cohort_size,
            source="expectations.peer_cohort",
            window_days=float(DEFAULT_WINDOW_DAYS),
        )
        return BaselineResolution(
            resolved=True,
            baseline_type="cohort",
            baseline_version=_spec_fingerprint(spec, {"cohort": peer.cohort_id}),
            source="expectations.peer_cohort",
            observations=observations,
            window_end=end,
            statistical_quality=peer.quality,
        )

    async def _resolve_predicted(
        self,
        tenant_id: str,
        spec: BaselineSpec,
        subject: ComparisonSubject,
        dimensions: list[str],
        end: datetime,
    ) -> BaselineResolution:
        # Self-history projection via the expectations statistical builder.
        target = spec.subject or subject
        events = await self._collector._analytics.query_events(
            tenant_id, {"user_id": target.subject_id}, limit=500
        )
        history = [
            {"ts": _epoch(e), "model": e.get("event_type", ""), "batch_size": 1}
            for e in events
            if _epoch(e) is not None
        ]
        if len(history) < MIN_PREDICTION_SAMPLE:
            return _unresolved(
                "predicted",
                f"insufficient self-history for prediction "
                f"({len(history)} < {MIN_PREDICTION_SAMPLE} events)",
            )
        history.sort(key=lambda h: h["ts"])
        actor = BaselineBuilder.build_self_baseline(history)
        events_per_day = actor.usual_rpm * 60 * 24
        observations = _rate_observations(
            dimensions,
            events_per_day,
            sample_size=actor.sample_size,
            source="expectations.self_history_projection",
            window_days=float(DEFAULT_WINDOW_DAYS),
        )
        return BaselineResolution(
            resolved=True,
            baseline_type="predicted",
            baseline_version=_spec_fingerprint(spec, {"end": end}),
            source="expectations.self_history_projection",
            observations=observations,
            window_end=end,
            statistical_quality=actor.quality,
        )

    async def _resolve_stored(
        self, tenant_id: str, spec: BaselineSpec, dimensions: list[str]
    ) -> BaselineResolution:
        baseline_type = spec.baseline_type
        if baseline_type == "policy":
            baseline_id = spec.policy_id
            missing_reason = "policy baseline requires policy_id"
        else:
            baseline_id = (
                spec.subject.subject_id
                if spec.subject and spec.subject.subject_type == STORED_BASELINE_SUBJECT_TYPE
                else None
            )
            missing_reason = (
                "manual baseline requires subject "
                f"{{subject_type: {STORED_BASELINE_SUBJECT_TYPE!r}, subject_id: <baseline_id>}}"
            )
        if not baseline_id:
            return _unresolved(baseline_type, missing_reason)

        record = await self._stored.latest(tenant_id, baseline_id)
        if record is None:
            return _unresolved(
                baseline_type, f"no stored baseline versions for {baseline_id!r}"
            )
        if record.get("kind") != baseline_type:
            return _unresolved(
                baseline_type,
                f"stored baseline {baseline_id!r} has kind {record.get('kind')!r}, "
                f"expected {baseline_type!r}",
            )
        observations = self._stored_observations(
            record, dimensions, source=f"stored_{baseline_type}_baseline"
        )
        return BaselineResolution(
            resolved=True,
            baseline_type=baseline_type,
            baseline_version=f"{baseline_id}@v{record['version']}",
            source=f"stored_{baseline_type}_baseline",
            observations=observations,
        )

    def _resolve_scenario(
        self,
        spec: BaselineSpec,
        dimensions: list[str],
        scenario_params: dict[str, Any],
        end: datetime,
    ) -> BaselineResolution:
        observations: dict[str, DimensionObservations] = {}
        for dimension in dimensions:
            raw = scenario_params.get(dimension)
            if not raw:
                observations[dimension] = DimensionObservations(
                    dimension=dimension,
                    collectable=False,
                    reason="scenario_supplies_no_parameters_for_dimension",
                    source="none",
                )
                continue
            metrics = [
                MetricValue(**{**m, "provenance": "scenario_parameters"}) for m in raw
            ]
            observations[dimension] = DimensionObservations(
                dimension=dimension,
                collectable=True,
                observation_count=len(metrics),
                metrics=metrics,
                source="scenario_parameters",
            )
        return BaselineResolution(
            resolved=True,
            baseline_type="scenario",
            baseline_version=_spec_fingerprint(spec, {"params": scenario_params, "end": end}),
            source="scenario_parameters",
            observations=observations,
            window_end=end,
        )

    @staticmethod
    def _stored_observations(
        record: dict[str, Any], dimensions: list[str], *, source: str
    ) -> dict[str, DimensionObservations]:
        stored_metrics: dict[str, list[dict[str, Any]]] = record.get("metrics") or {}
        observations: dict[str, DimensionObservations] = {}
        for dimension in dimensions:
            raw = stored_metrics.get(dimension)
            if not raw:
                observations[dimension] = DimensionObservations(
                    dimension=dimension,
                    collectable=False,
                    reason="stored_baseline_has_no_metrics_for_dimension",
                    source="none",
                )
                continue
            metrics = [MetricValue(**{**m, "provenance": source}) for m in raw]
            observations[dimension] = DimensionObservations(
                dimension=dimension,
                collectable=True,
                observation_count=len(metrics),
                metrics=metrics,
                source=source,
            )
        return observations


def _epoch(event: dict[str, Any]) -> Optional[float]:
    raw = event.get("timestamp") or event.get("occurred_at") or event.get("created_at")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.timestamp()


__all__ = [
    "DEFAULT_WINDOW_DAYS",
    "MIN_PREDICTION_SAMPLE",
    "STORED_BASELINE_SUBJECT_TYPE",
    "BaselineResolution",
    "BaselineResolver",
    "StoredBaselineRepository",
]
