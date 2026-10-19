"""Read-only Identity360 view over the canonical identity authorities.

Identity360 is a product surface in the 18-surface catalog, not one of the
technical ``ProjectionResult`` projection ids. This module therefore exposes a
typed surface read result without inventing a projection id or creating a
second identity authority. Runtime composition and policy authorization remain
the responsibility of the governed frame boundary.

The provider accepts exact tenant-owned entity, agent, or source-identity ids.
It never resolves arbitrary identifiers, returns raw identifier values or
hashes, evaluates identity, writes graph state, or treats missing joins as
proof of absence. Every repository result is rechecked against its tenant and
requested subject before projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Protocol

from graph.operational_intelligence.models import EvidenceRef


IdentitySubjectKind = Literal["entity", "agent", "source"]
IdentitySlotState = Literal["available", "empty", "unknown", "degraded", "truncated", "suppressed"]

DEFAULT_LIMIT = 100
MAX_LIMIT = 500
_SOURCE_IDENTIFIER_FIELDS = (
    "external_id",
    "anonymous_id",
    "user_id",
    "device_id",
    "installation_id",
    "session_id",
    "account_id",
    "agent_id",
    "runtime_id",
    "source_record_id",
)


@dataclass(frozen=True)
class IdentityRecordRead:
    """Outcome of a single exact-key authority read."""

    record: Optional[dict[str, Any]] = None
    available: bool = True
    reason: Optional[str] = None


@dataclass(frozen=True)
class IdentityBatchRead:
    """Bounded tenant-scoped authority read with completeness metadata."""

    rows: tuple[dict[str, Any], ...] = ()
    available: bool = True
    truncated: bool = False
    reason: Optional[str] = None


class Identity360Source(Protocol):
    """Injectable reads from canonical entity, identity and evidence stores."""

    async def canonical_entity(self, tenant_id: str, entity_id: str) -> IdentityRecordRead: ...

    async def identity_subject(self, tenant_id: str, entity_id: str) -> IdentityRecordRead: ...

    async def source_identity(
        self, tenant_id: str, source_identity_id: str
    ) -> IdentityRecordRead: ...

    async def source_identities_for_entity(
        self, tenant_id: str, entity_id: str, *, limit: int
    ) -> IdentityBatchRead: ...

    async def source_claims(
        self, tenant_id: str, source_identity_id: str, *, limit: int
    ) -> IdentityBatchRead: ...

    async def aliases_for_entity(
        self, tenant_id: str, entity_id: str, *, limit: int
    ) -> IdentityBatchRead: ...

    async def identity_edges_for_entity(
        self, tenant_id: str, entity_id: str, *, limit: int
    ) -> IdentityBatchRead: ...

    async def decisions_for_entity(
        self, tenant_id: str, entity_id: str, *, limit: int
    ) -> IdentityBatchRead: ...

    async def verification_for_entity(
        self, tenant_id: str, entity_id: str, *, limit: int
    ) -> IdentityBatchRead: ...


class RepositoryIdentity360Source:
    """Adapter over existing canonical repositories; imports are lazy.

    The identity repository has no public bounded-list methods for source
    identities or claims. Those two reads use its existing private repository
    stores with explicit tenant + subject filters and an extra row to detect
    truncation; no table or truth is introduced here.
    """

    def __init__(self, identity_repository: Any = None) -> None:
        self._identity_repository = identity_repository

    def _identity_repo(self) -> Any:
        if self._identity_repository is None:
            from identity.identity.repository import IdentityResolutionRepository

            self._identity_repository = IdentityResolutionRepository()
        return self._identity_repository

    async def canonical_entity(self, tenant_id: str, entity_id: str) -> IdentityRecordRead:
        try:
            from repositories.repos import EntityRepository

            row = await EntityRepository().find_by_id(entity_id)
        except Exception as exc:  # noqa: BLE001 - provider reports bounded degradation
            return IdentityRecordRead(
                available=False,
                reason=f"entity_registry_{type(exc).__name__}",
            )
        return IdentityRecordRead(record=row)

    async def identity_subject(self, tenant_id: str, entity_id: str) -> IdentityRecordRead:
        try:
            row = await self._identity_repo().get_subject_by_canonical_entity_id(
                tenant_id, entity_id
            )
        except Exception as exc:  # noqa: BLE001 - provider reports bounded degradation
            return IdentityRecordRead(
                available=False,
                reason=f"identity_subjects_{type(exc).__name__}",
            )
        return IdentityRecordRead(record=row)

    async def source_identity(self, tenant_id: str, source_identity_id: str) -> IdentityRecordRead:
        try:
            row = await self._identity_repo().get_source_identity_for_tenant(
                tenant_id, source_identity_id
            )
        except Exception as exc:  # noqa: BLE001 - provider reports bounded degradation
            return IdentityRecordRead(
                available=False,
                reason=f"source_identities_{type(exc).__name__}",
            )
        return IdentityRecordRead(record=row)

    async def source_identities_for_entity(
        self, tenant_id: str, entity_id: str, *, limit: int
    ) -> IdentityBatchRead:
        try:
            rows = await self._identity_repo()._source_identities.find_many(
                filters={"tenant_id": tenant_id, "canonical_entity_id": entity_id},
                limit=limit + 1,
            )
        except Exception as exc:  # noqa: BLE001 - provider reports bounded degradation
            return IdentityBatchRead(
                available=False,
                reason=f"source_identities_{type(exc).__name__}",
            )
        return IdentityBatchRead(
            rows=tuple(rows[:limit]),
            truncated=len(rows) > limit,
        )

    async def source_claims(
        self, tenant_id: str, source_identity_id: str, *, limit: int
    ) -> IdentityBatchRead:
        try:
            rows = await self._identity_repo()._claims.find_many(
                filters={
                    "tenant_id": tenant_id,
                    "source_identity_id": source_identity_id,
                },
                limit=limit + 1,
            )
        except Exception as exc:  # noqa: BLE001 - provider reports bounded degradation
            return IdentityBatchRead(
                available=False,
                reason=f"identity_claims_{type(exc).__name__}",
            )
        return IdentityBatchRead(
            rows=tuple(rows[:limit]),
            truncated=len(rows) > limit,
        )

    async def aliases_for_entity(
        self, tenant_id: str, entity_id: str, *, limit: int
    ) -> IdentityBatchRead:
        try:
            # Repository implementation currently caps this read at 500.
            rows = await self._identity_repo().get_entity_aliases(
                tenant_id, entity_id, include_revoked=True
            )
        except Exception as exc:  # noqa: BLE001 - provider reports bounded degradation
            return IdentityBatchRead(
                available=False,
                reason=f"identity_aliases_{type(exc).__name__}",
            )
        return IdentityBatchRead(
            rows=tuple(rows[:limit]),
            truncated=len(rows) > limit or (limit >= 500 and len(rows) >= 500),
        )

    async def identity_edges_for_entity(
        self, tenant_id: str, entity_id: str, *, limit: int
    ) -> IdentityBatchRead:
        try:
            # The canonical repository bounds each direction at 200 rows.
            rows = await self._identity_repo().get_entity_graph(tenant_id, entity_id)
        except Exception as exc:  # noqa: BLE001 - provider reports bounded degradation
            return IdentityBatchRead(
                available=False,
                reason=f"identity_edges_{type(exc).__name__}",
            )
        return IdentityBatchRead(
            rows=tuple(rows[:limit]),
            truncated=len(rows) > limit or (limit >= 400 and len(rows) >= 400),
        )

    async def decisions_for_entity(
        self, tenant_id: str, entity_id: str, *, limit: int
    ) -> IdentityBatchRead:
        try:
            from identity.identity.decision_evidence import (
                IdentityDecisionEvidenceRepository,
            )

            rows = await IdentityDecisionEvidenceRepository().list_for_entity(
                tenant_id, entity_id, limit=limit + 1
            )
        except Exception as exc:  # noqa: BLE001 - provider reports bounded degradation
            return IdentityBatchRead(
                available=False,
                reason=f"identity_decision_evidence_{type(exc).__name__}",
            )
        return IdentityBatchRead(
            rows=tuple(rows[:limit]),
            truncated=len(rows) > limit,
        )

    async def verification_for_entity(
        self, tenant_id: str, entity_id: str, *, limit: int
    ) -> IdentityBatchRead:
        try:
            from identity.identity.verification_repository import (
                VerificationEvidenceRepository,
            )

            rows = await VerificationEvidenceRepository().list_for_tenant(
                tenant_id,
                limit=limit + 1,
                extra={"canonical_entity_id": entity_id},
            )
        except Exception as exc:  # noqa: BLE001 - provider reports bounded degradation
            return IdentityBatchRead(
                available=False,
                reason=f"identity_verification_evidence_{type(exc).__name__}",
            )
        return IdentityBatchRead(
            rows=tuple(rows[:limit]),
            truncated=len(rows) > limit,
        )


@dataclass(frozen=True)
class Identity360Slot:
    """One catalog-aligned identity surface slot."""

    id: str
    state: IdentitySlotState
    content: dict[str, Any]
    evidence_refs: tuple[EvidenceRef, ...] = ()
    reason: Optional[str] = None
    truncated: bool = False


@dataclass(frozen=True)
class Identity360Result:
    """Immutable, backend-only Identity360 read result."""

    tenant_id: str
    subject_kind: IdentitySubjectKind
    subject_id: str
    state: Literal["available", "partial", "unknown", "degraded"]
    slots: tuple[Identity360Slot, ...]
    generated_at: str
    warnings: tuple[str, ...] = ()

    def slot(self, slot_id: str) -> Identity360Slot:
        """Return one named slot; convenient for frame/runtime adapters."""
        for slot in self.slots:
            if slot.id == slot_id:
                return slot
        raise KeyError(slot_id)


class Identity360Provider:
    """Read-only identity and identity-evidence projection service."""

    surface_id = "identity360"
    owns_canonical_truth = False
    graph_mutation_policy = "read_only"

    def __init__(
        self,
        source: Optional[Identity360Source] = None,
        *,
        limit: int = DEFAULT_LIMIT,
    ) -> None:
        self._source = source if source is not None else RepositoryIdentity360Source()
        self._limit = min(max(int(limit), 1), MAX_LIMIT)

    async def read(
        self,
        tenant_id: str,
        subject_kind: IdentitySubjectKind,
        subject_id: str,
        *,
        requested_slot_ids: Optional[set[str]] = None,
    ) -> Identity360Result:
        """Read one exact tenant-scoped identity subject and its evidence."""
        if not tenant_id.strip() or not subject_id.strip():
            raise ValueError("tenant_id and subject_id are required")
        if subject_kind not in {"entity", "agent", "source"}:
            raise ValueError("Identity360 supports entity, agent, or source subjects")

        slot_ids = {
            "resolved_subject_identity",
            "source_identifier_lineage",
            "actor_and_agent_binding",
            "relationship_identity_context",
            "identity_evidence",
        }
        requested = slot_ids if requested_slot_ids is None else set(requested_slot_ids)
        if requested - slot_ids:
            raise ValueError("Identity360 request contains an unknown slot")
        want_subject = "resolved_subject_identity" in requested
        want_lineage = "source_identifier_lineage" in requested
        want_relationships = "relationship_identity_context" in requested
        want_evidence = "identity_evidence" in requested
        needs_entity_scope = want_subject or want_lineage or want_relationships or want_evidence

        warnings: list[str] = []
        entity_id: Optional[str] = None
        source_row: Optional[dict[str, Any]] = None
        entity_row: Optional[dict[str, Any]] = None
        identity_subject: Optional[dict[str, Any]] = None
        subject_scope_known = False
        source_suppressed = False
        source_record_read = IdentityRecordRead()

        if subject_kind == "source" and needs_entity_scope:
            source_record_read = await self._safe_record(
                "source_identity",
                self._source.source_identity(tenant_id, subject_id),
            )
            source_row = self._scope_record(
                source_record_read, tenant_id, expected_id=subject_id, id_fields=("id",)
            )
            if source_row is not None:
                subject_scope_known = True
                source_suppressed = _is_suppressed(source_row.get("status"))
                linked_id = _safe_text(source_row.get("canonical_entity_id"))
                if linked_id and source_row.get("status") == "resolved" and want_subject:
                    entity_id = linked_id
                    entity_row, identity_subject, joined, join_reasons = await self._read_entity(
                        tenant_id, linked_id, expected_kind=None
                    )
                    warnings.extend(join_reasons)
                    if joined:
                        subject_scope_known = True
                    else:
                        warnings.append("source_canonical_entity_join_unverified")
                elif linked_id and want_subject:
                    warnings.append("source_identity_not_resolved")
            elif not source_record_read.available:
                warnings.append(source_record_read.reason or "source_identity_read_degraded")
        elif subject_kind in {"entity", "agent"} and needs_entity_scope:
            entity_id = subject_id
            (
                entity_row,
                identity_subject,
                subject_scope_known,
                join_reasons,
            ) = await self._read_entity(
                tenant_id,
                subject_id,
                expected_kind="agent" if subject_kind == "agent" else None,
            )
            warnings.extend(join_reasons)

        safe_entity = _safe_canonical_entity(entity_row) if entity_row else None
        safe_subject = _safe_identity_subject(identity_subject) if identity_subject else None
        subject_refs = [
            ref
            for ref in (
                _row_ref(entity_row, "entity_registry") if entity_row is not None else None,
                _row_ref(identity_subject, "identity_subjects")
                if identity_subject is not None
                else None,
                _row_ref(source_row, "identity_source_identities")
                if source_row is not None
                else None,
            )
            if ref is not None
        ]

        source_rows_read = IdentityBatchRead()
        aliases_read = IdentityBatchRead()
        edges_read = IdentityBatchRead()
        decisions_read = IdentityBatchRead()
        verification_read = IdentityBatchRead()
        claim_read = IdentityBatchRead()

        if (
            subject_kind == "source"
            and source_row is not None
            and not source_suppressed
            and (want_lineage or want_evidence)
        ):
            claim_read = await self._safe_batch(
                "source_claims",
                self._source.source_claims(tenant_id, subject_id, limit=self._limit),
            )
            claim_rows, claim_read = self._validated_rows(
                claim_read,
                tenant_id,
                expected_source_id=subject_id,
                source_field="source_identity_id",
            )
            source_rows = [source_row]
        elif subject_kind == "source" and source_row is not None and source_suppressed:
            claim_read = IdentityBatchRead(reason="source_identity_suppressed")
            claim_rows = []
            source_rows = [source_row]
        elif entity_id is not None and subject_scope_known:
            if want_lineage:
                source_rows_read = await self._safe_batch(
                    "source_identities",
                    self._source.source_identities_for_entity(
                        tenant_id, entity_id, limit=self._limit
                    ),
                )
            if want_relationships:
                edges_read = await self._safe_batch(
                    "identity_edges",
                    self._source.identity_edges_for_entity(tenant_id, entity_id, limit=self._limit),
                )
            if want_evidence:
                aliases_read = await self._safe_batch(
                    "identity_aliases",
                    self._source.aliases_for_entity(tenant_id, entity_id, limit=self._limit),
                )
                decisions_read = await self._safe_batch(
                    "identity_decision_evidence",
                    self._source.decisions_for_entity(tenant_id, entity_id, limit=self._limit),
                )
                verification_read = await self._safe_batch(
                    "identity_verification_evidence",
                    self._source.verification_for_entity(tenant_id, entity_id, limit=self._limit),
                )
            source_rows, source_rows_read = self._validated_rows(
                source_rows_read,
                tenant_id,
                expected_entity_id=entity_id,
                source_field="canonical_entity_id",
            )
            claim_rows = []
        else:
            source_rows = []
            claim_rows = []

        aliases, aliases_read = self._validated_rows(
            aliases_read,
            tenant_id,
            expected_entity_id=entity_id,
            source_field="canonical_entity_id",
            reason_on_mismatch="identity_alias_scope_mismatch",
        )
        edges, edges_read = self._validated_edge_rows(edges_read, tenant_id, entity_id)
        decision_rows, decisions_read = self._validated_rows(
            decisions_read,
            tenant_id,
            expected_entity_id=entity_id,
            source_field="entity_id",
        )
        verification_rows, verification_read = self._validated_rows(
            verification_read,
            tenant_id,
            expected_entity_id=entity_id,
            source_field="canonical_entity_id",
        )

        # For a source subject, include its exact source registry record and its
        # claim metadata only. Values, hashes, proof material and import payloads
        # are never copied into Identity360 output.
        if subject_kind == "source":
            source_items = [
                _safe_source_identity(
                    row,
                    include_canonical_entity=bool(safe_entity and safe_subject),
                )
                for row in source_rows
            ]
        else:
            source_items = [_safe_source_identity(row) for row in source_rows]
        lineage_refs = [
            ref
            for ref in (_row_ref(row, "identity_source_identities") for row in source_rows)
            if ref is not None
        ]
        claim_items = [_safe_claim(row) for row in claim_rows]
        claim_refs = [
            ref
            for ref in (_row_ref(row, "identity_claims") for row in claim_rows)
            if ref is not None
        ]
        alias_items = [_safe_alias(row) for row in aliases]
        alias_refs = [
            ref for ref in (_row_ref(row, "identity_aliases") for row in aliases) if ref is not None
        ]
        edge_items = [_safe_edge(row) for row in edges]
        edge_refs = [
            ref for ref in (_row_ref(row, "identity_edges") for row in edges) if ref is not None
        ]
        decision_items = [_safe_decision(row) for row in decision_rows]
        decision_refs = [
            ref
            for ref in (_row_ref(row, "identity_decision_evidence") for row in decision_rows)
            if ref is not None
        ]
        verification_items = [_safe_verification(row) for row in verification_rows]
        verification_refs = [
            ref
            for ref in (
                _row_ref(row, "identity_verification_evidence") for row in verification_rows
            )
            if ref is not None
        ]

        entity_state: IdentitySlotState = "available" if safe_entity and safe_subject else "unknown"
        if subject_kind == "source":
            entity_state = "available" if safe_entity and safe_subject else "unknown"
        if not subject_scope_known:
            entity_state = "degraded" if warnings else "unknown"

        lineage_state = _batch_state(
            source_rows_read if subject_kind != "source" else claim_read,
            known_subject=subject_scope_known,
            any_rows=bool(source_rows if subject_kind != "source" else claim_rows),
            failures=warnings,
        )
        if subject_kind == "source" and source_row is not None:
            lineage_state = (
                "suppressed"
                if source_suppressed
                else (
                    "degraded"
                    if not claim_read.available
                    else "truncated"
                    if claim_read.truncated
                    else "degraded"
                )
            )
            if not source_suppressed:
                warnings.append("source_provider_registry_join_not_performed")
        if subject_kind == "source":
            evidence_state = (
                "suppressed"
                if source_suppressed
                else (
                    "degraded"
                    if not claim_read.available
                    else "truncated"
                    if claim_read.truncated
                    else "available"
                    if source_row is not None
                    else "unknown"
                )
            )
            # Source records do not imply an identity graph query. Keep that
            # optional context unknown until a dedicated canonical join runs.
            relationship_state = "unknown"
        else:
            evidence_state = _aggregate_state(
                [aliases_read, decisions_read, verification_read],
                known_subject=subject_scope_known,
                row_count=len(aliases) + len(decision_rows) + len(verification_rows),
            )
            relationship_state = _batch_state(
                edges_read,
                known_subject=subject_scope_known and entity_id is not None,
                any_rows=bool(edges),
                failures=warnings,
            )

        # An unknown actor authority is explicit: this provider does not turn
        # identity edges or a source agent_id into delegation/authorization.
        actor_slot = Identity360Slot(
            id="actor_and_agent_binding",
            state="unknown",
            content={
                "state": "unknown",
                "authority": "agent_access",
                "reason": (
                    "Actor delegation and action authority require the canonical "
                    "Agent360 and execution authority joins; identity records do not prove them."
                ),
            },
            reason="agent_access_join_not_performed_by_identity_provider",
        )

        freshness = _freshness(
            [
                *source_rows,
                *claim_rows,
                *aliases,
                *edges,
                *decision_rows,
                *verification_rows,
            ]
        )
        source_identity_coverage = (
            {
                "state": "degraded"
                if not source_record_read.available
                else "suppressed"
                if source_suppressed
                else "available"
                if source_row is not None
                else "unknown",
                "returned": 1 if source_row is not None else 0,
                "truncated": False,
            }
            if subject_kind == "source"
            else _batch_coverage(source_rows_read, source_rows)
        )
        source_claim_coverage = (
            {
                "state": "suppressed",
                "returned": None,
                "truncated": None,
                "reason": "Claims were not read because the source identity is suppressed.",
            }
            if subject_kind == "source" and source_suppressed
            else _batch_coverage(claim_read, claim_rows)
            if subject_kind == "source"
            else {
                "state": "not_read",
                "returned": None,
                "truncated": None,
                "reason": "Claims are read by exact source identity only.",
            }
        )
        if subject_kind == "source":
            if source_suppressed:
                lineage_reason = claim_read.reason or "source_identity_suppressed"
                evidence_reason = "source_identity_suppressed"
            elif source_row is None:
                lineage_reason = claim_read.reason or "source_identity_record_unavailable"
                evidence_reason = "source_identity_record_unavailable"
            else:
                lineage_reason = claim_read.reason or "source_provider_registry_join_not_performed"
                evidence_reason = claim_read.reason
            relationship_reason = "source_identity_graph_join_not_performed"
        else:
            lineage_reason = source_rows_read.reason or (
                "identity_subject_not_resolved" if not subject_scope_known else None
            )
            relationship_reason = edges_read.reason or (
                "identity_subject_not_resolved" if not subject_scope_known else None
            )
            evidence_reason = _first_reason(
                aliases_read, decisions_read, verification_read, claim_read
            ) or ("identity_evidence_subject_not_resolved" if not subject_scope_known else None)

        if not want_subject:
            entity_state = "unknown"
            entity_reason = "identity_slot_not_requested"
        else:
            entity_reason = (
                None if entity_state == "available" else "canonical_identity_join_unavailable"
            )
        if not want_lineage:
            lineage_state = "unknown"
            lineage_reason = "identity_slot_not_requested"
        if not want_relationships:
            relationship_state = "unknown"
            relationship_reason = "identity_slot_not_requested"
        if not want_evidence:
            evidence_state = "unknown"
            evidence_reason = "identity_slot_not_requested"

        slots = (
            Identity360Slot(
                id="resolved_subject_identity",
                state=entity_state,
                content=(
                    {
                        "state": entity_state,
                        "subject": {"kind": subject_kind, "id": subject_id},
                        "canonicalEntity": safe_entity,
                        "identitySubject": safe_subject,
                        "resolution": {
                            "state": "resolved" if safe_entity and safe_subject else "unknown",
                            "authority": "entities+identity_subjects",
                            "exactIdMatch": bool(
                                safe_entity
                                and safe_entity.get("id")
                                == (entity_id if entity_id else subject_id)
                            ),
                        },
                        "freshness": freshness,
                    }
                    if want_subject
                    else {"state": "unknown", "reason": "identity_slot_not_requested"}
                ),
                evidence_refs=(
                    _dedupe_refs([*subject_refs, *lineage_refs, *alias_refs, *decision_refs])
                    if want_subject
                    else ()
                ),
                reason=entity_reason,
            ),
            Identity360Slot(
                id="source_identifier_lineage",
                state=lineage_state,
                content=(
                    {
                        "state": lineage_state,
                        "sourceIdentities": source_items,
                        "claims": claim_items,
                        "sourceEntityLinkState": (
                            "resolved"
                            if subject_kind == "source" and safe_entity and safe_subject
                            else "unknown"
                            if subject_kind == "source"
                            else None
                        ),
                        "identifierValuesIncluded": False,
                        "limitations": [
                            "Provider and connector registry metadata are not joined by this identity read service.",
                            "Source identity values are represented by identifier types only.",
                        ],
                        "coverage": {
                            "sourceIdentities": source_identity_coverage,
                            "claims": source_claim_coverage,
                            "truncated": source_rows_read.truncated
                            if subject_kind != "source"
                            else claim_read.truncated,
                        },
                    }
                    if want_lineage
                    else {"state": "unknown", "reason": "identity_slot_not_requested"}
                ),
                evidence_refs=(
                    _dedupe_refs([*subject_refs, *lineage_refs, *claim_refs])
                    if want_lineage
                    else ()
                ),
                reason=lineage_reason,
                truncated=(
                    (
                        source_rows_read.truncated
                        if subject_kind != "source"
                        else claim_read.truncated
                    )
                    if want_lineage
                    else False
                ),
            ),
            actor_slot
            if "actor_and_agent_binding" in requested
            else Identity360Slot(
                id="actor_and_agent_binding",
                state="unknown",
                content={"state": "unknown", "reason": "identity_slot_not_requested"},
                reason="identity_slot_not_requested",
            ),
            Identity360Slot(
                id="relationship_identity_context",
                state=relationship_state,
                content=(
                    {
                        "state": relationship_state,
                        "authority": "identity_edges",
                        "edges": edge_items,
                        "semantics": "identity_resolution_edges_only",
                        "limitations": [
                            "These edges describe identity resolution and do not assert social or business relationships."
                        ],
                    }
                    if want_relationships
                    else {"state": "unknown", "reason": "identity_slot_not_requested"}
                ),
                evidence_refs=(
                    tuple(_dedupe_refs([*subject_refs, *edge_refs])) if want_relationships else ()
                ),
                reason=relationship_reason,
                truncated=edges_read.truncated if want_relationships else False,
            ),
            Identity360Slot(
                id="identity_evidence",
                state=evidence_state,
                content=(
                    {
                        "state": evidence_state,
                        "aliases": alias_items,
                        "decisions": decision_items,
                        "verificationEvidence": verification_items,
                        "sourceClaims": claim_items,
                        "coverage": {
                            "aliases": _batch_coverage(aliases_read, aliases),
                            "decisions": _batch_coverage(decisions_read, decision_rows),
                            "verification": _batch_coverage(verification_read, verification_rows),
                            "sourceClaims": source_claim_coverage,
                        },
                        "freshness": freshness,
                        "limitations": [
                            "Raw identifier values, identifier hashes, proof material, consent snapshots, and signal payloads are omitted.",
                            "No identity decision is recomputed by this provider.",
                            "Suppressed source identities do not expose claim metadata.",
                        ],
                    }
                    if want_evidence
                    else {"state": "unknown", "reason": "identity_slot_not_requested"}
                ),
                evidence_refs=(
                    _dedupe_refs(
                        [
                            *alias_refs,
                            *decision_refs,
                            *verification_refs,
                            *lineage_refs,
                            *claim_refs,
                            *subject_refs,
                        ]
                    )
                    if want_evidence
                    else ()
                ),
                reason=evidence_reason,
                truncated=(
                    any(
                        item.truncated
                        for item in (
                            aliases_read,
                            decisions_read,
                            verification_read,
                            claim_read,
                        )
                    )
                    if want_evidence
                    else False
                ),
            ),
        )

        required_states = [
            slot.state
            for slot in slots
            if slot.id in requested
            and slot.id
            in {
                "resolved_subject_identity",
                "source_identifier_lineage",
                "identity_evidence",
            }
        ]
        if not required_states:
            overall: Literal["available", "partial", "unknown", "degraded"] = "unknown"
        elif all(state in {"available", "empty"} for state in required_states):
            overall: Literal["available", "partial", "unknown", "degraded"] = "available"
        elif all(state in {"unknown", "suppressed"} for state in required_states):
            overall = "degraded" if warnings else "unknown"
        else:
            overall = (
                "degraded"
                if any(state in {"degraded", "truncated"} for state in required_states)
                else "partial"
            )

        return Identity360Result(
            tenant_id=tenant_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            state=overall,
            slots=slots,
            generated_at=datetime.now(timezone.utc).isoformat(),
            warnings=tuple(_unique(warnings)),
        )

    async def _read_entity(
        self,
        tenant_id: str,
        entity_id: str,
        *,
        expected_kind: Optional[str],
    ) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]], bool, list[str]]:
        entity_read = await self._safe_record(
            "canonical_entity", self._source.canonical_entity(tenant_id, entity_id)
        )
        subject_read = await self._safe_record(
            "identity_subject", self._source.identity_subject(tenant_id, entity_id)
        )
        entity = self._scope_record(
            entity_read,
            tenant_id,
            expected_id=entity_id,
            id_fields=("entity_id", "id"),
            expected_kind=expected_kind,
            kind_field="entity_type",
        )
        identity_subject = self._scope_record(
            subject_read,
            tenant_id,
            expected_id=entity_id,
            id_fields=("canonical_entity_id",),
        )
        reasons = [reason for reason in (entity_read.reason, subject_read.reason) if reason]
        # A canonical entity and its identity-resolution subject are separate
        # authorities. Surface either known row, but only call the identity
        # joined when both exact tenant-scoped records exist.
        return (
            entity,
            identity_subject,
            entity is not None and identity_subject is not None,
            reasons,
        )

    async def _safe_record(self, source_name: str, awaitable: Any) -> IdentityRecordRead:
        try:
            result = await awaitable
            return (
                result
                if isinstance(result, IdentityRecordRead)
                else IdentityRecordRead(
                    available=False,
                    reason=f"{source_name}_invalid_read_result",
                )
            )
        except Exception as exc:  # noqa: BLE001 - failure stays local and content-free
            return IdentityRecordRead(
                available=False,
                reason=f"{source_name}_{type(exc).__name__}",
            )

    async def _safe_batch(self, source_name: str, awaitable: Any) -> IdentityBatchRead:
        try:
            result = await awaitable
            return (
                result
                if isinstance(result, IdentityBatchRead)
                else IdentityBatchRead(
                    available=False,
                    reason=f"{source_name}_invalid_read_result",
                )
            )
        except Exception as exc:  # noqa: BLE001 - failure stays local and content-free
            return IdentityBatchRead(
                available=False,
                reason=f"{source_name}_{type(exc).__name__}",
            )

    @staticmethod
    def _scope_record(
        read: IdentityRecordRead,
        tenant_id: str,
        *,
        expected_id: str,
        id_fields: tuple[str, ...],
        expected_kind: Optional[str] = None,
        kind_field: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        record = read.record
        if not read.available or not _is_mapping(record):
            return None
        if record.get("tenant_id") != tenant_id:
            return None
        if not any(str(record.get(field) or "") == expected_id for field in id_fields):
            return None
        if expected_kind and kind_field and str(record.get(kind_field) or "") != expected_kind:
            return None
        return record

    @staticmethod
    def _validated_rows(
        read: IdentityBatchRead,
        tenant_id: str,
        *,
        expected_entity_id: Optional[str] = None,
        expected_source_id: Optional[str] = None,
        source_field: Optional[str] = None,
        reason_on_mismatch: str = "identity_row_scope_mismatch",
    ) -> tuple[list[dict[str, Any]], IdentityBatchRead]:
        if not read.available:
            return [], read
        rows = [row for row in read.rows if _is_mapping(row)]
        if len(rows) != len(read.rows):
            return [], IdentityBatchRead(available=False, reason="identity_row_shape_mismatch")
        for row in rows:
            if row.get("tenant_id") != tenant_id:
                return [], IdentityBatchRead(available=False, reason="identity_row_tenant_mismatch")
            expected = expected_entity_id if expected_entity_id is not None else expected_source_id
            if (
                expected is not None
                and source_field
                and str(row.get(source_field) or "") != expected
            ):
                return [], IdentityBatchRead(available=False, reason=reason_on_mismatch)
        return rows, read

    @staticmethod
    def _validated_edge_rows(
        read: IdentityBatchRead, tenant_id: str, entity_id: Optional[str]
    ) -> tuple[list[dict[str, Any]], IdentityBatchRead]:
        if not read.available or entity_id is None:
            return [], read
        rows = [row for row in read.rows if _is_mapping(row)]
        if len(rows) != len(read.rows):
            return [], IdentityBatchRead(available=False, reason="identity_edge_shape_mismatch")
        for row in rows:
            if row.get("tenant_id") != tenant_id:
                return [], IdentityBatchRead(
                    available=False, reason="identity_edge_tenant_mismatch"
                )
            if entity_id not in {
                str(row.get("source_entity_id") or ""),
                str(row.get("target_entity_id") or ""),
            }:
                return [], IdentityBatchRead(
                    available=False, reason="identity_edge_subject_mismatch"
                )
        return rows, read


def _safe_canonical_entity(row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return {
        "id": _safe_text(row.get("entity_id") or row.get("id")),
        "type": _safe_text(row.get("entity_type")),
        "status": _safe_text(row.get("status")),
        "createdAt": _safe_text(row.get("created_at")),
        "updatedAt": _safe_text(row.get("updated_at")),
    }


def _safe_identity_subject(row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return {
        "id": _safe_text(row.get("id")),
        "canonicalEntityId": _safe_text(row.get("canonical_entity_id")),
        "type": _safe_text(row.get("entity_type")),
        "status": _safe_text(row.get("status")),
        "mergedIntoEntityId": _safe_text(row.get("merged_into_entity_id")),
        "firstSeenAt": _safe_text(row.get("first_seen_at")),
        "lastSeenAt": _safe_text(row.get("last_seen_at")),
        "createdAt": _safe_text(row.get("created_at")),
        "updatedAt": _safe_text(row.get("updated_at")),
    }


def _safe_source_identity(
    row: dict[str, Any], *, include_canonical_entity: bool = True
) -> dict[str, Any]:
    status = _safe_text(row.get("status"))
    if _is_suppressed(status):
        return {
            "id": _safe_text(row.get("id")),
            "status": status,
            "suppressed": True,
            "identifierTypes": [],
        }
    return {
        "id": _safe_text(row.get("id")),
        "sourceKind": _safe_text(row.get("source_kind")),
        "sourceNamespace": _safe_text(row.get("source_namespace")),
        "status": status,
        "canonicalEntityId": (
            _safe_text(row.get("canonical_entity_id")) if include_canonical_entity else None
        ),
        "identifierTypes": sorted(field for field in _SOURCE_IDENTIFIER_FIELDS if row.get(field)),
        "firstSeenAt": _safe_text(row.get("first_seen_at")),
        "lastSeenAt": _safe_text(row.get("last_seen_at")),
    }


def _safe_claim(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _safe_text(row.get("id")),
        "claimType": _safe_text(row.get("claim_type")),
        "verificationStatus": _safe_text(row.get("verification_status")),
        "confidenceHint": _bounded_confidence(row.get("confidence_hint")),
        "piiClassification": _safe_text(row.get("pii_classification")),
        "status": _safe_text(row.get("status")),
        "occurredAt": _safe_text(row.get("occurred_at")),
        "ingestedAt": _safe_text(row.get("ingested_at")),
        "expiresAt": _safe_text(row.get("expires_at")),
    }


def _safe_alias(row: dict[str, Any]) -> dict[str, Any]:
    revoked_at = _safe_text(row.get("revoked_at"))
    return {
        "id": _safe_text(row.get("id")),
        "aliasType": _safe_text(row.get("alias_type")),
        "redactedDisplayValue": (
            None if revoked_at else _safe_text(row.get("alias_display_value_redacted"))
        ),
        "source": _safe_text(row.get("source")),
        "sourcePlatform": _safe_text(row.get("source_platform")),
        "confidence": _bounded_confidence(row.get("confidence")),
        "confidenceTier": _safe_text(row.get("confidence_tier")),
        "firstSeenAt": _safe_text(row.get("first_seen_at")),
        "lastSeenAt": _safe_text(row.get("last_seen_at")),
        "revokedAt": revoked_at,
    }


def _safe_edge(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _safe_text(row.get("id")),
        "sourceEntityId": _safe_text(row.get("source_entity_id")),
        "targetEntityId": _safe_text(row.get("target_entity_id")),
        "type": _safe_text(row.get("edge_type")),
        "confidence": _bounded_confidence(row.get("confidence")),
        "confidenceTier": _safe_text(row.get("confidence_tier")),
        "reasonCodes": _safe_string_list(row.get("reason_codes")),
        "createdAt": _safe_text(row.get("created_at")),
        "revokedAt": _safe_text(row.get("revoked_at")),
    }


def _safe_decision(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _safe_text(row.get("decision_id") or row.get("id")),
        "decisionType": _safe_text(row.get("decision_type")),
        "confidence": _bounded_confidence(row.get("confidence_score")),
        "confidenceTier": _safe_text(row.get("confidence_tier")),
        "reviewStatus": _safe_text(row.get("review_status")),
        "policyDecisionId": _safe_text(row.get("policy_decision_id")),
        "createdAt": _safe_text(row.get("created_at")),
        "mergePolicyVersion": _safe_text(row.get("merge_policy_version")),
    }


def _safe_verification(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _safe_text(row.get("id")),
        "evidenceType": _safe_text(row.get("evidence_type")),
        "identifierType": _safe_text(row.get("identifier_type")),
        "verificationMethod": _safe_text(row.get("verification_method")),
        "assuranceLevel": _safe_text(row.get("assurance_level")),
        "issuer": _safe_text(row.get("issuer")),
        "status": _safe_text(row.get("status")),
        "verifiedAt": _safe_text(row.get("verified_at")),
        "expiresAt": _safe_text(row.get("expires_at")),
        "revokedAt": _safe_text(row.get("revoked_at")),
    }


def _row_ref(row: dict[str, Any], source: str) -> Optional[EvidenceRef]:
    identifier = _safe_text(
        row.get("decision_id")
        or row.get("id")
        or row.get("entity_id")
        or row.get("canonical_entity_id")
    )
    if not identifier:
        return None
    return EvidenceRef(
        id=identifier,
        type="annotation",
        source=source,
        observedAt=_safe_text(
            row.get("updated_at")
            or row.get("last_seen_at")
            or row.get("verified_at")
            or row.get("created_at")
            or row.get("ingested_at")
        ),
        confidence=_bounded_confidence(
            row.get("confidence_score")
            if row.get("confidence_score") is not None
            else row.get("confidence")
        ),
    )


def _batch_state(
    read: IdentityBatchRead,
    *,
    known_subject: bool,
    any_rows: bool,
    failures: list[str],
) -> IdentitySlotState:
    if not read.available:
        return "degraded"
    if read.truncated:
        return "truncated"
    if not known_subject:
        return "degraded" if failures else "unknown"
    return "available" if any_rows else "empty"


def _aggregate_state(
    reads: list[IdentityBatchRead], *, known_subject: bool, row_count: int
) -> IdentitySlotState:
    if any(not read.available for read in reads):
        return "degraded"
    if any(read.truncated for read in reads):
        return "truncated"
    if not known_subject:
        return "unknown"
    return "available" if row_count else "empty"


def _batch_coverage(read: IdentityBatchRead, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "state": "degraded"
        if not read.available
        else "truncated"
        if read.truncated
        else "available"
        if rows
        else "empty",
        "returned": len(rows),
        "truncated": read.truncated,
        "reason": read.reason,
    }


def _freshness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = [
        timestamp
        for row in rows
        for timestamp in (
            _safe_text(row.get("updated_at"))
            or _safe_text(row.get("last_seen_at"))
            or _safe_text(row.get("verified_at"))
            or _safe_text(row.get("created_at"))
            or _safe_text(row.get("ingested_at")),
        )
        if timestamp
    ]
    latest = max(timestamps) if timestamps else None
    age: Optional[float] = None
    if latest:
        try:
            parsed = datetime.fromisoformat(latest.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            age = max(
                0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
            )
        except ValueError:
            latest = None
    return {
        "state": "unknown",
        "observedAt": latest,
        "ageSeconds": age,
        "policy": "not_evaluated",
        "reason": "No canonical Identity360 freshness threshold is bound to this read service.",
    }


def _dedupe_refs(refs: list[EvidenceRef]) -> tuple[EvidenceRef, ...]:
    seen: set[tuple[str, str]] = set()
    result: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.source, ref.id)
        if key not in seen:
            seen.add(key)
            result.append(ref)
    return tuple(result)


def _bounded_confidence(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0.0 <= number <= 1.0 else None


def _safe_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_suppressed(value: Any) -> bool:
    return str(getattr(value, "value", value) or "").strip().lower() in {
        "suppressed",
        "deleted",
        "erased",
    }


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return sorted({text for item in value if (text := _safe_text(item))})


def _is_mapping(value: Any) -> bool:
    return isinstance(value, dict)


def _first_reason(*reads: IdentityBatchRead) -> Optional[str]:
    for read in reads:
        if read.reason:
            return read.reason
    return None


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "Identity360Provider",
    "Identity360Result",
    "Identity360Slot",
    "Identity360Source",
    "IdentityBatchRead",
    "IdentityRecordRead",
    "RepositoryIdentity360Source",
]
