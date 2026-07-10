from __future__ import annotations
from typing import Any
from services.card_linked_payments.gold import rollup_flows
from services.card_linked_payments.repositories import get_card_linked_repositories

async def get_profile_card_linked_activity(tenant_id: str, entity_id: str, **filters: Any) -> dict[str, Any]:
    repos = get_card_linked_repositories()
    flows = await repos.flows.list_for_entity(tenant_id, entity_id, **filters)
    rollup = rollup_flows(flows)
    story = []
    for flow in flows:
        story.append({
            "id": flow.get("id"),
            "label": f"{flow.get('basis', 'unknown')} via {flow.get('card_program_id') or 'unknown program'}",
            "basis": flow.get("basis", "unknown"),
            "source": flow.get("source"),
            "confidence": flow.get("confidence"),
            "campaign_id": flow.get("campaign_id"),
            "journey_id": flow.get("journey_id"),
            "wallet_address_hash": flow.get("wallet_address_hash"),
            "chain": flow.get("chain"),
            "asset": flow.get("asset"),
            "amount_usd": flow.get("amount_usd"),
            "evidence_refs": flow.get("evidence_refs", []),
        })
    return {
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "surface": "Profile360 → Economic Activity → Payment Rails → Card-linked Activity",
        "filters_supported": ["card_program", "issuer_id", "payment_network", "source", "basis", "rail", "volume_min", "volume_max", "chain", "asset_currency", "campaign_id", "journey_id", "session_id", "device_id", "confidence", "region_policy"],
        "rollup": rollup,
        "flows": flows,
        "story": story,
        "provenance_visible": True,
    }
