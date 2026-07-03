"""Canonical agentic observation ingestion pipeline.

This is the PR-2 bridge from route-specific JSONB writes toward the canonical
Aether medallion pipeline. It writes sanitized Bronze lineage, typed Silver
facts, canonical_activity, and durable projection outbox records atomically at
application level for the local/BaseRepository abstraction. Formal SQL
migrations and workerized outbox draining remain the next PR-2 hardening step.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from repositories.agentic_observability_repos import (
    AgentActivityRepository,
    AgenticProjectionOutboxRepository,
    SilverAgentActivityFactRepository,
    SilverAgentRiskFactRepository,
    SilverAgentToolInvocationFactRepository,
    SilverMCPConnectionFactRepository,
)
from repositories.lake import BronzeRepository, ProvenanceStatus
from services.agentic_observability.models import AgenticObservationRecord
from services.measurement.contracts import ActivityFamily, ActivityStatus, CanonicalActivity
from services.measurement.repositories.activity_repo import ActivityRepository
from shared.common.common import utc_now
from shared.graph.graph import Edge, Vertex
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.agentic_observability.pipeline")

_SENSITIVE_KEYS = {
    "access_token", "refresh_token", "authorization", "authorization_header",
    "api_key", "secret", "client_secret", "password", "cookie", "private_key",
}


@dataclass
class AgenticPipelineResult:
    observation_id: str
    bronze_id: str
    silver_table: str
    silver_fact_id: str
    canonical_activity_id: str
    outbox_records_created: int
    duplicate: bool = False


def _stable_hash(data: Any) -> str:
    return hashlib.sha256(str(data).encode()).hexdigest()


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in _SENSITIVE_KEYS:
                cleaned[key] = "[REDACTED]"
            else:
                cleaned[key] = _sanitize(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _fact_table_for_event(event_name: str) -> tuple[str, Any]:
    if event_name in {"agent_tool_observed", "agent_tool_invocation_observed"}:
        return "silver_agent_tool_invocation_facts", SilverAgentToolInvocationFactRepository()
    if event_name == "agent_mcp_connection_observed":
        return "silver_mcp_connection_facts", SilverMCPConnectionFactRepository()
    if event_name == "agent_risk_signal_observed":
        return "silver_agent_risk_facts", SilverAgentRiskFactRepository()
    return "silver_agent_activity_facts", SilverAgentActivityFactRepository()


def _agent_id(record: AgenticObservationRecord) -> str:
    return record.actor.actor_id or (record.agent.agent_id if record.agent else "")


def _base_fact(record: AgenticObservationRecord, bronze_id: str, received_at: str) -> dict[str, Any]:
    agent_id = _agent_id(record)
    return {
        "id": _stable_hash(f"{record.tenant_id}:{record.observation_id}:silver")[:32],
        "tenant_id": record.tenant_id,
        "idempotency_key": _stable_hash(f"{record.tenant_id}:{record.observation_id}:{record.event_name}"),
        "source_event_id": record.observation_id,
        "source_provider": record.source.provider.value,
        "agent_id": agent_id,
        "trace_id": record.observation_id,
        "status": record.action.status,
        "verification_status": "unverified",
        "observed_at": record.observed_at,
        "received_at": received_at,
        "processed_at": received_at,
        "schema_version": record.provenance.schema_version,
        "privacy_class": "metadata",
        "retention_class": "standard",
        "evidence_ref": f"bronze:{bronze_id}",
        "object_id": record.object.object_id,
        "object_type": record.object.object_type,
        "action_name": record.action.name,
        "raw_payload_hash": record.provenance.raw_event_hash,
        "created_at": received_at,
        "updated_at": received_at,
    }


def _activity_type(event_name: str) -> str:
    return {
        "agent_mcp_connection_observed": "mcp_connection_observed",
        "agent_tool_observed": "tool_observed",
        "agent_tool_invocation_observed": "tool_invocation_observed",
        "agent_risk_signal_observed": "risk_detected",
    }.get(event_name, "agent_activity_observed")


class AgenticIngestionPipeline:
    """Project accepted agentic observations through Bronze/Silver/activity/outbox."""

    async def ingest_record(
        self,
        record: AgenticObservationRecord,
        *,
        raw_payload: dict[str, Any],
        graph_mutations: list[Any],
    ) -> AgenticPipelineResult:
        received_at = utc_now().isoformat()
        sanitized_payload = _sanitize(raw_payload)
        sanitized_payload.update({
            "tenant_id": record.tenant_id,
            "observation_id": record.observation_id,
            "event_name": record.event_name,
            "payload_hash": _stable_hash(sanitized_payload),
            "secret_scan_status": "redacted" if sanitized_payload != raw_payload else "clean",
            "redaction_policy_version": "agentic-pr2-1",
            "privacy_class": "metadata",
            "retention_class": "standard",
            "received_at": received_at,
        })

        bronze = BronzeRepository("agentic_observations")
        bronze_record, is_new = await bronze.ingest(
            source="agentic_observability",
            source_tag=f"agentic:{record.event_name}",
            provider_record_id=record.observation_id,
            payload=sanitized_payload,
            schema_version=record.provenance.schema_version,
            entity_id=_agent_id(record) or record.object.object_id or record.observation_id,
            entity_type="agentic_observation",
            tenant_id=record.tenant_id,
            provenance_status=ProvenanceStatus.VALID.value,
            license_status="public_api",
            terms_status="approved",
            sensitivity_classification="metadata",
        )

        # Keep the existing Kyber/basic observation repository in sync while the
        # typed tables become the source of truth over subsequent PR-2 work.
        await AgentActivityRepository().insert(record.observation_id, record.model_dump(mode="json"))

        silver_table, silver_repo = _fact_table_for_event(record.event_name)
        fact = _base_fact(record, bronze_record["id"], received_at)
        await silver_repo.insert(fact["id"], fact)

        activity = CanonicalActivity(
            tenant_id=record.tenant_id,
            idempotency_key=fact["idempotency_key"],
            agent_id=fact.get("agent_id") or None,
            activity_family=ActivityFamily.agent,
            activity_type=_activity_type(record.event_name),
            actor_type=record.actor.actor_type.value,
            source="agentic_observability",
            platform=record.source.provider.value,
            occurred_at=record.observed_at,
            server_received_at=received_at,
            activity_status=ActivityStatus.observed,
            source_event_id=record.observation_id,
            source_system="agentic_observability",
            privacy_class="metadata",
            silver_fact_id=fact["id"],
            silver_table=silver_table,
        ).model_dump(mode="json")
        activity_row = await ActivityRepository().upsert(activity)
        activity_id = str(activity_row.get("activity_id") or activity.get("activity_id"))

        outbox_count = 0
        outbox = AgenticProjectionOutboxRepository()
        for idx, mutation in enumerate(graph_mutations):
            payload = _mutation_payload(mutation)
            outbox_id = _stable_hash(f"{record.tenant_id}:{record.observation_id}:graph:{idx}:{payload}")[:32]
            await outbox.insert(outbox_id, {
                "outbox_id": outbox_id,
                "tenant_id": record.tenant_id,
                "source_event_id": record.observation_id,
                "canonical_activity_id": activity_id,
                "mutation_domain": "graph",
                "mutation_type": payload.get("kind", "unknown"),
                "payload": payload,
                "idempotency_key": outbox_id,
                "status": "queued",
                "attempt_count": 0,
                "next_attempt_at": received_at,
                "last_attempt_at": None,
                "last_error_code": None,
                "last_error_message": None,
                "created_at": received_at,
                "completed_at": None,
                "dead_lettered_at": None,
            })
            outbox_count += 1

        metrics.increment("agentic_ingestion_pipeline_accepted_total", labels={"event_name": record.event_name})
        logger.info(
            "agentic_pipeline_ingested",
            extra={
                "extra_data": {
                    "tenant_id": record.tenant_id,
                    "event_id": record.observation_id,
                    "event_type": record.event_name,
                    "silver_table": silver_table,
                    "outbox_records": outbox_count,
                }
            },
        )
        return AgenticPipelineResult(
            observation_id=record.observation_id,
            bronze_id=bronze_record["id"],
            silver_table=silver_table,
            silver_fact_id=fact["id"],
            canonical_activity_id=activity_id,
            outbox_records_created=outbox_count,
            duplicate=not is_new,
        )


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _mutation_payload(mutation: Any) -> dict[str, Any]:
    if isinstance(mutation, Vertex):
        return {
            "kind": "vertex",
            "vertex_type": _enum_value(mutation.vertex_type),
            "vertex_id": mutation.vertex_id,
            "properties": mutation.properties,
        }
    if isinstance(mutation, Edge):
        return {
            "kind": "edge",
            "edge_type": _enum_value(mutation.edge_type),
            "from_vertex_id": mutation.from_vertex_id,
            "to_vertex_id": mutation.to_vertex_id,
            "properties": mutation.properties,
        }
    return {"kind": type(mutation).__name__, "value": str(mutation)}
