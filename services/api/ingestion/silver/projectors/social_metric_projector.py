"""Social Silver projector — social metric observation facts.

Projects Bronze events of type ``social_metric_observed`` into
``silver_social_metric_facts``. A single event may carry a bundle of metrics
(a provider metric snapshot): each provider record in the payload becomes one
metric row, so one Bronze event fans out to N rows (each with its own stable
idempotency key — see social_base).

Table (integrator DDL): columns = BaseProjector._base_row columns + provenance
columns + the domain columns below. UNIQUE on ``(tenant_id, idempotency_key)``.

Honesty (blueprint §11, schema $defs/socialMetricObservation) — THIS projector is
the enforcement point on the Silver plane:
- an unavailable / unauthorized / unsupported metric is ``value = NULL`` with an
  explicit ``status`` (``unavailable`` | ``not_authorized`` | ``not_supported``);
  it is NEVER coerced to a synthetic ``0``;
- ``value = 0`` is stored only when the provider actually reported zero — 0 is a
  measurement, null is a state, and the two never collapse;
- string values are NOT parsed into numbers: a metric that did not arrive as a
  clean number is materialized as ``NULL`` with status ``unavailable`` rather
  than risk inventing precision;
- ``metric_name`` is an open (non-enumerated) canonical vocabulary — the value
  supplied by the upstream normalizer is recorded verbatim, never remapped.

Record contract (properties, snake_case; single object or ``records`` list —
one metric per record):
    metric_name                canonical metric name (required)
    value                      number | None (never a fabricated 0)
    unit                       e.g. "count"
    status                     observed | unavailable | not_authorized |
                               not_supported (optional; derived when absent)
    social_identity_ref        the identity the metric is observed on
    window / population / quality / computation_ref
    observed_at
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .social_base import SocialFactProjector
from .social_common import as_list, as_str

SOCIAL_METRIC_TABLE = "silver_social_metric_facts"
SOCIAL_METRIC_TYPES = frozenset({"social_metric_observed"})

_METRIC_STATUS = frozenset(
    {"observed", "unavailable", "not_authorized", "not_supported"}
)


def _canonical_ref(provider_identity: str | None, value: Any) -> str | None:
    text = as_str(value)
    if not text:
        return None
    if ":" in text:
        return text
    if provider_identity:
        return f"{provider_identity}:{text}"
    return text


def _metric_value(value: Any) -> tuple[Any, bool]:
    """Return (value, was_measured) without ever fabricating a number.

    Accepts int/float (non-bool) and Decimal; strings and other types are NOT
    coerced (``was_measured=False`` -> status unavailable / null value).
    """
    if isinstance(value, bool):
        return None, False
    if isinstance(value, (int, float)):
        return value, True
    if isinstance(value, Decimal):
        try:
            return float(value), True
        except Exception:  # pragma: no cover - Decimal is finite by construction
            return None, False
    return None, False


class SocialMetricProjector(SocialFactProjector):
    """Deterministic metric normalization into silver_social_metric_facts."""

    handles = SOCIAL_METRIC_TYPES
    table = SOCIAL_METRIC_TABLE
    fact_kind = "social_metric_observation"

    def _record_key(self, event: dict[str, Any], record: dict[str, Any]) -> str | None:
        # Metric bundles need per-metric idempotency keys; a single-metric event
        # keeps the bare source_event_id (single-row projector convention).
        if self._is_single_record(event):
            return None
        return as_str(record.get("metric_name")) or None

    def build_row(
        self, event: dict[str, Any], record: dict[str, Any]
    ) -> dict[str, Any] | None:
        metric_name = as_str(record.get("metric_name"))
        if not metric_name:
            return None

        provider_identity = self._provider_family(event, record)
        social_identity_ref = _canonical_ref(
            provider_identity, record.get("social_identity_ref")
        )

        value, was_measured = _metric_value(record.get("value"))
        raw_status = str(record.get("status") or "").lower()
        if raw_status in _METRIC_STATUS:
            status = raw_status
        elif was_measured:
            status = "observed"
        else:
            status = "unavailable"

        row = self._base_social_row(event, record)
        observed_at = (
            as_str(record.get("observed_at")) or as_str(event.get("timestamp")) or None
        )
        metric_observation_id = as_str(record.get("metric_observation_id")) or (
            f"{provider_identity}:{social_identity_ref}:{metric_name}:{observed_at}"
            if provider_identity and social_identity_ref
            else f"{metric_name}:{observed_at}"
        )

        row.update({
            "metric_observation_id": metric_observation_id,
            "social_identity_ref": social_identity_ref,
            "metric_name": metric_name,
            # value is NULL unless the provider actually supplied a measurement.
            "value": value if was_measured else None,
            "unit": as_str(record.get("unit")),
            "status": status,
            "metric_window": record.get("window") if isinstance(record.get("window"), dict) else None,
            "population": as_str(record.get("population")),
            "observed_at": observed_at,
            "computation_ref": as_str(record.get("computation_ref")),
            "quality": as_str(record.get("quality")),
            "evidence_refs": as_list(record.get("evidence_refs")),
        })
        return row
