"""Missing actor evidence stays ``unknown`` and is never promoted to ``human``.

An identity (profile id, anonymous id) says whose record an event belongs to,
not that a human performed it. See docs/architecture/AGENT-DETECTION-RELIABILITY.md.
"""

from __future__ import annotations

from journeys.measurement.engine.attribution_engine import _touchpoint_to_resolver_dict
from journeys.measurement.engine.journey_compiler import _classify_pair
from journeys.measurement.contracts import TransitionType


def _actor(tp: dict) -> str:
    return _touchpoint_to_resolver_dict(tp)["properties"]["actor_type"]


def test_identity_without_actor_evidence_is_unknown() -> None:
    assert _actor({"anonymous_id": "anon_1"}) == "unknown"
    assert _actor({"profile_id": "p_1"}) == "unknown"
    assert _actor({}) == "unknown"


def test_agent_id_and_explicit_actor_are_kept() -> None:
    assert _actor({"anonymous_id": "anon_1", "agent_id": "agt_1"}) == "agent"
    assert _actor({"anonymous_id": "anon_1", "actor_type": "human"}) == "human"


def test_unknown_to_agent_is_not_a_human_handoff() -> None:
    prev = {"activity_family": "web2"}
    curr = {"activity_family": "web2", "actor_type": "agent", "agent_id": "agt_1"}
    assert _classify_pair(prev, curr, 1800) != TransitionType.human_to_agent.value


def test_declared_human_to_agent_is_still_a_handoff() -> None:
    prev = {"activity_family": "web2", "actor_type": "human"}
    curr = {"activity_family": "web2", "actor_type": "agent", "agent_id": "agt_1"}
    assert _classify_pair(prev, curr, 1800) == TransitionType.human_to_agent.value


import pytest  # noqa: E402

from journeys.measurement import silver_adapters as sa  # noqa: E402


@pytest.mark.parametrize(
    "adapter",
    [
        sa.adapt_campaign_touchpoint,
        sa.adapt_web3_transaction,
        sa.adapt_identity_evidence,
        sa.adapt_outcome,
        sa.adapt_revenue,
        sa.adapt_exposure,
        sa.adapt_account_activity,
        sa.adapt_canonical_conversion,
    ],
)
def test_silver_adapters_never_invent_a_human(adapter) -> None:
    row = {"tenant_id": "t", "event_id": "e1", "occurred_at": "2026-11-16T00:00:00Z"}
    assert adapter(row)["actor_type"] == "unknown"
    assert adapter({**row, "actor_type": "human"})["actor_type"] == "human"
