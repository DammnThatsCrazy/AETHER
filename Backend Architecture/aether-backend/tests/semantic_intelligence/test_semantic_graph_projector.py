"""Semantic graph projector — project Gold relationship state into the graph.

Proves the projector closes the "Gold is computed but never reaches the graph"
gap: a durable ``gold_relationship_semantic_state`` row becomes a governed
``SEMANTIC_RELATES_TO`` edge written THROUGH the mutation gateway (never a
direct graph write), idempotently, tenant-scoped — and that the overlay reads
real relationship edges instead of a hardcoded ``[]``.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
from typing import Any

import pytest

from config.settings import settings
from repositories.graph_mutation_ledger import (
    GraphMutationLedgerRepository,
    reset_graph_ledger_memory,
)
from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import graph_projector as projector_mod
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.engine import classify_event, get_store, set_store
from services.semantic_intelligence.graph_projector import (
    SEMANTIC_EDGE_TYPE,
    edge_from_relationship,
    project_pair,
    project_tenant,
    vertex_from_entity,
)
from services.semantic_intelligence.repositories.base_fact_repo import (
    SemanticFactRepository,
)
from services.semantic_intelligence.repositories.review_queue_repo import (
    SemanticReviewQueueRepository,
)
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore
from shared.graph.edge_properties import make_edge_idempotency_key
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.graph.mutation_gateway import GraphMutationGateway
from shared.graph.mutation_intents import edge_intent
from shared.graph.write_validator import GraphWriteValidator

TENANT = "tenant_projector"
OTHER_TENANT = "tenant_projector_other"
SOURCE = "profile_alice"
TARGET = "prod_widget"


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    # Per-tenant projector locks are bound to the event loop that first used
    # them; pytest-asyncio gives each test a fresh loop, so drop the cache
    # between tests (production keeps one long-lived loop and never clears it).
    projector_mod._TENANT_PROJECT_LOCKS.clear()
    original = get_store()
    set_store(DurableSemanticSentimentStore())
    service_mod.set_semantic_service(SemanticIntelligenceService())
    yield
    set_store(original)
    service_mod.set_semantic_service(SemanticIntelligenceService())
    reset_in_memory_stores()
    projector_mod._TENANT_PROJECT_LOCKS.clear()


async def _graph() -> GraphClient:
    client = GraphClient()
    await client.connect()
    return client


async def _seed_relationship(
    tenant: str, source: str, target: str, *, content: str = "great product, I recommend it"
) -> None:
    """Classify an actor→subject observation and persist its Gold relationship."""
    obs, sentiments = await classify_event(
        {
            "source_event_id": f"e_{tenant}_{source}_{target}",
            "source_type": "feedback",
            "actor_ref": source,
            "primary_subject_ref": target,
            "content": content,
        },
        tenant,
    )
    store = get_store()
    await store.put_semantic(obs)
    for s in sentiments:
        await store.put_sentiment(s)
    await service_mod.get_semantic_service().recompute_relationship_state(tenant, source, target)


async def _semantic_edges(client: GraphClient, source: str) -> list:
    return [e for e in await client.get_edges(source, edge_type=EdgeType.SEMANTIC_RELATES_TO)]


async def test_projects_relationship_gold_as_governed_edge():
    await _seed_relationship(TENANT, SOURCE, TARGET)
    client = await _graph()

    report = await project_tenant(TENANT, graph_client=client)

    assert report.projected == 1
    assert report.failed == 0
    edges = await _semantic_edges(client, SOURCE)
    assert len(edges) == 1
    edge = edges[0]
    assert edge.to_vertex_id == TARGET
    assert edge.edge_type == EdgeType.SEMANTIC_RELATES_TO == "SEMANTIC_RELATES_TO"
    # Governed provenance + tenant label are on the edge, never raw content.
    assert edge.properties.get("tenantId") == TENANT
    assert edge.properties.get("relationship_ref") == f"rel:{SOURCE}->{TARGET}"
    assert "stance_alignment" in edge.properties


async def test_projection_is_idempotent():
    await _seed_relationship(TENANT, SOURCE, TARGET)
    client = await _graph()

    first = await project_tenant(TENANT, graph_client=client)
    second = await project_tenant(TENANT, graph_client=client)

    assert first.projected == 1
    assert second.projected == 0
    assert second.skipped_existing == 1
    # No duplicate edge on the second sweep.
    assert len(await _semantic_edges(client, SOURCE)) == 1


async def test_projection_is_tenant_scoped():
    await _seed_relationship(TENANT, SOURCE, TARGET)
    await _seed_relationship(OTHER_TENANT, SOURCE, TARGET)
    client = await _graph()

    await project_tenant(TENANT, graph_client=client)
    edges = await _semantic_edges(client, SOURCE)
    # Only TENANT's edge exists; OTHER_TENANT was not projected into this client.
    assert [e.properties.get("tenantId") for e in edges] == [TENANT]

    await project_tenant(OTHER_TENANT, graph_client=client)
    edges = await _semantic_edges(client, SOURCE)
    assert sorted(e.properties.get("tenantId") for e in edges) == sorted([TENANT, OTHER_TENANT])


async def test_overlay_service_returns_real_relationship_edges():
    await _seed_relationship(TENANT, SOURCE, TARGET)
    service = service_mod.get_semantic_service()

    edges = await service.list_relationship_edges(TENANT)

    assert len(edges) == 1
    assert edges[0]["source_ref"] == SOURCE
    assert edges[0]["target_ref"] == TARGET
    assert "stance_alignment" in edges[0]
    # Tenant isolation: another tenant sees none of this.
    assert await service.list_relationship_edges(OTHER_TENANT) == []


async def test_degenerate_pairs_are_never_projected():
    # A self-loop / unknown endpoint is skipped, never a fabricated edge.
    assert edge_from_relationship(TENANT, {"source_ref": "x", "target_ref": "x"}) is None
    assert edge_from_relationship(TENANT, {"source_ref": "", "target_ref": "y"}) is None
    assert (
        edge_from_relationship(TENANT, {"source_ref": "unknown_subject", "target_ref": "y"}) is None
    )


async def test_projected_edge_is_canonical_and_passes_strict_validation():
    # Codex P1 (line 100): the edge must be canonical BEFORE the gateway, because
    # off-mode passes it straight to GraphClient.add_edge whose Neptune path
    # rejects a write missing any REQUIRED_EDGE_PROPERTIES member.
    await _seed_relationship(TENANT, SOURCE, TARGET)
    client = await _graph()

    await project_tenant(TENANT, graph_client=client)

    edges = await _semantic_edges(client, SOURCE)
    assert len(edges) == 1
    props = edges[0].properties
    for key in (
        "tenant_id",
        "idempotency_key",
        "actor_kind",
        "actor_id",
        "schema_version",
        "provenance",
        "valid_from",
        "confidence",
    ):
        assert props.get(key) not in (None, ""), f"missing required edge property {key!r}"
    # Stable, deterministic edge identity derived from the Gold row's natural key
    # PLUS a content revision (folded into the source_event_id component) so a
    # recomputed row with changed content re-projects. correlation_id keeps the
    # bare pair ref for traceability.
    rel_ref = f"rel:{SOURCE}->{TARGET}"
    assert props["source_event_id"].startswith(f"{rel_ref}@")
    assert props.get("correlation_id") == rel_ref
    assert props.get("content_revision")
    assert props["idempotency_key"] == make_edge_idempotency_key(
        TENANT,
        EdgeType.SEMANTIC_RELATES_TO,
        SOURCE,
        TARGET,
        source_event_id=props["source_event_id"],
    )
    assert props["actor_kind"] == "system"
    assert props["actor_id"] == "semantic_graph_projector"
    assert props["tenant_id"] == TENANT
    # The canonical property set satisfies the strict production validator.
    result = GraphWriteValidator().validate(edges[0], env="production")
    assert result.passed, result.violations


@pytest.mark.parametrize(
    ("bad_confidence", "target"),
    [
        (1.5, "prod_conf_oob"),     # out-of-range non-null confidence
        ("high", "prod_conf_bad"),  # malformed non-null confidence
    ],
)
async def test_malformed_confidence_is_clamped_not_persisted_raw(
    bad_confidence: Any, target: str
):
    # Codex P2 (graph_projector.py edge_from_relationship): build_edge_properties
    # received the safe ``_bounded_confidence(...)`` result, but the semantic
    # dict's RAW ``confidence`` (from the Gold row) overwrote that canonical
    # property during ``props.update``. Enforce mode then rejected the edge under
    # the validator's [0.0, 1.0] rule; off mode persisted invalid confidence
    # data. The projected edge must carry the bounded (clamped) value — 1.0 for
    # both an out-of-range number and an unparseable string — and satisfy the
    # strict production validator so enforce mode accepts it.
    await _upsert_raw_relationship(TENANT, SOURCE, target, bad_confidence)
    client = await _graph()

    report = await project_tenant(TENANT, graph_client=client)

    assert report.projected == 1
    assert report.failed == 0
    edges = await _semantic_edges(client, SOURCE)
    assert len(edges) == 1
    # The clamped confidence is what lands on the edge, never the raw value.
    assert float(edges[0].properties["confidence"]) == 1.0
    # The canonical property set satisfies the strict production validator (the
    # enforce-mode [0.0, 1.0] rule), so enforce mode accepts the edge.
    result = GraphWriteValidator().validate(edges[0], env="production")
    assert result.passed, result.violations


async def test_projects_full_gold_set_beyond_default_limit():
    # Codex P1 (line 146): list_by_tenant defaults to a 500-row limit; a tenant
    # with more relationships must not be truncated at the first page forever.
    row_count = 510
    for i in range(row_count):
        await _seed_raw_relationship(TENANT, "sub_bulk", f"prod_{i}", i)
    client = await _graph()

    report = await project_tenant(TENANT, graph_client=client)

    assert report.relationships_seen == row_count
    assert report.projected == row_count
    assert report.failed == 0
    assert len(await _semantic_edges(client, "sub_bulk")) == row_count


async def test_overlay_service_returns_full_gold_set_beyond_default_limit():
    # The projector non-truncation claim has a SECOND clause: the overlay read
    # (``list_relationship_edges``) must not truncate either. It pages through
    # ``gold_relationship_semantic_state`` at ``_RELATIONSHIP_PAGE`` (500) rows
    # per call with an offset, so a tenant with more than one page is served in
    # full. Every other overlay test seeds 1-2 relationships, so a revert of
    # ``list_relationship_edges`` to a single 500-limit read would otherwise pass
    # undetected — this seeds a second page's worth and pins the COMPLETE set.
    row_count = 510
    for i in range(row_count):
        await _seed_raw_relationship(TENANT, "sub_overlay", f"prod_{i}", i)
    service = service_mod.get_semantic_service()

    edges = await service.list_relationship_edges(TENANT)

    assert len(edges) == row_count
    assert {e["source_ref"] for e in edges} == {"sub_overlay"}
    assert {e["target_ref"] for e in edges} == {f"prod_{i}" for i in range(row_count)}


async def test_concurrent_sweeps_produce_single_edge():
    # Codex P1 (line 156): two projector passes racing must not both observe "no
    # edge" and append one. The per-tenant lock serialises sweeps in-process.
    await _seed_relationship(TENANT, SOURCE, TARGET)
    client = await _graph()

    first = asyncio.create_task(project_tenant(TENANT, graph_client=client))
    second = asyncio.create_task(project_tenant(TENANT, graph_client=client))
    reports = await asyncio.gather(first, second)

    assert sum(r.projected for r in reports) == 1
    assert sum(r.skipped_existing for r in reports) == 1
    assert len(await _semantic_edges(client, SOURCE)) == 1


async def test_sweep_collapses_duplicate_projections():
    # A pre-existing duplicate (e.g. appended by an earlier replica race) is
    # collapsed to a single live edge by reconciliation.
    await _seed_relationship(TENANT, SOURCE, TARGET)
    client = await _graph()
    repo = SemanticFactRepository("gold_relationship_semantic_state", mode="gold")
    rows = await repo.list_by_tenant(TENANT)
    assert len(rows) == 1
    edge = edge_from_relationship(TENANT, rows[0])
    assert edge is not None
    await client.add_edge(edge)
    await client.add_edge(edge)

    report = await project_tenant(TENANT, graph_client=client)

    # Reconciliation revokes both duplicates, then the sweep re-projects exactly
    # one canonical edge.
    assert report.revoked == 2
    assert report.projected == 1
    assert len(await _semantic_edges(client, SOURCE)) == 1


async def test_nonmemory_scan_retains_replica_raced_duplicate_edges():
    # Codex P1 (graph_projector.py _list_projected_edges_for_tenant): the
    # Neptune/non-memory scan collapsed two live replica-raced edges with the
    # same (type, source, target) into a single entry in the ``seen`` dict
    # BEFORE ``_reconcile_projections`` grouped and counted them. Reconciliation
    # then saw one canonical edge and took its ``len(edges) == 1`` keep path,
    # leaving the duplicate live forever. Every returned edge must be retained
    # so reconciliation sees BOTH (count 2) and collapses the duplicate.
    await _seed_relationship(TENANT, SOURCE, TARGET)
    client = await _graph()
    repo = SemanticFactRepository("gold_relationship_semantic_state", mode="gold")
    rows = await repo.list_by_tenant(TENANT)
    assert len(rows) == 1
    edge = edge_from_relationship(TENANT, rows[0])
    assert edge is not None

    # Two DISTINCT live edges with the same (type, source, target) AND the same
    # idempotency key — the replica-race shape. Simulate the Neptune path by
    # swapping in a non-in-memory backend so the flat-store fast path is skipped
    # and the per-vertex scan (the former ``seen``-dict collapse) is exercised.
    client._backend = _NeptuneLikeBackend(
        vertices=[
            Vertex(
                vertex_type="Profile",
                vertex_id=SOURCE,
                properties={"tenantId": TENANT},
            )
        ],
        edges=[edge, copy.deepcopy(edge)],
    )

    report = await project_tenant(TENANT, graph_client=client)

    # Reconciliation saw BOTH edges for the pair and revoked both duplicates...
    assert report.revoked == 2
    # ...then the sweep re-projected exactly one canonical edge.
    assert report.projected == 1
    live = [
        e
        for e in await client.get_edges(
            SOURCE,
            edge_type=SEMANTIC_EDGE_TYPE,
            direction="out",
        )
        if not (e.properties or {}).get("revoked")
    ]
    assert len(live) == 1
    assert live[0].to_vertex_id == TARGET


async def test_revokes_projection_when_gold_relationship_removed():
    # Codex P1 (line 160): when a Gold relationship disappears (retention /
    # erasure / recomputation), its projection must be revoked, not left alive.
    await _seed_relationship(TENANT, SOURCE, TARGET)
    await _seed_relationship(TENANT, SOURCE, "prod_other")
    client = await _graph()

    report = await project_tenant(TENANT, graph_client=client)
    assert report.projected == 2

    repo = SemanticFactRepository("gold_relationship_semantic_state", mode="gold")
    removed = await repo.delete_by_subject(TENANT, f"rel:{SOURCE}->{TARGET}")
    assert removed == 1

    second = await project_tenant(TENANT, graph_client=client)
    assert second.revoked == 1
    edges = await _semantic_edges(client, SOURCE)
    assert [e.to_vertex_id for e in edges] == ["prod_other"]


async def test_sweep_replaces_legacy_noncanonical_edge():
    # An edge written before canonicalisation (no idempotency key / actor /
    # provenance) is replaced on the next sweep, not duplicated alongside.
    await _seed_relationship(TENANT, SOURCE, TARGET)
    client = await _graph()
    await client.add_edge(
        Edge(
            edge_type=EdgeType.SEMANTIC_RELATES_TO,
            from_vertex_id=SOURCE,
            to_vertex_id=TARGET,
            properties={
                "tenantId": TENANT,
                "tenant_id": TENANT,
                "relationship_ref": f"rel:{SOURCE}->{TARGET}",
            },
        )
    )

    report = await project_tenant(TENANT, graph_client=client)

    # Reconciliation revokes the non-canonical legacy edge; the sweep re-projects
    # the canonical one.
    assert report.revoked == 1
    assert report.projected == 1
    edges = await _semantic_edges(client, SOURCE)
    assert len(edges) == 1
    assert edges[0].properties.get("idempotency_key")
    assert edges[0].properties.get("actor_kind") == "system"


async def test_project_once_continues_past_tenant_sweep_failure():
    # Codex P1 (graph_projector.py project_once): a tenant whose sweep RAISES
    # during its unguarded reconciliation phase (e.g. listing/revoking one
    # tenant's stale graph edges fails) must not abort the whole pass and starve
    # later tenants until the next interval. project_once isolates the failure
    # into a per-tenant failed report and keeps processing the rest. If the bug
    # returns, the RuntimeError escapes project_once and this test fails.
    await _seed_relationship(TENANT, SOURCE, TARGET)
    await _seed_relationship(OTHER_TENANT, SOURCE, "prod_other")
    client = await _graph()

    original_reconcile = projector_mod._reconcile_projections
    original_get_graph_client = projector_mod.get_graph_client

    async def flaky_reconcile(graph_client, gateway, tenant_id, expected, report, **kwargs):
        if tenant_id == TENANT:
            raise RuntimeError("reconciliation list failed for TENANT")
        return await original_reconcile(
            graph_client, gateway, tenant_id, expected, report, **kwargs
        )

    projector_mod._reconcile_projections = flaky_reconcile
    # project_once uses the process-wide get_graph_client(); point it at the
    # local client so the surviving tenant's edge is inspectable afterwards.
    projector_mod.get_graph_client = lambda: client
    try:
        reports = await projector_mod.project_once()
    finally:
        projector_mod._reconcile_projections = original_reconcile
        projector_mod.get_graph_client = original_get_graph_client

    by_tenant = {r.tenant_id: r for r in reports}
    # Every tenant is represented in the pass result — the loop did not abort.
    assert set(by_tenant) == {TENANT, OTHER_TENANT}
    # The failing tenant is reported as failed with its error recorded.
    assert by_tenant[TENANT].failed == 1
    assert by_tenant[TENANT].errors
    assert any("reconciliation list failed" in e for e in by_tenant[TENANT].errors)
    # The later tenant is still swept and its edge really landed in the graph.
    assert by_tenant[OTHER_TENANT].failed == 0
    assert by_tenant[OTHER_TENANT].projected == 1
    edges = await _semantic_edges(client, SOURCE)
    assert [e.properties.get("tenantId") for e in edges] == [OTHER_TENANT]


async def _seed_raw_relationship(tenant: str, source: str, target: str, index: int) -> None:
    """Seed one gold relationship row directly (bypasses the reducer path)."""
    repo = SemanticFactRepository("gold_relationship_semantic_state", mode="gold")
    rel = f"rel:{source}->{target}"
    await repo.upsert(
        {
            "id": f"raw_{tenant}_{index}",
            "tenant_id": tenant,
            "subject_ref": rel,
            "occurred_at": "2026-01-01T00:00:00+00:00",
            "idempotency_key": f"gold_relationship:{tenant}:{rel}:test",
            "data": {
                "source_ref": source,
                "target_ref": target,
                "relationship_ref": rel,
                "relationship_layer": "EXCLUDED",
                "stance_alignment": 0.5,
                "trust_signal": 0.5,
                "interaction_quality": "coherent",
                "influence_direction": "outbound",
                "confidence": 0.7,
                "valid_from": "2026-01-01T00:00:00+00:00",
            },
        }
    )


async def _upsert_raw_relationship(
    tenant: str, source: str, target: str, confidence: Any
) -> None:
    """Seed one gold relationship row directly with an arbitrary confidence."""
    repo = SemanticFactRepository("gold_relationship_semantic_state", mode="gold")
    rel = f"rel:{source}->{target}"
    await repo.upsert(
        {
            "id": f"raw_{tenant}_{source}_{target}",
            "tenant_id": tenant,
            "subject_ref": rel,
            "occurred_at": "2026-01-01T00:00:00+00:00",
            "idempotency_key": f"gold_relationship:{tenant}:{rel}:test",
            "data": {
                "source_ref": source,
                "target_ref": target,
                "relationship_ref": rel,
                "relationship_layer": "EXCLUDED",
                "stance_alignment": 0.5,
                "trust_signal": 0.5,
                "interaction_quality": "coherent",
                "influence_direction": "outbound",
                "confidence": confidence,
                "valid_from": "2026-01-01T00:00:00+00:00",
            },
        }
    )


class _NeptuneLikeBackend:
    """Minimal non-in-memory backend stand-in for the projector's Neptune path.

    Deliberately NOT ``_InMemoryGraphBackend`` so the projector's flat-store
    fast path is skipped and the per-vertex scan runs — the path that used to
    collapse duplicate edges into a ``seen`` dict keyed by (type, source,
    target) before reconciliation could group and count them.
    """

    def __init__(self, *, vertices: list[Vertex], edges: list[Edge]) -> None:
        self._vertices = list(vertices)
        self._edges = list(edges)

    async def add_edge(self, edge: Edge) -> None:
        self._edges.append(edge)

    async def revoke_edge(
        self,
        from_vertex_id: str,
        to_vertex_id: str,
        edge_type: str,
        reason: str,
        tenant_id: str | None = None,
    ) -> int:
        count = 0
        revoked_at = "2026-01-01T00:00:00+00:00"
        for edge in self._edges:
            if not (
                edge.from_vertex_id == from_vertex_id
                and edge.to_vertex_id == to_vertex_id
                and edge.edge_type == edge_type
            ):
                continue
            if tenant_id is not None and str(
                edge.properties.get("tenant_id")
            ) != str(tenant_id):
                continue
            if not edge.properties.get("revoked"):
                edge.properties["revoked"] = True
                edge.properties["revoked_at"] = revoked_at
                edge.properties["revoke_reason"] = reason
            count += 1
        return count

    async def get_edges(
        self,
        vertex_id: str,
        edge_type: str | None = None,
        direction: str = "out",
        include_revoked: bool = False,
    ) -> list[Edge]:
        results: list[Edge] = []
        for edge in self._edges:
            if not include_revoked and edge.properties.get("revoked"):
                continue
            touches = False
            if direction in ("out", "both") and edge.from_vertex_id == vertex_id:
                touches = True
            elif direction in ("in", "both") and edge.to_vertex_id == vertex_id:
                touches = True
            if touches and (edge_type is None or edge.edge_type == edge_type):
                results.append(edge)
        return results

    async def get_vertices_for_tenant(
        self,
        tenant_id: str,
        limit: int = 1000,
        *,
        vertex_type: str | None = None,
    ) -> list[Vertex]:
        matched = [
            v
            for v in self._vertices
            if str(v.properties.get("tenantId") or v.properties.get("tenant_id"))
            == tenant_id
            and (vertex_type is None or v.vertex_type == vertex_type)
        ]
        return matched[:limit]


# ── Helpers for the follow-up items (#7 / #1 / #2 / #6) ──────────────────────


async def _upsert_relationship_content(
    tenant: str,
    source: str,
    target: str,
    *,
    stance_alignment: float = 0.5,
    trust_signal: float = 0.5,
    interaction_quality: str = "positive",
    influence_direction: str = "source_to_target",
    confidence: float = 0.7,
) -> None:
    """Upsert one gold relationship row with explicit salient content.

    The idempotency key is fixed on the pair, so re-upserting the SAME pair with
    changed content overwrites the prior Gold row (gold-mode LWW) — the recompute
    shape the versioned-reprojection path must observe.
    """
    repo = SemanticFactRepository("gold_relationship_semantic_state", mode="gold")
    rel = f"rel:{source}->{target}"
    await repo.upsert(
        {
            "id": f"raw_{tenant}_{source}_{target}",
            "tenant_id": tenant,
            "subject_ref": rel,
            "occurred_at": "2026-01-01T00:00:00+00:00",
            "idempotency_key": f"gold_relationship:{tenant}:{rel}:test",
            "data": {
                "source_ref": source,
                "target_ref": target,
                "relationship_ref": rel,
                "relationship_layer": "EXCLUDED",
                "stance_alignment": stance_alignment,
                "trust_signal": trust_signal,
                "interaction_quality": interaction_quality,
                "influence_direction": influence_direction,
                "confidence": confidence,
                "reducer_version": "weighted-reducer.v1",
                "valid_from": "2026-01-01T00:00:00+00:00",
            },
        }
    )


async def _seed_entity_gold(
    tenant: str,
    entity_ref: str,
    *,
    confidence: float = 0.8,
    observation_count: int = 3,
    summary: str = "3 weighted observations",
) -> None:
    """Seed one gold_entity_semantic_state row directly."""
    repo = SemanticFactRepository("gold_entity_semantic_state", mode="gold")
    await repo.upsert(
        {
            "id": f"ess_{tenant}_{entity_ref}",
            "tenant_id": tenant,
            "subject_ref": entity_ref,
            "occurred_at": "2026-01-01T00:00:00+00:00",
            "idempotency_key": f"gold_entity:{tenant}:{entity_ref}:test",
            "data": {
                "entity_ref": entity_ref,
                "subject_ref": entity_ref,
                "semantic_summary": summary,
                "stance_distribution": {"supportive": 0.7, "opposed": 0.3},
                "confidence": confidence,
                "observation_count": observation_count,
                "reducer_version": "weighted-reducer.v1",
            },
        }
    )


def _enforce_projector(monkeypatch, **flags) -> None:
    """Pin settings.semantic flags for the duration of a test."""
    monkeypatch.setattr(
        settings,
        "semantic",
        dataclasses.replace(settings.semantic, **flags),
    )


# ── #7 mode_override on the gateway ──────────────────────────────────────────


async def test_gateway_mode_override_forces_ledger_when_global_off():
    # apply(..., mode_override='enforce') writes a ledger row even though the
    # global mutation_gateway_mode is 'off' (the default in this test env).
    reset_graph_ledger_memory()
    assert settings.temporal_observatory.mutation_gateway_mode == "off"
    await _upsert_relationship_content(TENANT, SOURCE, TARGET)
    repo = SemanticFactRepository("gold_relationship_semantic_state", mode="gold")
    data = (await repo.list_by_tenant(TENANT))[0]
    edge = edge_from_relationship(TENANT, data)
    assert edge is not None
    client = await _graph()
    gw = GraphMutationGateway(graph_client=client)

    outcome = await gw.apply(
        edge_intent(
            edge,
            operation="edge_created",
            tenant_id=TENANT,
            subject_kind="entity",
            subject_id=TARGET,
        ),
        mode_override="enforce",
    )

    assert outcome.mode == "enforce"
    assert outcome.applied and outcome.ledger_recorded
    rows = await GraphMutationLedgerRepository().list_records(TENANT)
    assert len(rows) == 1
    assert rows[0]["operation"] == "edge_created"
    reset_graph_ledger_memory()


async def test_gateway_mode_override_none_behaves_as_today():
    # apply(..., mode_override=None) is the off-mode byte-identical path: the
    # edge is projected but NO ledger row is written (global mode is 'off').
    reset_graph_ledger_memory()
    await _upsert_relationship_content(TENANT, SOURCE, TARGET)
    repo = SemanticFactRepository("gold_relationship_semantic_state", mode="gold")
    data = (await repo.list_by_tenant(TENANT))[0]
    edge = edge_from_relationship(TENANT, data)
    client = await _graph()
    gw = GraphMutationGateway(graph_client=client)

    outcome = await gw.apply(
        edge_intent(edge, operation="edge_created", tenant_id=TENANT),
        mode_override=None,
    )

    assert outcome.mode == "off"
    assert outcome.applied and not outcome.ledger_recorded
    assert await GraphMutationLedgerRepository().list_records(TENANT) == []
    # The edge still reached the graph (off-mode direct projection).
    assert len(await _semantic_edges(client, SOURCE)) == 1
    reset_graph_ledger_memory()


async def test_projector_gateway_mode_setting_forces_ledger(monkeypatch):
    # settings.semantic.graph_projector_gateway_mode='enforce' makes the projector
    # ledger its projections regardless of the (off) global mode.
    reset_graph_ledger_memory()
    _enforce_projector(monkeypatch, graph_projector_gateway_mode="enforce")
    await _seed_relationship(TENANT, SOURCE, TARGET)
    client = await _graph()

    report = await project_tenant(TENANT, graph_client=client)

    assert report.projected == 1
    rows = await GraphMutationLedgerRepository().list_records(TENANT)
    assert any(r["operation"] == "edge_created" for r in rows)
    reset_graph_ledger_memory()


# ── #1 Versioned re-projection of updated Gold ───────────────────────────────


async def test_recompute_to_different_content_replaces_edge(monkeypatch):
    # A recomputed Gold row with the SAME endpoints but CHANGED content re-projects:
    # the stale edge is revoked and exactly one new canonical edge carries the new
    # content. Enforce mode records the change in the ledger.
    reset_graph_ledger_memory()
    _enforce_projector(monkeypatch, graph_projector_gateway_mode="enforce")
    await _upsert_relationship_content(
        TENANT, SOURCE, TARGET, stance_alignment=0.5, confidence=0.7
    )
    client = await _graph()

    first = await project_tenant(TENANT, graph_client=client)
    assert first.projected == 1
    live = [e for e in await _semantic_edges(client, SOURCE) if not e.properties.get("revoked")]
    assert len(live) == 1
    original_key = live[0].properties["idempotency_key"]
    original_rev = live[0].properties["content_revision"]

    # Recompute the SAME pair to DIFFERENT content.
    await _upsert_relationship_content(
        TENANT, SOURCE, TARGET, stance_alignment=-0.9, confidence=0.2,
        interaction_quality="negative",
    )
    second = await project_tenant(TENANT, graph_client=client)

    # Old edge revoked, new canonical edge projected.
    assert second.revoked == 1
    assert second.projected == 1
    live = [e for e in await _semantic_edges(client, SOURCE) if not e.properties.get("revoked")]
    assert len(live) == 1
    assert live[0].properties["idempotency_key"] != original_key
    assert live[0].properties["content_revision"] != original_rev
    assert float(live[0].properties["stance_alignment"]) == -0.9
    # The genuine content change was NOT suppressed by enforce-mode dedup.
    rows = await GraphMutationLedgerRepository().list_records(TENANT)
    assert sum(1 for r in rows if r["operation"] == "edge_created") == 2
    reset_graph_ledger_memory()


async def test_recompute_to_identical_content_skips():
    # Recompute to IDENTICAL content -> same identity -> skipped_existing, still
    # exactly one edge, no revoke, no churn.
    await _upsert_relationship_content(TENANT, SOURCE, TARGET)
    client = await _graph()

    first = await project_tenant(TENANT, graph_client=client)
    assert first.projected == 1

    # Re-upsert identical content and re-project.
    await _upsert_relationship_content(TENANT, SOURCE, TARGET)
    second = await project_tenant(TENANT, graph_client=client)

    assert second.projected == 0
    assert second.skipped_existing == 1
    assert second.revoked == 0
    live = [e for e in await _semantic_edges(client, SOURCE) if not e.properties.get("revoked")]
    assert len(live) == 1


# ── #2 Entity Gold as governed vertices ──────────────────────────────────────


async def test_entity_gold_projected_as_vertex(monkeypatch):
    # Flag on: an entity Gold row becomes a governed vertex through the gateway,
    # tenant-scoped, carrying salient signal but no raw content.
    _enforce_projector(monkeypatch, graph_vertex_projection_enabled=True)
    await _seed_relationship(TENANT, SOURCE, TARGET)
    await _seed_entity_gold(TENANT, TARGET)
    client = await _graph()

    report = await project_tenant(TENANT, graph_client=client)

    assert report.vertices_projected == 1
    vid = projector_mod._entity_vertex_id(TENANT, TARGET)
    vertex = await client.get_vertex(vid)
    assert vertex is not None
    assert vertex.vertex_type == VertexType.ENTITY
    assert vertex.properties.get("tenantId") == TENANT
    assert vertex.properties.get("entity_ref") == TARGET
    assert vertex.properties.get("dominant_stance") == "supportive"
    assert "content_revision" in vertex.properties


async def test_entity_vertex_projection_is_idempotent(monkeypatch):
    _enforce_projector(monkeypatch, graph_vertex_projection_enabled=True)
    await _seed_entity_gold(TENANT, TARGET)
    client = await _graph()

    first = await project_tenant(TENANT, graph_client=client)
    second = await project_tenant(TENANT, graph_client=client)

    assert first.vertices_projected == 1
    assert second.vertices_projected == 0
    assert second.vertices_skipped_existing == 1


async def test_entity_vertex_projection_is_tenant_scoped(monkeypatch):
    _enforce_projector(monkeypatch, graph_vertex_projection_enabled=True)
    await _seed_entity_gold(TENANT, TARGET)
    await _seed_entity_gold(OTHER_TENANT, TARGET)
    client = await _graph()

    await project_tenant(TENANT, graph_client=client)

    # Only TENANT's vertex exists (distinct ids per tenant); OTHER_TENANT untouched.
    assert await client.get_vertex(projector_mod._entity_vertex_id(TENANT, TARGET)) is not None
    assert await client.get_vertex(projector_mod._entity_vertex_id(OTHER_TENANT, TARGET)) is None


async def test_vertex_projection_off_by_default():
    # Flag OFF (default): no vertices projected, edges-only behavior.
    await _seed_relationship(TENANT, SOURCE, TARGET)
    await _seed_entity_gold(TENANT, TARGET)
    client = await _graph()

    report = await project_tenant(TENANT, graph_client=client)

    assert report.vertices_projected == 0
    assert await client.get_vertex(projector_mod._entity_vertex_id(TENANT, TARGET)) is None


def test_vertex_from_entity_skips_degenerate():
    assert vertex_from_entity(TENANT, {"entity_ref": ""}) is None
    assert vertex_from_entity(TENANT, {"entity_ref": "unknown_subject"}) is None


# ── #6 Consent/quality promotion policy + project_pair seam ───────────────────


async def test_low_confidence_pair_deferred_to_review(monkeypatch):
    # Flag on: a low-confidence pair is deferred to the review queue, NOT projected.
    _enforce_projector(monkeypatch, graph_promotion_review_enabled=True)
    await _upsert_relationship_content(TENANT, SOURCE, TARGET, confidence=0.1)
    client = await _graph()

    report = await project_tenant(TENANT, graph_client=client)

    assert report.projected == 0
    assert report.deferred_review == 1
    assert len(await _semantic_edges(client, SOURCE)) == 0
    # A graph_promotion_candidate review item was enqueued, tenant-scoped.
    items = await SemanticReviewQueueRepository().list_open(
        TENANT, "graph_promotion_candidate"
    )
    assert len(items) == 1
    assert items[0]["payload"]["source_ref"] == SOURCE
    assert items[0]["payload"]["target_ref"] == TARGET


async def test_high_confidence_pair_still_auto_projected(monkeypatch):
    # Flag on but a high-confidence pair clears the predicate: auto-projected.
    _enforce_projector(monkeypatch, graph_promotion_review_enabled=True)
    await _upsert_relationship_content(TENANT, SOURCE, TARGET, confidence=0.9)
    client = await _graph()

    report = await project_tenant(TENANT, graph_client=client)

    assert report.projected == 1
    assert report.deferred_review == 0
    assert len(await _semantic_edges(client, SOURCE)) == 1


async def test_review_flag_off_auto_projects_everything():
    # Flag OFF (default): even a low-confidence pair is auto-projected (unchanged).
    await _upsert_relationship_content(TENANT, SOURCE, TARGET, confidence=0.1)
    client = await _graph()

    report = await project_tenant(TENANT, graph_client=client)

    assert report.projected == 1
    assert report.deferred_review == 0


async def test_project_pair_projects_single_edge(monkeypatch):
    # project_pair projects exactly that one pair's canonical edge (bypassing the
    # review policy — approval already decided), and is idempotent on re-call.
    _enforce_projector(monkeypatch, graph_promotion_review_enabled=True)
    # Low confidence: the sweep would defer it, but explicit approval projects it.
    await _upsert_relationship_content(TENANT, SOURCE, TARGET, confidence=0.1)
    await _upsert_relationship_content(TENANT, SOURCE, "prod_other", confidence=0.1)
    client = await _graph()

    report = await project_pair(TENANT, SOURCE, TARGET, graph_client=client)

    assert report.projected == 1
    live = [e for e in await _semantic_edges(client, SOURCE) if not e.properties.get("revoked")]
    assert [e.to_vertex_id for e in live] == [TARGET]

    # Re-approving the same pair is a no-op (already projected).
    again = await project_pair(TENANT, SOURCE, TARGET, graph_client=client)
    assert again.projected == 0
    assert again.skipped_existing == 1


async def test_project_pair_missing_pair_is_noop(monkeypatch):
    _enforce_projector(monkeypatch, graph_promotion_review_enabled=True)
    client = await _graph()

    report = await project_pair(TENANT, SOURCE, "never_seeded", graph_client=client)

    assert report.projected == 0
    assert report.relationships_seen == 0
