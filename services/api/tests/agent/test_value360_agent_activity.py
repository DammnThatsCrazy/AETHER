"""Value 360 agent_mediated_activity section (WO-092)."""
from __future__ import annotations

import pytest

from ingestion.silver import writer as silver_writer
from ingestion.silver.projectors.agent_execution_projector import AgentExecutionProjector
from repositories.repos import reset_in_memory_stores
from shared.intelligence_projections import ProjectionContext, ProjectionRequest, ProjectionSubject
from value.economic.economic360_provider import Economic360Provider

T = "tenant-v360"


class _Sources:
    async def records(self, *, tenant_id, subject):
        return []


class _CanonicalAgent:
    async def is_canonical_agent(self, tenant_id, agent_id):
        return True


def _req(kind, id_):
    subject = ProjectionSubject(kind=kind, id=id_)
    return (ProjectionRequest(projectionId="economic360", tenantId=T, subject=subject),
            ProjectionContext(projectionId="economic360", tenantId=T, registryState="in_flight",
                              dependencyState=[], warnings=[]))


def _section(result):
    return next(s for s in result.sections if s.id == "agent_mediated_activity")


@pytest.fixture(autouse=True)
def _clean():
    reset_in_memory_stores()
    silver_writer.reset_local_tables()
    yield
    reset_in_memory_stores()
    silver_writer.reset_local_tables()


async def _persist(agent, deployment, events):
    for i, (etype, props) in enumerate(events):
        r = AgentExecutionProjector().project({
            "messageId": f"{agent}-{deployment}-{i}", "type": etype, "tenantId": T,
            "timestamp": f"2026-10-22T10:00:{i:02d}Z",
            "validated_agent_deployment": {"deployment_id": deployment, "agent_id": agent},
            "properties": {"agentId": agent, **props}})
        await silver_writer.SilverFactWriter()._persist_generic(r.table, r.rows)


@pytest.mark.asyncio
async def test_non_agent_subjects_are_not_applicable():
    req, _ = _req("entity", "person-1")
    sec = await Economic360Provider(_Sources())._agent_mediated_activity_section(req)
    assert sec.state == "not_applicable"


@pytest.mark.asyncio
async def test_unbound_canonical_agent_is_unknown_not_empty():
    provider = Economic360Provider(_Sources(), agent_identity_reader=_CanonicalAgent())
    sec = _section(await provider.project(*_req("agent", "ent-agent-1")))
    assert sec.state == "unknown" and sec.content["reason"] == "no_active_identity_binding"
    assert sec.content["executionByAether"] is False


@pytest.mark.asyncio
async def test_bound_agent_attributes_reported_amounts_per_currency():
    from actions.agent_marketplace.identity_binding import AgentDeploymentIdentityBindingRepository

    await AgentDeploymentIdentityBindingRepository().bind(
        tenant_id=T, source_namespace="vendor.runtime", source_agent_ref="buyer",
        canonical_agent_entity_id="ent-agent-1", bound_by="admin", source_deployment_id="dep-1")
    await _persist("buyer", "dep-1", [
        ("agent_action_selected", {"decisionId": "d1", "candidateId": "sku"}),
        ("agent_transaction_initiated", {"decisionId": "d1", "amount": "40.00", "currency": "USD"}),
        ("agent_transaction_initiated", {"decisionId": "d1", "amount": "5", "currency": "EUR"}),
    ])
    await _persist("buyer", "other-dep", [  # same ref under another deployment: not this binding
        ("agent_transaction_initiated", {"amount": "999", "currency": "USD"})])
    provider = Economic360Provider(_Sources(), agent_identity_reader=_CanonicalAgent())
    sec = _section(await provider.project(*_req("agent", "ent-agent-1")))
    assert sec.state == "available"
    totals = {(t["currency"], t["finality"]): t["amount"] for t in sec.content["attribution"]["totals"]}
    assert totals == {("USD", "reported"): "40.00", ("EUR", "reported"): "5"}
    assert sec.content["binding"]["source_agent_refs"] == ["buyer"]


@pytest.mark.asyncio
async def test_reader_failure_degrades():
    class Boom:
        async def activity(self, *a):
            raise RuntimeError("diagnostic must not leak")

    provider = Economic360Provider(_Sources(), agent_identity_reader=_CanonicalAgent(),
                                   agent_activity_reader=Boom())
    sec = _section(await provider.project(*_req("agent", "ent-agent-1")))
    assert sec.state == "degraded" and "diagnostic" not in str(sec.content)
