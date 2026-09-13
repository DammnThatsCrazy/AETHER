"""TVL (total value locked / total value of positions) views — prompt §4.8.

Pure computation over a list of position records. Every USD total is produced
through ``price_sources.price`` + ``rollups.safe_rollup`` so that:

  - unknown / unpriced positions are ``None``, never ``0``;
  - testnet and spam positions never enter a trusted total;
  - mixed native currencies are only summed via their USD valuation.

A position record looks like::

    {
        "amount": "1.5", "currency"|"asset_id": "ETH",
        "chain": "ethereum", "network": "mainnet",
        "ownership_relationship": "owned", "metric_kind": "balance",
        "borrowed"|"is_borrowed": bool,          # a liability (debt) leg
        "is_lp": bool, "lp_underlying": ["ETH", "USDC"],
        "wrapped_of"|"is_wrapped": "ETH"|bool,   # wrapper over an underlying
        "spam": bool, "testnet": bool,
    }

Gross TVL is the USD sum of asset (non-liability) positions. Net TVL subtracts
the USD of borrowed/liability positions. Double counting from wrapped tokens and
LP tokens is prevented by :func:`dedupe_wrapped_and_lp` (see its docstring).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Optional

from services.value.rollups import safe_rollup

_CURRENCY_KEYS = ("currency", "asset_symbol", "asset_id", "asset")


def _currency(rec: dict) -> Optional[str]:
    for k in _CURRENCY_KEYS:
        v = rec.get(k)
        if v is not None and v != "":
            return str(v)
    return None


def _is_liability(pos: dict) -> bool:
    return bool(
        pos.get("metric_kind") == "liability"
        or pos.get("is_borrowed")
        or pos.get("borrowed")
    )


def _sub(a: Optional[str], b: Optional[str]) -> Optional[str]:
    if a is None:
        return None
    return format(Decimal(a) - Decimal(b or "0"), "f")


def gross_tvl(positions: Iterable[dict]) -> dict:
    """Total USD of all included (non-liability) positions.

    Testnet and spam positions are excluded by ``safe_rollup``. Returns a
    RollupResult-like dict (``total_usd`` is ``None`` when nothing is priced)
    augmented with ``by_asset``.
    """
    positions = list(positions)
    assets = [p for p in positions if not _is_liability(p)]
    result = safe_rollup(assets, metric_kind="balance")
    result["by_asset"] = by_asset(assets)
    return result


def net_tvl(positions: Iterable[dict]) -> dict:
    """Gross TVL minus borrowed/liability positions.

    ``net_usd`` is ``None`` when gross is unavailable. Borrowed USD is the USD
    magnitude of liability legs (priced as balances), or ``None`` if unpriced.
    """
    positions = list(positions)
    gross = gross_tvl(positions)
    gross_usd = gross["total_usd"]

    liabilities = [p for p in positions if _is_liability(p)]
    borrowed = safe_rollup(liabilities, metric_kind="balance")
    borrowed_usd = borrowed["total_usd"]

    # Liabilities exist but are unpriced: net TVL is UNKNOWN, not gross. Coercing
    # an unpriced borrowed leg to 0 would inflate net TVL.
    if liabilities and borrowed_usd is None:
        net_usd: Optional[str] = None
        rollup_status = "partial"
    else:
        net_usd = _sub(gross_usd, borrowed_usd)
        rollup_status = gross["rollup_status"]

    return {
        "gross_usd": gross_usd,
        "borrowed_usd": borrowed_usd,
        "net_usd": net_usd,
        "rollup_status": rollup_status,
        "unpriced_count": gross["unpriced_count"] + borrowed["unpriced_count"],
        "excluded_count": gross["excluded_count"] + borrowed["excluded_count"],
    }


def by_chain(positions: Iterable[dict]) -> dict:
    """Map chain -> USD total (``None`` when a chain's positions are unpriced)."""
    groups: dict[str, list] = {}
    for p in positions:
        if _is_liability(p):
            continue
        groups.setdefault(str(p.get("chain") or "unknown"), []).append(p)
    return {
        chain: safe_rollup(group, metric_kind="balance")["total_usd"]
        for chain, group in groups.items()
    }


def by_asset(positions: Iterable[dict]) -> dict:
    """Map asset symbol -> USD total (``None`` when that asset is unpriced)."""
    groups: dict[str, list] = {}
    for p in positions:
        if _is_liability(p):
            continue
        groups.setdefault(_currency(p) or "unknown", []).append(p)
    return {
        asset: safe_rollup(group, metric_kind="balance")["total_usd"]
        for asset, group in groups.items()
    }


def dedupe_wrapped_and_lp(positions: Iterable[dict]) -> list:
    """Drop positions that would double-count value already held elsewhere.

    Rule (order-preserving, non-mutating):

    1. A *wrapped* position (``is_wrapped`` true or ``wrapped_of`` set) is dropped
       when its ``wrapped_of`` underlying symbol is also present as a plain
       (non-wrapped, non-LP) position — the underlying is kept, the wrapper is
       redundant. If the underlying is absent, the wrapper is kept (it represents
       real value not otherwise held).
    2. An *LP* position (``is_lp`` true) is dropped when it declares
       ``lp_underlying`` and EVERY underlying symbol is present among the
       remaining non-LP positions — the LP is decomposed into its legs, so
       counting the LP token too would double count. If not all underlyings are
       present, the LP token is kept.
    """
    positions = list(positions)

    def _is_wrapped(p: dict) -> bool:
        return bool(p.get("is_wrapped") or p.get("wrapped_of"))

    plain_symbols = {
        _currency(p)
        for p in positions
        if not _is_wrapped(p) and not p.get("is_lp")
    }
    plain_symbols.discard(None)

    non_lp_symbols = {_currency(p) for p in positions if not p.get("is_lp")}
    non_lp_symbols.discard(None)

    kept: list = []
    for p in positions:
        if _is_wrapped(p):
            underlying = p.get("wrapped_of")
            if underlying is not None and str(underlying) in plain_symbols:
                continue  # underlying already held -> drop the wrapper
        if p.get("is_lp"):
            legs = [str(s) for s in (p.get("lp_underlying") or [])]
            if legs and all(leg in non_lp_symbols for leg in legs):
                continue  # decomposed into its legs -> drop the LP token
        kept.append(p)
    return kept
