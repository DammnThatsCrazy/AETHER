"""Unit tests for services.attribution.models — all attribution model classes.

Pure unit tests: no database, no HTTP, no settings loaded.
Each model's `attribute()` method is tested for:
  - Correctness of weight distribution
  - Result sums to ~1.0 (credit conservation)
  - Edge cases: single touchpoint, two touchpoints
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

# shared/__init__.py → shared.decorators → shared.auth.auth → jwt.
# The jwt package on this runner has a broken _cffi_backend.
# Pre-stub it so the import chain resolves without crypto hardware.
for _mod in ("jwt", "cryptography", "cryptography.hazmat",
             "cryptography.hazmat.primitives",
             "cryptography.hazmat.primitives.asymmetric",
             "cryptography.hazmat.primitives.asymmetric.ec",
             "cryptography.hazmat.bindings",
             "cryptography.hazmat.bindings._rust",
             "cryptography.hazmat._oid"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.attribution.models import (  # noqa: E402
    ActorWeightedModel,
    AttributionResult,
    DataDrivenModel,
    ExposureAwareModel,
    FirstTouchModel,
    LastTouchModel,
    LinearModel,
    PositionBasedModel,
    TimeDecayModel,
    Touchpoint,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tp(channel: str, source: str = "web", hours_ago: float = 0.0) -> Touchpoint:
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return Touchpoint(channel=channel, source=source, timestamp=ts)


def _weights(result: AttributionResult) -> list[float]:
    return [c.weight for c in result.credits]


def _sum_weights(result: AttributionResult) -> float:
    return sum(_weights(result))


# ---------------------------------------------------------------------------
# FirstTouchModel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_touch_single_tp():
    model = FirstTouchModel()
    tps = [_tp("organic")]
    result = await model.attribute(tps)
    assert _weights(result) == [pytest.approx(1.0)]
    assert result.model_used == "first_touch"


@pytest.mark.asyncio
async def test_first_touch_all_credit_to_first():
    model = FirstTouchModel()
    tps = [_tp("organic"), _tp("paid"), _tp("email")]
    result = await model.attribute(tps)
    weights = _weights(result)
    assert weights[0] == pytest.approx(1.0)
    assert weights[1] == pytest.approx(0.0)
    assert weights[2] == pytest.approx(0.0)
    assert _sum_weights(result) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# LastTouchModel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_last_touch_single_tp():
    model = LastTouchModel()
    tps = [_tp("organic")]
    result = await model.attribute(tps)
    assert _weights(result) == [pytest.approx(1.0)]


@pytest.mark.asyncio
async def test_last_touch_all_credit_to_last():
    model = LastTouchModel()
    tps = [_tp("organic"), _tp("paid"), _tp("email")]
    result = await model.attribute(tps)
    weights = _weights(result)
    assert weights[-1] == pytest.approx(1.0)
    assert weights[0] == pytest.approx(0.0)
    assert _sum_weights(result) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# LinearModel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_linear_single_tp():
    model = LinearModel()
    result = await model.attribute([_tp("organic")])
    assert _weights(result) == [pytest.approx(1.0)]


@pytest.mark.asyncio
async def test_linear_equal_distribution():
    model = LinearModel()
    tps = [_tp("organic"), _tp("paid"), _tp("email"), _tp("direct")]
    result = await model.attribute(tps)
    weights = _weights(result)
    for w in weights:
        assert w == pytest.approx(0.25)
    assert _sum_weights(result) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# TimeDecayModel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_time_decay_single_tp():
    model = TimeDecayModel(half_life_hours=168.0)
    result = await model.attribute([_tp("organic")])
    assert _weights(result) == [pytest.approx(1.0)]


@pytest.mark.asyncio
async def test_time_decay_more_recent_gets_higher_weight():
    model = TimeDecayModel(half_life_hours=24.0)
    tps = [_tp("organic", hours_ago=72), _tp("paid", hours_ago=0)]
    result = await model.attribute(tps)
    weights = _weights(result)
    # Most recent (last) should have higher weight
    assert weights[1] > weights[0]
    assert _sum_weights(result) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_time_decay_simultaneous_tps_equal_weight():
    model = TimeDecayModel(half_life_hours=24.0)
    now = datetime.now(timezone.utc)
    tps = [
        Touchpoint(channel="a", source="s", timestamp=now),
        Touchpoint(channel="b", source="s", timestamp=now),
    ]
    result = await model.attribute(tps)
    weights = _weights(result)
    assert weights[0] == pytest.approx(weights[1])


# ---------------------------------------------------------------------------
# PositionBasedModel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_position_based_single_tp():
    model = PositionBasedModel()
    result = await model.attribute([_tp("organic")])
    assert _weights(result) == [pytest.approx(1.0)]


@pytest.mark.asyncio
async def test_position_based_two_tps():
    model = PositionBasedModel(first_weight=0.40, last_weight=0.40)
    tps = [_tp("organic"), _tp("paid")]
    result = await model.attribute(tps)
    weights = _weights(result)
    assert weights[0] == pytest.approx(0.40 / (0.40 + 0.40))
    assert weights[1] == pytest.approx(0.40 / (0.40 + 0.40))
    assert _sum_weights(result) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_position_based_five_tps():
    model = PositionBasedModel(first_weight=0.40, last_weight=0.40)
    tps = [_tp(str(i)) for i in range(5)]
    result = await model.attribute(tps)
    weights = _weights(result)
    # First and last should each get ~40% of credit before normalization;
    # middle three share ~20%
    assert weights[0] > weights[1]
    assert weights[-1] > weights[-2]
    assert _sum_weights(result) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# DataDrivenModel (Shapley approximation)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_data_driven_single_tp():
    model = DataDrivenModel()
    result = await model.attribute([_tp("organic")])
    assert _weights(result) == [pytest.approx(1.0)]


@pytest.mark.asyncio
async def test_data_driven_weights_sum_to_one():
    model = DataDrivenModel(max_coalition_size=4)
    tps = [_tp(ch) for ch in ["organic", "paid", "email"]]
    result = await model.attribute(tps)
    assert _sum_weights(result) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.asyncio
async def test_data_driven_diverse_channels_higher_value():
    """Coalition value should reflect channel diversity."""
    from services.attribution.models import DataDrivenModel as DDM
    model = DDM()
    tps = [
        Touchpoint(channel="organic", source="google"),
        Touchpoint(channel="paid", source="fb"),
        Touchpoint(channel="email", source="mailchimp"),
    ]
    # All channels unique — diversity_factor should be 1.0
    v = DDM._coalition_value(tps, [0, 1, 2])
    assert v > 0


@pytest.mark.asyncio
async def test_data_driven_empty_coalition_value_is_zero():
    from services.attribution.models import DataDrivenModel as DDM
    tps = [_tp("organic")]
    assert DDM._coalition_value(tps, []) == 0.0


@pytest.mark.asyncio
async def test_data_driven_large_journey_truncated():
    """Journeys longer than max_coalition_size use only the last N touchpoints."""
    model = DataDrivenModel(max_coalition_size=3)
    tps = [_tp(str(i)) for i in range(10)]
    result = await model.attribute(tps)
    # Should return 3 credits (only the last 3 touchpoints)
    assert len(result.credits) == 3
    assert _sum_weights(result) == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# ActorWeightedModel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_actor_weighted_human_gets_more_than_agent():
    model = ActorWeightedModel(human_weight=0.7, agent_weight=0.3)
    human_tp = Touchpoint(channel="web", source="app", properties={"actor_type": "human"})
    agent_tp = Touchpoint(channel="api", source="agent", properties={"actor_type": "agent"})
    result = await model.attribute([human_tp, agent_tp])
    weights = _weights(result)
    assert weights[0] > weights[1]
    assert _sum_weights(result) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_actor_weighted_sums_to_one():
    model = ActorWeightedModel()
    tps = [
        Touchpoint(channel="web", source="s", properties={"actor_type": "human"}),
        Touchpoint(channel="api", source="s", properties={"actor_type": "agent"}),
        Touchpoint(channel="web", source="s", properties={}),  # no actor_type
    ]
    result = await model.attribute(tps)
    assert _sum_weights(result) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# ExposureAwareModel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exposure_aware_impression_reduced_credit():
    model = ExposureAwareModel(impression_weight=0.3, dwell_threshold_ms=0)
    impression_tp = Touchpoint(
        channel="display", source="ad",
        properties={"is_impression": True, "viewable_dwell_ms": 500},
    )
    click_tp = Touchpoint(channel="paid", source="google", properties={})
    result = await model.attribute([impression_tp, click_tp])
    weights = _weights(result)
    # Click should get more credit than impression
    assert weights[1] > weights[0]
    assert _sum_weights(result) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_exposure_aware_sums_to_one():
    model = ExposureAwareModel()
    tps = [
        Touchpoint(channel="display", source="ad",
                   properties={"is_impression": True}),
        Touchpoint(channel="paid", source="google", properties={}),
        Touchpoint(channel="organic", source="seo", properties={}),
    ]
    result = await model.attribute(tps)
    assert _sum_weights(result) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# General invariants across all models
# ---------------------------------------------------------------------------

ALL_MODELS = [
    FirstTouchModel(),
    LastTouchModel(),
    LinearModel(),
    TimeDecayModel(),
    PositionBasedModel(),
    DataDrivenModel(max_coalition_size=4),
    ActorWeightedModel(),
    ExposureAwareModel(),
]


@pytest.mark.parametrize("model", ALL_MODELS, ids=lambda m: m.name)
@pytest.mark.asyncio
async def test_all_models_sum_to_one(model):
    tps = [_tp(ch) for ch in ["organic", "paid", "email", "direct"]]
    result = await model.attribute(tps)
    assert _sum_weights(result) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize("model", ALL_MODELS, ids=lambda m: m.name)
@pytest.mark.asyncio
async def test_all_models_single_touchpoint(model):
    result = await model.attribute([_tp("organic")])
    assert _weights(result) == [pytest.approx(1.0)]


@pytest.mark.parametrize("model", ALL_MODELS, ids=lambda m: m.name)
@pytest.mark.asyncio
async def test_all_models_credits_match_touchpoint_count(model):
    tps = [_tp(str(i)) for i in range(3)]
    result = await model.attribute(tps)
    # DataDriven may truncate to max_coalition_size, others should match
    assert len(result.credits) <= len(tps)


@pytest.mark.parametrize("model", ALL_MODELS, ids=lambda m: m.name)
@pytest.mark.asyncio
async def test_all_models_name_in_result(model):
    result = await model.attribute([_tp("organic")])
    assert result.model_used == model.name
