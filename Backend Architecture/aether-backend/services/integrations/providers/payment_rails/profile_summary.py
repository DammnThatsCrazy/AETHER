"""Profile360 economic-flow extension — funding-session rollups per entity.

Read-only aggregation of observed funding sessions attributed to an entity
(as user, agent, or org). Amounts are never summed across currencies; the
rollup reports counts per provider/rail/status/reconciliation state plus
per-currency native totals with explicit currency labels.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from services.integrations.providers.payment_rails.repository import (
    get_payment_rails_repositories,
)


async def get_payment_rails_profile_summary(tenant_id: str, entity_id: str) -> dict[str, Any]:
    repos = get_payment_rails_repositories()
    sessions = await repos.sessions.list_for_tenant(tenant_id, limit=500)
    attributed = [
        s for s in sessions
        if entity_id in (s.get("user_id"), s.get("agent_id"), s.get("org_id"))
    ]

    by_provider: dict[str, int] = defaultdict(int)
    by_rail: dict[str, int] = defaultdict(int)
    by_status: dict[str, int] = defaultdict(int)
    by_reconciliation: dict[str, int] = defaultdict(int)
    # Native totals keyed by currency/asset — never merged into one scalar.
    completed_native_totals: dict[str, float] = defaultdict(float)

    for s in attributed:
        by_provider[s.get("provider", "unknown")] += 1
        by_rail[s.get("rail", "unknown")] += 1
        by_status[s.get("status", "unresolved")] += 1
        by_reconciliation[s.get("reconciliation_state", "sdk_only")] += 1
        if s.get("status") in ("completed", "refunded"):
            currency = s.get("destination_asset") or s.get("fiat_currency")
            amount = s.get("destination_amount") or s.get("source_amount")
            if currency and amount is not None:
                try:
                    completed_native_totals[str(currency)] += float(amount)
                except (TypeError, ValueError):
                    pass

    recent = sorted(attributed, key=lambda s: s.get("occurred_at") or "", reverse=True)[:10]
    return {
        "entity_id": entity_id,
        "session_count": len(attributed),
        "by_provider": dict(by_provider),
        "by_rail": dict(by_rail),
        "by_status": dict(by_status),
        "by_reconciliation_state": dict(by_reconciliation),
        "completed_native_totals": {
            currency: f"{total:.8f}".rstrip("0").rstrip(".")
            for currency, total in completed_native_totals.items()
        },
        "recent_sessions": [
            {
                "id": s.get("id"),
                "provider": s.get("provider"),
                "flow_type": s.get("flow_type"),
                "rail": s.get("rail"),
                "status": s.get("status"),
                "reconciliation_state": s.get("reconciliation_state"),
                "destination_asset": s.get("destination_asset"),
                "destination_amount": s.get("destination_amount"),
                "fiat_currency": s.get("fiat_currency"),
                "source_amount": s.get("source_amount"),
                "occurred_at": s.get("occurred_at"),
            }
            for s in recent
        ],
    }
