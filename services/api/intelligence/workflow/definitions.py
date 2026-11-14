"""Append-only, tenant-owned workflow definition registration authority.

Definitions describe explicitly registered configuration. They are not run
records and never establish that a trigger fired, a step executed, or an action
caused an external effect.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Protocol
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from graph.operational_intelligence.models import EvidenceRef
from intelligence.semantic_intelligence.repositories.base_fact_repo import SemanticFactRepository

_TABLE = "workflow_definition_revisions"
_MAX_DEFINITION_HISTORY = 200
_MAX_STEPS = 100
_MAX_TRIGGERS = 32


class WorkflowTriggerDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger_id: str = Field(min_length=1, max_length=128)
    kind: Literal["manual", "event", "schedule", "webhook", "signal"]
    source_ref: Optional[str] = Field(default=None, max_length=256)
    event_type: Optional[str] = Field(default=None, max_length=128)
    schedule_ref: Optional[str] = Field(default=None, max_length=256)

    @field_validator("trigger_id", "source_ref", "event_type", "schedule_ref")
    @classmethod
    def trim_identifiers(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("workflow trigger identifiers must not be blank")
        return value


class WorkflowStepDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1, max_length=128)
    kind: Literal["agent", "tool", "human", "condition", "wait", "subworkflow"]
    label: str = Field(min_length=1, max_length=200)
    depends_on: list[str] = Field(default_factory=list, max_length=32)
    agent_ref: Optional[str] = Field(default=None, max_length=256)
    tool_ref: Optional[str] = Field(default=None, max_length=256)
    capability_ref: Optional[str] = Field(default=None, max_length=256)
    workflow_ref: Optional[str] = Field(default=None, max_length=256)

    @field_validator("step_id", "label", "agent_ref", "tool_ref", "capability_ref", "workflow_ref")
    @classmethod
    def trim_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("workflow step identifiers and labels must not be blank")
        return value

    @field_validator("depends_on")
    @classmethod
    def dependencies_are_unique(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("workflow step dependencies must be non-empty and unique")
        return normalized


class WorkflowDefinitionRevision(BaseModel):
    """One immutable, actor-attributed registered definition revision."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(min_length=1, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=256)
    revision: int = Field(ge=1, le=999_999_999_999)
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Literal["active", "paused", "retired"] = "active"
    triggers: list[WorkflowTriggerDefinition] = Field(default_factory=list, max_length=_MAX_TRIGGERS)
    steps: list[WorkflowStepDefinition] = Field(default_factory=list, max_length=_MAX_STEPS)
    actor_ref: str = Field(min_length=1, max_length=256)
    created_at: datetime
    effective_at: Optional[datetime] = None
    retention_class: Literal["standard_90d"] = "standard_90d"

    @field_validator(
        "workflow_id", "tenant_id", "name", "actor_ref", "description"
    )
    @classmethod
    def trim_required_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("workflow definition identifiers and names must not be blank")
        return value

    @field_validator("created_at", "effective_at")
    @classmethod
    def normalize_timestamps(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("workflow definition timestamps must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_definition_links(self) -> "WorkflowDefinitionRevision":
        step_ids = [step.step_id for step in self.steps]
        trigger_ids = [trigger.trigger_id for trigger in self.triggers]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("workflow step IDs must be unique within a revision")
        if len(trigger_ids) != len(set(trigger_ids)):
            raise ValueError("workflow trigger IDs must be unique within a revision")
        known_steps = set(step_ids)
        if any(dependency not in known_steps for step in self.steps for dependency in step.depends_on):
            raise ValueError("workflow step dependency must name a step in this revision")
        return self

    @property
    def definition_digest(self) -> str:
        payload = self.model_dump(mode="json", exclude={"created_at"})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @property
    def record_id(self) -> str:
        key = f"{self.tenant_id}\0{self.workflow_id}\0{self.revision}".encode()
        return f"wfdef_{hashlib.sha256(key).hexdigest()[:32]}"


class WorkflowDefinitionFactRepository(SemanticFactRepository):
    """Generic semantic fact writer with bounded exact-subject revision reads."""

    def __init__(self) -> None:
        super().__init__(_TABLE)

    async def latest_for_subject(self, tenant_id: str, workflow_id: str) -> list[dict[str, Any]]:
        pool = await self._pool()
        if pool is None:
            rows = [
                row
                for row in self._store.values()
                if row.get("tenant_id") == tenant_id and row.get("subject_ref") == workflow_id
            ]
            rows.sort(key=lambda row: int((row.get("data") or {}).get("revision", 0)), reverse=True)
            return rows[:2]
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT id, tenant_id, subject_ref, data FROM {self.table_name} "
                "WHERE tenant_id = $1 AND subject_ref = $2 "
                "AND (data->>'revision') ~ '^[1-9][0-9]{0,11}$' "
                "ORDER BY (data->>'revision')::bigint DESC, id DESC LIMIT 2",
                tenant_id,
                workflow_id,
            )
        return [
            {
                "id": row["id"],
                "tenant_id": row["tenant_id"],
                "subject_ref": row["subject_ref"],
                "data": _json_mapping(row["data"]),
            }
            for row in rows
        ]

    async def revisions_for_subject(
        self, tenant_id: str, workflow_id: str, *, limit: int
    ) -> list[dict[str, Any]]:
        """Read a bounded history, including malformed rows for fail-closed validation."""
        pool = await self._pool()
        if pool is None:
            rows = [
                row
                for row in self._store.values()
                if row.get("tenant_id") == tenant_id and row.get("subject_ref") == workflow_id
            ]
            rows.sort(key=lambda row: str(row.get("occurred_at") or ""), reverse=True)
            return rows[:limit]
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT id, tenant_id, subject_ref, occurred_at, data FROM {self.table_name} "
                "WHERE tenant_id = $1 AND subject_ref = $2 "
                "ORDER BY occurred_at DESC NULLS LAST, id DESC LIMIT $3",
                tenant_id,
                workflow_id,
                limit,
            )
        return [
            {
                "id": row["id"],
                "tenant_id": row["tenant_id"],
                "subject_ref": row["subject_ref"],
                "occurred_at": row["occurred_at"],
                "data": _json_mapping(row["data"]),
            }
            for row in rows
        ]


class WorkflowDefinitionFactStore(Protocol):
    async def upsert(self, fact: dict[str, Any]) -> dict[str, Any]: ...

    async def find_by_ids(
        self, tenant_id: str, record_ids: list[str] | tuple[str, ...], *, subject: Optional[str] = None
    ) -> list[dict[str, Any]]: ...

    async def latest_for_subject(self, tenant_id: str, workflow_id: str) -> list[dict[str, Any]]: ...

    async def revisions_for_subject(
        self, tenant_id: str, workflow_id: str, *, limit: int
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class WorkflowDefinitionRead:
    rows: tuple[dict[str, Any], ...] = ()
    available: bool = False
    complete: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class ResolvedWorkflowDefinition:
    definition: WorkflowDefinitionRevision
    evidence_ref: EvidenceRef


class WorkflowDefinitionRepository:
    """Append-only writer and bounded exact current or as-of revision reader."""

    def __init__(self, fact_store: Optional[WorkflowDefinitionFactStore] = None) -> None:
        self._facts = fact_store or WorkflowDefinitionFactRepository()

    async def register(self, definition: WorkflowDefinitionRevision) -> WorkflowDefinitionRevision:
        typed = WorkflowDefinitionRevision.model_validate(definition)
        data = typed.model_dump(mode="json")
        data["definition_digest"] = typed.definition_digest
        data["idempotency_key"] = (
            f"workflow-definition:{typed.tenant_id}:{typed.workflow_id}:{typed.revision}"
        )
        existing_rows = await self._facts.find_by_ids(
            typed.tenant_id, [typed.record_id], subject=typed.workflow_id
        )
        if existing_rows:
            if len(existing_rows) != 1:
                raise ValueError("workflow_definition_revision_is_append_only")
            stored = _row_data(existing_rows[0])
            if stored is None or not _same_definition(stored, typed):
                raise ValueError("workflow_definition_revision_is_append_only")
            return WorkflowDefinitionRevision.model_validate(_domain_payload(stored))
        stored = await self._facts.upsert(
            {
                "id": typed.record_id,
                "tenant_id": typed.tenant_id,
                "source_event_id": None,
                "subject_ref": typed.workflow_id,
                "campaign_id": None,
                "occurred_at": typed.created_at,
                "idempotency_key": data["idempotency_key"],
                "data": data,
            }
        )
        persisted = _row_data(stored)
        if persisted is None or not _same_definition(persisted, typed):
            raise ValueError("workflow_definition_revision_is_append_only")
        return WorkflowDefinitionRevision.model_validate(_domain_payload(persisted))

    async def read_latest(
        self, tenant_id: str, workflow_id: str
    ) -> WorkflowDefinitionRead:
        if not tenant_id or not workflow_id:
            return WorkflowDefinitionRead(reason="exact_tenant_workflow_id_required")
        try:
            rows = await self._facts.latest_for_subject(tenant_id, workflow_id)
        except Exception:  # noqa: BLE001 - unavailable authority remains unknown
            return WorkflowDefinitionRead(reason="workflow_definition_read_unavailable")
        if not rows:
            return WorkflowDefinitionRead(rows=(), available=True, complete=True)
        if not isinstance(rows, (tuple, list)) or len(rows) > 2:
            return WorkflowDefinitionRead(
                available=True,
                reason="workflow_definition_latest_revision_read_invalid",
            )
        candidates: list[tuple[int, dict[str, Any]]] = []
        for raw in rows:
            candidate = _mapping(raw)
            if (
                candidate is None
                or candidate.get("tenant_id") != tenant_id
                or candidate.get("subject_ref") != workflow_id
            ):
                return WorkflowDefinitionRead(
                    available=True,
                    reason="workflow_definition_scope_or_payload_invalid",
                )
            candidate_data = _row_data(candidate)
            try:
                revision = int(candidate_data.get("revision")) if candidate_data else 0
            except (TypeError, ValueError):
                revision = 0
            if revision < 1:
                return WorkflowDefinitionRead(
                    available=True,
                    reason="workflow_definition_revision_invalid",
                )
            candidates.append((revision, candidate))
        latest_revision = max(revision for revision, _ in candidates)
        latest_candidates = [
            row for revision, row in candidates if revision == latest_revision
        ]
        if len(latest_candidates) != 1:
            return WorkflowDefinitionRead(
                available=True,
                reason="workflow_definition_latest_revision_not_unique",
            )
        row = latest_candidates[0]
        data = _row_data(row)
        if (
            row is None
            or row.get("tenant_id") != tenant_id
            or row.get("subject_ref") != workflow_id
            or data is None
        ):
            return WorkflowDefinitionRead(
                available=True,
                reason="workflow_definition_scope_or_payload_invalid",
            )
        try:
            typed = WorkflowDefinitionRevision.model_validate(_domain_payload(data))
        except Exception:  # noqa: BLE001 - malformed registered row stays unknown
            return WorkflowDefinitionRead(
                available=True,
                reason="workflow_definition_contract_invalid",
            )
        if (
            typed.tenant_id != tenant_id
            or typed.workflow_id != workflow_id
            or data.get("definition_digest") != typed.definition_digest
        ):
            return WorkflowDefinitionRead(
                available=True,
                reason="workflow_definition_scope_or_digest_mismatch",
            )
        normalized = dict(data)
        normalized["record_id"] = _text(row.get("id")) or typed.record_id
        normalized["tenant_id"] = tenant_id
        normalized["subject_ref"] = workflow_id
        return WorkflowDefinitionRead(rows=(normalized,), available=True, complete=True)

    async def read_as_of(
        self, tenant_id: str, workflow_id: str, as_of: datetime
    ) -> WorkflowDefinitionRead:
        """Select the highest revision known and effective at one exact UTC instant."""
        if (
            not tenant_id
            or not workflow_id
            or not isinstance(as_of, datetime)
            or as_of.tzinfo is None
            or as_of.utcoffset() is None
        ):
            return WorkflowDefinitionRead(reason="exact_tenant_workflow_as_of_required")
        anchor = as_of.astimezone(timezone.utc)
        try:
            rows = await self._facts.revisions_for_subject(
                tenant_id, workflow_id, limit=_MAX_DEFINITION_HISTORY + 1
            )
        except Exception:  # noqa: BLE001 - unavailable authority remains unknown
            return WorkflowDefinitionRead(reason="workflow_definition_history_read_unavailable")
        if not isinstance(rows, (list, tuple)) or len(rows) > _MAX_DEFINITION_HISTORY:
            return WorkflowDefinitionRead(
                available=True, reason="workflow_definition_history_truncated_or_invalid"
            )

        selected: list[tuple[int, dict[str, Any]]] = []
        seen_revisions: set[int] = set()
        for raw in rows:
            row = _mapping(raw)
            if (
                row is None
                or row.get("tenant_id") != tenant_id
                or row.get("subject_ref") != workflow_id
            ):
                return WorkflowDefinitionRead(
                    available=True, reason="workflow_definition_history_scope_invalid"
                )
            data = _row_data(row)
            if data is None:
                return WorkflowDefinitionRead(
                    available=True, reason="workflow_definition_history_contract_invalid"
                )
            try:
                definition = WorkflowDefinitionRevision.model_validate(
                    _domain_payload(data)
                )
            except Exception:  # noqa: BLE001 - malformed history cannot be replayed
                return WorkflowDefinitionRead(
                    available=True, reason="workflow_definition_history_contract_invalid"
                )
            if (
                definition.tenant_id != tenant_id
                or definition.workflow_id != workflow_id
                or row.get("id") != definition.record_id
                or _timestamp(row.get("occurred_at"))
                != _timestamp(definition.created_at)
                or data.get("definition_digest") != definition.definition_digest
                or definition.revision in seen_revisions
            ):
                return WorkflowDefinitionRead(
                    available=True, reason="workflow_definition_history_evidence_invalid"
                )
            seen_revisions.add(definition.revision)
            if definition.created_at <= anchor and (
                definition.effective_at is None or definition.effective_at <= anchor
            ):
                normalized = dict(data)
                normalized["record_id"] = definition.record_id
                normalized["tenant_id"] = tenant_id
                normalized["subject_ref"] = workflow_id
                selected.append((definition.revision, normalized))
        if not selected:
            return WorkflowDefinitionRead(rows=(), available=True, complete=True)
        selected.sort(key=lambda item: item[0], reverse=True)
        return WorkflowDefinitionRead(
            rows=(selected[0][1],), available=True, complete=True
        )


def workflow_definition_evidence(
    definition: WorkflowDefinitionRevision,
) -> Optional[EvidenceRef]:
    created_at = _timestamp(definition.created_at)
    if created_at is None:
        return None
    return EvidenceRef(
        id=definition.record_id,
        type="annotation",
        source=f"workflow.{_TABLE}",
        observedAt=created_at,
        uri=(
            f"store://{_TABLE}/"
            f"{quote(definition.tenant_id, safe='')}:{quote(definition.record_id, safe='')}"
        ),
    )


def _same_definition(raw: dict[str, Any], typed: WorkflowDefinitionRevision) -> bool:
    try:
        existing = WorkflowDefinitionRevision.model_validate(_domain_payload(raw))
    except Exception:  # noqa: BLE001 - malformed persisted row conflicts
        return False
    return (
        existing.model_dump(mode="json", exclude={"created_at"})
        == typed.model_dump(mode="json", exclude={"created_at"})
        and raw.get("definition_digest") == existing.definition_digest == typed.definition_digest
    )


def _domain_payload(data: dict[str, Any]) -> dict[str, Any]:
    ignored = {"idempotency_key", "definition_digest", "record_id", "subject_ref"}
    return {key: value for key, value in data.items() if key not in ignored}


def _row_data(raw: Any) -> Optional[dict[str, Any]]:
    row = _mapping(raw)
    if row is None:
        return None
    data = _mapping(row.get("data"))
    return data if data is not None else row


def _json_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _mapping(value: Any) -> Optional[dict[str, Any]]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            result = value.model_dump(mode="json")
        except Exception:  # noqa: BLE001 - malformed repository row
            return None
        return result if isinstance(result, dict) else None
    return None


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _timestamp(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value.astimezone(timezone.utc).isoformat()
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


__all__ = [
    "ResolvedWorkflowDefinition",
    "WorkflowDefinitionRead",
    "WorkflowDefinitionRepository",
    "WorkflowDefinitionRevision",
    "WorkflowStepDefinition",
    "WorkflowTriggerDefinition",
    "workflow_definition_evidence",
]
