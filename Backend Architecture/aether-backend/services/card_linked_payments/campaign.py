from __future__ import annotations
from typing import Any
from services.card_linked_payments.gold import rollup_flows
from services.card_linked_payments.repositories import get_card_linked_repositories

async def get_campaign_card_linked_outcomes(tenant_id: str, campaign_id: str, **filters: Any) -> dict[str, Any]:
    flows = await get_card_linked_repositories().flows.list_for_campaign(tenant_id, campaign_id, **filters)
    rollup = rollup_flows(flows)
    return {
        "tenant_id": tenant_id,
        "campaign_id": campaign_id,
        "attribution_basis": "direct" if flows else "insufficient_evidence",
        "causality_warning": "Card-linked outcomes are attributed observations; correlation is not causality unless direct evidence exists.",
        **rollup,
        "time_to_first_card_event": flows[0].get("occurred_at") if flows else None,
        "repeat_activity_7d": 0,
        "repeat_activity_30d": 0,
    }
