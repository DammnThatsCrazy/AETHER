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
