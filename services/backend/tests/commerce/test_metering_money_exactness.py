"""
Commerce metering money-boundary regression tests (financial normalization).

Proves that float money never reaches the commerce metering rollup math or the
persisted metering store:

- A meter record persists its amount as a canonical decimal string. The float
  is converted at the persistence boundary, so a float amount that is
  mathematically fine (``5.0``, ``0.05``) lands as the canonical decimal
  string ``"5.0"`` / ``"0.05"`` — never as the binary float.
- The tenant rollup sums in exact ``Decimal``: two fractional amounts (0.1 and
  0.2) total to exactly ``Decimal("0.3")`` — no binary-float accumulation
  artifact (``0.1 + 0.2`` in float yields ``0.30000000000000004``).
- A record written with no parseable amount is unpriced: it is never coerced
  to zero, while an explicitly-zero amount still prices as 0.0.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores
from services.commerce.metering import CommerceMeteringService


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _svc() -> CommerceMeteringService:
    # A fresh service per call binds to the (shared, reset) in-memory table.
    return CommerceMeteringService()


@pytest.mark.asyncio
async def test_meter_record_persists_canonical_decimal_string():
    svc = _svc()
    await svc.record_payment(
        "t_dec", resource_id="res_a", holder_id="agent_1",
        amount_usd=5.0, chain="eip155:8453", asset_symbol="USDC",
        authorization_id="auth_1",
    )
    await svc.record_payment(
        "t_dec", resource_id="res_a", holder_id="agent_1",
        amount_usd=0.05, chain="eip155:8453", asset_symbol="USDC",
        authorization_id="auth_2",
    )

    rows = await svc._repo.list_for_tenant("t_dec", limit=10)
    stored = {r["amount_usd"] for r in rows}
    # A "mathematically fine" float must land as a canonical decimal string.
    assert stored == {"5.0", "0.05"}
    assert all(isinstance(value, str) for value in stored)
    assert {Decimal(v) for v in stored} == {Decimal("5.0"), Decimal("0.05")}


@pytest.mark.asyncio
async def test_metering_rollup_sums_fractional_amounts_exactly():
    svc = _svc()
    await svc.record_payment(
        "t_frac", resource_id="res_a", holder_id="agent_1",
        amount_usd=0.1, chain="eip155:8453", asset_symbol="USDC",
        authorization_id="auth_1",
    )
    await svc.record_payment(
        "t_frac", resource_id="res_a", holder_id="agent_1",
        amount_usd=0.2, chain="eip155:8453", asset_symbol="USDC",
        authorization_id="auth_2",
    )

    summary = await svc.summarize("t_frac")
    total = summary["by_type"]["payment_paid"]["amount_usd"]

    # Sum of the persisted canonical facts is exactly 0.3.
    rows = await svc._repo.list_for_tenant("t_frac", limit=10)
    dec_sum = sum((Decimal(r["amount_usd"]) for r in rows), Decimal("0"))
    assert dec_sum == Decimal("0.3")

    # The surfaced total round-trips to the exact decimal — no binary-float
    # accumulation artifact (float 0.1 + 0.2 is 0.30000000000000004).
    assert Decimal(str(total)) == Decimal("0.3")
    assert str(total) == "0.3"
    assert total != 0.1 + 0.2


@pytest.mark.asyncio
async def test_unpriced_meter_record_is_never_coerced_to_zero():
    svc = _svc()
    await svc.record_access_granted(
        "t_none", resource_id="res_a", holder_id="agent_1",
        amount_usd=None, entitlement_id="ent_1",
    )

    rows = await svc._repo.list_for_tenant("t_none", limit=10)
    assert rows[0]["amount_usd"] is None

    summary = await svc.summarize("t_none")
    agg = summary["by_type"]["access_granted"]
    assert agg["count"] == 1
    assert agg["amount_usd"] is None


@pytest.mark.asyncio
async def test_explicit_zero_amount_still_prices_to_zero():
    svc = _svc()
    await svc.record_access_granted(
        "t_zero", resource_id="res_a", holder_id="agent_1",
        amount_usd=0.0, entitlement_id="ent_1",
    )

    rows = await svc._repo.list_for_tenant("t_zero", limit=10)
    assert rows[0]["amount_usd"] == "0.0"

    summary = await svc.summarize("t_zero")
    assert summary["by_type"]["access_granted"]["amount_usd"] == 0.0
