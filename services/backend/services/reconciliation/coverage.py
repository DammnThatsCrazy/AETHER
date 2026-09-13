"""Tenant-level, statistically honest SDK dimension coverage.

Small tenant populations use a full census. Larger populations use a
reproducible hash-ranked sample over the complete tenant frame, with population
size, method, seed, and Wilson confidence intervals reported in the response.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from services.reconciliation.dimension_status import compute_data_status
from services.reconciliation.expectations import REGISTERED_DIMENSIONS

logger = get_logger("aether.reconciliation.coverage")

DEFAULT_SAMPLE_LIMIT = 200
SAMPLE_SEED_VERSION = "sdk-coverage-v1"
_BUCKETS = ("ready", "stale", "empty", "error")


def _bucket_for_state(state: str) -> str:
    if state in ("ready", "stale", "error"):
        return state
    return "empty"


def _wilson_interval(successes: int, total: int) -> Optional[dict]:
    """95% Wilson score interval; unavailable for an empty sampling frame."""
    if total <= 0:
        return None
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + (z * z / total)
    centre = proportion + (z * z / (2 * total))
    spread = z * math.sqrt(
        (proportion * (1 - proportion) / total) + (z * z / (4 * total * total))
    )
    lower = max(0.0, (centre - spread) / denominator)
    upper = min(1.0, (centre + spread) / denominator)
    return {
        "confidence_level": 0.95,
        "lower": lower,
        "upper": upper,
        "margin_of_error": (upper - lower) / 2,
        "method": "wilson_score",
    }


async def _sampling_frame(
    aggregator: Any, tenant_id: str, *, sample_limit: int
) -> tuple[int, list[str], str]:
    repository = aggregator._entities
    population_size = await repository.count_by_tenant(tenant_id)
    if population_size <= sample_limit:
        rows = await repository.list_by_tenant(
            tenant_id, limit=max(1, population_size)
        )
        methodology = "full_population_census"
    else:
        rows = await repository.sample_by_tenant(
            tenant_id,
            limit=sample_limit,
            seed_version=SAMPLE_SEED_VERSION,
        )
        methodology = "deterministic_hash_sample"

    entity_ids: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        entity_id = row.get("entity_id") or row.get("id")
        if entity_id:
            entity_ids.append(str(entity_id))
    return population_size, entity_ids, methodology


def _unavailable_result(tenant_id: str, sample_limit: int, error_code: str) -> dict:
    dimensions = [
        {
            "dimension": dimension,
            **{bucket: 0 for bucket in _BUCKETS},
            "coverage_ratio": None,
            "value_state": "unavailable",
            "confidence_interval": None,
        }
        for dimension in REGISTERED_DIMENSIONS
    ]
    return {
        "tenant_id": tenant_id,
        "kind": "sdk_coverage",
        "sampling_status": "unavailable",
        "sampling_error_code": error_code,
        "population_size": None,
        "entities_sampled": 0,
        "sample_capped": False,
        "sample_limit": sample_limit,
        "methodology": "unavailable",
        "seed_version": SAMPLE_SEED_VERSION,
        "dimensions": dimensions,
        "overall_coverage": None,
        "overall_value_state": "unavailable",
        "computed_at": utc_now().isoformat(),
    }


async def compute_tenant_coverage(
    tenant_id: str,
    *,
    aggregator: Any = None,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
    now: Optional[datetime] = None,
) -> dict:
    """Compute tenant coverage using a census or full-frame deterministic sample."""
    now = now or datetime.now(timezone.utc)
    sample_limit = max(1, int(sample_limit))

    if aggregator is None:
        from services.profile.aggregator import Profile360Aggregator
        aggregator = Profile360Aggregator()

    try:
        population_size, entity_ids, methodology = await _sampling_frame(
            aggregator, tenant_id, sample_limit=sample_limit
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "tenant_coverage_sampling_frame_failed",
            extra={"tenant_id": tenant_id, "error_code": type(exc).__name__},
        )
        return _unavailable_result(tenant_id, sample_limit, type(exc).__name__)

    sample_capped = population_size > len(entity_ids)
    tallies: dict[str, dict[str, int]] = {
        dimension: {bucket: 0 for bucket in _BUCKETS}
        for dimension in REGISTERED_DIMENSIONS
    }

    for entity_id in entity_ids:
        try:
            status = await compute_data_status(
                aggregator, entity_id, tenant_id, now=now
            )
            dimension_rows = status.get("dimensions", [])
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "tenant_coverage_entity_failed",
                extra={
                    "tenant_id": tenant_id,
                    "entity_id": entity_id,
                    "error_code": type(exc).__name__,
                },
            )
            for dimension in REGISTERED_DIMENSIONS:
                tallies[dimension]["error"] += 1
            continue

        seen: set[str] = set()
        for row in dimension_rows:
            if not isinstance(row, dict):
                continue
            dimension = row.get("dimension")
            if dimension not in tallies:
                continue
            tallies[dimension][_bucket_for_state(row.get("state", "empty"))] += 1
            seen.add(dimension)
        for dimension in REGISTERED_DIMENSIONS:
            if dimension not in seen:
                tallies[dimension]["empty"] += 1

    entities_sampled = len(entity_ids)
    dimensions: list[dict] = []
    observed_ratios: list[float] = []
    for dimension in REGISTERED_DIMENSIONS:
        counts = tallies[dimension]
        ready = counts["ready"]
        ratio = ready / entities_sampled if entities_sampled else None
        if ratio is not None:
            observed_ratios.append(ratio)
        interval = _wilson_interval(ready, entities_sampled)
        if methodology == "full_population_census" and ratio is not None:
            interval = {
                "confidence_level": 1.0,
                "lower": ratio,
                "upper": ratio,
                "margin_of_error": 0.0,
                "method": "census_exact",
            }
        dimensions.append({
            "dimension": dimension,
            "ready": ready,
            "stale": counts["stale"],
            "empty": counts["empty"],
            "error": counts["error"],
            "coverage_ratio": ratio,
            "value_state": "observed" if ratio is not None else "missing",
            "confidence_interval": interval,
        })

    overall_coverage = (
        sum(observed_ratios) / len(observed_ratios)
        if observed_ratios
        else None
    )
    return {
        "tenant_id": tenant_id,
        "kind": "sdk_coverage",
        "sampling_status": "available",
        "sampling_error_code": None,
        "population_size": population_size,
        "entities_sampled": entities_sampled,
        "sample_capped": sample_capped,
        "sample_limit": sample_limit,
        "methodology": methodology,
        "seed_version": SAMPLE_SEED_VERSION,
        "dimensions": dimensions,
        "overall_coverage": overall_coverage,
        "overall_value_state": (
            "observed" if overall_coverage is not None else "missing"
        ),
        "computed_at": utc_now().isoformat(),
    }


__all__ = [
    "DEFAULT_SAMPLE_LIMIT",
    "SAMPLE_SEED_VERSION",
    "compute_tenant_coverage",
]
