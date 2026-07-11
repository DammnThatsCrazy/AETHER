"""Per-dimension expectation registry.

Each profile dimension declares what "healthy" means for it: the minimum
record volume to be considered sufficient, and the freshness SLA past which its
newest record is stale. Data-status and the reconciliation surface read these
so staleness/insufficiency are judged per dimension (a wallet link is fresh for
much longer than a session) instead of one global threshold.

Expectations are plain data — a single source of truth the diagnostic surfaces
consume. Adding a dimension is one entry here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_DAY = 24 * 60 * 60


@dataclass(frozen=True)
class DimensionExpectation:
    """What a healthy dimension looks like."""

    dimension: str
    # Minimum contributing records before the dimension is "ready" rather than
    # "insufficient_data".
    min_events: int = 1
    # Newest record older than this (seconds) → the dimension is "stale".
    freshness_sla_seconds: int = _DAY
    # Aggregator method that supplies the dimension's items.
    source_method: str = ""
    # Dimensions whose absence explains this one being empty (advisory).
    depends_on: tuple[str, ...] = field(default_factory=tuple)


# Canonical per-dimension expectations. SLAs differ by dimension: sessions go
# stale in a day, a wallet link stays fresh for a week, campaign attribution
# for a month.
EXPECTATION_REGISTRY: dict[str, DimensionExpectation] = {
    "wallets": DimensionExpectation(
        "wallets", min_events=1, freshness_sla_seconds=7 * _DAY, source_method="wallets",
    ),
    "sessions": DimensionExpectation(
        "sessions", min_events=1, freshness_sla_seconds=1 * _DAY, source_method="sessions",
    ),
    "campaigns": DimensionExpectation(
        "campaigns", min_events=1, freshness_sla_seconds=30 * _DAY, source_method="campaigns",
    ),
    "journeys": DimensionExpectation(
        "journeys", min_events=1, freshness_sla_seconds=7 * _DAY, source_method="journeys",
        depends_on=("sessions",),
    ),
    "financials": DimensionExpectation(
        "financials", min_events=1, freshness_sla_seconds=7 * _DAY, source_method="financials",
    ),
    "relationships": DimensionExpectation(
        "relationships", min_events=1, freshness_sla_seconds=30 * _DAY,
        source_method="relationships",
    ),
}

# Stable ordering for surfaces that enumerate the registry.
REGISTERED_DIMENSIONS: tuple[str, ...] = tuple(EXPECTATION_REGISTRY.keys())


def get_expectation(dimension: str) -> DimensionExpectation:
    """Expectation for a dimension; a permissive default for unregistered ones."""
    return EXPECTATION_REGISTRY.get(dimension) or DimensionExpectation(dimension)


def registry_snapshot() -> list[dict]:
    """Serializable view of the registry (for docs / diagnostics)."""
    return [
        {
            "dimension": exp.dimension,
            "min_events": exp.min_events,
            "freshness_sla_seconds": exp.freshness_sla_seconds,
            "source_method": exp.source_method,
            "depends_on": list(exp.depends_on),
        }
        for exp in EXPECTATION_REGISTRY.values()
    ]
