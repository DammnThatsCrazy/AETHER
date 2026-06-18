"""Maps AgentMail-style webhook event shapes to canonical observation models."""
from __future__ import annotations

from datetime import datetime, timezone

from services.agent_comm_observability.message_models import AgentMessageObservedRecord


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_agentmail_message(raw: dict, tenant_id: str) -> AgentMessageObservedRecord:
    """Normalize an AgentMail webhook message event to canonical model."""
    return AgentMessageObservedRecord(
        thread_obs_id=raw.get("thread_id"),
        inbox_obs_id=raw.get("inbox_id"),
        direction=raw.get("type", "inbound"),
        from_address=raw.get("from"),
        to_addresses=raw.get("to", []),
        subject=raw.get("subject"),
        has_attachments=bool(raw.get("attachments")),
        tenant_id=tenant_id,
        observed_at=raw.get("created_at") or _utc_now(),
    )
