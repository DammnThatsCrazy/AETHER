"""Communication-state reducer — rebuildable per-entity channel state (Phase 8).

Derives subscription/deliverability status and engagement counters for each
(tenant, entity, channel, scope) from silver_comms_facts. The reduction is a
pure function of the facts, so the state can always be rebuilt from scratch —
after identity merges/splits, consent changes, or replays — and produce the
same result (idempotent).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics
from services.comms.repository import (
    CommsFactsRepository,
    CommunicationStateRepository,
)

logger = get_logger("aether.comms.state")

# Events that change subscription status, in order of application.
_UNSUBSCRIBE_EVENTS = frozenset({"unsubscribe_observed"})
_COMPLAINT_EVENTS = frozenset({"email_spam_complaint"})


def reduce_facts(
    facts: list[dict[str, Any]],
    *,
    tenant_id: str,
    entity_id: str,
    channel: str = "email",
    scope: str = "marketing",
) -> dict[str, Any]:
    """Pure reducer: ordered facts → communication state row.

    Facts must be sorted ascending by occurred_at (the repository guarantees
    this). Machine-classified engagement never counts toward human metrics.
    """
    state: dict[str, Any] = {
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "channel": channel,
        "scope": scope,
        "subscription_status": "unknown",
        "deliverability_status": "unknown",
        "last_sent_at": None,
        "last_delivered_at": None,
        "last_reported_open_at": None,
        "last_human_engagement_at": None,
        "last_click_at": None,
        "last_reply_at": None,
        "total_sent": 0,
        "total_delivered": 0,
        "total_reported_opens": 0,
        "total_human_clicks": 0,
        "total_replies": 0,
        "hard_bounce_count": 0,
        "soft_bounce_count": 0,
        "complaint_count": 0,
        "suppression_scope": None,
        "unsubscribe_scope": None,
        "provider_profiles": {},
        "source_freshness_at": None,
        "schema_version": 1,
    }

    for fact in facts:
        event_type = fact.get("source_event_type") or fact.get("comms_type", "")
        occurred = fact.get("occurred_at")
        machine = bool(fact.get("suspected_machine_activity"))
        automated = fact.get("automated_response_kind") is not None

        if occurred is not None:
            state["source_freshness_at"] = _max_ts(state["source_freshness_at"], occurred)

        provider = fact.get("provider")
        if provider and fact.get("provider_account_id"):
            state["provider_profiles"][str(provider)] = str(fact["provider_account_id"])

        if event_type == "email_sent" or event_type == "message_sent_observed":
            state["total_sent"] += 1
            state["last_sent_at"] = _max_ts(state["last_sent_at"], occurred)
            if state["subscription_status"] == "unknown":
                state["subscription_status"] = "subscribed"
        elif event_type in ("email_delivered", "notification_delivered"):
            state["total_delivered"] += 1
            state["last_delivered_at"] = _max_ts(state["last_delivered_at"], occurred)
            state["deliverability_status"] = "deliverable"
            if state["subscription_status"] == "unknown":
                state["subscription_status"] = "subscribed"
        elif event_type in ("email_opened", "notification_opened"):
            state["total_reported_opens"] += 1
            state["last_reported_open_at"] = _max_ts(state["last_reported_open_at"], occurred)
            if not machine:
                state["last_human_engagement_at"] = _max_ts(
                    state["last_human_engagement_at"], occurred
                )
        elif event_type in ("email_clicked", "notification_clicked"):
            if not machine:
                state["total_human_clicks"] += 1
                state["last_click_at"] = _max_ts(state["last_click_at"], occurred)
                state["last_human_engagement_at"] = _max_ts(
                    state["last_human_engagement_at"], occurred
                )
        elif event_type in ("email_replied", "message_replied_observed"):
            if not automated:
                state["total_replies"] += 1
                state["last_reply_at"] = _max_ts(state["last_reply_at"], occurred)
                state["last_human_engagement_at"] = _max_ts(
                    state["last_human_engagement_at"], occurred
                )
        elif event_type == "email_bounced":
            if (fact.get("bounce_type") or "soft") == "hard":
                state["hard_bounce_count"] += 1
                state["deliverability_status"] = "hard_bounced"
            else:
                state["soft_bounce_count"] += 1
                if state["deliverability_status"] not in ("hard_bounced",):
                    state["deliverability_status"] = "soft_bounced"
        elif event_type in _COMPLAINT_EVENTS:
            state["complaint_count"] += 1
            state["subscription_status"] = "complained"
        elif event_type in _UNSUBSCRIBE_EVENTS:
            state["subscription_status"] = "unsubscribed"
            state["unsubscribe_scope"] = fact.get("unsubscribe_scope") or "marketing_channel"
        elif event_type == "email_suppressed":
            state["subscription_status"] = "suppressed"
            state["suppression_scope"] = fact.get("suppression_scope") or "provider_account"

    state["computed_at"] = datetime.now(timezone.utc).isoformat()
    return state


class CommunicationStateService:
    """Rebuilds and serves communication state. Update path is asynchronous:
    projection workers call ``rebuild_for_entity`` after relevant facts land,
    identity merge/split handlers call it for both sides."""

    def __init__(self) -> None:
        self._facts = CommsFactsRepository()
        self._states = CommunicationStateRepository()

    async def rebuild_for_entity(
        self, tenant_id: str, entity_id: str,
        *, channel: str = "email", scope: str = "marketing",
    ) -> dict[str, Any]:
        facts = await self._facts.facts_for_state_rebuild(tenant_id, entity_id, channel)
        state = reduce_facts(
            facts, tenant_id=tenant_id, entity_id=entity_id,
            channel=channel, scope=scope,
        )
        await self._states.upsert(state)
        metrics.increment(
            "comms_state_rebuilds_total",
            labels={"tenant_id": tenant_id, "channel": channel},
        )
        return state

    async def get(
        self, tenant_id: str, entity_id: str,
        *, channel: str = "email", scope: str = "marketing",
    ) -> Optional[dict[str, Any]]:
        return await self._states.get(tenant_id, entity_id, channel, scope)

    async def list_for_entity(self, tenant_id: str, entity_id: str) -> list[dict[str, Any]]:
        return await self._states.list_for_entity(tenant_id, entity_id)


def _max_ts(current: Any, candidate: Any) -> Any:
    if current is None:
        return candidate
    if candidate is None:
        return current
    return max(str(current), str(candidate)) if not (
        isinstance(current, datetime) and isinstance(candidate, datetime)
    ) else max(current, candidate)
