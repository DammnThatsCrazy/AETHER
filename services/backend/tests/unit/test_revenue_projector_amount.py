"""Regression: ``silver_revenue_facts.amount`` reads the canonical money field.

On the staging stack an ``order_completed`` event carrying ``revenue: 10``
projected ``silver_revenue_facts.amount = 0``: ``RevenueProjector`` only looked
at ``amount``/``total``/``value``, so the canonical order field ``revenue``
(``packages/shared/ecommerce-types.ts`` ``Order.revenue``, the web SDK's
``order_completed`` payload, and the key ``ConversionProjector`` already reads
for ``canonical_conversions.gross_value``) fell through to the legacy
``0.0`` collapse — and, with the exact-money flag on, to a ``None`` amount.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

import services.silver.projectors.revenue_projector as revenue_mod
from services.silver.projectors.conversion_projector import ConversionProjector
from services.silver.projectors.revenue_projector import RevenueProjector
from services.silver.writer import _coerce_value
from shared.backend_interpretation.money import revenue_exact_money


def _event(event_type: str, properties: dict) -> dict:
    return {
        "type": event_type,
        "messageId": "5b0c1d2e-3f40-4a5b-8c6d-7e8f9a0b1c2d",
        "timestamp": "2026-09-24T17:37:19.604646+00:00",
        "userId": "user_1",
        "context": {"tenantId": "tenant_1"},
        "properties": properties,
    }


def _row(event_type: str, properties: dict) -> dict:
    return RevenueProjector().project(_event(event_type, properties)).rows[0]


@pytest.fixture
def exact_money_off(monkeypatch):
    monkeypatch.setattr(
        revenue_mod, "revenue_exact_money",
        lambda props: revenue_exact_money(props, enabled=False),
    )


@pytest.fixture
def exact_money_on(monkeypatch):
    monkeypatch.setattr(
        revenue_mod, "revenue_exact_money",
        lambda props: revenue_exact_money(props, enabled=True),
    )


def test_order_completed_revenue_populates_amount_and_currency(exact_money_off):
    row = _row("order_completed", {"orderId": "o_1", "revenue": 10, "currency": "EUR"})

    assert row["amount"] == 10.0
    assert row["currency"] == "EUR"
    # What the Silver writer binds for the NUMERIC(20,4) column.
    assert _coerce_value("silver_revenue_facts", "amount", "numeric", row["amount"]) == Decimal("10.0")


def test_revenue_amount_matches_canonical_conversion_gross_value(exact_money_off):
    event = _event("order_completed", {"orderId": "o_2", "revenue": "42.50"})

    revenue_row = RevenueProjector().project(event).rows[0]
    conversion_row = ConversionProjector().project(event).rows[0]

    assert Decimal(str(revenue_row["amount"])) == Decimal(conversion_row["gross_value"])


@pytest.mark.parametrize(
    ("properties", "expected"),
    [
        ({"total": 19.99}, 19.99),       # mobile SDK trackPurchase
        ({"amount": 5}, 5.0),            # payment / invoice events
        ({"value": 7.5}, 7.5),
        ({"revenue": 10, "total": 99}, 10.0),  # canonical key wins
    ],
)
def test_other_money_keys_still_resolve(exact_money_off, properties, expected):
    assert _row("order_completed", properties)["amount"] == expected


def test_missing_amount_keeps_legacy_collapse_when_flag_off(exact_money_off):
    row = _row("order_completed", {"orderId": "o_3"})
    assert row["amount"] == 0.0
    assert row["currency"] == "USD"


def test_exact_money_path_reads_revenue_too(exact_money_on):
    row = _row("order_completed", {"orderId": "o_4", "revenue": "10.25", "currency": "GBP"})

    assert row["amount"] == 10.25
    assert row["currency"] == "GBP"
    assert Decimal(row["amount_exact"]) == Decimal("10.25")
    assert row["currency_exact"] == "GBP"


def test_subscription_mrr_uses_the_same_amount(exact_money_off):
    row = _row("subscription_started", {"revenue": 30})
    assert row["amount"] == 30.0
    assert row["mrr_delta"] == 30.0
    assert row["arr_delta"] == 360.0
