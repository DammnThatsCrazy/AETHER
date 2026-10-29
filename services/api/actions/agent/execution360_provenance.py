"""Bounded Bronze ingress provenance for admitted Execution360 telemetry.

Silver's ``source_event_id`` is the Bronze ``event_id`` produced by the
Bronze-to-Silver worker. Silver does not retain the Bronze schema version, so
this reader accepts an event only when the tenant has exactly one matching
Bronze row. The result classifies ingress for that observation; it does not
link source telemetry to an AETHER execution or verify an external effect.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

from graph.operational_intelligence.models import EvidenceRef


MAX_EXECUTION_PROVENANCE_EVENTS = 500


@dataclass(frozen=True)
class ExecutionSourceProvenanceRead:
    rows: list[dict[str, Any]]
    available: bool
    scope_known: bool
    truncated: bool = False
    reason: str | None = None
    unmatched_count: int = 0


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


def _safe_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 256 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    return value


def _instant(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo is not None else None


def _joined_record(
    raw: dict[str, Any], *, tenant_id: str, event_id: str, event_type: str
) -> dict[str, Any] | None:
    if raw.get("tenant_id") != tenant_id or raw.get("event_id") != event_id:
        return None
    if raw.get("event_type") != event_type:
        return None
    bronze_id = _safe_string(raw.get("id"))
    schema_version = _safe_string(raw.get("schema_version"))
    if bronze_id is None or schema_version is None:
        return None
    payload = _mapping(raw.get("payload"))
    envelope = _mapping(payload.get("observation_envelope"))
    tenancy = _mapping(envelope.get("tenancy"))
    observation = _mapping(envelope.get("observation"))
    source = _mapping(envelope.get("source"))
    provenance = _mapping(envelope.get("provenance"))
    rights = _mapping(envelope.get("rights"))
    if (
        tenancy.get("tenant_id") != tenant_id
        or observation.get("observation_id") != event_id
        or observation.get("observation_type") != event_type
        or payload.get("event_id") != event_id
        or payload.get("event_type") != event_type
    ):
        return None
    occurred_at = observation.get("occurred_at")
    if _instant(occurred_at) is None or _instant(raw.get("event_timestamp")) != _instant(occurred_at):
        return None
    evidence = EvidenceRef(
        id=event_id,
        type="event",
        source="bronze_sdk_events",
        observedAt=occurred_at,
        uri=f"store://bronze_sdk_events/{quote(bronze_id, safe='')}",
    )
    return {
        "tenantId": tenant_id,
        "sourceEventId": event_id,
        "eventName": event_type,
        "bronzeSchemaVersion": schema_version,
        "sourceId": _safe_string(rights.get("source_id")),
        "sourceProviderClaim": _safe_string(source.get("source_provider")),
        "sourceTrust": _safe_string(provenance.get("source_trust")),
        "credentialClass": _safe_string(provenance.get("credential_class")),
        "signatureStatus": _safe_string(provenance.get("signature_status")),
        "adapter": _safe_string(provenance.get("adapter")),
        "adapterVersion": _safe_string(provenance.get("adapter_version")),
        "observedAt": occurred_at,
        "evidenceRef": evidence.model_dump(mode="json", by_alias=True, exclude_none=True),
        "classification": "bronze_recorded_ingress_envelope",
        "sourceIdentityVerified": False,
        "externalExecutionVerified": False,
    }


async def read_execution_source_provenance(
    *, tenant_id: str, events: tuple[tuple[str, str], ...]
) -> ExecutionSourceProvenanceRead:
    """Join exact admitted tenant/event/type keys to unique Bronze records."""
    if not tenant_id:
        return ExecutionSourceProvenanceRead([], False, False, reason="tenant_scope_required")
    if not events:
        return ExecutionSourceProvenanceRead([], True, True)
    if len(events) > MAX_EXECUTION_PROVENANCE_EVENTS:
        return ExecutionSourceProvenanceRead([], True, False, truncated=True, reason="source_provenance_event_bound_exceeded")
    by_id: dict[str, str] = {}
    for event_id, event_type in events:
        safe_id, safe_type = _safe_string(event_id), _safe_string(event_type)
        if safe_id is None or safe_type is None or (safe_id in by_id and by_id[safe_id] != safe_type):
            return ExecutionSourceProvenanceRead([], True, False, reason="source_provenance_event_key_conflict")
        by_id[safe_id] = safe_type

    try:
        from repositories.repos import _IN_MEMORY_STORES, get_pool

        pool = await get_pool()
        bound = len(by_id) * 2 + 1
        if pool is None:
            raw_rows: list[dict[str, Any]] = []
            for raw in _IN_MEMORY_STORES.setdefault("bronze_sdk_events", {}).values():
                if (
                    isinstance(raw, dict)
                    and raw.get("tenant_id") == tenant_id
                    and raw.get("event_id") in by_id
                ):
                    raw_rows.append(raw)
                    if len(raw_rows) >= bound:
                        break
        else:
            async with pool.acquire() as conn:
                fetched = await conn.fetch(
                    """SELECT id, tenant_id, event_id, schema_version,
                              event_type, event_timestamp, payload
                       FROM bronze_sdk_events
                       WHERE tenant_id = $1 AND event_id = ANY($2::text[])
                       ORDER BY event_id ASC, schema_version ASC
                       LIMIT $3""",
                    tenant_id,
                    sorted(by_id),
                    bound,
                )
            raw_rows = [dict(row) for row in fetched]
    except Exception:  # noqa: BLE001 - optional source read remains fail closed
        return ExecutionSourceProvenanceRead([], False, False, reason="source_provenance_read_unavailable")

    if len(raw_rows) >= bound:
        return ExecutionSourceProvenanceRead([], True, False, truncated=True, reason="source_provenance_bronze_read_truncated")

    grouped: dict[str, list[dict[str, Any]]] = {event_id: [] for event_id in by_id}
    for raw in raw_rows:
        if raw.get("tenant_id") != tenant_id or raw.get("event_id") not in grouped:
            return ExecutionSourceProvenanceRead([], True, False, reason="source_provenance_bronze_scope_mismatch")
        grouped[raw["event_id"]].append(raw)

    records: list[dict[str, Any]] = []
    unmatched = 0
    for event_id, event_type in sorted(by_id.items()):
        candidates = grouped[event_id]
        if len(candidates) != 1:
            unmatched += 1
            continue
        record = _joined_record(candidates[0], tenant_id=tenant_id, event_id=event_id, event_type=event_type)
        if record is None:
            unmatched += 1
            continue
        records.append(record)
    return ExecutionSourceProvenanceRead(
        rows=records,
        available=True,
        scope_known=unmatched == 0,
        reason="source_provenance_exact_join_incomplete" if unmatched else None,
        unmatched_count=unmatched,
    )
