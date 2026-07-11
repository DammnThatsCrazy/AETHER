"""Per-dimension data-status for a profile, in canonical dimension-state terms.

Reuses the Profile360 aggregator's existing tenant-scoped dimension reads and
maps each into a :class:`DimensionEnvelope`: honest state (ready / empty /
stale / insufficient_data / degraded / error), a reason code, and freshness
(watermark + staleness against the SLA). A failed dimension degrades to an
``error`` envelope — it is surfaced, never erased or fatal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from shared.common.common import utc_now
from shared.dimension_state import (
    DimensionEnvelope,
    DimensionFreshness,
    envelope_for_error,
    envelope_for_items,
    rollup_state,
)
from shared.logger.logger import get_logger

from services.reconciliation.expectations import EXPECTATION_REGISTRY, get_expectation

logger = get_logger("aether.reconciliation.dimension_status")

# Default freshness SLA when a dimension has no registered expectation.
FRESHNESS_SLA_SECONDS = 24 * 60 * 60

# Timestamp fields tried per item, newest-first-wins.
_TS_FIELDS = (
    "occurred_at", "updated_at", "linked_at", "created_at",
    "observed_at", "last_seen_at", "timestamp",
)


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _newest_watermark(items: list[dict]) -> Optional[datetime]:
    newest: Optional[datetime] = None
    for item in items:
        if not isinstance(item, dict):
            continue
        for field in _TS_FIELDS:
            ts = _parse_ts(item.get(field))
            if ts is not None:
                if newest is None or ts > newest:
                    newest = ts
                break
    return newest


def _freshness(
    watermark: Optional[datetime], *, now: datetime, sla_seconds: int
) -> Optional[DimensionFreshness]:
    if watermark is None:
        return None
    age = (now - watermark).total_seconds()
    return DimensionFreshness(
        watermark=watermark.isoformat(),
        age_seconds=age,
        sla_seconds=float(sla_seconds),
        is_stale=age > sla_seconds,
    )


async def _dimension_reading(
    aggregator: Any, dimension: str, entity_id: str, tenant_id: str, *, now: datetime,
) -> DimensionEnvelope:
    """Read one dimension and map it to an envelope using its expectation."""
    exp = get_expectation(dimension)
    method = getattr(aggregator, exp.source_method or dimension, None)
    if method is None:  # pragma: no cover — defensive
        return envelope_for_error(dimension, message=f"no aggregator method for {dimension!r}")
    try:
        result = await method(entity_id, tenant_id)
    except Exception as exc:  # noqa: BLE001 — a failed dimension is surfaced, not fatal
        logger.warning(
            "data_status_dimension_failed",
            extra={"dimension": dimension, "error": str(exc)},
        )
        return envelope_for_error(dimension, message=type(exc).__name__)

    items = result.get("items", []) if isinstance(result, dict) else []
    if not isinstance(items, list):
        items = []
    watermark = _newest_watermark(items)
    return envelope_for_items(
        dimension,
        count=len(items),
        freshness=_freshness(watermark, now=now, sla_seconds=exp.freshness_sla_seconds),
        min_items=exp.min_events,
    )


async def compute_data_status(
    aggregator: Any, entity_id: str, tenant_id: str, *, now: Optional[datetime] = None
) -> dict:
    """Compute the canonical data-status for an entity across its dimensions.

    Returns ``{entity_id, tenant_id, overall_state, dimensions: [...], ...}``
    where each dimension is a serialized :class:`DimensionEnvelope` and
    ``overall_state`` is the worst dimension state. Per-dimension freshness SLAs
    and minimum volumes come from the expectation registry.
    """
    now = now or datetime.now(timezone.utc)
    envelopes: list[DimensionEnvelope] = []
    for dimension in EXPECTATION_REGISTRY:
        envelopes.append(
            await _dimension_reading(aggregator, dimension, entity_id, tenant_id, now=now)
        )
    overall = rollup_state(envelopes)
    return {
        "entity_id": entity_id,
        "tenant_id": tenant_id,
        "kind": "data_status",
        "overall_state": overall,
        "dimensions": [e.model_dump(mode="json") for e in envelopes],
        "dimension_count": len(envelopes),
        "ready": overall == "ready",
        "computed_at": utc_now().isoformat(),
    }


async def compute_reconciliation(
    aggregator: Any, entity_id: str, tenant_id: str, *, now: Optional[datetime] = None
) -> dict:
    """Per-dimension expectation-vs-actual reconciliation for an entity.

    For every registered dimension, report the declared expectation
    (min_events, freshness SLA) alongside the actual reading (count, watermark,
    state) and whether the expectation is met. ``unmet`` dimensions are the ones
    a surface should flag.
    """
    now = now or datetime.now(timezone.utc)
    rows: list[dict] = []
    for dimension, exp in EXPECTATION_REGISTRY.items():
        env = await _dimension_reading(aggregator, dimension, entity_id, tenant_id, now=now)
        met = env.state in ("ready", "not_applicable")
        rows.append({
            "dimension": dimension,
            "state": env.state,
            "reason_code": env.reason_code,
            "met": met,
            "expected": {
                "min_events": exp.min_events,
                "freshness_sla_seconds": exp.freshness_sla_seconds,
                "depends_on": list(exp.depends_on),
            },
            "actual": {
                "count": env.count,
                "watermark": env.freshness.watermark if env.freshness else None,
                "is_stale": env.freshness.is_stale if env.freshness else None,
            },
        })
    unmet = [r["dimension"] for r in rows if not r["met"]]
    return {
        "entity_id": entity_id,
        "tenant_id": tenant_id,
        "kind": "reconciliation",
        "overall_state": rollup_state(
            [DimensionEnvelope(dimension=r["dimension"], state=r["state"]) for r in rows]
        ),
        "dimensions": rows,
        "unmet_dimensions": unmet,
        "met": not unmet,
        "computed_at": utc_now().isoformat(),
    }
