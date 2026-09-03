"""graph_history_replay (temporal360 T2.1) — knowledge-time reconstruction.

The authority reconstructs the graph state Aether actually had at a knowledge
instant τ (KNOWN_THEN) from the append-only ledger, purely as a read:
``recorded_at <= τ`` rows replayed in ledger order, digest-verifiable, never
mutating the ledger. These tests drive the in-memory ledger with explicit
``recorded_at`` instants so the prefix boundaries are deterministic.
"""

from __future__ import annotations

import uuid

import pytest

from repositories.graph_mutation_ledger import (
    GraphMutationLedgerRepository,
    reset_graph_ledger_memory,
)
from shared.common.common import BadRequestError, parse_iso
from shared.graph.graph import Vertex
from shared.graph.mutation_gateway import replay_ledger, replay_state
from shared.graph.mutation_models import MutationRecord

from services.temporal360.history_replay import GraphHistoryReplay

TENANT = "tenant_t360"
OTHER_TENANT = "tenant_other"

T1 = "2026-01-01T00:00:00+00:00"  # node a created (status active)
T2 = "2026-01-02T00:00:00+00:00"  # node b created
T3 = "2026-01-03T00:00:00+00:00"  # edge a->b SAME_AS created
T4 = "2026-01-04T00:00:00+00:00"  # node a superseded -> status archived
T5 = "2026-01-05T00:00:00+00:00"  # edge a->b revoked (corrected away)


@pytest.fixture(autouse=True)
def _reset_ledger():
    reset_graph_ledger_memory()
    yield
    reset_graph_ledger_memory()


def _at(value: str):
    return parse_iso(value)


async def _append_node(
    ledger: GraphMutationLedgerRepository,
    *,
    at: str,
    node_id: str,
    status: str,
    key: str,
) -> None:
    record = MutationRecord(
        mutation_id=str(uuid.uuid4()),
        tenant_id=TENANT,
        aggregate_type="node",
        aggregate_id=node_id,
        operation="node_updated" if key.endswith("-supersede") else "node_created",
        recorded_at=_at(at),
        valid_from=_at(at),
        idempotency_key=key,
    )
    payload = {
        "kind": "node",
        "vertex_type": "User",
        "vertex_id": node_id,
        "properties": {"tenant_id": TENANT, "kind": "human", "status": status},
    }
    outcome = await ledger.append(record, payload)
    assert outcome.inserted


async def _append_edge(
    ledger: GraphMutationLedgerRepository, *, at: str, key: str
) -> None:
    record = MutationRecord(
        mutation_id=str(uuid.uuid4()),
        tenant_id=TENANT,
        aggregate_type="edge",
        aggregate_id="a:b:SAME_AS",
        operation="edge_created",
        recorded_at=_at(at),
        valid_from=_at(at),
        idempotency_key=key,
    )
    payload = {
        "kind": "edge",
        "edge_type": "SAME_AS",
        "from_vertex_id": "a",
        "to_vertex_id": "b",
        "properties": {"tenant_id": TENANT},
    }
    outcome = await ledger.append(record, payload)
    assert outcome.inserted


async def _append_revocation(
    ledger: GraphMutationLedgerRepository, *, at: str, key: str
) -> None:
    record = MutationRecord(
        mutation_id=str(uuid.uuid4()),
        tenant_id=TENANT,
        aggregate_type="edge",
        aggregate_id="a:b:SAME_AS",
        operation="edge_expired",
        recorded_at=_at(at),
        idempotency_key=key,
    )
    payload = {
        "kind": "edge_revocation",
        "edge_type": "SAME_AS",
        "from_vertex_id": "a",
        "to_vertex_id": "b",
        "reason": "corrected",
    }
    outcome = await ledger.append(record, payload)
    assert outcome.inserted


async def _scenario(ledger: GraphMutationLedgerRepository) -> None:
    """A deterministic known-time ledger: two nodes, one edge, then a vertex
    supersession and an edge revocation."""
    await _append_node(ledger, at=T1, node_id="a", status="active", key="a-create")
    await _append_node(ledger, at=T2, node_id="b", status="active", key="b-create")
    await _append_edge(ledger, at=T3, key="edge-ab-create")
    await _append_node(ledger, at=T4, node_id="a", status="archived", key="a-supersede")
    await _append_revocation(ledger, at=T5, key="edge-ab-revoke")


def _vertex_by_id(state, vertex_id: str) -> Vertex:
    return state.vertices[vertex_id]


class TestKnownAsOfReconstruction:
    @pytest.mark.asyncio
    async def test_prefix_at_tau_replays_known_then_state(self) -> None:
        ledger = GraphMutationLedgerRepository()
        await _scenario(ledger)
        replay = GraphHistoryReplay(ledger)

        # Between T1 and T2 only node a is known (status active).
        early = await replay.known_as_of(TENANT, "2026-01-01T12:00:00+00:00")
        assert early.row_count == 1
        assert set(early.state.vertices) == {"a"}
        assert _vertex_by_id(early.state, "a").properties["status"] == "active"
        assert early.state.edges == []

        # Between T3 and T4 the edge is known; node a is still active.
        mid = await replay.known_as_of(TENANT, "2026-01-03T12:00:00+00:00")
        assert mid.row_count == 3
        assert [e.edge_type for e in mid.state.edges] == ["SAME_AS"]
        assert _vertex_by_id(mid.state, "a").properties["status"] == "active"

        # After T4 the supersession is known (KNOWN_THEN at T4.5).
        later = await replay.known_as_of(TENANT, "2026-01-04T12:00:00+00:00")
        assert later.row_count == 4
        assert _vertex_by_id(later.state, "a").properties["status"] == "archived"
        # The edge is still present at T4.5 (revoked only at T5).
        assert len(later.state.edges) == 1

        # Distinct prefixes reconstruct to distinct states.
        assert early.state.digest != mid.state.digest != later.state.digest

    @pytest.mark.asyncio
    async def test_known_now_equals_full_ledger_and_differs_from_known_then(
        self,
    ) -> None:
        ledger = GraphMutationLedgerRepository()
        await _scenario(ledger)
        replay = GraphHistoryReplay(ledger)

        now = await replay.known_now(TENANT)
        assert now.row_count == 5
        # The revoked edge stays in the canonical edge list, flagged revoked —
        # live reads treat it as gone (corrections_between reasons over that).
        assert len(now.state.edges) == 1
        assert now.state.edges[0].properties["revoked"] is True
        assert _vertex_by_id(now.state, "a").properties["status"] == "archived"

        # A far-future as-of is the full ledger (KNOWN_NOW == full replay).
        future = await replay.known_as_of(TENANT, "2099-01-01T00:00:00+00:00")
        assert future.state.digest == now.state.digest

        # KNOWN_THEN at T4.5 (edge still live) differs from KNOWN_NOW (revoked).
        then = await replay.known_as_of(TENANT, "2026-01-04T12:00:00+00:00")
        assert then.state.digest != now.state.digest

    @pytest.mark.asyncio
    async def test_reconstruction_is_digest_verifiable_and_deterministic(
        self,
    ) -> None:
        ledger = GraphMutationLedgerRepository()
        await _scenario(ledger)
        replay = GraphHistoryReplay(ledger)

        first = await replay.known_as_of(TENANT, "2026-01-02T12:00:00+00:00")
        second = await replay.known_as_of(TENANT, "2026-01-02T12:00:00+00:00")
        assert first.state.digest == second.state.digest

        # The snapshot digest equals replaying exactly its ledger prefix again —
        # a reconstruction is reproducible from the prefix alone.
        rows = await ledger.list_records_known_as_of(
            TENANT, "2026-01-02T12:00:00+00:00"
        )
        assert first.row_count == len(rows) == 2
        assert replay_state(rows).digest == first.state.digest

        # The refactored digest replay agrees with the state-returning replay.
        full = await ledger.list_records(TENANT)
        assert replay_ledger(full) == replay_state(full).digest


class TestCorrections:
    @pytest.mark.asyncio
    async def test_known_then_vs_known_now_surfaces_supersession_and_revocation(
        self,
    ) -> None:
        ledger = GraphMutationLedgerRepository()
        await _scenario(ledger)
        replay = GraphHistoryReplay(ledger)

        then = await replay.known_as_of(TENANT, "2026-01-03T12:00:00+00:00")
        now = await replay.known_now(TENANT)
        report = GraphHistoryReplay.corrections_between(then, now)

        # Node a was superseded active -> archived; the edge was revoked.
        assert report["changed_vertices"] == ["a"]
        assert report["removed_edges"] == [("SAME_AS", "a", "b")]
        assert report["added_edges"] == []
        assert report["removed_vertices"] == []
        # Node b is unchanged; counts stay honest.
        assert report["vertex_count"] == {"then": 2, "now": 2}
        assert report["edge_count"] == {"then": 1, "now": 0}

        # Between T3 and T4 only the vertex supersession is visible.
        interim = await replay.known_as_of(TENANT, "2026-01-03T12:00:00+00:00")
        post = await replay.known_as_of(TENANT, "2026-01-04T12:00:00+00:00")
        mid = GraphHistoryReplay.corrections_between(interim, post)
        assert mid["changed_vertices"] == ["a"]
        assert mid["removed_edges"] == []


class TestReadOnlyAndIsolation:
    @pytest.mark.asyncio
    async def test_authority_reads_only_and_never_mutates_the_ledger(self) -> None:
        ledger = GraphMutationLedgerRepository()
        await _scenario(ledger)
        replay = GraphHistoryReplay(ledger)
        before = len(await ledger.list_records(TENANT))

        await replay.known_as_of(TENANT, "2026-01-03T12:00:00+00:00")
        await replay.known_now(TENANT)
        await replay.digest_known_as_of(TENANT, "2026-01-02T12:00:00+00:00")

        after = len(await ledger.list_records(TENANT))
        assert after == before == 5
        # Nothing appended, nothing superseded: offsets are untouched.
        assert after == 5

    @pytest.mark.asyncio
    async def test_tenant_isolation(self) -> None:
        ledger = GraphMutationLedgerRepository()
        await _scenario(ledger)
        replay = GraphHistoryReplay(ledger)

        other = await replay.known_now(OTHER_TENANT)
        assert other.row_count == 0
        assert other.state.vertices == {}
        assert other.state.edges == []
        # The empty-state digest differs from the populated tenant's.
        assert other.state.digest != (
            await replay.known_now(TENANT)
        ).state.digest

    @pytest.mark.asyncio
    async def test_unparseable_as_of_raises(self) -> None:
        ledger = GraphMutationLedgerRepository()
        replay = GraphHistoryReplay(ledger)
        with pytest.raises(BadRequestError):
            await replay.known_as_of(TENANT, "not-an-instant")
