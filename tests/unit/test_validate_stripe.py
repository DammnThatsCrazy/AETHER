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


def test_annual_price_contract_requires_cents_and_a_yearly_interval() -> None:
    from scripts.validate_stripe import OPTIONAL_ANNUAL_PRICE_CONTRACTS

    beta = OPTIONAL_ANNUAL_PRICE_CONTRACTS["Beta annual"]
    yearly = _valid_price()
    yearly.update({"product": beta["product_id"], "unit_amount": 305000, "recurring": {"interval": "year", "interval_count": 1}})
    assert _price_contract_errors(
        yearly,
        expected_product_id=beta["product_id"],
        expected_unit_amount=beta["unit_amount"],
        expected_livemode=False,
        expected_interval="year",
    ) == []

    # A yearly price entered in dollars ($30.50 instead of $3,050) and a
    # monthly price in the annual slot are both rejected.
    wrong = dict(yearly, unit_amount=3050, recurring={"interval": "month", "interval_count": 1})
    errors = _price_contract_errors(
        wrong,
        expected_product_id=beta["product_id"],
        expected_unit_amount=beta["unit_amount"],
        expected_livemode=False,
        expected_interval="year",
    )
    assert "unit amount must be 305000 cents" in errors
    assert "recurring interval must be yearly" in errors
