"""Comms graph projection — aggregated relationships, bounded cardinality
(Phase 17, ADR-C6).

Storage levels:
1. Event facts stay in ``silver_comms_facts`` (Postgres) — never in the graph.
2. Meaningful temporal activity lives in ``canonical_activity``.
3. Durable relationships live in ``communication_relationships`` (durable
   aggregate ledger) plus ONE graph edge per relationship, emitted on first
   observation and refreshed only on promotion transitions (first reply).

The literal ``"system"`` sender is banned: sender context resolves to an
agent, organization, entity, or provider-account vertex reference.
Message vertices are promoted only for replied threads (extendable to
support/high-value cases via the same promote path).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics
from repositories.repos import get_pool
from services.comms.contracts import CATEGORY_CONSENT_PURPOSE, MessageCategory

logger = get_logger("aether.comms.graph")

# Local fallback aggregate store (mirrors communication_relationships)
_local_relationships: dict[str, dict[str, Any]] = {}


def reset_local_relationships() -> None:
    _local_relationships.clear()


# Events that contribute to durable relationships. Queued/processed/deferred
# noise and machine engagement never touch the graph.
_RELATIONSHIP_EVENTS = frozenset({
    "email_sent", "email_delivered", "email_clicked", "email_replied",
    "message_sent_observed", "message_received_observed",
    "message_replied_observed", "notification_delivered", "notification_clicked",
})

_REPLY_EVENTS = frozenset({"email_replied", "message_replied_observed"})


def resolve_sender_ref(row: dict[str, Any]) -> Optional[str]:
    """Resolve the real sender context — never a global 'system' node."""
    if row.get("agent_id"):
        return f"agent:{row['agent_id']}"
    if row.get("organization_id"):
        return f"org:{row['organization_id']}"
    if row.get("sender_entity_id"):
        return f"entity:{row['sender_entity_id']}"
    provider = row.get("provider")
    account = row.get("provider_account_id")
    if provider and account:
        return f"provider_account:{provider}:{account}"
    return None


def resolve_recipient_ref(row: dict[str, Any]) -> Optional[str]:
    if row.get("recipient_entity_id"):
        return f"entity:{row['recipient_entity_id']}"
    if row.get("profile_id"):
        return f"entity:{row['profile_id']}"
    if row.get("recipient_alias_id"):
        return f"email_alias:{row['recipient_alias_id']}"
    return None


def edge_type_for(row: dict[str, Any]) -> str:
    """Relationship layer selection (Phase 17)."""
    from shared.graph.graph import EdgeType

    event_type = row.get("source_event_type", "")
    if event_type in _REPLY_EVENTS:
        return EdgeType.COMMUNICATES_WITH
    if row.get("agent_id"):
        # Agent-originated notification stream
        return EdgeType.NOTIFIES
    if row.get("message_category") in ("marketing", "sales"):
        return EdgeType.CONTACTED
    return EdgeType.COMMUNICATES_WITH


class CommsGraphProjector:
    """Updates the durable relationship aggregate and emits bounded edges."""

    async def _pool(self):
        return await get_pool()

    async def project_fact(self, row: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Fold one comms fact into its aggregated relationship.

        Returns the updated aggregate, or None when the fact does not
        contribute to a durable relationship (lifecycle noise, machine
        activity, unresolvable endpoints).
        """
        event_type = row.get("source_event_type", "")
        if event_type not in _RELATIONSHIP_EVENTS:
            return None
        if row.get("suspected_machine_activity"):
            return None
        sender_ref = resolve_sender_ref(row)
        recipient_ref = resolve_recipient_ref(row)
        if not sender_ref or not recipient_ref:
            return None
        # Inbound replies flow recipient → sender in the relationship.
        if event_type in _REPLY_EVENTS:
            sender_ref, recipient_ref = recipient_ref, sender_ref

        tenant_id = row.get("tenant_id", "")
        channel = row.get("channel", "email")
        edge_type = edge_type_for(row)
        occurred_at = row.get("occurred_at")
        campaign_id = str(row["campaign_id"]) if row.get("campaign_id") else None
        try:
            purpose = CATEGORY_CONSENT_PURPOSE[MessageCategory(row.get("message_category", "marketing"))]
        except (ValueError, KeyError):
            purpose = "analytics"

        deltas = {
            "message_count": 1,
            "delivered_count": 1 if event_type in ("email_delivered", "notification_delivered") else 0,
            "human_click_count": 1 if event_type in ("email_clicked", "notification_clicked") else 0,
            "reply_count": 1 if event_type in _REPLY_EVENTS else 0,
        }
        evidence = str(row.get("source_event_id") or "")

        aggregate, created, first_reply = await self._upsert_aggregate(
            tenant_id, sender_ref, recipient_ref, channel, edge_type,
            occurred_at=occurred_at, campaign_id=campaign_id,
            consent_purpose=purpose, evidence=evidence, deltas=deltas,
            confidence=_confidence(row),
        )

        # Bounded emission: one edge per relationship (first observation),
        # refreshed once when the relationship is upgraded by a first reply.
        if created or first_reply:
            await self._emit_edge(aggregate)
        if first_reply and row.get("external_message_id") and not aggregate.get("message_promoted"):
            await self._promote_message(row, aggregate)
        return aggregate

    # ── Aggregate persistence ────────────────────────────────────────────────

    async def _upsert_aggregate(
        self, tenant_id: str, sender_ref: str, recipient_ref: str,
        channel: str, edge_type: str, *,
        occurred_at: Any, campaign_id: Optional[str], consent_purpose: str,
        evidence: str, deltas: dict[str, int], confidence: float,
    ) -> tuple[dict[str, Any], bool, bool]:
        key = f"{tenant_id}:{sender_ref}:{recipient_ref}:{channel}:{edge_type}"
        pool = await self._pool()
        if pool is None:
            agg = _local_relationships.get(key)
            created = agg is None
            if created:
                agg = {
                    "tenant_id": tenant_id, "sender_ref": sender_ref,
                    "recipient_ref": recipient_ref, "channel": channel,
                    "edge_type": edge_type, "first_observed_at": occurred_at,
                    "message_count": 0, "delivered_count": 0,
                    "human_click_count": 0, "reply_count": 0,
                    "campaign_ids": [], "evidence_refs": [],
                    "consent_purpose": consent_purpose,
                    "confidence": confidence, "graph_emitted": False,
                    "message_promoted": False, "valid_from": occurred_at,
                }
                _local_relationships[key] = agg
            had_replies = agg["reply_count"] > 0
            for k, v in deltas.items():
                agg[k] += v
            agg["last_observed_at"] = occurred_at
            agg["confidence"] = max(agg.get("confidence") or 0.0, confidence)
            if campaign_id and campaign_id not in agg["campaign_ids"]:
                agg["campaign_ids"].append(campaign_id)
            if evidence and len(agg["evidence_refs"]) < 20:
                agg["evidence_refs"].append(evidence)
            first_reply = not had_replies and agg["reply_count"] > 0
            return agg, created, first_reply

        async with pool.acquire() as conn:
            existing = await conn.fetchrow(
                """
                SELECT reply_count, graph_emitted, message_promoted
                FROM communication_relationships
                WHERE tenant_id=$1 AND sender_ref=$2 AND recipient_ref=$3
                  AND channel=$4 AND edge_type=$5
                """,
                tenant_id, sender_ref, recipient_ref, channel, edge_type,
            )
            created = existing is None
            had_replies = bool(existing and existing["reply_count"] > 0)
            rec = await conn.fetchrow(
                """
                INSERT INTO communication_relationships (
                    tenant_id, sender_ref, recipient_ref, channel, edge_type,
                    first_observed_at, last_observed_at, message_count,
                    delivered_count, human_click_count, reply_count,
                    campaign_ids, confidence, consent_purpose, evidence_refs,
                    valid_from, updated_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$6,$7,$8,$9,$10,
                          CASE WHEN $11::text IS NULL THEN '{}'::text[] ELSE ARRAY[$11] END,
                          $12,$13,
                          CASE WHEN $14 = '' THEN '{}'::text[] ELSE ARRAY[$14] END,
                          $6, now())
                ON CONFLICT (tenant_id, sender_ref, recipient_ref, channel, edge_type)
                DO UPDATE SET
                    last_observed_at = EXCLUDED.last_observed_at,
                    message_count = communication_relationships.message_count + $7,
                    delivered_count = communication_relationships.delivered_count + $8,
                    human_click_count = communication_relationships.human_click_count + $9,
                    reply_count = communication_relationships.reply_count + $10,
                    campaign_ids = (
                        SELECT ARRAY(SELECT DISTINCT unnest(
                            communication_relationships.campaign_ids
                            || CASE WHEN $11::text IS NULL THEN '{}'::text[] ELSE ARRAY[$11] END
                        ))
                    ),
                    confidence = GREATEST(COALESCE(communication_relationships.confidence, 0), $12),
                    evidence_refs = (
                        CASE WHEN cardinality(communication_relationships.evidence_refs) < 20 AND $14 <> ''
                             THEN communication_relationships.evidence_refs || ARRAY[$14]
                             ELSE communication_relationships.evidence_refs END
                    ),
                    updated_at = now()
                RETURNING *
                """,
                tenant_id, sender_ref, recipient_ref, channel, edge_type,
                _ts(occurred_at), deltas["message_count"], deltas["delivered_count"],
                deltas["human_click_count"], deltas["reply_count"],
                campaign_id, confidence, consent_purpose, evidence,
            )
        aggregate = dict(rec)
        first_reply = not had_replies and aggregate["reply_count"] > 0
        return aggregate, created, first_reply

    # ── Graph emission ───────────────────────────────────────────────────────

    async def _emit_edge(self, aggregate: dict[str, Any]) -> None:
        try:
            from shared.graph.graph import Edge, get_graph_client
            from shared.graph.edge_properties import build_edge_properties

            evidence_refs = aggregate.get("evidence_refs") or []
            props = build_edge_properties(
                tenant_id=aggregate["tenant_id"],
                edge_type=aggregate["edge_type"],
                from_vertex_id=aggregate["sender_ref"],
                to_vertex_id=aggregate["recipient_ref"],
                actor_kind="system",
                actor_id="comms_graph_projector",
                provenance="comms_graph_projector",
                provenance_class="silver",
                valid_from=str(aggregate.get("valid_from") or aggregate.get("first_observed_at") or ""),
                source_event_id=evidence_refs[0] if evidence_refs else "",
                consent_purpose=aggregate.get("consent_purpose") or "",
                confidence=float(aggregate.get("confidence") or 0.5),
                channel=aggregate.get("channel", "email"),
                relationship_context=aggregate.get("relationship_context") or "",
                message_count=str(aggregate.get("message_count", 0)),
                delivered_count=str(aggregate.get("delivered_count", 0)),
                human_click_count=str(aggregate.get("human_click_count", 0)),
                reply_count=str(aggregate.get("reply_count", 0)),
                first_observed_at=str(aggregate.get("first_observed_at") or ""),
                last_observed_at=str(aggregate.get("last_observed_at") or ""),
            )
            edge = Edge(
                edge_type=aggregate["edge_type"],
                from_vertex_id=aggregate["sender_ref"],
                to_vertex_id=aggregate["recipient_ref"],
                properties=props,
            )
            await get_graph_client().add_edge(edge)
            aggregate["graph_emitted"] = True
            await self._mark_flag(aggregate, "graph_emitted")
            metrics.increment(
                "comms_graph_edges_emitted_total",
                labels={"tenant_id": aggregate["tenant_id"],
                        "edge_type": aggregate["edge_type"]},
            )
        except Exception as exc:
            logger.warning("comms_graph_edge_emit_failed: %s", exc)

    async def _promote_message(self, row: dict[str, Any], aggregate: dict[str, Any]) -> None:
        """Selective message promotion: replied threads become graph vertices."""
        try:
            from shared.graph.graph import Edge, Vertex, VertexType, get_graph_client
            from shared.graph.edge_properties import build_edge_properties

            tenant_id = row.get("tenant_id", "")
            message_ref = f"message:{tenant_id}:{row['external_message_id']}"
            client = get_graph_client()
            vertex_type = getattr(VertexType, "MESSAGE", "Message")
            await client.upsert_vertex(Vertex(
                vertex_type=vertex_type if isinstance(vertex_type, str) else "Message",
                vertex_id=message_ref,
                properties={
                    "tenant_id": tenant_id,
                    "external_message_id": row["external_message_id"],
                    "external_thread_id": row.get("external_thread_id") or "",
                    "channel": row.get("channel", "email"),
                    "promotion_reason": "replied",
                    "provider": row.get("provider") or "",
                },
            ))
            props = build_edge_properties(
                tenant_id=tenant_id,
                edge_type="RESPONDED_TO",
                from_vertex_id=aggregate["sender_ref"],
                to_vertex_id=message_ref,
                actor_kind="system",
                actor_id="comms_graph_projector",
                provenance="comms_graph_projector",
                provenance_class="silver",
                valid_from=str(row.get("occurred_at") or ""),
                source_event_id=str(row.get("source_event_id") or ""),
                consent_purpose=aggregate.get("consent_purpose") or "",
                confidence=float(aggregate.get("confidence") or 0.5),
            )
            await client.add_edge(Edge(
                edge_type="RESPONDED_TO",
                from_vertex_id=aggregate["sender_ref"],
                to_vertex_id=message_ref,
                properties=props,
            ))
            aggregate["message_promoted"] = True
            await self._mark_flag(aggregate, "message_promoted")
            metrics.increment(
                "comms_graph_messages_promoted_total",
                labels={"tenant_id": tenant_id},
            )
        except Exception as exc:
            logger.warning("comms_message_promotion_failed: %s", exc)

    async def _mark_flag(self, aggregate: dict[str, Any], flag: str) -> None:
        pool = await self._pool()
        if pool is None:
            return
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                UPDATE communication_relationships SET {flag} = true
                WHERE tenant_id=$1 AND sender_ref=$2 AND recipient_ref=$3
                  AND channel=$4 AND edge_type=$5
                """,
                aggregate["tenant_id"], aggregate["sender_ref"],
                aggregate["recipient_ref"], aggregate["channel"],
                aggregate["edge_type"],
            )


def _confidence(row: dict[str, Any]) -> float:
    value = row.get("identity_confidence") or row.get("engagement_confidence")
    try:
        return float(value) if value is not None else 0.5
    except (TypeError, ValueError):
        return 0.5


def _ts(value: Any) -> Any:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)
