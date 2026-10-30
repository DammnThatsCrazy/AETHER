"""Agent continuity review decisions: confirm / reject, never a merge (WO-013 follow-up)."""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

import actions.agent.deployment_routes as agent_routes
from identity.identity.pending_review import PendingIdentityReviewRepository
from ingestion.silver import writer as silver_writer
from repositories.repos import reset_in_memory_stores
from shared.common.common import BadRequestError, ConflictError, NotFoundError

T = "tenant-continuity"
AGENT = "dup-agent"


@pytest.fixture
def continuity(monkeypatch):
    from config.settings import settings

    reset_in_memory_stores()
    silver_writer.reset_local_tables()
    monkeypatch.setattr(agent_routes.settings, "external_agent_telemetry",
                        dataclasses.replace(agent_routes.settings.external_agent_telemetry,
                                            enabled=True, registry_enabled=True))
    monkeypatch.setattr(settings, "identity_continuity",
                        dataclasses.replace(settings.identity_continuity, resolution_enabled=True))
    yield
    reset_in_memory_stores()
    silver_writer.reset_local_tables()


def _request(tenant=T):
    t = SimpleNamespace(tenant_id=tenant, user_id="u", site_ids=[], require_permission=lambda _: None)
    return SimpleNamespace(state=SimpleNamespace(tenant=t))


async def _queue_review(agent=AGENT):
    from actions.agent.deployments import get_deployment_repository
    from identity.identity import ingestion_worker
    from shared.events.events import Event, Topic

    deps = [await get_deployment_repository().create(T, {
        "agent_id": agent, "display_name": "bot", "external_platform": platform,
        "environment": "production", "consent_mode": "tenant_managed"}, actor="t", request_id="r")
        for platform in ("web_widget", "slack_app")]

    class _Producer:
        async def publish(self, event):
            return None

    for i, dep in enumerate(deps):
        await ingestion_worker.resolve_sdk_observation(Event(
            topic=Topic.SDK_EVENTS_VALIDATED, tenant_id=T,
            payload={"event_id": f"{agent}-q-{i}", "event_type": "agent_tool_invocation_observed",
                     "tenant_id": T, "properties": {}, "context": {},
                     "validated_agent_deployment": {"deployment_id": dep["id"], "agent_id": agent}}),
            _Producer())
    [review] = await agent_routes._agent_continuity_reviews(T, agent)
    return review


async def _source_rows():
    from identity.identity.routes import get_identity_resolver

    rows = await get_identity_resolver()._repo.list_source_identities_by_identifier(
        T, "agent_id", AGENT, limit=20)
    return sorted((str(r.get("id")), r.get("canonical_entity_id"), r.get("status")) for r in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("route,decision", [
    ("confirm_agent_continuity", "confirmed"), ("reject_agent_continuity", "rejected")])
async def test_decision_is_recorded_and_never_merges(continuity, route, decision):
    review = await _queue_review()
    before = await _source_rows()
    assert len(before) == 2

    data = (await getattr(agent_routes, route)(AGENT, review["id"], _request()))["data"]
    assert data["status"] == decision
    assert data["merge_performed"] is False and data["authority"] == "none"
    assert data["decision"]["decided_by"] == "u"
    assert data["decision"]["merge_performed"] is False
    assert f"agent_continuity_{decision}" in data["reason_codes"]

    assert await _source_rows() == before  # nothing merged, bound or relinked
    assert await agent_routes._agent_continuity_reviews(T, AGENT) == []  # leaves the queue
    stored = await PendingIdentityReviewRepository().get(
        T, review["id"], entry_type="agent_continuity_candidate")
    assert stored["status"] == decision

    again = (await getattr(agent_routes, route)(AGENT, review["id"], _request()))["data"]
    assert again["status"] == decision and again["decision"] == data["decision"]


@pytest.mark.asyncio
async def test_opposite_decision_conflicts(continuity):
    review = await _queue_review()
    await agent_routes.confirm_agent_continuity(AGENT, review["id"], _request())
    with pytest.raises(ConflictError):
        await agent_routes.reject_agent_continuity(AGENT, review["id"], _request())


@pytest.mark.asyncio
async def test_other_tenant_other_agent_and_unknown_id_are_not_found(continuity):
    review = await _queue_review()
    for agent, rid, tenant in ((AGENT, review["id"], "other-tenant"),
                               ("someone-else", review["id"], T),
                               (AGENT, "nope", T)):
        with pytest.raises(NotFoundError):
            await agent_routes.confirm_agent_continuity(agent, rid, _request(tenant))


@pytest.mark.asyncio
async def test_repository_keeps_kinds_apart_and_is_compare_and_set(continuity):
    review = await _queue_review()
    repo = PendingIdentityReviewRepository()
    assert await repo.get(T, review["id"]) is None  # late-binding approve/merge cannot load it
    with pytest.raises(ValueError):
        await repo.decide_agent_continuity(tenant_id=T, record_id=review["id"],
                                           decision="merged", decided_by="u")
    assert await repo.decide_agent_continuity(tenant_id=T, record_id=review["id"],
                                              decision="confirmed", decided_by="u") is not None
    assert await repo.decide_agent_continuity(tenant_id=T, record_id=review["id"],
                                              decision="rejected", decided_by="u") is None


@pytest.mark.asyncio
async def test_requires_registry(continuity, monkeypatch):
    review = await _queue_review()
    monkeypatch.setattr(agent_routes.settings, "external_agent_telemetry",
                        dataclasses.replace(agent_routes.settings.external_agent_telemetry,
                                            enabled=False, registry_enabled=False))
    with pytest.raises(BadRequestError):
        await agent_routes.confirm_agent_continuity(AGENT, review["id"], _request())


@pytest.mark.asyncio
async def test_requires_agent_manage(continuity):
    from shared.common.common import ForbiddenError

    review = await _queue_review()

    def _deny(perm):
        raise ForbiddenError(f"Missing permission: {perm}")

    request = _request()
    request.state.tenant.require_permission = _deny
    with pytest.raises(ForbiddenError):
        await agent_routes.confirm_agent_continuity(AGENT, review["id"], request)
    stored = await PendingIdentityReviewRepository().get(
        T, review["id"], entry_type="agent_continuity_candidate")
    assert stored["status"] == "open"
