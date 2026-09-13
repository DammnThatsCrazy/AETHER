"""Pure unit tests for the observation ingest path + economic-role classifier."""
from __future__ import annotations

from decimal import Decimal

import pydantic
import pytest

from services.valuation.ingest import (
    classify_economic_role,
    normalize_observation,
    observe_price,
)
from services.valuation.price_providers import PROVIDER_REPORTED

from ._fakes import FakeObservationStore

OBSERVED_AT = "2026-09-02T11:59:00+00:00"


def _observation_dict(**overrides):
    base = {
        "asset_id": "crypto:ETH",
        "quote_asset_id": "fiat:USD",
        "price": "100.00",
        "provider": PROVIDER_REPORTED,
        "observed_at": OBSERVED_AT,
        "source": "test:fixture",
        "source_record_id": "sr-1",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_observe_price_stamps_received_at_and_observation_id():
    store = FakeObservationStore()
    recorded = await observe_price(store, _observation_dict())
    assert recorded.received_at is not None
    assert recorded.observation_id is not None
    assert recorded.observation_id.startswith("obs_")
    assert isinstance(recorded.price, Decimal)
    assert len(store.rows) == 1


@pytest.mark.asyncio
async def test_observe_price_is_idempotent_on_natural_key():
    store = FakeObservationStore()
    payload = _observation_dict()
    first = await observe_price(store, payload)
    second = await observe_price(store, payload)
    assert first == second
    assert len(store.rows) == 1
    assert store.record_calls == 1  # second call short-circuits before record


@pytest.mark.asyncio
async def test_observe_price_distinct_source_record_ids_both_recorded():
    store = FakeObservationStore()
    await observe_price(store, _observation_dict(source_record_id="sr-a"))
    await observe_price(store, _observation_dict(source_record_id="sr-b"))
    assert len(store.rows) == 2


@pytest.mark.asyncio
async def test_observe_price_rejects_float_price():
    store = FakeObservationStore()
    with pytest.raises(pydantic.ValidationError):
        await observe_price(store, _observation_dict(price=100.5))


def test_normalize_observation_rejects_missing_observed_at():
    with pytest.raises(ValueError):
        normalize_observation({"asset_id": "crypto:ETH", "price": "1"})


def test_classify_economic_role_membership_and_defaults():
    assert classify_economic_role("payment") == "payment"
    assert classify_economic_role("REVENUE") == "revenue"
    assert classify_economic_role("asset holding") == "asset_holding"
    assert classify_economic_role({"role": "fee"}) == "fee"
    assert classify_economic_role({"purpose": "settlement"}) == "settlement"
    assert classify_economic_role("chargeback") == "unknown"
    assert classify_economic_role(None) == "unknown"
    assert classify_economic_role("unknown") == "unknown"
    assert classify_economic_role({"hint": "dispute"}) == "dispute"
