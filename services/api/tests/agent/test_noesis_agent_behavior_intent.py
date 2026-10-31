"""Noesis ``agent_behavior`` intent end to end (WO-115).

Classifier mapping, allowlist / registry / QueryPlan parity, the agent:manage
and registry-flag gates, tenant scoping, honest absent data, and parity with
the ``GET /v1/agent/agents/{agent_ref}/behavior`` route (same read model).
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import pytest

import actions.agent.deployment_routes as agent_routes
from ingestion.silver import writer as silver_writer
from ingestion.silver.projectors.agent_execution_projector import AgentExecutionProjector
from intelligence.noesis.adapters import agent_behavior_adapter
from intelligence.noesis.capability_registry import get_capability
from intelligence.noesis.models import SUPPORTED_INTENTS, NoesisQueryRequest, QueryPlan
from intelligence.noesis.service import NoesisService, Scope
from repositories.repos import AnalyticsRepository, reset_in_memory_stores
from shared.auth.auth import Role, TenantContext
from shared.cache.cache import CacheClient
from shared.graph.graph import GraphClient

FIXTURE = json.loads((Path(__file__).resolve().parents[4] / "tests/fixtures/agent_behavior/golden_scenarios.json").read_text())
T = FIXTURE["tenant_id"]
AGENT = "gsc-buyer"


class _Flags:
    noesis_enabled = True
    debug_enabled = False
    multi_hop_enabled = False

    def is_tenant_allowed(self, tenant_id: str) -> bool:
        return True


def _events(sid):
    return [{"messageId": ev["id"], "type": ev["type"], "tenantId": T, "timestamp": ev["at"],
             "properties": {"agentId": ev["agent"], **ev["properties"]}}
            for ev in next(s for s in FIXTURE["scenarios"] if s["id"] == sid)["events"]]


async def _persist(events):
    for e in events:
        r = AgentExecutionProjector().project(e)
        await silver_writer.SilverFactWriter()._persist_generic(r.table, r.rows)


@pytest.fixture
def registry_on(monkeypatch):
    reset_in_memory_stores()
    silver_writer.reset_local_tables()
    monkeypatch.setattr(agent_routes.settings, "external_agent_telemetry",
                        dataclasses.replace(agent_routes.settings.external_agent_telemetry,
                                            enabled=True, registry_enabled=True))
    yield
    reset_in_memory_stores()
    silver_writer.reset_local_tables()


@pytest.fixture
def service() -> NoesisService:
    return NoesisService(graph=GraphClient(), analytics=AnalyticsRepository(CacheClient()), flags=_Flags())


def _scope(tenant=T, *, manage=True) -> Scope:
    return Scope("aether", tenant, False, False, agent_manage=manage)


def _plan(target=AGENT, tenant=T) -> QueryPlan:
    return QueryPlan(intent="agent_behavior", target=target, tenant_id=tenant)  # type: ignore[arg-type]


def _req(message="explain the behavior of agent gsc-buyer") -> NoesisQueryRequest:
    return NoesisQueryRequest(message=message, surface="aether")


# --- classification and parity ------------------------------------------------

@pytest.mark.parametrize("message", [
    "What does agent ag_123 usually do?",
    "Explain the behavior of agent ag_123",
    "Show the decisions agent ag_123 made",
    "Show the blind spots for agent ag_123",
])
def test_classifier_maps_behavior_phrasings(service, message):
    plan = service._classify(NoesisQueryRequest(message=message, surface="aether"), _scope())
    assert plan.intent == "agent_behavior"
    assert plan.target == "ag_123"
    assert plan.confidence >= 0.8


def test_plain_agent_queries_still_route_to_agent_lookup(service):
    for message in ("List active agents", "Find agent configuration"):
        plan = service._classify(NoesisQueryRequest(message=message, surface="aether"), _scope())
        assert plan.intent == "agent_lookup"


def test_intent_registered_in_every_parity_list(service):
    assert "agent_behavior" in SUPPORTED_INTENTS
    assert "agent_behavior" in set(get_args(QueryPlan.model_fields["intent"].annotation))
    cap = get_capability("agent_behavior")
    assert cap is not None and cap.requires_target is True
    assert cap.surfaces == ["aether", "kyber"]
    assert "read-only" in cap.description.lower() and "agent:manage" in cap.description
    service._assert_read_only(_plan())


def test_scope_carries_agent_manage_from_permissions(service):
    body = NoesisQueryRequest(message="x", surface="aether")
    viewer = TenantContext(tenant_id=T, role=Role.VIEWER, permissions=["read"])
    manager = TenantContext(tenant_id=T, role=Role.VIEWER, permissions=["read", "agent:manage"])
    assert service._resolve_scope(body, viewer).agent_manage is False
    assert service._resolve_scope(body, manager).agent_manage is True


# --- gates ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_registry_disabled_is_service_disabled(service, monkeypatch):
    monkeypatch.setattr(agent_routes.settings, "external_agent_telemetry",
                        dataclasses.replace(agent_routes.settings.external_agent_telemetry,
                                            enabled=False, registry_enabled=False))
    response = await service._dispatch(_plan(), _scope(), _req())
    assert response.error is not None and response.error.code == "service_disabled"
    assert response.results == []


@pytest.mark.asyncio
async def test_without_agent_manage_is_forbidden_and_reads_nothing(service, registry_on, monkeypatch):
    async def _boom(*_a, **_k):
        raise AssertionError("read model must not be read without agent:manage")

    monkeypatch.setattr(agent_behavior_adapter, "read_agent_behavior", _boom)
    response = await service._dispatch(_plan(), _scope(manage=False), _req())
    assert response.error is not None and response.error.code == "forbidden"
    assert response.results == []


@pytest.mark.asyncio
async def test_query_entry_point_enforces_agent_manage(service, registry_on):
    viewer = TenantContext(tenant_id=T, role=Role.VIEWER, permissions=["read"])
    response = await service.query(_req(), viewer)
    assert response.intent == "agent_behavior"
    assert response.error is not None and response.error.code == "forbidden"


@pytest.mark.asyncio
async def test_missing_target_and_fleet_scope_ask_to_refine(service, registry_on):
    no_target = await service._dispatch(_plan(target=None), _scope(), _req("agent behavior"))
    assert no_target.actions and no_target.actions[0].type == "refine_query"
    fleet = await service._dispatch(_plan(tenant=""), Scope("kyber", "", True, False, agent_manage=True), _req())
    assert fleet.actions and fleet.actions[0].type == "refine_query"


# --- read model -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_reads_the_same_model_as_the_http_route(service, registry_on):
    await _persist(_events("GS-C"))
    response = await service._dispatch(_plan(), _scope(), _req())
    assert response.error is None
    assert response.evidence.sufficient is True
    [model] = response.results
    assert model["sections"]["decisions"]["data"][0]["disposition"] == "constrained_non_action"
    assert "1 reconstructed decision(s)" in response.answer
    assert "not an identity resolution" in response.answer
    assert {s.resource_type for s in response.evidence.sources} == set(agent_behavior_adapter.SOURCES)

    request = SimpleNamespace(state=SimpleNamespace(tenant=SimpleNamespace(
        tenant_id=T, user_id="u", site_ids=[], require_permission=lambda _: None)))
    route = (await agent_routes.agent_behavior_read_model(AGENT, request))["data"]
    assert model["sections"]["behavior"] == route["sections"]["behavior"]
    assert model["sections"]["decisions"] == route["sections"]["decisions"]


@pytest.mark.asyncio
async def test_other_tenant_sees_no_behavior(service, registry_on):
    await _persist(_events("GS-C"))
    response = await service._dispatch(_plan(tenant="other-tenant"), _scope("other-tenant"), _req())
    assert response.evidence.sufficient is False
    assert "not evidence the agent is inactive" in response.answer


@pytest.mark.asyncio
async def test_read_failure_is_honest_unavailability(service, registry_on, monkeypatch):
    async def _fail(*_a, **_k):
        raise RuntimeError("silver down")

    monkeypatch.setattr(agent_behavior_adapter, "read_agent_behavior", _fail)
    response = await service._dispatch(_plan(), _scope(), _req())
    assert response.evidence.sufficient is False
    assert "unavailable" in response.answer
    assert response.results == []
