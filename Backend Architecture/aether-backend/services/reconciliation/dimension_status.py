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

logger = get_logger("aether.reconciliation.dimension_status")

# Freshness SLA shared with the Profile360 quality/freshness surfaces.
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


def _freshness(watermark: Optional[datetime], *, now: datetime) -> Optional[DimensionFreshness]:
    if watermark is None:
        return None
    age = (now - watermark).total_seconds()
    return DimensionFreshness(
        watermark=watermark.isoformat(),
        age_seconds=age,
        sla_seconds=float(FRESHNESS_SLA_SECONDS),
        is_stale=age > FRESHNESS_SLA_SECONDS,
    )


# Dimensions reported by data-status → (aggregator method name, min_items).
_DIMENSION_SPECS: tuple[tuple[str, str, int], ...] = (
    ("wallets", "wallets", 1),
    ("sessions", "sessions", 1),
    ("campaigns", "campaigns", 1),
    ("journeys", "journeys", 1),
    ("financials", "financials", 1),
    ("relationships", "relationships", 1),
)


async def _dimension_envelope(
    aggregator: Any, method_name: str, dimension: str, min_items: int,
    entity_id: str, tenant_id: str, *, now: datetime,
) -> DimensionEnvelope:
    method = getattr(aggregator, method_name, None)
    if method is None:  # pragma: no cover — defensive
        return envelope_for_error(dimension, message=f"no aggregator method {method_name!r}")
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
        freshness=_freshness(watermark, now=now),
        min_items=min_items,
    )


async def compute_data_status(
    aggregator: Any, entity_id: str, tenant_id: str, *, now: Optional[datetime] = None
) -> dict:
    """Compute the canonical data-status for an entity across its dimensions.

    Returns ``{entity_id, tenant_id, overall_state, dimensions: [...], ...}``
    where each dimension is a serialized :class:`DimensionEnvelope` and
    ``overall_state`` is the worst dimension state.
    """
    now = now or datetime.now(timezone.utc)
    envelopes: list[DimensionEnvelope] = []
    for dimension, method_name, min_items in _DIMENSION_SPECS:
        envelopes.append(
            await _dimension_envelope(
                aggregator, method_name, dimension, min_items,
                entity_id, tenant_id, now=now,
            )
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
        "freshness_sla_seconds": FRESHNESS_SLA_SECONDS,
        "computed_at": utc_now().isoformat(),
    }
