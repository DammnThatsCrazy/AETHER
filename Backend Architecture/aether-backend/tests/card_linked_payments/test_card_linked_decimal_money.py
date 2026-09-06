"""Decimal-money regression suite for the card-linked domain lane.

Pins the financial-normalization money rule on the card-linked rollup path:
amounts are decimal strings / Decimal; float money never reaches a rollup sum;
and an unknown/unparseable amount contributes nothing and is never zeroed.

Covered:
  1. gold ``_sum_usd`` sums fractional decimal-string amounts exactly
     (``"0.10" + "0.20"`` -> ``"0.30"``) and emits the 2-decimal string that
     the rollup contract (and existing tests) require;
  2. an unparseable / absent / non-finite amount contributes nothing to the
     sum — never coerced to 0;
  3. the entity rollup surface (Profile360 backing) and profile summary carry
     exact decimal totals out;
  4. volume filters compare with Decimal (never float) and exclude unknown
     amounts instead of treating them as 0;
  5. ``amount_bucket`` categorizes with exact Decimal ceilings.
"""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from services.card_linked_payments.gold import (  # noqa: E402
    _sum_usd,
    entity_economic_activity,
)
from services.card_linked_payments.ingestion import CardLinkedIngestionService  # noqa: E402
from services.card_linked_payments.models import amount_bucket  # noqa: E402
from services.card_linked_payments.profile_summary import (  # noqa: E402
    apply_flow_filters,
    get_card_linked_profile_summary,
)
from services.card_linked_payments.repositories import (  # noqa: E402
    reset_card_linked_repositories,
)

def _svc() -> CardLinkedIngestionService:
    reset_card_linked_repositories()
    return CardLinkedIngestionService(settings)


def _tenant() -> str:
    return "t_" + uuid.uuid4().hex[:12]


# ── gold._sum_usd: exact Decimal sums, unknown never 0 ────────────────────────


def test_sum_usd_fractional_string_amounts_sum_exactly():
    assert _sum_usd([{"amount_usd": "0.10"}, {"amount_usd": "0.20"}]) == "0.30"


def test_sum_usd_preserves_2_decimal_output_contract():
    assert _sum_usd([{"amount_usd": "100.00"}, {"amount_usd": "25.00"}]) == "125.00"


def test_sum_usd_unparseable_and_none_contribute_nothing_not_zeroed():
    rows = [
        {"amount_usd": None},
        {"amount_usd": ""},
        {"amount_usd": "not-a-number"},
        {"amount_usd": "0.10"},
    ]
    assert _sum_usd(rows) == "0.10"


def test_sum_usd_non_finite_never_counts():
    assert _sum_usd([{"amount_usd": "NaN"}, {"amount_usd": "0.50"}]) == "0.50"


def test_sum_usd_raw_numeric_amounts_parse_exactly():
    # A raw number that reaches the source row is parsed via to_decimal, never
    # routed through float money.
    assert _sum_usd([{"amount_usd": 100}, {"amount_usd": "0.50"}]) == "100.50"


def test_sum_usd_empty_rows_is_zero():
    assert _sum_usd([]) == "0.00"


# ── entity rollup + profile summary carry exact decimal totals out ────────────


async def _ingest_spend_flows(tenant: str, rows: list[dict]) -> None:
    svc = _svc()
    for i, row in enumerate(rows):
        await svc.ingest_provider_webhook(tenant, {
            "id": f"pw-dm-{i}",
            "provider": "acme",
            "provider_event_id": f"pe-dm-{i}",
            "basis": "spend",
            "card_program_id": "redotpay",
            "amount_usd": row.get("amount_usd"),
            "wallet_address_hash": row["wallet_address_hash"],
        })


@pytest.mark.asyncio
async def test_entity_rollup_fractional_and_unknown_amounts_exact():
    tenant = _tenant()
    wallet = "0xdecimal"
    await _ingest_spend_flows(tenant, [
        {"wallet_address_hash": wallet, "amount_usd": "0.10"},
        {"wallet_address_hash": wallet, "amount_usd": "0.20"},
        # Unknown / unparseable amounts must not be zeroed into the total.
        {"wallet_address_hash": wallet, "amount_usd": None},
        {"wallet_address_hash": wallet, "amount_usd": "garbage"},
    ])
    rollup = await entity_economic_activity(tenant, wallet)
    assert rollup["spend_count"] == 4          # all flows observed...
    assert rollup["spend_volume_usd"] == "0.30"  # ...but only parseable money sums


@pytest.mark.asyncio
async def test_profile_summary_rollup_and_flow_amounts_decimal_strings():
    tenant = _tenant()
    wallet = "0xsummary"
    await _ingest_spend_flows(tenant, [
        {"wallet_address_hash": wallet, "amount_usd": "0.10"},
        {"wallet_address_hash": wallet, "amount_usd": "0.20"},
    ])
    data = await get_card_linked_profile_summary(tenant, wallet)
    assert data["summary"]["spend_volume_usd"] == "0.30"
    # Flow payloads carry the exact decimal strings onward (never floats).
    for flow in data["flows"]:
        assert isinstance(flow.get("amount_usd"), str)
        assert flow["amount_usd"] in ("0.10", "0.20")


# ── volume filters compare with Decimal; unknown amounts are excluded ─────────


def test_apply_flow_filters_volume_bound_decimal_exact():
    rows = [
        {"id": "a", "amount_usd": "0.10"},
        {"id": "b", "amount_usd": "0.20"},
        {"id": "c", "amount_usd": "0.300000"},
        {"id": "unknown", "amount_usd": None},
        {"id": "garbage", "amount_usd": "nope"},
    ]
    # volume_min / volume_max are compared as Decimal, so "0.20" rows keep
    # their place and "0.300000" == 0.30 is not a float-approx edge.
    low = apply_flow_filters(rows, {"volume_min": "0.20"})
    assert {r["id"] for r in low} == {"b", "c"}
    high = apply_flow_filters(rows, {"volume_max": "0.20"})
    assert {r["id"] for r in high} == {"a", "b"}
    # Unknown/unparseable amounts are excluded once a bound is active — never
    # coerced to 0 and then "in range".
    assert "unknown" not in {r["id"] for r in low}
    assert "garbage" not in {r["id"] for r in high}


def test_apply_flow_filters_invalid_volume_bound_raises_value_error():
    with pytest.raises(ValueError):
        apply_flow_filters([{"amount_usd": "1.00"}], {"volume_min": "not-a-number"})


# ── amount_bucket: exact Decimal ceilings ─────────────────────────────────────


def test_amount_bucket_decimal_boundaries_exact():
    assert amount_bucket("9.99") == "0-10"
    assert amount_bucket("10.00") == "10-100"
    assert amount_bucket("100.00") == "100-1k"
    assert amount_bucket("0.10") == "0-10"
    assert amount_bucket("100000.00") == "100k+"


def test_amount_bucket_unknown_never_bucketed_as_zero():
    assert amount_bucket(None) is None
    assert amount_bucket("") is None
    assert amount_bucket("not-a-number") is None
    assert amount_bucket("NaN") is None
