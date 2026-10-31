"""One builder for the Agent360 behavior read model (WO-110).

The behavior read model is served two ways: the
``GET /v1/agent/agents/{agent_ref}/behavior`` route and the behavior sections
of the registered ``agent360`` projection provider. Both call
:func:`build_agent_behavior_read_model`, so the two can never disagree.

The model is a rebuildable projection over tenant-scoped Silver facts
(ADR-AB-002). Nothing here writes Bronze, Silver, identity or graph state
(ADR-AB-008). Agent refs are source-reported; this is not identity resolution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

BEHAVIOR_FACT_LIMIT = 1000
SILVER_TABLE = "silver_agent_execution_facts"


@dataclass(frozen=True)
class BehaviorInputs:
    """Bounded, tenant-scoped inputs for one agent's behavior model."""

    facts: list[Any]
    truncated: bool
    grants: list[dict[str, Any]]


async def load_behavior_facts(tenant_id: str, agent_ref: str, *, analytics: Any = None) -> tuple[list[Any], bool]:
    """Bounded tenant-scoped Silver facts for one agent plus the tenant's spawn edges."""
    from intelligence.agent_behavior.facts import normalize_rows

    if analytics is None:
        from dependencies.providers import get_cache
        from repositories.repos import AnalyticsRepository

        analytics = AnalyticsRepository(get_cache())
    rows = await analytics.query_silver(
        SILVER_TABLE, {"tenant_id": tenant_id, "agent_id": agent_ref}, limit=BEHAVIOR_FACT_LIMIT + 1,
    )
    truncated = len(rows) > BEHAVIOR_FACT_LIMIT
    spawns = await analytics.query_silver(
        SILVER_TABLE, {"tenant_id": tenant_id, "source_event_type": "agent_subagent_spawned"},
        limit=BEHAVIOR_FACT_LIMIT,
    )
    return normalize_rows(rows[:BEHAVIOR_FACT_LIMIT] + spawns, tenant_id), truncated


async def load_behavior_inputs(tenant_id: str, agent_ref: str) -> BehaviorInputs:
    from repositories.repos import DelegationRepository

    facts, truncated = await load_behavior_facts(tenant_id, agent_ref)
    grants = await DelegationRepository().active_for(agent_ref, tenant_id)
    return BehaviorInputs(facts=facts, truncated=truncated, grants=list(grants or []))


async def agent_continuity_reviews(tenant_id: str, agent_ref: str) -> list[dict[str, Any]]:
    """Open and reviewer-decided continuity items touching this agent's source identities."""
    from identity.identity.pending_review import PendingIdentityReviewRepository
    from identity.identity.routes import get_identity_resolver

    repo = getattr(get_identity_resolver(), "_repo", None)
    if repo is None:
        return []
    ids = {str(row.get("id")) for row in await repo.list_source_identities_by_identifier(
        tenant_id, "agent_id", agent_ref, limit=20)}
    items = await PendingIdentityReviewRepository().list_agent_continuity(tenant_id)
    return [
        {k: item.get(k) for k in ("id", "status", "reason_codes", "candidate_source_identity_ids",
                                  "identify_source_identity_id", "created_at", "seen_count", "decision")}
        for item in items
        if ids & ({item.get("identify_source_identity_id")} | set(item.get("candidate_source_identity_ids") or []))
    ]


def compose_behavior_read_model(inputs: BehaviorInputs, agent_ref: str, *,
                                queued_reviews: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    from intelligence.agent_behavior.read_models import agent360_behavior

    return agent360_behavior(inputs.facts, agent_ref, truncated=inputs.truncated, grants=inputs.grants,
                             queued_reviews=queued_reviews)


async def build_agent_behavior_read_model(tenant_id: str, agent_ref: str, *,
                                          include_reviews: bool = True) -> dict[str, Any]:
    """The Agent360 behavior read model for one tenant-scoped, source-reported agent ref."""
    inputs = await load_behavior_inputs(tenant_id, agent_ref)
    reviews = await agent_continuity_reviews(tenant_id, agent_ref) if include_reviews else None
    return compose_behavior_read_model(inputs, agent_ref, queued_reviews=reviews)
