"""
Agentic Observability → canonical durable ingestion spine.

INVARIANT: This module writes OBSERVATIONS. It never executes, originates,
signs, or settles a provider action.

Agentic observations are routed THROUGH the one canonical durable spine used by
every other SDK event: a typed Bronze row + an ``event_outbox`` row written in a
SINGLE transaction (``services.ingestion.bronze_bulk.ingest_many``). The relay
worker drains the outbox, publishes ``Topic.SDK_EVENTS_VALIDATED``, and the
SilverDispatcher fans the event out to the AgentExecutionProjector (→
``silver_agent_execution_facts`` + canonical_activity) and the
SilverGraphProjector (→ bounded graph mutations).

There is no parallel Bronze/Silver/canonical/outbox architecture here anymore:
the old bespoke medallion writer (``AgenticIngestionPipeline.ingest_record`` and
the ``_EVENT_TO_SILVER`` map) has been removed. The only side store this module
still touches is the legacy ``obs_agent_activities`` compat table, so the
existing Kyber read routes keep returning counts.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from services.ingestion.bronze_bulk import BronzeSDKEvent, OutboxEvent, ingest_many
from services.ingestion.generated_registry import CANONICAL_EVENT_TYPES
from services.ingestion.validation import (
    SCHEMA_VERSION,
    get_event_family,
    scrub_sensitive_fields,
    strip_canonical_entity_id,
)
from shared.common.common import utc_now
from shared.events.events import Topic
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.agentic_observability.pipeline")

_SOURCE = "agentic_observability"


@dataclass(frozen=True)
class ObservationIngestResult:
    """Outcome of a single canonical-spine observation ingest."""

    event_id: str
    status: str  # "accepted" | "duplicate"
    outbox_written: int = 0

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"


def compute_event_id(
    *,
    tenant_id: str,
    provider_id: str,
    event_type: str,
    integration_id: Optional[str],
    environment_id: Optional[str],
    provider_event_id: Optional[str],
) -> str:
    """Deterministic, event-type/provider/integration/environment/tenant-namespaced id.

    A stable ``provider_event_id`` yields a deterministic 32-char key so retries
    of the same external event dedupe at the Bronze uniqueness boundary. Absent a
    provider event id there is nothing to dedupe on, so a fresh uuid is used
    (unique, but non-idempotent).

    ``event_type`` is part of the namespace so two DIFFERENT observations that
    happen to share a ``provider_event_id`` (e.g. a status transition emitted as
    a distinct event, or two endpoints observing the same entity) do not collide
    and silently drop one at the Bronze uniqueness boundary.
    """
    if provider_event_id:
        raw = f"{tenant_id}:{provider_id}:{event_type}:{integration_id or ''}:{environment_id or ''}:{provider_event_id or ''}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
    return uuid.uuid4().hex


async def ingest_observation(
    *,
    tenant_id: str,
    event_name: str,
    provider_id: str,
    integration_id: str | None = None,
    environment_id: str | None = None,
    provider_event_id: str | None = None,
    actor_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    anonymous_id: str | None = None,
    user_id: str | None = None,
    observed_at: str | None = None,
    properties: dict | None = None,
    context_extra: dict | None = None,
) -> "ObservationIngestResult":
    """Persist one agentic observation through the canonical durable spine.

    Writes exactly ONE typed Bronze row + ONE ``event_outbox`` row in a single
    transaction (via ``ingest_many``). The relay + SilverDispatcher own every
    downstream Silver / canonical / graph write; nothing bespoke is written here
    except the legacy ``obs_agent_activities`` compat upsert.
    """
    if event_name not in CANONICAL_EVENT_TYPES:
        raise ValueError(
            f"Unknown event_name {event_name!r}; use a canonical event registry value"
        )

    now_iso = utc_now().isoformat()
    observed_at = observed_at or now_iso

    event_id = compute_event_id(
        tenant_id=tenant_id,
        provider_id=provider_id,
        event_type=event_name,
        integration_id=integration_id,
        environment_id=environment_id,
        provider_event_id=provider_event_id,
    )

    # Recursively scrub secrets/keys/tokens/authorization before persistence, and
    # drop any client-asserted canonical entity id (mirrors build_normalized_payload).
    scrubbed_props, props_sensitive = scrub_sensitive_fields(dict(properties or {}))
    scrubbed_props = strip_canonical_entity_id(scrubbed_props)

    context: dict[str, Any] = {
        "tenantId": tenant_id,
        "actorId": actor_id,
        "agentId": agent_id,
        "provider": provider_id,
        "integrationId": integration_id,
        "environment": environment_id,
        **(context_extra or {}),
    }
    context, ctx_sensitive = scrub_sensitive_fields(context)
    context = strip_canonical_entity_id(context)
    if props_sensitive or ctx_sensitive:
        metrics.increment("agentic_obs_sensitive_scrub_total")

    normalized: dict[str, Any] = {
        "event_id": event_id,
        "tenant_id": tenant_id,
        "event_type": event_name,
        "event_family": get_event_family(event_name),
        "session_id": session_id,
        "anonymous_id": anonymous_id,
        "user_id": user_id,
        "properties": scrubbed_props,
        "context": context,
        "timestamp": observed_at,
        "received_at": now_iso,
        "ingested_at": now_iso,
        "batch_id": f"{_SOURCE}:{tenant_id}",
        "schema_version": SCHEMA_VERSION,
        "source": _SOURCE,
    }

    entity_id = agent_id or actor_id or user_id or anonymous_id or session_id or tenant_id

    bronze = BronzeSDKEvent(
        tenant_id=tenant_id,
        event_id=event_id,
        schema_version=SCHEMA_VERSION,
        batch_id=normalized["batch_id"],
        event_type=event_name,
        event_family=normalized["event_family"],
        event_timestamp=observed_at,
        received_at=now_iso,
        session_id=session_id or "",
        anonymous_id=anonymous_id or "",
        user_id=user_id,
        entity_id=entity_id,
        payload=normalized,
        source=_SOURCE,
        source_tag=provider_id,
    )
    outbox = OutboxEvent(
        tenant_id=tenant_id,
        event_id=event_id,
        topic=Topic.SDK_EVENTS_VALIDATED.value,
        partition_key=agent_id or session_id or tenant_id,
        payload=normalized,
    )

    result = await ingest_many([bronze], [outbox])
    status = result.statuses[0] if result.statuses else "duplicate"

    # Legacy per-type compat writes (obs_agent_tools / obs_agent_connections /
    # obs_agent_risk_signals / obs_agent_activities) are owned by the calling
    # routes so each Kyber read surface counts its own store accurately; the
    # spine writer stays canonical-only and does not inflate a catch-all table.

    metrics.increment(
        "agentic_obs_canonical_ingest_total",
        labels={"status": status, "provider": provider_id},
    )
    return ObservationIngestResult(
        event_id=event_id,
        status=status,
        outbox_written=result.outbox_written,
    )
