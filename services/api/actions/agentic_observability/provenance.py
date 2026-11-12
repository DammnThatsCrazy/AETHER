"""Durable lineage from agentic compatibility evidence to canonical Bronze.

The agentic compatibility tables remain read adapters for existing consumers.
When an observation also enters the canonical ingestion spine, this module
records an exact tenant-scoped link in the immutable Bronze payload and
provides a bounded reader that verifies both ends of that link. Provider names
are retained as source assertions; without a Rights ``source_id`` or a
configured freshness SLA, source identity/trust and stale-vs-fresh status stay
unknown.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from graph.operational_intelligence.models import EvidenceRef

AGENTIC_OBSERVABILITY_SOURCE = "agentic_observability"
AGENTIC_OBSERVABILITY_ADAPTER_VERSION = "1.0"
AGENT_EVIDENCE_TABLES = frozenset(
    {"obs_agent_activities", "obs_agent_tools", "obs_agent_risk_signals"}
)
MAX_AGENTIC_PROVENANCE_READ = 600


class AgentEvidenceReference(BaseModel):
    """Server-constructed reference to one persisted agentic evidence row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    source: Literal[
        "obs_agent_activities", "obs_agent_tools", "obs_agent_risk_signals"
    ]
    id: str = Field(min_length=1)
    observed_at: Optional[str] = None
    event_type: str = Field(min_length=1)

    def evidence_ref(self) -> EvidenceRef:
        return EvidenceRef(
            id=self.id,
            type="event",
            source=self.source,
            observedAt=self.observed_at,
        )


class AgenticEvidenceProvenanceRecord(BaseModel):
    """Provenance captured with an agentic event in canonical Bronze.

    ``source_provider_claim`` comes from the authenticated observation request's
    source envelope, but it has not been joined to a registered source or
    Rights grant. It must not be rendered as a verified source identity.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    tenant_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    bronze_event_id: str = Field(min_length=1)
    bronze_schema_version: str = Field(min_length=1)
    bronze_event_type: str = Field(min_length=1)
    evidence_ref: EvidenceRef
    bronze_evidence_ref: EvidenceRef
    source_system: Literal["agentic_observability"] = AGENTIC_OBSERVABILITY_SOURCE
    source_provider_claim: Optional[str] = None
    source_provider_claim_state: Literal["source_asserted", "missing"]
    source_id: None = None
    source_identity_state: Literal["unresolved"] = "unresolved"
    source_trust: Literal["unknown"] = "unknown"
    credential_class: None = None
    signature_status: None = None
    adapter: Literal["agentic_observability"] = AGENTIC_OBSERVABILITY_SOURCE
    adapter_version: str = AGENTIC_OBSERVABILITY_ADAPTER_VERSION
    observed_at: Optional[str] = None
    received_at: str = Field(min_length=1)
    ingested_at: str = Field(min_length=1)
    freshness_state: Literal["not_assessed", "undated"]
    freshness_sla_seconds: None = None
    freshness_reason: Literal["agentic_source_freshness_sla_not_configured"] = (
        "agentic_source_freshness_sla_not_configured"
    )

    @model_validator(mode="after")
    def _same_tenant_and_event(self) -> "AgenticEvidenceProvenanceRecord":
        if self.evidence_ref.source not in AGENT_EVIDENCE_TABLES:
            raise ValueError("agentic provenance must reference an owned evidence table")
        if self.evidence_ref.type != "event":
            raise ValueError("agentic compatibility evidence must use event evidence type")
        if self.bronze_evidence_ref.source != "bronze_sdk_events":
            raise ValueError("agentic provenance must cite canonical Bronze evidence")
        if self.bronze_evidence_ref.type != "event":
            raise ValueError("canonical Bronze evidence must use event evidence type")
        if self.bronze_evidence_ref.id != self.bronze_event_id:
            raise ValueError("Bronze evidence reference must match the canonical event id")
        if self.bronze_evidence_ref.observedAt != self.observed_at:
            raise ValueError("Bronze evidence timestamp must match the observed timestamp")
        expected_freshness = "not_assessed" if self.observed_at else "undated"
        if self.freshness_state != expected_freshness:
            raise ValueError("freshness state must reflect timestamp availability only")
        if not self.source_provider_claim and self.source_provider_claim_state != "missing":
            raise ValueError("missing provider claim must remain explicitly missing")
        if self.source_provider_claim and self.source_provider_claim_state != "source_asserted":
            raise ValueError("provider claim state must not imply verified source identity")
        return self


@dataclass(frozen=True)
class AgenticProvenanceQuery:
    """Exact evidence-to-Bronze key supplied by a tenant-scoped 360 reader."""

    bronze_event_id: str
    bronze_schema_version: str
    evidence_ref: AgentEvidenceReference


@dataclass(frozen=True)
class AgenticProvenanceReadBatch:
    rows: list[dict[str, Any]]
    truncated: bool = False
    scope_mismatch: bool = False
    scope_known: bool = True


def build_agentic_provenance_record(
    *,
    tenant_id: str,
    bronze_event_id: str,
    bronze_schema_version: str,
    bronze_event_type: str,
    reference: AgentEvidenceReference,
    provider_claim: Optional[str],
    observed_at: Optional[str],
    received_at: str,
    ingested_at: str,
) -> AgenticEvidenceProvenanceRecord:
    """Build the event's durable lineage record without upgrading claims."""
    if not tenant_id or reference.tenant_id != tenant_id:
        raise ValueError("agentic evidence reference tenant must match the Bronze tenant")
    if not bronze_event_id:
        raise ValueError("canonical Bronze event id is required")
    if not bronze_schema_version or not bronze_event_type:
        raise ValueError("canonical Bronze schema and event type are required")
    if reference.event_type != bronze_event_type:
        raise ValueError("compatibility evidence event type must match canonical Bronze")
    if not reference.agent_id.strip() or not reference.id.strip():
        raise ValueError("agentic evidence reference requires exact agent and record ids")
    if reference.observed_at != observed_at:
        raise ValueError("agentic evidence reference timestamp must match the event timestamp")

    return AgenticEvidenceProvenanceRecord(
        tenant_id=tenant_id,
        agent_id=reference.agent_id,
        bronze_event_id=bronze_event_id,
        bronze_schema_version=bronze_schema_version,
        bronze_event_type=bronze_event_type,
        evidence_ref=reference.evidence_ref(),
        bronze_evidence_ref=EvidenceRef(
            id=bronze_event_id,
            type="event",
            source="bronze_sdk_events",
            observedAt=observed_at,
        ),
        source_provider_claim=(
            provider_claim
            if provider_claim and provider_claim.strip().lower() != "unknown"
            else None
        ),
        source_provider_claim_state=(
            "source_asserted"
            if provider_claim and provider_claim.strip().lower() != "unknown"
            else "missing"
        ),
        observed_at=observed_at,
        received_at=received_at,
        ingested_at=ingested_at,
        freshness_state="not_assessed" if observed_at else "undated",
    )


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _same_instant(value: Any, expected: Optional[str]) -> bool:
    if expected is None:
        return True
    try:
        if isinstance(value, datetime):
            actual = value
        elif isinstance(value, str):
            actual = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            return False
        wanted = datetime.fromisoformat(expected.replace("Z", "+00:00"))
        if actual.tzinfo is None or wanted.tzinfo is None:
            return False
        return actual.timestamp() == wanted.timestamp()
    except (TypeError, ValueError, OverflowError):
        return False


async def read_agentic_provenance_records(
    *,
    tenant_id: str,
    queries: list[AgenticProvenanceQuery],
) -> AgenticProvenanceReadBatch:
    """Read and verify exact Bronze event links for a bounded tenant request.

    This performs no provider/time correlation. Every returned provenance
    record must match the requested Bronze event id, tenant, agent, evidence
    table and evidence record id on the stored Bronze payload.
    """
    if not tenant_id:
        return AgenticProvenanceReadBatch(rows=[], scope_known=False)
    if not queries:
        return AgenticProvenanceReadBatch(rows=[])

    by_event: dict[tuple[str, str], AgenticProvenanceQuery] = {}
    scope_mismatch = False
    for query in queries:
        event_id = (
            query.bronze_event_id.strip()
            if isinstance(query.bronze_event_id, str)
            else ""
        )
        schema_version = (
            query.bronze_schema_version.strip()
            if isinstance(query.bronze_schema_version, str)
            else ""
        )
        key = (event_id, schema_version)
        if (
            not event_id
            or not schema_version
            or query.evidence_ref.tenant_id != tenant_id
            or key in by_event
        ):
            scope_mismatch = True
            continue
        by_event[key] = query

    if not by_event:
        return AgenticProvenanceReadBatch(rows=[], scope_mismatch=scope_mismatch)
    if len(by_event) > MAX_AGENTIC_PROVENANCE_READ:
        return AgenticProvenanceReadBatch(
            rows=[], truncated=True, scope_mismatch=scope_mismatch
        )

    from repositories.repos import _IN_MEMORY_STORES, get_pool

    expected_keys = set(by_event)
    expected_event_ids = {event_id for event_id, _ in expected_keys}
    pool = await get_pool()
    if pool is None:
        raw_rows = [
            row
            for row in _IN_MEMORY_STORES.setdefault("bronze_sdk_events", {}).values()
            if isinstance(row, dict)
            and row.get("tenant_id") == tenant_id
            and (row.get("event_id"), row.get("schema_version")) in expected_keys
        ]
    else:
        async with pool.acquire() as conn:
            fetched = await conn.fetch(
                """SELECT id, tenant_id, event_id, payload, source, source_tag,
                          schema_version, event_type, event_timestamp, received_at, created_at
                   FROM bronze_sdk_events
                   WHERE tenant_id = $1 AND event_id = ANY($2::text[])
                     AND schema_version = ANY($3::text[])
                   ORDER BY event_id ASC, schema_version ASC
                   LIMIT $4""",
                tenant_id,
                sorted(expected_event_ids),
                sorted({schema for _, schema in expected_keys}),
                min(len(expected_keys) * 2 + 1, MAX_AGENTIC_PROVENANCE_READ + 1),
            )
        raw_rows = [dict(row) for row in fetched]

    truncated = len(raw_rows) > len(expected_keys)
    provenance_rows: list[dict[str, Any]] = []
    seen_events: set[tuple[str, str]] = set()
    for raw in raw_rows[: MAX_AGENTIC_PROVENANCE_READ + 1]:
        event_id = raw.get("event_id")
        schema_version = raw.get("schema_version")
        key = (str(event_id), str(schema_version))
        query = by_event.get(key)
        if (
            query is None
            or raw.get("tenant_id") != tenant_id
            or raw.get("source") != AGENTIC_OBSERVABILITY_SOURCE
            or raw.get("event_type") != query.evidence_ref.event_type
            or key in seen_events
        ):
            scope_mismatch = True
            continue
        seen_events.add(key)
        payload = _mapping(raw.get("payload"))
        record = _mapping(payload.get("agentic_provenance"))
        try:
            typed = AgenticEvidenceProvenanceRecord.model_validate(record)
        except Exception:  # noqa: BLE001 - malformed or absent lineage cannot back a claim
            scope_mismatch = True
            continue
        expected = query.evidence_ref
        if (
            typed.tenant_id != tenant_id
            or typed.agent_id != expected.agent_id
            or typed.bronze_event_id != event_id
            or typed.bronze_schema_version != query.bronze_schema_version
            or typed.bronze_event_type != expected.event_type
            or typed.evidence_ref.id != expected.id
            or typed.evidence_ref.source != expected.source
            or typed.evidence_ref.observedAt != expected.observed_at
            or typed.bronze_evidence_ref.id != event_id
            or (typed.source_provider_claim or "unknown") != raw.get("source_tag")
            or not _same_instant(raw.get("event_timestamp"), typed.observed_at)
            or not _same_instant(raw.get("received_at"), typed.received_at)
        ):
            scope_mismatch = True
            continue
        provenance_rows.append(
            {
                **typed.model_dump(mode="json", by_alias=True),
                "source_row_id": raw.get("id"),
                "source_tag_claim": raw.get("source_tag"),
                "event_timestamp": raw.get("event_timestamp"),
                "bronze_created_at": raw.get("created_at"),
            }
        )

    # A stored canonical_event_id with no exact tenant Bronze row, or a row
    # without its matching event-to-evidence reference, is an incomplete link.
    missing = expected_keys - seen_events
    if missing:
        scope_mismatch = True
    return AgenticProvenanceReadBatch(
        rows=provenance_rows,
        truncated=truncated,
        scope_mismatch=scope_mismatch,
    )
