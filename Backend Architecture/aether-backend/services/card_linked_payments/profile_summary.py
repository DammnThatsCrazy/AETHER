"""Profile360 card-linked activity — entity summary, story, drilldown.

Placement: Profile360 → Economic Activity → Payment Rails → Card-linked
Activity. Every payload separates bases (top-up is never presented as
spend), labels confidence/source/provenance, and renders unknown
issuer/network visibly instead of hiding them.
"""

from __future__ import annotations

from typing import Any

from services.card_linked_payments.gold import entity_economic_activity
from services.card_linked_payments.repositories import get_card_linked_repositories

# Filters supported across Profile360/Campaign360/Graph surfaces.
FILTERABLE_FIELDS = (
    "card_program_id", "issuer_id", "payment_network", "basis", "rail",
    "chain", "asset", "campaign_id", "journey_id", "session_id", "device_id",
    "confidence", "source", "region_policy", "actor_kind",
    "reconciliation_state",
)


def apply_flow_filters(rows: list[dict], filters: dict[str, Any]) -> list[dict]:
    out = rows
    for field in FILTERABLE_FIELDS:
        value = filters.get(field)
        if value is not None and value != "":
            out = [r for r in out if str(r.get(field) or "unknown") == str(value)]
    volume_min = filters.get("volume_min")
    volume_max = filters.get("volume_max")

    def _usd(row: dict) -> float:
        try:
            return float(row.get("amount_usd") or 0)
        except (TypeError, ValueError):
            return 0.0

    if volume_min is not None:
        out = [r for r in out if _usd(r) >= float(volume_min)]
    if volume_max is not None:
        out = [r for r in out if _usd(r) <= float(volume_max)]
    since = filters.get("since")
    until = filters.get("until")
    if since:
        out = [r for r in out if (r.get("occurred_at") or "") >= str(since)]
    if until:
        out = [r for r in out if (r.get("occurred_at") or "") <= str(until)]
    return out


def _attributed_to_entity(rows: list[dict], entity_id: str) -> list[dict]:
    return [r for r in rows if entity_id in (
        r.get("canonical_entity_id"), r.get("user_id"), r.get("agent_id"),
        r.get("org_id"), r.get("wallet_address_hash"),
    )]


def _story(flows: list[dict]) -> list[dict[str, Any]]:
    """Chronological entity story: campaign → provider → wallet funding →
    provider spends. Each step carries basis/source/confidence so the UI
    can never label a top-up as spend."""
    ordered = sorted(flows, key=lambda r: r.get("occurred_at") or "")
    steps: list[dict[str, Any]] = []
    seen_campaigns: set[str] = set()
    seen_programs: set[str] = set()
    for flow in ordered:
        campaign = flow.get("campaign_id")
        if campaign and campaign not in seen_campaigns:
            seen_campaigns.add(campaign)
            steps.append({"kind": "campaign_source", "campaign_id": campaign,
                          "occurred_at": flow.get("occurred_at")})
        program = flow.get("card_program_id")
        if program and program not in seen_programs:
            seen_programs.add(program)
            steps.append({"kind": "card_program_used", "card_program_id": program,
                          "issuer_id": flow.get("issuer_id"),
                          "payment_network": flow.get("payment_network") or "unknown",
                          "occurred_at": flow.get("occurred_at")})
        steps.append({
            "kind": f"card_{flow.get('basis', 'unknown')}",
            "flow_id": flow.get("id"),
            "basis": flow.get("basis", "unknown"),
            "source": flow.get("source"),
            "confidence": flow.get("confidence"),
            "chain": flow.get("chain"),
            "asset": flow.get("asset"),
            "amount_usd": flow.get("amount_usd"),
            "wallet_address_hash": flow.get("wallet_address_hash"),
            "occurred_at": flow.get("occurred_at"),
        })
    return steps


async def get_card_linked_profile_summary(
    tenant_id: str, entity_id: str, filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repos = get_card_linked_repositories()
    all_rows = await repos.flows.list_for_tenant(tenant_id)
    attributed = _attributed_to_entity(
        [r for r in all_rows if r.get("reconciliation_state") != "benchmark_only"],
        entity_id,
    )
    filtered = apply_flow_filters(attributed, filters or {})
    rollup = await entity_economic_activity(tenant_id, entity_id)
    provenance = sorted({str(r.get("source")) for r in filtered})
    warnings = []
    if any(r.get("basis") == "unknown" for r in filtered):
        warnings.append("Some flows carry basis=unknown — do not interpret them as spend.")
    if rollup["topup_count"] and not rollup["spend_count"]:
        warnings.append("Only top-up/funding evidence exists — top-up volume is not card spend.")
    return {
        "entity_id": entity_id,
        "summary": rollup,
        "flows": filtered[:200],
        "story": _story(filtered),
        "provenance": provenance,
        "filters_applied": {k: v for k, v in (filters or {}).items() if v not in (None, "")},
        "available_filters": list(FILTERABLE_FIELDS) + ["volume_min", "volume_max", "since", "until"],
        "warnings": warnings,
    }


async def get_card_linked_drilldown(
    tenant_id: str, entity_id: str, object_id: str,
) -> dict[str, Any] | None:
    """Evidence/provenance drill for one flow attributed to the entity."""
    repos = get_card_linked_repositories()
    flow = await repos.flows.get(tenant_id, object_id)
    if flow is None:
        return None
    if entity_id not in (
        flow.get("canonical_entity_id"), flow.get("user_id"), flow.get("agent_id"),
        flow.get("org_id"), flow.get("wallet_address_hash"),
    ):
        return None
    reconciliations = await repos.reconciliation.list_for_tenant(tenant_id)
    related = [r for r in reconciliations if object_id in (r.get("flow_ids") or [])]
    return {
        "flow": flow,
        "evidence_refs": flow.get("evidence_refs", []),
        "provenance": {
            "source": flow.get("source"),
            "confidence": flow.get("confidence"),
            "basis": flow.get("basis"),
            "reconciliation_state": flow.get("reconciliation_state"),
            "region_policy": flow.get("region_policy"),
        },
        "reconciliation_records": related,
    }
