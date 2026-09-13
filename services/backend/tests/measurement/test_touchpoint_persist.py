"""Touchpoint durability — properties / revenue_usd / is_conversion round-trip.

``services/campaign/routes.py::record_touchpoint`` builds a touchpoint dict
that includes ``properties``, ``revenue_usd``, and ``is_conversion`` and
passes it to ``TouchpointRepository.upsert_from_campaign_touchpoint``, but
until now ``silver_campaign_touchpoint_facts`` had no columns for any of the
three — the repository silently dropped them before the row reached storage,
even though the API response echoed the caller's input back as if it had
been persisted.

These tests exercise the repository directly (local in-memory branch, as the
sibling ``tests/unit/test_touchpoint_source_classification.py`` does) and
assert all three fields round-trip through ``upsert_from_campaign_touchpoint``
and ``get`` with correct, durable types:

- ``properties``    -> dict (JSONB column)
- ``revenue_usd``   -> decimal.Decimal, never float (NUMERIC(18,6) column;
  see docs/source-of-truth/FINANCIAL_VALUE_SEMANTICS.md)
- ``is_conversion`` -> bool (BOOLEAN column)
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from services.measurement.repositories.touchpoint_repo import (
    TouchpointRepository,
    _reset_local_touchpoints,
)


@pytest.fixture(autouse=True)
def reset_local_store(monkeypatch: pytest.MonkeyPatch):
    async def no_pool():
        return None

    # Force the in-memory branch regardless of the ambient AETHER_ENV/
    # DATABASE_URL — same technique the sibling classification-repo tests
    # use, so this file is hermetic even if run outside AETHER_ENV=local.
    monkeypatch.setattr(
        "services.measurement.repositories.touchpoint_repo.get_pool",
        no_pool,
    )
    _reset_local_touchpoints()
    yield
    _reset_local_touchpoints()


def _campaign_touchpoint_payload(**overrides) -> dict:
    """Shape matches the ``touchpoint`` dict built by
    ``services/campaign/routes.py::record_touchpoint`` and passed as
    ``data=`` to ``upsert_from_campaign_touchpoint``.
    """
    payload = {
        "user_id": "user-123",
        "session_id": "session-abc",
        "channel": "paid_search",
        "source": "google",
        "event_type": "conversion",
        "is_conversion": True,
        "revenue_usd": 129.99,
        "occurred_at": "2026-08-07T12:00:00+00:00",
        "properties": {"k": "v", "order_id": "ord-42"},
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_touchpoint_properties_revenue_is_conversion_round_trip() -> None:
    repo = TouchpointRepository()
    tenant_id = "tenant-round-trip"
    campaign_id = "campaign-1"
    touchpoint_id = str(uuid4())

    written = await repo.upsert_from_campaign_touchpoint(
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        touchpoint_id=touchpoint_id,
        data=_campaign_touchpoint_payload(),
    )

    # The write path itself must return the durable values, not the caller's
    # raw input echoed back unpersisted.
    assert written["properties"] == {"k": "v", "order_id": "ord-42"}
    assert isinstance(written["properties"], dict)
    assert written["revenue_usd"] == Decimal("129.99")
    assert isinstance(written["revenue_usd"], Decimal)
    assert written["is_conversion"] is True

    # Read back through a fresh repository instance — proves persistence,
    # not just a same-call in-memory echo.
    fetched = await TouchpointRepository().get(tenant_id, touchpoint_id)
    assert fetched is not None

    assert fetched["properties"] == {"k": "v", "order_id": "ord-42"}
    assert isinstance(fetched["properties"], dict)

    assert fetched["revenue_usd"] == Decimal("129.99")
    assert isinstance(fetched["revenue_usd"], Decimal)
    assert not isinstance(fetched["revenue_usd"], float)

    assert fetched["is_conversion"] is True
    assert isinstance(fetched["is_conversion"], bool)


@pytest.mark.asyncio
async def test_touchpoint_revenue_usd_avoids_binary_float_precision_loss() -> None:
    """Decimal must be derived via str(), not float() — Decimal(0.1) != Decimal('0.1')."""
    repo = TouchpointRepository()
    tenant_id = "tenant-precision"
    touchpoint_id = str(uuid4())

    await repo.upsert_from_campaign_touchpoint(
        tenant_id=tenant_id,
        campaign_id="campaign-1",
        touchpoint_id=touchpoint_id,
        data=_campaign_touchpoint_payload(revenue_usd=19.1, is_conversion=True),
    )

    fetched = await repo.get(tenant_id, touchpoint_id)
    assert fetched["revenue_usd"] == Decimal("19.1")
    # The unsafe conversion path (Decimal(19.1)) would produce a long
    # binary-float artifact instead of the exact decimal literal.
    assert str(fetched["revenue_usd"]) == "19.1"


@pytest.mark.asyncio
async def test_touchpoint_defaults_are_backward_compatible_when_absent() -> None:
    """A touchpoint arriving without the three fields must still round-trip
    to the nullable/defaulted values the migration establishes: an empty
    properties object, a NULL revenue_usd, and is_conversion=False — never
    a KeyError or silently dropped column.
    """
    repo = TouchpointRepository()
    tenant_id = "tenant-defaults"
    touchpoint_id = str(uuid4())

    data = _campaign_touchpoint_payload()
    del data["properties"]
    del data["revenue_usd"]
    del data["is_conversion"]

    await repo.upsert_from_campaign_touchpoint(
        tenant_id=tenant_id,
        campaign_id="campaign-1",
        touchpoint_id=touchpoint_id,
        data=data,
    )

    fetched = await repo.get(tenant_id, touchpoint_id)
    assert fetched["properties"] == {}
    assert fetched["revenue_usd"] is None
    assert fetched["is_conversion"] is False


@pytest.mark.asyncio
async def test_touchpoint_non_conversion_still_persists_properties() -> None:
    """A non-conversion touchpoint (is_conversion=False, revenue_usd=0.0 —
    the TouchpointCreate Pydantic defaults) must still durably persist
    caller-supplied properties rather than only conversions being tracked.
    """
    repo = TouchpointRepository()
    tenant_id = "tenant-non-conversion"
    touchpoint_id = str(uuid4())

    await repo.upsert_from_campaign_touchpoint(
        tenant_id=tenant_id,
        campaign_id="campaign-1",
        touchpoint_id=touchpoint_id,
        data=_campaign_touchpoint_payload(
            is_conversion=False, revenue_usd=0.0, properties={"page": "/pricing"},
        ),
    )

    fetched = await repo.get(tenant_id, touchpoint_id)
    assert fetched["properties"] == {"page": "/pricing"}
    assert fetched["is_conversion"] is False
    assert fetched["revenue_usd"] == Decimal("0.0")
    assert isinstance(fetched["revenue_usd"], Decimal)
