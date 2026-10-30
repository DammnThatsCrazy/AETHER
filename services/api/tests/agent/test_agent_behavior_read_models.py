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
    assert sec["identity"]["data"]["agent"]["recognition"] == "probable_agent"
    assert all(cl["merge_eligible"] is False for cl in sec["identity"]["data"]["resolver_claims"])
    assert sec["authority"]["state"] == "unavailable" and sec["value"]["state"] == "unavailable"
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


def test_governance_sections_compose_owner_seams():
    events = [
        _extra(1, "agent_transaction_initiated", "buyer", amount="120.00", currency="USD",
               resourceRef="merchant:shop-1", actionType="purchase", decisionId="dz"),
        _extra(2, "agent_action_selected", "buyer", decisionId="dz", candidateId="sku"),
        *[_extra(3 + i, "agent_authorization_denied", "buyer") for i in range(3)],
    ]
    facts = _facts(events)
    grants = [{"delegation_id": "g1", "grantor_entity_id": "person-1", "grantee_entity_id": "buyer",
               "starts_at": "2026-10-01T00:00:00Z", "scope": {"actions": ["purchase"], "max_amount": "100.00"}}]
    sec = agent360_behavior(facts, "buyer", grants=grants)["sections"]
    [check] = sec["authority"]["data"]
    assert check["status"] == "outside" and "max_transaction_exceeded" in check["reasons"]
    [total] = sec["value"]["data"]["totals"]
    assert total == {"class": "agent_selected_and_executed", "currency": "USD", "finality": "reported", "amount": "120.00"}
    sources = {s["source"] for s in sec["risk"]["data"]["signals"]}
    assert "agent_behavior.authority_boundary_exceeded" in sources
    assert {a["kind"] for a in sec["risk"]["data"]["adversarial"]} >= {"authority_probing", "authority_boundary_exceeded"}
    assert sec["trust"]["data"]["trust"]["authority_compliance"]["outside"] == 1
    assert sec["trust"]["data"]["reputation"]["kind"] == "reputation"
    assert sec["market"]["data"][0]["target"] == "merchant:shop-1"


@pytest.mark.asyncio
async def test_behavior_route_shows_queued_agent_continuity_reviews(_routes, monkeypatch):
    from actions.agent.deployments import get_deployment_repository
    from config.settings import settings
    from identity.identity import ingestion_worker
    from shared.events.events import Event, Topic

    monkeypatch.setattr(settings, "identity_continuity",
                        dataclasses.replace(settings.identity_continuity, resolution_enabled=True))
    deps = [await get_deployment_repository().create(T, {
        "agent_id": "dup-agent", "display_name": "bot", "external_platform": platform,
        "environment": "production", "consent_mode": "tenant_managed"}, actor="t", request_id="r")
        for platform in ("web_widget", "slack_app")]

    class _Producer:
        async def publish(self, event):
            return None

    for i, dep in enumerate(deps):
        await ingestion_worker.resolve_sdk_observation(Event(
            topic=Topic.SDK_EVENTS_VALIDATED, tenant_id=T,
            payload={"event_id": f"q-{i}", "event_type": "agent_tool_invocation_observed", "tenant_id": T,
                     "properties": {}, "context": {},
                     "validated_agent_deployment": {"deployment_id": dep["id"], "agent_id": "dup-agent"}}),
            _Producer())
    await _persist([_extra(1, "agent_tool_invocation_observed", "dup-agent", toolName="t", status="succeeded")])
    data = (await agent_routes.agent_behavior_read_model("dup-agent", _request()))["data"]
    [review] = data["sections"]["identity"]["data"]["queued_reviews"]
    assert review["reason_codes"] == ["agent_ref_reported_by_multiple_deployments"]
    assert review["status"] == "open"


# --- WO-110: behavior sections through the agent360 projection provider -------------

def _projection(tenant=T, subject_kind="agent", subject_id="gsc-buyer", authorized=True, auth_tenant=None):
    from shared.intelligence_projections import ProjectionContext, ProjectionRequest, ProjectionSubject
    from shared.intelligence_projections.contracts import ProjectionReadAuthorization

    subject = ProjectionSubject(kind=subject_kind, id=subject_id)
    req = ProjectionRequest(projectionId="agent360", tenantId=tenant, subject=subject)
    auths = [ProjectionReadAuthorization(
        tenantId=auth_tenant or tenant, sourceSurfaceId="agent360", sourceSubject=subject,
        sourceSlotId="behavior", consumerProjectionId="agent360", targetProjectionId="agent360",
        capabilityKey="agent_behavior", policyState="allowed")] if authorized else []
    ctx = ProjectionContext(projectionId="agent360", tenantId=tenant, registryState="in_flight",
                            dependencyState=[], warnings=[], experience360ReadAuthorizations=auths)
    return req, ctx


class _BehaviorOnlySource:
    """Every core Agent360 read fails closed; only the behavior seam answers."""

    def __init__(self, model=None, fail=False):
        self.model, self.fail = model, fail

    def __getattr__(self, name):
        async def _unavailable(*a, **k):
            raise RuntimeError("core source not under test")
        return _unavailable

    async def behavior_read_model(self, tenant_id, agent_id):
        from actions.agent.agent360_provider import Agent360ReadBatch

        if self.fail:
            raise RuntimeError("diagnostic must not leak")
        return Agent360ReadBatch(rows=[self.model] if self.model else [])


def test_agent360_registry_declares_behavior_sections():
    from actions.agent.agent360_provider import BEHAVIOR_SECTIONS, OUTPUT_SECTIONS
    from shared.intelligence_projections.generated_registry import INTELLIGENCE_PROJECTION_DEFINITIONS

    declared = INTELLIGENCE_PROJECTION_DEFINITIONS["agent360"]["outputSections"]
    assert set(declared) == set(OUTPUT_SECTIONS)
    assert set(BEHAVIOR_SECTIONS) <= set(declared)


@pytest.mark.asyncio
async def test_agent360_provider_serves_the_route_read_model(_routes):
    from actions.agent.agent360_provider import Agent360Provider, BEHAVIOR_SECTIONS, RepositoryAgent360Source

    await _persist(_events("GS-C"))
    route = (await agent_routes.agent_behavior_read_model("gsc-buyer", _request()))["data"]
    result = await Agent360Provider(RepositoryAgent360Source()).project(*_projection())
    by_id = {s.id: s for s in result.sections}
    for section_id, key in BEHAVIOR_SECTIONS.items():
        assert by_id[section_id].content["data"] == route["sections"][key]["data"], section_id
        assert by_id[section_id].content["binding"]["agentRefBasis"] == "source_reported"
    assert by_id["behavior_decisions"].state == "available"
    assert by_id["behavior_value"].state == "empty"  # no value-moving action observed
    [claim] = [c for c in result.claims if c.kind == "agent_behavior_decision"]
    assert claim.claimState.value == "derived" and claim.domainSlotIds is None
    gs_c = next(s for s in FIXTURE["scenarios"] if s["id"] == "GS-C")
    assert {r.id for r in claim.evidenceRefs} <= {e["id"] for e in gs_c["events"]}

    other = await Agent360Provider(RepositoryAgent360Source()).project(*_projection(tenant="other-tenant"))
    other_by_id = {s.id: s for s in other.sections}
    assert other_by_id["behavior"].state == "empty"
    assert other_by_id["behavior_decisions"].content["data"] == []


@pytest.mark.asyncio
async def test_agent360_behavior_sections_degrade_honestly(_routes):
    from actions.agent.agent360_provider import Agent360Provider, BEHAVIOR_SECTIONS

    facts = _facts(_events("GS-C"))
    capped_model = agent360_behavior(facts, "gsc-buyer", truncated=True)

    failed = await Agent360Provider(_BehaviorOnlySource(fail=True)).project(*_projection())
    assert {s.state for s in failed.sections if s.id in BEHAVIOR_SECTIONS} == {"degraded"}
    assert "agent_behavior_source_unavailable" in failed.degradedReasons
    assert "diagnostic must not leak" not in str([s.model_dump() for s in failed.sections])

    capped = await Agent360Provider(_BehaviorOnlySource(capped_model)).project(*_projection())
    by_id = {s.id: s for s in capped.sections}
    assert by_id["behavior"].state == "degraded"
    assert by_id["behavior_value"].state == "unknown"  # absence in a capped read is not proof
    assert "agent_behavior_source_truncated" in capped.degradedReasons

    wrong = await Agent360Provider(_BehaviorOnlySource(agent360_behavior(facts, "someone"))).project(
        *_projection())
    assert {s.state for s in wrong.sections if s.id in BEHAVIOR_SECTIONS} == {"degraded"}

    req, ctx = _projection()
    windowed_req = type(req).model_validate({
        **req.model_dump(by_alias=True, exclude_none=True),
        "timeRange": {"from": "2026-10-01T00:00:00Z", "to": "2026-10-02T00:00:00Z"}})
    windowed = await Agent360Provider(_BehaviorOnlySource(capped_model)).project(windowed_req, ctx)
    assert {s.state for s in windowed.sections if s.id in BEHAVIOR_SECTIONS} == {"unknown"}


@pytest.mark.asyncio
async def test_agent360_behavior_sections_fail_closed_without_gate_parity(_routes, monkeypatch):
    """The projection path must not bypass the route's registry flag or agent:manage."""
    from actions.agent.agent360_provider import BEHAVIOR_SECTIONS, Agent360Provider

    source = _BehaviorOnlySource()
    for kwargs in ({"authorized": False}, {"auth_tenant": "other-tenant"}):
        res = await Agent360Provider(source).project(*_projection(**kwargs))
        states = {sec.state for sec in res.sections if sec.id in BEHAVIOR_SECTIONS}
        assert states == {"suppressed"}, kwargs
        assert "agent_behavior_not_authorized" in res.degradedReasons
    monkeypatch.setattr(agent_routes.settings, "external_agent_telemetry",
                        dataclasses.replace(agent_routes.settings.external_agent_telemetry,
                                            enabled=False, registry_enabled=False))
    res = await Agent360Provider(source).project(*_projection())
    assert {sec.state for sec in res.sections if sec.id in BEHAVIOR_SECTIONS} == {"not_applicable"}
