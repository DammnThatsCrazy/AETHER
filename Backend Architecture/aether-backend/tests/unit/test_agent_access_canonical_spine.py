"""Integration + adversarial suite for the PR-1 canonical-spine agentic bridge.

The whole point of PR-1 is that agentic observations now flow through the ONE
canonical durable spine (typed Bronze + ``event_outbox`` in a single txn →
relay → SilverDispatcher → projectors → bounded graph mutations) instead of a
bespoke per-service repo + synchronous graph write. These tests assert the REAL
wired behaviour of that path — no mocks that would let a broken wiring pass:

  1. End-to-end: ``ingest_observation`` → outbox payload → the SAME envelope the
     relay worker builds (``workers._bus_payload_to_sdk_envelope``) →
     ``SilverDispatcher().project_with_outcome`` produces a
     ``silver_agent_execution_facts`` row carrying the REAL tool name, and
     ``SilverGraphProjector`` emits a BOUNDED ``tool:{tenant}:{tool_name}``
     vertex (regression for the per-event-cardinality + wrong-field bugs).
  2. Route delegation (flag ON): ``/tools`` and ``/mcp`` write exactly one
     Bronze + one outbox row and report ``graph_mutations_queued > 0``.
  3. Flag OFF (default): the same POSTs write NO spine rows (legacy sync path).
  4. Idempotency + namespacing of the deterministic ``event_id``.
  5. Adversarial / security: tenant spoofing, recursive secret scrubbing,
     execution-claim rejection, decimal-safe economics.
  6. Kyber read compat: the legacy ``obs_agent_activities`` count still moves.

Runs fully in-memory under ``AETHER_ENV=local`` (in-memory ``ingest_many`` +
in-memory graph). It intentionally does NOT duplicate the sibling smoke test
``services/agentic_observability/tests/test_canonical_spine_ingest.py``.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.environ.setdefault("AETHER_ENV", "local")

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from config.settings import AgenticObservabilityIngestionConfig, settings  # noqa: E402
from repositories.agentic_observability_repos import AgentActivityRepository  # noqa: E402
from repositories.repos import _IN_MEMORY_STORES, reset_in_memory_stores  # noqa: E402
from services.agentic_observability.pipeline import (  # noqa: E402
    compute_event_id,
    ingest_observation,
)
from services.ingestion.workers import _bus_payload_to_sdk_envelope  # noqa: E402
from services.silver.dispatcher import SilverDispatcher  # noqa: E402
from services.silver.projectors.silver_graph_projector import SilverGraphProjector  # noqa: E402
from shared.graph.graph import get_graph_client  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _run(coro):
    """Drive a coroutine on a dedicated loop, leaving a fresh default loop behind.

    ``asyncio.run`` closes the process-wide default loop; sibling suites that
    still drive coroutines via ``asyncio.get_event_loop().run_until_complete``
    (e.g. test_observability_tenant_isolation) would then hit a closed loop when
    this module is collected before them. Installing a fresh default loop after
    each run keeps the shared loop usable across files.
    """
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


class _Tenant:
    tenant_id = "tenant-a"

    def require_permission(self, perm: str) -> None:  # authoritative in-test tenant
        return None


def _client() -> TestClient:
    """FastAPI app wired with the agentic-observability routers + fake tenant.

    Includes BOTH ``router`` and ``mcp_router`` because ``/v1/observability/
    agent/mcp`` lives on the separate ``mcp_router``.
    """
    from services.agentic_observability.routes import mcp_router, router

    app = FastAPI()

    @app.middleware("http")
    async def tenant_middleware(request: Request, call_next):  # noqa: ANN001
        request.state.tenant = _Tenant()
        return await call_next(request)

    app.include_router(router)
    app.include_router(mcp_router)
    return TestClient(app)


def _set_spine(enabled: bool):
    prev = settings.agentic_observability_ingestion
    settings.agentic_observability_ingestion = AgenticObservabilityIngestionConfig(
        canonical_spine_enabled=enabled
    )
    return prev


@pytest.fixture
def spine_on():
    prev = _set_spine(True)
    try:
        yield
    finally:
        settings.agentic_observability_ingestion = prev


@pytest.fixture
def spine_off():
    prev = _set_spine(False)
    try:
        yield
    finally:
        settings.agentic_observability_ingestion = prev


def _bronze():
    return _IN_MEMORY_STORES.setdefault("bronze_sdk_events", {})


def _outbox():
    return _IN_MEMORY_STORES.setdefault("event_outbox", {})


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


# ---------------------------------------------------------------------------
# 1. End-to-end: ingest → relay envelope → Silver fact → bounded graph vertex
# ---------------------------------------------------------------------------

def test_end_to_end_tool_observation_flows_to_silver_and_bounded_graph_vertex():
    tenant = "tenant-e2e-1"

    async def _flow():
        # Connect the graph client up front: connect() re-inits the in-memory
        # backend, so it must run BEFORE emission (never after, or it wipes the
        # just-written vertices). The emission and this read share the same
        # process-wide client.
        client = get_graph_client()
        await client.connect()

        result = await ingest_observation(
            tenant_id=tenant,
            event_name="agent_tool_invocation_observed",
            provider_id="mcp",
            integration_id="int-1",
            environment_id="prod",
            provider_event_id="prov-evt-e2e-1",
            agent_id="agent-e2e",
            observed_at="2026-07-24T00:00:00+00:00",
            properties={
                "agentId": "agent-e2e",
                "toolName": "search_web",     # the REAL tool name
                "serverName": "acme-mcp",
                "serverUrl": "https://mcp.acme.test",
                "status": "succeeded_observed",
                "provider": "mcp",
                "objectType": "tool",         # NOT the tool name — regression guard
                "objectId": "search_web",
            },
        )
        assert result.status == "accepted"
        assert result.outbox_written == 1

        # Take the exact payload the relay would publish and rebuild the SDK
        # envelope the Silver projectors consume — the real worker path.
        (outbox_row,) = list(_outbox().values())
        assert outbox_row["topic"] == "aether.sdk.events.validated"
        envelope = _bus_payload_to_sdk_envelope(outbox_row["payload"])
        assert envelope["type"] == "agent_tool_invocation_observed"
        assert envelope["context"]["tenantId"] == tenant

        outcome = await SilverDispatcher().project_with_outcome(envelope)
        aef = [r for r in outcome.results if r.table == "silver_agent_execution_facts"]
        assert len(aef) == 1, f"expected one agent_execution_facts result, got {len(aef)}"
        row = aef[0].rows[0]

        # Regression for the wrong-field bug: tool_name is the REAL tool name,
        # never object_type ("tool").
        assert row["tool_name"] == "search_web"
        assert row["object_type"] == "tool"
        assert row["tool_name"] != row["object_type"]
        assert row["event_name"] == "agent_tool_invocation_observed"
        assert row["server_name"] == "acme-mcp"

        # Drive the real graph emission for this Silver table.
        await SilverGraphProjector().maybe_emit(aef[0], envelope)

        vertex_ids = {v.vertex_id for v in await client.get_all_vertices()}
        # BOUNDED vertex id carries the real tool name…
        assert f"tool:{tenant}:search_web" in vertex_ids
        # …and NOT the object_type ("tool"): a wrong-field emission would
        # produce tool:{tenant}:tool.
        assert f"tool:{tenant}:tool" not in vertex_ids

        vertex = await client.get_vertex(f"tool:{tenant}:search_web")
        assert vertex is not None
        assert vertex.properties.get("tool_name") == "search_web"

    _run(_flow())


def test_bounded_tool_vertex_cardinality_across_distinct_events():
    """Three DISTINCT source events for one (agent, tool) → exactly ONE vertex.

    Regression for per-event graph cardinality: the vertex is keyed on
    (tenant, tool) and the edge idempotency key EXCLUDES the source event, so
    repeated observations converge instead of exploding the graph.
    """
    tenant = "tenant-card-1"

    async def _flow():
        client = get_graph_client()
        await client.connect()
        edge_keys: set[str] = set()
        source_event_ids: set[str] = set()

        for pe in ("prov-A", "prov-B", "prov-C"):
            res = await ingest_observation(
                tenant_id=tenant,
                event_name="agent_tool_invocation_observed",
                provider_id="mcp",
                provider_event_id=pe,
                agent_id="agent-card",
                properties={"agentId": "agent-card", "toolName": "search_web", "provider": "mcp"},
            )
            outbox_row = next(v for v in _outbox().values() if v["event_id"] == res.event_id)
            envelope = _bus_payload_to_sdk_envelope(outbox_row["payload"])
            outcome = await SilverDispatcher().project_with_outcome(envelope)
            aef = next(r for r in outcome.results if r.table == "silver_agent_execution_facts")
            await SilverGraphProjector().maybe_emit(aef, envelope)

        tool_vertices = [
            v.vertex_id for v in await client.get_all_vertices()
            if v.vertex_id.startswith(f"tool:{tenant}:")
        ]
        assert tool_vertices == [f"tool:{tenant}:search_web"], tool_vertices

        for edge in await client.get_edges("agent-card"):
            if edge.to_vertex_id == f"tool:{tenant}:search_web":
                edge_keys.add(edge.properties.get("idempotency_key"))
                source_event_ids.add(edge.properties.get("source_event_id"))
        # All 3 events collapse onto ONE bounded (event-excluding) idempotency
        # key, even though each carries its own distinct source_event_id.
        assert len(edge_keys) == 1, edge_keys
        assert len(source_event_ids) == 3, source_event_ids

    _run(_flow())


# ---------------------------------------------------------------------------
# 2. Route delegation (flag ON) — spine rows + queued graph mutations
# ---------------------------------------------------------------------------

def test_route_tools_delegates_to_spine_when_flag_on(spine_on):
    resp = _client().post(
        "/v1/observability/agent/tools",
        json={"tenant_id": "tenant-a", "agent_id": "agent-1",
              "tool_name": "search_web", "status": "succeeded_observed"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    # Regression for the graph_mutations_queued == 0 bug.
    assert data["graph_mutations_queued"] > 0
    assert data["graph_projection_status"] == "queued"
    assert len(_bronze()) == 1
    assert len(_outbox()) == 1


def test_route_mcp_delegates_to_spine_when_flag_on(spine_on):
    resp = _client().post(
        "/v1/observability/agent/mcp",
        json={"tenant_id": "tenant-a", "agent_id": "agent-1",
              "server_name": "acme", "server_url": "https://mcp.acme.test",
              "tools": ["search_web"]},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["graph_mutations_queued"] > 0
    assert data["graph_projection_status"] == "queued"
    assert len(_bronze()) == 1
    assert len(_outbox()) == 1


# ---------------------------------------------------------------------------
# 3. Flag OFF (default) — no spine rows, legacy synchronous shape
# ---------------------------------------------------------------------------

def test_route_tools_flag_off_uses_legacy_path(spine_off):
    resp = _client().post(
        "/v1/observability/agent/tools",
        json={"tenant_id": "tenant-a", "agent_id": "agent-1", "tool_name": "search_web"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["graph_mutations_queued"] == 0
    # No canonical-spine rows written on the OFF path.
    assert len(_bronze()) == 0
    assert len(_outbox()) == 0
    # Legacy synchronous response shape is preserved.
    assert set(data) >= {"observation_id", "received_at", "graph_mutations_queued", "tenant_id"}


def test_route_mcp_flag_off_uses_legacy_path(spine_off):
    resp = _client().post(
        "/v1/observability/agent/mcp",
        json={"tenant_id": "tenant-a", "agent_id": "agent-1", "server_name": "acme"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["graph_mutations_queued"] == 0
    assert len(_bronze()) == 0
    assert len(_outbox()) == 0


# ---------------------------------------------------------------------------
# 4. Idempotency + namespacing of the deterministic event_id
# ---------------------------------------------------------------------------

def test_same_provider_event_id_is_idempotent_duplicate():
    async def _flow():
        base = dict(
            tenant_id="tenant-idem",
            event_name="agent_tool_invocation_observed",
            provider_id="mcp",
            integration_id="int-1",
            environment_id="prod",
            provider_event_id="prov-evt-dup",
        )
        # Different non-identifying fields (agent_id / properties) must NOT
        # change the deterministic id — only the namespacing tuple does.
        first = await ingest_observation(**base, agent_id="agent-A", properties={"toolName": "x"})
        second = await ingest_observation(**base, agent_id="agent-B", properties={"toolName": "y"})

        assert first.event_id == second.event_id
        assert first.status == "accepted"
        assert first.outbox_written == 1
        assert second.status == "duplicate"
        assert second.outbox_written == 0
        # No second Bronze / outbox row on replay.
        assert len(_bronze()) == 1
        assert len(_outbox()) == 1

    _run(_flow())


def test_event_id_is_namespaced_by_provider_integration_environment_tenant():
    kw = dict(
        tenant_id="t1", provider_id="mcp", integration_id="int-1",
        environment_id="prod", provider_event_id="prov-evt-ns",
    )
    base = compute_event_id(**kw)
    assert compute_event_id(**{**kw, "provider_id": "other"}) != base
    assert compute_event_id(**{**kw, "integration_id": "other"}) != base
    assert compute_event_id(**{**kw, "environment_id": "other"}) != base
    assert compute_event_id(**{**kw, "tenant_id": "other"}) != base


# ---------------------------------------------------------------------------
# 5. Adversarial / security
# ---------------------------------------------------------------------------

def test_tenant_spoofing_is_rejected_403(spine_on):
    client = _client()
    # Payload tenant_id != authenticated tenant → 403 before any spine write.
    tools = client.post(
        "/v1/observability/agent/tools",
        json={"tenant_id": "tenant-EVIL", "agent_id": "agent-1", "tool_name": "x"},
    )
    assert tools.status_code == 403
    assert "tenant_id mismatch" in tools.text

    mcp = client.post(
        "/v1/observability/agent/mcp",
        json={"tenant_id": "tenant-EVIL", "agent_id": "agent-1", "server_name": "s"},
    )
    assert mcp.status_code == 403
    # A rejected spoof must not have written anything through the spine.
    assert len(_bronze()) == 0
    assert len(_outbox()) == 0


def test_secrets_are_recursively_scrubbed_from_bronze():
    async def _flow():
        await ingest_observation(
            tenant_id="tenant-scrub",
            event_name="agent_activity_observed",
            provider_id="custom",
            provider_event_id="prov-evt-scrub",
            properties={
                "api_key": "sk-should-not-persist",
                "private_key": "pk-should-not-persist",
                "seed_phrase": "correct horse battery staple",
                "refresh_token": "rt-should-not-persist",
                "toolName": "search_web",  # non-secret survives
                "nested": {
                    "access_token": "at-should-not-persist",
                    "client_secret": "cs-should-not-persist",
                    "safe": "keep-me",
                },
            },
        )
        (row,) = list(_bronze().values())
        props = row["payload"]["properties"]
        for key in ("api_key", "private_key", "seed_phrase", "refresh_token"):
            assert props[key] == "[REDACTED]", f"{key} leaked into Bronze: {props[key]!r}"
        # Recursion: nested secrets are redacted, non-secret siblings preserved.
        assert props["nested"]["access_token"] == "[REDACTED]"
        assert props["nested"]["client_secret"] == "[REDACTED]"
        assert props["nested"]["safe"] == "keep-me"
        assert props["toolName"] == "search_web"
        # No raw secret VALUE survives anywhere in the persisted payload.
        blob = str(row["payload"])
        assert "should-not-persist" not in blob
        assert "correct horse battery staple" not in blob

    _run(_flow())


def test_authorization_key_is_scrubbed_from_bronze():
    # Regression: a bare 'authorization' header key must be redacted before Bronze.
    # Closed by adding \bauthorization\b (+ bearer/cookie/session_token) to
    # services/ingestion/validation.py::_SENSITIVE_KEY_PATTERNS.
    async def _flow():
        await ingest_observation(
            tenant_id="tenant-authz",
            event_name="agent_activity_observed",
            provider_id="custom",
            provider_event_id="prov-evt-authz",
            properties={"authorization": "Bearer super-secret-token"},
        )
        (row,) = list(_bronze().values())
        assert row["payload"]["properties"].get("authorization") == "[REDACTED]"

    _run(_flow())


def test_execution_claim_is_rejected_422(spine_on):
    client = _client()
    # Top-level execution claim.
    r1 = client.post("/v1/observability/agent/events", json=_agent_event(execution_by_aether=True))
    assert r1.status_code == 422, r1.text
    # Nested economics execution claim.
    r2 = client.post(
        "/v1/observability/agent/events",
        json=_agent_event(economics={"amount": "1", "is_execution_by_aether": True}),
    )
    assert r2.status_code == 422, r2.text
    # Neither rejected request wrote through the spine.
    assert len(_bronze()) == 0
    assert len(_outbox()) == 0


def test_economics_amount_rejects_binary_float_and_round_trips_decimal_string(spine_on):
    client = _client()
    # A binary float amount is rejected (money must be a decimal string).
    bad = client.post(
        "/v1/observability/agent/events",
        json=_agent_event(economics={"amount": 12.34, "currency": "USD"}),
    )
    assert bad.status_code == 422, bad.text

    # A decimal string is accepted and round-trips as a STRING in Bronze.
    good = client.post(
        "/v1/observability/agent/events",
        json=_agent_event(
            economics={"amount": "12.34", "currency": "USD"},
            source={"provider": "custom", "provider_event_id": "prov-evt-econ"},
        ),
    )
    assert good.status_code == 201, good.text
    (row,) = list(_bronze().values())
    amount = row["payload"]["properties"]["amount"]
    assert amount == "12.34"
    assert isinstance(amount, str)


# ---------------------------------------------------------------------------
# 6. Kyber read compat — legacy obs_agent_activities count still increments
# ---------------------------------------------------------------------------

def test_kyber_activity_count_increments_after_delegated_observation():
    tenant = "tenant-kyber"

    async def _flow():
        repo = AgentActivityRepository()
        before = await repo.count({"tenant_id": tenant})
        await ingest_observation(
            tenant_id=tenant,
            event_name="agent_tool_invocation_observed",
            provider_id="mcp",
            provider_event_id="prov-evt-kyber",
            agent_id="agent-kyber",
            properties={"agentId": "agent-kyber", "toolName": "search_web", "provider": "mcp"},
        )
        after = await repo.count({"tenant_id": tenant})
        assert after == before + 1, f"legacy obs_agent_activities did not increment: {before} -> {after}"

    _run(_flow())
