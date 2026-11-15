"""A redeemed cross-device handoff continues ONE journey across both devices.

Before this, an anonymous journey loaded only its own anonymous ID's activity,
so the desktop visitor who redeemed a mobile handoff started a separate journey
and the explicit_handoff evidence never appeared. These tests compile real
journeys from the in-memory canonical activity ledger.
"""
from __future__ import annotations

import pytest

from journeys.handoff import continuation_jobs
from journeys.handoff.continuation_scope import resolve_continuation_scope
from journeys.handoff.service import issue_handoff, redeem_handoff
from journeys.measurement.engine.journey_compiler import JourneyCompiler
from journeys.measurement.repositories import activity_repo, conversion_repo, journey_repo, journey_step_repo
from journeys.measurement.repositories.activity_repo import ActivityRepository
from journeys.measurement.repositories.journey_repo import JourneyRepository
from journeys.measurement.repositories.journey_step_repo import JourneyStepRepository
from repositories import journey_handoff_repo

pytestmark = pytest.mark.asyncio
T = "tenant-cont"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    async def no_pool(*_a, **_k):
        return None

    monkeypatch.setattr(journey_handoff_repo, "get_pool", no_pool)
    for store in (activity_repo._local_store, journey_repo._local_store,
                  journey_step_repo._local_store, conversion_repo._local_store):
        store.clear()
    journey_handoff_repo.reset_journey_handoff_memory()
    yield
    for store in (activity_repo._local_store, journey_repo._local_store,
                  journey_step_repo._local_store, conversion_repo._local_store):
        store.clear()
    journey_handoff_repo.reset_journey_handoff_memory()


async def _activity(i, *, anon, session, platform, device, profile=None, tenant=T, minute=None):
    await ActivityRepository().upsert({
        "activity_id": f"{tenant}-a{i}", "tenant_id": tenant, "idempotency_key": f"k{i}",
        "anonymous_id": anon, "profile_id": profile, "session_id": session,
        "platform": platform, "device_id": device, "activity_family": "web2",
        "activity_type": "page_view", "actor_type": "human", "activity_status": "observed",
        "occurred_at": f"2026-11-14T10:{(minute if minute is not None else i):02d}:00+00:00",
    })


async def _handoff(src_anon, src_session, dst_anon, dst_session, tenant=T):
    issued = await issue_handoff(
        tenant_id=tenant, app_namespace="app", journey_id="client-j", session_id=src_session,
        anonymous_id=src_anon, platform="ios",
    )
    link, reason = await redeem_handoff(
        tenant_id=tenant, app_namespace="app", token=issued["token"], session_id=dst_session,
        anonymous_id=dst_anon, platform="web",
    )
    assert link is not None, reason
    return link


async def _mobile_then_desktop():
    await _activity(0, anon="anon-m", session="mob-1", platform="mobile_ios", device="dev-m")
    await _activity(1, anon="anon-m", session="mob-1", platform="mobile_ios", device="dev-m")
    await _activity(2, anon="anon-w", session="web-1", platform="web", device="dev-w")
    await _activity(3, anon="anon-w", session="web-1", platform="web", device="dev-w")


async def _steps(version):
    return await JourneyStepRepository().list_by_version(T, version["journey_version_id"])


async def test_without_a_handoff_devices_stay_separate_journeys():
    await _mobile_then_desktop()
    mobile = await JourneyCompiler().compile_for_profile(T, "anon-m", identity_type="anonymous")
    desktop = await JourneyCompiler().compile_for_profile(T, "anon-w", identity_type="anonymous")
    assert mobile["step_count"] == 2 and desktop["step_count"] == 2
    assert mobile["journey_id"] != desktop["journey_id"]


async def test_redeemed_handoff_compiles_one_journey_with_explicit_hop():
    await _mobile_then_desktop()
    link = await _handoff("anon-m", "mob-1", "anon-w", "web-1")
    version = await JourneyCompiler().compile_for_profile(T, "anon-w", identity_type="anonymous")
    # Compiling the desktop end returns the continuation journey owned by the
    # mobile root, spanning both devices.
    assert version["profile_id"] == "anon-m"
    assert version["step_count"] == 4
    assert set(version["session_ids"]) == {"mob-1", "web-1"}
    steps = await _steps(version)
    hop = [s for s in steps if s["transition_evidence"]]
    assert len(hop) == 1
    assert hop[0]["transition_evidence"]["link_basis"] == "explicit_handoff"
    assert hop[0]["transition_evidence"]["handoff_id"] == link["handoff_id"]
    assert hop[0]["transition_evidence"]["identity_merge"] == "not_performed"


async def test_non_root_standalone_journey_is_retired_not_duplicated():
    await _mobile_then_desktop()
    compiler = JourneyCompiler()
    await compiler.compile_for_profile(T, "anon-w", identity_type="anonymous")
    await _handoff("anon-m", "mob-1", "anon-w", "web-1")
    await compiler.compile_for_profile(T, "anon-w", identity_type="anonymous")
    repo = JourneyRepository()
    assert await repo.find_current_for_profile(T, "anon-w", identity_type="anonymous") == []
    current = await repo.find_current_for_profile(T, "anon-m", identity_type="anonymous")
    assert len(current) == 1 and current[0]["step_count"] == 4


async def test_chained_handoffs_pick_the_first_device_as_root():
    await _mobile_then_desktop()
    await _activity(4, anon="anon-t", session="tab-1", platform="web", device="dev-t")
    await _handoff("anon-m", "mob-1", "anon-w", "web-1")
    await _handoff("anon-w", "web-1", "anon-t", "tab-1")
    scope = await resolve_continuation_scope(T, ["anon-t"])
    assert scope.root_anonymous_id == "anon-m"
    assert scope.anonymous_ids == ("anon-m", "anon-t", "anon-w")
    version = await JourneyCompiler().compile_for_profile(T, "anon-t", identity_type="anonymous")
    assert version["step_count"] == 5


async def test_scope_walk_is_bounded_and_reports_truncation():
    for i in range(5):
        await _handoff(f"anon-{i}", f"s-{i}", f"anon-{i + 1}", f"s-{i + 1}")
    scope = await resolve_continuation_scope(T, ["anon-0"], max_anonymous_ids=3)
    assert len(scope.anonymous_ids) == 3 and scope.truncated


async def test_other_tenants_handoffs_never_extend_a_journey():
    await _mobile_then_desktop()
    await _handoff("anon-m", "mob-1", "anon-w", "web-1", tenant="tenant-other")
    version = await JourneyCompiler().compile_for_profile(T, "anon-w", identity_type="anonymous")
    assert version["step_count"] == 2


async def test_profile_journey_pulls_handoff_linked_pre_login_activity():
    # Desktop logs in after the handoff: the profile journey continues the
    # mobile pre-login activity, but never another profile's activity.
    await _activity(0, anon="anon-m", session="mob-1", platform="mobile_ios", device="dev-m")
    await _activity(1, anon="anon-m", session="mob-1", platform="mobile_ios", device="dev-m",
                    profile="someone-else")
    await _activity(2, anon="anon-w", session="web-1", platform="web", device="dev-w",
                    profile="user-1")
    await _handoff("anon-m", "mob-1", "anon-w", "web-1")
    version = await JourneyCompiler().compile_for_profile(T, "user-1", identity_type="profile")
    assert version["step_count"] == 2
    ids = {s["activity_id"] for s in await _steps(version)}
    assert ids == {f"{T}-a0", f"{T}-a2"}


async def test_continuation_job_rebuilds_anonymous_and_profile_journeys():
    await _mobile_then_desktop()
    await _activity(5, anon="anon-w", session="web-1", platform="web", device="dev-w",
                    profile="user-1", minute=5)
    link = await _handoff("anon-m", "mob-1", "anon-w", "web-1")
    result = await continuation_jobs.run_handoff_continuation(T, {
        "handoff_id": link["handoff_id"], "source_anonymous_id": "anon-m",
        "redeemed_anonymous_id": "anon-w",
    })
    assert result["step_count"] == 5
    assert result["profile_journeys_rebuilt"] == 1
    profile = await JourneyRepository().find_current_for_profile(T, "user-1", identity_type="profile")
    assert profile and profile[0]["rebuild_reason"] == f"handoff_redeemed:{link['handoff_id']}"


async def test_enqueue_is_idempotent_per_handoff_and_fail_soft():
    calls = []

    class Jobs:
        async def enqueue(self, tenant_id, job_type, payload, **kw):
            calls.append((tenant_id, job_type, payload, kw["idempotency_key"]))
            return {"id": "job-1"}

    link = {"handoff_id": "h1", "from": {"anonymous_id": "a"}, "to": {"anonymous_id": "b"}}
    assert await continuation_jobs.queue_handoff_continuation(T, link, jobs=Jobs())
    assert calls == [(T, continuation_jobs.JOB_TYPE,
                      {"handoff_id": "h1", "source_anonymous_id": "a", "redeemed_anonymous_id": "b"},
                      "journey_handoff:h1")]

    class Down:
        async def enqueue(self, *a, **k):
            raise RuntimeError("jobs plane down")

    assert await continuation_jobs.queue_handoff_continuation(T, link, jobs=Down()) is False


async def test_handler_is_registered_internal_only():
    from workers.jobs.bootstrap import register_durable_job_handlers
    from workers.jobs.handlers import HANDLER_REGISTRY, TENANT_INVOCABLE

    register_durable_job_handlers()
    assert continuation_jobs.JOB_TYPE in HANDLER_REGISTRY
    assert continuation_jobs.JOB_TYPE not in TENANT_INVOCABLE


async def test_joining_two_continuations_retires_every_former_root():
    # A->B and C->D are compiled separately; then B->D joins them. Only the
    # oldest root (A) may stay current, so C must be retired too.
    compiler = JourneyCompiler()
    await _activity(0, anon="A", session="sA", platform="mobile_ios", device="dA")
    await _activity(1, anon="B", session="sB", platform="web", device="dB")
    await _activity(2, anon="C", session="sC", platform="mobile_ios", device="dC")
    await _activity(3, anon="D", session="sD", platform="web", device="dD")
    await _handoff("A", "sA", "B", "sB")
    await _handoff("C", "sC", "D", "sD")
    await compiler.compile_for_profile(T, "B", identity_type="anonymous")
    await compiler.compile_for_profile(T, "D", identity_type="anonymous")
    repo = JourneyRepository()
    assert len(await repo.find_current_for_profile(T, "C", identity_type="anonymous")) == 1
    await _handoff("B", "sB", "D", "sD")
    version = await compiler.compile_for_profile(T, "D", identity_type="anonymous")
    assert version["profile_id"] == "A" and version["step_count"] == 4
    for member in ("B", "C", "D"):
        assert await repo.find_current_for_profile(T, member, identity_type="anonymous") == []
    assert len(await repo.find_current_for_profile(T, "A", identity_type="anonymous")) == 1


async def test_profile_journey_keeps_seed_devices_pre_login_activity():
    # The mobile acquisition (unowned) must stay in the profile journey after
    # the mobile device also logs in, which makes it a seed of the profile.
    await _activity(0, anon="anon-m", session="mob-1", platform="mobile_ios", device="dev-m")
    await _activity(1, anon="anon-w", session="web-1", platform="web", device="dev-w", profile="user-1")
    await _handoff("anon-m", "mob-1", "anon-w", "web-1")
    first = await JourneyCompiler().compile_for_profile(T, "user-1", identity_type="profile")
    assert first["step_count"] == 2
    await _activity(2, anon="anon-m", session="mob-1", platform="mobile_ios", device="dev-m", profile="user-1")
    again = await JourneyCompiler().compile_for_profile(T, "user-1", identity_type="profile")
    ids = {s["activity_id"] for s in await _steps(again)}
    assert ids == {f"{T}-a0", f"{T}-a1", f"{T}-a2"}
