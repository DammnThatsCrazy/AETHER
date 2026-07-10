"""Gold rollups for card-linked payment rail observability."""
from __future__ import annotations
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any

SPEND_BASES = {"spend"}
TOPUP_BASES = {"topup", "funding"}


def rollup_flows(flows: list[dict[str, Any]]) -> dict[str, Any]:
    by_basis = Counter(str(f.get("basis", "unknown")) for f in flows)
    by_source = Counter(str(f.get("source", "unknown")) for f in flows)
    by_confidence = Counter(str(f.get("confidence", "weak")) for f in flows)
    by_program = Counter(str(f.get("card_program_id") or "unknown") for f in flows)
    by_issuer = Counter(str(f.get("issuer_id") or "unknown") for f in flows)
    by_network = Counter(str(f.get("payment_network") or "unknown") for f in flows)
    by_chain = Counter(str(f.get("chain") or "unknown") for f in flows)
    by_asset = Counter(str(f.get("asset") or "unknown") for f in flows)
    volume_by_basis: dict[str, Decimal] = defaultdict(Decimal)
    users_by_basis: dict[str, set[str]] = defaultdict(set)
    wallets: set[str] = set()
    for f in flows:
        basis = str(f.get("basis", "unknown"))
        amount = Decimal(str(f.get("amount_usd") or "0"))
        volume_by_basis[basis] += amount
        actor = f.get("canonical_entity_id") or f.get("user_id") or f.get("wallet_address_hash") or f.get("id")
        users_by_basis[basis].add(str(actor))
        if f.get("wallet_address_hash"):
            wallets.add(str(f["wallet_address_hash"]))
    return {
        "total_flows": len(flows),
        "card_topup_users": len(set().union(*(users_by_basis[b] for b in TOPUP_BASES)) if TOPUP_BASES else set()),
        "card_spend_users": len(set().union(*(users_by_basis[b] for b in SPEND_BASES)) if SPEND_BASES else set()),
        "card_topup_volume": str(sum((volume_by_basis[b] for b in TOPUP_BASES), Decimal("0"))),
        "card_spend_volume": str(sum((volume_by_basis[b] for b in SPEND_BASES), Decimal("0"))),
        "card_linked_volume": str(sum(volume_by_basis.values(), Decimal("0"))),
        "active_card_wallets": len(wallets),
        "programs_observed": sorted(k for k in by_program if k != "unknown"),
        "issuers_observed": sorted(k for k in by_issuer if k != "unknown"),
        "payment_networks_observed": sorted(by_network),
        "basis_breakdown": dict(by_basis),
        "source_breakdown": dict(by_source),
        "confidence_breakdown": dict(by_confidence),
        "chain_breakdown": dict(by_chain),
        "asset_breakdown": dict(by_asset),
        "volume_by_basis": {k: str(v) for k, v in volume_by_basis.items()},
        "warnings": _warnings(by_basis),
    }


def _warnings(by_basis: Counter[str]) -> list[str]:
    warnings = []
    if by_basis.get("topup") or by_basis.get("funding"):
        warnings.append("Card top-up/funding volume is separated from card spend volume.")
    if by_basis.get("benchmark_only"):
        warnings.append("PaymentScan benchmark-only data is not user-level card spend truth.")
    if by_basis.get("unknown"):
        warnings.append("Unknown basis records require review before activation or attribution use.")
    return warnings
