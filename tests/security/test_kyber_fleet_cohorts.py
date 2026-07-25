"""Fleet projections and cohorts must be honest about what they do not know.

Two different failure modes are under test here and neither of them raises.

*Missing data must read as missing.* A partial scan, an undated row, a row in an
``unknown`` state — each has to surface as ``totals_known: false`` with the gap
named in ``missing_inputs``, and the rolled-up state has to be ``unknown`` or
``no_data`` rather than ``healthy``. A confident number computed over inputs that
were never read is worse than no number: an operator acts on it.

*A stale row must not read as current.* Precomputation buys a bounded query cost
and pays for it in freshness, so freshness is part of the answer. A row computed
an hour ago and rendered green converts "we do not know" into "it is fine", and
the operator stops looking exactly when they should not.

The cohort tests attack a third thing: a cohort is an aggregate, and an aggregate
over one tenant *is* an identification. A cohort resolving below its minimum is
suppressed and says so, rather than returning a member count that is itself the
disclosure.

``services/kyber/graph/fleet.py`` names this file as the place its bounded-query
claim is proven, so ``test_a_fleet_read_costs_the_same...`` counts repository
calls while scaling the fleet.

Error classes are resolved at call time (see ``_raises_named``): sibling suites
in this directory purge ``shared.*`` from ``sys.modules``, after which a class
imported here at module scope is no longer the object the service raises.
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "kyber-graph-test")

from repositories.repos import BaseRepository, reset_in_memory_stores  # noqa: E402
from services.kyber.graph.cohorts import (  # noqa: E402
    ABSOLUTE_MINIMUM_SIZE,
    COHORT_DEFINITION_TABLE,
    FLEET_CAPABILITY,
    SUPPRESSION_REASON,
    CohortService,
)
from services.kyber.graph.contracts import CohortDefinition, FleetProjectionRow  # noqa: E402
from services.kyber.graph.fleet import (  # noqa: E402
    FLEET_PROJECTION_TABLE,
    FleetProjectionService,
)
from shared.common.common import utc_now  # noqa: E402

PROJECTION = "graph_health"
ENV = "test"


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


# ── Helpers ──────────────────────────────────────────────────────────────────


class _Table(BaseRepository):
    """A concrete repository over one in-memory table. No database."""

    def __init__(self, table: str) -> None:
        super().__init__(table)


class CountingRepository:
    """Records how many reads a fleet answer costs.

    The precomputed projection table exists so a fleet question costs a bounded
    number of queries *independent of tenant count*. A per-tenant fan-out would
    be correct and would still be an outage at five thousand tenants — and it
    would degrade exactly when the fleet is unhealthy. Counting is the only way
    to assert the difference, because both shapes return the same numbers.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.find_many_calls = 0

    async def find_many(
        self, filters: Optional[dict[str, Any]] = None, limit: int = 50, **_: Any
    ) -> list[dict[str, Any]]:
        self.find_many_calls += 1
        matched = [
            row
            for row in self.rows
            if all(row.get(key) == value for key, value in (filters or {}).items())
        ]
        return matched[:limit]


class OverflowingRepository:
    """Always returns one more row than asked for, so the scan budget binds.

    ``scan`` detects truncation by over-fetching a single row; a fake that
    honours the budget exactly could never exercise that branch, and the
    partial-answer labelling would go untested.
    """

    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    async def find_many(
        self, filters: Optional[dict[str, Any]] = None, limit: int = 50, **_: Any
    ) -> list[dict[str, Any]]:
        return [dict(self.row, tenant_id=f"tenant_{index}") for index in range(limit)]


def _row(
    tenant: str,
    *,
    state: str = "healthy",
    age_seconds: int = 0,
    score: Optional[float] = None,
    region: Optional[str] = "eu-west",
    dimension: Optional[str] = None,
    source_offset: Optional[int] = None,
    projection: str = PROJECTION,
) -> FleetProjectionRow:
    return FleetProjectionRow(
        projection=projection,
        tenant_id=tenant,
        environment=ENV,
        region=region,
        dimension=dimension,
        state=state,  # type: ignore[arg-type]
        score=score,
        source_offset=source_offset,
        computed_at=(utc_now() - timedelta(seconds=age_seconds)).isoformat(),
    )


def _service(**kwargs: Any) -> FleetProjectionService:
    return FleetProjectionService(_Table(FLEET_PROJECTION_TABLE), **kwargs)


async def _seed(service: FleetProjectionService, rows: list[FleetProjectionRow]) -> None:
    for row in rows:
        await service.record(row)


async def _raises_named(name: str, awaitable: Any) -> Exception:
    """Await something that must raise ``name``, matched at call time.

    The class is compared by name rather than by identity because a sibling
    suite's ``shared.*`` purge re-creates these exception classes; an identity
    check would then pass a real failure through as an unrelated error.
    """
    try:
        result = await awaitable
    except Exception as exc:  # noqa: BLE001 - the class is checked here
        assert type(exc).__name__ == name, f"expected {name}, got {type(exc).__name__}: {exc}"
        return exc
    raise AssertionError(f"expected {name}, but the call returned {result!r}")


# ── 8. Partial reads are labelled partial ────────────────────────────────────


async def test_a_partial_fleet_read_reports_totals_known_false():
    """A truncated scan never yields a confident sum.

    The row count that comes back is the *page*, not the fleet, so presenting
    it as a total would understate every aggregate computed from it.
    """
    service = FleetProjectionService(
        OverflowingRepository(_row("tenant_seed").model_dump())
    )
    aggregate = await service.read(PROJECTION, limit=5)

    assert aggregate["truncated"] is True
    assert aggregate["totals_known"] is False
    assert "kyber_fleet_projections:scan_truncated" in aggregate["missing_inputs"]
    assert aggregate["state"] != "healthy", "a partial read must not roll up to healthy"
    assert aggregate["state"] == "unknown"
    assert aggregate["row_count"] == 5


async def test_a_summary_over_a_truncated_scan_is_labelled_partial():
    """Every projection in the summary inherits the incompleteness."""
    service = FleetProjectionService(
        OverflowingRepository(_row("tenant_seed").model_dump())
    )
    summary = await service.summary()

    assert summary["truncated"] is True
    assert summary["totals_known"] is False
    assert summary["missing_inputs"]
    assert summary["state"] == "unknown"
    for projection in summary["projections"].values():
        assert projection["totals_known"] is False
        assert projection["state"] != "healthy"


async def test_an_empty_projection_table_is_no_data_not_healthy():
    """Nothing read is not the same as nothing wrong."""
    summary = await _service().summary()
    assert summary["state"] == "no_data"
    assert summary["totals_known"] is False
    assert summary["stale"] is True
    assert "kyber_fleet_projections:empty" in summary["missing_inputs"]

    aggregate = await _service().read(PROJECTION)
    assert aggregate["state"] == "no_data"
    assert aggregate["totals_known"] is False
    assert "kyber_fleet_projections:no_rows" in aggregate["missing_inputs"]


async def test_rows_in_an_unknown_state_are_counted_as_missing_input():
    """One shrug among healthy rows makes the whole answer a shrug.

    The count is reported and the tenants are not: this is a D1 surface, so
    naming which tenants were unknown would make a fleet capability a tenant
    read.
    """
    service = _service()
    # Ids that are not substrings of the aggregate's own key names, so the
    # "no tenant is named" assertion below cannot pass or fail by accident.
    await _seed(
        service,
        [
            _row("acme_ltd"),
            _row("globex_inc"),
            _row("initech_sa", state="unknown"),
            _row("umbrella_gmbh", state="no_data"),
        ],
    )
    aggregate = await service.read(PROJECTION)

    assert aggregate["totals_known"] is False
    assert "fleet_projection_state_unknown:count=2" in aggregate["missing_inputs"]
    assert aggregate["state"] == "unknown"
    rendered = repr(aggregate)
    for tenant in ("acme_ltd", "globex_inc", "initech_sa", "umbrella_gmbh"):
        assert tenant not in rendered, "a D1 aggregate must not name a tenant"


async def test_a_complete_fresh_read_does_produce_a_verdict():
    """The control: the honesty machinery is not simply refusing to answer."""
    service = _service()
    await _seed(service, [_row("tenant_a"), _row("tenant_b"), _row("tenant_c", state="degraded")])
    aggregate = await service.read(PROJECTION)

    assert aggregate["totals_known"] is True
    assert aggregate["missing_inputs"] == []
    assert aggregate["stale"] is False
    # Worst observed, because a fleet with one degraded tenant is not healthy.
    assert aggregate["state"] == "degraded"
    assert aggregate["tenant_count"] == 3


# ── 9. Staleness ─────────────────────────────────────────────────────────────


async def test_a_stale_projection_row_is_reported_stale_and_never_healthy():
    """An hour-old row rendered green would convert "unknown" into "fine".

    Every row here says ``healthy``; the only defect is age. The answer must
    still refuse to say healthy, and must say why.
    """
    service = _service(max_age_seconds=900)
    await _seed(
        service,
        [_row("tenant_a", age_seconds=3600), _row("tenant_b", age_seconds=30)],
    )
    aggregate = await service.read(PROJECTION)

    assert aggregate["stale"] is True
    assert aggregate["oldest_row_age_seconds"] > 900
    assert aggregate["max_age_seconds"] == 900
    assert "fleet_projection_stale:max_age_seconds=900" in aggregate["missing_inputs"]
    assert aggregate["totals_known"] is False
    assert aggregate["state"] == "unknown", (
        "a stale row must not be served as a current healthy one"
    )


async def test_freshness_is_taken_from_the_weakest_row_not_the_newest():
    """One fresh row cannot vouch for the rest of the fleet."""
    service = _service(max_age_seconds=60)
    await _seed(
        service,
        [_row("tenant_a", age_seconds=1), _row("tenant_b", age_seconds=600)],
    )
    aggregate = await service.read(PROJECTION)
    assert aggregate["stale"] is True
    assert aggregate["oldest_row_age_seconds"] >= 600


async def test_an_undated_row_is_missing_input_rather_than_assumed_fresh():
    """``computed_at`` that will not parse is a gap, not a green light."""
    service = _service()
    row = _row("tenant_a")
    await service.record(row.model_copy(update={"computed_at": "not-a-timestamp"}))

    aggregate = await service.read(PROJECTION)
    assert "fleet_projection_computed_at_unparseable:count=1" in aggregate["missing_inputs"]
    assert aggregate["stale"] is True
    assert aggregate["totals_known"] is False
    assert aggregate["state"] != "healthy"


# ── 10. Cohort minimum size ──────────────────────────────────────────────────


def _cohorts(fleet: FleetProjectionService) -> CohortService:
    return CohortService(_Table(COHORT_DEFINITION_TABLE), fleet=fleet)


async def _define(service: CohortService, *, minimum_size: int, **filters: Any):
    return await service.define(
        CohortDefinition(
            name="degraded-eu-enterprise",
            filters={"projection": PROJECTION, **filters},
            minimum_size=minimum_size,
        )
    )


async def test_a_cohort_below_its_minimum_size_is_suppressed_not_returned():
    """Two members is a selector for two tenants, not an aggregate.

    The member *count* is withheld along with the members: at size one or two
    the count is itself the identification, so "fewer than the minimum" is all
    that can be safely disclosed.
    """
    fleet = _service()
    await _seed(fleet, [_row("tenant_a", state="degraded"), _row("tenant_b", state="degraded")])
    cohorts = _cohorts(fleet)
    cohort = await _define(cohorts, minimum_size=3, state="degraded")

    result = await cohorts.evaluate(cohort.cohort_id, capabilities={FLEET_CAPABILITY})

    assert result["suppressed"] is True
    assert result["reason"] == SUPPRESSION_REASON
    assert result["member_count"] is None
    assert result["members"] is None
    assert result["totals_known"] is False
    assert f"cohort_below_minimum:{SUPPRESSION_REASON}" in result["missing_inputs"]
    assert "tenant_a" not in repr(result) and "tenant_b" not in repr(result)


async def test_a_cohort_of_exactly_the_minimum_size_resolves():
    """The boundary is inclusive, so suppression is not simply always-on."""
    fleet = _service()
    await _seed(
        fleet,
        [_row(f"tenant_{i}", state="degraded") for i in range(3)],
    )
    cohorts = _cohorts(fleet)
    cohort = await _define(cohorts, minimum_size=3, state="degraded")

    result = await cohorts.evaluate(cohort.cohort_id, capabilities={FLEET_CAPABILITY})
    assert result["suppressed"] is False
    assert result["member_count"] == 3
    assert result["members"] == ["tenant_0", "tenant_1", "tenant_2"]


async def test_one_member_short_of_a_raised_minimum_is_still_suppressed():
    """A definition may raise its own floor, and the raised floor binds."""
    fleet = _service()
    await _seed(fleet, [_row(f"tenant_{i}", state="degraded") for i in range(4)])
    cohorts = _cohorts(fleet)
    cohort = await _define(cohorts, minimum_size=5, state="degraded")
    assert cohort.minimum_size == 5

    result = await cohorts.evaluate(cohort.cohort_id, capabilities={FLEET_CAPABILITY})
    assert result["suppressed"] is True
    assert result["member_count"] is None


async def test_a_definition_cannot_lower_the_minimum_below_the_absolute_floor():
    """``minimum_size: 1`` would make the cohort surface a per-tenant read."""
    fleet = _service()
    await _seed(fleet, [_row("tenant_a", state="degraded")])
    cohorts = _cohorts(fleet)
    cohort = await _define(cohorts, minimum_size=1, state="degraded")

    assert cohort.minimum_size == ABSOLUTE_MINIMUM_SIZE
    result = await cohorts.evaluate(cohort.cohort_id, capabilities={FLEET_CAPABILITY})
    assert result["suppressed"] is True, (
        "a single-tenant cohort must never resolve, whatever the definition asked for"
    )
    assert result["minimum_size"] == ABSOLUTE_MINIMUM_SIZE


async def test_at_the_absolute_floor_a_cohort_resolves():
    """The other side of the same boundary."""
    fleet = _service()
    await _seed(
        fleet, [_row(f"tenant_{i}", state="degraded") for i in range(ABSOLUTE_MINIMUM_SIZE)]
    )
    cohorts = _cohorts(fleet)
    cohort = await _define(cohorts, minimum_size=1, state="degraded")

    result = await cohorts.evaluate(cohort.cohort_id, capabilities={FLEET_CAPABILITY})
    assert result["suppressed"] is False
    assert result["member_count"] == ABSOLUTE_MINIMUM_SIZE


async def test_member_identifiers_require_the_fleet_capability():
    """Without the capability the cohort is counts and distributions only."""
    fleet = _service()
    await _seed(fleet, [_row(f"tenant_{i}", state="degraded") for i in range(3)])
    cohorts = _cohorts(fleet)
    cohort = await _define(cohorts, minimum_size=3, state="degraded")

    result = await cohorts.evaluate(cohort.cohort_id, capabilities=())
    assert result["suppressed"] is False
    assert result["member_count"] == 3
    assert result["members"] is None
    assert result["members_disclosure_gated"] is True
    assert "tenant_0" not in repr(result)


async def test_filters_that_could_reach_tenant_records_are_dropped():
    """A cohort evaluates over projection columns and nothing else."""
    fleet = _service()
    cohorts = _cohorts(fleet)
    stored = await cohorts.define(
        CohortDefinition(
            name="sneaky",
            filters={"projection": PROJECTION, "email": "a@b.c", "entity_id": "x"},
            minimum_size=3,
        )
    )
    assert set(stored.filters) == {"projection"}


async def test_an_unknown_cohort_is_not_found_rather_than_empty():
    """Absence must not read as a cohort that resolved to nobody."""
    await _raises_named(
        "NotFoundError", _cohorts(_service()).evaluate("kco_does_not_exist")
    )


async def test_a_suppressed_cohort_is_distinguishable_from_an_empty_one():
    """Suppression and absence must not look the same to an operator."""
    fleet = _service()
    await _seed(fleet, [_row("tenant_a", state="degraded")])
    cohorts = _cohorts(fleet)

    suppressed = await cohorts.evaluate(
        (await _define(cohorts, minimum_size=3, state="degraded")).cohort_id
    )
    empty = await cohorts.evaluate(
        (await _define(cohorts, minimum_size=3, state="failing")).cohort_id
    )
    # Both are suppressed — an empty cohort is below the minimum too — and both
    # say so explicitly rather than returning a zero count.
    for result in (suppressed, empty):
        assert result["suppressed"] is True
        assert result["reason"] == SUPPRESSION_REASON
        assert result["member_count"] is None


# ── 11. Provenance round-trip ────────────────────────────────────────────────


async def test_record_and_read_preserve_source_offset_and_computed_at():
    """Provenance survives storage, so freshness can be judged after the fact.

    ``source_offset`` is how far the projector had consumed when this fact was
    computed; losing it in the round trip would leave the row unfalsifiable.
    """
    service = _service()
    stamp = (utc_now() - timedelta(seconds=42)).isoformat()
    original = _row("tenant_a", source_offset=1234, score=0.5).model_copy(
        update={"computed_at": stamp}
    )
    returned = await service.record(original)
    assert returned.source_offset == 1234

    rows, truncated = await service.scan(projection=PROJECTION)
    assert truncated is False
    assert len(rows) == 1
    assert rows[0].source_offset == 1234
    assert rows[0].computed_at == stamp
    assert rows[0].score == 0.5

    aggregate = await service.read(PROJECTION)
    assert aggregate["oldest_computed_at"] == stamp
    assert aggregate["oldest_row_age_seconds"] == pytest.approx(42, abs=5)


async def test_a_replayed_projection_row_upserts_rather_than_duplicating():
    """The natural key is (projection, tenant, environment, dimension).

    A replay that appended instead of converging would double-count in every
    aggregate computed from the table.
    """
    service = _service()
    first = _row("tenant_a", state="healthy", source_offset=1)
    await service.record(first)
    await service.record(
        first.model_copy(update={"state": "degraded", "source_offset": 2})
    )

    rows, _ = await service.scan(projection=PROJECTION)
    assert len(rows) == 1
    assert rows[0].state == "degraded"
    assert rows[0].source_offset == 2
    assert (await service.read(PROJECTION))["tenant_count"] == 1


# ── Bounded cost ─────────────────────────────────────────────────────────────


async def test_a_fleet_read_costs_the_same_number_of_queries_at_any_fleet_size():
    """One query at three tenants and one query at fifty.

    ``fleet.py`` names this file as where that claim is proven. A per-tenant
    fan-out would return identical numbers and degrade precisely when the fleet
    is unhealthy, so only the call count can tell the two shapes apart.
    """
    small = CountingRepository([_row(f"tenant_{i}").model_dump() for i in range(3)])
    large = CountingRepository([_row(f"tenant_{i}").model_dump() for i in range(50)])

    small_summary = await FleetProjectionService(small).summary()
    large_summary = await FleetProjectionService(large).summary()

    assert small.find_many_calls == large.find_many_calls == 1
    assert small_summary["tenant_count"] == 3
    assert large_summary["tenant_count"] == 50
    assert small_summary["queries_issued"] == large_summary["queries_issued"] == 1

    cohort_repo = CountingRepository([_row(f"tenant_{i}").model_dump() for i in range(50)])
    fleet = FleetProjectionService(cohort_repo)
    cohorts = CohortService(_Table(COHORT_DEFINITION_TABLE), fleet=fleet)
    cohort = await _define(cohorts, minimum_size=3)
    cohort_repo.find_many_calls = 0
    result = await cohorts.evaluate(cohort.cohort_id, capabilities={FLEET_CAPABILITY})
    assert cohort_repo.find_many_calls == 1
    assert result["member_count"] == 50


async def test_a_rebuild_that_cannot_run_is_refused_rather_than_reported_done():
    """A rebuild nobody performed must not read as stale rows corrected."""
    service = _service()

    import services.kyber.graph.fleet as fleet_module

    original = fleet_module._resolve_projector
    fleet_module._resolve_projector = lambda: None  # type: ignore[assignment]
    try:
        refused = await service.rebuild(PROJECTION, tenant_ids=["tenant_a"])
    finally:
        fleet_module._resolve_projector = original  # type: ignore[assignment]

    assert refused["accepted"] is False
    assert refused["totals_known"] is False
    assert refused["missing_inputs"] == ["services.kyber.graph.projector:unavailable"]
