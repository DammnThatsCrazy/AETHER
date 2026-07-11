"""Tenant-level SDK dimension-coverage diagnostic.

Where :mod:`services.reconciliation.dimension_status` answers "how complete is
*this entity's* data?", this module answers the tenant-wide question: across a
bounded sample of a tenant's entities, how many have usable (ready) data in
each dimension, and how many are empty / stale / errored?

It is an honest, bounded sweep:

* **Bounded** — enumeration is capped at ``sample_limit`` entities. When the
  tenant has more, ``sample_capped`` is set True and the cap is logged, so a
  caller never mistakes a truncated sample for the whole tenant.
* **Honest** — each entity's per-dimension state is computed by reusing
  :func:`compute_data_status` (the canonical per-entity surface). A single
  entity's failure degrades *that entity's* dimensions to ``error``; it never
  aborts the sweep. A tenant with zero entities yields a well-formed empty
  result, not an error.

The four per-dimension buckets (``ready`` / ``stale`` / ``empty`` / ``error``)
partition the sampled entities for that dimension — they always sum to
``entities_sampled``. ``empty`` folds every non-usable, non-stale, non-error
state (genuinely empty, insufficient_data, not_applicable, …) so the buckets
stay a clean partition.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from services.reconciliation.dimension_status import compute_data_status
from services.reconciliation.expectations import REGISTERED_DIMENSIONS

logger = get_logger("aether.reconciliation.coverage")

# Default bound on how many entities a single sweep enumerates.
DEFAULT_SAMPLE_LIMIT = 200

# The four coverage buckets, in a stable order. They partition the sample.
_BUCKETS = ("ready", "stale", "empty", "error")


def _bucket_for_state(state: str) -> str:
    """Map a canonical dimension state into one of the four coverage buckets.

    ``ready`` / ``stale`` / ``error`` map through directly; every other state
    (``empty``, ``insufficient_data``, ``not_applicable``, ``partial``,
    ``pending``, ``degraded``, ``suppressed``) folds into ``empty`` so the four
    buckets always partition the sample. Only ``ready`` counts as usable.
    """
    if state in ("ready", "stale", "error"):
        return state
    return "empty"


async def _enumerate_entities(
    aggregator: Any, tenant_id: str, *, fetch_limit: int
) -> list[str]:
    """Bounded, tenant-scoped enumeration of entity ids for a tenant.

    Uses the entities repository's tenant-scoped listing method
    (``EntityRepository.list_by_tenant``, which filters ``find_many`` on
    ``tenant_id``). We fetch ``fetch_limit`` rows so the caller can detect the
    cap by requesting one more than it intends to keep. Any enumeration failure
    degrades to an empty sample (logged) rather than raising.
    """
    try:
        rows = await aggregator._entities.list_by_tenant(tenant_id, limit=fetch_limit)
    except Exception as exc:  # noqa: BLE001 — enumeration failure is surfaced, not fatal
        logger.warning(
            "tenant_coverage_enumeration_failed",
            extra={"tenant_id": tenant_id, "error": str(exc)},
        )
        return []
    ids: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        eid = row.get("entity_id") or row.get("id")
        if eid:
            ids.append(str(eid))
    return ids


async def compute_tenant_coverage(
    tenant_id: str,
    *,
    aggregator: Any = None,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
    now: Optional[datetime] = None,
) -> dict:
    """Compute tenant-wide SDK dimension coverage over a bounded entity sample.

    Enumerates up to ``sample_limit`` of the tenant's entities and, for each,
    computes its per-dimension data-status via :func:`compute_data_status`.
    Aggregates per dimension across the sample: counts of entities whose
    dimension state is ready / stale / empty / error, plus a coverage ratio
    (entities with usable — i.e. ``ready`` — data ÷ sampled).

    Returns::

        {
          "tenant_id": ...,
          "kind": "sdk_coverage",
          "entities_sampled": int,
          "sample_capped": bool,
          "sample_limit": int,
          "dimensions": [
            {"dimension", "ready", "stale", "empty", "error", "coverage_ratio"},
            ...
          ],
          "overall_coverage": float,
          "computed_at": iso8601,
        }

    Honesty guarantees: a per-entity failure degrades that entity's dimensions
    to ``error`` and the sweep continues; a tenant with zero entities returns a
    well-formed result with ``entities_sampled == 0`` (never an error).
    """
    now = now or datetime.now(timezone.utc)
    sample_limit = max(1, int(sample_limit))

    if aggregator is None:
        from services.profile.aggregator import Profile360Aggregator
        aggregator = Profile360Aggregator()

    # Fetch one more than we intend to keep so we can detect the cap honestly.
    entity_ids = await _enumerate_entities(
        aggregator, tenant_id, fetch_limit=sample_limit + 1
    )
    sample_capped = len(entity_ids) > sample_limit
    if sample_capped:
        entity_ids = entity_ids[:sample_limit]
        logger.info(
            "tenant_coverage_sample_capped",
            extra={"tenant_id": tenant_id, "sample_limit": sample_limit},
        )

    # tallies[dimension][bucket] = count
    tallies: dict[str, dict[str, int]] = {
        dim: {bucket: 0 for bucket in _BUCKETS} for dim in REGISTERED_DIMENSIONS
    }

    for entity_id in entity_ids:
        try:
            status = await compute_data_status(aggregator, entity_id, tenant_id, now=now)
            dimension_rows = status.get("dimensions", [])
        except Exception as exc:  # noqa: BLE001 — one entity never aborts the sweep
            logger.warning(
                "tenant_coverage_entity_failed",
                extra={"tenant_id": tenant_id, "entity_id": entity_id, "error": str(exc)},
            )
            # A wholesale per-entity failure degrades every dimension to error
            # for that entity — surfaced, never silently dropped.
            for dim in REGISTERED_DIMENSIONS:
                tallies[dim]["error"] += 1
            continue

        seen: set[str] = set()
        for row in dimension_rows:
            if not isinstance(row, dict):
                continue
            dim = row.get("dimension")
            if dim not in tallies:
                continue
            tallies[dim][_bucket_for_state(row.get("state", "empty"))] += 1
            seen.add(dim)
        # Defensive: a dimension missing from this entity's status counts as
        # empty so every dimension's buckets still sum to entities_sampled.
        for dim in REGISTERED_DIMENSIONS:
            if dim not in seen:
                tallies[dim]["empty"] += 1

    entities_sampled = len(entity_ids)
    dimensions: list[dict] = []
    ratio_sum = 0.0
    for dim in REGISTERED_DIMENSIONS:
        counts = tallies[dim]
        ready = counts["ready"]
        ratio = (ready / entities_sampled) if entities_sampled else 0.0
        ratio_sum += ratio
        dimensions.append({
            "dimension": dim,
            "ready": ready,
            "stale": counts["stale"],
            "empty": counts["empty"],
            "error": counts["error"],
            "coverage_ratio": ratio,
        })

    overall_coverage = (ratio_sum / len(REGISTERED_DIMENSIONS)) if REGISTERED_DIMENSIONS else 0.0

    return {
        "tenant_id": tenant_id,
        "kind": "sdk_coverage",
        "entities_sampled": entities_sampled,
        "sample_capped": sample_capped,
        "sample_limit": sample_limit,
        "dimensions": dimensions,
        "overall_coverage": overall_coverage,
        "computed_at": utc_now().isoformat(),
    }
