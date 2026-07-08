"""
Agentic Observability Ingestion Pipeline (Bronze → Silver → Canonical → Outbox).

INVARIANT: Pipeline writes observations. It never executes provider actions.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from repositories.agentic_observability_repos import (
    AgentActivityRepository,
    AgenticBronzeObservationRepository,
    AgenticProjectionOutboxRepository,
    SilverAgentActivityFactRepository,
    SilverAgentRiskFactRepository,
    SilverAgentToolInvocationFactRepository,
    SilverMCPConnectionFactRepository,
)
from repositories.lake import ProvenanceStatus
from services.agentic_observability.models import AgenticObservationRecord
from services.measurement.repositories.activity_repo import ActivityRepository
from shared.common.common import utc_now
from shared.logger.logger import get_logger

logger = get_logger("aether.agentic_observability.pipeline")

_SENSITIVE_BARE = frozenset({
    "password", "secret", "token", "apikey", "privatekey",
    "ssn", "dob", "creditcard", "cardnumber", "cvv", "pin",
    "authorization", "xapikey", "xauthtoken", "accesstoken",
    "clientsecret", "refreshtoken",
})

_NORMALIZE_RE = re.compile(r"[^a-z0-9]")


def _bare_key(k: str) -> str:
    """Normalize a key to bare lowercase alphanumeric for matching.

    Collapses camelCase, underscores, and hyphens so accessToken, access_token,
    and access-token all map to accesstoken before comparison.
    """
    # Insert _ before uppercase transitions (camelCase → snake_case) then strip all non-alnum
    snake = re.sub(r"([A-Z])", r"_\1", k).lower()
    return _NORMALIZE_RE.sub("", snake)


def _sanitize(data: Any, depth: int = 0) -> Any:
    """Redact sensitive keys from nested dicts (handles camelCase and snake_case)."""
    if depth > 10:
        return data
    if isinstance(data, dict):
        return {
            k: "[REDACTED]" if _bare_key(k) in _SENSITIVE_BARE else _sanitize(v, depth + 1)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_sanitize(item, depth + 1) for item in data]
    return data


_EVENT_TO_SILVER: dict[str, str] = {
    "agent_tool_invoked": "silver_agent_tool_invocation_facts",
    "agent_tool_completed": "silver_agent_tool_invocation_facts",
    "mcp_connection_observed": "silver_mcp_connection_facts",
    "mcp_server_connected": "silver_mcp_connection_facts",
    "agent_risk_signal": "silver_agent_risk_facts",
}


def _fact_table_for_event(event_name: str) -> str:
    return _EVENT_TO_SILVER.get(event_name, "silver_agent_activity_facts")


def _base_fact(record: AgenticObservationRecord) -> dict[str, Any]:
    return {
        "observation_id": record.observation_id,
        "tenant_id": record.tenant_id,
        "event_name": record.event_name,
        "agent_id": record.agent.agent_id if record.agent else None,
        "observed_at": record.observed_at,
        "source_provider": record.source.provider.value,
    }


def _activity_type(record: AgenticObservationRecord) -> str:
    return record.event_name.replace("_observed", "").replace("_", ".")


@dataclass
class AgenticPipelineResult:
    observation_id: str
    bronze_id: Optional[str] = None
    silver_id: Optional[str] = None
    activity_id: Optional[str] = None
    outbox_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors


class AgenticIngestionPipeline:
    """Bronze → Silver → CanonicalActivity → ProjectionOutbox pipeline."""

    def __init__(self) -> None:
        self._bronze = AgenticBronzeObservationRepository()
        self._silver_dispatch: dict[str, Any] = {
            "silver_agent_tool_invocation_facts": SilverAgentToolInvocationFactRepository(),
            "silver_mcp_connection_facts": SilverMCPConnectionFactRepository(),
            "silver_agent_risk_facts": SilverAgentRiskFactRepository(),
            "silver_agent_activity_facts": SilverAgentActivityFactRepository(),
        }
        self._activity_repo = ActivityRepository()
        self._obs_repo = AgentActivityRepository()
        self._outbox = AgenticProjectionOutboxRepository()

    async def ingest_record(
        self,
        record: AgenticObservationRecord,
        raw_payload: dict[str, Any],
        graph_mutations: list[Any],
    ) -> AgenticPipelineResult:
        result = AgenticPipelineResult(observation_id=record.observation_id)
        sanitized = _sanitize(raw_payload)

        # Derive a stable Bronze ID from the provider's event id so retries are idempotent.
        provider_event_id = (
            (record.source.provider_event_id or record.observation_id)
            if record.source else record.observation_id
        )
        bronze_id = hashlib.sha256(
            f"{record.tenant_id}:{provider_event_id}".encode()
        ).hexdigest()[:36]

        # Bronze write
        try:
            await self._bronze.insert(bronze_id, {
                "id": bronze_id,
                "observation_id": record.observation_id,
                "tenant_id": record.tenant_id,
                "event_name": record.event_name,
                "payload": sanitized,
                "provenance_status": ProvenanceStatus.VALID.value,
                "source": "agentic_observability",
                "source_tag": record.source.provider.value,
                "ingested_at": utc_now().isoformat(),
            })
            result.bronze_id = bronze_id
        except Exception as exc:
            logger.warning("bronze write failed", extra={"error": str(exc)})
            result.errors.append(f"bronze:{type(exc).__name__}")

        # Kyber compat: upsert into obs_agent_activities
        try:
            await self._obs_repo.insert(record.observation_id, record.model_dump(mode="json"))
        except Exception as exc:
            logger.warning("obs_repo upsert failed", extra={"error": str(exc)})

        # Silver fact write
        try:
            silver_table = _fact_table_for_event(record.event_name)
            silver_repo = self._silver_dispatch.get(silver_table, self._silver_dispatch["silver_agent_activity_facts"])
            silver_id = str(uuid.uuid4())
            await silver_repo.insert(silver_id, {**_base_fact(record), "silver_id": silver_id})
            result.silver_id = silver_id
        except Exception as exc:
            logger.warning("silver write failed", extra={"error": str(exc)})
            result.errors.append(f"silver:{type(exc).__name__}")

        # CanonicalActivity write
        try:
            agent_id = record.agent.agent_id if record.agent else None
            canonical: dict[str, Any] = {
                "tenant_id": record.tenant_id,
                "idempotency_key": f"agentic:{record.observation_id}",
                "activity_family": "agentic",
                "activity_type": _activity_type(record),
                "actor_type": record.actor.actor_type.value,
                "agent_id": agent_id,
                "occurred_at": record.observed_at,
                "activity_status": "observed",
                "source_event_id": record.observation_id,
                "source_system": "agentic_observability",
                "silver_fact_id": result.silver_id,
                "silver_table": _fact_table_for_event(record.event_name),
                "schema_version": 2,
            }
            activity = await self._activity_repo.upsert(canonical)
            result.activity_id = str(activity.get("activity_id", ""))
        except Exception as exc:
            logger.warning("canonical_activity write failed", extra={"error": str(exc)})
            result.errors.append(f"canonical_activity:{type(exc).__name__}")

        # Outbox: enqueue each graph mutation
        for mutation in graph_mutations:
            try:
                outbox_id = str(uuid.uuid4())
                if isinstance(mutation, dict):
                    payload = mutation
                elif hasattr(mutation, "model_dump"):
                    payload = mutation.model_dump(mode="json")
                else:
                    payload = vars(mutation)
                mutation_type = "vertex" if "vertex_type" in payload else "edge"
                await self._outbox.insert(outbox_id, {
                    "outbox_id": outbox_id,
                    "tenant_id": record.tenant_id,
                    "observation_id": record.observation_id,
                    "mutation_type": mutation_type,
                    "payload": payload,
                    "status": "queued",
                    "attempts": 0,
                    "created_at": utc_now().isoformat(),
                })
                result.outbox_ids.append(outbox_id)
            except Exception as exc:
                logger.warning("outbox enqueue failed", extra={"error": str(exc)})
                result.errors.append(f"outbox:{type(exc).__name__}")

        return result
