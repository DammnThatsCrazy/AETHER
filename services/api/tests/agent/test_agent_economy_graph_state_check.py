"""Read-only agent-economy graph reconciliation contracts."""
from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from actions.agent_marketplace.graph_state_check import (  # noqa: E402
    AgentEconomyGraphStateChecker,
    _scoped_id,
)
from shared.graph.graph import Edge, EdgeType, Vertex, VertexType, tenant_of  # noqa: E402


TENANT = "tenant-a"
OTHER = "tenant-b"
DEPLOYMENT = "deployment-a"
SOURCE_EVENT = "source-event-a"
INTENT = "intent-a"
DELEGATION = "delegation-a"
AGENT = "canonical-agent-a"
BINDING = "binding-a"


def _source_row(**changes: Any) -> dict[str, Any]:
    row = {
        "tenant_id": TENANT,
        "deployment_id": DEPLOYMENT,
        "run_id": "run-a",
        "source_event_id": SOURCE_EVENT,
        "event_name": "agent_task_completed",
        "occurred_at": "2026-10-10T12:00:00+00:00",
        "delegation_id": DELEGATION,
        "payment_intent_ref": INTENT,
    }
    row.update(changes)
    return row


def _deployment(tenant_id: str = TENANT) -> dict[str, Any]:
    return {
        "id": DEPLOYMENT,
        "tenant_id": tenant_id,
        "agent_id": "source-agent-a",
        "agent_source_namespace": "xai.marketplace",
    }


def _identity_binding(tenant_id: str = TENANT) -> dict[str, Any]:
    return {
        "id": BINDING,
        "tenant_id": tenant_id,
        "source_namespace": "xai.marketplace",
        "source_agent_ref": "source-agent-a",
        "canonical_agent_entity_id": AGENT,
        "source_deployment_id": DEPLOYMENT,
        "binding_authority": "tenant_admin_explicit",
        "status": "active",
    }


def _intent(*, tenant_id: str = TENANT, agent_id: str = "source-agent-a") -> dict[str, Any]:
    return {
        "intent_id": INTENT,
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "metadata": {"source_authority": "x402_commerce"},
    }


def _delegation(tenant_id: str = TENANT) -> dict[str, Any]:
    return {
        "delegation_id": DELEGATION,
        "tenant_id": tenant_id,
        "grantor_entity_id": "grantor-a",
        "grantee_entity_id": "grantee-a",
        "starts_at": "2026-10-01T00:00:00+00:00",
        "ends_at": None,
        "revoked_at": None,
    }


def _edge(
    edge_type: str,
    source: str,
    target: str,
    *,
    tenant_id: str = TENANT,
    source_event_id: str = SOURCE_EVENT,
    **properties: Any,
) -> Edge:
    return Edge(
        edge_type=edge_type,
        from_vertex_id=source,
        to_vertex_id=target,
        properties={
            "tenant_id": tenant_id,
            "source_event_id": source_event_id,
            **properties,
        },
    )


def _expected_edges(*, delegation_status: str = "indeterminate") -> list[Edge]:
    action_id = _scoped_id("agent_action", TENANT, DEPLOYMENT, SOURCE_EVENT)
    delegation_id = _scoped_id("delegation", TENANT, DELEGATION)
    return [
        _edge(
            EdgeType.REFERENCES_DELEGATION_RECORD,
            action_id,
            delegation_id,
            authorization_claim="none",
            delegation_authorization_status=delegation_status,
            execution_occurrence="source_reported",
            execution_verified=False,
        ),
        _edge(
            EdgeType.CORRELATED_WITH_ECONOMIC_RECORD,
            action_id,
            f"{TENANT}:{INTENT}",
            economic_record_kind="payment_intent",
        ),
        _edge(
            EdgeType.AGENT_LINKED_TO_EXTERNAL_ACCOUNT,
            AGENT,
            DEPLOYMENT,
            source_event_id=BINDING,
            binding_authority="tenant_admin_explicit",
            provenance="agent_deployment_identity_binding",
            source_namespace="xai.marketplace",
            source_agent_ref="source-agent-a",
            canonical_agent_entity_id=AGENT,
        ),
    ]


def _vertices() -> list[Vertex]:
    action_id = _scoped_id("agent_action", TENANT, DEPLOYMENT, SOURCE_EVENT)
    delegation_id = _scoped_id("delegation", TENANT, DELEGATION)
    return [
        Vertex(VertexType.ACTION_RECORD, action_id, {"tenant_id": TENANT}),
        Vertex(VertexType.DELEGATION, delegation_id, {"tenant_id": TENANT}),
        Vertex(VertexType.PAYMENT_INTENT, f"{TENANT}:{INTENT}", {"tenant_id": TENANT}),
        Vertex(VertexType.AGENT, AGENT, {"tenant_id": TENANT}),
        Vertex(VertexType.EXTERNAL_AGENTIC_ACCOUNT, DEPLOYMENT, {"tenant_id": TENANT}),
    ]


class _FakeAnalytics:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    async def query_silver_page(
        self, table: str, filters: dict[str, Any], *, limit: int, cursor: str | None = None,
    ):
        self.calls.append({"table": table, "filters": filters, "limit": limit, "cursor": cursor})
        assert table == "silver_agent_execution_facts"
        assert filters == {"tenant_id": TENANT}
        offset = int(cursor or 0)
        page = self.rows[offset:offset + limit]
        truncated = offset + limit < len(self.rows)
        return page, (str(offset + limit) if truncated else None), truncated


class _FakeDeploymentRepository:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def get_record(self, tenant_id: str, deployment_id: str):
        return next((
            row for row in self.rows
            if row.get("tenant_id") == tenant_id and row.get("id") == deployment_id
        ), None)

    async def list_page(self, tenant_id: str, *, limit: int, cursor: str | None = None):
        rows = [row for row in self.rows if row.get("tenant_id") == tenant_id]
        offset = int(cursor or 0)
        page = rows[offset:offset + limit]
        truncated = offset + limit < len(rows)
        return page, (str(offset + limit) if truncated else None), truncated


class _FakeRepository:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    async def find_many(self, *, filters: dict[str, Any], limit: int):
        self.calls.append(filters)
        return [
            row for row in self.rows
            if all(row.get(key) == value for key, value in filters.items())
        ][:limit]

    async def find_for_source(self, tenant_id: str, source_namespace: str, source_agent_ref: str):
        return await self.find_many(
            filters={
                "tenant_id": tenant_id,
                "source_namespace": source_namespace,
                "source_agent_ref": source_agent_ref,
                "status": "active",
            },
            limit=2,
        )


class _FakeGraph:
    def __init__(self, edges: list[Edge], vertices: list[Vertex]) -> None:
        self.edges = edges
        self.vertices = {vertex.vertex_id: vertex for vertex in vertices}
        self.calls: list[dict[str, Any]] = []

    async def get_edges_for_tenant(
        self,
        tenant_id: str,
        limit: int,
        *,
        edge_types: list[str] | None = None,
        include_revoked: bool = False,
    ):
        self.calls.append({
            "tenant_id": tenant_id,
            "limit": limit,
            "edge_types": edge_types,
            "include_revoked": include_revoked,
        })
        matching = [
            edge for edge in self.edges
            if tenant_of(edge.properties) == tenant_id
            and (edge_types is None or edge.edge_type in edge_types)
            and (include_revoked or not edge.properties.get("revoked"))
        ]
        return matching[:limit], len(matching) > limit

    async def get_vertex_for_tenant(self, tenant_id: str, vertex_id: str):
        vertex = self.vertices.get(vertex_id)
        return vertex if vertex and tenant_of(vertex.properties) == tenant_id else None


def _checker(
    *,
    rows: list[dict[str, Any]] | None = None,
    edges: list[Edge] | None = None,
    deployment_rows: list[dict[str, Any]] | None = None,
    bindings: list[dict[str, Any]] | None = None,
    entities: list[dict[str, Any]] | None = None,
    intent_rows: list[dict[str, Any]] | None = None,
    delegation_rows: list[dict[str, Any]] | None = None,
    extensions=(),
) -> AgentEconomyGraphStateChecker:
    return AgentEconomyGraphStateChecker(
        graph=_FakeGraph(edges or [], _vertices()),
        analytics=_FakeAnalytics(rows if rows is not None else [_source_row()]),
        deployment_repo=_FakeDeploymentRepository(
            deployment_rows if deployment_rows is not None else [_deployment()]
        ),
        delegation_repo=_FakeRepository(
            delegation_rows if delegation_rows is not None else [_delegation()]
        ),
        payment_intent_repo=_FakeRepository(
            intent_rows if intent_rows is not None else [_intent()]
        ),
        settlement_repo=_FakeRepository([]),
        identity_binding_repo=_FakeRepository(
            bindings if bindings is not None else [_identity_binding()]
        ),
        entity_repo=_FakeRepository(
            entities if entities is not None else [{
                "entity_id": AGENT, "tenant_id": TENANT, "entity_type": "agent",
            }]
        ),
        authority_extensions=extensions,
    )


@pytest.mark.asyncio
async def test_graph_state_checker_reports_consistency_for_canonical_links_and_identity():
    async def authority_extension(_row, _context):
        return {"statuses": [{
            "authority": "delegation_authorization",
            "status": "within_scope",
            "execution_occurrence": "source_reported",
            "execution_verified": False,
        }]}

    checker = _checker(
        edges=_expected_edges(delegation_status="within_scope"),
        extensions=[authority_extension],
    )
    result = await checker.reconcile(TENANT)

    assert result["status"] == "consistent"
    assert result["coverage"]["status"] == "complete"
    assert result["coverage"]["delegation_authority_checked"] is True
    assert result["coverage"]["source_scan_complete"] is True
    assert result["counts"] == {
        "missing": 0, "extra": 0, "mismatched": 0,
        "unresolved": 0, "unauthorized": 0,
    }
    assert any(
        status.get("authority") == "agent_deployment_identity_binding"
        and status.get("status") == "matched"
        for status in result["source_reference_statuses"]
    )
    authorization_statuses = [
        status for status in result["source_reference_statuses"]
        if status.get("authority") == "delegation_authorization"
    ]
    assert len(authorization_statuses) == 1
    assert authorization_statuses[0]["status"] == "within_scope"
    assert checker._graph.calls
    assert all(call["tenant_id"] == TENANT for call in checker._graph.calls)


@pytest.mark.asyncio
async def test_graph_state_checker_marks_coverage_partial_only_when_authority_status_missing():
    result = await _checker(edges=_expected_edges()).reconcile(TENANT)

    assert result["status"] == "partial"
    assert result["coverage"]["status"] == "partial"
    assert result["coverage"]["delegation_authority_checked"] is False
    assert result["counts"] == {
        "missing": 0, "extra": 0, "mismatched": 0,
        "unresolved": 0, "unauthorized": 0,
    }


@pytest.mark.asyncio
async def test_graph_state_checker_reports_missing_expected_edges():
    result = await _checker(edges=[]).reconcile(TENANT)

    assert result["status"] == "inconsistent"
    assert result["counts"]["missing"] == 3
    assert {row["record_kind"] for row in result["findings"]["missing"]} == {
        "delegation", "payment_intent", "identity_binding",
    }


@pytest.mark.asyncio
async def test_graph_state_checker_finds_orphan_tenant_edges_as_extras():
    edges = _expected_edges()
    edges.append(_edge(
        EdgeType.CORRELATED_WITH_ECONOMIC_RECORD,
        "orphan-action",
        f"{TENANT}:orphan-intent",
        source_event_id="not-in-silver",
        economic_record_kind="payment_intent",
    ))
    result = await _checker(edges=edges).reconcile(TENANT)

    assert result["counts"]["extra"] == 1
    assert result["findings"]["extra"][0]["source_event_id"] == "not-in-silver"
    assert result["findings"]["extra"][0]["scope"] == "unmatched_source_evidence"


@pytest.mark.asyncio
async def test_graph_state_checker_reports_wrong_economic_target_as_mismatched():
    edges = _expected_edges()
    edges[1] = _edge(
        EdgeType.CORRELATED_WITH_ECONOMIC_RECORD,
        _scoped_id("agent_action", TENANT, DEPLOYMENT, SOURCE_EVENT),
        f"{TENANT}:wrong-intent",
        economic_record_kind="payment_intent",
    )
    wrong_vertices = _vertices() + [
        Vertex(VertexType.PAYMENT_INTENT, f"{TENANT}:wrong-intent", {"tenant_id": TENANT})
    ]
    checker = _checker(edges=edges)
    checker._graph.vertices.update({v.vertex_id: v for v in wrong_vertices})
    result = await checker.reconcile(TENANT)

    assert result["counts"]["mismatched"] == 1
    assert result["findings"]["mismatched"][0]["expected_to_vertex_id"] == f"{TENANT}:{INTENT}"
    assert result["counts"]["missing"] == 0


@pytest.mark.asyncio
async def test_graph_state_checker_rejects_delegation_edge_that_claims_authorization():
    edges = _expected_edges()
    delegation_index = next(
        index for index, edge in enumerate(edges)
        if edge.edge_type == EdgeType.REFERENCES_DELEGATION_RECORD
    )
    original = edges[delegation_index]
    edges[delegation_index] = _edge(
        EdgeType.REFERENCES_DELEGATION_RECORD,
        original.from_vertex_id,
        original.to_vertex_id,
        authorization_claim="authorized",
        delegation_authorization_status="within_scope",
        execution_occurrence="source_reported",
        execution_verified=False,
    )

    result = await _checker(edges=edges).reconcile(TENANT)

    assert result["counts"]["unauthorized"] == 1
    assert result["findings"]["unauthorized"][0]["reason"] == "persisted_edge_properties_mismatch"


@pytest.mark.asyncio
async def test_graph_state_checker_rejects_identity_edge_with_wrong_canonical_binding():
    edges = _expected_edges()
    identity_index = next(
        index for index, edge in enumerate(edges)
        if edge.edge_type == EdgeType.AGENT_LINKED_TO_EXTERNAL_ACCOUNT
    )
    original = edges[identity_index]
    edges[identity_index] = _edge(
        EdgeType.AGENT_LINKED_TO_EXTERNAL_ACCOUNT,
        original.from_vertex_id,
        original.to_vertex_id,
        source_event_id=BINDING,
        provenance="agent_deployment_identity_binding",
        binding_authority="tenant_admin_explicit",
        source_namespace="xai.marketplace",
        source_agent_ref="source-agent-a",
        canonical_agent_entity_id="different-agent",
    )

    result = await _checker(edges=edges).reconcile(TENANT)

    assert result["counts"]["unauthorized"] == 1
    assert result["findings"]["unauthorized"][0]["properties"][
        "canonical_agent_entity_id"
    ]["observed"] == "different-agent"


@pytest.mark.asyncio
async def test_graph_state_checker_surfaces_unresolved_identity_and_indeterminate_authorization():
    async def authority_extension(_row, _context):
        return {"statuses": [{
            "authority": "delegation_authorization",
            "status": "indeterminate",
            "reason": "actor_binding_unresolved",
            "execution_occurrence": "source_reported",
            "execution_verified": False,
        }]}

    edges = [edge for edge in _expected_edges() if edge.edge_type != EdgeType.AGENT_LINKED_TO_EXTERNAL_ACCOUNT]
    result = await _checker(
        edges=edges,
        bindings=[],
        extensions=[authority_extension],
    ).reconcile(TENANT)

    assert result["counts"]["unresolved"] >= 1
    statuses = result["source_reference_statuses"]
    assert any(
        status.get("authority") == "delegation_authorization"
        and status.get("status") == "indeterminate"
        and status.get("execution_verified") is False
        for status in statuses
    )
    assert any(
        finding.get("reference_kind") == "identity"
        for finding in result["findings"]["unresolved"]
    )


@pytest.mark.asyncio
async def test_graph_state_checker_reports_unauthorized_economic_link_for_agent_mismatch():
    result = await _checker(
        edges=_expected_edges(),
        intent_rows=[_intent(agent_id="different-agent")],
    ).reconcile(TENANT)

    assert result["counts"]["unauthorized"] >= 1
    assert any(
        finding.get("reason") == "persisted_link_for_unauthorized_economic_reference"
        for finding in result["findings"]["unauthorized"]
    )


@pytest.mark.asyncio
async def test_graph_state_checker_scopes_canonical_reads_and_graph_scan_by_tenant():
    foreign_intent = _intent(tenant_id=OTHER)
    foreign_edge = _edge(
        EdgeType.CORRELATED_WITH_ECONOMIC_RECORD,
        _scoped_id("agent_action", OTHER, DEPLOYMENT, SOURCE_EVENT),
        f"{OTHER}:{INTENT}",
        tenant_id=OTHER,
        economic_record_kind="payment_intent",
    )
    checker = _checker(
        edges=[foreign_edge],
        intent_rows=[foreign_intent],
        bindings=[],
    )
    result = await checker.reconcile(TENANT)

    assert result["coverage"]["status"] == "partial"
    assert result["coverage"]["delegation_authority_checked"] is False
    assert result["counts"]["extra"] == 0
    assert f"{OTHER}:{INTENT}" not in str(result)
    assert result["counts"]["unresolved"] >= 1
    assert all(call["tenant_id"] == TENANT for call in checker._graph.calls)
    assert all(
        call.get("tenant_id") == TENANT
        for repo in (checker._payment_intent_repo, checker._delegation_repo)
        for call in repo.calls
    )


@pytest.mark.asyncio
async def test_graph_state_checker_rejects_conflicting_tenant_property_aliases():
    edge = _edge(
        EdgeType.CORRELATED_WITH_ECONOMIC_RECORD,
        "untrusted-action",
        f"{TENANT}:intent-a",
        tenant_id=OTHER,
        source_event_id="foreign-claim",
        economic_record_kind="payment_intent",
    )
    edge.properties["tenantId"] = TENANT

    result = await _checker(edges=[edge]).reconcile(TENANT)

    assert result["counts"]["unauthorized"] == 1
    assert result["findings"]["unauthorized"][0]["reason"] == (
        "tenant_owned_edge_has_mismatched_tenant_property"
    )


@pytest.mark.asyncio
async def test_graph_state_checker_marks_truncated_graph_scan_partial():
    result = await _checker(edges=_expected_edges()).reconcile(
        TENANT, graph_edge_limit=1,
    )

    assert result["coverage"]["status"] == "partial"
    assert result["coverage"]["graph_edge_scan_truncated"] is True


@pytest.mark.asyncio
async def test_graph_state_checker_bounds_empty_but_truncated_source_pages():
    checker = _checker(edges=[])

    class EmptyTruncatedAnalytics:
        def __init__(self):
            self.calls = 0

        async def query_silver_page(self, _table, _filters, *, limit, cursor=None):
            self.calls += 1
            return [], f"opaque-{self.calls}", True

    analytics = EmptyTruncatedAnalytics()
    checker._analytics = analytics
    result = await checker.reconcile(
        TENANT, source_page_size=2, max_source_rows=10,
    )

    assert analytics.calls == 13  # ceil(10 / 2) plus the bounded empty-page allowance
    assert result["coverage"]["status"] == "partial"
    assert result["coverage"]["source_scan_error"] == "source_scan_page_limit_reached"
    assert result["coverage"]["source_scan_complete"] is False


@pytest.mark.asyncio
async def test_graph_state_checker_bounds_empty_but_truncated_deployment_pages():
    checker = _checker(edges=[])

    class EmptyTruncatedDeploymentRepository(_FakeDeploymentRepository):
        def __init__(self):
            super().__init__([])
            self.calls = 0

        async def list_page(self, _tenant_id, *, limit, cursor=None):
            self.calls += 1
            return [], f"opaque-{self.calls}", True

    deployments = EmptyTruncatedDeploymentRepository()
    checker._deployment_repo = deployments
    result = await checker.reconcile(
        TENANT, max_source_rows=10,
    )

    assert deployments.calls == 9  # ceil(10 / 250) plus the bounded empty-page allowance
    assert result["coverage"]["status"] == "partial"
    assert result["coverage"]["identity_binding_scan_truncated"] is True
