"""Fleet projections — cross-tenant answers that do not fan out per tenant.

A fleet question ("how many tenants are degraded?") has two possible shapes. The
obvious one loops over tenants and asks each in turn; it is correct for three
tenants, slow for fifty, and an outage for five thousand — and it degrades
exactly when the fleet is unhealthy, because the unhealthy tenants are the slow
ones. The shape here is the other one: a projector writes one precomputed row
per (projection, tenant, environment, dimension) ahead of time, and every read
is a **bounded number of queries independent of tenant count**. That property is
the entire reason this module exists, and
``tests/security/test_kyber_fleet_cohorts.py`` asserts it by counting repository
calls while scaling the tenant count.

The price of precomputation is staleness, so freshness is part of every
response rather than a footnote:

* ``computed_at`` — when this answer was assembled,
* ``oldest_computed_at`` / ``oldest_row_age_seconds`` — the weakest input,
* ``stale`` — whether that age exceeds the configured maximum.

And the rule that follows from it: **missing or stale data reads as ``unknown``
or ``no_data``, never ``healthy``.** A stale row rendered green is worse than no
row at all, because it converts "we do not know" into "it is fine" and an
operator stops looking.

Incompleteness is labelled the way the agent-access plane already labels it
(``services/agent_access_intelligence/kyber_ops_routes.py``): a partial read
returns ``totals_known: false`` with ``missing_inputs`` naming what was absent,
never a confident wrong number.

One further constraint: these are ``D1`` fleet-aggregate surfaces, so the
responses carry counts and distributions and **never a tenant identifier**.
Naming tenants here would make a D1 capability a D2 read.
"""
from __future__ import annotations

import importlib
from collections import Counter
from typing import Any, Iterable, Optional, Sequence

from repositories.repos import BaseRepository
from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics

from .contracts import FleetProjectionRow, HealthStatus, now_iso
from .scoped_gateway import parse_iso

logger = get_logger("aether.kyber.graph.fleet")

#: Projection table from ``alembic/versions/20260810_kyber_graph_ops.py``.
FLEET_PROJECTION_TABLE = "kyber_fleet_projections"

#: How old the weakest row may be before a read is labelled stale.
DEFAULT_MAX_AGE_SECONDS = 900

#: Hard scan bounds. Both are *fleet* bounds, not per-tenant bounds — a read
#: costs the same number of queries whether the fleet has 3 tenants or 5,000.
DEFAULT_READ_LIMIT = 500
SUMMARY_SCAN_LIMIT = 2000

#: A rebuild names tenants explicitly; the list is bounded so a "rebuild
#: everything" request cannot become an unbounded fan-out through the back door.
MAX_REBUILD_TENANTS = 200

#: Worst-first. A fleet roll-up takes the worst *observed* state, but only once
#: the inputs are known to be complete — see ``_roll_up``.
_SEVERITY: tuple[HealthStatus, ...] = ("failing", "degraded", "healthy")

#: States that are themselves an admission of missing input.
_UNKNOWN_STATES: frozenset[str] = frozenset({"unknown", "no_data"})

_PROJECTOR_MODULE = "services.kyber.graph.projector"


def _row_key(row: FleetProjectionRow) -> str:
    """The natural key for one projected fact.

    Storage is keyed on this rather than on ``row_id`` so a projector replay
    upserts the same fact instead of accumulating duplicate rows that would
    then double-count in every aggregate.
    """
    return "|".join(
        (
            row.projection,
            row.tenant_id,
            row.environment or "-",
            row.dimension or "-",
        )
    )


def _coerce_rows(records: Iterable[dict[str, Any]]) -> list[FleetProjectionRow]:
    """Parse stored records, skipping any that no longer match the contract."""
    rows: list[FleetProjectionRow] = []
    for record in records:
        try:
            rows.append(FleetProjectionRow(**record))
        except Exception as exc:  # pragma: no cover - schema drift in storage
            logger.warning(f"kyber: unparseable fleet projection row skipped: {exc}")
    return rows


class FleetProjectionService:
    """Read and maintain the precomputed fleet facts.

    The repository is injectable so the bounded-query property can be *proven*
    rather than asserted: a counting fake substituted here records exactly how
    many queries a read costs at 3 tenants and at 50.
    """

    def __init__(
        self,
        repository: Optional[Any] = None,
        *,
        max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    ) -> None:
        self._repo = repository if repository is not None else BaseRepository(
            FLEET_PROJECTION_TABLE
        )
        self.max_age_seconds = max(1, int(max_age_seconds))

    # ── Write path ───────────────────────────────────────────────────────────

    async def record(self, row: FleetProjectionRow) -> FleetProjectionRow:
        """Upsert one projected fact.

        Idempotent on the natural key so a replayed projector run corrects the
        fact rather than duplicating it.
        """
        key = _row_key(row)
        payload = row.model_dump()
        existing = await self._repo.find_by_id(key)
        if existing is None:
            await self._repo.insert(key, payload)
        else:
            await self._repo.update(key, payload)
        metrics.increment(
            "kyber_fleet_projection_rows_written_total",
            labels={"projection": row.projection, "state": row.state},
        )
        return row

    # ── Read path ────────────────────────────────────────────────────────────

    async def scan(
        self,
        *,
        projection: Optional[str] = None,
        environment: Optional[str] = None,
        limit: int = SUMMARY_SCAN_LIMIT,
    ) -> tuple[list[FleetProjectionRow], bool]:
        """Fetch projection rows in **exactly one** query.

        This is the only place in the package that reads the projection table,
        so "how many queries does a fleet answer cost?" has one auditable
        answer. Callers that need a different slice narrow the filters; they do
        not loop.

        Returns:
            ``(rows, truncated)``. ``truncated`` is detected by asking for one
            more row than the budget, never inferred from a short page.
        """
        budget = min(max(1, int(limit)), SUMMARY_SCAN_LIMIT)
        filters: dict[str, Any] = {}
        if projection:
            filters["projection"] = projection
        if environment:
            filters["environment"] = environment

        records = await self._repo.find_many(filters, limit=budget + 1)
        rows = _coerce_rows(records)
        truncated = len(rows) > budget
        return (rows[:budget] if truncated else rows), truncated

    async def read(
        self,
        projection: str,
        *,
        environment: Optional[str] = None,
        limit: int = DEFAULT_READ_LIMIT,
    ) -> dict[str, Any]:
        """One projection's fleet aggregate. Exactly one query.

        Args:
            projection: The projection name to read.
            environment: Optional environment filter, pushed into the query.
            limit: Row scan bound. Exceeding it makes the answer partial, and
                the response says so rather than reporting a short count.

        Returns:
            Counts and distributions only — never a tenant identifier, because
            this is a ``D1`` fleet-aggregate surface.
        """
        budget = min(max(1, int(limit)), SUMMARY_SCAN_LIMIT)
        rows, truncated = await self.scan(
            projection=projection, environment=environment, limit=budget
        )
        aggregate = self.aggregate(rows, truncated=truncated)
        aggregate.update(
            {
                "projection": projection,
                "environment": environment,
                "queries_issued": 1,
                "scan_limit": budget,
            }
        )
        metrics.increment(
            "kyber_fleet_projection_reads_total",
            labels={
                "projection": projection,
                "state": str(aggregate["state"]),
                "stale": str(aggregate["stale"]).lower(),
            },
        )
        return aggregate

    async def summary(self, *, environment: Optional[str] = None) -> dict[str, Any]:
        """Every projection's aggregate, still in a single query.

        The whole point of the projection table is that this costs the same at
        any fleet size, so the summary does *not* iterate projections and call
        :meth:`read` for each — that would reintroduce a fan-out keyed on
        cardinality rather than on tenants.
        """
        rows, truncated = await self.scan(environment=environment, limit=SUMMARY_SCAN_LIMIT)

        grouped: dict[str, list[FleetProjectionRow]] = {}
        for row in rows:
            grouped.setdefault(row.projection, []).append(row)

        projections = {
            name: self.aggregate(group, truncated=truncated)
            for name, group in sorted(grouped.items())
        }
        overall = self.aggregate(rows, truncated=truncated)
        missing = list(overall["missing_inputs"])
        if not rows:
            missing = ["kyber_fleet_projections:empty"]

        return {
            "environment": environment,
            "projections": projections,
            "projection_count": len(projections),
            "tenant_count": overall["tenant_count"],
            "state": overall["state"],
            "by_state": overall["by_state"],
            "stale": overall["stale"],
            "oldest_computed_at": overall["oldest_computed_at"],
            "oldest_row_age_seconds": overall["oldest_row_age_seconds"],
            "max_age_seconds": self.max_age_seconds,
            "totals_known": overall["totals_known"],
            "missing_inputs": missing,
            "truncated": truncated,
            "queries_issued": 1,
            "scan_limit": SUMMARY_SCAN_LIMIT,
            "computed_at": now_iso(),
        }

    async def rebuild(
        self,
        projection: str,
        *,
        tenant_ids: Optional[Sequence[str]] = None,
    ) -> dict[str, Any]:
        """Ask the projector to recompute one projection.

        This does not recompute anything itself. The projector owns replay,
        offsets and idempotency; duplicating any of that here would give the
        fleet two sources of truth for how far a projection has consumed. When
        the projector cannot be resolved the request is *refused* — reporting a
        rebuild that never ran would leave an operator believing stale rows had
        been corrected.
        """
        requested = [str(t).strip() for t in (tenant_ids or ()) if str(t).strip()]
        truncated = len(requested) > MAX_REBUILD_TENANTS
        if truncated:
            requested = requested[:MAX_REBUILD_TENANTS]

        projector = _resolve_projector()
        if projector is None:
            return {
                "projection": projection,
                "accepted": False,
                "requested_tenant_count": len(requested),
                "truncated": truncated,
                "totals_known": False,
                "missing_inputs": [f"{_PROJECTOR_MODULE}:unavailable"],
                "requested_at": now_iso(),
            }

        rebuild = getattr(projector, "rebuild", None) or getattr(projector, "run", None)
        if rebuild is None:
            logger.error(f"kyber: {_PROJECTOR_MODULE} exposes neither rebuild() nor run()")
            return {
                "projection": projection,
                "accepted": False,
                "requested_tenant_count": len(requested),
                "truncated": truncated,
                "totals_known": False,
                "missing_inputs": [f"{_PROJECTOR_MODULE}:no_rebuild_entry_point"],
                "requested_at": now_iso(),
            }

        try:
            outcome = await rebuild(projection, tenant_ids=requested or None)
        except Exception as exc:
            logger.error(f"kyber: fleet projection rebuild failed for {projection}: {exc}")
            return {
                "projection": projection,
                "accepted": False,
                "requested_tenant_count": len(requested),
                "truncated": truncated,
                "totals_known": False,
                "missing_inputs": [f"kyber_graph_projector:rebuild_failed:{type(exc).__name__}"],
                "requested_at": now_iso(),
            }

        detail = outcome if isinstance(outcome, dict) else {"result": outcome}
        return {
            "projection": projection,
            "accepted": True,
            "requested_tenant_count": len(requested),
            "truncated": truncated,
            "totals_known": not truncated,
            "missing_inputs": (["rebuild_tenant_list:truncated"] if truncated else []),
            "projector": detail,
            "requested_at": now_iso(),
        }

    # ── Aggregation ──────────────────────────────────────────────────────────

    def aggregate(
        self, rows: Sequence[FleetProjectionRow], *, truncated: bool
    ) -> dict[str, Any]:
        """Fold rows into a D1 aggregate that is honest about what it is missing.

        Public because the cohort surface folds the same rows the same way; two
        implementations would eventually disagree about what counts as stale.
        """
        now = utc_now()
        by_state: Counter[str] = Counter()
        by_region: Counter[str] = Counter()
        by_dimension: Counter[str] = Counter()
        tenants: set[str] = set()
        scores: list[float] = []
        oldest: Optional[str] = None
        oldest_age: Optional[float] = None

        for row in rows:
            by_state[row.state] += 1
            by_region[row.region or "-"] += 1
            by_dimension[row.dimension or "-"] += 1
            tenants.add(row.tenant_id)
            if row.score is not None:
                scores.append(float(row.score))
            computed = parse_iso(row.computed_at)
            if computed is None:
                continue
            age = (now - computed).total_seconds()
            if oldest_age is None or age > oldest_age:
                oldest_age = age
                oldest = row.computed_at

        missing: list[str] = []
        if not rows:
            missing.append("kyber_fleet_projections:no_rows")
        if truncated:
            missing.append("kyber_fleet_projections:scan_truncated")
        unknown_rows = sum(count for state, count in by_state.items() if state in _UNKNOWN_STATES)
        if unknown_rows:
            # Counts, not tenant ids: this surface is D1.
            missing.append(f"fleet_projection_state_unknown:count={unknown_rows}")
        undated = sum(1 for row in rows if parse_iso(row.computed_at) is None)
        if undated:
            missing.append(f"fleet_projection_computed_at_unparseable:count={undated}")

        stale = bool(rows) and oldest_age is not None and oldest_age > self.max_age_seconds
        if not rows:
            # No data is its own kind of stale: there is nothing fresh to trust.
            stale = True
        elif oldest_age is None:
            stale = True
        if stale and rows:
            missing.append(f"fleet_projection_stale:max_age_seconds={self.max_age_seconds}")

        totals_known = not missing
        return {
            "row_count": len(rows),
            "tenant_count": len(tenants),
            "by_state": dict(by_state),
            "by_region": dict(by_region),
            "by_dimension": dict(by_dimension),
            "score": _score_summary(scores),
            "state": _roll_up(by_state, totals_known=totals_known, has_rows=bool(rows)),
            "stale": stale,
            "oldest_computed_at": oldest,
            "oldest_row_age_seconds": oldest_age,
            "max_age_seconds": self.max_age_seconds,
            "totals_known": totals_known,
            "missing_inputs": missing,
            "truncated": truncated,
            "computed_at": now_iso(),
        }


def _score_summary(scores: Sequence[float]) -> dict[str, Optional[float]]:
    """Min / mean / max, or all ``None`` when nothing carried a score."""
    if not scores:
        return {"count": 0, "min": None, "mean": None, "max": None}
    return {
        "count": len(scores),
        "min": min(scores),
        "mean": sum(scores) / len(scores),
        "max": max(scores),
    }


def _roll_up(
    by_state: "Counter[str]", *, totals_known: bool, has_rows: bool
) -> HealthStatus:
    """The single state to show for a group of rows.

    Absent rows are ``no_data`` and incomplete rows are ``unknown``. Neither is
    ever ``healthy`` — that is the whole rule. Only a complete set of rows gets
    a real verdict, and then it is the worst one observed, because a fleet with
    one failing tenant is not a healthy fleet.
    """
    if not has_rows:
        return "no_data"
    if not totals_known:
        return "unknown"
    for state in _SEVERITY:
        if by_state.get(state):
            return state
    return "unknown"


def _resolve_projector() -> Optional[Any]:
    """The projection worker, or ``None`` when it is not deployed.

    Resolved through :func:`importlib.import_module` so this module stays
    importable while the projector is built alongside it, and so a rebuild is
    refused rather than silently skipped when the projector is absent.
    """
    try:
        module = importlib.import_module(_PROJECTOR_MODULE)
    except Exception as exc:
        logger.warning(f"kyber: graph projector unavailable ({_PROJECTOR_MODULE}): {exc}")
        return None
    for symbol in ("kyber_graph_projector", "graph_projector", "projector"):
        candidate = getattr(module, symbol, None)
        if candidate is not None:
            return candidate
    factory = getattr(module, "KyberGraphProjector", None)
    if factory is not None:
        try:
            return factory()
        except Exception as exc:  # pragma: no cover - constructor mismatch
            logger.error(f"kyber: KyberGraphProjector() failed: {exc}")
    return None


#: Process-wide service over the real projection table.
fleet_projection_service = FleetProjectionService()


__all__ = [
    "DEFAULT_MAX_AGE_SECONDS",
    "DEFAULT_READ_LIMIT",
    "FLEET_PROJECTION_TABLE",
    "MAX_REBUILD_TENANTS",
    "SUMMARY_SCAN_LIMIT",
    "FleetProjectionService",
    "fleet_projection_service",
]
