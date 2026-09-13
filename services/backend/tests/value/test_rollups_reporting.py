"""Reporting-asset-keyed safe_rollup generalization (financial normalization).

The USD-first envelope is byte-identical when no reporting context is given; a
``reporting_asset_id`` / ``amount_in_reporting_asset`` resolver adds a
``reporting_totals`` block. Conversion to a non-USD reporting asset is never
guessed — a record without a trustworthy amount in the reporting asset is
counted as unpriced-for-reporting and contributes nothing (unknown != 0).
"""
from decimal import Decimal

from services.value.rollups import safe_rollup


def _eth_resolver(record):
    """Resolver that can only denominate native-ETH records in the reporting asset."""
    return Decimal(record["amount"]) if record.get("currency") == "ETH" else None


def test_default_output_is_byte_identical_usd_first():
    """No reporting context => exact USD-first envelope, no additive keys."""
    records = [
        {"amount": "1", "currency": "ETH", "amount_usd": "3000"},
        {"amount": "5", "currency": "UNKNOWNTOK"},
        {"amount": "2", "currency": "BTC", "testnet": True, "amount_usd": "60000"},
    ]
    result = safe_rollup(records)

    assert result == {
        "total_usd": "3000",            # only the priced, ownership-included record
        "by_native_currency": {
            "ETH": {"amount": "1", "usd_value": "3000", "count": 1, "priced": True},
            "UNKNOWNTOK": {"amount": "5", "usd_value": None, "count": 1, "priced": False},
            "BTC": {"amount": "2", "usd_value": None, "count": 1, "priced": False},
        },
        "unpriced_count": 1,
        "stale_count": 0,
        "excluded_count": 1,
        "rollup_status": "partial",
        "native_currency": None,        # mixed native currencies => no raw scalar
        "native_total": None,
    }
    assert "reporting_totals" not in result
    assert "value_lineage" not in result


def test_non_usd_reporting_with_resolver_sums_only_denominated_records():
    records = [
        {"amount": "2", "currency": "ETH", "amount_usd": "6000", "id": "rec-a"},
        {"amount": "5", "currency": "UNKNOWNTOK", "id": "rec-b"},
        {"amount": "3", "currency": "BTC", "testnet": True, "amount_usd": "90000", "id": "rec-c"},
    ]
    result = safe_rollup(
        records,
        reporting_asset_id="crypto:ETH",
        amount_in_reporting_asset=_eth_resolver,
    )

    # The USD-first top-level envelope is still present and correct.
    assert result["total_usd"] == "6000"
    assert result["rollup_status"] == "partial"

    rt = result["reporting_totals"]["crypto:ETH"]
    assert rt["total"] == "2"                    # only native-ETH denominated
    assert rt["priced_count"] == 1
    assert rt["unpriced_count"] == 1             # UNKNOWNTOK has no ETH amount
    assert rt["excluded_count"] == 1             # testnet BTC never enters a total
    assert rt["coverage_percentage"] == 50.0
    assert rt["rollup_status"] == "partial"


def test_non_usd_reporting_without_resolver_never_guesses():
    """Without a resolver, a USD valuation is never misread as an ETH total."""
    result = safe_rollup(
        [{"amount": "2", "currency": "ETH", "amount_usd": "6000"}],
        reporting_asset_id="crypto:ETH",
    )

    assert result["total_usd"] == "6000"         # USD total intact
    rt = result["reporting_totals"]["crypto:ETH"]
    assert rt["total"] is None                   # never "0", never a guessed 6000 ETH
    assert rt["priced_count"] == 0
    assert rt["unpriced_count"] == 1
    assert rt["coverage_percentage"] == 0.0
    assert rt["rollup_status"] == "unavailable"


def test_usd_reporting_envelope_mirrors_trusted_total():
    result = safe_rollup(
        [{"amount": "1", "currency": "ETH", "amount_usd": "3000", "id": "a"}],
        reporting_asset_id="fiat:USD",
        amount_in_reporting_asset=lambda r: Decimal(r["amount_usd"]),
    )

    rt = result["reporting_totals"]["fiat:USD"]
    assert rt["total"] == "3000"
    assert rt["priced_count"] == 1
    assert rt["unpriced_count"] == 0
    assert rt["coverage_percentage"] == 100.0
    assert rt["rollup_status"] == "complete"


def test_lineage_opt_in_lists_priced_sources_only():
    result = safe_rollup(
        [
            {"amount": "1", "currency": "ETH", "amount_usd": "3000", "source_record_id": "src-1"},
            {"amount": "5", "currency": "UNKNOWNTOK", "source_record_id": "src-2"},
        ],
        reporting_asset_id="crypto:ETH",
        amount_in_reporting_asset=_eth_resolver,
        include_lineage=True,
    )

    assert result["value_lineage"] == [
        {
            "source_record_id": "src-1",
            "native_amount": "1",
            "native_currency": "ETH",
            "reporting_amount": "1",
            "reporting_asset_id": "crypto:ETH",
        }
    ]


def test_all_unpriced_for_reporting_total_is_none_never_zero():
    result = safe_rollup(
        [{"amount": "10", "currency": "UNKNOWNTOK"}],
        reporting_asset_id="crypto:ETH",
        amount_in_reporting_asset=_eth_resolver,
    )

    rt = result["reporting_totals"]["crypto:ETH"]
    assert rt["total"] is None
    assert rt["total"] != 0
    assert rt["priced_count"] == 0
    assert rt["rollup_status"] == "unavailable"
