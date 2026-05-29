"""Notification Intelligence — Lifecycle Engine

Manages state transitions for IntelligenceNotificationEvent.
Transitions are forward-only and each is recorded in the audit trail.

Also provides start_sla_worker() — a background task that checks for
expired operator_review notifications and advances them to 'expired'.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics
from services.notification_intelligence.models import (
    NotificationLifecycleState,
    LIFECYCLE_TRANSITIONS,
)
from services.notification_intelligence.audit import build_audit_entry

logger = get_logger("aether.notification.lifecycle")

SLA_POLL_INTERVAL_S = 60


class LifecycleError(Exception):
    pass


class LifecycleEngine:
    def __init__(self, repo=None, producer=None, graph=None):
        self._repo = repo
        self._producer = producer
        self._graph = graph

    async def advance(
        self,
        notification_id: str,
        new_state: NotificationLifecycleState,
        actor_user_id: Optional[str] = None,
        actor_role: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict:
        if self._repo is None:
            logger.warning("lifecycle_advance_no_repo notification_id=%s", notification_id)
            return {}

        record = await self._repo.find_by_id(notification_id)
        if not record:
            raise LifecycleError(f"Notification {notification_id!r} not found")

        current = NotificationLifecycleState(record.get("lifecycle_state", "detected"))
        allowed = LIFECYCLE_TRANSITIONS.get(current, [])
        if new_state not in allowed:
            raise LifecycleError(
                f"Invalid transition {current.value} → {new_state.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

        entry = build_audit_entry(
            state=new_state.value,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            metadata=metadata,
        )

        existing_trail = record.get("audit_trail") or []
        if isinstance(existing_trail, str):
            import json
            existing_trail = json.loads(existing_trail)
        existing_trail.append(entry)

        updated = await self._repo.update(notification_id, {
            "lifecycle_state": new_state.value,
            "audit_trail": existing_trail,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

        metrics.increment("aether_notifications_lifecycle_duration_seconds",
                          labels={"from_state": current.value, "to_state": new_state.value})
        logger.info("lifecycle_advanced id=%s %s→%s", notification_id, current.value, new_state.value)
        return updated

    async def on_approve(
        self,
        notification: dict,
        actor_user_id: str,
        config: Any,
        graph=None,
        producer=None,
    ) -> None:
        from shared.events.events import Event, Topic
        graph = graph or self._graph
        producer = producer or self._producer

        gp = notification.get("graph_propagation") or {}
        entity_ids = gp.get("entity_ids", [])

        if entity_ids and graph and getattr(config, "auto_propagate_on_approve", True):
            for entity_id in entity_ids:
                try:
                    vertex = await graph.get_vertex(entity_id)
                    if vertex:
                        vertex.properties["notification_state"] = "acknowledged"
                        vertex.properties["last_operator_review"] = datetime.now(timezone.utc).isoformat()
                        await graph.upsert_vertex(vertex)
                except Exception as exc:
                    logger.warning("graph_update_failed entity=%s error=%s", entity_id, exc)

            if producer:
                await producer.publish(Event(
                    topic=Topic.INTEL_NOTIFICATION_PROPAGATED,
                    tenant_id=notification.get("tenant_id", ""),
                    payload={"notification_id": notification.get("id", ""), "entity_ids": entity_ids},
                ))

        # Link to investigation case if present
        op_ctx = notification.get("operator_context") or {}
        case_id = op_ctx.get("investigation_case_id")
        if case_id and producer:
            await producer.publish(Event(
                topic=Topic.INVESTIGATION_CASE_UPDATED,
                tenant_id=notification.get("tenant_id", ""),
                payload={"case_id": case_id, "notification_id": notification.get("id", ""),
                         "actor_user_id": actor_user_id},
            ))

        if producer:
            await producer.publish(Event(
                topic=Topic.GOVERNANCE_DECISION_EVALUATED,
                tenant_id=notification.get("tenant_id", ""),
                payload={"decision": "operator_approved",
                         "notification_id": notification.get("id", ""),
                         "actor_user_id": actor_user_id},
            ))


async def start_sla_worker(repo=None, producer=None, config_repo=None) -> None:
    """Background worker: expire operator_review notifications past their SLA deadline."""
    from repositories.repos import NotificationIntelligenceRepository
    from shared.events.events import Event, Topic

    _repo = repo
    _producer = producer

    if _repo is None:
        try:
            _repo = NotificationIntelligenceRepository()
        except Exception:
            logger.warning("sla_worker: could not init repository — worker disabled")
            return

    engine = LifecycleEngine(repo=_repo, producer=_producer)

    while True:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            overdue = await _repo.find_many(filters={
                "lifecycle_state": NotificationLifecycleState.OPERATOR_REVIEW.value,
            })
            for record in overdue:
                expires_at = record.get("expires_at")
                if not expires_at:
                    continue
                if expires_at < now_iso:
                    try:
                        await engine.advance(
                            record["id"],
                            NotificationLifecycleState.EXPIRED,
                            actor_user_id="system",
                            actor_role="system",
                            metadata={"reason": "sla_exceeded"},
                        )
                        metrics.increment("aether_notifications_expired_total",
                                          labels={"tenant_id": record.get("tenant_id", ""),
                                                  "severity": record.get("severity", "")})
                        if _producer:
                            await _producer.publish(Event(
                                topic=Topic.INTEL_NOTIFICATION_EXPIRED,
                                tenant_id=record.get("tenant_id", ""),
                                payload={"notification_id": record["id"]},
                            ))
                    except Exception as exc:
                        logger.warning("sla_expire_failed id=%s error=%s", record.get("id"), exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("sla_worker_error: %s", exc)
        await asyncio.sleep(SLA_POLL_INTERVAL_S)
