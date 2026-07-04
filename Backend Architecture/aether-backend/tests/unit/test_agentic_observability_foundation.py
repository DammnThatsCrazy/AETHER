from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.environ.setdefault("AETHER_ENV", "local")

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from repositories.repos import reset_in_memory_stores


class Tenant:
    tenant_id = "tenant-a"

    def require_permission(self, perm: str) -> None:
        return None


def _client() -> TestClient:
    from services.agentic_observability.routes import router

    app = FastAPI()

    @app.middleware("http")
    async def tenant_middleware(request: Request, call_next):
        request.state.tenant = Tenant()
        return await call_next(request)

    app.include_router(router)
    return TestClient(app)


def _agent_event(**overrides):
    payload = {
        "tenant_id": "tenant-a",
        "event_name": "agent_activity_observed",
        "source": {"provider": "custom"},
        "actor": {"actor_type": "agent", "actor_id": "agent-1"},
        "object": {"object_type": "task", "object_id": "task-1"},
        "action": {"name": "observe", "status": "observed"},
    }
    payload.update(overrides)
    return payload


def setup_function() -> None:
    reset_in_memory_stores()
    from services.measurement.repositories.activity_repo import _local_store
    _local_store.clear()


def test_rejects_tenant_payload_mismatch() -> None:
    resp = _client().post("/v1/observability/agent/events", json=_agent_event(tenant_id="tenant-b"))
    assert resp.status_code == 403
    assert "tenant_id mismatch" in resp.text


def test_rejects_unknown_event_name() -> None:
    resp = _client().post("/v1/observability/agent/events", json=_agent_event(event_name="made_up_event"))
    assert resp.status_code == 422
    assert "Unknown event_name" in resp.text


def test_graph_counts_are_truthful_when_projection_fails() -> None:
    resp = _client().post("/v1/observability/agent/events", json=_agent_event())
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["graph_mutations_built"] == 2
    assert data["graph_mutations_persisted"] == data["graph_mutations_queued"]
    assert data["graph_projection_status"] == "outbox_queued"
    assert data["graph_mutations_queued"] == 2


def test_kyber_overview_is_repository_backed_not_placeholder() -> None:
    client = _client()
    created = client.post("/v1/observability/agent/events", json=_agent_event())
    assert created.status_code == 201, created.text
    resp = client.get("/v1/admin/kyber/agentic-observability/overview")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "message" not in data
    assert data["counts"]["activities"] == 1


def test_agent_event_enters_bronze_silver_activity_and_outbox() -> None:
    client = _client()
    resp = client.post("/v1/observability/agent/events", json=_agent_event())
    assert resp.status_code == 201, resp.text

    from repositories.repos import _IN_MEMORY_STORES

    assert len(_IN_MEMORY_STORES.get("bronze_agentic_observations", {})) == 1
    assert len(_IN_MEMORY_STORES.get("silver_agent_activity_facts", {})) == 1
    assert len(_IN_MEMORY_STORES.get("agentic_projection_outbox", {})) == 2

    outbox_rows = list(_IN_MEMORY_STORES["agentic_projection_outbox"].values())
    assert {row["status"] for row in outbox_rows} == {"queued"}
    assert {row["mutation_domain"] for row in outbox_rows} == {"graph"}


def test_agentic_graph_outbox_worker_projects_and_completes_records() -> None:
    import asyncio

    from repositories.repos import _IN_MEMORY_STORES
    from services.agentic_observability.outbox_worker import AgenticGraphOutboxWorker
    from shared.graph.graph import GraphClient

    client = _client()
    created = client.post("/v1/observability/agent/events", json=_agent_event())
    assert created.status_code == 201, created.text

    graph_client = GraphClient()
    worker = AgenticGraphOutboxWorker(graph_client=graph_client)
    result = asyncio.run(worker.process_batch(tenant_id="tenant-a"))

    assert result.scanned == 2
    assert result.completed == 2
    assert result.failed == 0
    assert {row["status"] for row in _IN_MEMORY_STORES["agentic_projection_outbox"].values()} == {"completed"}
    assert asyncio.run(graph_client.get_vertex("task-1")) is not None


def test_agentic_graph_outbox_worker_dead_letters_after_retry_limit() -> None:
    import asyncio

    from repositories.agentic_observability_repos import AgenticProjectionOutboxRepository
    from repositories.repos import _IN_MEMORY_STORES
    from services.agentic_observability.outbox_worker import AgenticGraphOutboxWorker

    class FailingGraphClient:
        async def upsert_vertex(self, vertex):  # noqa: ANN001
            raise RuntimeError("graph unavailable")

        async def add_edge(self, edge):  # noqa: ANN001
            raise RuntimeError("graph unavailable")

    async def run() -> None:
        repo = AgenticProjectionOutboxRepository()
        await repo.insert(
            "outbox-dead-letter",
            {
                "outbox_id": "outbox-dead-letter",
                "tenant_id": "tenant-a",
                "source_event_id": "evt-dead-letter",
                "mutation_domain": "graph",
                "mutation_type": "vertex",
                "payload": {"kind": "vertex", "vertex_type": "Agent", "vertex_id": "agent:tenant-a:agent-dead", "properties": {"tenantId": "tenant-a"}},
                "status": "queued",
                "attempt_count": 0,
            },
        )
        worker = AgenticGraphOutboxWorker(graph_client=FailingGraphClient(), max_attempts=1)
        result = await worker.process_batch(tenant_id="tenant-a")
        assert result.dead_lettered == 1

    asyncio.run(run())
    row = _IN_MEMORY_STORES["agentic_projection_outbox"]["outbox-dead-letter"]
    assert row["status"] == "dead_lettered"
    assert row["last_error_code"] == "RuntimeError"


def test_kyber_pipeline_health_and_lineage_are_repository_backed() -> None:
    client = _client()
    created = client.post("/v1/observability/agent/events", json=_agent_event())
    assert created.status_code == 201, created.text
    event_id = created.json()["observation_id"]

    health = client.get("/v1/admin/kyber/agentic-observability/pipeline-health")
    assert health.status_code == 200, health.text
    health_data = health.json()
    assert health_data["tenant_id"] == "tenant-a"
    assert health_data["bronze_agentic_observations"] == 1
    assert health_data["canonical_activity"] == 1
    assert health_data["outbox"]["queued"] == 2

    lineage = client.get(f"/v1/admin/kyber/agentic-observability/lineage/{event_id}")
    assert lineage.status_code == 200, lineage.text
    lineage_data = lineage.json()
    assert lineage_data["complete"] is True
    assert lineage_data["counts"] == {
        "bronze": 1,
        "silver": 1,
        "canonical_activity": 1,
        "outbox": 2,
    }
    assert lineage_data["gaps"] == []


def test_kyber_reconcile_reports_missing_pipeline_stages() -> None:
    import asyncio

    from repositories.lake import BronzeRepository, ProvenanceStatus

    async def seed_bronze_only() -> str:
        row, _ = await BronzeRepository("agentic_observations").ingest(
            source="agentic_observability",
            source_tag="agentic:agent_activity_observed",
            provider_record_id="evt-bronze-only",
            payload={"observation_id": "evt-bronze-only", "tenant_id": "tenant-a"},
            tenant_id="tenant-a",
            provenance_status=ProvenanceStatus.VALID.value,
            license_status="public_api",
            terms_status="approved",
            sensitivity_classification="metadata",
        )
        return row["id"]

    asyncio.run(seed_bronze_only())
    resp = _client().post("/v1/admin/kyber/agentic-observability/reconcile", json={"limit": 10})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "gaps_detected"
    assert data["checked"] == 1
    assert data["gap_counts"] == {
        "silver_missing": 1,
        "canonical_activity_missing": 1,
        "graph_outbox_missing": 1,
    }
    assert data["events_with_gaps"][0]["source_event_id"] == "evt-bronze-only"


def test_agentic_contract_v2_event_type_alias_and_context_lineage() -> None:
    client = _client()
    payload = _agent_event(
        schema_version="2.0",
        event_name=None,
        event_type="agent_tool_invocation_observed",
        agent={
            "agent_id": "agent-1",
            "agent_version": "2026.07.03",
            "model": "gpt-5.5",
            "model_version": "2026-07-03",
            "framework": "custom",
            "framework_version": "1.2.3",
            "runtime_id": "runtime-1",
            "environment": "prod",
            "owner_id": "human-1",
            "organization_id": "org-1",
        },
        runtime={"runtime_id": "runtime-1", "environment": "prod", "sdk_name": "@aether/node", "sdk_version": "0.1.0"},
        correlation={
            "trace_id": "trace-1",
            "task_id": "task-1",
            "connection_id": "conn-1",
            "invocation_id": "invoke-1",
            "provider_request_id": "req-1",
            "external_object_id": "obj-1",
            "campaign_id": "camp_1",
        },
        mcp={
            "protocol": "mcp",
            "protocol_version": "2025-06-18",
            "transport": "stdio",
            "server_name": "x-tools",
            "server_identity_hash": "server-hash",
            "tool_name": "x.create_post",
            "tool_id": "tool-x-create-post",
            "tool_schema_hash": "schema-hash",
            "invocation_phase": "completed",
            "arguments_policy": "metadata_only",
            "result_policy": "metadata_only",
        },
        authorization={
            "authorization_id": "auth-1",
            "credential_ref": "vault://agentic/auth-1",
            "external_account_id": "acct-1",
            "grantor_id": "human-1",
            "grantee_id": "agent-1",
            "scopes": ["tweet.write"],
            "scope_hash": "scope-hash",
        },
        verification={
            "verification_status": "provider_confirmed",
            "verification_source": "provider_api",
            "verification_confidence": 0.99,
            "provider_request_id": "req-1",
            "external_object_id": "obj-1",
            "evidence_ref": "provider:x:req-1",
        },
        privacy={
            "content_capture_mode": "metadata_only",
            "redaction_policy_id": "agentic-v2-default",
            "privacy_class": "metadata",
            "retention_class": "standard",
            "contains_sensitive_data": False,
        },
    )
    payload.pop("event_name")
    resp = client.post("/v1/observability/agent/events", json=payload)
    assert resp.status_code == 201, resp.text

    from repositories.repos import _IN_MEMORY_STORES

    facts = list(_IN_MEMORY_STORES["silver_agent_tool_invocation_facts"].values())
    assert len(facts) == 1
    fact = facts[0]
    assert fact["trace_id"] == "trace-1"
    assert fact["runtime_id"] == "runtime-1"
    assert fact["connection_id"] == "conn-1"
    assert fact["tool_id"] == "tool-x-create-post"
    assert fact["authorization_id"] == "auth-1"
    assert fact["external_account_id"] == "acct-1"
    assert fact["provider_request_id"] == "req-1"
    assert fact["external_object_id"] == "obj-1"
    assert fact["verification_status"] == "provider_confirmed"
    assert fact["evidence_ref"] == "provider:x:req-1"
    assert fact["schema_version"] == "2.0"


def test_agentic_contract_v2_rejects_conflicting_event_aliases() -> None:
    resp = _client().post(
        "/v1/observability/agent/events",
        json=_agent_event(
            schema_version="2.0",
            event_name="agent_activity_observed",
            event_type="agent_tool_invocation_observed",
        ),
    )
    assert resp.status_code == 422
    assert "event_name and event_type must match" in resp.text

def test_kyber_release_readiness_is_blocked_until_full_productization() -> None:
    resp = _client().get("/v1/admin/kyber/agentic-observability/release-readiness")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["product"] == "aether_agentic_intelligence"
    assert data["release_gate"] == "internal_preview"
    assert data["ga_ready"] is False
    assert data["complete_capabilities"] < data["total_capabilities"]
    capabilities = {item["capability"]: item for item in data["capabilities"]}
    assert capabilities["mcp_gateway_middleware_and_proxy"]["status"] == "missing"
    assert capabilities["provider_connector_lifecycle"]["status"] == "partial"
    assert capabilities["release_level_end_to_end_scenario"]["status"] == "missing"
    assert data["blockers"]


def test_agentic_product_surfaces_read_canonical_observations() -> None:
    client = _client()
    created = client.post(
        "/v1/observability/agent/events",
        json=_agent_event(
            event_name="agent_tool_invocation_observed",
            actor={"actor_type": "agent", "actor_id": "agent-1"},
            correlation={"campaign_id": "camp-agentic-1", "trace_id": "trace-agentic-1"},
            verification={"verification_status": "provider_confirmed", "external_object_id": "post-1"},
        ),
    )
    assert created.status_code == 201, created.text

    profile = client.get("/v1/admin/kyber/agentic-observability/agents/agent-1/profile360")
    assert profile.status_code == 200, profile.text
    profile_data = profile.json()
    assert profile_data["profile_type"] == "agent_profile_360"
    assert profile_data["counts"]["activities"] >= 1
    assert profile_data["counts"]["tools"] >= 1
    assert profile_data["counts"]["canonical_activities"] == 1
    assert profile_data["evidence"]["tools"][0]["evidence_classification"] == "provider_confirmed_fact"

    journey = client.get("/v1/admin/kyber/agentic-observability/journey-v2?agent_id=agent-1")
    assert journey.status_code == 200, journey.text
    journey_data = journey.json()
    assert journey_data["journey_version"] == "v2"
    assert journey_data["steps"][0]["agent_id"] == "agent-1"
    assert journey_data["steps"][0]["campaign_id"] == "camp-agentic-1"
    assert journey_data["steps"][0]["evidence_classification"] == "observed_fact"

    influence = client.get("/v1/admin/kyber/agentic-observability/campaigns/camp-agentic-1/influence")
    assert influence.status_code == 200, influence.text
    influence_data = influence.json()
    assert influence_data["agentic_touchpoint_count"] == 1
    assert influence_data["agent_ids"] == ["agent-1"]
    assert influence_data["attribution_status"] == "eligible_for_modeling"
