"""Sample-size sufficiency gating.

Before a calculator is allowed to report a real number it must clear a minimum
sample threshold. :func:`evaluate_sufficiency` maps a sample count against that
threshold to the appropriate :class:`ValueState`, so "not enough data" surfaces
as ``INSUFFICIENT_DATA`` with a ``value`` of ``None`` rather than a misleading
small-sample point estimate.
"""

from __future__ import annotations

from shared.measurement.value_states import ValueState


def evaluate_sufficiency(sample_size: int, min_required: int) -> tuple[ValueState, dict]:
    """Return ``(state, detail)`` describing whether the sample is sufficient.

    ``(OBSERVED, {..., "met": True})`` when ``sample_size >= min_required >= 0``;
    otherwise ``(INSUFFICIENT_DATA, {..., "met": False})``.
    """

    met = min_required >= 0 and sample_size >= min_required
    detail = {
        "sample_size": sample_size,
        "min_required": min_required,
        "met": met,
    }
    if met:
        return (ValueState.OBSERVED, detail)
    return (ValueState.INSUFFICIENT_DATA, detail)


def sufficiency_dict(sample_size: int, min_required: int) -> dict:
    """Return only the sufficiency detail dict (suitable for a result's ``sufficiency``)."""

    return evaluate_sufficiency(sample_size, min_required)[1]
