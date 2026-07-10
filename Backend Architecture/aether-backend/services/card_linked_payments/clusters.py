from __future__ import annotations
from collections import defaultdict
from typing import Any

CARD_LINKED_CLUSTER_TYPES = [
    "RedotPay card users", "KAST card users", "Gnosis card users", "MetaMask card users",
    "USDC card top-up users", "USDT card top-up users", "Base card-funding users",
    "High-volume card-linked users", "Repeat card-spend users", "Campaign-converted card users",
    "Issuer exposure clusters", "Suspicious top-up/refund loop clusters", "Agent-influenced card activity clusters",
]

def generate_card_linked_clusters(flows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, set[str]] = defaultdict(set)
    for f in flows:
        member = str(f.get("canonical_entity_id") or f.get("user_id") or f.get("wallet_address_hash") or f.get("id"))
        program = str(f.get("card_program_id") or "")
        asset = str(f.get("asset") or "")
        chain = str(f.get("chain") or "")
        issuer = str(f.get("issuer_id") or "")
        basis = str(f.get("basis") or "unknown")
        if program: groups[f"{program} card users"].add(member)
        if asset and basis in {"topup", "funding"}: groups[f"{asset} card top-up users"].add(member)
        if chain == "base" and basis in {"topup", "funding"}: groups["Base card-funding users"].add(member)
        if issuer: groups[f"{issuer} issuer exposure"].add(member)
        if basis == "spend": groups["Repeat card-spend users"].add(member)
        if f.get("campaign_id"): groups["Campaign-converted card users"].add(member)
        if f.get("agent_id"): groups["Agent-influenced card activity clusters"].add(member)
    return [{"cluster_id": f"card_linked:{name.lower().replace(' ', '_')}", "name": name, "cluster_type": "card_linked_behavior", "members": sorted(members), "member_count": len(members), "review_only": True} for name, members in sorted(groups.items())]
