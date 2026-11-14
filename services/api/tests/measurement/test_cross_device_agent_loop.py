"""Cross-device certification scenario (XD-1), end to end in one process.

A person taps an Apple Ads ad, installs the iOS app and browses anonymously,
drops, continues on a desktop browser through a journey handoff, logs in, and
then delegates work to agents. The test drives the real routes, compiler,
repositories and the continuation job; only Apple's API, consent, the jobs
queue and the agents' Silver fact store are faked.

What it certifies (code-level; real devices and a partner tenant are a separate
certification, see docs/operations/runbooks/cross-device-certification.md):
  1. The ad click is recorded server-side as platform-verified evidence on the
     mobile anonymous ID; the client never asserts it.
  2. Redeeming the handoff queues one continuation rebuild, and the rebuilt
     journey spans both devices with the hop labelled explicit_handoff.
  3. After login the PROFILE journey still starts at the ad acquisition and
     includes the pre-login mobile steps, without merging any identity.
  4. Profile 360 for that person lists the agents acting for them.
  5. Negative controls: a replayed Apple token, another tenant's handoff, and a
     second redemption of the same token change nothing.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import httpx
import pytest

from journeys.handoff import continuation_jobs
from journeys.handoff import routes as handoff_routes
from journeys.measurement.engine.journey_compiler import JourneyCompiler
from journeys.measurement.repositories import (
    activity_repo, conversion_repo, journey_repo, journey_step_repo, touchpoint_repo,
)
from journeys.measurement.repositories.activity_repo import ActivityRepository
from journeys.measurement.repositories.journey_repo import JourneyRepository
from journeys.measurement.repositories.journey_step_repo import JourneyStepRepository
from journeys.traffic import apple_ads_attribution as apple_ads
from repositories import journey_handoff_repo

pytestmark = pytest.mark.asyncio
T, APP = "tenant-xd", "shop-app"
STORES = (activity_repo._local_store, journey_repo._local_store, journey_step_repo._local_store,
          conversion_repo._local_store, touchpoint_repo._local_store)


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    async def no_pool(*_a, **_k):
        return None

    monkeypatch.setattr(journey_handoff_repo, "get_pool", no_pool)
    for cls in (activity_repo.ActivityRepository, touchpoint_repo.TouchpointRepository):
        monkeypatch.setattr(cls, "_pool", no_pool)
    settings = handoff_routes.settings
    monkeypatch.setattr(settings, "identity_continuity", dataclasses.replace(
        settings.identity_continuity, journey_handoff_enabled=True))
    monkeypatch.setattr(settings, "mobile", dataclasses.replace(
        settings.mobile, apple_ads_attribution_enabled=True))

    from governance.consent import authority

    async def consent(tenant_id, anonymous_id):
        return True, "", {}

    monkeypatch.setattr(authority, "evaluate_identity_link_consent", consent)

    def apple(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "attribution": True, "orgId": 1, "campaignId": 777, "adGroupId": 8,
            "keywordId": 9, "adId": 10, "conversionType": "Download", "claimType": "Click",
            "clickDate": "2026-11-14T09:58:00Z",
        })

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: real(transport=httpx.MockTransport(apple)))
    for store in STORES:
        store.clear()
    journey_handoff_repo.reset_journey_handoff_memory()
    yield
    for store in STORES:
        store.clear()
    journey_handoff_repo.reset_journey_handoff_memory()


def _req(tenant=T):
    t = SimpleNamespace(tenant_id=tenant, site_ids=[APP], require_permission=lambda _: None)
    return SimpleNamespace(state=SimpleNamespace(tenant=t))


async def _event(i, *, anon, session, platform, device, minute, profile=None, tenant=T,
                 activity_type="screen_view"):
    await ActivityRepository().upsert({
        "activity_id": f"xd-{tenant}-{i}", "tenant_id": tenant, "idempotency_key": f"xd-{i}",
        "anonymous_id": anon, "profile_id": profile, "session_id": session,
        "platform": platform, "device_id": device, "activity_family": "web2",
        "activity_type": activity_type, "actor_type": "human", "activity_status": "observed",
        "occurred_at": f"2026-11-14T10:{minute:02d}:00+00:00",
    })


class QueueSpy:
    def __init__(self):
        self.jobs = []

    async def enqueue(self, tenant_id, job_type, payload, **kw):
        self.jobs.append((tenant_id, job_type, payload, kw["idempotency_key"]))
        return {"id": f"job-{len(self.jobs)}"}


@pytest.fixture
def queue(monkeypatch):
    spy = QueueSpy()
    real = continuation_jobs.queue_handoff_continuation

    async def queue_into_spy(tenant_id, link, **_kw):
        return await real(tenant_id, link, jobs=spy)

    monkeypatch.setattr(handoff_routes, "queue_handoff_continuation", queue_into_spy)
    return spy


async def _mobile_leg():
    # 1. Ad -> install: the SDK posts the AdServices token; the server verifies it.
    out = await apple_ads.resolve_apple_ads_attribution(apple_ads.AppleAdsResolve(
        token="adservices-token", anonymous_id="anon-phone", session_id="phone-s1"), _req())
    assert out["resolved"] and out["evidence"]["proof_level"] == "platform_verified"
    await _event(1, anon="anon-phone", session="phone-s1", platform="mobile_ios", device="iphone", minute=0)
    await _event(2, anon="anon-phone", session="phone-s1", platform="mobile_ios", device="iphone", minute=2,
                 activity_type="product_viewed")
    # 2. The user drops; before leaving, the app issues a handoff (QR / link).
    issued = (await handoff_routes.issue(handoff_routes.IssueRequest(
        journey_id="client-journey-1", session_id="phone-s1", anonymous_id="anon-phone", platform="ios",
    ), _req()))["data"]
    return issued


async def test_xd1_ad_to_mobile_to_desktop_to_login_to_agents(monkeypatch, queue):
    issued = await _mobile_leg()

    # 3. Later, on a desktop browser: a fresh anonymous visitor redeems it.
    await _event(3, anon="anon-desk", session="desk-s1", platform="web", device="macbook", minute=40)
    link = (await handoff_routes.redeem(handoff_routes.RedeemRequest(
        token=issued["token"], session_id="desk-s1", anonymous_id="anon-desk", platform="web",
    ), _req()))["data"]
    assert link["identity_merge"] == "not_performed"
    [(tenant, job_type, payload, key)] = queue.jobs
    assert (tenant, job_type, key) == (T, continuation_jobs.JOB_TYPE, f"journey_handoff:{link['handoff_id']}")

    # The worker runs the queued job.
    result = await continuation_jobs.run_handoff_continuation(T, payload)
    assert result["step_count"] == 4  # ad acquisition + 2 mobile + 1 desktop

    repo = JourneyRepository()
    assert await repo.find_current_for_profile(T, "anon-desk", identity_type="anonymous") == []
    [journey] = await repo.find_current_for_profile(T, "anon-phone", identity_type="anonymous")
    steps = await JourneyStepRepository().list_by_version(T, journey["journey_version_id"])
    assert steps[0]["activity_type"] == "app_install_attributed"
    hops = [s["transition_evidence"] for s in steps if s.get("transition_evidence")]
    assert [h["link_basis"] for h in hops] == ["explicit_handoff"]
    assert hops[0]["handoff_id"] == link["handoff_id"]

    # 4. The person logs in on the desktop.
    await _event(4, anon="anon-desk", session="desk-s1", platform="web", device="macbook", minute=45,
                 profile="person-1", activity_type="login")
    profile_journey = await JourneyCompiler().compile_for_profile(
        T, "person-1", identity_type="profile", trigger_reason="identity_change")
    profile_steps = await JourneyStepRepository().list_by_version(T, profile_journey["journey_version_id"])
    kinds = [s["activity_type"] for s in profile_steps]
    assert kinds[0] == "app_install_attributed"          # the journey still starts at the ad
    assert "product_viewed" in kinds and kinds[-1] == "login"
    assert set(profile_journey["session_ids"]) == {"phone-s1", "desk-s1"}
    # No identity was merged: the mobile rows still carry no profile.
    mobile_rows = await ActivityRepository().list_by_profile(T, "anon-phone", identity_type="anonymous")
    assert all(row.get("profile_id") is None for row in mobile_rows)

    # 5. The person delegates to an orchestrator; Profile 360 lists it.
    from actions.agent import behavior_read_model
    from intelligence.agent_behavior.facts import AgentFact

    class Grants:
        async def find_many(self, filters, limit):
            return [{"tenant_id": T, "grantor_entity_id": "person-1", "grantee_entity_id": "orchestrator-1"}]

    async def facts(tenant_id, ref):
        return [AgentFact(event_id="f1", event_type="agent.tool.called", tenant_id=T, agent_ref=ref,
                          occurred_at="2026-11-14T10:50:00Z", principal_id="person-1")], False

    monkeypatch.setattr(behavior_read_model, "load_behavior_facts", facts)
    agents = await behavior_read_model.build_principal_agents(T, "person-1", grants_repo=Grants())
    assert [a["agent_ref"] for a in agents["agents"]] == ["orchestrator-1"]
    assert agents["agents"][0]["link_basis"] == "recorded_grant"
    assert agents["identity_merge"] == "not_performed"


async def test_xd1_negative_controls(queue):
    issued = await _mobile_leg()
    # A replayed Apple token cannot attribute a second device.
    replay = await apple_ads.resolve_apple_ads_attribution(apple_ads.AppleAdsResolve(
        token="adservices-token", anonymous_id="anon-attacker"), _req())
    assert replay == {"resolved": False, "status": "token_already_bound"}

    # Another tenant cannot redeem the token.
    from shared.common.common import NotFoundError

    body = handoff_routes.RedeemRequest(token=issued["token"], session_id="desk-s1",
                                        anonymous_id="anon-desk", platform="web")
    with pytest.raises(NotFoundError):
        await handoff_routes.redeem(body, _req(tenant="tenant-other"))
    # A second redemption of a spent token is refused and queues nothing more.
    await handoff_routes.redeem(body, _req())
    with pytest.raises(NotFoundError):
        await handoff_routes.redeem(body, _req())
    assert len(queue.jobs) == 1

    # Without a handoff, an unrelated desktop visitor's journey stays its own.
    await _event(9, anon="anon-stranger", session="s9", platform="web", device="pc", minute=50)
    stranger = await JourneyCompiler().compile_for_profile(T, "anon-stranger", identity_type="anonymous")
    assert stranger["step_count"] == 1 and stranger["profile_id"] == "anon-stranger"
