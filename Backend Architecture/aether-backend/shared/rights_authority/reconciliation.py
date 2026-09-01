"""Inventory and reconciliation report for legacy rights-less artifacts.

The report is deliberately a plan, not a backfill. A row without an
authoritative envelope cannot be assigned rights by inference; it must be
quarantined or reviewed with source evidence by a concrete adapter.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.rights_authority.pep import rights_mode
from shared.rights_authority.service import RightsAuthority, rights_authority

_RESOURCE_TABLES = {
    "bronze": ("sdk_events", "dune_raw", "connector_raw"),
    "silver": ("silver_identity", "silver_onchain", "silver_social", "silver_market"),
    "gold": ("gold_identity", "gold_onchain", "gold_social", "gold_market"),
}


def _has_rights(row: dict[str, Any]) -> bool:
    rights = row.get("rights")
    if not isinstance(rights, dict):
        payload = row.get("payload")
        rights = payload.get("rights") if isinstance(payload, dict) else None
    if not isinstance(rights, dict):
        return False
    return bool(
        rights.get("rights_decision_refs")
        or rights.get("decision_id")
        or rights.get("rights_envelope_refs")
        or rights.get("envelope_refs")
    )


async def build_reconciliation_report(
    *,
    tenant_id: Optional[str] = None,
    limit_per_table: int = 10_000,
    authority: RightsAuthority = rights_authority,
) -> dict[str, Any]:
    """Return counts and bounded row refs requiring an evidence-backed plan."""
    resources: dict[str, dict[str, Any]] = {}
    total_rows = 0
    total_rightsless = 0
    for resource_type, tables in _RESOURCE_TABLES.items():
        for table in tables:
            repo = BaseRepository(table)
            filters = {"tenant_id": tenant_id} if tenant_id else None
            rows = await repo.find_many(filters=filters, limit=limit_per_table)
            missing = [
                {
                    "id": row.get("id"),
                    "tenant_id": row.get("tenant_id"),
                    "source": row.get("source") or row.get("source_tag"),
                    "reason": "rights_context_missing",
                }
                for row in rows
                if not _has_rights(row)
            ]
            total_rows += len(rows)
            total_rightsless += len(missing)
            resources[f"{resource_type}:{table}"] = {
                "rows_scanned": len(rows),
                "rights_attached": len(rows) - len(missing),
                "rightsless": len(missing),
                "sample": missing[:100],
            }

    decisions = await authority.repository.list_decisions(tenant_id)
    outcomes: dict[str, int] = {}
    for decision in decisions:
        outcome = str(decision.get("outcome", "unknown"))
        outcomes[outcome] = outcomes.get(outcome, 0) + 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tenant_id": tenant_id,
        "rights_mode": rights_mode(),
        "resources": resources,
        "totals": {
            "rows_scanned": total_rows,
            "rights_attached": total_rows - total_rightsless,
            "rightsless": total_rightsless,
        },
        "decision_outcomes": outcomes,
        "migration": {
            "status": "evidence_required" if total_rightsless else "no_rightsless_rows_found",
            "mutation_performed": False,
            "next_action": (
                "quarantine or review each sampled row with source evidence before backfill"
                if total_rightsless else "continue shadow/enforce reconciliation"
            ),
        },
    }


__all__ = ["build_reconciliation_report"]
