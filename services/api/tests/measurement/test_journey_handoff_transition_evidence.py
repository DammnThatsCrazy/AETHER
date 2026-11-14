"""Compiled journey steps say HOW a cross-device hop was linked: handoff vs inference."""
from __future__ import annotations

import pytest

from journeys.handoff.service import issue_handoff, redeem_handoff
from journeys.measurement.engine.journey_compiler import (
    _classify_transitions, _explicit_handoff_links, _transition_evidence,
)
from repositories import journey_handoff_repo

pytestmark = pytest.mark.asyncio
T = "tenant-te"


@pytest.fixture(autouse=True)
def _clean():
    journey_handoff_repo.reset_journey_handoff_memory()
    yield
    journey_handoff_repo.reset_journey_handoff_memory()


def _act(i, session, platform, device):
    return {
        "activity_id": f"a{i}", "activity_family": "web2", "actor_type": "human",
        "occurred_at": f"2026-10-22T10:0{i}:00Z", "session_id": session,
        "platform": platform, "device_id": device,
    }


ACTS = [
    _act(0, "mob-1", "mobile_ios", "dev-m"),
    _act(1, "mob-1", "mobile_ios", "dev-m"),
    _act(2, "web-1", "web", "dev-w"),
]


async def _redeem(src="mob-1", dst="web-1"):
    issued = await issue_handoff(
        tenant_id=T, app_namespace="app", journey_id="j", session_id=src,
        anonymous_id="anon-m", platform="ios",
    )
    link, _ = await redeem_handoff(
        tenant_id=T, app_namespace="app", token=issued["token"], session_id=dst,
        anonymous_id="anon-w", platform="web",
    )
    return link


async def test_redeemed_handoff_marks_the_hop_explicit():
    link = await _redeem()
    transitions = _classify_transitions(ACTS, 1800)
    assert transitions[2] == "mobile_to_web"
    evidence = _transition_evidence(ACTS, transitions, await _explicit_handoff_links(T, ACTS))
    assert evidence[0] == {} and evidence[1] == {}
    assert evidence[2]["link_basis"] == "explicit_handoff"
    assert evidence[2]["handoff_id"] == link["handoff_id"]
    assert evidence[2]["identity_merge"] == "not_performed"


async def test_without_a_handoff_the_hop_is_labelled_inferred():
    transitions = _classify_transitions(ACTS, 1800)
    evidence = _transition_evidence(ACTS, transitions, await _explicit_handoff_links(T, ACTS))
    assert evidence[2]["link_basis"] == "inferred"


async def test_other_tenants_handoff_and_unredeemed_tokens_do_not_count():
    await _redeem()
    other = await _explicit_handoff_links("tenant-other", ACTS)
    assert other == {}
    journey_handoff_repo.reset_journey_handoff_memory()
    await issue_handoff(
        tenant_id=T, app_namespace="app", journey_id="j", session_id="mob-1",
        anonymous_id="anon-m", platform="ios",
    )
    assert await _explicit_handoff_links(T, ACTS) == {}


async def test_reverse_direction_is_not_credited_as_the_handoff():
    await _redeem(src="web-1", dst="mob-1")  # a handoff the other way
    transitions = _classify_transitions(ACTS, 1800)
    evidence = _transition_evidence(ACTS, transitions, await _explicit_handoff_links(T, ACTS))
    assert evidence[2]["link_basis"] == "inferred"


async def test_lookup_failure_keeps_hops_inferred(monkeypatch):
    async def boom(self, *a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr(
        journey_handoff_repo.JourneyHandoffRepository, "redeemed_for_sessions", boom
    )
    assert await _explicit_handoff_links(T, ACTS) == {}
