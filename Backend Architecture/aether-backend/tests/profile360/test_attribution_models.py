"""Tests for ActorWeighted + ExposureAware attribution models."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from services.attribution.models import (
    ActorWeightedModel,
    ExposureAwareModel,
    Touchpoint,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _tp(channel: str, props: dict) -> Touchpoint:
    return Touchpoint(
        channel=channel,
        source="src",
        timestamp=datetime.now(timezone.utc),
        properties=props,
    )


def test_actor_weighted_normalizes():
    tps = [
        _tp("paid", {"actor_type": "human"}),
        _tp("direct", {"actor_type": "agent"}),
        _tp("email", {"actor_type": "human"}),
    ]
    result = _run(ActorWeightedModel().attribute(tps))
    total = sum(c.weight for c in result.credits)
    assert abs(total - 1.0) < 1e-6
    # Agent share is lower than the human shares at the same position class.
    agent_share = result.credits[1].weight
    human_share = result.credits[0].weight
    assert agent_share < human_share


def test_actor_weighted_unknown_actor_neutral():
    tps = [_tp("paid", {})]
    result = _run(ActorWeightedModel().attribute(tps))
    assert result.credits[0].weight == 1.0


def test_exposure_aware_filters_low_dwell_impressions():
    tps = [
        _tp("display", {"is_impression": True, "viewable_dwell_ms": 100}),
        _tp("direct", {}),
    ]
    result = _run(ExposureAwareModel().attribute(tps))
    # The impression got dropped (dwell < threshold), only the click remains.
    assert len(result.credits) == 1
    assert result.credits[0].touchpoint.channel == "direct"


def test_exposure_aware_keeps_qualifying_impression():
    tps = [
        _tp("display", {"is_impression": True, "viewable_dwell_ms": 5000}),
        _tp("direct", {}),
    ]
    result = _run(ExposureAwareModel().attribute(tps))
    assert len(result.credits) == 2
    total = sum(c.weight for c in result.credits)
    assert abs(total - 1.0) < 1e-6
