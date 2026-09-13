"""Ownership + rollup-inclusion rules.

Decides whether a value belongs in a TRUSTED owned USD rollup:
  - liabilities are never counted as assets;
  - testnet assets are excluded from production rollups by default;
  - spam / untrusted / scam assets are excluded by default;
  - counterparty / external / observed relationships are excluded from an OWNED
    portfolio (they are still observed, just not owned liquidity).
"""
from __future__ import annotations

from typing import Optional

# Relationships that count toward owned portfolio value.
OWNED_RELATIONSHIPS = frozenset({"owned", "controlled"})
# Relationships that are observed but excluded from an owned portfolio rollup.
NON_PORTFOLIO_RELATIONSHIPS = frozenset({
    "counterparty", "external", "observed", "inferred",
})
_TESTNET_MARKERS = ("testnet", "goerli", "sepolia", "ropsten", "rinkeby",
                    "mumbai", "devnet", "fuji", "holesky")


def is_testnet(native: dict) -> bool:
    hay = " ".join(str(native.get(k) or "") for k in ("chain", "network")).lower()
    if native.get("testnet") is True:
        return True
    return any(m in hay for m in _TESTNET_MARKERS)


def is_spam(native: dict) -> bool:
    return bool(native.get("spam") or native.get("untrusted") or native.get("scam"))


def rollup_inclusion(
    native: dict,
    *,
    ownership_relationship: str = "owned",
    metric_kind: str = "balance",
    production: bool = True,
) -> tuple[bool, Optional[str]]:
    """Return (include_in_owned_rollup, exclusion_reason)."""
    if metric_kind == "liability":
        return False, "liability_not_asset"
    if production and is_testnet(native):
        return False, "testnet_excluded"
    if is_spam(native):
        return False, "spam_or_untrusted_excluded"
    if ownership_relationship in NON_PORTFOLIO_RELATIONSHIPS:
        return False, f"ownership_{ownership_relationship}_excluded"
    return True, None
