"""Append-only Social360 trust and transmission evidence authority.

This authority records explicit, tenant-authorized assertions. It validates
canonical entity identities, source provenance, relationship paths, and linked
risk signals before accepting a record. A recorded transmission assertion is
still correlated evidence; it does not prove that risk was caused or transmitted
along the path. Trust assertions are kept separate from graph edges and never
write graph state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Protocol
from uuid import UUID, NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from graph.operational_intelligence.models import EvidenceRef
from shared.contracts_models.epistemic import EpistemicStatus

MAX_SOCIAL_EVIDENCE_READ = 100
MAX_SOCIAL_CONTAGION_PATH_NODES = 4


class SocialEvidenceAuthorityError(RuntimeError):
    """A proposed assertion cannot be joined to its exact canonical evidence."""


class SocialEvidenceConflict(SocialEvidenceAuthorityError):
    """An idempotency key was replayed with different assertion content."""


class SocialEvidenceInput(BaseModel):
    """Typed source assertion envelope. Tenant and actor are always server supplied."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: str = Field(min_length=1, max_length=512)
    source_observation_id: str = Field(min_length=1, max_length=512)
    source_revision_id: str = Field(min_length=1, max_length=512)
    source_event_id: str = Field(min_length=1, max_length=512)
    source_entity_id: str = Field(min_length=1, max_length=512)
    target_entity_id: str = Field(min_length=1, max_length=512)
    observed_at: datetime
    effective_at: datetime
    risk_signal_ids: list[str] = Field(default_factory=list, max_length=MAX_SOCIAL_EVIDENCE_READ)

    @model_validator(mode="after")
    def _aware_times_and_identifiers(self) -> "SocialEvidenceInput":
        for name in ("observed_at", "effective_at"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must include a timezone")
        ids = [self.source_id, self.source_observation_id, self.source_revision_id, self.source_event_id]
        if len({item.strip() for item in ids}) != len(ids):
            # Source IDs may intentionally repeat across record and revision, but
            # the source namespace and exact event identity may not collapse.
            if self.source_id == self.source_event_id:
                raise ValueError("source_id and source_event_id must identify different namespaces")
        if len(self.risk_signal_ids) != len(set(self.risk_signal_ids)):
            raise ValueError("risk_signal_ids must be unique")
        if any(not item.strip() for item in self.risk_signal_ids):
            raise ValueError("risk_signal_ids cannot contain blank identifiers")
        return self


class SocialTrustEdgeInput(SocialEvidenceInput):
    """Explicit trust assertion for one exact canonical entity pair."""

    risk_signal_ids: list[str] = Field(default_factory=list, max_length=MAX_SOCIAL_EVIDENCE_READ)
    assertion_note: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def _distinct_endpoints(self) -> "SocialTrustEdgeInput":
        if self.source_entity_id == self.target_entity_id:
            raise ValueError("trust assertion endpoints must be distinct")
        return self


class SocialContagionEvidenceInput(SocialEvidenceInput):
    """Explicit source assertion linked to an exact observed FOLLOWS path."""

    path_entity_ids: list[str] = Field(
        min_length=3,
        max_length=MAX_SOCIAL_CONTAGION_PATH_NODES,
    )

    @model_validator(mode="after")
    def _path_matches_endpoints(self) -> "SocialContagionEvidenceInput":
        if len(self.path_entity_ids) != len(set(self.path_entity_ids)):
            raise ValueError("path_entity_ids must not repeat entities")
        if self.path_entity_ids[0] != self.source_entity_id:
            raise ValueError("path must begin at source_entity_id")
        if self.path_entity_ids[-1] != self.target_entity_id:
            raise ValueError("path must end at target_entity_id")
        if not self.risk_signal_ids:
            raise ValueError("social contagion evidence requires exact linked risk signals")
        return self


@dataclass(frozen=True)
class SocialEvidenceRead:
    """Bounded exact-subject evidence read for Social360 and Risk360 consumers."""

    tenant_id: str
    subject_entity_id: str
    records: tuple[dict[str, Any], ...] = ()
    available: bool = True
    truncated: bool = False
    reason: Optional[str] = None


class SocialEvidenceStore(Protocol):
    async def append(self, record: dict[str, Any]) -> dict[str, Any]: ...

    async def erase_subject_refs(self, tenant_id: str, refs: set[str]) -> int: ...

    async def list_for_subject(
        self,
        tenant_id: str,
        subject_entity_id: str,
        *,
        assertion_kind: str,
        limit: int,
        as_of: Optional[datetime] = None,
    ) -> tuple[list[dict[str, Any]], bool]: ...


class RepositorySocialEvidenceStore:
    """Durable append-only ledger with a DB-free local/test adapter."""

    _local_rows: dict[tuple[str, str], dict[str, Any]] = {}

    async def erase_subject_refs(self, tenant_id: str, refs: set[str]) -> int:
        """Delete assertions naming this tenant's data subject in any role.

        An assertion can concern the subject as a path intermediary or as the
        authenticated annotating actor even when its indexed subject endpoint
        belongs to someone else. The append-only trigger rejects UPDATE but
        permits this governed DSR DELETE.
        """
        from repositories.repos import get_pool

        exact_refs = sorted(ref for ref in refs if isinstance(ref, str) and ref)
        if not tenant_id or not exact_refs:
            return 0
        pool = await get_pool()
        if pool is None:
            victims = [
                key
                for key, record in self._local_rows.items()
                if key[0] == tenant_id
                and record.get("tenant_id") == tenant_id
                and _mentions_subject(record, set(exact_refs))
            ]
            for key in victims:
                del self._local_rows[key]
            return len(victims)

        async with pool.acquire() as connection:
            result = await connection.execute(
                """DELETE FROM social_relationship_evidence_events
                   WHERE tenant_id = $1
                     AND (
                       subject_entity_id = ANY($2::text[])
                       OR source_entity_id = ANY($2::text[])
                       OR target_entity_id = ANY($2::text[])
                       OR payload->>'actor_id' = ANY($2::text[])
                       OR (
                         jsonb_typeof(payload->'path_entity_ids') = 'array'
                         AND (payload->'path_entity_ids') ?| $2::text[]
                       )
                     )""",
                tenant_id,
                exact_refs,
            )
        return int(result.rsplit(" ", 1)[-1])

    async def append(self, record: dict[str, Any]) -> dict[str, Any]:
        from repositories.repos import get_pool

        tenant_id = record["tenant_id"]
        record_id = record["record_id"]
        key = (tenant_id, record_id)
        pool = await get_pool()
        if pool is None:
            existing = self._local_rows.get(key)
            if existing is not None:
                if _idempotent_record(existing) == _idempotent_record(record):
                    return dict(existing)
                raise SocialEvidenceConflict("social evidence record id already exists")
            self._local_rows[key] = dict(record)
            return dict(record)

        async with pool.acquire() as connection:
            status = await connection.execute(
                """INSERT INTO social_relationship_evidence_events (
                       tenant_id, record_id, assertion_kind, subject_entity_id,
                       source_entity_id, target_entity_id, source_id,
                       source_observation_id, source_revision_id, source_event_id,
                       observed_at, effective_at, recorded_at, payload
                   ) VALUES (
                       $1, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10,
                       $11, $12, $13, $14::jsonb
                   ) ON CONFLICT DO NOTHING""",
                tenant_id,
                record_id,
                record["assertion_kind"],
                record["subject_entity_id"],
                record["source_entity_id"],
                record["target_entity_id"],
                record["source_id"],
                record["source_observation_id"],
                record["source_revision_id"],
                record["source_event_id"],
                _as_datetime(record["observed_at"]),
                _as_datetime(record["effective_at"]),
                _as_datetime(record["recorded_at"]),
                json.dumps(record, default=str),
            )
            if status.endswith(" 1"):
                return dict(record)
            existing = await connection.fetchrow(
                """SELECT payload FROM social_relationship_evidence_events
                   WHERE tenant_id = $1 AND source_id = $2 AND source_event_id = $3""",
                tenant_id,
                record["source_id"],
                record["source_event_id"],
            )
        if existing is None:
            raise SocialEvidenceConflict("social evidence idempotency record is inconsistent")
        payload = _decode_mapping(existing["payload"])
        if _idempotent_record(payload) != _idempotent_record(record):
            raise SocialEvidenceConflict("social source event was replayed with conflicting evidence")
        return payload

    async def list_for_subject(
        self,
        tenant_id: str,
        subject_entity_id: str,
        *,
        assertion_kind: str,
        limit: int,
        as_of: Optional[datetime] = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        from repositories.repos import get_pool

        bounded = min(max(int(limit), 1), MAX_SOCIAL_EVIDENCE_READ)
        anchor = _utc(as_of) if as_of is not None else None
        pool = await get_pool()
        if pool is None:
            rows = [
                dict(record)
                for (row_tenant, _), record in self._local_rows.items()
                if row_tenant == tenant_id
                and record.get("tenant_id") == tenant_id
                and record.get("subject_entity_id") == subject_entity_id
                and record.get("assertion_kind") == assertion_kind
                and (
                    anchor is None
                    or all(
                        (timestamp := _as_datetime(record.get(field))) is not None
                        and timestamp <= anchor
                        for field in ("effective_at", "observed_at", "recorded_at")
                    )
                )
            ]
            rows.sort(
                key=lambda row: (
                    str(row.get("effective_at")),
                    str(row.get("recorded_at")),
                    row["record_id"],
                ),
                reverse=True,
            )
            return rows[:bounded], len(rows) > bounded

        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """SELECT payload FROM social_relationship_evidence_events
                   WHERE tenant_id = $1 AND subject_entity_id = $2
                     AND assertion_kind = $3
                     AND ($4::timestamptz IS NULL OR (
                       effective_at <= $4 AND observed_at <= $4 AND recorded_at <= $4
                     ))
                   ORDER BY effective_at DESC, recorded_at DESC, record_id DESC
                   LIMIT $5""",
                tenant_id,
                subject_entity_id,
                assertion_kind,
                anchor,
                bounded + 1,
            )
        records = [_decode_mapping(row["payload"]) for row in rows]
        return records[:bounded], len(records) > bounded


class SocialEvidenceAuthority:
    """Validate source, identity, graph, and risk joins before durable append."""

    def __init__(
        self,
        *,
        store: Optional[SocialEvidenceStore] = None,
        entity_reader: Any = None,
        source_reader: Any = None,
        risk_signal_reader: Any = None,
        graph_path_reader: Any = None,
    ) -> None:
        self._store = store or RepositorySocialEvidenceStore()
        self._entity_reader = entity_reader
        self._source_reader = source_reader
        self._risk_signal_reader = risk_signal_reader
        self._graph_path_reader = graph_path_reader

    async def record_trust_edge(
        self,
        tenant_id: str,
        event: SocialTrustEdgeInput,
        *,
        actor_id: str,
        actor_type: str,
    ) -> dict[str, Any]:
        """Append an explicit operator trust assertion for an exact entity pair."""
        if not event.source_id.startswith("aether.operator:"):
            raise SocialEvidenceAuthorityError("trust assertions require an authenticated operator source")
        if not tenant_id or not actor_id or not actor_type:
            raise SocialEvidenceAuthorityError("tenant and authenticated actor context are required")
        entities = await self._canonical_entities(
            tenant_id, (event.source_entity_id, event.target_entity_id)
        )
        if set(entities) != {event.source_entity_id, event.target_entity_id}:
            raise SocialEvidenceAuthorityError("trust endpoints must resolve as exact tenant entities")
        risk_refs = await self._validated_risk_refs(
            tenant_id, event.risk_signal_ids, allowed_subject_ids=set(entities)
        )
        policy_ref = EvidenceRef(
            id=f"social360:admin-grant:{actor_id}",
            type="annotation",
            source="authenticated_tenant_permission",
            observedAt=datetime.now(timezone.utc).isoformat(),
        )
        record = self._record_base(
            tenant_id=tenant_id,
            event=event,
            actor_id=actor_id,
            actor_type=actor_type,
            assertion_kind="trust_edge",
            subject_entity_id=event.target_entity_id,
        )
        record.update(
            {
                "source_entity_id": event.source_entity_id,
                "target_entity_id": event.target_entity_id,
                "assertion_state": "operator_asserted",
                "assertion_note": event.assertion_note,
                "causal_status": "not_applicable",
                "risk_signal_ids": list(event.risk_signal_ids),
                "risk_evidence_refs": [ref.model_dump(mode="json") for ref in risk_refs],
                "policy_evidence_refs": [policy_ref.model_dump(mode="json")],
            }
        )
        return await self._store.append(record)

    async def record_social_contagion_evidence(
        self,
        tenant_id: str,
        event: SocialContagionEvidenceInput,
        *,
        actor_id: str,
        actor_type: str,
    ) -> dict[str, Any]:
        """Append source-reported social risk transmission evidence.

        The persisted row is deliberately marked correlated. It preserves the
        exact graph path and risk signals for downstream Risk360 use, while
        keeping causality, source reliability, and policy outcome unestablished.
        """
        if not tenant_id or not actor_id or not actor_type:
            raise SocialEvidenceAuthorityError("tenant and authenticated actor context are required")
        entities = await self._canonical_entities(tenant_id, tuple(event.path_entity_ids))
        if tuple(entities) != tuple(event.path_entity_ids):
            raise SocialEvidenceAuthorityError("social path contains a non-canonical tenant entity")
        source_read = await self._source_observation(
            tenant_id,
            event.source_id,
            event.source_observation_id,
            event.source_revision_id,
            event.source_event_id,
        )
        if source_read is None:
            raise SocialEvidenceAuthorityError("exact tenant source observation with ingress provenance is required")
        path_read = await self._observed_path(tenant_id, tuple(event.path_entity_ids))
        if path_read is None:
            raise SocialEvidenceAuthorityError("exact observed canonical FOLLOWS path is required")
        risk_refs = await self._validated_risk_refs(
            tenant_id,
            event.risk_signal_ids,
            allowed_subject_ids=set(event.path_entity_ids),
        )
        source_ref, source_trust, source_revision_status = source_read
        path_refs, path_observed_at = path_read
        observed_at = _utc(event.observed_at)
        if any(_as_datetime(value) is None for value in path_observed_at):
            raise SocialEvidenceAuthorityError("path timestamps must be timezone-aware")
        path_times = [_as_datetime(value) for value in path_observed_at]
        if any(right < left for left, right in zip(path_times, path_times[1:])):
            raise SocialEvidenceAuthorityError("path relationship evidence must be chronological")
        if path_times and path_times[-1] > observed_at:
            raise SocialEvidenceAuthorityError("risk source observation cannot predate its final path edge")

        record = self._record_base(
            tenant_id=tenant_id,
            event=event,
            actor_id=actor_id,
            actor_type=actor_type,
            assertion_kind="social_contagion",
            subject_entity_id=event.target_entity_id,
        )
        record.update(
            {
                "source_entity_id": event.source_entity_id,
                "target_entity_id": event.target_entity_id,
                "path_entity_ids": list(event.path_entity_ids),
                "path_evidence_refs": [ref.model_dump(mode="json") for ref in path_refs],
                "source_evidence_refs": [source_ref.model_dump(mode="json")],
                "source_trust_classification": source_trust,
                "source_revision_status": source_revision_status,
                "risk_signal_ids": list(event.risk_signal_ids),
                "risk_evidence_refs": [ref.model_dump(mode="json") for ref in risk_refs],
                "assertion_state": "source_reported",
                "claim_state": EpistemicStatus.CORRELATED.value,
                "causal_status": "unverified",
                "policy_state": "unknown",
            }
        )
        return await self._store.append(record)

    async def read_social_contagion_evidence(
        self,
        tenant_id: str,
        subject_entity_id: str,
        *,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        as_of: Optional[datetime] = None,
        limit: int = MAX_SOCIAL_EVIDENCE_READ,
    ) -> SocialEvidenceRead:
        """Read exact-subject records for Risk360 with explicit bitemporal bounds."""
        return await self._read(
            tenant_id,
            subject_entity_id,
            assertion_kind="social_contagion",
            start=start,
            end=end,
            as_of=as_of,
            limit=limit,
        )

    async def read_trust_edge_evidence(
        self,
        tenant_id: str,
        subject_entity_id: str,
        *,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        as_of: Optional[datetime] = None,
        limit: int = MAX_SOCIAL_EVIDENCE_READ,
    ) -> SocialEvidenceRead:
        """Read exact-subject operator trust assertions without graph mutation."""
        return await self._read(
            tenant_id,
            subject_entity_id,
            assertion_kind="trust_edge",
            start=start,
            end=end,
            as_of=as_of,
            limit=limit,
        )

    async def _read(
        self,
        tenant_id: str,
        subject_entity_id: str,
        *,
        assertion_kind: str,
        start: Optional[datetime],
        end: Optional[datetime],
        as_of: Optional[datetime],
        limit: int,
    ) -> SocialEvidenceRead:
        if not tenant_id or not subject_entity_id:
            return SocialEvidenceRead(tenant_id, subject_entity_id, available=False, reason="exact_social_subject_required")
        if start and end and _utc(end) <= _utc(start):
            return SocialEvidenceRead(tenant_id, subject_entity_id, available=False, reason="social_evidence_time_range_invalid")
        bounded = min(max(int(limit), 1), MAX_SOCIAL_EVIDENCE_READ)
        try:
            rows, truncated = await self._store.list_for_subject(
                tenant_id,
                subject_entity_id,
                assertion_kind=assertion_kind,
                limit=bounded,
                as_of=_utc(as_of) if as_of else None,
            )
        except Exception:  # noqa: BLE001 - fail closed on an authority read error
            return SocialEvidenceRead(tenant_id, subject_entity_id, available=False, reason="social_evidence_authority_unavailable")
        valid: list[dict[str, Any]] = []
        for row in rows:
            if (
                row.get("tenant_id") != tenant_id
                or row.get("subject_entity_id") != subject_entity_id
                or row.get("assertion_kind") != assertion_kind
            ):
                return SocialEvidenceRead(tenant_id, subject_entity_id, available=False, reason="social_evidence_scope_mismatch")
            observed = _as_datetime(row.get("observed_at"))
            effective = _as_datetime(row.get("effective_at"))
            if observed is None or effective is None:
                return SocialEvidenceRead(tenant_id, subject_entity_id, available=False, reason="social_evidence_timestamp_invalid")
            if start and observed < _utc(start):
                continue
            if end and observed >= _utc(end):
                continue
            valid.append(row)
        return SocialEvidenceRead(
            tenant_id,
            subject_entity_id,
            tuple(valid),
            available=True,
            truncated=truncated,
            reason="social_evidence_read_truncated" if truncated else None,
        )

    async def _canonical_entities(self, tenant_id: str, entity_ids: tuple[str, ...]) -> tuple[str, ...]:
        reader = self._entity_reader
        if reader is None:
            from repositories.repos import EntityRepository

            reader = EntityRepository()
        try:
            rows, truncated = await reader.find_many_for_tenant_entity_ids(
                tenant_id, set(entity_ids)
            )
        except Exception as exc:  # noqa: BLE001 - identity is fail closed
            raise SocialEvidenceAuthorityError("canonical entity identity is unavailable") from exc
        if truncated or len(rows) != len(set(entity_ids)):
            raise SocialEvidenceAuthorityError("canonical entity identity is unresolved or conflicted")
        ids = []
        for row in rows:
            if row.get("tenant_id") != tenant_id or not isinstance(row.get("entity_id"), str):
                raise SocialEvidenceAuthorityError("canonical entity scope mismatch")
            ids.append(row["entity_id"])
        if len(ids) != len(set(ids)) or set(ids) != set(entity_ids):
            raise SocialEvidenceAuthorityError("canonical entity identity is ambiguous")
        return tuple(entity_id for entity_id in entity_ids if entity_id in set(ids))

    async def _source_observation(
        self,
        tenant_id: str,
        source_id: str,
        observation_id: str,
        revision_id: str,
        event_id: str,
    ) -> Optional[tuple[EvidenceRef, str, str]]:
        reader = self._source_reader
        if reader is None:
            from intelligence.risk360.provider import RepositoryRiskSourceReader

            reader = RepositoryRiskSourceReader()
        try:
            rows, truncated = await reader.source_provenance_observations(
                tenant_id=tenant_id, source_id=source_id
            )
        except Exception:  # noqa: BLE001 - source provenance is fail closed
            return None
        if truncated:
            return None
        exact = [
            row for row in rows
            if row.get("tenant_id") == tenant_id
            and row.get("source_id") == source_id
            and row.get("observation_id") == observation_id
            and isinstance(row.get("evidence_ref"), dict)
            and row["evidence_ref"].get("id") == event_id
        ]
        if len(exact) != 1:
            return None
        canonical_revision_id = exact[0].get("source_revision_id")
        if canonical_revision_id is not None and canonical_revision_id != revision_id:
            return None
        revision_status = (
            "canonical_source_revision_bound"
            if canonical_revision_id == revision_id
            else "source_reported_revision_unverified"
        )
        source_trust = exact[0].get("source_trust")
        if not isinstance(source_trust, str) or not source_trust.strip():
            return None
        try:
            return EvidenceRef.model_validate(exact[0]["evidence_ref"]), source_trust, revision_status
        except Exception:  # noqa: BLE001 - malformed evidence fails closed
            return None

    async def _observed_path(
        self, tenant_id: str, entity_ids: tuple[str, ...]
    ) -> Optional[tuple[tuple[EvidenceRef, ...], tuple[str, ...]]]:
        reader = self._graph_path_reader
        if reader is None:
            from services.social360.provider import RepositorySocialGraphPathReader

            reader = RepositorySocialGraphPathReader()
        try:
            read = await reader.read_paths(tenant_id, entity_ids[0])
        except Exception:  # noqa: BLE001 - graph is fail closed
            return None
        if (
            getattr(read, "tenant_id", None) != tenant_id
            or getattr(read, "start_entity_id", None) != entity_ids[0]
            or not getattr(read, "available", False)
        ):
            return None
        paths = [path for path in getattr(read, "paths", ()) if tuple(getattr(path, "entity_ids", ())) == entity_ids]
        if len(paths) != 1:
            return None
        path = paths[0]
        refs = tuple(ref for edge_refs in path.edge_evidence_refs for ref in edge_refs)
        if not refs or any(not isinstance(ref, EvidenceRef) for ref in refs):
            return None
        times = tuple(path.edge_observed_at)
        if len(times) != len(entity_ids) - 1:
            return None
        return refs, times

    async def _validated_risk_refs(
        self,
        tenant_id: str,
        signal_ids: list[str],
        *,
        allowed_subject_ids: set[str],
    ) -> tuple[EvidenceRef, ...]:
        if not signal_ids:
            return ()
        reader = self._risk_signal_reader
        if reader is None:
            from intelligence.risk360.store import RiskSignalRepository

            reader = RiskSignalRepository()
        refs: list[EvidenceRef] = []
        for signal_id in signal_ids:
            try:
                row = await reader.get_scoped(tenant_id, signal_id)
            except Exception as exc:  # noqa: BLE001 - exact risk evidence is fail closed
                raise SocialEvidenceAuthorityError("canonical risk signal authority is unavailable") from exc
            if (
                not isinstance(row, dict)
                or row.get("tenant_id") != tenant_id
                or row.get("signal_id") != signal_id
                or row.get("subject_kind") != "entity"
                or row.get("subject_id") not in allowed_subject_ids
            ):
                raise SocialEvidenceAuthorityError("risk evidence must bind to an exact path entity in this tenant")
            observed_at = row.get("observed_at")
            if _as_datetime(observed_at) is None:
                raise SocialEvidenceAuthorityError("risk evidence timestamp is unavailable")
            refs.append(
                EvidenceRef(
                    id=signal_id,
                    type="model_output",
                    source=f"risk_signals:{row.get('source') or 'unknown'}",
                    observedAt=_iso(observed_at),
                )
            )
            for raw in row.get("evidence_refs", []):
                if not isinstance(raw, dict):
                    continue
                try:
                    refs.append(EvidenceRef.model_validate(raw))
                except Exception:  # noqa: BLE001 - malformed optional evidence omitted
                    continue
        return tuple(_dedupe_evidence(refs))

    @staticmethod
    def _record_base(
        *,
        tenant_id: str,
        event: SocialEvidenceInput,
        actor_id: str,
        actor_type: str,
        assertion_kind: str,
        subject_entity_id: str,
    ) -> dict[str, Any]:
        return {
            # A stable ID makes a retried source event idempotent across
            # processes and database connections. The database also enforces
            # this uniqueness independently.
            "record_id": str(
                uuid5(
                    NAMESPACE_URL,
                    f"aether:social360:{tenant_id}:{event.source_id}:{event.source_event_id}",
                )
            ),
            "tenant_id": tenant_id,
            "assertion_kind": assertion_kind,
            "subject_entity_id": subject_entity_id,
            "source_entity_id": event.source_entity_id,
            "target_entity_id": event.target_entity_id,
            "source_id": event.source_id,
            "source_observation_id": event.source_observation_id,
            "source_revision_id": event.source_revision_id,
            # The canonical Bronze source reader binds source and observation
            # IDs today, but does not expose a source-native revision. Preserve
            # the submitted revision without presenting it as verified.
            "source_revision_status": "source_reported_revision_unverified",
            "source_event_id": event.source_event_id,
            "observed_at": _iso(event.observed_at),
            "effective_at": _iso(event.effective_at),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "actor_id": actor_id,
            "actor_type": actor_type,
        }


def _idempotent_record(record: dict[str, Any]) -> dict[str, Any]:
    """Fields whose equality means a duplicate source event is a safe retry."""
    return {
        key: value
        for key, value in record.items()
        if key not in {"record_id", "recorded_at"}
    }


def _mentions_subject(record: dict[str, Any], refs: set[str]) -> bool:
    if any(
        isinstance(record.get(field), str) and record[field] in refs
        for field in (
            "subject_entity_id",
            "source_entity_id",
            "target_entity_id",
            "actor_id",
        )
    ):
        return True
    path = record.get("path_entity_ids")
    return isinstance(path, list) and any(ref in refs for ref in path if isinstance(ref, str))


def _decode_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _as_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(timezone.utc)


def _iso(value: Any) -> Optional[str]:
    parsed = _as_datetime(value)
    return parsed.isoformat() if parsed is not None else None


def _dedupe_evidence(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    seen: set[tuple[str, str]] = set()
    result: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.source, ref.id)
        if key not in seen:
            seen.add(key)
            result.append(ref)
    return result


__all__ = [
    "MAX_SOCIAL_CONTAGION_PATH_NODES",
    "MAX_SOCIAL_EVIDENCE_READ",
    "RepositorySocialEvidenceStore",
    "SocialContagionEvidenceInput",
    "SocialEvidenceAuthority",
    "SocialEvidenceAuthorityError",
    "SocialEvidenceConflict",
    "SocialEvidenceInput",
    "SocialEvidenceRead",
    "SocialTrustEdgeInput",
]
