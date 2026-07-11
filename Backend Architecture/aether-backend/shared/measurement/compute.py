"""Measurement computation bridge — honest metric computation for engine calculators.

Turns raw ``(numerator, denominator)`` counts into an integrity-plane
:class:`MeasurementResult`: the value is ``None`` with an honest
:class:`ValueState` when the data is insufficient (never a bare ``0``), a Wilson
interval is attached for proportion metrics, and the result is keyed to a
:class:`MeasurementContext`. Engine calculators (the Campaign360 gold
materializer, attribution, journey) use this so the Measurement Integrity Plane
is populated by *real* computations rather than sidecar zeros.

The gold ClickHouse rows keep their typed float columns for analytical
compatibility; the plane (``measurement_results``, surfaced at ``/v1/measurement``)
is the integrity source of truth — a ``0.0`` in gold is legacy denormalization,
while the plane says ``insufficient_data`` when that is the truth.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.measurement.context import MeasurementContext
from shared.measurement.contracts import MeasurementResult, Uncertainty
from shared.measurement.registry import get_definition
from shared.measurement.sufficiency import evaluate_sufficiency
from shared.measurement.uncertainty import as_uncertainty, wilson_interval
from shared.measurement.value_states import ValueState


def rate_result(
    numerator: float,
    denominator: float,
    *,
    metric_name: str,
    definition: Optional[Any] = None,
) -> tuple[Optional[float], ValueState, Optional[Uncertainty], dict]:
    """Compute a proportion metric honestly.

    Returns ``(value | None, ValueState, Uncertainty | None, sufficiency)``:

    - ``denominator <= 0`` → ``(None, MISSING_INPUTS, None, …)`` — no sample.
    - ``denominator < min_sample`` → ``(None, INSUFFICIENT_DATA, None, …)``.
    - otherwise → ``(numerator/denominator, OBSERVED, Wilson band, …)`` — the
      Wilson interval only when the metric is a bounded proportion (``[0, 1]``).
    """
    defn = definition if definition is not None else get_definition(metric_name)
    min_sample = int(getattr(defn, "min_sample", 1) or 1)
    trials = int(denominator)
    successes = int(numerator)

    if trials <= 0:
        return (
            None,
            ValueState.MISSING_INPUTS,
            None,
            {"sample_size": max(trials, 0), "min_required": min_sample, "met": False},
        )

    state, detail = evaluate_sufficiency(trials, min_sample)
    if state is not ValueState.OBSERVED:
        return (None, state, None, detail)

    value = successes / trials
    uncertainty: Optional[Uncertainty] = None
    is_proportion = (
        defn is not None
        and getattr(defn, "lower", None) == 0.0
        and getattr(defn, "upper", None) == 1.0
    )
    if is_proportion and 0 <= successes <= trials:
        low, high = wilson_interval(successes, trials)
        uncertainty = as_uncertainty("wilson", value, low, high)
    return (value, ValueState.OBSERVED, uncertainty, detail)


def build_result(
    context: MeasurementContext,
    *,
    metric_name: str,
    numerator: float,
    denominator: float,
    unit: Optional[str] = None,
    lineage: Optional[dict] = None,
) -> MeasurementResult:
    """Compute a rate and package it as a :class:`MeasurementResult` keyed to the
    context (its ``context_hash`` pins the result to exactly these conditions)."""
    defn = get_definition(metric_name)
    value, state, uncertainty, sufficiency = rate_result(
        numerator, denominator, metric_name=metric_name, definition=defn
    )
    return MeasurementResult(
        tenant_id=context.tenant_id,
        metric_name=metric_name,
        metric_version=(getattr(defn, "version", "1") if defn else "1"),
        context_hash=context.context_hash(),
        value=value,
        value_state=state,
        unit=unit or (getattr(defn, "unit", "ratio") if defn else "ratio"),
        lineage=lineage or {},
        sufficiency=sufficiency,
        uncertainty=uncertainty,
    )


async def record_rate(
    repo: Any,
    context: MeasurementContext,
    *,
    metric_name: str,
    numerator: float,
    denominator: float,
    unit: Optional[str] = None,
    lineage: Optional[dict] = None,
) -> Optional[dict]:
    """Best-effort: compute the rate and persist a :class:`MeasurementResult` into
    the plane. Idempotent — an active result already recorded for this context is
    returned unchanged rather than raising (the reject-on-active-duplicate path),
    and any error is swallowed so a calling materialization never breaks on
    telemetry. Returns the stored/existing row, or ``None`` on failure.
    """
    result = build_result(
        context,
        metric_name=metric_name,
        numerator=numerator,
        denominator=denominator,
        unit=unit,
        lineage=lineage,
    )
    record = result.model_dump(mode="json")
    try:
        return await repo.insert_result(record)
    except Exception:
        try:
            return await repo.get_active(
                context.tenant_id, metric_name, result.metric_version, context.context_hash()
            )
        except Exception:
            return None


__all__ = ["rate_result", "build_result", "record_rate"]
