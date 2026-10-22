"""End-to-end scenarios: nested agents and fleets, from raw SDK events to reviewed attribution.

Both scenarios push SDK-shaped events through the real Silver projector and writer,
then read them back through the lineage, handoff and fleet-hypothesis routes.
Only storage is local (in-memory); no reader is stubbed.

A: a person continues a mobile journey on web, dispatches an orchestrator, which
   spawns two sub-agents that call tools and return a result.
B: a Risk360-flagged actor's orchestrator spawns 15 sub-agents that scan and swap
   against shared wallets over one RPC endpoint. The fleet is attributed to the
   delegating principal only as a reviewable hypothesis with competing explanations.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from actions.agent.deployment_routes import agent_spawn_lineage
from config.settings import settings
from ingestion.silver import writer as silver_writer
from ingestion.silver.projectors.agent_execution_projector import AgentExecutionProjector
from intelligence.fraud_networks import fleet_routes
from journeys.handoff import routes as handoff_routes
from repositories import journey_handoff_repo
from repositories.repos import DelegationRepository, reset_in_memory_stores

T = "tenant-scn"
APP = "shop-app"
_seq = {"n": 0}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    reset_in_memory_stores()
    silver_writer.reset_local_tables()
    journey_handoff_repo.reset_journey_handoff_memory()
    _seq["n"] = 0
    monkeypatch.setattr(
        settings, "external_agent_telemetry",
        dataclasses.replace(settings.external_agent_telemetry, enabled=True, registry_enabled=True),
    )
    monkeypatch.setattr(
        settings, "identity_continuity",
        dataclasses.replace(settings.identity_continuity, journey_handoff_enabled=True),
    )
    monkeypatch.setattr(
        settings, "fraud_intelligence",
        dataclasses.replace(settings.fraud_intelligence, fraud_networks_enabled=True),
    )
    from governance.consent import authority

    async def allow(tenant_id, anonymous_id):
        return True, "", {}

    monkeypatch.setattr(authority, "evaluate_identity_link_consent", allow)
    yield
    reset_in_memory_stores()
    silver_writer.reset_local_tables()
    journey_handoff_repo.reset_journey_handoff_memory()


def _request(user="analyst-1"):
    tenant = SimpleNamespace(
        tenant_id=T, user_id=user, site_ids=[APP], require_permission=lambda _: None,
    )
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


async def _emit(event_type: str, agent: str, at: str, **props) -> None:
    _seq["n"] += 1
    result = AgentExecutionProjector().project({
        "messageId": f"evt-{_seq['n']:04d}",
        "type": event_type,
        "tenantId": T,
        "timestamp": at,
        "properties": {"agentId": agent, **props},
    })
    assert result is not None
    await silver_writer.SilverFactWriter()._persist_generic(result.table, result.rows)


def _walk(node):
    yield node
    for child in node["children"]:
        yield from _walk(child)


@pytest.mark.asyncio
async def test_scenario_a_mobile_to_web_orchestrator_with_two_subagents():
    # 1. Mobile journey, then continued on web through an explicit handoff.
    issued = (await handoff_routes.issue(
        handoff_routes.IssueRequest(
            journey_id="jrn-checkout", session_id="mob-1", anonymous_id="anon-mob", platform="ios",
        ), _request(),
    ))["data"]
    link = (await handoff_routes.redeem(
        handoff_routes.RedeemRequest(
            token=issued["token"], session_id="web-1", anonymous_id="anon-web", platform="web",
        ), _request(),
    ))["data"]
    assert link["link_basis"] == "explicit_handoff" and link["identity_merge"] == "not_performed"

    # 2. On web the user dispatches an orchestrator that spawns two sub-agents.
    await _emit("agent_task_started", "orch", "2026-10-22T10:00:00Z",
                runId="run-1", taskId="task-trip")
    for i, child in enumerate(("flights", "hotels"), start=1):
        await _emit("agent_subagent_spawned", "orch", f"2026-10-22T10:00:0{i}Z",
                    parentAgentId="orch", childAgentId=child, rootAgentId="orch",
                    runId="run-1", taskId="task-trip")
        await _emit("agent_tool_invocation_observed", child, f"2026-10-22T10:00:1{i}Z",
                    runId=f"run-{child}", toolName=f"{child}_search", taskId=f"t-{child}")
        await _emit("agent_task_completed", child, f"2026-10-22T10:00:2{i}Z",
                    runId=f"run-{child}", taskId=f"t-{child}", outcome="completed")
    await _emit("agent_task_completed", "orch", "2026-10-22T10:00:30Z",
                runId="run-1", taskId="task-trip", outcome="completed")

    # 3. Lineage shows orchestrator -> 2 sub-agents with their tools and outcomes.
    lineage = (await agent_spawn_lineage("orch", _request(), max_depth=8))["data"]
    assert lineage["source_status"] == "available"
    assert lineage["totals"]["agent_count"] == 3 and lineage["totals"]["max_depth"] == 1
    assert lineage["totals"]["tool_call_count"] == 2
    kids = {n["agent_ref"]: n for n in lineage["tree"]["children"]}
    assert set(kids) == {"flights", "hotels"}
    assert kids["flights"]["activity"]["tools"] == [{"tool_name": "flights_search", "calls": 1}]
    assert kids["hotels"]["activity"]["outcomes"] == {"completed": 1}
    assert lineage["attribution"] == "none"

    # 4. The mobile -> web hop is listed against the same journey.
    handoffs = (await handoff_routes.journey_handoffs("jrn-checkout", _request()))["data"]
    assert handoffs["count"] == 1 and handoffs["items"][0]["link_basis"] == "explicit_handoff"

    # 5. A user's own small fleet is context, not a review item.
    await DelegationRepository().grant(
        delegation_id="del-user", tenant_id=T, grantor_entity_id="person-1",
        grantee_entity_id="orch", scope={"type": "task"},
    )
    built = (await fleet_routes.build(
        fleet_routes.BuildRequest(tenant_id=T, root_agent_ref="orch"), _request(),
    ))["data"]
    assert built["member_count"] == 3
    assert built["status"] == "unconfirmed" and built["priority"] == "low"
    assert built["person_link"]["principal_entity_ids"] == ["person-1"]


@pytest.mark.asyncio
async def test_scenario_b_flagged_actor_fleet_is_a_reviewable_hypothesis():
    from repositories.agentic_observability_repos import AgentRiskSignalRepository

    n_workers = 15
    workers = [f"scan-{i:02d}" for i in range(n_workers)]
    await DelegationRepository().grant(
        delegation_id="del-ops", tenant_id=T, grantor_entity_id="person-9",
        grantee_entity_id="swarm-root", scope={"type": "task"},
    )
    for i, worker in enumerate(workers):
        at = f"2026-10-22T11:00:{i:02d}Z"
        await _emit("agent_subagent_spawned", "swarm-root", at, parentAgentId="swarm-root",
                    childAgentId=worker, rootAgentId="swarm-root", runId="run-swarm")
        for step, tool in enumerate(("wallet_scan", "swap_quote")):
            await _emit("agent_tool_invocation_observed", worker, f"2026-10-22T11:05:{i:02d}.{step}Z",
                        runId=f"run-{worker}", toolName=tool,
                        serverUrl="https://rpc.shared.example/v1",
                        objectType="wallet", objectId="0xdeadbeef")
    # Risk360 flags one worker.
    await AgentRiskSignalRepository().insert("risk-1", {
        "tenant_id": T, "agent_id": workers[3], "signal": "wash_swap_pattern",
    })

    lineage = (await agent_spawn_lineage("swarm-root", _request(), max_depth=8))["data"]
    assert lineage["totals"]["agent_count"] == n_workers + 1
    assert lineage["totals"]["tool_call_count"] == n_workers * 2
    assert lineage["truncated"] == []

    hyp = (await fleet_routes.build(
        fleet_routes.BuildRequest(tenant_id=T, root_agent_ref="swarm-root"), _request(),
    ))["data"]
    kinds = {e["type"] for e in hyp["evidence"]}
    assert {"observed_spawn_tree", "spawn_burst", "shared_endpoint",
            "identical_tool_sequence", "overlapping_targets",
            "canonical_principal_delegation"} <= kinds
    assert hyp["member_count"] == n_workers + 1
    assert hyp["status"] == "needs_review" and hyp["priority"] == "high"
    assert hyp["risk_context"]["flagged_agent_refs"] == [workers[3]]
    assert hyp["person_link"]["claim"] == "authority_granted"
    assert hyp["confidence"] <= 0.9
    ids = {c["id"] for c in hyp["competing_explanations"]}
    assert {"shared_third_party_infrastructure", "same_vendor_template",
            "principal_is_not_the_actor"} <= ids
    assert hyp["status"] != "confirmed_by_reviewer", "the builder must never confirm"

    # Every inference points back at observed events.
    spawn_evidence = next(e for e in hyp["evidence"] if e["type"] == "observed_spawn_tree")
    assert spawn_evidence["source_event_refs"] and all(
        r.startswith("evt-") for r in spawn_evidence["source_event_refs"]
    )

    # A human decides; the decision is recorded without altering the evidence.
    reviewed = (await fleet_routes.review(
        hyp["hypothesis_id"],
        fleet_routes.ReviewRequest(
            tenant_id=T, decision="confirm", reason="delegation and swap targets match the case",
        ),
        _request("analyst-7"),
    ))["data"]
    assert reviewed["status"] == "confirmed_by_reviewer"
    assert reviewed["review_history"][0]["reviewer_id"] == "analyst-7"
    assert reviewed["evidence"] == hyp["evidence"] and reviewed["confidence"] == hyp["confidence"]

    # Rebuilding later must not undo the review.
    again = (await fleet_routes.build(
        fleet_routes.BuildRequest(tenant_id=T, root_agent_ref="swarm-root"), _request(),
    ))["data"]
    assert again["status"] == "confirmed_by_reviewer"
    assert len(again["review_history"]) == 1


@pytest.mark.asyncio
async def test_scenario_b_without_a_principal_cannot_be_confirmed():
    from shared.common.common import BadRequestError

    for i in range(6):
        await _emit("agent_subagent_spawned", "free-root", f"2026-10-22T12:00:{i:02d}Z",
                    parentAgentId="free-root", childAgentId=f"w{i}", rootAgentId="free-root")
    hyp = (await fleet_routes.build(
        fleet_routes.BuildRequest(tenant_id=T, root_agent_ref="free-root"), _request(),
    ))["data"]
    assert hyp["person_link"] is None
    with pytest.raises(BadRequestError):
        await fleet_routes.review(
            hyp["hypothesis_id"],
            fleet_routes.ReviewRequest(tenant_id=T, decision="confirm", reason="gut feeling about this one"),
            _request(),
        )
