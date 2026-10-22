"""Focused contracts for external-agent marketplace lineage and recovery."""

from __future__ import annotations

import dataclasses
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

os.environ.setdefault("AETHER_ENV", "local")

from actions.agent.deployments import AgentDeploymentRepository  # noqa: E402
from actions.agent_marketplace.lineage import build_marketplace_origin_mutations  # noqa: E402
from actions.agent_marketplace.models import AgentMarketplaceOrigin  # noqa: E402
from actions.agent_marketplace.projection import (  # noqa: E402
    AgentMarketplaceGraphOutboxRepository,
    AgentMarketplaceGraphOutboxWorker,
    AgentMarketplaceGraphProjectionOutbox,
)
from ingestion.silver.projectors.agent_execution_projector import AgentExecutionProjector  # noqa: E402
from ingestion.silver.projectors.base import ProjectionResult  # noqa: E402
from ingestion.silver.projectors.silver_graph_projector import (  # noqa: E402
    SilverGraphProjector,
    build_external_agent_run_mutations,
)
from shared.common.common import NotFoundError  # noqa: E402
from shared.graph.graph import Edge, EdgeType, Vertex, VertexType  # noqa: E402
from shared.outbox import STATUS_DEAD_LETTERED, STATUS_FAILED, STATUS_PERSISTED, STATUS_PROCESSING, STATUS_QUEUED  # noqa: E402


def _tenant() -> str:
    return f"tenant-{uuid.uuid4().hex}"


def _origin(**changes) -> dict:
    payload = {
        "source_namespace": "xai.marketplace",
        "listing_ref": "listing-1",
        "template_ref": "template-1",
        "template_version": "v2",
        "listing_url": "https://market.example/listing-1",
        "category": "engineering",
        "catalog_capabilities": ["code review", "issue triage"],
    }
    payload.update(changes)
    return payload


def _run_row(**changes) -> dict:
    row = {
        "tenant_id": "tenant-a",
        "deployment_id": "deployment-a",
        "agent_id": "registry-agent-reference",
        "run_id": "run-1",
        "run_correlation_source": "run_id",
        "source_event_id": "source-event-1",
        "event_name": "agent_policy_evaluated",
        "occurred_at": "2026-10-10T10:00:00+00:00",
        "task_ref": "task-1",
        "action_ref": "action-1",
        "action_type": "issue.update",
        "trigger_ref": "trigger-1",
        "trigger_type": "webhook",
        "policy_id": "policy-1",
        "policy_version": "4",
        "policy_decision": "allow",
        "policy_reason_codes": ["within_scope"],
        "delegation_id": "delegation-1",
        "delegated_to_ref": "external-agent-2",
        "outcome_ref": "outcome-1",
        "outcome": "completed",
        "status": "completed",
        "principal_id": "principal-1",
    }
    row.update(changes)
    return row


def _vertices(mutations: list[object]) -> list[Vertex]:
    return [item for item in mutations if isinstance(item, Vertex)]


def _edges(mutations: list[object]) -> list[Edge]:
    return [item for item in mutations if isinstance(item, Edge)]


def test_marketplace_origin_validates_safe_references_and_strips_url_tracking():
    origin = AgentMarketplaceOrigin.model_validate(_origin(source_namespace=" XAI.Marketplace "))
    assert origin.source_namespace == "xai.marketplace"
    assert origin.assertion == "tenant_declared"

    for bad_url in (
        "https://user:secret@market.example/listing",
        "https://market.example/listing?utm_source=feed",
        "https://market.example/listing#details",
    ):
        with pytest.raises(ValidationError):
            AgentMarketplaceOrigin.model_validate(_origin(listing_url=bad_url))

    with pytest.raises(ValidationError):
        AgentMarketplaceOrigin.model_validate(_origin(listing_ref="bad\nref"))
    with pytest.raises(ValidationError):
        AgentMarketplaceOrigin.model_validate(_origin(untrusted=True))


def test_marketplace_lineage_is_tenant_scoped_and_does_not_resolve_agent_identity():
    origin = _origin()
    deployment = {
        "id": "deployment-1",
        "tenant_id": "tenant-a",
        "agent_id": "registry-agent-1",
        "external_platform": "custom_marketplace",
        "created_at": "2026-10-10T10:00:00+00:00",
        "marketplace_origin": origin,
    }
    mutations_a = build_marketplace_origin_mutations(deployment)
    mutations_b = build_marketplace_origin_mutations({**deployment, "tenant_id": "tenant-b"})
    vertices_a = _vertices(mutations_a)
    vertices_b = _vertices(mutations_b)

    assert {v.vertex_type for v in vertices_a} >= {
        VertexType.EXTERNAL_AGENTIC_ACCOUNT,
        VertexType.MARKETPLACE,
        VertexType.AGENT_TEMPLATE,
        VertexType.AGENT_MARKETPLACE_LISTING,
    }
    assert len({v.vertex_id for v in vertices_a} & {v.vertex_id for v in vertices_b}) == 1
    assert all(v.properties.get("tenant_id") == "tenant-a" for v in vertices_a)
    assert all(v.vertex_id != "registry-agent-1" for v in vertices_a)
    assert all(e.properties.get("assertion") == "tenant_declared" for e in _edges(mutations_a))


def test_agent_execution_projector_projects_validated_causality_and_bounds_references():
    event = {
        "messageId": "source-event-1",
        "type": "agent_policy_evaluated",
        "tenantId": "tenant-a",
        "timestamp": "2026-10-10T10:00:00Z",
        "properties": {
            "agentId": "sdk-agent-id",
            "runId": " run-1 ",
            "taskId": "task-1",
            "actionId": "action-1",
            "actionType": "issue.update",
            "resourceRef": "repo:acme/project",
            "triggerId": "trigger-1",
            "policyId": "policy-1",
            "policyVersion": "4",
            "decision": "allow",
            "reasonCodes": ["within_scope", "bad\nreason", "x" * 300],
            "delegationId": "delegation-1",
            "delegatedToAgentId": "external-agent-2",
            "delegatedToNamespace": " Vendor.Runtime ",
        },
        "context": {
            "tenantId": "tenant-a",
            "agentDeployment": {"deploymentId": "sdk-untrusted"},
            "correlation": {"traceId": "trace-1", "causationId": "cause-1"},
        },
        "validated_agent_deployment": {
            "deploymentId": "deployment-a",
            "agentId": "registry-agent-1",
        },
    }
    result = AgentExecutionProjector().project(event)
    assert result is not None
    row = result.rows[0]
    assert result.table == "silver_agent_execution_facts"
    assert row["tenant_id"] == "tenant-a"
    assert row["deployment_id"] == "deployment-a"
    assert row["agent_id"] == "registry-agent-1"
    assert row["run_id"] == "run-1"
    assert row["trace_id"] == "trace-1"
    assert row["run_correlation_source"] == "run_id"
    assert row["delegation_id"] == "delegation-1"
    assert row["delegated_to_ref"] == "external-agent-2"
    assert row["delegated_to_namespace"] == "Vendor.Runtime"
    assert row["resource_ref"] == "repo:acme/project"
    assert row["policy_reason_codes"] == ["within_scope"]


def test_agent_execution_projector_keeps_subagent_spawn_lineage_references():
    result = AgentExecutionProjector().project({
        "messageId": "spawn-1",
        "type": "agent_subagent_spawned",
        "timestamp": "2026-10-10T10:00:00Z",
        "properties": {
            "agentId": "orchestrator-1",
            "parentAgentId": "orchestrator-1",
            "childAgentId": "worker-1",
            "rootAgentId": "orchestrator-1",
            "parentRunId": "run-root",
            "runId": "run-root",
        },
    })
    assert result is not None
    row = result.rows[0]
    assert row["parent_agent_ref"] == "orchestrator-1"
    assert row["child_agent_ref"] == "worker-1"
    assert row["root_agent_ref"] == "orchestrator-1"
    assert row["parent_run_id"] == "run-root"
    assert row["delegated_to_ref"] == "worker-1"


def test_agent_execution_projector_uses_source_event_for_missing_outcome_and_trace_fallback():
    result = AgentExecutionProjector().project({
        "messageId": "event-complete-1",
        "type": "agent_task_completed",
        "timestamp": "2026-10-10T10:00:00Z",
        "properties": {"taskId": "task-1"},
        "context": {"correlation": {"traceId": "trace-only"}},
    })
    assert result is not None
    row = result.rows[0]
    assert row["run_id"] == "trace-only"
    assert row["run_correlation_source"] == "trace_id"
    assert row["outcome_ref"] == "event-complete-1"
    assert row["status"] == "completed"
    assert row["outcome"] == "completed"


def test_external_agent_run_mutations_are_bounded_tenant_scoped_and_source_reported():
    row = _run_row()
    mutations = build_external_agent_run_mutations(row)
    vertices = _vertices(mutations)
    assert {v.vertex_type for v in vertices} >= {
        VertexType.EXTERNAL_AGENTIC_ACCOUNT,
        VertexType.AGENT_EXECUTION_RUN,
        VertexType.TASK,
        VertexType.ACTION_RECORD,
        VertexType.DECISION_RECORD,
        VertexType.OUTCOME_OBSERVATION,
    }
    assert all(v.properties.get("tenant_id") == "tenant-a" for v in vertices)
    assert "registry-agent-reference" not in {v.vertex_id for v in vertices}
    run = next(v for v in vertices if v.vertex_type == VertexType.AGENT_EXECUTION_RUN)
    assert run.properties["evidence_status"] == "source_reported"
    assert "status" not in run.properties and "event_name" not in run.properties
    action = next(v for v in vertices if v.vertex_type == VertexType.ACTION_RECORD)
    assert action.properties["trigger_ref"] == "trigger-1"
    assert action.properties["policy_decision"] == "allow"
    assert action.properties["delegation_id"] == "delegation-1"
    assert any(v.properties.get("outcome_ref") == "outcome-1" for v in vertices)
    assert all(edge.properties.get("tenant_id") == "tenant-a" for edge in _edges(mutations))

    other_tenant = build_external_agent_run_mutations(_run_row(tenant_id="tenant-b"))
    ids_a = {v.vertex_id for v in vertices if v.vertex_type != VertexType.EXTERNAL_AGENTIC_ACCOUNT}
    ids_b = {
        v.vertex_id for v in _vertices(other_tenant)
        if v.vertex_type != VertexType.EXTERNAL_AGENTIC_ACCOUNT
    }
    assert ids_a.isdisjoint(ids_b)


def test_external_agent_run_mutations_require_complete_correlation_and_curated_action_evidence():
    assert build_external_agent_run_mutations(_run_row(run_id="")) == []
    mutations = build_external_agent_run_mutations(_run_row(
        event_name="agent_activity_observed",
        action_ref=None,
        action_type=None,
        trigger_ref=None,
        trigger_type=None,
        tool_name=None,
        policy_id=None,
        policy_decision=None,
        delegation_id=None,
        delegated_to_ref=None,
        outcome_ref=None,
        status="running",
        principal_id="principal-1",
    ))
    assert all(v.vertex_type != VertexType.ACTION_RECORD for v in _vertices(mutations))


@pytest.mark.asyncio
async def test_external_deployment_graph_path_never_emits_legacy_agent_tool_edge(monkeypatch):
    import ingestion.silver.projectors.silver_graph_projector as module

    direct_writes = []
    external_rows = []

    async def record_direct(*args, **kwargs):
        direct_writes.append((args, kwargs))

    async def record_external(row, tenant_id, source_event_id):
        external_rows.append((row, tenant_id, source_event_id))

    monkeypatch.setattr(module, "_emit", record_direct)
    monkeypatch.setattr(module, "_emit_vertex", record_direct)
    projector = SilverGraphProjector()
    monkeypatch.setattr(projector, "_emit_external_agent_run", record_external)
    row = _run_row(event_name="agent_tool_invocation_observed", tool_name="browser.search")
    await projector._emit_agent_execution(
        ProjectionResult(table="silver_agent_execution_facts", rows=[row]),
        {"type": "agent_tool_invocation_observed"},
    )
    assert direct_writes == []
    assert external_rows == [(row, "tenant-a", "source-event-1")]


class _MemoryOutboxRepository:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    @staticmethod
    def outbox_id(tenant_id, payload):
        return AgentMarketplaceGraphOutboxRepository.outbox_id(tenant_id, payload)

    async def enqueue(self, tenant_id, source_event_id, payload):
        row_id = AgentMarketplaceGraphOutboxRepository.outbox_id(tenant_id, payload)
        existing = self.rows.get(row_id)
        if existing:
            return existing, False
        row = {
            "id": row_id,
            "outbox_id": row_id,
            "tenant_id": tenant_id,
            "source_event_id": source_event_id,
            "status": STATUS_QUEUED,
            "attempts": 0,
            "next_attempt_at": None,
            "last_error": None,
            "payload": payload,
            "created_at": "2026-10-10T10:00:00+00:00",
            "updated_at": "2026-10-10T10:00:00+00:00",
        }
        self.rows[row_id] = row
        return row, True

    async def find_many(self, *, filters=None, limit=100, sort_by="created_at", sort_order="asc", offset=0):
        rows = [row for row in self.rows.values() if all(row.get(k) == v for k, v in (filters or {}).items())]
        rows.sort(key=lambda row: row.get(sort_by) or "", reverse=sort_order == "desc")
        return rows[offset:offset + limit]

    async def insert(self, row_id, data):
        self.rows[row_id] = data
        return data

    async def get(self, row_id):
        return self.rows.get(row_id)

    async def list_for_tenant(self, tenant_id, limit=100_000):
        rows = [row for row in self.rows.values() if row.get("tenant_id") == tenant_id]
        return rows[:limit]

    async def list_for_tenant_page(self, tenant_id, *, limit, cursor=None):
        rows = sorted(
            (row for row in self.rows.values() if row.get("tenant_id") == tenant_id),
            key=lambda row: row["outbox_id"],
        )
        start = int(cursor or "0")
        page = rows[start:start + limit]
        truncated = start + len(page) < len(rows)
        next_cursor = str(start + len(page)) if truncated else None
        return page, next_cursor, truncated


def _vertex(tenant_id: str, vertex_id: str) -> Vertex:
    return Vertex(
        vertex_type=VertexType.AGENT_EXECUTION_RUN,
        vertex_id=vertex_id,
        properties={"tenant_id": tenant_id, "evidence_status": "source_reported"},
    )


@pytest.mark.asyncio
async def test_outbox_deduplicates_by_tenant_and_reconcile_reports_source_coverage_only(monkeypatch):
    repo = _MemoryOutboxRepository()
    outbox = AgentMarketplaceGraphProjectionOutbox(repo=repo)
    first = _vertex("tenant-a", "run-a")
    second = _vertex("tenant-a", "run-b")
    one = await outbox.enqueue_mutations("tenant-a", "event-1", [first])
    duplicate = await outbox.enqueue_mutations("tenant-a", "event-2", [first])
    assert one["queued"] == 1
    assert duplicate["duplicates"] == 1

    async def expected(tenant_id, limit, *, cursor=None):
        assert tenant_id == "tenant-a"
        return [("event-1", first), ("event-2", second)], False, None

    monkeypatch.setattr(outbox, "_expected_mutations", expected)
    report = await outbox.reconcile("tenant-a")
    assert report["source_mutations_checked"] == 2
    assert report["missing_outbox_rows"] == 1
    assert report["graph_state_checked"] is False
    repaired = await outbox.repair("tenant-a", enqueue_missing=True, replay_dead_letters=False)
    assert repaired["enqueued_missing"] == 1
    assert len(await repo.list_for_tenant("tenant-a")) == 2


@pytest.mark.asyncio
async def test_durable_outbox_repository_uses_stable_tenant_scoped_mutation_ids():
    repo = AgentMarketplaceGraphOutboxRepository()
    tenant_a, tenant_b = _tenant(), _tenant()
    payload = {
        "kind": "vertex",
        "vertex_type": "AgentExecutionRun",
        "vertex_id": "run-1",
        "properties": {"tenant_id": tenant_a},
    }
    first, created = await repo.enqueue(tenant_a, "event-1", payload)
    duplicate, duplicate_created = await repo.enqueue(tenant_a, "event-2", payload)
    other_tenant, other_created = await repo.enqueue(
        tenant_b, "event-1", {**payload, "properties": {"tenant_id": tenant_b}}
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate["outbox_id"] == first["outbox_id"]
    assert duplicate["source_event_id"] == "event-1"
    assert other_created is True
    assert other_tenant["outbox_id"] != first["outbox_id"]
    assert [row["tenant_id"] for row in await repo.list_for_tenant(tenant_a)] == [tenant_a]


@pytest.mark.asyncio
async def test_outbox_repair_requeues_stale_processing_and_dead_letters_only_for_tenant():
    repo = _MemoryOutboxRepository()
    outbox = AgentMarketplaceGraphProjectionOutbox(repo=repo)
    await outbox.enqueue_mutations("tenant-a", "event-a", [_vertex("tenant-a", "a")])
    await outbox.enqueue_mutations("tenant-b", "event-b", [_vertex("tenant-b", "b")])
    rows_a = await repo.list_for_tenant("tenant-a")
    processing = rows_a[0]
    await repo.insert(processing["outbox_id"], {
        **processing, "status": STATUS_PROCESSING,
        "updated_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    })
    dead_row, _ = await repo.enqueue("tenant-a", "event-c", {"kind": "vertex", "vertex_type": "task", "vertex_id": "dead", "properties": {}})
    dead_id = dead_row["outbox_id"]
    dead = repo.rows[dead_id]
    await repo.insert(dead_id, {**dead, "status": STATUS_DEAD_LETTERED, "attempts": 8, "last_error": "blocked"})

    report = await outbox.repair("tenant-a", enqueue_missing=False, replay_dead_letters=True)
    assert report["requeued_terminal"] == 2
    assert repo.rows[processing["outbox_id"]]["status"] == STATUS_QUEUED
    assert repo.rows[dead_id]["status"] == STATUS_QUEUED
    assert repo.rows[dead_id]["attempts"] == 0
    tenant_b_rows = await repo.list_for_tenant("tenant-b")
    assert tenant_b_rows[0]["status"] == STATUS_QUEUED


@pytest.mark.asyncio
async def test_outbox_worker_retries_blocked_gateway_writes_and_uses_enforce_idempotency(monkeypatch):
    import shared.graph.mutation_gateway as gateway_module

    repo = _MemoryOutboxRepository()
    outbox = AgentMarketplaceGraphProjectionOutbox(repo=repo)
    await outbox.enqueue_mutations("tenant-a", "event-1", [
        _vertex("tenant-a", "run-1"),
        Edge(
            edge_type=EdgeType.RUN_CONTAINS_TASK,
            from_vertex_id="run-1",
            to_vertex_id="task-1",
            properties={"tenant_id": "tenant-a"},
        ),
    ])
    calls = []

    class Gateway:
        async def apply(self, intent, *, mode_override=None):
            calls.append((intent, mode_override))
            return SimpleNamespace(blocked=len(calls) == 1, applied=len(calls) > 1, deduplicated=False)

    monkeypatch.setattr(gateway_module, "get_mutation_gateway", lambda: Gateway())
    worker = AgentMarketplaceGraphOutboxWorker(repo=repo)
    first = await worker.drain_once(tenant_id="tenant-a", limit=1)
    assert first["failed"] == 1
    row = next(iter(repo.rows.values()))
    assert row["status"] == STATUS_FAILED
    assert row["last_error"] == "RuntimeError: graph mutation was blocked by the mutation gateway"

    # Make the recorded backoff due and exercise the retry through the same worker.
    repo.rows[row["outbox_id"]]["next_attempt_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat()
    second = await worker.drain_once(tenant_id="tenant-a", limit=1)
    # The queued edge and the now-due failed vertex are both eligible in this
    # drain pass; the vertex is therefore retried successfully as well.
    assert second["succeeded"] == 2
    persisted = repo.rows[row["outbox_id"]]
    assert persisted["status"] == STATUS_PERSISTED
    assert all(mode == "enforce" for _, mode in calls)
    assert calls[0][0].operation == "node_versioned"
    assert {intent.operation for intent, _ in calls} == {"node_versioned", "edge_created"}


@pytest.mark.asyncio
async def test_outbox_worker_tenant_filter_does_not_drain_other_tenant_rows(monkeypatch):
    import shared.graph.mutation_gateway as gateway_module

    repo = _MemoryOutboxRepository()
    outbox = AgentMarketplaceGraphProjectionOutbox(repo=repo)
    await outbox.enqueue_mutations("tenant-a", "event-a", [_vertex("tenant-a", "a")])
    await outbox.enqueue_mutations("tenant-b", "event-b", [_vertex("tenant-b", "b")])
    seen = []

    class Gateway:
        async def apply(self, intent, *, mode_override=None):
            seen.append((intent, mode_override))
            return SimpleNamespace(blocked=False, applied=True, deduplicated=False)

    monkeypatch.setattr(gateway_module, "get_mutation_gateway", lambda: Gateway())
    result = await AgentMarketplaceGraphOutboxWorker(repo=repo).drain_once(tenant_id="tenant-b")
    assert result["succeeded"] == 1
    assert len(seen) == 1
    row_a = next(row for row in repo.rows.values() if row["tenant_id"] == "tenant-a")
    row_b = next(row for row in repo.rows.values() if row["tenant_id"] == "tenant-b")
    assert row_a["status"] == STATUS_QUEUED
    assert row_b["status"] == STATUS_PERSISTED


@pytest.mark.asyncio
async def test_run_explanation_is_tenant_scoped_and_labels_source_claims(monkeypatch):
    from actions.agent.deployment_routes import explain_agent_run
    from config.settings import settings
    from repositories.repos import AnalyticsRepository

    tenant_id = _tenant()
    other_tenant = _tenant()
    deployment = await AgentDeploymentRepository().create(
        tenant_id,
        {"agent_id": "agent-1", "display_name": "Bot", "external_platform": "web_widget"},
    )
    captured = {}
    async def query_silver(self, table, filters, *, limit=50):
        captured.update(table=table, filters=filters, limit=limit)
        return [
            {
                "source_event_id": "event-2", "event_name": "agent_task_completed",
                "occurred_at": "2026-10-10T10:02:00Z", "outcome_ref": "event-2",
                "outcome": "completed",
            },
            {
                "source_event_id": "event-1", "event_name": "agent_policy_evaluated",
                "occurred_at": "2026-10-10T10:01:00Z", "trigger_ref": "trigger-1",
                "policy_id": "policy-1", "policy_version": "4",
                "policy_decision": "allow", "policy_reason_codes": ["within_scope"],
            },
        ]

    monkeypatch.setattr(AnalyticsRepository, "query_silver", query_silver)
    monkeypatch.setattr(
        settings,
        "external_agent_telemetry",
        dataclasses.replace(settings.external_agent_telemetry, enabled=True, registry_enabled=True),
    )
    response = await explain_agent_run(
        deployment["id"], "run-1", SimpleNamespace(state=SimpleNamespace(
            tenant=SimpleNamespace(tenant_id=tenant_id, user_id="user", require_permission=lambda _: None),
            request_id="req",
        ), headers={}),
    )
    data = response["data"]
    assert captured == {
        "table": "silver_agent_execution_facts",
        "filters": {"tenant_id": tenant_id, "deployment_id": deployment["id"], "run_id": "run-1"},
        "limit": 200,
    }
    assert [item["source_event_id"] for item in data["evidence"]] == ["event-1", "event-2"]
    assert all(item["evidence_authority"] == "tenant_source_asserted" for item in data["evidence"])
    assert data["coverage"] == {
        "trigger_evidence": "observed", "policy_evaluation": "observed",
        "delegation": "not_observed", "outcome": "observed",
    }
    assert "do not establish hidden model reasoning" in data["explanation_boundary"]

    with pytest.raises(NotFoundError):
        await explain_agent_run(
            deployment["id"], "run-1", SimpleNamespace(state=SimpleNamespace(
                tenant=SimpleNamespace(tenant_id=other_tenant, user_id="other", require_permission=lambda _: None),
                request_id="req-other",
            ), headers={}),
        )


@pytest.mark.asyncio
async def test_deployment_run_index_groups_recent_runs_with_tenant_scope(monkeypatch):
    from actions.agent.deployment_routes import list_agent_runs
    from config.settings import settings
    from repositories.repos import AnalyticsRepository

    tenant_id = _tenant()
    other_tenant = _tenant()
    deployment = await AgentDeploymentRepository().create(
        tenant_id,
        {"agent_id": "agent-1", "display_name": "Bot", "external_platform": "web_widget"},
    )
    captured = {}

    async def query_silver(self, table, filters, *, limit=50):
        captured.update(table=table, filters=filters, limit=limit)
        return [
            {"run_id": "run-1", "occurred_at": "2026-10-10T11:02:00Z", "event_name": "agent_task_completed"},
            {"run_id": "run-2", "occurred_at": "2026-10-10T11:00:00Z", "event_name": "agent_task_started"},
            {"run_id": "run-1", "occurred_at": "2026-10-10T11:01:00Z", "event_name": "agent_tool_invocation_observed"},
            {"run_id": None, "occurred_at": "2026-10-10T10:59:00Z", "event_name": "agent_activity_observed"},
        ]

    monkeypatch.setattr(AnalyticsRepository, "query_silver", query_silver)
    monkeypatch.setattr(
        settings,
        "external_agent_telemetry",
        dataclasses.replace(settings.external_agent_telemetry, enabled=True, registry_enabled=True),
    )
    request = SimpleNamespace(state=SimpleNamespace(
        tenant=SimpleNamespace(tenant_id=tenant_id, user_id="user", require_permission=lambda _: None),
    ))
    response = await list_agent_runs(deployment["id"], request, limit=500)

    assert captured == {
        "table": "silver_agent_execution_facts",
        "filters": {"tenant_id": tenant_id, "deployment_id": deployment["id"]},
        "limit": 500,
    }
    assert response["data"]["source_status"] == "available"
    assert response["data"]["source_rows_scanned"] == 4
    runs = response["data"]["runs"]
    assert [item["run_id"] for item in runs] == ["run-1", "run-2"]
    assert runs[0]["event_count"] == 2
    assert runs[0]["first_event_at"] == "2026-10-10T11:01:00Z"
    assert runs[0]["last_event_at"] == "2026-10-10T11:02:00Z"

    wrong_tenant_request = SimpleNamespace(state=SimpleNamespace(
        tenant=SimpleNamespace(tenant_id=other_tenant, user_id="other", require_permission=lambda _: None),
    ))
    with pytest.raises(NotFoundError):
        await list_agent_runs(deployment["id"], wrong_tenant_request, limit=500)


@pytest.mark.asyncio
async def test_silver_recovery_pages_are_tenant_and_filter_bound(monkeypatch):
    import ingestion.silver.writer as silver_writer
    import repositories.repos as repos_module

    table = "silver_agent_execution_facts"
    old_rows = silver_writer._local_tables.get(table)
    rows = [
        {
            "tenant_id": "tenant-page-test",
            "fact_id": str(uuid.uuid4()),
            "source_event_id": f"event-{index}",
            "occurred_at": f"2026-10-10T10:0{index}:00+00:00",
        }
        for index in range(5)
    ]
    silver_writer._local_tables[table] = {row["fact_id"]: row for row in rows}

    async def no_pool():
        return None

    monkeypatch.setattr(repos_module, "get_pool", no_pool)
    repository = repos_module.AnalyticsRepository(None)
    try:
        first, cursor, truncated = await repository.query_silver_page(
            table, {"tenant_id": "tenant-page-test"}, limit=2,
        )
        second, cursor, truncated = await repository.query_silver_page(
            table, {"tenant_id": "tenant-page-test"}, limit=2, cursor=cursor,
        )
        third, cursor, truncated = await repository.query_silver_page(
            table, {"tenant_id": "tenant-page-test"}, limit=2, cursor=cursor,
        )
        assert [row["source_event_id"] for row in first + second + third] == [
            "event-4", "event-3", "event-2", "event-1", "event-0",
        ]
        assert cursor is None
        assert truncated is False

        _page, query_cursor, query_truncated = await repository.query_silver_page(
            table, {"tenant_id": "tenant-page-test"}, limit=1,
        )
        assert query_truncated is True
        with pytest.raises(ValueError, match="does not match this query"):
            await repository.query_silver_page(
                table, {"tenant_id": "another-tenant"}, limit=1, cursor=query_cursor,
            )
    finally:
        if old_rows is None:
            silver_writer._local_tables.pop(table, None)
        else:
            silver_writer._local_tables[table] = old_rows


@pytest.mark.asyncio
async def test_tenant_projection_recovery_returns_composite_source_cursor(monkeypatch):
    import actions.agent.deployments as deployments_module
    import dependencies.providers as providers_module
    import repositories.repos as repos_module
    from config.settings import settings

    tenant_id = _tenant()
    seen_deployments = []
    seen_silver = []

    class DeploymentPages:
        async def list_page(self, requested_tenant, *, limit, cursor=None):
            assert requested_tenant == tenant_id
            assert limit == 1
            seen_deployments.append(cursor)
            return ([], "deployment-next", True) if cursor is None else ([], None, False)

    class SilverPages:
        def __init__(self, _cache):
            pass

        async def query_silver_page(self, table, filters, *, limit, cursor=None):
            assert table == "silver_agent_execution_facts"
            assert filters == {"tenant_id": tenant_id}
            assert limit == 1
            seen_silver.append(cursor)
            return ([], "silver-next", True) if cursor is None else ([], None, False)

    monkeypatch.setattr(deployments_module, "get_deployment_repository", lambda: DeploymentPages())
    monkeypatch.setattr(providers_module, "get_cache", lambda: object())
    monkeypatch.setattr(repos_module, "AnalyticsRepository", SilverPages)
    monkeypatch.setattr(
        settings,
        "external_agent_telemetry",
        dataclasses.replace(settings.external_agent_telemetry, graph_enabled=True),
    )

    projection = AgentMarketplaceGraphProjectionOutbox()
    _expected, truncated, cursor = await projection._expected_mutations(tenant_id, 1)
    assert truncated is True
    assert cursor
    assert seen_deployments == [None]
    assert seen_silver == [None]

    _expected, truncated, final_cursor = await projection._expected_mutations(
        tenant_id, 1, cursor=cursor,
    )
    assert truncated is False
    assert final_cursor is None
    assert seen_deployments == [None, "deployment-next"]
    assert seen_silver == [None, "silver-next"]


@pytest.mark.asyncio
async def test_reconcile_marks_scans_as_non_snapshot_consistent():
    tenant_id = _tenant()
    outbox = AgentMarketplaceGraphProjectionOutbox(
        repo=AgentMarketplaceGraphOutboxRepository(),
    )

    report = await outbox.reconcile(tenant_id, limit=5)

    assert report["scan_consistency"] == "best_effort_non_snapshot"
    assert report["scan_pages_exhausted"] is True


@pytest.mark.asyncio
async def test_deployment_identity_binding_is_namespace_scoped_immutable_and_graph_explicit():
    from actions.agent.deployments import AgentDeployment, ExternalPlatform
    from actions.agent_marketplace.identity_binding import (
        AgentDeploymentIdentityBindingRepository,
        build_agent_deployment_identity_mutations,
    )
    from shared.common.common import ConflictError

    tenant_id = _tenant()
    validated_deployment = AgentDeployment(
        tenant_id=tenant_id,
        agent_id="runtime-agent-7",
        agent_source_namespace=" Vendor.Runtime ",
        display_name="Runtime agent",
        external_platform=ExternalPlatform.API_AGENT,
    )
    assert validated_deployment.agent_source_namespace == "vendor.runtime"
    with pytest.raises(ValidationError):
        AgentDeployment(
            tenant_id=tenant_id,
            agent_id="runtime-agent-7",
            agent_source_namespace="bad namespace",
            display_name="Runtime agent",
            external_platform=ExternalPlatform.API_AGENT,
        )
    repository = AgentDeploymentIdentityBindingRepository()
    binding = await repository.bind(
        tenant_id=tenant_id,
        source_namespace=" Vendor.Runtime ".strip().lower(),
        source_agent_ref="runtime-agent-7",
        canonical_agent_entity_id="canonical-agent-7",
        bound_by="tenant-admin-1",
        source_deployment_id="deployment-7",
    )
    replayed = await repository.bind(
        tenant_id=tenant_id,
        source_namespace="vendor.runtime",
        source_agent_ref="runtime-agent-7",
        canonical_agent_entity_id="canonical-agent-7",
        bound_by="tenant-admin-2",
        source_deployment_id="deployment-8",
    )
    assert replayed["id"] == binding["id"]
    assert binding["binding_authority"] == "tenant_admin_explicit"
    with pytest.raises(ConflictError):
        await repository.bind(
            tenant_id=tenant_id,
            source_namespace="vendor.runtime",
            source_agent_ref="runtime-agent-7",
            canonical_agent_entity_id="canonical-agent-other",
            bound_by="tenant-admin-1",
            source_deployment_id="deployment-7",
        )
    assert await repository.find_for_source(
        _tenant(), "vendor.runtime", "runtime-agent-7",
    ) == []

    deployment = {
        "id": "deployment-7",
        "tenant_id": tenant_id,
        "agent_id": "runtime-agent-7",
        "agent_source_namespace": "vendor.runtime",
    }
    mutations = build_agent_deployment_identity_mutations(deployment, binding)
    link = next(edge for edge in _edges(mutations) if edge.edge_type == EdgeType.AGENT_LINKED_TO_EXTERNAL_ACCOUNT)
    assert link.from_vertex_id == "canonical-agent-7"
    assert link.to_vertex_id == "deployment-7"
    assert link.properties["provenance"] == "agent_deployment_identity_binding"
    assert link.properties["binding_authority"] == "tenant_admin_explicit"
    assert build_agent_deployment_identity_mutations(
        {**deployment, "agent_source_namespace": "other.runtime"}, binding,
    ) == []


@pytest.mark.asyncio
async def test_run_authority_evaluates_canonical_delegation_separately_from_occurrence(monkeypatch):
    import actions.agent_marketplace.authority as authority_module

    tenant_id = _tenant()
    entities = {
        "canonical-grantor": {
            "entity_id": "canonical-grantor", "tenant_id": tenant_id, "entity_type": "agent",
        },
        "canonical-grantee": {
            "entity_id": "canonical-grantee", "tenant_id": tenant_id, "entity_type": "agent",
        },
    }
    identity_rows = {
        "runtime-grantor": [{
            "tenant_id": tenant_id, "source_namespace": "vendor.runtime",
            "source_agent_ref": "runtime-grantor",
            "canonical_agent_entity_id": "canonical-grantor",
            "binding_authority": "tenant_admin_explicit", "status": "active",
        }],
        "runtime-grantee": [{
            "tenant_id": tenant_id, "source_namespace": "vendor.target",
            "source_agent_ref": "runtime-grantee",
            "canonical_agent_entity_id": "canonical-grantee",
            "binding_authority": "tenant_admin_explicit", "status": "active",
        }],
    }
    binding_lookups: list[tuple[str, str]] = []
    delegation = {
        "delegation_id": "delegation-canonical-1",
        "tenant_id": tenant_id,
        "grantor_entity_id": "canonical-grantor",
        "grantee_entity_id": "canonical-grantee",
        "starts_at": "2026-10-01T00:00:00+00:00",
        "ends_at": "2026-11-01T00:00:00+00:00",
        "revoked_at": None,
        "scope": {
            "actions": ["issue.update"],
            "resources": ["repo:acme:*"],
        },
    }

    class DeploymentRepository:
        async def get_record(self, requested_tenant, deployment_id):
            assert requested_tenant == tenant_id
            return {
                "id": deployment_id,
                "tenant_id": tenant_id,
                "agent_id": "runtime-grantor",
                "agent_source_namespace": "vendor.runtime",
            }

    class DelegationRepositoryFake:
        async def find_by_id(self, delegation_id):
            assert delegation_id == "delegation-canonical-1"
            return delegation

    class BindingRepositoryFake:
        async def find_for_source(self, requested_tenant, namespace, source_ref):
            assert requested_tenant == tenant_id
            binding_lookups.append((namespace, source_ref))
            return [
                row for row in identity_rows.get(source_ref, [])
                if row["source_namespace"] == namespace
            ]

    class EntityRepositoryFake:
        async def find_by_id(self, entity_id):
            return entities.get(entity_id)

    monkeypatch.setattr(authority_module, "get_deployment_repository", lambda: DeploymentRepository())
    resolver = authority_module.AgentRunAuthorityResolver(
        delegation_repo=DelegationRepositoryFake(),
        identity_binding_repo=BindingRepositoryFake(),
        entity_repo=EntityRepositoryFake(),
    )
    row = _run_row(
        tenant_id=tenant_id,
        deployment_id="deployment-grantor",
        delegation_id="delegation-canonical-1",
        delegated_to_ref="runtime-grantee",
        delegated_to_namespace="vendor.target",
        action_type="issue.update",
        resource_ref="repo:acme:project",
        occurred_at="2026-10-10T10:00:00+00:00",
    )
    resolved = await resolver.resolve(row)
    assert resolved["delegation_resolution"]["party_identity_status"] == "matched"
    assert resolved["delegation_authorization"]["status"] == "within_scope"
    assert resolved["delegation_resolution"]["target_source_namespace"] == "vendor.target"
    assert resolved["delegation_authorization"]["target_namespace_status"] == "matched"
    assert resolved["delegation_authorization"]["actor_entity_id"] == "canonical-grantor"
    assert resolved["delegation_authorization"]["target_entity_id"] == "canonical-grantee"
    assert binding_lookups == [
        ("vendor.runtime", "runtime-grantor"),
        ("vendor.target", "runtime-grantee"),
    ]
    assert resolved["execution_occurrence"] == {
        "status": "source_reported",
        "verified": False,
        "source_event_id": row["source_event_id"],
        "reason": "no_server_authoritative_external_execution_receipt",
    }

    graph_mutations = authority_module.build_agent_run_authority_mutations(row, resolved)
    link = next(edge for edge in _edges(graph_mutations) if edge.edge_type == EdgeType.REFERENCES_DELEGATION_RECORD)
    assert link.properties["authorization_claim"] == "none"
    assert link.properties["delegation_authorization_status"] == "within_scope"
    assert link.properties["execution_occurrence"] == "source_reported"
    assert link.properties["execution_verified"] is False

    for invalid_namespace in (None, "invalid namespace"):
        binding_lookups.clear()
        unresolved = await resolver.resolve({
            **row,
            "delegated_to_namespace": invalid_namespace,
        })
        assert unresolved["delegation_resolution"]["target_identity_status"] == "unresolved"
        assert unresolved["delegation_resolution"]["target_namespace_status"] == "unresolved"
        assert unresolved["delegation_authorization"]["status"] == "indeterminate"
        assert unresolved["delegation_authorization"]["reason"] == (
            "target_source_namespace_missing_or_invalid"
        )
        # Only the actor lookup is attempted; the target is never guessed to
        # share the actor's namespace.
        assert binding_lookups == [("vendor.runtime", "runtime-grantor")]

    actor_bindings = identity_rows.pop("runtime-grantor")
    binding_lookups.clear()
    actor_unresolved = await resolver.resolve(row)
    assert actor_unresolved["delegation_resolution"]["actor_identity_status"] == "unresolved"
    assert actor_unresolved["delegation_resolution"]["target_identity_status"] == "matched"
    assert actor_unresolved["delegation_authorization"]["status"] == "indeterminate"
    assert actor_unresolved["delegation_authorization"]["reason"] == (
        "canonical_party_binding_unresolved"
    )
    assert binding_lookups == [
        ("vendor.runtime", "runtime-grantor"),
        ("vendor.target", "runtime-grantee"),
    ]
    identity_rows["runtime-grantor"] = actor_bindings


@pytest.mark.asyncio
async def test_run_authorization_is_indeterminate_for_ambiguous_bindings_and_missing_amount(monkeypatch):
    import actions.agent_marketplace.authority as authority_module

    tenant_id = _tenant()
    delegation = {
        "delegation_id": "delegation-ambiguous",
        "tenant_id": tenant_id,
        "grantor_entity_id": "canonical-a",
        "grantee_entity_id": "canonical-b",
        "starts_at": "2026-10-01T00:00:00+00:00",
        "ends_at": "2026-11-01T00:00:00+00:00",
        "revoked_at": None,
        "scope": {"actions": ["issue.update"], "max_amount": "10"},
    }

    class DeploymentRepository:
        async def get_record(self, requested_tenant, deployment_id):
            return {
                "id": deployment_id, "tenant_id": tenant_id,
                "agent_id": "runtime-a", "agent_source_namespace": "vendor.runtime",
            }

    class DelegationRepositoryFake:
        async def find_by_id(self, delegation_id):
            return delegation

    class BindingRepositoryFake:
        async def find_for_source(self, requested_tenant, namespace, source_ref):
            if source_ref == "runtime-a":
                return [{
                    "tenant_id": tenant_id, "source_namespace": namespace,
                    "source_agent_ref": source_ref, "canonical_agent_entity_id": "canonical-a",
                    "binding_authority": "tenant_admin_explicit", "status": "active",
                }]
            return [
                {"tenant_id": tenant_id, "source_namespace": namespace, "source_agent_ref": source_ref},
                {"tenant_id": tenant_id, "source_namespace": namespace, "source_agent_ref": source_ref},
            ]

    class EntityRepositoryFake:
        async def find_by_id(self, entity_id):
            return {"entity_id": entity_id, "tenant_id": tenant_id, "entity_type": "agent"}

    monkeypatch.setattr(authority_module, "get_deployment_repository", lambda: DeploymentRepository())
    resolver = authority_module.AgentRunAuthorityResolver(
        delegation_repo=DelegationRepositoryFake(),
        identity_binding_repo=BindingRepositoryFake(),
        entity_repo=EntityRepositoryFake(),
    )
    row = _run_row(
        tenant_id=tenant_id, deployment_id="deployment-a",
        delegation_id="delegation-ambiguous", delegated_to_ref="runtime-b",
        delegated_to_namespace="vendor.runtime",
        action_type="issue.update", resource_ref="repo:acme:project",
        occurred_at="2026-10-10T10:00:00+00:00",
    )
    ambiguous = await resolver.resolve(row)
    assert ambiguous["delegation_resolution"]["target_identity_status"] == "ambiguous"
    assert ambiguous["delegation_authorization"]["status"] == "indeterminate"
    assert ambiguous["delegation_authorization"]["reason"] == "canonical_party_binding_unresolved"

    class BoundRepositoryFake(BindingRepositoryFake):
        async def find_for_source(self, requested_tenant, namespace, source_ref):
            canonical = "canonical-a" if source_ref == "runtime-a" else "canonical-b"
            return [{
                "tenant_id": tenant_id, "source_namespace": namespace,
                "source_agent_ref": source_ref, "canonical_agent_entity_id": canonical,
                "binding_authority": "tenant_admin_explicit", "status": "active",
            }]

    resolver = authority_module.AgentRunAuthorityResolver(
        delegation_repo=DelegationRepositoryFake(),
        identity_binding_repo=BoundRepositoryFake(),
        entity_repo=EntityRepositoryFake(),
    )
    no_amount = await resolver.resolve(row)
    assert no_amount["delegation_authorization"]["status"] == "indeterminate"
    assert no_amount["delegation_authorization"]["reason"] == (
        "authoritative_amount_missing_for_delegation_limit"
    )


def test_delegation_authorization_reports_scope_and_time_mismatches_separately():
    from actions.agent_marketplace.authority import _evaluate_delegation_authorization

    actor = {"status": "matched", "canonical_agent_entity_id": "grantor"}
    target = {"status": "matched", "canonical_agent_entity_id": "grantee"}
    record = {
        "tenant_id": "tenant-a",
        "delegation_id": "delegation-a",
        "grantor_entity_id": "grantor",
        "grantee_entity_id": "grantee",
        "starts_at": "2026-10-01T00:00:00+00:00",
        "ends_at": "2026-11-01T00:00:00+00:00",
        "revoked_at": None,
        "scope": {"actions": ["issue.update"], "resources": ["repo:acme:*"]},
    }
    common = {
        "tenant_id": "tenant-a", "actor": actor, "target": target,
        "action_type": "issue.update", "resource_ref": "repo:acme:project",
        "occurred_at": "2026-10-10T10:00:00+00:00", "authoritative_amount": None,
    }
    assert _evaluate_delegation_authorization(record=record, **common)["status"] == "within_scope"
    out_of_scope = _evaluate_delegation_authorization(
        record=record, **{**common, "action_type": "issue.delete"},
    )
    assert out_of_scope["status"] == "out_of_scope"
    assert out_of_scope["reason"] == "action_not_in_delegation_scope"

    revoked = _evaluate_delegation_authorization(
        record={**record, "revoked_at": "2026-10-09T00:00:00+00:00"}, **common,
    )
    assert revoked["status"] == "out_of_scope"
    assert revoked["reason"] == "delegation_revoked"
    assert revoked["execution_verified"] is False


@pytest.mark.asyncio
async def test_binding_endpoint_validates_tenant_agent_and_preserves_graph_disabled_state(monkeypatch):
    import actions.agent.deployment_routes as routes_module
    import actions.agent_marketplace.identity_binding as binding_module
    from config.settings import settings
    from shared.common.common import BadRequestError

    tenant_id = _tenant()
    deployment = {
        "id": "deployment-binding-route",
        "tenant_id": tenant_id,
        "agent_id": "runtime-ref",
        "agent_source_namespace": "vendor.runtime",
    }

    class Tenant:
        user_id = "tenant-admin"

        def require_permission(self, permission):
            assert permission == "agent:manage"

    tenant = Tenant()
    tenant.tenant_id = tenant_id

    class DeploymentRepository:
        async def get(self, requested_tenant, deployment_id):
            assert requested_tenant == tenant_id
            assert deployment_id == deployment["id"]
            return deployment

    class EntityRepositoryFake:
        entity = {
            "entity_id": "canonical-agent",
            "tenant_id": tenant_id,
            "entity_type": "agent",
        }

        async def find_by_id(self, entity_id):
            assert entity_id == "canonical-agent"
            return self.entity

    saved = {}

    class BindingRepositoryFake:
        async def bind(self, **kwargs):
            saved.update(kwargs)
            return {
                "id": "binding-1", "tenant_id": tenant_id,
                "binding_authority": "tenant_admin_explicit", "status": "active",
            }

    monkeypatch.setattr(routes_module, "_repo", lambda: DeploymentRepository())
    monkeypatch.setattr(routes_module, "EntityRepository", EntityRepositoryFake)
    monkeypatch.setattr(binding_module, "AgentDeploymentIdentityBindingRepository", BindingRepositoryFake)
    monkeypatch.setattr(
        settings,
        "external_agent_telemetry",
        dataclasses.replace(
            settings.external_agent_telemetry, enabled=True, registry_enabled=True,
            graph_enabled=False,
        ),
    )
    request = SimpleNamespace(
        state=SimpleNamespace(tenant=tenant, request_id="request-1"), headers={},
    )
    response = await routes_module.bind_deployment_agent_identity(
        deployment["id"], routes_module.AgentIdentityBindingRequest(
            canonical_agent_entity_id="canonical-agent",
        ), request,
    )
    assert response["data"]["graph_projection_status"] == "disabled"
    assert saved == {
        "tenant_id": tenant_id,
        "source_namespace": "vendor.runtime",
        "source_agent_ref": "runtime-ref",
        "canonical_agent_entity_id": "canonical-agent",
        "bound_by": "tenant-admin",
        "source_deployment_id": deployment["id"],
    }

    EntityRepositoryFake.entity = {
        "entity_id": "canonical-agent", "tenant_id": "another-tenant", "entity_type": "agent",
    }
    with pytest.raises(BadRequestError):
        await routes_module.bind_deployment_agent_identity(
            deployment["id"], routes_module.AgentIdentityBindingRequest(
                canonical_agent_entity_id="canonical-agent",
            ), request,
        )


@pytest.mark.asyncio
async def test_graph_recovery_rebuilds_only_validated_deployment_identity_edges(monkeypatch):
    import actions.agent.deployments as deployments_module
    import actions.agent_marketplace.identity_binding as binding_module
    import dependencies.providers as providers_module
    import repositories.repos as repos_module
    from config.settings import settings

    tenant_id = _tenant()
    deployment = {
        "id": "deployment-recover",
        "tenant_id": tenant_id,
        "agent_id": "runtime-ref",
        "agent_source_namespace": "vendor.runtime",
    }
    binding = {
        "id": "binding-recover", "tenant_id": tenant_id,
        "source_namespace": "vendor.runtime", "source_agent_ref": "runtime-ref",
        "canonical_agent_entity_id": "canonical-agent", "binding_authority": "tenant_admin_explicit",
        "status": "active", "bound_at": "2026-10-10T10:00:00+00:00",
    }

    class DeploymentPages:
        async def list_page(self, requested_tenant, *, limit, cursor=None):
            return [deployment], None, False

    async def find_for_source(self, requested_tenant, namespace, source_ref):
        assert (requested_tenant, namespace, source_ref) == (
            tenant_id, "vendor.runtime", "runtime-ref",
        )
        return [binding]

    async def find_by_id(self, entity_id):
        return {
            "entity_id": entity_id, "tenant_id": tenant_id, "entity_type": "agent",
        }

    monkeypatch.setattr(deployments_module, "get_deployment_repository", lambda: DeploymentPages())
    monkeypatch.setattr(binding_module.AgentDeploymentIdentityBindingRepository, "find_for_source", find_for_source)
    monkeypatch.setattr(repos_module.EntityRepository, "find_by_id", find_by_id)
    monkeypatch.setattr(providers_module, "get_cache", lambda: object())
    monkeypatch.setattr(
        settings,
        "external_agent_telemetry",
        dataclasses.replace(settings.external_agent_telemetry, graph_enabled=False),
    )
    expected, truncated, cursor = await AgentMarketplaceGraphProjectionOutbox()._expected_mutations(
        tenant_id, 10,
    )
    assert not truncated and cursor is None
    identity_edges = [
        mutation for _source_event_id, mutation in expected
        if isinstance(mutation, Edge) and mutation.edge_type == EdgeType.AGENT_LINKED_TO_EXTERNAL_ACCOUNT
    ]
    assert len(identity_edges) == 1
    assert identity_edges[0].from_vertex_id == "canonical-agent"
    assert identity_edges[0].to_vertex_id == deployment["id"]
