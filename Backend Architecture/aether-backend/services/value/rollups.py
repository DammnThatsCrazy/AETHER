"""Safe value rollups — never a single mixed-currency scalar, unknown != 0.

A rollup groups values by native currency, sums a trusted total across only the
values that carry a trustworthy valuation in the reporting asset, and records
why anything was excluded. Totals are keyed by reporting asset (canonical asset
id); ``fiat:USD`` is the default reporting asset and produces output that is
byte-identical to the USD-first contract. If no value can be priced in the
reporting asset, the reporting total is None (not 0). A
single-native-currency raw sum is exposed separately as an unambiguous
convenience (deprecated); a mixed-currency raw sum is never produced.

Financial-normalization additivity: a caller may pass a ``reporting_asset_id``
(and, for non-USD reporting assets, an ``amount_in_reporting_asset`` resolver)
to receive a ``reporting_totals`` envelope keyed by that asset. Conversion is
never guessed — a record whose amount in the reporting asset cannot be stated
trustworthily is counted as unpriced-for-reporting and contributes nothing.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from decimal import Decimal
from typing import Optional

from services.value.models import to_decimal
from services.value.valuation import value_of

# Canonical reporting asset used when the caller gives no reporting_asset_id
# (spelling mirrors services/valuation/price_providers.USD_ASSET_ID).
USD_ASSET_ID = "fiat:USD"

# Optional per-record resolver: returns the record's amount denominated in the
# reporting asset (already trustworthy / ownership-vetted by the caller), or
# None when no trustworthy valuation in that asset exists.
ReportingValuator = Callable[[dict], Optional[Decimal]]


def _dstr(d: Optional[Decimal]) -> Optional[str]:
    return None if d is None else format(d, "f")


def _coverage_percentage(priced: int, unpriced: int) -> Optional[float]:
    """Share of amount-bearing, ownership-included records with a trusted
    reporting valuation (None when there is nothing to cover)."""
    total = priced + unpriced
    if total == 0:
        return None
    return round(100.0 * priced / total, 1)


def _reporting_status(
    priced: int, unpriced: int, excluded: int, amount_bearing: int,
) -> str:
    """Mirror the USD rollup_status rule for one reporting asset.

    ``amount_bearing`` is the count of records that carry a parseable native
    amount and passed ownership rules (testnet / spam / liability /
    counterparty never count as value-bearing).
    """
    if amount_bearing == 0 and excluded == 0:
        return "unavailable"
    if priced == 0:
        return "unavailable"
    if unpriced == 0 and priced == amount_bearing:
        return "complete"
    return "partial"


def safe_rollup(
    records: Iterable[dict],
    *,
    metric_kind: str = "flow",
    reporting_asset_id: str = USD_ASSET_ID,
    amount_in_reporting_asset: Optional[ReportingValuator] = None,
    include_lineage: bool = False,
) -> dict:
    """Roll up an iterable of raw value records safely.

    Returns a dict matching packages/shared/value.ts RollupResult, plus
    `native_currency` / `native_total` (the unambiguous single-currency raw sum,
    or None when currencies are mixed). The top-level USD envelope is unchanged
    from the USD-first contract.

    When a non-default reporting context is requested (``reporting_asset_id``
    other than ``fiat:USD`` or an explicit ``amount_in_reporting_asset``
    resolver), an additive ``reporting_totals`` block is included, keyed by the
    reporting asset id. For ``fiat:USD`` the reporting total equals the trusted
    USD total. Conversion to another reporting asset is never guessed: the
    caller supplies ``amount_in_reporting_asset`` (e.g. backed by the valuation
    engine) or records simply count as unpriced-for-reporting.
    """
    by_currency: dict[str, dict] = {}
    included = 0          # records with a parseable native amount
    priced = 0            # records counted into the USD total (priced + eligible)
    unpriced = 0          # records with an amount but no trusted USD value
    excluded = 0          # records with no amount, or priced-but-rollup-ineligible
    total_usd = Decimal(0)
    any_usd = False

    # Reporting-asset view (only computed when a non-default reporting context
    # is requested). Reuses one value_of pass; never re-prices.
    want_reporting = reporting_asset_id != USD_ASSET_ID or amount_in_reporting_asset is not None
    reporting_valuations: list[tuple[Decimal, str, object]] = []  # (reporting amount, native cur, record)
    reporting_priced = 0
    reporting_unpriced = 0
    reporting_excluded = 0
    reporting_total = Decimal(0)
    any_reporting = False
    reporting_included = 0
    lineage: list[dict] = [] if include_lineage else None  # type: ignore[assignment]

    for record in records:
        v = value_of(record, metric_kind=metric_kind)
        amount = to_decimal(v["native"]["amount"])
        if amount is None:
            excluded += 1
            if want_reporting:
                reporting_excluded += 1
            continue
        included += 1
        currency = v["native"]["currency"] or "unknown"
        usd = to_decimal(v["valuation"]["usd_value"])
        eligible = v["status"].get("include_in_rollups", usd is not None)

        bucket = by_currency.setdefault(
            currency, {"amount": Decimal(0), "usd": Decimal(0), "count": 0, "priced": True}
        )
        bucket["amount"] += amount
        bucket["count"] += 1
        if usd is not None and eligible:
            bucket["usd"] += usd
            total_usd += usd
            any_usd = True
            priced += 1
        elif usd is None:
            bucket["priced"] = False
            unpriced += 1
        else:
            # Priced but ownership/policy-excluded (testnet / spam / liability /
            # counterparty) — never enters the trusted USD total.
            bucket["priced"] = False
            excluded += 1

        if not want_reporting:
            continue

        # Ownership rules gate the reporting view identically to the USD view:
        # include_in_rollups means ownership-passed AND priced; exclusion_reason
        # == "unpriced" means ownership-passed but unpriced (in USD) — still a
        # countable, potentially priceable-in-reporting record.
        ownership_included = eligible or v["status"].get("exclusion_reason") == "unpriced"
        if not ownership_included:
            reporting_excluded += 1
            continue

        reporting_included += 1
        reporting_amount = _amount_in_reporting_asset(
            record, reporting_asset_id, usd if eligible else None,
            amount_in_reporting_asset,
        )
        if reporting_amount is None:
            reporting_unpriced += 1
            continue
        reporting_priced += 1
        reporting_total += reporting_amount
        any_reporting = True
        if include_lineage:
            lineage.append({
                "source_record_id": (
                    record.get("source_record_id") or record.get("source_id") or record.get("id")
                ),
                "native_amount": _dstr(amount),
                "native_currency": currency,
                "reporting_amount": _dstr(reporting_amount),
                "reporting_asset_id": reporting_asset_id,
            })

    if included == 0 and excluded == 0:
        rollup_status = "unavailable"
    elif priced == 0:
        rollup_status = "unavailable"
    elif unpriced == 0 and priced == included:
        rollup_status = "complete"
    else:
        rollup_status = "partial"

    # Single unambiguous native currency => expose a raw sum; otherwise None.
    native_currency: Optional[str] = None
    native_total: Optional[str] = None
    if len(by_currency) == 1:
        native_currency = next(iter(by_currency))
        native_total = _dstr(by_currency[native_currency]["amount"])

    result: dict = {
        "total_usd": _dstr(total_usd) if any_usd else None,
        "by_native_currency": {
            cur: {
                "amount": _dstr(b["amount"]),
                "usd_value": _dstr(b["usd"]) if b["priced"] else None,
                "count": b["count"],
                "priced": b["priced"],
            }
            for cur, b in by_currency.items()
        },
        "unpriced_count": unpriced,
        "stale_count": 0,
        "excluded_count": excluded,
        "rollup_status": rollup_status,
        "native_currency": native_currency,
        "native_total": native_total,
    }

    if want_reporting:
        reporting_status = _reporting_status(
            reporting_priced, reporting_unpriced, reporting_excluded, reporting_included,
        )
        result["reporting_totals"] = {
            reporting_asset_id: {
                "total": _dstr(reporting_total) if any_reporting else None,
                "priced_count": reporting_priced,
                "unpriced_count": reporting_unpriced,
                "excluded_count": reporting_excluded,
                "stale_count": 0,
                "coverage_percentage": _coverage_percentage(
                    reporting_priced, reporting_unpriced,
                ),
                "rollup_status": reporting_status,
            }
        }
    if include_lineage:
        result["value_lineage"] = lineage

    return result


def _amount_in_reporting_asset(
    record: dict,
    reporting_asset_id: str,
    usd_if_eligible: Optional[Decimal],
    amount_in_reporting_asset: Optional[ReportingValuator],
) -> Optional[Decimal]:
    """Trustworthy amount of ``record`` in the reporting asset, or None.

    USD reporting reuses the record's vetted USD valuation. Any other reporting
    asset requires an explicit caller resolver; a conversion is never guessed,
    so an absent resolver means "no trustworthy valuation in that asset".
    """
    if amount_in_reporting_asset is not None:
        return to_decimal(amount_in_reporting_asset(record))
    if reporting_asset_id == USD_ASSET_ID:
        return usd_if_eligible
    return None
