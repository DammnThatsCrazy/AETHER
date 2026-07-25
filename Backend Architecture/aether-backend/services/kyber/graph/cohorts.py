"""Cohorts — named cross-tenant groupings, evaluated over projections only.

A cohort answers "how are the tenants that look like *this* doing?" — enterprise
tenants in ``eu-west``, tenants on the new ingestion path, tenants whose graph
health degraded after a release. It is a genuinely useful operator question and
it is also the easiest way to accidentally build a tenant lookup tool, so two
constraints are structural rather than advisory.

**Evaluation reads fleet projections and nothing else.** No tenant entities, no
identity joins, no reach into a tenant's own graph. A cohort whose filters could
touch raw tenant data would be a cross-tenant read wearing an aggregate's
clothing, and it would also reintroduce the per-tenant fan-out that
:mod:`services.kyber.graph.fleet` exists to remove.

**A cohort that resolves below its minimum size is suppressed.** Otherwise
"tenants in region X on plan Y with state failing" is a single-tenant selector
with extra steps: the aggregate *is* the identification. Suppression is reported
(``suppressed: true``, ``reason: "below_minimum_cohort_size"``) rather than
returned as an empty result, because an operator who cannot tell suppression
from absence will conclude the cohort is fine.

Member identifiers are returned only when the caller holds
``kyber.graph.fleet.read`` **and** the cohort is at or above its minimum size.
Everyone else gets counts and distributions.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Optional

from repositories.repos import BaseRepository
from shared.common.common import NotFoundError
from shared.logger.logger import get_logger, metrics

from .contracts import CohortDefinition, FleetProjectionRow, now_iso
from .fleet import SUMMARY_SCAN_LIMIT, FleetProjectionService, fleet_projection_service

logger = get_logger("aether.kyber.graph.cohorts")

#: Cohort table from ``alembic/versions/20260810_kyber_graph_ops.py``.
COHORT_DEFINITION_TABLE = "kyber_cohort_definitions"

#: Capability that may see which tenants are in a cohort, as opposed to how many.
FLEET_CAPABILITY = "kyber.graph.fleet.read"

#: Floor on ``minimum_size``. A cohort definition may raise its own minimum but
#: never lower it below this, so "minimum_size: 1" cannot be used to turn the
#: cohort surface into a per-tenant read.
ABSOLUTE_MINIMUM_SIZE = 3

#: The only filter keys a cohort may name. Every one resolves to a column of the
#: projection row; there is deliberately no key that reaches tenant records.
SUPPORTED_FILTERS: frozenset[str] = frozenset({
    "projection", "environment", "region", "dimension", "state", "states",
    "min_score", "max_score",
})

#: Reason string returned when a cohort is too small to disclose.
SUPPRESSION_REASON = "below_minimum_cohort_size"


class CohortService:
    """Define and evaluate cohorts over the fleet projection table.

    Both collaborators are injectable: the cohort repository and the fleet
    service. The tests substitute a counting fleet repository to prove that a
    cohort evaluation costs one projection query and never touches a tenant
    entity store.
    """

    def __init__(
        self,
        repository: Optional[Any] = None,
        *,
        fleet: Optional[FleetProjectionService] = None,
    ) -> None:
        self._repo = repository if repository is not None else BaseRepository(
            COHORT_DEFINITION_TABLE
        )
        self._fleet = fleet if fleet is not None else fleet_projection_service

    # ── Definition ───────────────────────────────────────────────────────────

    async def define(self, cohort: CohortDefinition) -> CohortDefinition:
        """Persist a cohort definition, normalising it first.

        Normalisation is where the two structural constraints are applied:
        unsupported filter keys are dropped (a filter that cannot be evaluated
        over projections must not silently widen into one that can), and
        ``minimum_size`` is raised to :data:`ABSOLUTE_MINIMUM_SIZE` when a
        caller asks for less.

        Returns:
            The stored definition, which may differ from the argument.
        """
        filters = {k: v for k, v in (cohort.filters or {}).items() if k in SUPPORTED_FILTERS}
        dropped = sorted(set(cohort.filters or {}) - SUPPORTED_FILTERS)
        if dropped:
            logger.warning(
                f"kyber: cohort {cohort.name!r} declared unsupported filters {dropped}; "
                "dropped — cohorts evaluate over fleet projections only"
            )
        normalised = cohort.model_copy(
            update={
                "filters": filters,
                "minimum_size": max(int(cohort.minimum_size), ABSOLUTE_MINIMUM_SIZE),
            }
        )
        await self._repo.insert(normalised.cohort_id, normalised.model_dump())
        metrics.increment(
            "kyber_cohort_definitions_total",
            labels={"minimum_size": str(normalised.minimum_size)},
        )
        return normalised

    async def get(self, cohort_id: str) -> Optional[CohortDefinition]:
        """One cohort definition, or ``None``."""
        record = await self._repo.find_by_id(cohort_id)
        if record is None:
            return None
        try:
            return CohortDefinition(**record)
        except Exception as exc:  # pragma: no cover - schema drift in storage
            logger.error(f"kyber: unparseable cohort definition {cohort_id}: {exc}")
            return None

    # ── Evaluation ───────────────────────────────────────────────────────────

    async def evaluate(
        self,
        cohort_id: str,
        *,
        environment: Optional[str] = None,
        capabilities: Iterable[str] = (),
    ) -> dict[str, Any]:
        """Resolve a cohort to an aggregate over fleet projections.

        Args:
            cohort_id: The definition to evaluate.
            environment: Overrides the definition's own environment filter.
            capabilities: The caller's held capabilities. Member identifiers are
                disclosed only when this contains ``kyber.graph.fleet.read``.

        Returns:
            An aggregate. When the cohort resolves below its minimum size the
            result is ``{"suppressed": true, "reason": "…"}`` with no member
            count — the count itself is the disclosure at size one.

        Raises:
            NotFoundError: When the cohort id is unknown.
        """
        cohort = await self.get(cohort_id)
        if cohort is None:
            raise NotFoundError(f"Unknown cohort: {cohort_id}")

        filters = dict(cohort.filters or {})
        projection = str(filters.get("projection") or "").strip()
        env = environment or filters.get("environment")

        # ── The one query. Fleet projections only: no tenant entity is read,
        # no identity is joined, and the cost does not scale with tenant count.
        rows, truncated = await self._fleet.scan(
            projection=projection or None, environment=env, limit=SUMMARY_SCAN_LIMIT
        )
        matched = [row for row in rows if _matches(row, filters)]
        members = sorted({row.tenant_id for row in matched})

        missing: list[str] = []
        if truncated:
            missing.append("kyber_fleet_projections:scan_truncated")
        if not projection:
            missing.append("cohort_filters:projection_unset")

        base = {
            "cohort_id": cohort.cohort_id,
            "name": cohort.name,
            "filters": filters,
            "environment": env,
            "minimum_size": cohort.minimum_size,
            "queries_issued": 1,
            "computed_at": now_iso(),
        }

        if len(members) < cohort.minimum_size:
            # Deliberately no member_count: at size one or two the count is the
            # identification. "Fewer than the minimum" is all that is safe.
            metrics.increment(
                "kyber_cohort_evaluations_total",
                labels={"outcome": "suppressed"},
            )
            return {
                **base,
                "suppressed": True,
                "reason": SUPPRESSION_REASON,
                "member_count": None,
                "members": None,
                "state": "unknown",
                "stale": True,
                "totals_known": False,
                "missing_inputs": missing + [f"cohort_below_minimum:{SUPPRESSION_REASON}"],
                "truncated": truncated,
            }

        freshness = self._fleet.aggregate(matched, truncated=truncated)
        by_state: Counter[str] = Counter(row.state for row in matched)
        disclose_members = FLEET_CAPABILITY in set(capabilities)

        metrics.increment(
            "kyber_cohort_evaluations_total",
            labels={"outcome": "members" if disclose_members else "aggregate"},
        )
        return {
            **base,
            "suppressed": False,
            "reason": None,
            "member_count": len(members),
            "members": members if disclose_members else None,
            "members_disclosure_gated": not disclose_members,
            "row_count": len(matched),
            "by_state": dict(by_state),
            "by_region": freshness["by_region"],
            "by_dimension": freshness["by_dimension"],
            "score": freshness["score"],
            "state": freshness["state"],
            "stale": freshness["stale"],
            "oldest_computed_at": freshness["oldest_computed_at"],
            "oldest_row_age_seconds": freshness["oldest_row_age_seconds"],
            "max_age_seconds": freshness["max_age_seconds"],
            "totals_known": freshness["totals_known"] and not missing,
            "missing_inputs": missing + list(freshness["missing_inputs"]),
            "truncated": truncated,
        }


def _matches(row: FleetProjectionRow, filters: dict[str, Any]) -> bool:
    """Whether one projection row satisfies the cohort's predicates.

    Every predicate reads a projection column. There is no branch here that can
    reach a tenant record, which is what keeps a cohort an aggregate.
    """
    projection = filters.get("projection")
    if projection and row.projection != projection:
        return False
    environment = filters.get("environment")
    if environment and row.environment != environment:
        return False
    region = filters.get("region")
    if region and row.region != region:
        return False
    dimension = filters.get("dimension")
    if dimension and row.dimension != dimension:
        return False

    states = filters.get("states")
    if states and row.state not in set(states):
        return False
    state = filters.get("state")
    if state and row.state != state:
        return False

    min_score = filters.get("min_score")
    if min_score is not None and (row.score is None or float(row.score) < float(min_score)):
        return False
    max_score = filters.get("max_score")
    if max_score is not None and (row.score is None or float(row.score) > float(max_score)):
        return False
    return True


#: Process-wide service over the real cohort table.
cohort_service = CohortService()


__all__ = [
    "ABSOLUTE_MINIMUM_SIZE",
    "COHORT_DEFINITION_TABLE",
    "FLEET_CAPABILITY",
    "SUPPORTED_FILTERS",
    "SUPPRESSION_REASON",
    "CohortService",
    "cohort_service",
]
