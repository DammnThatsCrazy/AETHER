"""Agent360 / Profile360 behavior read models, routes and query capabilities (WO-110–WO-132)."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import actions.agent.deployment_routes as agent_routes
from ingestion.silver import writer as silver_writer
from ingestion.silver.projectors.agent_execution_projector import AgentExecutionProjector
from intelligence.agent_behavior.facts import normalize_rows
from intelligence.agent_behavior.read_models import (
    QUERY_CAPABILITIES, agent360_behavior, communications, decision_detail, human_agent_coupling,
    human_overrides, profile360_agents, run_capability,
)
from repositories.repos import reset_in_memory_stores
from shared.common.common import NotFoundError

FIXTURE = json.loads((Path(__file__).resolve().parents[4] / "tests/fixtures/agent_behavior/golden_scenarios.json").read_text())
T = FIXTURE["tenant_id"]


def _events(sid):
    return [{"messageId": ev["id"], "type": ev["type"], "tenantId": T, "timestamp": ev["at"],
             "properties": {"agentId": ev["agent"], **ev["properties"]}}
            for ev in next(s for s in FIXTURE["scenarios"] if s["id"] == sid)["events"]]


def _facts(events):
    rows = [r for e in events for r in AgentExecutionProjector().project(e).rows]
    return normalize_rows(rows, T)


def _extra(i, etype, agent, **props):
    return {"messageId": f"rm-{i:03d}", "type": etype, "tenantId": T,
            "timestamp": f"2026-10-22T14:00:{i:02d}Z", "properties": {"agentId": agent, **props}}


def test_agent360_sections_report_state_and_blind_spots():
    facts = _facts(_events("GS-A"))
    rm = agent360_behavior(facts, "gsa-orch")
    sec = rm["sections"]
    assert sec["identity"]["state"] == "unavailable" and sec["identity"]["reason"]
    assert sec["behavior"]["state"] == "available"
    assert [a["agent"] for a in sec["journey"]["data"]["agents"]] == ["gsa-orch", "gsa-wkr-flights", "gsa-wkr-hotels"]
    assert "memory" in sec["observability"]["data"]["not_observed_families"]
    assert sec["influence"]["data"]["by_state"]["observed"] == 2
    assert agent360_behavior(facts, "nobody")["sections"]["behavior"]["state"] == "unavailable"
    assert agent360_behavior(facts, "gsa-orch", truncated=True)["sections"]["behavior"]["state"] == "partial"


def test_decision_detail_for_gs_c():
    facts = _facts(_events("GS-C"))
    detail = decision_detail(facts, "derived:gsc-buyer:gsc-task-buy")
    assert detail["envelope"]["disposition"]["disposition"] == "constrained_non_action"
    assert detail["counterfactual"]["status"] == "hypothetical"
    assert detail["attribution"]["factors"][0]["factor"] == "constraint_removed_alternative"
    assert decision_detail(facts, "missing") is None


def test_profile360_overrides_coupling_and_communications():
    events = _events("GS-A") + [
        _extra(1, "agent_authorization_requested", "gsa-orch", authorizationId="az1"),
        _extra(5, "agent_authorization_granted", "gsa-orch", authorizationId="az1", approverActorId="gsa-person-1"),
        _extra(6, "agent_human_override_observed", "gsa-orch", decisionId="dz", overriddenBy="gsa-person-1",
               humanOverride=True),
        _extra(7, "agent_execution_succeeded", "gsa-orch", decisionId="dz"),
        _extra(8, "agent_message_sent_observed", "gsa-orch", threadId="th1"),
        _extra(9, "agent_message_generated", "gsa-orch", threadId="th1"),
    ]
    facts = _facts(events)
    grants = [{"delegation_id": "gsa-del-1", "grantor_entity_id": "gsa-person-1", "grantee_entity_id": "gsa-orch"}]
    prof = profile360_agents("gsa-person-1", facts, grants)
    assert prof["identity_merge"] == "not_performed"
    assert prof["agents"][0] == {**prof["agents"][0], "agent_ref": "gsa-orch", "link_basis": "recorded_grant"}
    coupling = human_agent_coupling("gsa-person-1", facts, ["gsa-orch"])
    assert coupling["approval_requests"] == 1 and coupling["approval_latency_seconds_median"] == 4.0
    [ov] = human_overrides(facts)
    assert ov["overridden_by"]["value"] == "gsa-person-1" and ov["outcome_after"] == "agent_execution_succeeded"
    comms = communications(facts, "gsa-orch")
    assert comms["threads"] == 1 and comms["content"] == "not_stored"


def test_query_capabilities_are_closed():
    facts = _facts(_events("GS-A"))
    assert set(QUERY_CAPABILITIES) >= {"agent_behavior.summary", "agent_behavior.decision"}
    assert run_capability("agent_behavior.summary", facts, {"agent_ref": "gsa-orch"})["agent_ref"] == "gsa-orch"
    with pytest.raises(ValueError):
        run_capability("agent_behavior.free_text", facts, {})
    with pytest.raises(ValueError):
        run_capability("agent_behavior.summary", facts, {})


@pytest.fixture
def _routes(monkeypatch):
    reset_in_memory_stores()
    silver_writer.reset_local_tables()
    monkeypatch.setattr(agent_routes.settings, "external_agent_telemetry",
                        dataclasses.replace(agent_routes.settings.external_agent_telemetry,
                                            enabled=True, registry_enabled=True))
    yield
    reset_in_memory_stores()
    silver_writer.reset_local_tables()


def _request(tenant=T):
    t = SimpleNamespace(tenant_id=tenant, user_id="u", site_ids=[], require_permission=lambda _: None)
    return SimpleNamespace(state=SimpleNamespace(tenant=t))


async def _persist(events):
    for e in events:
        r = AgentExecutionProjector().project(e)
        await silver_writer.SilverFactWriter()._persist_generic(r.table, r.rows)


@pytest.mark.asyncio
async def test_behavior_routes_are_tenant_scoped(_routes):
    await _persist(_events("GS-C"))
    data = (await agent_routes.agent_behavior_read_model("gsc-buyer", _request()))["data"]
    assert data["sections"]["decisions"]["data"][0]["disposition"] == "constrained_non_action"
    other = (await agent_routes.agent_behavior_read_model("gsc-buyer", _request("other-tenant")))["data"]
    assert other["sections"]["behavior"]["state"] == "unavailable"
    detail = (await agent_routes.agent_decision_detail(
        "gsc-buyer", "derived:gsc-buyer:gsc-task-buy", _request()))["data"]
    assert detail["envelope"]["status"] == "closed"
    with pytest.raises(NotFoundError):
        await agent_routes.agent_decision_detail("gsc-buyer", "derived:gsc-buyer:gsc-task-buy", _request("other-tenant"))
    with pytest.raises(NotFoundError):
        await agent_routes.agent_decision_detail("someone-else", "derived:gsc-buyer:gsc-task-buy", _request())
