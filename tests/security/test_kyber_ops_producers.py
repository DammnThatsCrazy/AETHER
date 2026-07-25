"""Proof that the Kyber ops planes have production *producers*, not just code.

Three surfaces in this release were written, tested in isolation, and never
called by anything that runs. The failure mode they shared is the worst kind:
each one answered successfully while returning nothing, so a console rendering
an empty list looked like a healthy platform.

These tests pin the wiring, not the algorithms — the algorithms already have
suites (``test_kyber_graph_projector.py``, ``test_kyber_ops_plane.py``). What
was missing was any test that would fail if the *call* disappeared:

* the D0 platform route reads ``PLATFORM_NODE_TYPES``; a projector sweep must
  leave those node types in the store. Nothing else writes them, so without
  this assertion the route is empty in every real deployment;
* ``sync_topology`` reports what it is not producing, and that report must reach
  the sweep result rather than a log line nobody greps;
* topology and ledger read different inputs, so one failing must not take the
  other down — and must not be reported as success;
* the projector's own stall must reach the exception queue exactly once per
  condition, and a recovery must not add a second row;
* the correlation loop must survive a raising iteration, because a supervised
  loop that dies on one malformed signal silently stops correlating forever.

Nothing here needs a database: the graph store and the ops repositories fall
back to shared in-memory dicts under ``AETHER_ENV=local``.

**Error classes are resolved at call time.** Sibling suites in this directory
purge ``shared.*`` from ``sys.modules``, so a class imported at module scope is
a different object after re-import and ``pytest.raises`` silently lets a real
failure escape. See ``_RefusalMatcher`` in ``test_kyber_command_plane.py``; the
same reasoning applies to any identity comparison against a re-importable type,
which is why the assertions below match on names and payload content rather
than on class objects.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "kyber-ops-producers-test")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.kyber.graph.projector import (  # noqa: E402
    PROJECTION_STALL_FAILURE_THRESHOLD,
    KyberGraphProjector,
)
from services.kyber.graph.repository import KyberGraphStore  # noqa: E402
from services.kyber.graph.routes import PLATFORM_NODE_TYPES  # noqa: E402
from services.kyber.graph.topology import UNDERIVABLE_INPUTS  # noqa: E402
from services.kyber.ops.contracts import IncidentSignal  # noqa: E402
from services.kyber.ops.correlation import (  # noqa: E402
    IncidentCorrelationWorker,
    build_incident_correlator_coro,
)
from services.kyber.ops.exceptions import (  # noqa: E402
    ExceptionService,
    report_operational_signal,
)

TENANT = "tenant_acme"
ENV = "test"
_NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)

#: The node types the D0 ``/platform`` route queries that only ``sync_topology``
#: can produce. ``Release``/``Deployment``/``ModelDeployment``/``Region`` are
#: declared-underivable (see ``UNDERIVABLE_INPUTS``), so requiring them here
#: would assert a lie; these three are the ones a running process must write.
TOPOLOGY_OWNED_NODE_TYPES = ("Service", "WorkerRole", "FeatureSurface")


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _clock() -> datetime:
    return _NOW


def _store() -> KyberGraphStore:
    return KyberGraphStore(clock=_clock)


class FakeLedger:
    """The one read shape the projector uses, with an injectable failure.

    Deliberately the same signature as ``GraphMutationLedgerRepository.list_records``
    — the declared seam in ``services/kyber/seams.py`` is what keeps that true.
    """

    def __init__(self, rows: Optional[list[dict[str, Any]]] = None) -> None:
        self.rows = list(rows or [])
        self.fail_with: Optional[Exception] = None

    async def list_records(
        self,
        tenant_id: str,
        aggregate_id: Optional[str] = None,
        limit: int = 1000,
        *,
        since_offset: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        if self.fail_with is not None:
            raise self.fail_with
        rows = [
            r for r in self.rows
            if r["tenant_id"] == tenant_id
            and (since_offset is None or r["ledger_offset"] > since_offset)
        ]
        rows.sort(key=lambda r: r["ledger_offset"])
        return [dict(r) for r in rows[:limit]]


def _row(offset: int, aggregate_type: str = "entity", *, tenant_id: str = TENANT) -> dict[str, Any]:
    return {
        "mutation_id": f"mut_{offset}",
        "ledger_offset": offset,
        "tenant_id": tenant_id,
        "aggregate_type": aggregate_type,
        "aggregate_id": f"agg_{offset}",
        "operation": "upsert",
        "recorded_at": (_NOW - timedelta(seconds=30)).isoformat(),
        "source_event_id": f"evt_{offset}",
        "payload": {"secret_field": "MUST_NOT_BE_PROJECTED"},
    }


def _projector(
    ledger: Optional[FakeLedger] = None, store: Optional[KyberGraphStore] = None
) -> KyberGraphProjector:
    return KyberGraphProjector(
        store=store or _store(),
        ledger=ledger or FakeLedger(),
        clock=_clock,
        environment=ENV,
    )


async def _queue(limit: int = 100) -> dict[str, Any]:
    """The operator queue, read through a fresh service instance.

    A fresh instance is used deliberately: the repositories share one in-memory
    dict per table, so this proves the rows are durable state rather than
    something held on the singleton that raised them.
    """
    return await ExceptionService().queue(status=None, limit=limit)


# ── Z1: the platform surface is actually populated ───────────────────────────


async def test_a_projector_sweep_writes_the_platform_node_types_the_route_reads():
    """The test that would have caught the empty ``/platform`` graph.

    ``GET /v1/kyber/graph/platform`` queries ``PLATFORM_NODE_TYPES``. The ledger
    projection writes only Tenant/TenantGraph/GraphDomain, so unless the sweep
    also derives topology, every one of the node types the route asks for is
    absent and the route returns an empty graph while reporting success.
    """
    store = _store()
    report = await _projector(FakeLedger([_row(1)]), store).project_all(tenant_ids=[TENANT])

    # The store assertion comes first on purpose: it is the one that fails if
    # the wiring is ever removed, and it fails saying the route is empty rather
    # than that a bookkeeping flag is off.
    for node_type in TOPOLOGY_OWNED_NODE_TYPES:
        assert node_type in PLATFORM_NODE_TYPES, f"{node_type} is not a D0 node type"
        nodes = await store.find_nodes(node_type=node_type, environment=ENV, limit=200)
        assert nodes, f"the /platform route queries {node_type} and the sweep wrote none"

    assert report["topology_ok"] is True
    assert report["topology"]["ran"] is True

    # And the ledger half still ran in the same sweep.
    assert await store.get_node(f"tenant:{TENANT}", environment=ENV) is not None


async def test_topology_is_synced_once_per_interval_not_once_per_sweep():
    """Cadence: converge on the first sweep after boot, then back off.

    Topology derives from deploy-time inputs, so re-deriving it on every
    60-second ledger sweep is waste. The second sweep must skip — and skipping
    must be visible as ``ran: False``, not indistinguishable from a sync that
    produced nothing.
    """
    store = _store()
    projector = _projector(FakeLedger([_row(1)]), store)

    first = await projector.project_all(tenant_ids=[TENANT])
    second = await projector.project_all(tenant_ids=[TENANT])

    assert first["topology"]["ran"] is True
    assert second["topology"]["ran"] is False
    assert second["topology"]["reason"] == "not_due"
    # Skipping is not a failure, and the nodes stay where the first sync put them.
    assert second["topology_ok"] is True
    assert await store.find_nodes(node_type="Service", environment=ENV, limit=200)


async def test_topology_missing_inputs_reach_the_sweep_result():
    """The honest report must survive the trip to the caller.

    ``sync_topology`` names the topology it knows it is not producing. If that
    list only reached a log line, the graph's incompleteness would be invisible
    to anything reading the projector's result — which is every operator surface.
    """
    report = await _projector(FakeLedger([_row(1)])).project_all(tenant_ids=[TENANT])

    declared = {name for name, _ in UNDERIVABLE_INPUTS}
    assert declared <= set(report["topology"]["missing_inputs"])
    # Lifted to the top level so a caller reading only the summary still sees it.
    assert declared <= set(report["topology_missing_inputs"])
    # Kept out of ``missing_inputs``, which means "an input this sweep lacked".
    assert report["missing_inputs"] == []


# ── Z1: failure isolation ────────────────────────────────────────────────────


async def test_a_topology_failure_does_not_stop_ledger_projection():
    """Two independent inputs; one broken must not hide the other.

    The failure is also reported *as a failure*: a sweep that swallowed it would
    claim the platform graph is current when it is whatever the last successful
    sync left behind.
    """
    store = _store()
    projector = _projector(FakeLedger([_row(1)]), store)

    async def _boom(_store: KyberGraphStore, *, environment: str) -> dict[str, Any]:
        raise RuntimeError("role table unreadable")

    import services.kyber.graph.projector as projector_module

    original = projector_module.sync_topology
    projector_module.sync_topology = _boom
    try:
        report = await projector.project_all(tenant_ids=[TENANT])
    finally:
        projector_module.sync_topology = original

    assert report["topology_ok"] is False
    assert "RuntimeError" in report["topology"]["error"]

    # The ledger half completed regardless.
    assert report["ok_tenants"] == 1
    assert report["rows_processed"] == 1
    assert await store.get_node(f"tenant:{TENANT}", environment=ENV) is not None

    # And an operator was told, rather than the failure living in a log line.
    queue = await _queue()
    titles = [item["title"] for item in queue["items"]]
    assert any("topology sync failed" in title for title in titles), titles


async def test_a_failed_topology_sync_retries_on_the_next_sweep():
    """A failure must not consume the interval; the next sweep tries again."""
    store = _store()
    projector = _projector(FakeLedger([_row(1)]), store)

    async def _boom(_store: KyberGraphStore, *, environment: str) -> dict[str, Any]:
        raise RuntimeError("transient")

    import services.kyber.graph.projector as projector_module

    original = projector_module.sync_topology
    projector_module.sync_topology = _boom
    try:
        failed = await projector.project_all(tenant_ids=[TENANT])
    finally:
        projector_module.sync_topology = original

    assert failed["topology_ok"] is False
    recovered = await projector.project_all(tenant_ids=[TENANT])
    assert recovered["topology"]["ran"] is True, "a failed sync must not start the interval"
    assert recovered["topology_ok"] is True
    assert await store.find_nodes(node_type="Service", environment=ENV, limit=200)


# ── Z2: the exception queue has a real producer ──────────────────────────────


async def test_a_stalled_projection_raises_exactly_one_exception_and_recovery_adds_none():
    """The projector is a real producer, and it compresses.

    Below the threshold nothing is raised — one failed batch is a blip. At and
    above it, every run reports, and every report lands on the same
    ``dedupe_key``: one row with a count, not a wall of duplicates. Recovery
    stops the producer, so the queue does not grow after the condition clears.
    """
    store = _store()
    ledger = FakeLedger([_row(1)])
    projector = _projector(ledger, store)
    ledger.fail_with = RuntimeError("ledger unavailable")

    for _ in range(PROJECTION_STALL_FAILURE_THRESHOLD - 1):
        await projector.project_tenant(TENANT)
    assert (await _queue())["total"] == 0, "a blip must not page anyone"

    await projector.project_tenant(TENANT)
    queue = await _queue()
    assert queue["total"] == 1, "the stall must reach the operator queue"
    raised = queue["items"][0]
    assert raised["metadata"]["signal_type"] == "kyber_graph_projection_stalled"
    assert raised["affected_tenants"] == [TENANT]
    assert raised["signal_count"] == 1

    # Still failing: compresses onto the same row rather than opening a second.
    await projector.project_tenant(TENANT)
    queue = await _queue()
    assert queue["total"] == 1, "a repeat must compress, not duplicate"
    assert queue["items"][0]["exception_id"] == raised["exception_id"]
    assert queue["items"][0]["signal_count"] == 2

    # Recovered: the producer stops, so nothing new appears.
    ledger.fail_with = None
    result = await projector.project_tenant(TENANT)
    assert result["ok"] is True
    queue = await _queue()
    assert queue["total"] == 1, "recovery must not raise a second exception"
    assert queue["items"][0]["signal_count"] == 2


async def test_the_raised_exception_carries_the_incident_it_was_correlated_into():
    """One observation in, one queued exception linked to one incident.

    A producer should not have to know Kyber keeps two planes; the entry point
    does both halves, and the link is what lets an operator move from the queue
    to the investigation.
    """
    exception = await report_operational_signal(
        IncidentSignal(
            source="kyber_graph_projector",
            signal_type="kyber_graph_projection_stalled",
            service="graph-writer",
            tenant_id=TENANT,
        ),
        title="Kyber Graph projection stalled",
        dedupe_key=f"kyber_graph_projection_stalled:{ENV}:{TENANT}",
        severity="high",
    )
    assert exception.incident_id, "the exception must link to its incident"
    assert exception.affected_services == ["graph-writer"]
    assert exception.affected_tenants == [TENANT]
    # Severity is stamped onto the signal so the two planes cannot disagree.
    assert exception.metadata["payload"]["severity"] == "high"


async def test_the_exception_is_still_raised_when_correlation_fails():
    """The queue is the durable operator signal; correlation is enrichment."""

    class BrokenCorrelator:
        async def ingest_signal(self, _signal: IncidentSignal) -> Any:
            raise RuntimeError("incident store unavailable")

    exception = await report_operational_signal(
        IncidentSignal(source="test", signal_type="probe"),
        title="something is wrong",
        dedupe_key="probe:test",
        correlator=BrokenCorrelator(),  # type: ignore[arg-type]
    )
    assert exception.incident_id is None
    assert (await _queue())["total"] == 1


# ── Z3: the correlation loop is supervised and survives ──────────────────────


async def test_the_correlation_loop_survives_a_raising_iteration():
    """A loop that dies on one bad sweep silently stops correlating forever."""

    class FlakyCorrelator:
        def __init__(self) -> None:
            self.calls = 0

        async def correlate(self, **_kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("malformed signal")
            if self.calls >= 3:
                worker.stop()
            return {"signals_examined": 0}

    correlator = FlakyCorrelator()
    worker = IncidentCorrelationWorker(correlator=correlator)  # type: ignore[arg-type]

    import services.kyber.ops.correlation as correlation_module

    original = correlation_module.sweep_interval_seconds
    correlation_module.sweep_interval_seconds = lambda: 0
    try:
        await asyncio.wait_for(worker.run_forever(), timeout=5)
    finally:
        correlation_module.sweep_interval_seconds = original

    assert correlator.calls >= 3, "the loop must keep sweeping after a raise"


def test_the_correlator_factory_returns_a_long_running_coroutine():
    """A WorkerSpec factory must hand the supervisor a loop, not one sweep.

    The supervisor restarts any spec whose coroutine returns, so a single sweep
    would make the supervisor's backoff — not this module's interval — decide
    the cadence.
    """
    coro = build_incident_correlator_coro()
    try:
        assert coro.cr_code.co_name == "run_forever", (
            f"expected the supervised loop, got {coro.cr_code.co_name}"
        )
    finally:
        coro.close()
