"""Portfolio classification + USD subtotals — prompt §4.14.

Pure computation. Classifies each holding into a bucket and produces per-bucket
USD subtotals through ``rollups.safe_rollup`` (so unpriced => ``None`` never
``0``, testnet/spam excluded, mixed currencies only summed via USD).

Testnet, spam, and counterparty/external/observed/inferred holdings are excluded
from OWNED totals (counted in ``excluded_count``). Liabilities are never counted
as assets; ``net_worth_usd = total_portfolio_usd - liabilities_usd``.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Optional

from services.value import ownership_rules, price_sources
from services.value.models import is_usd
from services.value.rollups import safe_rollup

_CURRENCY_KEYS = ("currency", "asset_symbol", "asset_id", "asset")
_FX_FIAT = frozenset({"EUR", "GBP", "JPY", "CAD", "AUD"})
_CASH_ACCOUNTS = frozenset({"cash", "checking", "savings", "depository"})
_BROKERAGE_ACCOUNTS = frozenset({"brokerage", "investment", "securities"})


def _currency(rec: dict) -> Optional[str]:
    for k in _CURRENCY_KEYS:
        v = rec.get(k)
        if v is not None and v != "":
            return str(v)
    return None


def _is_liability(h: dict) -> bool:
    return bool(
        h.get("metric_kind") == "liability"
        or h.get("is_liability")
        or h.get("liability")
    )


def _classify(h: dict) -> str:
    """Return the asset bucket name for a (non-excluded, non-liability) holding."""
    if h.get("locked") or h.get("staked"):
        return "locked_staked"
    if h.get("claimable") or h.get("is_claimable") or h.get("reward"):
        return "claimable_rewards"
    cur = _currency(h)
    if price_sources.is_stablecoin(cur):
        return "stablecoin"
    account_type = str(h.get("account_type") or "").lower()
    if is_usd(cur) or (cur is not None and cur.upper() in _FX_FIAT) or account_type in _CASH_ACCOUNTS:
        return "cash"
    if account_type in _BROKERAGE_ACCOUNTS or str(h.get("asset_class") or "").lower() == "equity":
        return "brokerage"
    return "volatile_crypto"


def _total_usd(records: list) -> tuple[Optional[str], int, int]:
    roll = safe_rollup(records, metric_kind="balance")
    return roll["total_usd"], roll["unpriced_count"], roll["excluded_count"]


def _sum_optional(values: Iterable[Optional[str]]) -> Optional[str]:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return format(sum((Decimal(v) for v in present), Decimal(0)), "f")


def _grouped_totals(records: list, keyfn) -> dict:
    groups: dict[str, list] = {}
    for r in records:
        groups.setdefault(keyfn(r), []).append(r)
    return {k: safe_rollup(g, metric_kind="balance")["total_usd"] for k, g in groups.items()}


def portfolio(holdings: Iterable[dict]) -> dict:
    """Classify holdings into buckets and return USD subtotals + net worth."""
    buckets: dict[str, list] = {
        "cash": [], "stablecoin": [], "volatile_crypto": [], "brokerage": [],
        "locked_staked": [], "claimable_rewards": [],
    }
    liabilities: list = []
    included: list = []           # owned asset holdings (for by_chain/by_asset)
    excluded_count = 0
    relationships: list[str] = []

    for h in holdings:
        if ownership_rules.is_testnet(h) or ownership_rules.is_spam(h):
            excluded_count += 1
            continue
        relationship = h.get("ownership_relationship") or "owned"
        if relationship in ownership_rules.NON_PORTFOLIO_RELATIONSHIPS:
            excluded_count += 1  # counterparty/external/observed/inferred -> not owned
            continue
        if _is_liability(h):
            liabilities.append(h)
            continue
        relationships.append(relationship)
        included.append(h)
        buckets[_classify(h)].append(h)

    unpriced_count = 0
    bucket_usd: dict[str, Optional[str]] = {}
    for name, recs in buckets.items():
        total, unpriced, excluded = _total_usd(recs)
        bucket_usd[name] = total
        unpriced_count += unpriced
        excluded_count += excluded

    liabilities_usd, liab_unpriced, liab_excluded = _total_usd(liabilities)
    unpriced_count += liab_unpriced
    excluded_count += liab_excluded

    total_portfolio_usd = _sum_optional(bucket_usd.values())
    if total_portfolio_usd is None:
        net_worth_usd: Optional[str] = None
    else:
        net_worth_usd = format(
            Decimal(total_portfolio_usd) - Decimal(liabilities_usd or "0"), "f"
        )

    if not included:
        ownership_confidence = "unknown"
    elif all(r in ownership_rules.OWNED_RELATIONSHIPS for r in relationships):
        ownership_confidence = "high"
    else:
        ownership_confidence = "medium"

    return {
        "cash_usd": bucket_usd["cash"],
        "stablecoin_usd": bucket_usd["stablecoin"],
        "volatile_crypto_usd": bucket_usd["volatile_crypto"],
        "brokerage_usd": bucket_usd["brokerage"],
        "locked_staked_usd": bucket_usd["locked_staked"],
        "claimable_rewards_usd": bucket_usd["claimable_rewards"],
        "liabilities_usd": liabilities_usd,
        "total_portfolio_usd": total_portfolio_usd,
        "net_worth_usd": net_worth_usd,
        "unpriced_count": unpriced_count,
        "stale_count": 0,
        "excluded_count": excluded_count,
        "by_chain": _grouped_totals(included, lambda h: str(h.get("chain") or "unknown")),
        "by_asset": _grouped_totals(included, lambda h: _currency(h) or "unknown"),
        "ownership_confidence": ownership_confidence,
    }
