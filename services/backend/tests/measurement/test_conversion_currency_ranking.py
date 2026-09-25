"""Conversion money correctness on the SDK -> Silver -> canonical path.

Regression for two defects found by the staging rehearsal:

1. Currency. ``ConversionProjector`` hardcoded ``exchange_rate = "1.0"`` and the
   Silver writer inserted ``canonical_conversions`` through its generic path, so
   a EUR or JPY order was stored at USD parity and counted as the same USD
   amount downstream (attribution credits -> campaign revenue). The repository's
   unpriced branch also left the ``"1.0"`` default in place.
2. Ranking. The generic Silver insert is ``ON CONFLICT DO NOTHING`` -- the first
   source record to land owned the canonical row, whatever its authority -- and
   the repository's equal-authority rule was last-write-wins.

Events here are shaped like real ``/v1/batch`` track events after Bronze
canonicalization (``type`` = event name, ``properties``, ``context``).
"""

from __future__ import annotations

import itertools
from decimal import Decimal
from typing import Any

import pytest

from services.measurement.engine import attribution_engine as engine_mod
from services.measurement.repositories import attribution_run_repo as run_mod
from services.measurement.repositories import conversion_repo as conv_mod
from services.measurement.repositories import journey_repo as journey_mod
from services.measurement.repositories import touchpoint_repo as tp_mod
from services.measurement.repositories.attribution_run_repo import AttributionRunRepository
from services.measurement.repositories.conversion_repo import (
    ConversionRepository,
    conversion_is_unconverted,
    normalized_money,
)
from services.silver.projectors.conversion_projector import ConversionProjector
from services.silver.writer import SilverFactWriter
from services.value import fx_provider, price_sources

TENANT = "tenant-fx-rank"


@pytest.fixture(autouse=True)
def _local_mode(monkeypatch: pytest.MonkeyPatch):
    async def no_pool():
        return None

    for mod in (conv_mod, run_mod, tp_mod, journey_mod):
        if hasattr(mod, "get_pool"):
            monkeypatch.setattr(mod, "get_pool", no_pool)
    conv_mod._local_store.clear()
    fx_provider.register()
    yield
    conv_mod._local_store.clear()
    price_sources.clear_price_providers()


def _track(event: str, message_id: str, props: dict[str, Any], ts: str) -> dict[str, Any]:
    """A /v1/batch ``track`` event as the Silver dispatcher receives it."""
    return {
        "type": event,
        "messageId": message_id,
        "id": message_id,
        "timestamp": ts,
        "receivedAt": ts,
        "userId": "user_42",
        "anonymousId": "anon_9f2c",
        "tenantId": TENANT,
        "properties": props,
        "context": {"tenantId": TENANT, "library": {"name": "aether-web", "version": "9.0.0"}},
    }


async def _project_and_write(event: dict[str, Any]) -> None:
    result = ConversionProjector().project(event)
    assert result is not None and not result.skipped
    written = await SilverFactWriter().persist([result])
    assert written == 1


def _stored() -> list[dict[str, Any]]:
    return [r for r in conv_mod._local_store.values() if r.get("tenant_id") == TENANT]


# -- Currency -----------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("currency", "rate", "usd"),
    [("EUR", "1.08", Decimal("108.00")), ("JPY", "0.0067", Decimal("0.6700"))],
)
async def test_silver_foreign_order_records_real_rate_not_parity(currency, rate, usd):
    await _project_and_write(_track(
        "order_completed", f"msg-{currency}",
        {"order_id": f"ord-{currency}", "revenue": "100.00", "currency": currency.lower()},
        "2026-09-20T10:00:00+00:00",
    ))

    (row,) = _stored()
    assert row["currency"] == currency            # native preserved, normalized case
    assert row["gross_value"] == "100.00"         # native amount preserved
    assert row["exchange_rate"] == rate           # real recorded rate, not "1.0"
    fx = row["provenance"]["fx_conversion"]
    assert fx["priced"] is True
    assert fx["conversion_source"].startswith("fx_snapshot_")
    assert normalized_money(row, "gross_value") == usd
    assert not conversion_is_unconverted(row)


@pytest.mark.asyncio
async def test_silver_order_with_unknown_rate_is_explicitly_unconverted():
    await _project_and_write(_track(
        "order_completed", "msg-sek",
        {"order_id": "ord-sek", "revenue": "250", "currency": "SEK"},
        "2026-09-20T10:00:00+00:00",
    ))

    (row,) = _stored()
    assert row["currency"] == "SEK"
    assert row["gross_value"] == "250"
    assert row["exchange_rate"] is None           # never a silent 1.0
    fx = row["provenance"]["fx_conversion"]
    assert fx["priced"] is False and fx["method"] == "unpriced"
    assert fx["exchange_rate"] is None
    assert conversion_is_unconverted(row)
    assert normalized_money(row, "gross_value") is None


@pytest.mark.asyncio
async def test_caller_supplied_foreign_parity_is_not_trusted():
    row = await ConversionRepository().upsert({
        "tenant_id": TENANT, "conversion_type": "purchase", "order_id": "o-1",
        "currency": "SEK", "gross_value": "10", "exchange_rate": "1.0",
        "occurred_at": "2026-09-20T10:00:00+00:00", "source_event_id": "e-1",
    })
    assert row["exchange_rate"] is None
    assert conversion_is_unconverted(row)


def test_legacy_unpriced_row_with_parity_rate_is_unconverted():
    # Rows written before exchange_rate became nullable hold 1.0 plus the
    # priced=false marker; the marker wins, so they are not read as USD.
    legacy = {
        "currency": "SEK", "normalized_currency": "USD", "exchange_rate": "1.0",
        "gross_value": "10",
        "provenance": '{"fx_conversion": {"priced": false, "method": "unpriced"}}',
    }
    assert conversion_is_unconverted(legacy)
    assert normalized_money(legacy, "gross_value") is None


def test_same_currency_row_is_parity_even_without_rate():
    row = {"currency": "usd", "normalized_currency": "USD", "exchange_rate": None,
           "gross_value": "12.50"}
    assert normalized_money(row, "gross_value") == Decimal("12.50")
    assert normalized_money(row, "net_value") is None  # missing is unknown, not 0


# -- Deterministic ranking ------------------------------------------------------


def _checkout(ts: str = "2026-09-20T10:00:00+00:00") -> dict[str, Any]:
    # Client-observed checkout (authority 80) for order ord-77, EUR 90.
    return _track("checkout_completed", "msg-checkout-77",
                  {"order_id": "ord-77", "revenue": "90.00", "currency": "EUR"}, ts)


def _order(ts: str = "2026-09-20T10:00:05+00:00") -> dict[str, Any]:
    # Commerce webhook order (authority 90) for the same order, EUR 100.
    return _track("order_completed", "msg-order-77",
                  {"order_id": "ord-77", "revenue": "100.00", "currency": "EUR"}, ts)


@pytest.mark.asyncio
@pytest.mark.parametrize("order", ["checkout_first", "order_first"])
async def test_higher_authority_wins_regardless_of_arrival_order(order):
    events = [_checkout(), _order()]
    if order == "order_first":
        events.reverse()
    for event in events:
        await _project_and_write(event)

    (row,) = _stored()                            # one canonical row per order
    assert row["authority_rank"] == 90
    assert row["gross_value"] == "100.00"
    assert row["source_event_id"] == "msg-order-77"
    assert row["exchange_rate"] == "1.08"
    # The losing record is kept as evidence, never dropped.
    assert row["evidence_ids"] == ["msg-checkout-77", "msg-order-77"]


@pytest.mark.asyncio
async def test_equal_authority_is_order_independent():
    def rec(event_id: str, ts: str, value: str) -> dict[str, Any]:
        return {
            "tenant_id": TENANT, "conversion_type": "purchase",
            "deduplication_key": "dk-eq", "authority_rank": 90,
            "currency": "USD", "gross_value": value, "occurred_at": ts,
            "source_event_id": event_id, "evidence_ids": [event_id],
        }

    records = [
        rec("evt-a", "2026-09-20T10:00:00+00:00", "100.00"),
        rec("evt-b", "2026-09-20T11:00:00+00:00", "120.00"),  # later update
        rec("evt-c", "2026-09-20T11:00:00+00:00", "125.00"),  # same time, id tie-break
    ]
    winners = set()
    for perm in itertools.permutations(records):
        conv_mod._local_store.clear()
        for r in perm:
            await ConversionRepository().upsert(dict(r))
        (row,) = _stored()
        winners.add((row["source_event_id"], row["gross_value"], tuple(row["evidence_ids"])))
    assert winners == {("evt-c", "125.00", ("evt-a", "evt-b", "evt-c"))}


@pytest.mark.asyncio
async def test_canonical_conversion_id_is_stable_across_merges():
    first = await ConversionRepository().upsert({
        "tenant_id": TENANT, "conversion_type": "purchase", "deduplication_key": "dk-id",
        "authority_rank": 50, "gross_value": "1", "occurred_at": "2026-09-20T10:00:00+00:00",
        "source_event_id": "e1",
    })
    await ConversionRepository().upsert({
        "tenant_id": TENANT, "conversion_type": "purchase", "deduplication_key": "dk-id",
        "authority_rank": 90, "gross_value": "2", "occurred_at": "2026-09-20T10:00:00+00:00",
        "source_event_id": "e2",
    })
    (row,) = _stored()
    assert row["conversion_id"] == first["conversion_id"]
    assert row["gross_value"] == "2"


def test_sql_conflict_clause_is_ranked_not_first_write_wins():
    sql = " ".join(conv_mod._UPSERT_SQL.split())
    assert "DO NOTHING" not in sql
    assert "(EXCLUDED.occurred_at, COALESCE(EXCLUDED.source_event_id, '')) >=" in sql
    # Every winner-owned column moves under the same ranking condition.
    for col in ("gross_value", "net_value", "currency", "exchange_rate",
                "provenance", "source_event_id", "occurred_at"):
        assert f"{col} = CASE WHEN EXCLUDED.authority_rank > canonical_conversions.authority_rank" in sql
    assert "jsonb_array_elements" in sql           # evidence merged, not replaced


# -- Downstream: attribution credits are normalized ---------------------------


async def _attribute(currency: str, message_id: str) -> tuple[dict, list[dict]]:
    from services.measurement.repositories.touchpoint_repo import TouchpointRepository

    profile = f"profile-{message_id}"
    campaign = f"camp-{message_id}"
    await TouchpointRepository().upsert({
        "tenant_id": TENANT, "profile_id": profile, "campaign_id": campaign,
        "touchpoint_type": "click", "channel": "paid_search", "source": "google",
        "is_click_through": True, "occurred_at": "2026-09-20T09:00:00+00:00",
        "received_at": "2026-09-20T09:00:00+00:00", "idempotency_key": f"tp-{message_id}",
    })
    conversion = await ConversionRepository().upsert({
        "tenant_id": TENANT, "conversion_type": "purchase", "profile_id": profile,
        "order_id": f"ord-{message_id}", "currency": currency,
        "gross_value": "100.00", "net_value": "100.00",
        "occurred_at": "2026-09-20T10:00:00+00:00", "source_event_id": message_id,
        "authority_rank": 90,
    })
    run = await engine_mod.AttributionEngine().run_for_conversion(
        TENANT, conversion["conversion_id"], model_type="last_touch",
    )
    credits = await AttributionRunRepository().list_credits_for_conversion(
        TENANT, conversion["conversion_id"],
    )
    return run, credits, campaign


@pytest.mark.asyncio
async def test_attribution_credits_carry_usd_not_native_amount():
    run, credits, campaign = await _attribute("EUR", "attr-eur")
    assert run["currency"] == "USD"
    assert Decimal(str(run["eligible_revenue"])) == Decimal("108.00")
    assert credits, "the click should be credited"
    assert sum(Decimal(c["attributed_net_revenue"]) for c in credits) == Decimal("108.00")

    summary = await AttributionRunRepository().campaign_credit_summary(TENANT, campaign)
    assert summary["total_attributed_net_revenue"] == Decimal("108.00")
    assert summary["unconverted_credit_count"] == 0
    assert summary["data_quality"] == "complete"


@pytest.mark.asyncio
async def test_unconverted_conversion_credits_have_no_revenue():
    run, credits, campaign = await _attribute("SEK", "attr-sek")
    assert run["eligible_revenue"] is None
    assert credits
    assert all(c["attributed_net_revenue"] is None for c in credits)

    summary = await AttributionRunRepository().campaign_credit_summary(TENANT, campaign)
    # Excluded from the USD total -- not counted as 100 USD -- and flagged.
    assert summary["total_attributed_net_revenue"] == Decimal("0")
    assert summary["unconverted_credit_count"] == len(credits)
    assert summary["data_quality"] == "partial"
