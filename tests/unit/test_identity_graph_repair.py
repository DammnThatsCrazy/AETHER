"""Repair-mode coverage for identity repository/graph reconciliation."""

from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from shared.graph.graph import Edge, GraphClient
from services.identity.graph_reconciliation import repair_identity_edges
from services.identity.models import ConfidenceTier, EdgeType
from services.identity.repository import IdentityResolutionRepository


@pytest.fixture(autouse=True)
def _stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


async def _graph() -> GraphClient:
    graph = GraphClient()
    await graph.connect()
    return graph


async def _repo_edge(repo, tenant, source, target):
    return await repo.create_identity_edge(
        tenant_id=tenant,
        source_entity_id=source,
        target_entity_id=target,
        edge_type=EdgeType.SAME_AS,
        confidence=1.0,
        confidence_tier=ConfidenceTier.DETERMINISTIC,
        reason_codes=["repair_test"],
        source_event_ids=["event-1"],
    )


@pytest.mark.asyncio
async def test_repair_defaults_to_non_mutating_dry_run():
    tenant = "tenant-repair-dry"
    repo = IdentityResolutionRepository()
    graph = await _graph()
    await _repo_edge(repo, tenant, "a", "b")

    result = await repair_identity_edges(
        tenant,
        request_id="repair-dry-1",
        repo=repo,
        graph=graph,
    )

    assert result["status"] == "dry_run"
    assert result["outcomes"][0]["status"] == "planned"
    assert await graph.get_edges("a", edge_type=EdgeType.SAME_AS.value) == []


@pytest.mark.asyncio
async def test_mutating_repair_applies_both_exact_drift_fixes():
    tenant = "tenant-repair-live"
    repo = IdentityResolutionRepository()
    graph = await _graph()
    await _repo_edge(repo, tenant, "a", "b")
    await graph.add_edge(Edge(
        edge_type=EdgeType.SAME_AS.value,
        from_vertex_id="a",
        to_vertex_id="orphan",
        properties={"tenant_id": tenant},
    ))

    result = await repair_identity_edges(
        tenant,
        dry_run=False,
        request_id="repair-live-1",
        actor_id="operator-1",
        repo=repo,
        graph=graph,
    )

    assert result["status"] == "succeeded"
    assert result["applied"] == 2
    active = await graph.get_edges("a", edge_type=EdgeType.SAME_AS.value)
    assert {edge.to_vertex_id for edge in active} == {"b"}
    all_edges = await graph.get_edges(
        "a", edge_type=EdgeType.SAME_AS.value, include_revoked=True
    )
    orphan = next(edge for edge in all_edges if edge.to_vertex_id == "orphan")
    assert orphan.properties["revoked"] is True


@pytest.mark.asyncio
async def test_request_id_retry_returns_durable_outcomes_without_duplicate_edges():
    tenant = "tenant-repair-retry"
    repo = IdentityResolutionRepository()
    graph = await _graph()
    await _repo_edge(repo, tenant, "a", "b")

    first = await repair_identity_edges(
        tenant,
        dry_run=False,
        request_id="repair-retry-1",
        repo=repo,
        graph=graph,
    )
    second = await repair_identity_edges(
        tenant,
        dry_run=False,
        request_id="repair-retry-1",
        repo=repo,
        graph=graph,
    )

    assert first["replayed"] is False
    assert second["replayed"] is True
    edges = await graph.get_edges("a", edge_type=EdgeType.SAME_AS.value)
    assert len(edges) == 1


@pytest.mark.asyncio
async def test_request_id_cannot_cross_tenant_boundary():
    repo = IdentityResolutionRepository()
    graph = await _graph()
    await repair_identity_edges(
        "tenant-a",
        request_id="shared-request",
        repo=repo,
        graph=graph,
    )
    with pytest.raises(ValueError, match="another tenant"):
        await repair_identity_edges(
            "tenant-b",
            request_id="shared-request",
            repo=repo,
            graph=graph,
        )
