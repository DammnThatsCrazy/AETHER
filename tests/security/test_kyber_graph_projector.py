"""The Kyber Graph projection must converge, resume, and never skip.

A projection has two failure modes and they are not symmetric. Projecting too
much — a replayed range duplicating nodes — inflates the graph and every count
computed from it. Projecting too little — an offset that advanced past a batch
that failed — leaves a hole that reads as "nothing happened for that tenant",
and no later run will ever fill it. The tests below weight accordingly: replay
idempotence, resumption, and the refusal to advance on failure each get a direct
test, because each one is a property no amount of downstream validation can
recover.

The tenant-discipline test is here for the same reason the guard is: the Kyber
Graph holds platform topology and *references* into tenant data. A ``Service``
node carrying a ``tenant_id`` would mean tenant data had leaked into the global
plane, where isolation is no longer structural but a query-time filter — the
defect class the whole plane was built to avoid.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "kyber-graph-test")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.kyber.graph.contracts import (  # noqa: E402
    TENANT_SCOPED_NODE_TYPES,
    KyberGraphEdge,
    KyberGraphNode,
)
from services.kyber.graph.projector import (  # noqa: E402
    PROJECTION_NAME,
    KyberGraphProjector,
    build_kyber_graph_projector_coro,
)
from services.kyber.graph.repository import KyberGraphStore  # noqa: E402
from services.kyber.graph.topology import (  # noqa: E402
    feature_surface_nodes,
    service_nodes,
    sync_topology,
    worker_role_edges,
)
from shared.common.common import AetherError  # noqa: E402

TENANT = "tenant_acme"
ENV = "test"
_NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_stores():
    """Every test starts from an empty graph (in-memory backend, no Postgres)."""
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _clock():
    return _NOW


def _store() -> KyberGraphStore:
    return KyberGraphStore(clock=_clock)


class FakeLedger:
    """Stand-in for ``GraphMutationLedgerRepository`` with the same read shape.

    Only ``list_records`` is exercised by the projector, and the declared seam
    in ``services/kyber/seams.py`` is what proves this signature still matches
    the real repository — a fake that drifted would otherwise make these tests
    pass against an API that no longer exists.
    """

    def __init__(
        self,
        rows: Optional[list[dict[str, Any]]] = None,
        *,
        sorted_output: bool = True,
    ) -> None:
        self.rows = list(rows or [])
        #: The real repository reads ``ORDER BY ledger_offset``. Setting this
        #: False delivers the batch shuffled, so the projector's own ordering is
        #: what has to hold the invariant.
        self.sorted_output = sorted_output
        self.fail_with: Optional[Exception] = None
        self.calls: list[tuple[str, Optional[str], int, Optional[int]]] = []

    async def list_records(
        self,
        tenant_id: str,
        aggregate_id: Optional[str] = None,
        limit: int = 1000,
        *,
        since_offset: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        self.calls.append((tenant_id, aggregate_id, limit, since_offset))
        if self.fail_with is not None:
            raise self.fail_with
        rows = [
            r for r in self.rows
            if r["tenant_id"] == tenant_id
            and (since_offset is None or r["ledger_offset"] > since_offset)
        ]
        if self.sorted_output:
            rows.sort(key=lambda r: r["ledger_offset"])
        return [dict(r) for r in rows[:limit]]


def _row(offset: int, aggregate_type: str, *, tenant_id: str = TENANT,
         recorded_at: Optional[datetime] = None) -> dict[str, Any]:
    """One ledger row in the shape ``list_records`` returns."""
    stamp = (recorded_at or _NOW - timedelta(seconds=30)).isoformat()
    return {
        "mutation_id": f"mut_{offset}",
        "ledger_offset": offset,
        "tenant_id": tenant_id,
        "aggregate_type": aggregate_type,
        "aggregate_id": f"agg_{offset}",
        "operation": "upsert",
        "recorded_at": stamp,
        "source_event_id": f"evt_{offset}",
        # Payload contents must never reach the graph. If they ever do, this
        # marker is what a reviewer will find in a node's properties.
        "payload": {"secret_field": "MUST_NOT_BE_PROJECTED", "email": "a@b.c"},
    }


def _projector(ledger: FakeLedger, store: Optional[KyberGraphStore] = None) -> KyberGraphProjector:
    return KyberGraphProjector(
        store=store or _store(), ledger=ledger, clock=_clock, environment=ENV
    )


# ── Replay idempotence ───────────────────────────────────────────────────────

async def test_replaying_the_same_range_is_idempotent():
    """The same ledger range projected twice yields the same graph.

    This is the property that makes at-least-once delivery safe. If it fails,
    every count derived from the graph inflates on each redelivery.
    """
    ledger = FakeLedger([_row(1, "entity"), _row(2, "campaign"), _row(3, "entity")])
    store = _store()
    projector = _projector(ledger, store)

    first = await projector.project_tenant(TENANT)
    assert first["ok"] is True
    assert first["rows_processed"] == 3

    nodes_after_first = await store.find_nodes(environment=ENV, limit=500)
    edges_after_first = await store.edges_from(f"tenant:{TENANT}", environment=ENV)
    node_ids = {n.node_id for n in nodes_after_first}

    # Rewind the durable offset: the same rows are delivered a second time.
    offset = await store.offset_for(PROJECTION_NAME, TENANT)
    await store.save_offset(offset.model_copy(update={"last_offset": 0}))

    second = await projector.project_tenant(TENANT)
    assert second["rows_processed"] == 3

    nodes_after_second = await store.find_nodes(environment=ENV, limit=500)
    assert len(nodes_after_second) == len(nodes_after_first)
    # Same rows, not new rows that merely happen to be equal in number.
    assert {n.node_id for n in nodes_after_second} == node_ids
    assert len(await store.edges_from(f"tenant:{TENANT}", environment=ENV)) == len(
        edges_after_first
    )


async def test_projected_nodes_carry_provenance_and_no_payload():
    """Provenance is stored; payload contents are not.

    The graph references tenant data and never copies it — a payload field
    surfacing in node properties is a boundary violation, not a cosmetic one.
    """
    ledger = FakeLedger([_row(7, "entity")])
    store = _store()
    await _projector(ledger, store).project_tenant(TENANT)

    tenant_node = await store.get_node(f"tenant:{TENANT}", environment=ENV)
    assert tenant_node is not None
    assert tenant_node.source_offset == 7
    assert tenant_node.source_event_id == "evt_7"
    assert tenant_node.tenant_id == TENANT

    for node in await store.find_nodes(environment=ENV, limit=500):
        rendered = repr(node.properties)
        assert "MUST_NOT_BE_PROJECTED" not in rendered
        assert "a@b.c" not in rendered


async def test_domains_and_edges_reflect_touched_aggregates():
    """Each touched aggregate type becomes one GraphDomain under the tenant."""
    ledger = FakeLedger([_row(1, "entity"), _row(2, "entity"), _row(3, "campaign")])
    store = _store()
    await _projector(ledger, store).project_tenant(TENANT)

    domains = await store.find_nodes(node_type="GraphDomain", environment=ENV, limit=100)
    assert {d.properties["aggregate_type"] for d in domains} == {"entity", "campaign"}

    owns = await store.edges_from(
        f"tenant:{TENANT}", relationship_type="OWNS_GRAPH", environment=ENV
    )
    assert len(owns) == 1
    contains = await store.edges_from(
        f"tenant_graph:{TENANT}", relationship_type="CONTAINS_DOMAIN", environment=ENV
    )
    assert len(contains) == 2
    assert await store.edges_to(f"tenant_graph:{TENANT}", environment=ENV)


# ── Resumption ───────────────────────────────────────────────────────────────

async def test_projector_resumes_from_durable_offset():
    """A second run consumes only what arrived since the stored offset."""
    ledger = FakeLedger([_row(1, "entity"), _row(2, "entity")])
    store = _store()
    projector = _projector(ledger, store)

    first = await projector.project_tenant(TENANT)
    assert first["last_offset"] == 2

    idle = await projector.project_tenant(TENANT)
    assert idle["rows_processed"] == 0
    assert idle["nodes_upserted"] == 0
    assert idle["edges_upserted"] == 0
    assert idle["last_offset"] == 2

    ledger.rows.append(_row(9, "dataset"))
    resumed = await projector.project_tenant(TENANT)
    assert resumed["rows_processed"] == 1
    assert resumed["last_offset"] == 9
    assert resumed["from_offset"] == 2


async def test_lag_is_measured_from_the_newest_consumed_row():
    """Freshness is reported, so a silently-behind projection is visible."""
    stale = _NOW - timedelta(minutes=5)
    ledger = FakeLedger([_row(1, "entity", recorded_at=stale)])
    result = await _projector(ledger).project_tenant(TENANT)
    assert result["lag_seconds"] == pytest.approx(300.0, abs=1.0)


# ── Failure handling ─────────────────────────────────────────────────────────

async def test_failed_batch_does_not_advance_the_offset():
    """A failure re-processes; it never skips.

    Advancing on failure would leave a permanent hole that reads as an empty
    tenant, so the offset must stay put while the error is recorded.
    """
    ledger = FakeLedger([_row(1, "entity"), _row(2, "entity")])
    store = _store()
    projector = _projector(ledger, store)

    ledger.fail_with = RuntimeError("ledger unavailable")
    failed = await projector.project_tenant(TENANT)
    assert failed["ok"] is False
    assert failed["last_offset"] == 0
    assert "ledger unavailable" in failed["error"]

    stored = await store.offset_for(PROJECTION_NAME, TENANT)
    assert stored.last_offset == 0
    assert stored.consecutive_failures == 1
    assert "ledger unavailable" in (stored.last_error or "")

    # Repeated failure accumulates; nothing is consumed.
    await projector.project_tenant(TENANT)
    assert (await store.offset_for(PROJECTION_NAME, TENANT)).consecutive_failures == 2
    assert not await store.find_nodes(environment=ENV, limit=10)

    # Recovery clears the error and finally consumes the same rows.
    ledger.fail_with = None
    recovered = await projector.project_tenant(TENANT)
    assert recovered["ok"] is True
    assert recovered["rows_processed"] == 2
    clean = await store.offset_for(PROJECTION_NAME, TENANT)
    assert clean.last_offset == 2
    assert clean.consecutive_failures == 0
    assert clean.last_error is None


async def test_one_stuck_tenant_does_not_stall_the_fleet():
    """project_all isolates per-tenant failures."""
    other = "tenant_globex"
    ledger = FakeLedger([_row(1, "entity"), _row(2, "entity", tenant_id=other)])
    store = _store()

    class OneTenantBreaks(KyberGraphProjector):
        async def project_tenant(self, tenant_id: str, *, limit: int = 500):
            if tenant_id == TENANT:
                raise RuntimeError("poison row")
            return await super().project_tenant(tenant_id, limit=limit)

    projector = OneTenantBreaks(
        store=store, ledger=ledger, clock=_clock, environment=ENV
    )
    report = await projector.project_all(tenant_ids=[TENANT, other])
    assert report["tenants"] == 2
    assert report["failed_tenants"] == 1
    assert report["ok_tenants"] == 1
    assert await store.get_node(f"tenant:{other}", environment=ENV) is not None


async def test_project_all_reports_a_missing_tenant_roster():
    """With nothing projected yet and no roster passed, the gap is named."""
    report = await _projector(FakeLedger()).project_all()
    assert report["tenants"] == 0
    assert "tenant_ids" in report["missing_inputs"]


async def test_project_all_derives_known_tenants_after_a_first_run():
    """Once a tenant has an offset row, the fleet sweep finds it again."""
    ledger = FakeLedger([_row(1, "entity")])
    store = _store()
    projector = _projector(ledger, store)
    await projector.project_tenant(TENANT)

    ledger.rows.append(_row(4, "campaign"))
    report = await projector.project_all()
    assert report["tenants"] == 1
    assert report["missing_inputs"] == []
    assert report["rows_processed"] == 1


# ── Store semantics ──────────────────────────────────────────────────────────

async def test_out_of_order_rows_never_regress_source_offset():
    """An older row must not overwrite newer state."""
    store = _store()
    await store.upsert_node(
        KyberGraphNode(
            node_key=f"tenant:{TENANT}",
            node_type="Tenant",
            environment=ENV,
            tenant_id=TENANT,
            display_name="current",
            health="healthy",
            source_offset=10,
            source_event_id="evt_10",
        )
    )
    returned = await store.upsert_node(
        KyberGraphNode(
            node_key=f"tenant:{TENANT}",
            node_type="Tenant",
            environment=ENV,
            tenant_id=TENANT,
            display_name="stale",
            health="failing",
            source_offset=5,
            source_event_id="evt_5",
        )
    )
    assert returned.source_offset == 10
    stored = await store.get_node(f"tenant:{TENANT}", environment=ENV)
    assert stored is not None
    assert stored.source_offset == 10
    assert stored.display_name == "current"
    assert stored.health == "healthy"
    assert len(await store.find_nodes(environment=ENV, limit=50)) == 1

    # A newer row still applies.
    await store.upsert_node(
        KyberGraphNode(
            node_key=f"tenant:{TENANT}",
            node_type="Tenant",
            environment=ENV,
            tenant_id=TENANT,
            display_name="newest",
            source_offset=11,
        )
    )
    final = await store.get_node(f"tenant:{TENANT}", environment=ENV)
    assert final is not None
    assert final.source_offset == 11
    assert final.display_name == "newest"


async def test_out_of_order_ledger_batch_produces_the_correct_final_state():
    """Rows delivered out of order converge on the highest offset."""
    ledger = FakeLedger(
        [_row(3, "entity"), _row(1, "entity"), _row(2, "entity")], sorted_output=False
    )
    store = _store()
    result = await _projector(ledger, store).project_tenant(TENANT)
    assert result["last_offset"] == 3
    node = await store.get_node(f"tenant:{TENANT}", environment=ENV)
    assert node is not None
    assert node.source_offset == 3
    assert node.source_event_id == "evt_3"


async def test_tenant_id_is_refused_on_a_non_tenant_scoped_node_type():
    """A Service node may not carry a tenant — that would be tenant data here."""
    store = _store()
    assert "Service" not in TENANT_SCOPED_NODE_TYPES
    with pytest.raises(AetherError) as excinfo:
        await store.upsert_node(
            KyberGraphNode(
                node_key="service:api",
                node_type="Service",
                environment=ENV,
                tenant_id=TENANT,
            )
        )
    assert "tenant_id" in str(excinfo.value)
    assert not await store.find_nodes(node_type="Service", limit=10)

    # The same node without a tenant is fine.
    await store.upsert_node(
        KyberGraphNode(node_key="service:api", node_type="Service", environment=ENV)
    )
    assert len(await store.find_nodes(node_type="Service", environment=ENV, limit=10)) == 1


async def test_edges_are_keyed_by_source_type_target():
    """A duplicate relationship is one row, whatever edge_id it was given."""
    store = _store()
    first = KyberGraphEdge(
        source_node_key=f"tenant:{TENANT}",
        target_node_key=f"tenant_graph:{TENANT}",
        relationship_type="OWNS_GRAPH",
        environment=ENV,
        tenant_id=TENANT,
        source_offset=1,
    )
    duplicate = KyberGraphEdge(
        source_node_key=f"tenant:{TENANT}",
        target_node_key=f"tenant_graph:{TENANT}",
        relationship_type="OWNS_GRAPH",
        environment=ENV,
        tenant_id=TENANT,
        source_offset=2,
    )
    assert first.idempotency_key == duplicate.idempotency_key
    assert first.edge_id != duplicate.edge_id

    await store.upsert_edge(first)
    await store.upsert_edge(duplicate)
    edges = await store.edges_from(f"tenant:{TENANT}", environment=ENV)
    assert len(edges) == 1
    assert edges[0].edge_id == first.edge_id
    assert edges[0].source_offset == 2

    # A different relationship type between the same pair is a different edge.
    await store.upsert_edge(
        KyberGraphEdge(
            source_node_key=f"tenant:{TENANT}",
            target_node_key=f"tenant_graph:{TENANT}",
            relationship_type="DEPENDS_ON",
            environment=ENV,
        )
    )
    assert len(await store.edges_from(f"tenant:{TENANT}", environment=ENV)) == 2


async def test_expired_edges_are_hidden_but_retained():
    """Expiry closes the validity window instead of deleting history."""
    store = _store()
    edge = KyberGraphEdge(
        source_node_key="service:api",
        target_node_key="worker_role:job_worker",
        relationship_type="RUNS",
        environment=ENV,
    )
    await store.upsert_edge(edge)
    await store.expire_edge(edge, at=_NOW.isoformat())

    assert await store.edges_from("service:api", environment=ENV) == []
    retained = await store.edges_from("service:api", environment=ENV, include_expired=True)
    assert len(retained) == 1
    assert retained[0].valid_to == _NOW.isoformat()


async def test_offsets_are_per_tenant_and_single_rowed():
    """One offset row per (projection, tenant), re-saved in place."""
    store = _store()
    first = await store.offset_for(PROJECTION_NAME, TENANT)
    assert first.last_offset == 0
    await store.save_offset(first.model_copy(update={"last_offset": 4}))
    await store.save_offset(first.model_copy(update={"last_offset": 9}))

    assert (await store.offset_for(PROJECTION_NAME, TENANT)).last_offset == 9
    assert (await store.offset_for(PROJECTION_NAME, "tenant_other")).last_offset == 0
    assert len(await store.list_offsets(PROJECTION_NAME)) == 1


# ── Topology ─────────────────────────────────────────────────────────────────

async def test_sync_topology_reports_missing_inputs_instead_of_inventing_nodes():
    """What cannot be derived is named, not fabricated."""
    store = _store()
    report = await sync_topology(store, environment=ENV)

    assert report["missing_inputs"], "underivable topology must be reported"
    assert "release_and_deployment_nodes" in report["missing_inputs"]
    assert "surface_to_service_edges" in report["missing_inputs"]

    # Nothing was invented to fill those gaps.
    assert await store.find_nodes(node_type="Release", environment=ENV, limit=10) == []
    assert await store.find_nodes(node_type="Deployment", environment=ENV, limit=10) == []


async def test_sync_topology_is_derived_and_idempotent():
    """Topology comes from roles.py and the capability registry, and converges."""
    store = _store()
    first = await sync_topology(store, environment=ENV)
    assert first["service_nodes"] == len(service_nodes()) > 1
    assert first["feature_surface_nodes"] == len(feature_surface_nodes()) > 0
    assert first["edges_upserted"] == len(worker_role_edges()) > 0

    services = await store.find_nodes(node_type="Service", environment=ENV, limit=100)
    assert {"service:api", "service:maintenance"} <= {s.node_key for s in services}
    surfaces = await store.find_nodes(node_type="FeatureSurface", environment=ENV, limit=100)
    assert "feature_surface:graph" in {s.node_key for s in surfaces}

    await sync_topology(store, environment=ENV)
    assert len(await store.find_nodes(environment=ENV, limit=500)) == first["nodes_upserted"]
    runs = await store.edges_from(
        "service:maintenance", relationship_type="RUNS", environment=ENV, limit=100
    )
    assert "worker_role:kyber_retention_sweep" in {e.target_node_key for e in runs}


async def test_topology_and_ledger_projection_share_one_graph():
    """Both writers converge on the same environment-scoped graph."""
    store = _store()
    await sync_topology(store, environment=ENV)
    await _projector(FakeLedger([_row(1, "entity")]), store).project_tenant(TENANT)

    assert await store.get_node("service:api", environment=ENV) is not None
    assert await store.get_node(f"tenant:{TENANT}", environment=ENV) is not None
    # Tenant nodes are tenant-scoped; service nodes are not.
    assert (await store.get_node("service:api", environment=ENV)).tenant_id is None


def test_worker_factory_is_zero_arg():
    """The supervisor registers the projector as an ordinary WorkerSpec factory."""
    coro = build_kyber_graph_projector_coro()
    try:
        assert hasattr(coro, "send")
    finally:
        coro.close()
