from scripts.validate_stripe import _price_contract_errors


def _valid_price() -> dict[str, object]:
    return {
        "active": True,
        "livemode": False,
        "product": "prod_test",
        "currency": "usd",
        "unit_amount": 29900,
        "recurring": {"interval": "month", "interval_count": 1},
    }


def test_self_service_price_contract_accepts_subscription_price() -> None:
    assert _price_contract_errors(
        _valid_price(),
        expected_product_id="prod_test",
        expected_unit_amount=29900,
        expected_livemode=False,
    ) == []


def test_self_service_price_contract_rejects_wrong_product_amount_and_shape() -> None:
    price = _valid_price()
    price.update(
        {
            "product": "prod_wrong",
            "currency": "eur",
            "unit_amount": 1999,
            "recurring": None,
            "livemode": True,
        }
    )
    errors = _price_contract_errors(
        price,
        expected_product_id="prod_test",
        expected_unit_amount=29900,
        expected_livemode=False,
    )
    assert "price mode does not match the configured Stripe key" in errors
    assert "price is assigned to the wrong Stripe product" in errors
    assert "currency must be USD" in errors
    assert "unit amount must be 29900 cents" in errors
    assert "price must be recurring for subscription Checkout" in errors


def test_self_service_price_contract_rejects_non_monthly_recurring_price() -> None:
    price = _valid_price()
    price["recurring"] = {"interval": "year", "interval_count": 2}
    errors = _price_contract_errors(
        price,
        expected_product_id="prod_test",
        expected_unit_amount=29900,
        expected_livemode=False,
    )
    assert "recurring interval must be monthly" in errors
    assert "recurring interval_count must be 1" in errors
