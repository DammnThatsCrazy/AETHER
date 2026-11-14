"""Canonical provider-thread observations authored with durable Silver facts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from journeys.communication360.composition import event_time


def provider_thread_observation(row: dict[str, Any]) -> dict[str, Any] | None:
    row = dict(row)
    if isinstance(row.get("fact_id"), UUID):
        row["fact_id"] = str(row["fact_id"])
    for key in ("occurred_at", "received_at"):
        if isinstance(row.get(key), datetime):
            row[key] = row[key].isoformat()
    required = (
        "tenant_id", "fact_id", "message_id", "provider", "provider_account_id",
        "external_thread_id", "external_message_id", "occurred_at",
    )
    if any(not isinstance(row.get(key), str) or not row[key].strip() for key in required):
        return None
    if event_time(row["occurred_at"]) is None:
        return None
    scope = {key: row[key] for key in required}
    digest = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
    thread_scope = {key: row[key] for key in (
        "tenant_id", "provider", "provider_account_id", "external_thread_id",
    )}
    thread_digest = hashlib.sha256(json.dumps(thread_scope, sort_keys=True).encode()).hexdigest()
    payload = {
        "producer": "silver_comms_observation_writer.v1",
        "tenant_id": row["tenant_id"],
        "thread_id": f"provider-thread:{thread_digest[:32]}",
        "provider": row["provider"],
        "provider_account_id": row["provider_account_id"],
        "external_thread_id": row["external_thread_id"],
        "message_ids": [row["message_id"]],
        "silver_fact_id": row["fact_id"],
        "external_message_id": row["external_message_id"],
        "message_occurred_at": row["occurred_at"],
        "claim_state": "observed",
        "history_completeness": "unknown",
        "canonical_conversation_membership": "unknown",
        "evidence_refs": [{
            "id": row["fact_id"], "type": "event",
            "source": "services/api/journeys/comms/silver_comms_facts",
            "observedAt": row["occurred_at"],
        }],
    }
    for key in ("campaign_id", "source_connector_id"):
        if isinstance(row.get(key), str) and row[key]:
            payload["source_id" if key == "source_connector_id" else key] = row[key]
    return {
        "fact_id": f"communication360_thread_{digest[:32]}",
        "tenant_id": row["tenant_id"],
        "kind": "provider_thread",
        "source_event_id": row.get("source_event_id"),
        "source_event_type": row.get("source_event_type"),
        "actor_id": None,
        "agent_id": None,
        "occurred_at": row["occurred_at"],
        "received_at": row.get("received_at") or row["occurred_at"],
        "idempotency_key": f"provider-thread-observation:{digest}",
        "payload": payload,
    }
