"""Money vocabulary: arithmetic, determinism, and serialization."""

from __future__ import annotations

from decimal import Decimal

import pytest

from shared.commerce_contracts.money import (
    Currency,
    Money,
    money_from_cents,
    sum_money,
    to_cents,
)


# ── Currency vocabulary ────────────────────────────────────────────────────


def test_currency_enum_members() -> None:
    assert {c.value for c in Currency} == {"USD", "EUR", "GBP", "CAD", "AUD"}
    assert Currency.USD.value == "USD"
    assert Currency.USD == "USD"  # str-enum compares by value


# ── Money construction / typing ────────────────────────────────────────────


def test_money_amount_is_exact_decimal() -> None:
    m = Money(amount="12.34", currency="USD")  # str coerced to Decimal
    assert isinstance(m.amount, Decimal)
    assert m.amount == Decimal("12.34")
    n = Money(amount=1200, currency="EUR")  # int coerced to Decimal
    assert n.amount == Decimal("1200")


def test_money_accepts_negative_amounts() -> None:
    # Refunds/credits are legitimate — negatives must never be rejected.
    m = Money(amount=Decimal("-25.00"), currency="USD")
    assert m.amount == Decimal("-25.00")


def test_money_is_frozen_and_hashable() -> None:
    m = Money(amount=Decimal("1.00"), currency="USD")
    with pytest.raises(Exception):
        m.amount = Decimal("2.00")  # type: ignore[misc]
    assert hash(m) == hash(Money(amount=Decimal("1.00"), currency="USD"))


def test_money_model_dump_and_json_serialization() -> None:
    m = Money(amount=Decimal("12.34"), currency="USD")
    dumped = m.model_dump()
    assert dumped == {"amount": Decimal("12.34"), "currency": "USD"}
    json_dump = m.model_dump(mode="json")
    # pydantic v2 serializes Decimal to str in JSON mode.
    assert json_dump == {"amount": "12.34", "currency": "USD"}


# ── sum_money ──────────────────────────────────────────────────────────────


def test_sum_money_single_currency() -> None:
    total = sum_money(
        [
            Money(amount=Decimal("1.00"), currency="USD"),
            Money(amount=Decimal("2.50"), currency="USD"),
            Money(amount=Decimal("0.25"), currency="USD"),
        ]
    )
    assert total.amount == Decimal("3.75")
    assert total.currency == "USD"


def test_sum_money_single_item_preserves_currency() -> None:
    total = sum_money([Money(amount=Decimal("9.99"), currency="EUR")])
    assert total.amount == Decimal("9.99")
    assert total.currency == "EUR"


def test_sum_money_empty_input_returns_zero() -> None:
    total = sum_money([])
    assert total.amount == Decimal("0")
    assert isinstance(total, Money)
    # Documented default: no common currency exists for an empty input, so the
    # platform's base ledger currency (USD) is used. Locked so a change to
    # _DEFAULT_SUM_CURRENCY cannot silently drift from the docstring.
    assert total.currency == "USD"


def test_sum_money_mixed_currency_raises() -> None:
    with pytest.raises(ValueError):
        sum_money(
            [
                Money(amount=Decimal("1.00"), currency="USD"),
                Money(amount=Decimal("1.00"), currency="EUR"),
            ]
        )


def test_sum_money_negative_amounts_sum() -> None:
    total = sum_money(
        [
            Money(amount=Decimal("10.00"), currency="USD"),
            Money(amount=Decimal("-3.00"), currency="USD"),
        ]
    )
    assert total.amount == Decimal("7.00")


# ── money_from_cents / to_cents determinism ────────────────────────────────


def test_money_from_cents_to_cents_round_trip() -> None:
    for cents in (0, 1, 99, 100, 12345, 999999, -12345):
        m = money_from_cents(cents, "USD")
        assert m.amount == Decimal(cents) / 100
        assert m.currency == "USD"
        assert to_cents(m) == cents


def test_to_cents_rounds_half_up_deterministically() -> None:
    # ROUND_HALF_UP: 1.005 -> 1.01 -> 101 cents.
    assert to_cents(Money(amount=Decimal("1.005"), currency="USD")) == 101
    # 1.004 stays 1.00 -> 100 cents.
    assert to_cents(Money(amount=Decimal("1.004"), currency="USD")) == 100
    # Negative half rounds away from zero.
    assert to_cents(Money(amount=Decimal("-1.005"), currency="USD")) == -101
    # Exact cent amounts are untouched.
    assert to_cents(Money(amount=Decimal("12.34"), currency="USD")) == 1234


def test_money_from_cents_takes_any_currency_string() -> None:
    m = money_from_cents(499, "JPY")  # currency is a str, not enum-gated
    assert m.amount == Decimal("4.99")
    assert m.currency == "JPY"
