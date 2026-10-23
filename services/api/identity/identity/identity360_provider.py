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
from shared.temporal.instant import coerce_utc_lenient
from typing import Any, Literal, Optional, Protocol

from graph.operational_intelligence.models import EvidenceRef


IdentitySubjectKind = Literal["entity", "agent", "source"]
IdentitySlotState = Literal[
    "available", "empty", "partial", "unknown", "degraded", "truncated", "suppressed"
]

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


@dataclass(frozen=True)
class IdentityProviderRegistryRead:
    """Exact provider-runtime registry lookup for one recorded source system."""

    entry: Optional[dict[str, Any]] = None
    available: bool = True
    reason: Optional[str] = None


class Identity360Source(Protocol):
    """Injectable reads from canonical entity, identity and evidence stores."""

    async def canonical_entity(self, tenant_id: str, entity_id: str) -> IdentityRecordRead: ...

    async def identity_subject(self, tenant_id: str, entity_id: str) -> IdentityRecordRead: ...

    async def source_identity(
        self, tenant_id: str, source_identity_id: str
    ) -> IdentityRecordRead: ...

    async def provider_registry_entry(
        self, source_system_id: str
    ) -> IdentityProviderRegistryRead: ...

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

    async def conflicts_for_entity(
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

    async def provider_registry_entry(
        self, source_system_id: str
    ) -> IdentityProviderRegistryRead:
        """Resolve only an exact recorded provider key against the runtime registry.

        This does not parse a namespace, infer a provider from a prefix, or load
        plugins as a side effect of a read. The application loads the registry
        during startup; an absent exact key therefore remains explicitly
        unknown to Identity360.
        """
        if not source_system_id.strip():
            return IdentityProviderRegistryRead(reason="source_system_id_not_recorded")
        try:
            from connectors.provider_runtime.registry import provider_registry

            plugin = provider_registry.get(source_system_id)
            if plugin is None:
                return IdentityProviderRegistryRead(reason="provider_identity_not_registered")
            identity = plugin.identity()
            manifest = plugin.manifest()
        except Exception as exc:  # noqa: BLE001 - lookup failures stay content-free
            return IdentityProviderRegistryRead(
                available=False,
                reason=f"provider_registry_{type(exc).__name__}",
            )

        identity_key = _safe_text(getattr(identity, "key", None))
        manifest_key = _safe_text(getattr(manifest, "identity_key", None))
        if identity_key != source_system_id or manifest_key != source_system_id:
            return IdentityProviderRegistryRead(
                available=False,
                reason="provider_registry_identity_mismatch",
            )
        return IdentityProviderRegistryRead(
            entry={
                "identityKey": identity_key,
                "providerFamily": _safe_text(getattr(manifest, "provider_family", None)),
                "productId": _safe_text(getattr(manifest, "product_id", None)),
                "capabilityId": _safe_text(getattr(manifest, "capability_id", None)),
                "displayName": _safe_text(getattr(manifest, "display_name", None)),
                "category": _safe_text(getattr(manifest, "category", None)),
            }
        )

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

    async def conflicts_for_entity(
        self, tenant_id: str, entity_id: str, *, limit: int
    ) -> IdentityBatchRead:
        """Read tenant-scoped identity conflicts and retain exact entity matches.

        The canonical conflict repository exposes a tenant list rather than an
        entity filter. This bounded read filters its returned rows against the
        exact canonical candidate ids and carries truncation conservatively so
        absence is never inferred from an incomplete tenant list.
        """
        try:
            rows = await self._identity_repo().get_conflicts(tenant_id, limit=limit + 1)
        except Exception as exc:  # noqa: BLE001 - provider reports bounded degradation
            return IdentityBatchRead(
                available=False,
                reason=f"identity_conflicts_{type(exc).__name__}",
            )
        scoped: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                return IdentityBatchRead(available=False, reason="identity_conflict_shape_mismatch")
            if row.get("tenant_id") != tenant_id:
                return IdentityBatchRead(
                    available=False, reason="identity_conflict_tenant_mismatch"
                )
            candidates: list[str] = []
            for field in ("candidate_entity_ids", "involved_canonical_entity_ids"):
                values = row.get(field) or []
                if not isinstance(values, (list, tuple, set)):
                    return IdentityBatchRead(
                        available=False, reason="identity_conflict_subject_shape_mismatch"
                    )
                candidates.extend(str(value) for value in values if value is not None)
            if entity_id in candidates:
                scoped.append(row)
        return IdentityBatchRead(
            rows=tuple(scoped[:limit]),
            truncated=len(rows) > limit or len(scoped) > limit,
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
            "identifier_inventory",
            "namespace_map",
            "match_evidence",
            "conflicts",
            "confidence",
            "aliases",
            "devices_sessions",
            "wallets",
            "policy_redactions",
            "evidence_trace",
        }
        requested = slot_ids if requested_slot_ids is None else set(requested_slot_ids)
        if requested - slot_ids:
            raise ValueError("Identity360 request contains an unknown slot")
        want_identifiers = "identifier_inventory" in requested
        want_namespaces = "namespace_map" in requested
        want_matches = "match_evidence" in requested
        want_conflicts = "conflicts" in requested
        want_confidence = "confidence" in requested
        want_aliases = "aliases" in requested
        want_devices = "devices_sessions" in requested
        want_wallets = "wallets" in requested
        want_policy = "policy_redactions" in requested
        want_trace = "evidence_trace" in requested
        want_subject = bool(
            requested
            & {
                "match_evidence",
                "conflicts",
                "confidence",
                "aliases",
                "wallets",
                "evidence_trace",
            }
        )
        want_lineage = bool(
            requested
            & {"identifier_inventory", "namespace_map", "devices_sessions", "wallets", "evidence_trace"}
        )
        want_relationships = bool(requested & {"match_evidence", "confidence", "evidence_trace"})
        want_evidence = bool(
            requested & {"match_evidence", "confidence", "aliases", "evidence_trace"}
        )
        want_verification = bool(requested & {"match_evidence", "wallets", "evidence_trace"})
        want_claims = want_identifiers or want_trace
        needs_entity_scope = bool(requested)

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
                        subject_scope_known = False
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
        conflicts_read = IdentityBatchRead()
        verification_read = IdentityBatchRead()
        claim_read = IdentityBatchRead()
        provider_registry_reads: dict[str, IdentityProviderRegistryRead] = {}

        source_rows: list[dict[str, Any]] = []
        claim_rows: list[dict[str, Any]] = []
        if subject_kind == "source" and source_row is not None:
            source_rows = [source_row]
            source_rows_read = IdentityBatchRead(rows=(source_row,))
            if source_suppressed:
                claim_read = IdentityBatchRead(reason="source_identity_suppressed")
            elif want_claims:
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
                claim_rows, claim_read = self._validated_provenance_rows(
                    claim_read, claim_rows, "identity_claims"
                )

        if entity_id is not None and subject_scope_known:
            if subject_kind != "source" and want_lineage:
                source_rows_read = await self._safe_batch(
                    "source_identities",
                    self._source.source_identities_for_entity(
                        tenant_id, entity_id, limit=self._limit
                    ),
                )
                source_rows, source_rows_read = self._validated_rows(
                    source_rows_read,
                    tenant_id,
                    expected_entity_id=entity_id,
                    source_field="canonical_entity_id",
                )
                source_rows, source_rows_read = self._validated_provenance_rows(
                    source_rows_read, source_rows, "identity_source_identities"
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
            if want_verification:
                verification_read = await self._safe_batch(
                    "identity_verification_evidence",
                    self._source.verification_for_entity(tenant_id, entity_id, limit=self._limit),
                )
            if want_conflicts or want_trace:
                conflicts_read = await self._safe_batch(
                    "identity_conflicts",
                    self._source.conflicts_for_entity(tenant_id, entity_id, limit=self._limit),
                )

        # Namespace metadata is joined only through the exact source-system key
        # recorded by the tenant-scoped identity authority. In particular, never
        # derive a provider from a namespace prefix or infer a tenant connection.
        if want_namespaces and not source_suppressed:
            provider_system_ids = {
                source_system_id
                for row in source_rows
                if not _is_suppressed(row.get("status"))
                and _safe_text(row.get("source_namespace"))
                and (source_system_id := _safe_text(row.get("source_system_id")))
            }
            for source_system_id in sorted(provider_system_ids):
                provider_registry_reads[source_system_id] = (
                    await self._safe_provider_registry_entry(source_system_id)
                )

        aliases, aliases_read = self._validated_rows(
            aliases_read,
            tenant_id,
            expected_entity_id=entity_id,
            source_field="canonical_entity_id",
            reason_on_mismatch="identity_alias_scope_mismatch",
        )
        aliases, aliases_read = self._validated_provenance_rows(
            aliases_read, aliases, "identity_aliases"
        )
        edges, edges_read = self._validated_edge_rows(edges_read, tenant_id, entity_id)
        decision_rows, decisions_read = self._validated_rows(
            decisions_read,
            tenant_id,
            expected_entity_id=entity_id,
            source_field="entity_id",
        )
        conflict_rows, conflicts_read = self._validated_conflicts(
            conflicts_read, tenant_id, entity_id
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
                {
                    **_safe_source_identity(
                        row,
                        include_canonical_entity=bool(safe_entity and safe_subject),
                    ),
                    "evidenceRef": _required_row_ref(
                        row, "identity_source_identities"
                    ).model_dump(mode="json", exclude_none=True),
                }
                for row in source_rows
            ]
        else:
            source_items = [
                {
                    **_safe_source_identity(row),
                    "evidenceRef": _required_row_ref(
                        row, "identity_source_identities"
                    ).model_dump(mode="json", exclude_none=True),
                }
                for row in source_rows
            ]
        lineage_refs = [
            ref
            for ref in (_row_ref(row, "identity_source_identities") for row in source_rows)
            if ref is not None
        ]
        lineage_ref_by_source_id = {
            source_id: ref
            for row in source_rows
            if (source_id := _safe_text(row.get("id")))
            if (ref := _row_ref(row, "identity_source_identities")) is not None
        }
        claim_items = [
            {
                **_safe_claim(row),
                "evidenceRef": _required_row_ref(row, "identity_claims").model_dump(
                    mode="json", exclude_none=True
                ),
            }
            for row in claim_rows
        ]
        claim_refs = [
            ref
            for ref in (_row_ref(row, "identity_claims") for row in claim_rows)
            if ref is not None
        ]
        alias_items = [
            {
                **_safe_alias(row),
                "evidenceRef": _required_row_ref(row, "identity_aliases").model_dump(
                    mode="json", exclude_none=True
                ),
            }
            for row in aliases
        ]
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
        wallet_verification_rows = [
            row
            for row in verification_rows
            if row.get("identifier_type") == "wallet"
            and row.get("evidence_type") == "wallet_ownership_verified"
        ]
        wallet_verification_items = [
            _safe_verification(row) for row in wallet_verification_rows
        ]
        wallet_verification_refs = [
            ref
            for ref in (
                _row_ref(row, "identity_verification_evidence")
                for row in wallet_verification_rows
            )
            if ref is not None
        ]
        conflict_items = [_safe_conflict(row) for row in conflict_rows]
        conflict_refs = [
            ref for ref in (_row_ref(row, "identity_conflicts") for row in conflict_rows) if ref is not None
        ]
        verification_items = [_safe_verification(row) for row in verification_rows]
        verification_refs = [
            ref
            for ref in (
                _row_ref(row, "identity_verification_evidence") for row in verification_rows
            )
            if ref is not None
        ]

        for provider_read in provider_registry_reads.values():
            if provider_read.reason:
                warnings.append(provider_read.reason)

        freshness = _freshness(
            [
                *source_rows,
                *claim_rows,
                *aliases,
                *edges,
                *decision_rows,
                *conflict_rows,
                *verification_rows,
            ]
        )
        entity_identity_known = entity_id is not None and subject_scope_known

        if subject_kind != "source":
            claim_coverage: dict[str, Any] = {
                "state": "not_read",
                "returned": None,
                "truncated": None,
                "reason": "Claims are read only by exact source identity.",
            }
        elif source_suppressed:
            claim_coverage = {
                "state": "suppressed",
                "returned": None,
                "truncated": None,
                "reason": "Claims were not read because the source identity is suppressed.",
            }
        elif source_row is None:
            claim_coverage = {
                "state": "unknown" if source_record_read.available else "degraded",
                "returned": None,
                "truncated": None,
                "reason": "The exact source identity record is unavailable.",
            }
        elif want_claims:
            claim_coverage = _batch_coverage(claim_read, claim_rows)
        else:
            claim_coverage = {
                "state": "not_read",
                "returned": None,
                "truncated": None,
                "reason": "Source claims were not needed for the requested slots.",
            }

        source_identity_coverage = (
            {
                "state": "suppressed",
                "returned": None,
                "truncated": None,
                "reason": "The source identity is suppressed.",
            }
            if subject_kind == "source" and source_suppressed
            else {
                "state": "degraded"
                if not source_record_read.available
                else "available"
                if source_row is not None
                else "unknown",
                "returned": 1 if source_row is not None else 0,
                "truncated": False,
            }
            if subject_kind == "source"
            else _batch_coverage(source_rows_read, source_rows)
        )

        if subject_kind == "source":
            if source_suppressed:
                identifier_state: IdentitySlotState = "suppressed"
                identifier_reason = "source_identity_suppressed"
            elif source_row is None:
                identifier_state = "degraded" if not source_record_read.available else "unknown"
                identifier_reason = source_record_read.reason or "source_identity_record_unavailable"
            elif not claim_read.available and want_claims:
                identifier_state = "degraded"
                identifier_reason = claim_read.reason or "identity_claim_read_degraded"
            elif claim_read.truncated:
                identifier_state = "truncated"
                identifier_reason = "identity_claim_read_truncated"
            elif source_items[0].get("identifierTypes") or claim_items:
                identifier_state = "available"
                identifier_reason = None
            else:
                identifier_state = "empty"
                identifier_reason = None
        else:
            identifier_state = _batch_state(
                source_rows_read,
                known_subject=subject_scope_known,
                any_rows=bool(source_items),
                failures=warnings,
            )
            identifier_reason = source_rows_read.reason or (
                "identity_subject_not_resolved" if not subject_scope_known else None
            )

        source_row_by_id = {
            source_id: row
            for row in source_rows
            if (source_id := _safe_text(row.get("id"))) is not None
        }
        namespace_items: list[dict[str, Any]] = []
        for item in source_items:
            if not item.get("sourceNamespace"):
                continue
            source_row = source_row_by_id.get(str(item.get("id") or ""), {})
            source_system_id = _safe_text(source_row.get("source_system_id"))
            provider_read = provider_registry_reads.get(source_system_id or "")
            provider_entry = provider_read.entry if provider_read is not None else None
            provider_join_state = (
                "resolved"
                if provider_entry is not None
                else "degraded"
                if provider_read is not None and not provider_read.available
                else "unknown"
            )
            namespace_items.append(
                {
                    "sourceIdentityId": item.get("id"),
                    "sourceKind": item.get("sourceKind"),
                    "sourceNamespace": item.get("sourceNamespace"),
                    "canonicalEntityId": item.get("canonicalEntityId"),
                    "status": item.get("status"),
                    "evidenceRef": item.get("evidenceRef"),
                    "providerIdentity": (
                        provider_entry.get("identityKey") if provider_entry is not None else None
                    ),
                    "provider": provider_entry,
                    "providerRegistryJoin": {
                        "state": provider_join_state,
                        "reason": (
                            None
                            if provider_join_state == "resolved"
                            else provider_read.reason
                            if provider_read is not None
                            else "source_system_id_not_recorded"
                        ),
                    },
                }
            )
            if provider_read is None:
                warnings.append("source_system_id_not_recorded")
        namespace_metadata_incomplete = len(namespace_items) < len(source_items)
        namespace_provider_reads = [
            provider_registry_reads[source_system_id]
            for row in source_rows
            if not _is_suppressed(row.get("status"))
            and _safe_text(row.get("source_namespace"))
            and (source_system_id := _safe_text(row.get("source_system_id")))
            and source_system_id in provider_registry_reads
        ]
        namespace_registry_degraded = any(
            not provider_read.available for provider_read in namespace_provider_reads
        )
        namespace_registry_complete = (
            bool(source_items)
            and not namespace_metadata_incomplete
            and len(namespace_items) == len(source_items)
            and len(namespace_provider_reads) == len(namespace_items)
            and all(provider_read.entry is not None for provider_read in namespace_provider_reads)
        )
        namespace_registry_summary = {
            "state": "partial"
            if namespace_registry_complete
            else "degraded"
            if namespace_registry_degraded
            else "partial"
            if source_items
            else "unknown",
            "authority": "provider_runtime_registry",
            "joinState": "resolved"
            if namespace_registry_complete
            else "degraded"
            if namespace_registry_degraded
            else "unknown",
            "resolvedEntries": sum(
                provider_read.entry is not None for provider_read in namespace_provider_reads
            ),
            "unknownEntries": sum(
                provider_read.entry is None and provider_read.available
                for provider_read in namespace_provider_reads
            )
            + max(0, len(namespace_items) - len(namespace_provider_reads)),
            "degradedEntries": sum(
                not provider_read.available for provider_read in namespace_provider_reads
            ),
            "reason": (
                "provider_registry_freshness_unknown"
                if namespace_registry_complete
                else "provider_identity_lookup_incomplete"
                if source_items and not namespace_registry_degraded
                else "provider_registry_read_degraded"
                if namespace_registry_degraded
                else None
            ),
            "freshness": {
                "state": "unknown",
                "reason": "provider_runtime_registry_has_no_read_watermark",
            },
        }
        if subject_kind == "source":
            if source_row is None:
                namespace_state: IdentitySlotState = (
                    "degraded" if not source_record_read.available else "unknown"
                )
                namespace_reason = source_record_read.reason or "source_identity_record_unavailable"
            elif source_suppressed:
                namespace_state = "suppressed"
                namespace_reason = "source_identity_suppressed"
            elif namespace_items and namespace_registry_complete:
                namespace_state = "partial"
                namespace_reason = "provider_registry_freshness_unknown"
            elif namespace_items and namespace_registry_degraded:
                namespace_state = "degraded"
                namespace_reason = "source_provider_registry_read_degraded"
            elif namespace_items:
                namespace_state = "partial"
                namespace_reason = (
                    "source_namespace_metadata_incomplete"
                    if namespace_metadata_incomplete
                    else "source_provider_identity_unresolved"
                )
            else:
                namespace_state = "unknown"
                namespace_reason = "source_namespace_not_recorded"
        else:
            if not subject_scope_known:
                namespace_state = (
                    "degraded" if not source_rows_read.available or warnings else "unknown"
                )
                namespace_reason = source_rows_read.reason or "identity_subject_not_resolved"
            elif not source_rows_read.available:
                namespace_state = "degraded"
                namespace_reason = source_rows_read.reason or "source_identity_read_degraded"
            elif source_rows_read.truncated:
                namespace_state = "truncated"
                namespace_reason = "source_identity_read_truncated"
            elif not source_items:
                namespace_state = "empty"
                namespace_reason = None
            elif namespace_metadata_incomplete or namespace_registry_degraded:
                namespace_state = "degraded"
                namespace_reason = (
                    "source_provider_registry_read_degraded"
                    if namespace_registry_degraded
                    else "source_namespace_metadata_incomplete"
                )
            elif namespace_registry_complete:
                namespace_state = "partial"
                namespace_reason = "provider_registry_freshness_unknown"
            elif namespace_items:
                namespace_state = "partial"
                namespace_reason = "source_provider_identity_unresolved"
            else:
                namespace_state = "degraded"
                namespace_reason = "source_namespace_not_recorded"

        alias_state = (
            _batch_state(
                aliases_read,
                known_subject=True,
                any_rows=bool(aliases),
                failures=warnings,
            )
            if entity_identity_known
            else "degraded"
            if not aliases_read.available
            else "unknown"
        )
        alias_reason = aliases_read.reason or (
            "identity_subject_not_resolved" if not entity_identity_known else None
        )

        match_state: IdentitySlotState
        if not entity_identity_known:
            match_state = "degraded" if warnings and subject_kind != "source" else "unknown"
            match_reason = (
                "source_identity_not_resolved"
                if subject_kind == "source"
                else "canonical_identity_join_unavailable"
            )
        else:
            match_state = _aggregate_state(
                [aliases_read, edges_read, decisions_read, verification_read],
                known_subject=True,
                row_count=len(aliases) + len(edges) + len(decision_rows) + len(verification_rows),
            )
            match_reason = _first_reason(
                aliases_read, edges_read, decisions_read, verification_read
            )

        conflict_state = (
            _batch_state(
                conflicts_read,
                known_subject=True,
                any_rows=bool(conflict_rows),
                failures=warnings,
            )
            if entity_identity_known
            else "degraded"
            if not conflicts_read.available
            else "unknown"
        )
        conflict_reason = conflicts_read.reason or (
            "canonical_identity_join_unavailable" if not entity_identity_known else None
        )

        confidence_scores: list[dict[str, Any]] = []
        for kind, rows, source_name in (
            ("identity_alias", aliases, "identity_aliases"),
            ("identity_edge", edges, "identity_edges"),
            ("identity_decision", decision_rows, "identity_decision_evidence"),
        ):
            for row in rows:
                ref = _row_ref(row, source_name)
                score = _bounded_confidence(
                    row.get("confidence_score")
                    if row.get("confidence_score") is not None
                    else row.get("confidence")
                )
                if score is not None and ref is not None:
                    confidence_scores.append(
                        {
                            "evidenceType": kind,
                            "score": score,
                            "tier": _safe_text(row.get("confidence_tier")),
                            "evidenceRef": ref.model_dump(mode="json"),
                        }
                    )
        confidence_state = (
            "unknown"
            if not entity_identity_known
            else _aggregate_state(
                [aliases_read, edges_read, decisions_read],
                known_subject=True,
                row_count=len(confidence_scores),
            )
        )
        confidence_reason = (
            "canonical_identity_join_unavailable"
            if not entity_identity_known
            else _first_reason(aliases_read, edges_read, decisions_read)
        )

        device_identifier_types = {"device_id", "installation_id", "session_id"}
        device_session_items: list[dict[str, Any]] = []
        device_session_evidence_missing = False
        for item in source_items:
            observed_types = sorted(
                device_identifier_types.intersection(item.get("identifierTypes", []))
            )
            if not observed_types:
                continue
            evidence_ref = lineage_ref_by_source_id.get(str(item.get("id") or ""))
            if evidence_ref is None:
                # Do not surface a device/session observation without a
                # canonical source-identity evidence pointer.
                device_session_evidence_missing = True
                continue
            device_session_items.append(
                {
                    "sourceIdentityId": item.get("id"),
                    "identifierTypes": observed_types,
                    "firstSeenAt": item.get("firstSeenAt"),
                    "lastSeenAt": item.get("lastSeenAt"),
                    "evidenceRef": evidence_ref.model_dump(mode="json", exclude_none=True),
                }
            )
        device_session_refs = _dedupe_refs(
            [
                lineage_ref_by_source_id[str(item["sourceIdentityId"])]
                for item in device_session_items
                if str(item.get("sourceIdentityId") or "") in lineage_ref_by_source_id
            ]
        )
        if subject_kind == "source":
            devices_state: IdentitySlotState = (
                "unknown"
                if source_row is None and source_record_read.available
                else "degraded"
                if source_row is None
                else "suppressed"
                if source_suppressed
                else "degraded"
                if device_session_evidence_missing
                else "degraded"
                if not source_record_read.available
                else "partial"
                if device_session_items
                else "unknown"
            )
            devices_reason = (
                "source_identity_record_unavailable"
                if source_row is None
                else "source_identity_suppressed"
                if source_suppressed
                else "device_session_evidence_ref_missing"
                if device_session_evidence_missing
                else "source_identity_read_degraded"
                if not source_record_read.available
                else "device_session_inventory_authority_not_joined"
            )
        else:
            devices_state = (
                "degraded"
                if not source_rows_read.available or device_session_evidence_missing
                else "truncated"
                if source_rows_read.truncated
                else "partial"
                if device_session_items
                else "unknown"
            )
            devices_reason = source_rows_read.reason or (
                "identity_subject_not_resolved"
                if not subject_scope_known
                else "device_session_evidence_ref_missing"
                if device_session_evidence_missing
                else "device_session_inventory_authority_not_joined"
            )

        wallet_candidates = [
            {
                "sourceIdentityId": item.get("id"),
                "sourceKind": item.get("sourceKind"),
                "sourceNamespace": item.get("sourceNamespace"),
                "status": item.get("status"),
            }
            for item in source_items
            if item.get("sourceKind") == "sdk_wallet"
            or "wallet" in str(item.get("sourceNamespace") or "").lower()
        ]
        if not want_wallets:
            wallet_state: IdentitySlotState = "unknown"
            wallet_reason = "identity_slot_not_requested"
        elif not subject_scope_known:
            wallet_state = "degraded" if warnings else "unknown"
            wallet_reason = "identity_subject_not_resolved"
        elif not verification_read.available:
            wallet_state = "degraded"
            wallet_reason = verification_read.reason or "wallet_proof_read_degraded"
        elif verification_read.truncated:
            wallet_state = "truncated"
            wallet_reason = "wallet_proof_read_truncated"
        elif wallet_verification_items:
            # Verification evidence proves control at a point in time. It is
            # not a wallet inventory and does not establish current control.
            wallet_state = "partial"
            wallet_reason = "wallet_ownership_proof_observed_current_control_unknown"
        else:
            # An empty proof query does not establish that the entity has no
            # wallets, so preserve unknown rather than returning an empty set.
            wallet_state = "unknown"
            wallet_reason = "wallet_ownership_proof_not_observed_wallet_presence_unknown"

        all_refs = _dedupe_refs(
            [
                *subject_refs,
                *lineage_refs,
                *claim_refs,
                *alias_refs,
                *edge_refs,
                *decision_refs,
                *conflict_refs,
                *verification_refs,
            ]
        )
        all_reads = [
            source_rows_read,
            claim_read,
            aliases_read,
            edges_read,
            decisions_read,
            conflicts_read,
            verification_read,
        ]
        trace_state: IdentitySlotState
        if not subject_scope_known:
            trace_state = "degraded" if warnings else "unknown"
        elif any(not read.available for read in all_reads):
            trace_state = "degraded"
        elif any(read.truncated for read in all_reads):
            trace_state = "truncated"
        else:
            trace_state = "available" if all_refs else "empty"

        def slot_state(slot_id: str, state: IdentitySlotState) -> IdentitySlotState:
            return state if slot_id in requested else "unknown"

        slots = (
            Identity360Slot(
                id="identifier_inventory",
                state=slot_state("identifier_inventory", identifier_state),
                content=(
                    {
                        "state": identifier_state,
                        "sourceIdentities": source_items,
                        "claims": claim_items,
                        "identifierValuesIncluded": False,
                        "coverage": {
                            "sourceIdentities": source_identity_coverage,
                            "sourceClaims": claim_coverage,
                        },
                        "freshness": freshness,
                    }
                    if want_identifiers
                    else {"state": "unknown", "reason": "identity_slot_not_requested"}
                ),
                evidence_refs=(
                    _dedupe_refs([*lineage_refs, *claim_refs, *subject_refs])
                    if want_identifiers
                    else ()
                ),
                reason=identifier_reason if want_identifiers else "identity_slot_not_requested",
                truncated=(
                    claim_read.truncated if subject_kind == "source" else source_rows_read.truncated
                )
                if want_identifiers
                else False,
            ),
            Identity360Slot(
                id="namespace_map",
                state=slot_state("namespace_map", namespace_state),
                content=(
                    {
                        "state": namespace_state,
                        "mappings": namespace_items,
                        "authority": "identity_source_identities",
                        "completeness": "observed_source_identity_metadata",
                        "canonicalNamespaceRegistryJoin": namespace_registry_summary,
                        "freshness": freshness,
                    }
                    if want_namespaces
                    else {"state": "unknown", "reason": "identity_slot_not_requested"}
                ),
                evidence_refs=_dedupe_refs([*lineage_refs, *subject_refs]) if want_namespaces else (),
                reason=namespace_reason if want_namespaces else "identity_slot_not_requested",
                truncated=source_rows_read.truncated if want_namespaces else False,
            ),
            Identity360Slot(
                id="match_evidence",
                state=slot_state("match_evidence", match_state),
                content=(
                    {
                        "state": match_state,
                        "subjectResolution": {
                            "state": "resolved" if entity_identity_known else "unknown",
                            "subject": {"kind": subject_kind, "id": subject_id},
                            "canonicalEntity": safe_entity,
                            "identitySubject": safe_subject,
                            "authority": "entities+identity_subjects",
                        },
                        "decisions": decision_items,
                        "identityEdges": edge_items,
                        "aliases": alias_items,
                        "verificationEvidence": verification_items,
                        "semantics": "recorded_identity_resolution_evidence_only",
                        "limitations": [
                            "No identity decision is recomputed by this provider.",
                            "Raw identifier values, signal payloads, hashes, proof material, and consent snapshots are omitted.",
                            "Identity edges do not assert social or business relationships.",
                        ],
                        "freshness": freshness,
                    }
                    if want_matches
                    else {"state": "unknown", "reason": "identity_slot_not_requested"}
                ),
                evidence_refs=(
                    _dedupe_refs(
                        [*subject_refs, *decision_refs, *edge_refs, *alias_refs, *verification_refs]
                    )
                    if want_matches
                    else ()
                ),
                reason=match_reason if want_matches else "identity_slot_not_requested",
                truncated=(
                    any(
                        read.truncated
                        for read in (aliases_read, edges_read, decisions_read, verification_read)
                    )
                    if want_matches
                    else False
                ),
            ),
            Identity360Slot(
                id="conflicts",
                state=slot_state("conflicts", conflict_state),
                content=(
                    {
                        "state": conflict_state,
                        "items": conflict_items,
                        "authority": "identity_conflicts",
                        "coverage": _batch_coverage(conflicts_read, conflict_rows),
                        "freshness": freshness,
                    }
                    if want_conflicts
                    else {"state": "unknown", "reason": "identity_slot_not_requested"}
                ),
                evidence_refs=(
                    _dedupe_refs([*conflict_refs, *subject_refs]) if want_conflicts else ()
                ),
                reason=conflict_reason if want_conflicts else "identity_slot_not_requested",
                truncated=conflicts_read.truncated if want_conflicts else False,
            ),
            Identity360Slot(
                id="confidence",
                state=slot_state("confidence", confidence_state),
                content=(
                    {
                        "state": confidence_state,
                        "scores": confidence_scores,
                        "compositeConfidence": None,
                        "semantics": "source_reported_evidence_scores_only",
                        "reason": "No calibrated composite identity confidence is owned by this read provider.",
                        "freshness": freshness,
                    }
                    if want_confidence
                    else {"state": "unknown", "reason": "identity_slot_not_requested"}
                ),
                evidence_refs=(
                    _dedupe_refs([*alias_refs, *edge_refs, *decision_refs, *subject_refs])
                    if want_confidence
                    else ()
                ),
                reason=confidence_reason if want_confidence else "identity_slot_not_requested",
                truncated=(
                    any(read.truncated for read in (aliases_read, edges_read, decisions_read))
                    if want_confidence
                    else False
                ),
            ),
            Identity360Slot(
                id="aliases",
                state=slot_state("aliases", alias_state),
                content=(
                    {
                        "state": alias_state,
                        "items": alias_items,
                        "valuesRedacted": True,
                        "coverage": _batch_coverage(aliases_read, aliases),
                        "freshness": freshness,
                    }
                    if want_aliases
                    else {"state": "unknown", "reason": "identity_slot_not_requested"}
                ),
                evidence_refs=_dedupe_refs(alias_refs) if want_aliases else (),
                reason=alias_reason if want_aliases else "identity_slot_not_requested",
                truncated=aliases_read.truncated if want_aliases else False,
            ),
            Identity360Slot(
                id="devices_sessions",
                state=slot_state("devices_sessions", devices_state),
                content=(
                    {
                        "state": devices_state,
                        "sourceIdentityObservations": device_session_items,
                        "sourceIdentityCoverage": source_identity_coverage,
                        "observedIdentifierCount": len(device_session_items),
                        "inventoryState": "unknown",
                        "identifierValuesIncluded": False,
                        "limitations": [
                            "This is source identity identifier metadata, not a device or session inventory.",
                            "Dedicated device and session authorities are not joined by Identity360.",
                        ],
                        "freshness": freshness,
                    }
                    if want_devices
                    else {"state": "unknown", "reason": "identity_slot_not_requested"}
                ),
                evidence_refs=device_session_refs if want_devices else (),
                reason=devices_reason if want_devices else "identity_slot_not_requested",
                truncated=source_rows_read.truncated if want_devices else False,
            ),
            Identity360Slot(
                id="wallets",
                state=slot_state("wallets", wallet_state),
                content=(
                    {
                        "state": wallet_state,
                        "observedSourceCandidates": wallet_candidates,
                        "ownershipProofs": wallet_verification_items,
                        "ownershipState": "unknown",
                        "currentControl": "unknown",
                        "addressIncluded": False,
                        "identifierHashIncluded": False,
                        "authority": "identity_verification_evidence",
                        "coverage": {
                            "verificationEvidence": _batch_coverage(
                                verification_read, verification_rows
                            ),
                            "walletOwnershipProofsReturned": len(wallet_verification_items),
                        },
                        "limitations": [
                            "Wallet addresses and identifier hashes are omitted.",
                            "Verification proves control at the recorded time only; current control is unknown.",
                            "Source candidates do not establish ownership.",
                        ],
                        "reason": wallet_reason,
                        "freshness": _freshness(wallet_verification_rows),
                    }
                    if want_wallets
                    else {"state": "unknown", "reason": "identity_slot_not_requested"}
                ),
                evidence_refs=(
                    _dedupe_refs(
                        [
                            ref
                            for item, ref in zip(source_items, lineage_refs)
                            if item.get("sourceKind") == "sdk_wallet"
                            or "wallet" in str(item.get("sourceNamespace") or "").lower()
                        ]
                        + wallet_verification_refs
                    )
                    if want_wallets
                    else ()
                ),
                reason=wallet_reason if want_wallets else "identity_slot_not_requested",
                truncated=verification_read.truncated if want_wallets else False,
            ),
            Identity360Slot(
                id="policy_redactions",
                state=slot_state("policy_redactions", "degraded"),
                content=(
                    {
                        "state": "degraded",
                        "projectionRedaction": {
                            "state": "applied",
                            "authority": "identity360_output_sanitizer",
                        },
                        "authorizationPolicy": {
                            "state": "unknown",
                            "reason": "policy_context_and_decision_authority_not_joined",
                            "freshness": "unknown",
                        },
                        "redactedCategories": [
                            "raw_identifier_values",
                            "identifier_hashes",
                            "signal_payloads",
                            "proof_material",
                            "consent_snapshots",
                            "private_names",
                        ],
                    }
                    if want_policy
                    else {"state": "unknown", "reason": "identity_slot_not_requested"}
                ),
                evidence_refs=all_refs if want_policy else (),
                reason=(
                    "policy_context_and_decision_authority_not_joined"
                    if want_policy
                    else "identity_slot_not_requested"
                ),
            ),
            Identity360Slot(
                id="evidence_trace",
                state=slot_state("evidence_trace", trace_state),
                content=(
                    {
                        "state": trace_state,
                        "evidenceRefs": [ref.model_dump(mode="json") for ref in all_refs],
                        "freshness": freshness,
                        "coverage": {
                            "sourceIdentities": source_identity_coverage,
                            "sourceClaims": claim_coverage,
                            "aliases": _batch_coverage(aliases_read, aliases),
                            "identityEdges": _batch_coverage(edges_read, edges),
                            "decisions": _batch_coverage(decisions_read, decision_rows),
                            "conflicts": _batch_coverage(conflicts_read, conflict_rows),
                            "verification": _batch_coverage(verification_read, verification_rows),
                        },
                    }
                    if want_trace
                    else {"state": "unknown", "reason": "identity_slot_not_requested"}
                ),
                evidence_refs=all_refs if want_trace else (),
                reason=(
                    "identity_evidence_read_degraded"
                    if trace_state == "degraded"
                    else "identity_evidence_read_truncated"
                    if trace_state == "truncated"
                    else None
                    if want_trace
                    else "identity_slot_not_requested"
                ),
                truncated=any(read.truncated for read in all_reads) if want_trace else False,
            ),
        )

        required_states = [
            slot.state
            for slot in slots
            if slot.id in requested
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

    async def _safe_provider_registry_entry(
        self, source_system_id: str
    ) -> IdentityProviderRegistryRead:
        reader = getattr(self._source, "provider_registry_entry", None)
        if not callable(reader):
            return IdentityProviderRegistryRead(
                available=False,
                reason="provider_registry_reader_unavailable",
            )
        try:
            result = await reader(source_system_id)
        except Exception as exc:  # noqa: BLE001 - keep registry diagnostics private
            return IdentityProviderRegistryRead(
                available=False,
                reason=f"provider_registry_{type(exc).__name__}",
            )
        if not isinstance(result, IdentityProviderRegistryRead):
            return IdentityProviderRegistryRead(
                available=False,
                reason="provider_registry_invalid_read_result",
            )
        if not result.available:
            return IdentityProviderRegistryRead(
                available=False,
                reason=result.reason or "provider_registry_read_degraded",
            )
        if result.entry is not None and result.entry.get("identityKey") != source_system_id:
            return IdentityProviderRegistryRead(
                available=False,
                reason="provider_registry_identity_mismatch",
            )
        if result.entry is None:
            return result
        return IdentityProviderRegistryRead(
            entry={
                "identityKey": source_system_id,
                **{
                    field: _safe_text(result.entry.get(field))
                    for field in (
                        "providerFamily",
                        "productId",
                        "capabilityId",
                        "displayName",
                        "category",
                    )
                },
            }
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
    def _validated_provenance_rows(
        read: IdentityBatchRead,
        rows: list[dict[str, Any]],
        source: str,
    ) -> tuple[list[dict[str, Any]], IdentityBatchRead]:
        """Reject scoped records that cannot carry an exact record-level ref."""
        if not read.available:
            return [], read
        if any(_required_row_ref_or_none(row, source) is None for row in rows):
            return [], IdentityBatchRead(
                available=False,
                truncated=read.truncated,
                reason=f"{source}_evidence_ref_missing",
            )
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

    @staticmethod
    def _validated_conflicts(
        read: IdentityBatchRead, tenant_id: str, entity_id: Optional[str]
    ) -> tuple[list[dict[str, Any]], IdentityBatchRead]:
        if not read.available or entity_id is None:
            return [], read
        rows = [row for row in read.rows if _is_mapping(row)]
        if len(rows) != len(read.rows):
            return [], IdentityBatchRead(available=False, reason="identity_conflict_shape_mismatch")
        scoped: list[dict[str, Any]] = []
        for row in rows:
            if row.get("tenant_id") != tenant_id:
                return [], IdentityBatchRead(
                    available=False, reason="identity_conflict_tenant_mismatch"
                )
            candidate_ids: list[str] = []
            for field in ("candidate_entity_ids", "involved_canonical_entity_ids"):
                values = row.get(field) or []
                if not isinstance(values, (list, tuple, set)):
                    return [], IdentityBatchRead(
                        available=False, reason="identity_conflict_subject_shape_mismatch"
                    )
                candidate_ids.extend(str(value) for value in values if value is not None)
            if entity_id in candidate_ids:
                scoped.append(row)
        return scoped, read


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
            _safe_text(row.get("canonical_entity_id"))
            if include_canonical_entity and status == "resolved"
            else None
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
    metadata = row.get("metadata")
    chain_namespace = (
        _safe_text(metadata.get("chain_namespace"))
        if row.get("identifier_type") == "wallet" and isinstance(metadata, dict)
        else None
    )
    item = {
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
    if row.get("identifier_type") == "wallet":
        item["chainNamespace"] = chain_namespace
    return item


def _safe_conflict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _safe_text(row.get("id")),
        "type": _safe_text(row.get("conflict_type")),
        "status": _safe_text(row.get("status")),
        "confidence": _bounded_confidence(row.get("confidence")),
        "reasonCodes": _safe_string_list(row.get("reason_codes")),
        "severity": _safe_text(row.get("severity")),
        "recommendedAction": _safe_text(row.get("recommended_action")),
        "createdAt": _safe_text(row.get("created_at")),
        "resolvedAt": _safe_text(row.get("resolved_at")),
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


def _required_row_ref_or_none(row: dict[str, Any], source: str) -> Optional[EvidenceRef]:
    """Build a row-level evidence pointer without falling back to its subject."""
    if not _safe_text(row.get("id")):
        return None
    return _row_ref(row, source)


def _required_row_ref(row: dict[str, Any], source: str) -> EvidenceRef:
    ref = _required_row_ref_or_none(row, source)
    if ref is None:
        raise ValueError(f"{source} row passed without a validated evidence reference")
    return ref


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
            parsed = coerce_utc_lenient(latest)
            if parsed is None:
                raise ValueError(latest)
            age = max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())
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
    "IdentityProviderRegistryRead",
    "IdentityBatchRead",
    "IdentityRecordRead",
    "RepositoryIdentity360Source",
]
