"""Profile360 Agent Activity / Delegation projection (summary only).

For one human or organization this surfaces how many agents act for it and how
they are related (direct vs delegated, active vs historical, depth, risk,
unresolved, revoked). It is a SUMMARY: a principal with 100,000 agents is never
rendered as 100,000 rows here. Row-level exploration is the cursor-paginated
``/v1/agent-lineage/...`` API, reached by cohort navigation on the client.

The projection reads the materialized lineage summary through the injectable
:class:`LineageSummaryReader`. Rules:

  * unknown is ``None``, never ``0`` — a count the lineage summary does not
    carry (communications, financial activity, outcomes, ephemeral split) is
    ``None`` with a stated reason, not a fabricated zero;
  * with no reader wired, or when the reader fails or returns a summary for
    another tenant/principal, the section degrades to completeness
    ``unavailable`` with every count ``None``;
  * every result carries the seam ``Disclosure`` so the client can badge
    truncated / stale / recomputing / unresolved states.

The derived lineage read model never replaces the canonical graph and
Bronze/Silver evidence; this module only re-shapes its summary.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol

from shared.agent_lineage.models import Disclosure, LineageSummary
from shared.logger.logger import get_logger

logger = get_logger("aether.profile.agent_lineage")

SECTION_ID = "agent_activity"
UNAVAILABLE_PROJECTION_VERSION = "unavailable"

# Cohort navigation offered by the client (work order §41). ``filter`` is the
# ``/v1/agent-lineage/principals/{id}/agents`` query parameter the cohort maps
# to; ``group_by`` cohorts open ``/clusters`` / grouped listings instead.
COHORT_NAVIGATION: tuple[dict[str, Optional[str]], ...] = (
    {"id": "direct", "label": "Direct", "filter": "relationship=direct", "group_by": None},
    {"id": "delegated", "label": "Delegated", "filter": "relationship=indirect", "group_by": None},
    {"id": "platform", "label": "Platform", "filter": None, "group_by": "platform"},
    {"id": "operator", "label": "Operator", "filter": None, "group_by": "operator"},
    {"id": "authority", "label": "Authority", "filter": None, "group_by": "authority"},
    {"id": "agent_family", "label": "Agent family", "filter": None, "group_by": "agent_family"},
    {"id": "deployment", "label": "Deployment", "filter": None, "group_by": "deployment"},
    {"id": "risk", "label": "Risk", "filter": "risk=flagged", "group_by": None},
    {"id": "value", "label": "Value", "filter": None, "group_by": "value"},
    {"id": "communication", "label": "Communication", "filter": None, "group_by": "communication"},
    {"id": "time", "label": "Time", "filter": None, "group_by": "time"},
    {"id": "depth", "label": "Depth", "filter": None, "group_by": "depth"},
    {"id": "status", "label": "Status", "filter": None, "group_by": "status"},
)

# Counts the seam's LineageSummary does not carry. They stay ``None`` (unknown)
# with the reason below instead of being derived from unrelated counters.
_NOT_IN_SEAM_SUMMARY: dict[str, str] = {
    "ephemeral_agent_instances": "summary_does_not_classify_ephemeral_instances",
    "agent_mediated_communications": "communication_activity_not_in_lineage_summary",
    "agent_directed_financial_activity": "financial_activity_not_in_lineage_summary",
    "agent_outcomes": "outcomes_not_in_lineage_summary",
}


class LineageSummaryReader(Protocol):
    """Tenant-bounded read of the materialized principal lineage summary."""

    async def summary(
        self, tenant_id: str, principal_entity_id: str
    ) -> Optional[LineageSummary]:
        """Return the summary, or ``None`` when none has been materialized."""


def _unavailable_disclosure(reason: str) -> Disclosure:
    return Disclosure(
        projection_version=UNAVAILABLE_PROJECTION_VERSION,
        completeness="unavailable",
        truncated=False,
        truncation_reasons=[reason],
    )


def _sum_known(*values: Optional[int]) -> Optional[int]:
    """Sum counts only when every operand is known; otherwise unknown."""
    if any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


_COUNT_KEYS: tuple[str, ...] = (
    "total_agents",
    "directly_authorized_agents",
    "indirectly_delegated_agents",
    "active_agents",
    "historical_agents",
    "agent_instances",
    "ephemeral_agent_instances",
    "agent_runs",
    "max_delegation_depth",
    "tools_used",
    "services_used",
    "agent_mediated_communications",
    "agent_directed_financial_activity",
    "agent_outcomes",
    "risk_flagged_agents",
    "unresolved_associations",
    "revoked_relationships",
)


def _empty_counts() -> dict[str, Optional[int]]:
    return {key: None for key in _COUNT_KEYS}


def _counts_from_summary(summary: LineageSummary) -> dict[str, Optional[int]]:
    counts = _empty_counts()
    counts.update(
        {
            "total_agents": _sum_known(summary.direct_agents, summary.indirect_agents),
            "directly_authorized_agents": summary.direct_agents,
            "indirectly_delegated_agents": summary.indirect_agents,
            "active_agents": summary.active_agents,
            "historical_agents": summary.historical_agents,
            "agent_instances": summary.agent_instances,
            "agent_runs": summary.agent_runs,
            "max_delegation_depth": summary.max_delegation_depth,
            "tools_used": summary.tools_used,
            "services_used": summary.services_used,
            "risk_flagged_agents": summary.risk_flagged_agents,
            "unresolved_associations": summary.unresolved_agents,
            "revoked_relationships": summary.revoked_agents,
        }
    )
    return counts


def _unavailable(
    tenant_id: str, principal_entity_id: str, reason: str
) -> dict[str, Any]:
    return {
        "section": SECTION_ID,
        "tenant_id": tenant_id,
        "principal_entity_id": principal_entity_id,
        "completeness": "unavailable",
        "reason": reason,
        "counts": _empty_counts(),
        "unavailable_counts": dict(_NOT_IN_SEAM_SUMMARY),
        "verified_links": None,
        "inferred_links": None,
        "disclosure": _unavailable_disclosure(reason).model_dump(mode="json"),
        "default_view": "summary",
        "row_list_policy": "cursor_paginated_never_unbounded",
        "navigation": [dict(item) for item in COHORT_NAVIGATION],
    }


async def compose_agent_activity(
    reader: Optional[LineageSummaryReader],
    tenant_id: str,
    principal_entity_id: str,
) -> dict[str, Any]:
    """Compose the Agent Activity / Delegation summary for one principal."""
    if reader is None:
        return _unavailable(tenant_id, principal_entity_id, "lineage_reader_not_configured")
    try:
        summary = await reader.summary(tenant_id, principal_entity_id)
    except Exception as exc:  # noqa: BLE001 - degrade this section only
        logger.warning(
            "profile360_agent_lineage_read_failed",
            extra={"principal_entity_id": principal_entity_id, "error": type(exc).__name__},
        )
        return _unavailable(tenant_id, principal_entity_id, "lineage_reader_failed")
    if summary is None:
        return _unavailable(tenant_id, principal_entity_id, "lineage_summary_not_materialized")
    if summary.tenant_id != tenant_id or summary.principal_entity_id != principal_entity_id:
        # A reader must never certify another tenant's/principal's summary.
        return _unavailable(tenant_id, principal_entity_id, "lineage_summary_scope_mismatch")

    return {
        "section": SECTION_ID,
        "tenant_id": tenant_id,
        "principal_entity_id": principal_entity_id,
        "completeness": summary.disclosure.completeness,
        "reason": None,
        "counts": _counts_from_summary(summary),
        "unavailable_counts": dict(_NOT_IN_SEAM_SUMMARY),
        "verified_links": summary.verified_links,
        "inferred_links": summary.inferred_links,
        "disclosure": summary.disclosure.model_dump(mode="json"),
        "default_view": "summary",
        "row_list_policy": "cursor_paginated_never_unbounded",
        "navigation": [dict(item) for item in COHORT_NAVIGATION],
    }
