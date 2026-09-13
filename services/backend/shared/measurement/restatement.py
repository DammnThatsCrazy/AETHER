"""Restatement records — the audit link when a prior measurement is corrected.

When a metric is recomputed and supersedes an earlier result, that correction
must be traceable. :func:`build_restatement` produces a pure record linking the
prior and new results. It refuses to link two results that do not describe the
same measurement (same tenant, metric, version, and context), so a restatement
can never silently swap one metric's value for another's.

Persistence of the record lives elsewhere; this function is pure.
"""

from __future__ import annotations

from datetime import datetime, timezone

from shared.measurement.contracts import MeasurementResult
from shared.measurement.validators import MeasurementValidationError

_IDENTITY_FIELDS: tuple[str, ...] = (
    "tenant_id",
    "metric_name",
    "metric_version",
    "context_hash",
)


def build_restatement(prior: MeasurementResult, new: MeasurementResult, reason: str) -> dict:
    """Build a restatement record linking ``prior`` → ``new``.

    Both results must share ``tenant_id``, ``metric_name``, ``metric_version``,
    and ``context_hash``; otherwise :class:`MeasurementValidationError` is raised.
    """

    for field in _IDENTITY_FIELDS:
        prior_value = getattr(prior, field)
        new_value = getattr(new, field)
        if prior_value != new_value:
            raise MeasurementValidationError(
                f"restatement identity mismatch on {field!r}: {prior_value!r} != {new_value!r}"
            )

    return {
        "prior_result_id": prior.id,
        "new_result_id": new.id,
        "reason": reason,
        "restated_at": datetime.now(timezone.utc).isoformat(),
    }
