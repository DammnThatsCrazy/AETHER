"""Risk360 persistence — tenant-scoped JSONB repositories (BaseRepository pattern).

Risk signals and risk assessments are stored as auto-created JSONB tables (see
``repositories/repos.py``); in the local environment the store is in-memory.
Record IDs are tenant-qualified (``{tenant_id}:{natural_id}``) so identical
natural ids never collide across tenants, and every read path re-checks the
tenant before returning a row. **NO Alembic migrations** — BaseRepository owns
the schema (the convention established for new stores, first used by the
comparison workbench).

The tenant-scoped JSONB base is **reused** from the comparison workbench store
(``services/api/intelligence/intelligence/comparison/store.py``, single-monolith reuse) rather
than re-declared: :class:`intelligence.intelligence.comparison.store.TenantScopedComparisonRepository`
is the generic tenant-qualified JSONB base, and the risk repositories here are
thin specializations bound to the risk table names and natural-id keys.

Runs are NOT stored here — :class:`intelligence.risk360.contracts.RiskAssessmentRun`
is a reproducibility reference onto the substrate ``computation_runs`` table and
creates no parallel run table (see the SoT ``RISK_FRAUD_360.md`` §8).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from graph.operational_intelligence.models import EvidenceRef
from intelligence.intelligence.comparison.store import TenantScopedComparisonRepository
from intelligence.risk360.contracts import (
    PoisoningEvidenceStatus,
    RiskPoisoningEvidence,
    RiskPoisoningLifecycleEvent,
)
class RiskPoisoningEvidenceConflict(RuntimeError):
    """A poisoning evidence id or version chain conflicts with stored truth."""


class RiskPoisoningEvidenceReadIncomplete(RuntimeError):
    """An exact tenant/source/subject evidence read could not be established."""


@dataclass(frozen=True)
class RiskPoisoningEvidenceRead:
    """Bounded, exact-scope poisoning evidence read result."""

    records: list[RiskPoisoningEvidence]
    complete: bool
    reason: Optional[str] = None


_POISONING_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"acknowledged", "resolved", "dismissed"}),
    "acknowledged": frozenset({"open", "resolved", "dismissed"}),
    "resolved": frozenset(),
    "dismissed": frozenset(),
    "superseded": frozenset(),
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _record_id(tenant_id: str, evidence_id: str) -> str:
    return f"{tenant_id}:{evidence_id}"


def _json_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if key not in {"id", "created_at", "updated_at"}
    }


def _as_evidence(record: dict[str, Any]) -> RiskPoisoningEvidence:
    return RiskPoisoningEvidence.model_validate(_public_record(record))


def _as_of_status(
    record: RiskPoisoningEvidence,
    *,
    as_of: Optional[datetime],
) -> Optional[RiskPoisoningEvidence]:
    """Reconstruct a known-then status from recorded lifecycle transitions."""
    if as_of is None:
        return record
    if record.recorded_at > as_of:
        return None
    status: PoisoningEvidenceStatus = "open"
    superseded_by: Optional[str] = None
    events = [
        event for event in record.lifecycle_events if event.occurred_at <= as_of
    ]
    for event in events:
        status = event.to_status
        if event.to_status == "superseded":
            superseded_by = next(
                (
                    evidence_id
                    for evidence_id in (record.superseded_by_evidence_id,)
                    if evidence_id
                ),
                None,
            )
    return record.model_copy(
        update={
            "status": status,
            "superseded_by_evidence_id": superseded_by,
            "lifecycle_events": events,
        }
    )


class TenantScopedRiskRepository(TenantScopedComparisonRepository):
    """Risk360 tenant-scoped JSONB base.

    Reuses the comparison workbench's generic tenant-scoped base unchanged
    (tenant-qualified IDs, tenant-checked reads, envelope stripping). This class
    exists so the risk repositories read as one risk-owned family; add shared
    risk read helpers here rather than re-declaring scoping logic.
    """


class RiskSignalRepository(TenantScopedRiskRepository):
    """Tenant-scoped JSONB store for ``risk_signals``."""

    natural_id_key = "signal_id"

    def __init__(self) -> None:
        super().__init__("risk_signals")

    async def list_by_subject(
        self,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List signals for one subject within a tenant (tenant-checked)."""
        return await self.list_scoped(
            tenant_id,
            {"subject_kind": subject_kind, "subject_id": subject_id},
            limit=limit,
            offset=offset,
        )

    async def list_by_dimension(
        self,
        tenant_id: str,
        risk_dimension: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List signals for one risk dimension within a tenant."""
        return await self.list_scoped(
            tenant_id,
            {"risk_dimension": risk_dimension},
            limit=limit,
            offset=offset,
        )


class RiskAssessmentRepository(TenantScopedRiskRepository):
    """Tenant-scoped JSONB store for ``risk_assessments``."""

    natural_id_key = "assessment_id"

    def __init__(self) -> None:
        super().__init__("risk_assessments")

    async def list_by_subject(
        self,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List assessments for one subject within a tenant (tenant-checked)."""
        return await self.list_scoped(
            tenant_id,
            {"subject_kind": subject_kind, "subject_id": subject_id},
            limit=limit,
            offset=offset,
        )


class RiskPoisoningEvidenceRepository(TenantScopedRiskRepository):
    """Canonical risk-domain store for appendable source-poisoning evidence.

    This repository is owned by the risk subsystem, never by the Risk360 read
    projection. Its rows are immutable evidence versions except for audited
    lifecycle transitions. Version replacement locks the predecessor and
    writes both sides of the supersession link in one database transaction.
    """

    natural_id_key = "evidence_id"

    def __init__(self) -> None:
        super().__init__("risk_poisoning_evidence")

    async def create(self, evidence: RiskPoisoningEvidence) -> RiskPoisoningEvidence:
        """Insert an initial evidence version once; repeated identical writes are idempotent."""
        if evidence.version != 1 or evidence.supersedes_evidence_id is not None:
            raise ValueError("initial poisoning evidence must start at version 1")
        if evidence.status != "open" or evidence.superseded_by_evidence_id is not None:
            raise ValueError("initial poisoning evidence must start open")
        record_id = _record_id(evidence.tenant_id, evidence.evidence_id)
        payload = evidence.model_dump(mode="json")
        now = _utc_now().isoformat()
        pool = await self._ensure_pool()

        if pool is None:
            existing = self._store.get(record_id)
            if existing is not None:
                if _public_record(existing) == payload:
                    return _as_evidence(existing)
                raise RiskPoisoningEvidenceConflict("poisoning evidence id already exists")
            self._store[record_id] = {
                **payload,
                "id": record_id,
                "created_at": now,
                "updated_at": now,
            }
            return evidence

        await self._ensure_table()
        async with pool.acquire() as conn:
            status = await conn.execute(
                f"""INSERT INTO {self.table_name} (id, data, tenant_id, created_at, updated_at)
                    VALUES ($1, $2::jsonb, $3, NOW(), NOW())
                    ON CONFLICT (id) DO NOTHING""",
                record_id,
                json.dumps(payload, separators=(",", ":")),
                evidence.tenant_id,
            )
            if status.endswith(" 0"):
                row = await conn.fetchrow(
                    f"SELECT data, tenant_id FROM {self.table_name} WHERE id = $1",
                    record_id,
                )
                if (
                    row is not None
                    and row["tenant_id"] == evidence.tenant_id
                    and _public_record({**_json_payload(row["data"]), "id": record_id}) == payload
                ):
                    return _as_evidence({**_json_payload(row["data"]), "id": record_id})
                raise RiskPoisoningEvidenceConflict("poisoning evidence id already exists")
        return evidence

    async def get(
        self, tenant_id: str, evidence_id: str
    ) -> Optional[RiskPoisoningEvidence]:
        """Fetch one exact tenant-owned evidence version."""
        if not tenant_id or not evidence_id:
            return None
        record_id = _record_id(tenant_id, evidence_id)
        pool = await self._ensure_pool()
        if pool is None:
            record = self._store.get(record_id)
            if record is None or record.get("tenant_id") != tenant_id:
                return None
        else:
            await self._ensure_table()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT data, tenant_id FROM {self.table_name} WHERE id = $1",
                    record_id,
                )
            if row is None or row["tenant_id"] != tenant_id:
                return None
            record = {**_json_payload(row["data"]), "id": record_id}
        try:
            evidence = _as_evidence(record)
        except Exception as exc:  # malformed persisted data is not a record
            raise RiskPoisoningEvidenceReadIncomplete(
                "stored poisoning evidence contract is invalid"
            ) from exc
        if evidence.tenant_id != tenant_id or evidence.evidence_id != evidence_id:
            raise RiskPoisoningEvidenceReadIncomplete(
                "stored poisoning evidence scope is inconsistent"
            )
        return evidence

    async def transition_status(
        self,
        tenant_id: str,
        evidence_id: str,
        new_status: PoisoningEvidenceStatus,
        *,
        actor_id: str,
        reason: Optional[str] = None,
        evidence_refs: Optional[list[EvidenceRef]] = None,
    ) -> Optional[RiskPoisoningEvidence]:
        """Apply one legal, auditable lifecycle transition to an evidence version."""
        if not actor_id or not actor_id.strip():
            raise ValueError("poisoning evidence transitions require an actor id")
        record_id = _record_id(tenant_id, evidence_id)
        pool = await self._ensure_pool()
        if pool is None:
            record = self._store.get(record_id)
            if record is None or record.get("tenant_id") != tenant_id:
                return None
            current = _as_evidence(record)
            if new_status == current.status:
                return current
            if new_status not in _POISONING_STATUS_TRANSITIONS[current.status]:
                raise RiskPoisoningEvidenceConflict("illegal poisoning evidence status transition")
            event = RiskPoisoningLifecycleEvent(
                event_id=f"plc_{uuid4().hex}",
                from_status=current.status,
                to_status=new_status,
                occurred_at=_utc_now(),
                actor_id=actor_id,
                reason=reason,
                evidence_refs=evidence_refs or [],
            )
            updated = RiskPoisoningEvidence.model_validate(
                {
                    **current.model_dump(mode="python"),
                    "status": new_status,
                    "lifecycle_events": [*current.lifecycle_events, event],
                }
            )
            self._store[record_id] = {
                **_public_record(record),
                **updated.model_dump(mode="json"),
                "id": record_id,
                "created_at": record.get("created_at"),
                "updated_at": _utc_now().isoformat(),
            }
            return updated

        await self._ensure_table()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"SELECT data, tenant_id, created_at FROM {self.table_name} WHERE id = $1 FOR UPDATE",
                    record_id,
                )
                if row is None or row["tenant_id"] != tenant_id:
                    return None
                raw = {**_json_payload(row["data"]), "id": record_id}
                current = _as_evidence(raw)
                if current.tenant_id != tenant_id or current.evidence_id != evidence_id:
                    raise RiskPoisoningEvidenceReadIncomplete(
                        "stored poisoning evidence scope is inconsistent"
                    )
                if new_status == current.status:
                    return current
                if new_status not in _POISONING_STATUS_TRANSITIONS[current.status]:
                    raise RiskPoisoningEvidenceConflict(
                        "illegal poisoning evidence status transition"
                    )
                event = RiskPoisoningLifecycleEvent(
                    event_id=f"plc_{uuid4().hex}",
                    from_status=current.status,
                    to_status=new_status,
                    occurred_at=_utc_now(),
                    actor_id=actor_id,
                    reason=reason,
                    evidence_refs=evidence_refs or [],
                )
                updated = RiskPoisoningEvidence.model_validate(
                    {
                        **current.model_dump(mode="python"),
                        "status": new_status,
                        "lifecycle_events": [*current.lifecycle_events, event],
                    }
                )
                await conn.execute(
                    f"UPDATE {self.table_name} SET data = $1::jsonb, updated_at = NOW() "
                    "WHERE id = $2 AND tenant_id = $3",
                    json.dumps(updated.model_dump(mode="json"), separators=(",", ":")),
                    record_id,
                    tenant_id,
                )
                return updated

    async def restate(
        self,
        tenant_id: str,
        previous_evidence_id: str,
        replacement: RiskPoisoningEvidence,
        *,
        actor_id: str,
        reason: str,
    ) -> RiskPoisoningEvidence:
        """Append a source/subject-identical successor and supersede its predecessor.

        The exact source and subject bindings are invariant across a chain. The
        replacement keeps the original first-seen instant, advances the version,
        names its predecessor, and records why the old interpretation changed.
        """
        if not actor_id or not actor_id.strip() or not reason or not reason.strip():
            raise ValueError("poisoning evidence restatement requires actor and reason")
        if replacement.tenant_id != tenant_id:
            raise ValueError("replacement evidence tenant does not match repository scope")
        if replacement.supersedes_evidence_id != previous_evidence_id:
            raise ValueError("replacement must name the exact predecessor")
        if replacement.restatement_reason != reason:
            raise ValueError("replacement restatement reason must match the transition reason")
        if replacement.status != "open" or replacement.superseded_by_evidence_id is not None:
            raise ValueError("replacement evidence must start open")

        previous_record_id = _record_id(tenant_id, previous_evidence_id)
        replacement_record_id = _record_id(tenant_id, replacement.evidence_id)
        replacement_payload = replacement.model_dump(mode="json")
        pool = await self._ensure_pool()

        if pool is None:
            previous_row = self._store.get(previous_record_id)
            if previous_row is None or previous_row.get("tenant_id") != tenant_id:
                raise RiskPoisoningEvidenceConflict("predecessor poisoning evidence is unavailable")
            previous = _as_evidence(previous_row)
            if previous.status == "superseded":
                if previous.superseded_by_evidence_id == replacement.evidence_id:
                    existing_row = self._store.get(replacement_record_id)
                    if existing_row is not None and _public_record(existing_row) == replacement_payload:
                        return _as_evidence(existing_row)
                raise RiskPoisoningEvidenceConflict("predecessor already has a successor")
            self._validate_restatement(previous, replacement, tenant_id)
            existing_row = self._store.get(replacement_record_id)
            if existing_row is not None:
                raise RiskPoisoningEvidenceConflict("replacement evidence id already exists")
            for row in self._store.values():
                if (
                    row.get("tenant_id") == tenant_id
                    and row.get("supersedes_evidence_id") == previous_evidence_id
                ):
                    raise RiskPoisoningEvidenceConflict("predecessor already has a successor")
            event = RiskPoisoningLifecycleEvent(
                event_id=f"plc_{uuid4().hex}",
                from_status=previous.status,
                to_status="superseded",
                occurred_at=replacement.recorded_at,
                actor_id=actor_id,
                reason=reason,
                evidence_refs=replacement.evidence_refs,
            )
            updated_previous = RiskPoisoningEvidence.model_validate(
                {
                    **previous.model_dump(mode="python"),
                    "status": "superseded",
                    "superseded_by_evidence_id": replacement.evidence_id,
                    "lifecycle_events": [*previous.lifecycle_events, event],
                }
            )
            now = _utc_now().isoformat()
            self._store[previous_record_id] = {
                **updated_previous.model_dump(mode="json"),
                "id": previous_record_id,
                "created_at": previous_row.get("created_at"),
                "updated_at": now,
            }
            self._store[replacement_record_id] = {
                **replacement_payload,
                "id": replacement_record_id,
                "created_at": now,
                "updated_at": now,
            }
            return replacement

        await self._ensure_table()
        async with pool.acquire() as conn:
            async with conn.transaction():
                previous_row = await conn.fetchrow(
                    f"SELECT data, tenant_id FROM {self.table_name} WHERE id = $1 FOR UPDATE",
                    previous_record_id,
                )
                if previous_row is None or previous_row["tenant_id"] != tenant_id:
                    raise RiskPoisoningEvidenceConflict("predecessor poisoning evidence is unavailable")
                previous_raw = {
                    **_json_payload(previous_row["data"]),
                    "id": previous_record_id,
                }
                previous = _as_evidence(previous_raw)
                if previous.status == "superseded":
                    if previous.superseded_by_evidence_id == replacement.evidence_id:
                        existing_row = await conn.fetchrow(
                            f"SELECT data, tenant_id FROM {self.table_name} WHERE id = $1",
                            replacement_record_id,
                        )
                        if (
                            existing_row is not None
                            and existing_row["tenant_id"] == tenant_id
                            and _public_record(
                                {**_json_payload(existing_row["data"]), "id": replacement_record_id}
                            )
                            == replacement_payload
                        ):
                            return _as_evidence(
                                {**_json_payload(existing_row["data"]), "id": replacement_record_id}
                            )
                    raise RiskPoisoningEvidenceConflict("predecessor already has a successor")
                self._validate_restatement(previous, replacement, tenant_id)
                branches = await conn.fetch(
                    f"SELECT id FROM {self.table_name} WHERE tenant_id = $1 "
                    "AND data->>'supersedes_evidence_id' = $2 LIMIT 2",
                    tenant_id,
                    previous_evidence_id,
                )
                if branches:
                    raise RiskPoisoningEvidenceConflict("predecessor already has a successor")
                inserted = await conn.execute(
                    f"""INSERT INTO {self.table_name} (id, data, tenant_id, created_at, updated_at)
                        VALUES ($1, $2::jsonb, $3, NOW(), NOW())
                        ON CONFLICT (id) DO NOTHING""",
                    replacement_record_id,
                    json.dumps(replacement_payload, separators=(",", ":")),
                    tenant_id,
                )
                if inserted.endswith(" 0"):
                    raise RiskPoisoningEvidenceConflict("replacement evidence id already exists")
                event = RiskPoisoningLifecycleEvent(
                    event_id=f"plc_{uuid4().hex}",
                    from_status=previous.status,
                    to_status="superseded",
                    occurred_at=replacement.recorded_at,
                    actor_id=actor_id,
                    reason=reason,
                    evidence_refs=replacement.evidence_refs,
                )
                updated_previous = RiskPoisoningEvidence.model_validate(
                    {
                        **previous.model_dump(mode="python"),
                        "status": "superseded",
                        "superseded_by_evidence_id": replacement.evidence_id,
                        "lifecycle_events": [*previous.lifecycle_events, event],
                    }
                )
                await conn.execute(
                    f"UPDATE {self.table_name} SET data = $1::jsonb, updated_at = NOW() "
                    "WHERE id = $2 AND tenant_id = $3",
                    json.dumps(updated_previous.model_dump(mode="json"), separators=(",", ":")),
                    previous_record_id,
                    tenant_id,
                )
        return replacement

    @staticmethod
    def _validate_restatement(
        previous: RiskPoisoningEvidence,
        replacement: RiskPoisoningEvidence,
        tenant_id: str,
    ) -> None:
        if (
            previous.tenant_id != tenant_id
            or replacement.tenant_id != tenant_id
            or previous.source_id != replacement.source_id
            or previous.subject_kind != replacement.subject_kind
            or previous.subject_id != replacement.subject_id
        ):
            raise RiskPoisoningEvidenceConflict(
                "restatement source and subject must exactly match its predecessor"
            )
        if replacement.version != previous.version + 1:
            raise RiskPoisoningEvidenceConflict("restatement version is not the next version")
        if replacement.evidence_id == previous.evidence_id:
            raise RiskPoisoningEvidenceConflict("restatement must have a new evidence id")
        if replacement.first_seen_at != previous.first_seen_at:
            raise RiskPoisoningEvidenceConflict("restatement must preserve first_seen_at")
        if replacement.last_seen_at < previous.last_seen_at:
            raise RiskPoisoningEvidenceConflict("restatement cannot move last_seen_at backwards")
        if replacement.recorded_at < previous.recorded_at:
            raise RiskPoisoningEvidenceConflict("restatement cannot precede its predecessor")
        if previous.lifecycle_events and replacement.recorded_at < previous.lifecycle_events[-1].occurred_at:
            raise RiskPoisoningEvidenceConflict(
                "restatement cannot predate the predecessor lifecycle"
            )

    async def list_for_subject(
        self,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        *,
        source_id: Optional[str] = None,
        as_of: Optional[datetime] = None,
        limit: int = 100,
    ) -> RiskPoisoningEvidenceRead:
        """Read bounded evidence for one exact tenant/subject and optional source.

        ``as_of`` uses recorded time plus the append-only lifecycle trail; it
        does not confuse source occurrence time with when Aether knew a result.
        """
        if not tenant_id or not subject_kind or not subject_id or limit < 1 or limit > 500:
            raise ValueError("poisoning evidence read requires exact scope and a bounded limit")
        if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
            raise ValueError("poisoning evidence as_of must include a timezone")

        pool = await self._ensure_pool()
        query_limit = limit + 1
        if pool is None:
            candidates: list[dict[str, Any]] = []
            for row in self._store.values():
                if (
                    row.get("tenant_id") != tenant_id
                    or row.get("subject_kind") != subject_kind
                    or row.get("subject_id") != subject_id
                    or (source_id is not None and row.get("source_id") != source_id)
                ):
                    continue
                try:
                    model = _as_evidence(row)
                except Exception as exc:
                    raise RiskPoisoningEvidenceReadIncomplete(
                        "stored poisoning evidence contract is invalid"
                    ) from exc
                if as_of is not None and model.recorded_at > as_of:
                    continue
                candidates.append(row)
            candidates.sort(
                key=lambda row: str(row.get("recorded_at") or ""),
                reverse=True,
            )
        else:
            await self._ensure_table()
            predicates = [
                "tenant_id = $1",
                "data->>'subject_kind' = $2",
                "data->>'subject_id' = $3",
            ]
            params: list[Any] = [tenant_id, subject_kind, subject_id]
            if source_id is not None:
                params.append(source_id)
                predicates.append(f"data->>'source_id' = ${len(params)}")
            if as_of is not None:
                params.append(as_of)
                predicates.append(f"(data->>'recorded_at')::timestamptz <= ${len(params)}")
            params.append(query_limit)
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"SELECT id, tenant_id, data FROM {self.table_name} "
                    f"WHERE {' AND '.join(predicates)} "
                    "ORDER BY (data->>'recorded_at')::timestamptz DESC, id ASC "
                    f"LIMIT ${len(params)}",
                    *params,
                )
            candidates = []
            for row in rows:
                if row["tenant_id"] != tenant_id:
                    raise RiskPoisoningEvidenceReadIncomplete(
                        "poisoning evidence tenant scope is inconsistent"
                    )
                payload = _json_payload(row["data"])
                if (
                    payload.get("tenant_id") != tenant_id
                    or payload.get("subject_kind") != subject_kind
                    or payload.get("subject_id") != subject_id
                    or (source_id is not None and payload.get("source_id") != source_id)
                ):
                    raise RiskPoisoningEvidenceReadIncomplete(
                        "poisoning evidence exact binding is inconsistent"
                    )
                candidates.append({**payload, "id": row["id"]})

        truncated = len(candidates) > limit
        records: list[RiskPoisoningEvidence] = []
        for row in candidates[:limit]:
            try:
                record = _as_evidence(row)
            except Exception as exc:
                raise RiskPoisoningEvidenceReadIncomplete(
                    "stored poisoning evidence contract is invalid"
                ) from exc
            if (
                record.tenant_id != tenant_id
                or record.subject_kind != subject_kind
                or record.subject_id != subject_id
                or (source_id is not None and record.source_id != source_id)
            ):
                raise RiskPoisoningEvidenceReadIncomplete(
                    "poisoning evidence exact binding is inconsistent"
                )
            at_anchor = _as_of_status(record, as_of=as_of)
            if at_anchor is not None:
                records.append(at_anchor)

        successors: dict[str, int] = {}
        for record in records:
            if record.supersedes_evidence_id:
                successors[record.supersedes_evidence_id] = (
                    successors.get(record.supersedes_evidence_id, 0) + 1
                )
        if any(count > 1 for count in successors.values()):
            raise RiskPoisoningEvidenceReadIncomplete("poisoning evidence restatement chain forks")

        return RiskPoisoningEvidenceRead(
            records=records,
            complete=not truncated,
            reason="poisoning_evidence_scan_truncated" if truncated else None,
        )

    async def erase_subject_refs(self, tenant_id: str, refs: set[str]) -> int:
        """Erase exact tenant-owned records naming a subject or source reference."""
        subject_rows = await self.delete_for_tenant_where(
            tenant_id, "subject_id", refs
        )
        source_rows = await self.delete_for_tenant_where(
            tenant_id, "source_id", refs
        )
        return subject_rows + source_rows


__all__ = [
    "TenantScopedRiskRepository",
    "RiskSignalRepository",
    "RiskAssessmentRepository",
    "RiskPoisoningEvidenceRepository",
    "RiskPoisoningEvidenceRead",
    "RiskPoisoningEvidenceConflict",
    "RiskPoisoningEvidenceReadIncomplete",
]
