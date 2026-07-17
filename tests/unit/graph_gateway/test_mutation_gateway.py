"""GraphMutationGateway (WP2.5) — pipeline, mode ladder, bitemporal ledger,
tenant isolation, and determinism digests.

All tests run on the in-memory GraphClient backend + in-memory ledger
(AETHER_ENV=local, no DATABASE_URL), which share transaction semantics with
the asyncpg paths by construction (see repositories/graph_mutation_ledger.py).
"""

from __future__ import annotations

import pytest

from repositories.graph_mutation_ledger import (
    GraphMutationLedgerRepository,
    reset_graph_ledger_memory,
)
from shared.graph.edge_properties import build_edge_properties, make_edge_idempotency_key
from shared.graph.graph import Edge, GraphClient, Vertex
from shared.graph.mutation_gateway import (
    EdgeRevocation,
    GraphMutationGateway,
    MutationIntent,
    current_graph_digest,
    replay_ledger,
)
from shared.graph.write_validator import GraphWriteValidationError

TENANT = "tenant_gw"
OTHER_TENANT = "tenant_other"
VALID_FROM = "2026-07-01T00:00:00+00:00"


@pytest.fixture(autouse=True)
def _reset_ledger():
    reset_graph_ledger_memory()
    yield
    reset_graph_ledger_memory()


@pytest.fixture
def set_mode(monkeypatch):
    def _set(mode: str) -> None:
        # Resolve config.settings at CALL time: other suites (e.g.
        # tests/graph) evict backend modules from sys.modules, so a
        # collection-time module reference can go stale. The gateway reads
        # the mode from whatever module is live in sys.modules — patch that.
        import config.settings as settings_module

        monkeypatch.setattr(
            settings_module.settings,
            "temporal_observatory",
            settings_module.TemporalObservatoryConfig(mutation_gateway_mode=mode),
        )

    return _set


def _edge(
    tenant: str = TENANT,
    edge_type: str = "SAME_AS",
    from_id: str = "entity_a",
    to_id: str = "entity_b",
    source_event_id: str = "evt-1",
    confidence: float = 0.9,
    **extra,
) -> Edge:
    props = build_edge_properties(
        tenant_id=tenant,
        edge_type=edge_type,
        from_vertex_id=from_id,
        to_vertex_id=to_id,
        actor_kind="system",
        actor_id="identity_resolver",
        provenance="test",
        valid_from=VALID_FROM,
        confidence=confidence,
        source_event_id=source_event_id,
        **extra,
    )
    return Edge(
        edge_type=edge_type, from_vertex_id=from_id, to_vertex_id=to_id, properties=props
    )


def _gateway() -> tuple[GraphMutationGateway, GraphClient, GraphMutationLedgerRepository]:
    client = GraphClient()
    ledger = GraphMutationLedgerRepository()
    return GraphMutationGateway(graph_client=client, ledger=ledger), client, ledger


# ── Mode: off — pure delegation, zero ledger ─────────────────────────────────


@pytest.mark.asyncio
async def test_off_mode_delegates_and_writes_no_ledger(set_mode):
    set_mode("off")
    gateway, client, ledger = _gateway()
    outcome = await gateway.apply(
        MutationIntent(operation="edge_created", tenant_id=TENANT, edge=_edge())
    )
    assert outcome.mode == "off" and outcome.applied
    assert outcome.record is None and not outcome.ledger_recorded
    edges = await client.get_edges("entity_a")
    assert len(edges) == 1
    assert await ledger.list_records(TENANT) == []


# ── Mode: shadow — delegate AND ledger; ledger failure never breaks writes ──


@pytest.mark.asyncio
async def test_shadow_mode_projects_and_appends_ledger(set_mode):
    set_mode("shadow")
    gateway, client, ledger = _gateway()
    outcome = await gateway.apply(
        MutationIntent(
            operation="edge_created",
            tenant_id=TENANT,
            edge=_edge(),
            actor_kind="service",
            actor_id="identity",
            causality_class="observed_sequence",
            source_event_id="evt-1",
            evidence_refs=["evt-1"],
        )
    )
    assert outcome.applied and outcome.ledger_recorded and not outcome.deduplicated
    assert len(await client.get_edges("entity_a")) == 1
    rows = await ledger.list_records(TENANT)
    assert len(rows) == 1
    row = rows[0]
    assert row["operation"] == "edge_created"
    assert row["aggregate_type"] == "edge"
    assert row["aggregate_id"] == "SAME_AS:entity_a:entity_b"
    assert row["causality_class"] == "observed_sequence"
    assert row["evidence_refs"] == ["evt-1"]
    assert row["payload"]["kind"] == "edge"
    # Idempotency reuses the canonical helper.
    assert row["idempotency_key"] == make_edge_idempotency_key(
        TENANT, "SAME_AS", "entity_a", "entity_b", "evt-1"
    )
    # Bitemporal names carried verbatim.
    assert row["valid_from"].startswith("2026-07-01")
    assert row["recorded_at"] is not None and row["superseded_at"] is None


@pytest.mark.asyncio
async def test_shadow_ledger_failure_never_fails_the_write(set_mode):
    set_mode("shadow")

    class _ExplodingLedger:
        async def append(self, record, fact_payload=None):
            raise RuntimeError("ledger down")

    client = GraphClient()
    gateway = GraphMutationGateway(graph_client=client, ledger=_ExplodingLedger())
    outcome = await gateway.apply(
        MutationIntent(operation="edge_created", tenant_id=TENANT, edge=_edge())
    )
    assert outcome.applied  # the write survived
    assert not outcome.ledger_recorded
    assert len(await client.get_edges("entity_a")) == 1


# ── Idempotency: double-apply → one ledger row ───────────────────────────────


@pytest.mark.asyncio
async def test_idempotent_double_apply_one_ledger_row_shadow(set_mode):
    set_mode("shadow")
    gateway, _client, ledger = _gateway()
    intent = lambda: MutationIntent(  # noqa: E731
        operation="edge_created", tenant_id=TENANT, edge=_edge()
    )
    first = await gateway.apply(intent())
    second = await gateway.apply(intent())
    assert first.ledger_recorded and not first.deduplicated
    assert second.deduplicated and not second.ledger_recorded
    assert len(await ledger.list_records(TENANT)) == 1


@pytest.mark.asyncio
async def test_enforce_dedup_short_circuits_projection(set_mode):
    set_mode("enforce")
    gateway, client, ledger = _gateway()
    intent = lambda: MutationIntent(  # noqa: E731
        operation="edge_created", tenant_id=TENANT, edge=_edge()
    )
    first = await gateway.apply(intent())
    second = await gateway.apply(intent())
    assert first.applied and first.ledger_recorded
    assert second.deduplicated and not second.applied
    # Enforce dedup happens BEFORE projection: exactly one projected edge.
    assert len(await client.get_edges("entity_a")) == 1
    assert len(await ledger.list_records(TENANT)) == 1


# ── Enforce: validation and ledger failures propagate ────────────────────────


@pytest.mark.asyncio
async def test_enforce_rejects_invalid_edge(set_mode):
    set_mode("enforce")
    gateway, client, _ledger = _gateway()
    bad_edge = Edge(
        edge_type="SAME_AS",
        from_vertex_id="entity_a",
        to_vertex_id="entity_b",
        properties={"tenant_id": TENANT},  # missing required properties
    )
    with pytest.raises(GraphWriteValidationError):
        await gateway.apply(
            MutationIntent(operation="edge_created", tenant_id=TENANT, edge=bad_edge)
        )
    assert await client.get_edges("entity_a") == []


@pytest.mark.asyncio
async def test_enforce_ledger_failure_propagates_and_blocks_projection(set_mode):
    set_mode("enforce")

    class _ExplodingLedger:
        async def append(self, record, fact_payload=None):
            raise RuntimeError("ledger down")

    client = GraphClient()
    gateway = GraphMutationGateway(graph_client=client, ledger=_ExplodingLedger())
    with pytest.raises(RuntimeError, match="ledger down"):
        await gateway.apply(
            MutationIntent(operation="edge_created", tenant_id=TENANT, edge=_edge())
        )
    assert await client.get_edges("entity_a") == []


# ── Shape stage ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_operation_rejected(set_mode):
    set_mode("shadow")
    gateway, _client, _ledger = _gateway()
    with pytest.raises(ValueError, match="unknown mutation operation"):
        await gateway.apply(
            MutationIntent(operation="edge_invented", tenant_id=TENANT, edge=_edge())
        )


@pytest.mark.asyncio
async def test_intent_requires_exactly_one_target(set_mode):
    set_mode("shadow")
    gateway, _client, _ledger = _gateway()
    with pytest.raises(ValueError, match="exactly one"):
        await gateway.apply(MutationIntent(operation="edge_created", tenant_id=TENANT))


# ── Bitemporal supersession ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_second_version_closes_the_first(set_mode):
    set_mode("shadow")
    gateway, _client, ledger = _gateway()
    v1 = await gateway.apply(
        MutationIntent(operation="edge_created", tenant_id=TENANT, edge=_edge())
    )
    v2 = await gateway.apply(
        MutationIntent(
            operation="edge_versioned",
            tenant_id=TENANT,
            edge=_edge(confidence=0.95, source_event_id="evt-2"),
            idempotency_key="explicit-v2-key",
        )
    )
    assert v1.after_version_id and v2.after_version_id
    assert v2.before_version_id == v1.after_version_id  # chained versions

    versions = await ledger.list_fact_versions(
        TENANT, aggregate_id="SAME_AS:entity_a:entity_b"
    )
    assert len(versions) == 2
    by_id = {v["version_id"]: v for v in versions}
    closed = by_id[v1.after_version_id]
    open_ = by_id[v2.after_version_id]
    # The first version is closed with BOTH bitemporal end markers set...
    assert closed["valid_to"] is not None and closed["superseded_at"] is not None
    # ...and the second stays open.
    assert open_["superseded_at"] is None
    assert open_["created_by_mutation_id"] == v2.mutation_id


# ── Tenant isolation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ledger_records_never_cross_tenants(set_mode):
    set_mode("shadow")
    gateway, _client, ledger = _gateway()
    await gateway.apply(
        MutationIntent(operation="edge_created", tenant_id=TENANT, edge=_edge())
    )
    await gateway.apply(
        MutationIntent(
            operation="edge_created",
            tenant_id=OTHER_TENANT,
            edge=_edge(tenant=OTHER_TENANT),
        )
    )
    rows_a = await ledger.list_records(TENANT)
    rows_b = await ledger.list_records(OTHER_TENANT)
    assert {r["tenant_id"] for r in rows_a} == {TENANT}
    assert {r["tenant_id"] for r in rows_b} == {OTHER_TENANT}
    # Same edge tuple, two tenants → two distinct ledger rows (key is
    # tenant-scoped, so no cross-tenant dedupe).
    assert len(rows_a) == 1 and len(rows_b) == 1


# ── Revocation path ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_revocation_projects_and_ledgers(set_mode):
    set_mode("shadow")
    gateway, client, ledger = _gateway()
    await gateway.apply(
        MutationIntent(operation="edge_created", tenant_id=TENANT, edge=_edge())
    )
    outcome = await gateway.apply(
        MutationIntent(
            operation="identity_split",
            tenant_id=TENANT,
            revocation=EdgeRevocation(
                from_vertex_id="entity_a",
                to_vertex_id="entity_b",
                edge_type="SAME_AS",
                reason="fragment_split",
            ),
        )
    )
    assert outcome.applied and outcome.projection_result == 1  # one edge revoked
    assert await client.get_edges("entity_a") == []  # revoked edges are hidden
    rows = await ledger.list_records(TENANT)
    assert [r["operation"] for r in rows] == ["edge_created", "identity_split"]
    assert rows[1]["payload"]["kind"] == "edge_revocation"


# ── Determinism substrate ────────────────────────────────────────────────────


async def _shadow_scenario(gateway: GraphMutationGateway) -> None:
    """Vertices + edge + second version + revocation, all through the gateway."""
    for vertex_id in ("entity_a", "entity_b"):
        await gateway.apply(
            MutationIntent(
                operation="node_created",
                tenant_id=TENANT,
                vertex=Vertex(
                    vertex_type="User",
                    vertex_id=vertex_id,
                    properties={"tenant_id": TENANT, "kind": "human"},
                ),
            )
        )
    await gateway.apply(
        MutationIntent(operation="edge_created", tenant_id=TENANT, edge=_edge())
    )
    await gateway.apply(
        MutationIntent(
            operation="edge_versioned",
            tenant_id=TENANT,
            edge=_edge(confidence=0.95, source_event_id="evt-2"),
            idempotency_key="v2-key",
        )
    )
    await gateway.apply(
        MutationIntent(
            operation="edge_expired",
            tenant_id=TENANT,
            revocation=EdgeRevocation(
                from_vertex_id="entity_a",
                to_vertex_id="entity_b",
                edge_type="SAME_AS",
                reason="expired",
            ),
        )
    )


@pytest.mark.asyncio
async def test_replay_is_deterministic_across_runs(set_mode):
    set_mode("shadow")
    gateway, _client, ledger = _gateway()
    await _shadow_scenario(gateway)
    rows = await ledger.list_records(TENANT)
    assert len(rows) == 5
    assert replay_ledger(rows) == replay_ledger(rows)  # same records → same digest
    # And replaying a fresh copy of the rows still matches.
    rows_again = await ledger.list_records(TENANT)
    assert replay_ledger(rows) == replay_ledger(rows_again)


@pytest.mark.asyncio
async def test_shadow_ledger_replays_to_the_directly_written_graph(set_mode):
    """Ledger written in shadow mode replays to a graph equal to what the
    delegated direct writes produced (digest parity)."""
    set_mode("shadow")
    gateway, client, ledger = _gateway()
    await _shadow_scenario(gateway)
    rows = await ledger.list_records(TENANT)
    assert replay_ledger(rows) == await current_graph_digest(client, TENANT)


@pytest.mark.asyncio
async def test_digest_is_tenant_scoped(set_mode):
    set_mode("shadow")
    gateway, client, _ledger = _gateway()
    await _shadow_scenario(gateway)
    # A different tenant's view of the same backend is empty → different digest.
    assert await current_graph_digest(client, TENANT) != await current_graph_digest(
        client, OTHER_TENANT
    )


@pytest.mark.asyncio
async def test_checkpoint_records_replay_digest(set_mode):
    set_mode("shadow")
    gateway, client, ledger = _gateway()
    await _shadow_scenario(gateway)
    digest = await current_graph_digest(client, TENANT)
    rows = await ledger.list_records(TENANT)
    checkpoint = await ledger.record_checkpoint(
        TENANT, scope="tenant", digest=digest, mutation_offset=rows[-1]["ledger_offset"]
    )
    assert checkpoint["digest"] == digest
    assert checkpoint["mutation_offset"] == 5
