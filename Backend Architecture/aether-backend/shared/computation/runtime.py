"""The compute bridge: build canonical results with honest status.

Generalizes ``shared/measurement/compute.py`` to the canonical result envelope.
These helpers are the ONLY sanctioned way to turn raw numerators/denominators/
amounts into a :class:`CanonicalResult`, because they encode the status rules
that keep "unknown" from becoming 0:

  * an undefined denominator -> ``missing_inputs`` (value None), never 0;
  * a denominator below the definition's minimum sample -> ``insufficient_data``;
  * an unpriced money amount -> ``unavailable`` (value None), never 0.
"""

from __future__ import annotations

import uuid
from typing import Optional

from shared.computation.context import ComputationContext
from shared.computation.definition import ComputationDefinition
from shared.computation.quality import Quality, QualityDimensionName
from shared.computation.result import CanonicalResult, ResultStatus
from shared.computation.types import MathType, to_decimal, to_decimal_string
from shared.computation.uncertainty import Uncertainty, UncertaintyKind, wilson


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex}"


def _base_kwargs(definition: ComputationDefinition, context: ComputationContext) -> dict:
    return {
        "definition_id": definition.definition_id,
        "definition_version": definition.definition_version,
        "tenant_id": context.tenant_id,
        "value_type": definition.output_type,
        "unit": definition.unit,
        "grain": context.grain,
        "dimensions": dict(context.dimensions),
        "window": {
            "start": context.event_time_start,
            "end": context.event_time_end,
            "timezone": context.timezone,
        },
        "as_of": context.as_of,
        "context_hash": context.context_hash(),
    }


def rate_result(
    definition: ComputationDefinition,
    context: ComputationContext,
    *,
    numerator: object,
    denominator: object,
    run_id: Optional[str] = None,
    lineage: Optional[dict] = None,
) -> CanonicalResult:
    """Build a rate result with honest status (ratio-of-sums friendly)."""
    num = to_decimal(numerator)
    den = to_decimal(denominator)
    base = _base_kwargs(definition, context)
    base.update(
        run_id=run_id,
        numerator=to_decimal_string(num),
        denominator=to_decimal_string(den),
        lineage=lineage or {},
    )

    if den is None or den == 0:
        return CanonicalResult(
            status=ResultStatus.MISSING_INPUTS,
            value=None,
            quality=Quality().with_dimension(
                QualityDimensionName.SAMPLE_SUFFICIENCY,
                state="insufficient_data",
                reason="undefined or zero denominator",
            ),
            **base,
        )

    if den < definition.minimum_sample_size:
        return CanonicalResult(
            status=ResultStatus.INSUFFICIENT_DATA,
            value=None,
            sample_size=int(den),
            quality=Quality().with_dimension(
                QualityDimensionName.SAMPLE_SUFFICIENCY,
                state="insufficient_data",
                reason=f"denominator {den} below minimum sample {definition.minimum_sample_size}",
                threshold=float(definition.minimum_sample_size),
            ),
            **base,
        )

    value = float((num or 0) / den)
    uncertainty: Optional[Uncertainty] = None
    # Attach a Wilson band only for bounded [0,1] proportions.
    if (
        definition.valid_range_low == 0.0
        and definition.valid_range_high == 1.0
        and num is not None
        and 0 <= num <= den
    ):
        uncertainty = wilson(int(num), int(den))

    return CanonicalResult(
        status=ResultStatus.AVAILABLE,
        value=value,
        sample_size=int(den),
        uncertainty=uncertainty,
        quality=Quality().with_dimension(
            QualityDimensionName.SAMPLE_SUFFICIENCY, state="ready"
        ),
        **base,
    )


def money_result(
    definition: ComputationDefinition,
    context: ComputationContext,
    *,
    amount: object,
    currency: Optional[str],
    status: ResultStatus = ResultStatus.AVAILABLE,
    run_id: Optional[str] = None,
    lineage: Optional[dict] = None,
) -> CanonicalResult:
    """Build a money result. An unpriced amount -> ``unavailable`` (value None)."""
    base = _base_kwargs(definition, context)
    base.update(run_id=run_id, lineage=lineage or {})
    d = to_decimal(amount)
    if d is None or not currency:
        return CanonicalResult(
            status=ResultStatus.UNAVAILABLE,
            value=None,
            currency=currency or None,
            quality=Quality().with_dimension(
                QualityDimensionName.VALUATION_CONFIDENCE,
                state="degraded",
                reason="unpriced or currency-less amount",
            ),
            **base,
        )
    return CanonicalResult(
        status=status,
        value=float(d),
        currency=currency,
        numerator=to_decimal_string(d),
        **base,
    )


def count_result(
    definition: ComputationDefinition,
    context: ComputationContext,
    *,
    amount: object,
    fractional: bool = False,
    run_id: Optional[str] = None,
) -> CanonicalResult:
    """Build a count result. Fractional counts are preserved (never int()-cut)."""
    base = _base_kwargs(definition, context)
    base.update(run_id=run_id)
    d = to_decimal(amount)
    if d is None:
        return CanonicalResult(status=ResultStatus.MISSING_INPUTS, value=None, **base)
    value = float(d) if fractional else float(int(d))
    return CanonicalResult(status=ResultStatus.AVAILABLE, value=value, **base)


__all__ = [
    "new_run_id",
    "rate_result",
    "money_result",
    "count_result",
    "UncertaintyKind",
]
