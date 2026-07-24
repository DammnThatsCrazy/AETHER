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
from shared.graph.edge_properties import build_edge_properties, make_edge_idempotency_key
from shared.graph.graph import Edge, EdgeType, Vertex, VertexType
from shared.graph.mutation_gateway import get_mutation_gateway
from shared.graph.mutation_intents import edge_intent, vertex_intent
from shared.logger.logger import get_logger

logger = get_logger("aether.silver.graph_projector")

_EMIT_ENABLED = os.getenv("AETHER_SILVER_GRAPH_EMIT", "true").lower() != "false"

# Observed agent-execution event names that justify a BOUNDED graph vertex.
# Everything else (generic activity, risk signals, trades, …) stays a Silver
# fact only — high-cardinality per-event nodes never enter the graph.
_MCP_EVENTS = frozenset({"agent_mcp_connection_observed"})
_TOOL_EVENTS = frozenset({
    "agent_tool_invocation_observed",
    "agent_tool_observed",
    "agent_tool_called",
})


async def _emit(edge: Edge, *, subject_id: str = "") -> None:
    """Route a Silver-sourced edge through the canonical mutation gateway.

    Behaviour is identical to the pre-gateway ``get_graph_client().add_edge``
    when the gateway mode is ``off`` (default); ``shadow`` / ``enforce`` also
    record the write in the append-only mutation ledger as ``edge_created``.
    """
    await get_mutation_gateway().apply(
        edge_intent(
            edge,
            operation="edge_created",
            actor_id="silver_projector",
            subject_kind="entity" if subject_id else None,
            subject_id=subject_id or None,
        )
    )


async def _emit_vertex(vertex: Vertex, *, tenant_id: str) -> None:
    """Route a Silver-sourced vertex through the canonical mutation gateway."""
    await get_mutation_gateway().apply(
        vertex_intent(
            vertex,
            operation="node_created",
            tenant_id=tenant_id,
            actor_id="silver_projector",
        )
    )


def _bounded_edge(
    edge_type: str,
    from_id: str,
    to_id: str,
    tenant_id: str,
    source_event_id: str,
    valid_from: str,
) -> Edge:
    """Silver edge whose idempotency key EXCLUDES the source event.

    ``source_event_id`` still travels on the edge (silver-sourced writes require
    it for traceability), but the idempotency key is over ``(agent, target)``
    only — so repeated observations of the same (agent, server) or (agent, tool)
    converge on exactly ONE edge instead of one edge per event.
    """
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
        confidence=0.9,
    )
    props["idempotency_key"] = make_edge_idempotency_key(
        tenant_id, edge_type, from_id, to_id
    )
    return Edge(
        edge_type=edge_type,
        from_vertex_id=from_id,
        to_vertex_id=to_id,
        properties=props,
    )


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
        "silver_campaign_touchpoint_facts": "_emit_touchpoint_source",
    }

    # entry_method values that carry platform-verified install evidence.
    _PLATFORM_EVIDENCE_ENTRY_METHODS = frozenset({
        "android_install_referrer",
        "android_app_link",
        "ios_universal_link",
        "ios_adattributionkit",
    })

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
        await _emit(edge, subject_id=user_id)

    async def _emit_revenue(self, result: ProjectionResult, event: dict[str, Any]) -> None:
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
                await _emit(edge, subject_id=user_id)
        elif event_type in ("subscription_started", "trial_converted"):
            plan_id = props.get("planId") or props.get("subscriptionId", "")
            if plan_id:
                edge = _edge(
                    EdgeType.SUBSCRIBES_TO, user_id, plan_id, tenant_id,
                    source_event_id, occurred_at, consent_purpose="commerce",
                )
                await _emit(edge, subject_id=user_id)

    async def _emit_outcome(self, result: ProjectionResult, event: dict[str, Any]) -> None:
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
        await _emit(edge, subject_id=user_id)

    async def _emit_comms(self, result: ProjectionResult, event: dict[str, Any]) -> None:
        """Aggregated communication relationships (ADR-C6).

        Delegates to CommsGraphProjector: one durable edge per
        (sender context, recipient, channel) relationship — never one edge
        per event, never a global 'system' sender node.
        """
        from services.comms.graph_projection import CommsGraphProjector
        projector = CommsGraphProjector()
        for row in result.rows:
            await projector.project_fact(row)

    async def _emit_agent_execution(self, result: ProjectionResult, event: dict[str, Any]) -> None:
        """Bounded graph emission for observed agent-execution facts.

        - MCP connection events → one ``MCPConnection`` vertex per (tenant,
          server) and one ``AGENT_CONNECTED_VIA_MCP`` edge per (agent, server).
        - Tool invocation events → one ``AgentToolObserved`` vertex per (tenant,
          tool) carrying the REAL tool name, and one ``AGENT_USED_TOOL_OBS`` edge
          per (agent, tool).
        - Everything else (generic activity, risk signals, trades, …) stays a
          Silver fact only — no per-event vertex enters the graph (high-cardinality
          stays in Silver, not the graph).

        All emissions are idempotent over their bounded key and never raise
        (maybe_emit already isolates failures from the Silver write).
        """
        for row in result.rows:
            agent_id = row.get("agent_id")
            source_event_id = str(row.get("source_event_id") or "")
            if not agent_id or not source_event_id:
                continue
            tenant_id = str(row.get("tenant_id") or "default")
            agent_id = str(agent_id)
            occurred_at = _as_iso(row.get("occurred_at"))
            event_name = row.get("event_name") or event.get("type") or ""

            if event_name in _MCP_EVENTS:
                server_name = row.get("server_name")
                if not server_name:
                    continue
                vertex_id = f"mcp:{tenant_id}:{server_name}"
                await _emit_vertex(
                    Vertex(
                        vertex_type=VertexType.MCP_CONNECTION,
                        vertex_id=vertex_id,
                        properties={
                            "tenant_id": tenant_id,
                            "tenantId": tenant_id,
                            "server_name": str(server_name),
                            "server_url": row.get("server_url"),
                        },
                    ),
                    tenant_id=tenant_id,
                )
                await _emit(
                    _bounded_edge(
                        EdgeType.AGENT_CONNECTED_VIA_MCP, agent_id, vertex_id,
                        tenant_id, source_event_id, occurred_at,
                    ),
                    subject_id=agent_id,
                )

            elif event_name in _TOOL_EVENTS:
                tool_name = row.get("tool_name")
                if not tool_name:
                    continue
                vertex_id = f"tool:{tenant_id}:{tool_name}"
                await _emit_vertex(
                    Vertex(
                        vertex_type=VertexType.AGENT_TOOL_OBS,
                        vertex_id=vertex_id,
                        properties={
                            "tool_name": str(tool_name),  # REAL tool name, not object_type
                            "tenant_id": tenant_id,
                            "tenantId": tenant_id,
                        },
                    ),
                    tenant_id=tenant_id,
                )
                await _emit(
                    _bounded_edge(
                        EdgeType.AGENT_USED_TOOL_OBS, agent_id, vertex_id,
                        tenant_id, source_event_id, occurred_at,
                    ),
                    subject_id=agent_id,
                )
            # else: generic activity / risk-signal → Silver fact only.

    async def _emit_touchpoint_source(self, result: ProjectionResult, event: dict[str, Any]) -> None:
        """Project canonical source/attribution relationships (spec §13.6).

        Reads the classified touchpoint rows (never the raw event) and emits, per
        row: entity/session arrived-through-source, session used-placement,
        journey originated-from-link, install attributed-to-platform-evidence,
        and agent/AI referred-entity. All edges are tenant-scoped and
        replay-safe: the edge identity is (from, to, edge_type), so replaying an
        event upserts the same edges idempotently.
        """
        for row in result.rows:
            tenant_id = str(row.get("tenant_id") or "default")
            source_event_id = str(row.get("source_event_id") or "")
            if not source_event_id:
                continue
            occurred_at = _as_iso(row.get("occurred_at"))
            entity_id = (
                row.get("profile_id") or row.get("cluster_id") or row.get("anonymous_id") or ""
            )
            session_id = row.get("session_id") or ""

            # 1. arrived-through-source (entity or session → Source node)
            source_class = row.get("source_class")
            arrived_from = entity_id or session_id
            if arrived_from and source_class:
                source_token = str(row.get("source") or "unknown")
                source_vertex = f"source:{tenant_id}:{source_class}:{source_token}"
                await _emit(
                    _edge(
                        EdgeType.ARRIVED_THROUGH_SOURCE, str(arrived_from), source_vertex,
                        tenant_id, source_event_id, occurred_at, consent_purpose="analytics",
                    ),
                    subject_id=str(arrived_from),
                )

            # 2. used-placement (session → Placement node)
            placement_id = row.get("placement_id")
            if session_id and placement_id:
                placement_vertex = f"placement:{tenant_id}:{placement_id}"
                await _emit(
                    _edge(
                        EdgeType.USED_PLACEMENT, str(session_id), placement_vertex,
                        tenant_id, source_event_id, occurred_at, consent_purpose="analytics",
                    ),
                    subject_id=str(session_id),
                )

            # 3. originated-from-link (session/journey → VerifiedSourceLink node)
            link_id = row.get("verified_referral_link_id")
            link_from = session_id or entity_id
            if link_from and link_id:
                link_vertex = f"sourcelink:{tenant_id}:{link_id}"
                await _emit(
                    _edge(
                        EdgeType.ORIGINATED_FROM_LINK, str(link_from), link_vertex,
                        tenant_id, source_event_id, occurred_at, consent_purpose="analytics",
                    ),
                    subject_id=str(link_from),
                )

            # 4. install attributed-to-platform-evidence (entity → PlatformEvidence node)
            entry_method = row.get("entry_method")
            if (
                entity_id
                and entry_method in self._PLATFORM_EVIDENCE_ENTRY_METHODS
                and row.get("proof_level") == "platform_verified"
            ):
                evidence_vertex = f"platform_evidence:{tenant_id}:{entry_method}"
                await _emit(
                    _edge(
                        EdgeType.ATTRIBUTED_TO_PLATFORM_EVIDENCE, str(entity_id), evidence_vertex,
                        tenant_id, source_event_id, occurred_at, consent_purpose="analytics",
                    ),
                    subject_id=str(entity_id),
                )

            # 5. agent/AI referred-entity (Agent/AI node → entity)
            actor_type = row.get("actor_type")
            ai_provider = row.get("ai_provider")
            agent_id = row.get("agent_id")
            if entity_id and (actor_type in ("agent", "ai") or ai_provider or agent_id):
                if agent_id:
                    referrer_vertex = f"agent:{tenant_id}:{agent_id}"
                elif ai_provider:
                    referrer_vertex = f"ai:{tenant_id}:{ai_provider}"
                else:
                    referrer_vertex = f"{actor_type}:{tenant_id}:unknown"
                await _emit(
                    _edge(
                        EdgeType.REFERRED_ENTITY, referrer_vertex, str(entity_id),
                        tenant_id, source_event_id, occurred_at, consent_purpose="analytics",
                    ),
                    subject_id=referrer_vertex,
                )


def _as_iso(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
