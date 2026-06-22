"""
Silver→Graph projector — emits graph mutations after Silver projection.

Called by SilverDispatcher after a projector writes Silver facts.
Each emission is:
  - idempotent (key = sha256(source_event_id + edge_type))
  - evidence-backed (source_event_id required, provenance_class="silver")
  - fire-and-forget (failures are logged, not raised, to preserve Silver writes)
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from services.silver.projectors.base import ProjectionResult
from shared.graph.edge_properties import build_edge_properties
from shared.graph.graph import Edge, EdgeType
from shared.logger.logger import get_logger

logger = get_logger("aether.silver.graph_projector")

_EMIT_ENABLED = os.getenv("AETHER_SILVER_GRAPH_EMIT", "true").lower() != "false"


def _edge(
    edge_type: str,
    from_id: str,
    to_id: str,
    tenant_id: str,
    source_event_id: str,
    valid_from: str,
    consent_purpose: str = "",
    confidence: float = 0.9,
) -> Edge:
    props = build_edge_properties(
        tenant_id=tenant_id,
        edge_type=edge_type,
        from_vertex_id=from_id,
        to_vertex_id=to_id,
        actor_kind="system",
        actor_id="silver_projector",
        provenance="silver_projector",
        provenance_class="silver",
        valid_from=valid_from,
        source_event_id=source_event_id,
        consent_purpose=consent_purpose,
        confidence=confidence,
    )
    return Edge(
        edge_type=edge_type,
        from_vertex_id=from_id,
        to_vertex_id=to_id,
        properties=props,
    )


class SilverGraphProjector:
    """
    Translates Silver ProjectionResults into graph mutations.

    Only projector tables that carry meaningful entity relationships are
    mapped. Other Silver tables (friction, data_quality, etc.) do not
    produce graph mutations.
    """

    # Map Silver table → handler method name
    _TABLE_HANDLERS: dict[str, str] = {
        "silver_exposure_facts":       "_emit_exposure",
        "silver_revenue_facts":        "_emit_revenue",
        "silver_outcome_facts":        "_emit_outcome",
        "silver_comms_facts":          "_emit_comms",
        "silver_agent_execution_facts": "_emit_agent_execution",
    }

    async def maybe_emit(self, result: ProjectionResult, event: dict[str, Any]) -> None:
        if not _EMIT_ENABLED or result.skipped or not result.rows:
            return
        handler_name = self._TABLE_HANDLERS.get(result.table)
        if not handler_name:
            return
        handler = getattr(self, handler_name)
        try:
            await handler(result, event)
        except Exception as exc:
            logger.warning("silver_graph_projector emit failed for %s: %s", result.table, exc)

    # ── Per-table handlers ──────────────────────────────────────────────

    async def _emit_exposure(self, result: ProjectionResult, event: dict[str, Any]) -> None:
        from shared.graph.graph import get_graph_client
        graph = get_graph_client()
        ctx = event.get("context") or {}
        tenant_id = ctx.get("tenantId") or event.get("tenantId") or "default"
        user_id = event.get("userId") or event.get("anonymousId", "")
        content_id = (event.get("properties") or {}).get("contentId") or (event.get("properties") or {}).get("recommendationId", "")
        source_event_id = event.get("messageId", "")
        occurred_at = event.get("timestamp", "")
        if not (user_id and content_id and source_event_id):
            return
        edge = _edge(
            EdgeType.EXPOSED_TO, user_id, content_id, tenant_id,
            source_event_id, occurred_at, consent_purpose="analytics",
        )
        await graph.add_edge(edge)

    async def _emit_revenue(self, result: ProjectionResult, event: dict[str, Any]) -> None:
        from shared.graph.graph import get_graph_client
        graph = get_graph_client()
        ctx = event.get("context") or {}
        tenant_id = ctx.get("tenantId") or event.get("tenantId") or "default"
        user_id = event.get("userId", "")
        props = event.get("properties") or {}
        source_event_id = event.get("messageId", "")
        occurred_at = event.get("timestamp", "")
        event_type = event.get("type", "")
        if not (user_id and source_event_id):
            return
        if event_type in ("order_completed",):
            product_id = props.get("productId") or props.get("orderId", "")
            if product_id:
                edge = _edge(
                    EdgeType.PURCHASED, user_id, product_id, tenant_id,
                    source_event_id, occurred_at, consent_purpose="commerce",
                )
                await get_graph_client().add_edge(edge)
        elif event_type in ("subscription_started", "trial_converted"):
            plan_id = props.get("planId") or props.get("subscriptionId", "")
            if plan_id:
                edge = _edge(
                    EdgeType.SUBSCRIBES_TO, user_id, plan_id, tenant_id,
                    source_event_id, occurred_at, consent_purpose="commerce",
                )
                await get_graph_client().add_edge(edge)

    async def _emit_outcome(self, result: ProjectionResult, event: dict[str, Any]) -> None:
        from shared.graph.graph import get_graph_client
        graph = get_graph_client()
        ctx = event.get("context") or {}
        tenant_id = ctx.get("tenantId") or event.get("tenantId") or "default"
        user_id = event.get("userId", "")
        props = event.get("properties") or {}
        goal_id = props.get("goalId") or props.get("outcomeId", "")
        source_event_id = event.get("messageId", "")
        occurred_at = event.get("timestamp", "")
        if not (user_id and goal_id and source_event_id):
            return
        edge = _edge(
            EdgeType.ACHIEVED_OUTCOME, user_id, goal_id, tenant_id,
            source_event_id, occurred_at, consent_purpose="analytics",
        )
        await graph.add_edge(edge)

    async def _emit_comms(self, result: ProjectionResult, event: dict[str, Any]) -> None:
        from shared.graph.graph import get_graph_client
        graph = get_graph_client()
        ctx = event.get("context") or {}
        tenant_id = ctx.get("tenantId") or event.get("tenantId") or "default"
        props = event.get("properties") or {}
        recipient_id = props.get("recipientId") or event.get("userId", "")
        sender_id = props.get("senderId") or ctx.get("actorId", "system")
        source_event_id = event.get("messageId", "")
        occurred_at = event.get("timestamp", "")
        if not (recipient_id and source_event_id):
            return
        edge = _edge(
            EdgeType.CONTACTED, sender_id, recipient_id, tenant_id,
            source_event_id, occurred_at, consent_purpose="analytics",
        )
        await graph.add_edge(edge)

    async def _emit_agent_execution(self, result: ProjectionResult, event: dict[str, Any]) -> None:
        # agent_task events already drive existing EXECUTED_AS/PRODUCED edges
        # via the dedicated graph_mutations.py handler — no additional emission needed.
        pass
