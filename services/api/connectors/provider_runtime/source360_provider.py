"""Tenant-scoped Source360 projection over canonical identity and connector evidence.

Source360 reads Identity360 source-identity lineage for entity/agent subjects,
and Universal Provider Runtime connection records plus admitted provider-record
Bronze lineage for source/connection subjects. It does not infer a provider
connection from an identity namespace, or treat a connection as proof of
provider health, schema completeness, expected coverage, or freshness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from graph.operational_intelligence.models import EvidenceRef, PageInfo
from shared.contracts_models.epistemic import EpistemicStatus
from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
)
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTION_DEFINITIONS,
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.provider import IntelligenceProjectionProvider

PROJECTION_ID = "source360"
OUTPUT_SECTIONS: tuple[str, ...] = tuple(
    INTELLIGENCE_PROJECTION_DEFINITIONS[PROJECTION_ID]["outputSections"]
)
SUPPORTED_SUBJECT_KINDS = frozenset({"source", "connection", "entity", "agent"})
_IDENTITY_LINEAGE_SUBJECT_KINDS = frozenset({"entity", "agent"})

_MAX_CONNECTIONS = 100
_MAX_PROVIDER_RECORD_SCAN = 500
_MAX_CLAIMS = 100
_CONNECTION_SOURCE = "services/api/connectors/provider_runtime/connection.py:provider_connections"
_BRONZE_SOURCE = "services/api/repositories/lake.py:bronze_provider_records"
_SOURCE_SLOTS = (
    "source_identifier_lineage",
    "identity_evidence",
    "source_and_policy_context",
    "evidence_and_coverage",
    "source_signals_and_coverage",
    "source_lineage_and_coverage",
)
_CONNECTION_SLOTS = ("evidence_and_source_lineage",)


@dataclass(frozen=True)
class SourceRowsRead:
    """Bounded connection rows with explicit availability and completeness."""

    rows: list[dict[str, Any]]
    available: bool
    complete: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class ProviderRecordsRead:
    """Tenant/provider Bronze rows and exact provider-scope count when known."""

    rows: list[dict[str, Any]]
    total_count: Optional[int]
    available: bool
    complete: bool
    reason: Optional[str] = None


class Source360Source(Protocol):
    """Injectable read seam for tenant connections and provider Bronze lineage."""

    async def connections(
        self,
        *,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        limit: int,
    ) -> SourceRowsRead: ...

    async def provider_records(
        self,
        *,
        tenant_id: str,
        provider_identity: str,
        limit: int,
    ) -> ProviderRecordsRead: ...

    async def source_authority(self, rights_decision_ref: str, *, tenant_id: str) -> Any: ...


class IdentityLineageReader(Protocol):
    """Canonical identity authority used for entity/agent source lineage."""

    async def read(self, tenant_id: str, subject_kind: str, subject_id: str) -> Any: ...


class RepositoryIdentityLineageReader:
    """Adapter over Identity360's exact subject and source-lineage read."""

    def __init__(self, provider: Any = None) -> None:
        self._provider = provider

    async def read(self, tenant_id: str, subject_kind: str, subject_id: str) -> Any:
        if self._provider is None:
            from identity.identity.identity360_provider import Identity360Provider

            self._provider = Identity360Provider()
        return await self._provider.read(
            tenant_id,
            subject_kind,
            subject_id,
            requested_slot_ids={"source_identifier_lineage"},
        )


class RepositorySource360Source:
    """Adapter over tenant-filtered UPR connection and provider Bronze stores."""

    def __init__(self, *, connections: Any = None, bronze: Any = None) -> None:
        self._connections = connections
        self._bronze = bronze

    def _connection_repository(self) -> Any:
        if self._connections is None:
            from connectors.provider_runtime.connection import ProviderConnectionRepository

            self._connections = ProviderConnectionRepository()
        return self._connections

    def _bronze_repository(self) -> Any:
        if self._bronze is None:
            from repositories.lake import BronzeRepository

            self._bronze = BronzeRepository("provider_records")
        return self._bronze

    async def connections(
        self,
        *,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        limit: int,
    ) -> SourceRowsRead:
        repository = self._connection_repository()
        try:
            if subject_kind == "connection":
                rows = await repository.find_many(
                    filters={"tenant_id": tenant_id, "connection_id": subject_id},
                    limit=2,
                )
                complete = len(rows) < 2
            elif subject_kind == "source":
                bounded_limit = min(max(limit, 1), _MAX_CONNECTIONS) + 1
                rows = await repository.find_many(
                    filters={
                        "tenant_id": tenant_id,
                        "provider_identity": subject_id,
                    },
                    sort_by="created_at",
                    sort_order="desc",
                    limit=bounded_limit,
                )
                complete = len(rows) < bounded_limit
            else:
                return SourceRowsRead([], True, True, "unsupported_source_subject")
        except Exception:  # noqa: BLE001 - keep storage diagnostics private
            return SourceRowsRead([], False, False, "provider_connection_authority_unavailable")

        scoped = [
            row
            for row in rows
            if isinstance(row, dict)
            and row.get("tenant_id") == tenant_id
            and (
                row.get("connection_id") == subject_id
                if subject_kind == "connection"
                else row.get("provider_identity") == subject_id
            )
        ]
        if len(scoped) != len(rows):
            return SourceRowsRead(
                scoped[:limit], False, False, "unscoped_connection_authority_rows_dropped"
            )
        if subject_kind == "connection" and len(scoped) > 1:
            return SourceRowsRead(scoped[:limit], True, False, "duplicate_connection_records")
        return SourceRowsRead(
            scoped[:limit], True, complete, None if complete else "connection_read_truncated"
        )

    async def provider_records(
        self,
        *,
        tenant_id: str,
        provider_identity: str,
        limit: int,
    ) -> ProviderRecordsRead:
        filters = {
            "tenant_id": tenant_id,
            "source": provider_identity,
            "provenance_status": "valid",
            "license_status": "tenant_rights_granted",
            "terms_status": "active_grant",
            "quarantine_status": "not_quarantined",
        }
        repository = self._bronze_repository()
        try:
            total = await repository.count(filters=filters)
            rows = await repository.find_many(
                filters=filters,
                sort_by="created_at",
                sort_order="desc",
                limit=_MAX_PROVIDER_RECORD_SCAN + 1,
            )
        except Exception:  # noqa: BLE001 - keep storage diagnostics private
            return ProviderRecordsRead(
                [], None, False, False, "provider_evidence_authority_unavailable"
            )

        if not isinstance(total, int) or total < 0:
            return ProviderRecordsRead(
                [], None, False, False, "provider_evidence_count_unavailable"
            )
        if len(rows) > _MAX_PROVIDER_RECORD_SCAN:
            rows = rows[:_MAX_PROVIDER_RECORD_SCAN]
        complete = total <= len(rows)
        return ProviderRecordsRead(
            [row for row in rows if isinstance(row, dict)],
            total,
            True,
            complete,
            None if complete else "provider_evidence_scan_truncated",
        )

    async def source_authority(self, rights_decision_ref: str, *, tenant_id: str) -> Any:
        """Resolve one admitted record's historical decision to its tenant grant."""
        from tenancy.rights_authority.source_lineage import trace_source_authority

        return await trace_source_authority(rights_decision_ref, tenant_id=tenant_id)


class Source360Provider(IntelligenceProjectionProvider):
    """Project connector identity and admitted source evidence conservatively."""

    projection_id = PROJECTION_ID
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    def __init__(
        self,
        source: Optional[Source360Source] = None,
        *,
        identity_lineage_reader: Optional[IdentityLineageReader] = None,
    ) -> None:
        self._source = source if source is not None else RepositorySource360Source()
        self._identity_lineage = (
            identity_lineage_reader
            if identity_lineage_reader is not None
            else RepositoryIdentityLineageReader()
        )

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        generated_at = datetime.now(timezone.utc).isoformat()
        tenant_id = request.tenantId
        subject = request.subject
        temporal_mode = request.temporalMode or "window"
        claims: list[ClaimEnvelope] = []
        warnings: list[str] = []

        if (
            not tenant_id.strip()
            or context.tenantId != tenant_id
            or subject.kind not in SUPPORTED_SUBJECT_KINDS
            or not subject.id.strip()
        ):
            reason = (
                "source_subject_to_provider_join_unsupported"
                if subject.kind not in SUPPORTED_SUBJECT_KINDS
                else "source_request_scope_or_identifier_invalid"
            )
            sections = _unknown_sections(reason)
            return _result(
                request,
                context,
                sections,
                [],
                generated_at,
                temporal_mode,
                degraded_reasons=[reason],
            )

        if subject.kind in _IDENTITY_LINEAGE_SUBJECT_KINDS:
            return await self._project_identity_lineage(
                request,
                context,
                generated_at=generated_at,
                temporal_mode=temporal_mode,
            )

        if request.asOf is not None:
            reason = "historical_source_snapshot_unavailable"
            sections = _unknown_sections(reason)
            return _result(
                request,
                context,
                sections,
                [],
                generated_at,
                temporal_mode,
                degraded_reasons=[reason],
            )
        if temporal_mode not in {"window", "relative"}:
            reason = "source_temporal_mode_unsupported"
            sections = _unknown_sections(reason)
            return _result(
                request,
                context,
                sections,
                [],
                generated_at,
                temporal_mode,
                degraded_reasons=[reason],
            )
        if temporal_mode == "relative" and request.timeRange is None:
            reason = "relative_source_window_unresolved"
            sections = _unknown_sections(reason)
            return _result(
                request,
                context,
                sections,
                [],
                generated_at,
                temporal_mode,
                degraded_reasons=[reason],
            )

        time_bounds, time_issue = _time_bounds(request)
        if time_issue is not None:
            sections = _unknown_sections(time_issue)
            return _result(
                request,
                context,
                sections,
                [],
                generated_at,
                temporal_mode,
                degraded_reasons=[time_issue],
            )

        source_connections = await self._safe_connections(request)
        connection_rows = _scoped_connections(source_connections, tenant_id, subject)
        connection_mismatch = len(connection_rows) != len(source_connections.rows)
        if connection_mismatch:
            warnings.append("unscoped_connection_authority_rows_dropped")
            source_connections = SourceRowsRead(
                connection_rows,
                source_connections.available,
                False,
                "unscoped_connection_authority_rows_dropped",
            )

        connection_id: Optional[str] = None
        provider_identity: Optional[str] = None
        if subject.kind == "connection":
            if len(connection_rows) == 1:
                connection_id = _text(connection_rows[0].get("connection_id"))
                provider_identity = _text(connection_rows[0].get("provider_identity"))
            elif len(connection_rows) > 1:
                warnings.append("duplicate_connection_records")
            else:
                # A caller cannot supply a provider identity for an unresolved
                # connection and thereby expand the query's tenant scope.
                if not source_connections.available or not source_connections.complete:
                    reason = source_connections.reason or (
                        "provider_connection_authority_unavailable"
                        if not source_connections.available
                        else "provider_connection_read_incomplete"
                    )
                    return _result(
                        request,
                        context,
                        _unknown_sections(reason),
                        [],
                        generated_at,
                        temporal_mode,
                        degraded_reasons=[reason],
                    )
                sections = _missing_connection_sections(
                    request,
                    generated_at,
                    temporal_mode,
                    source_connections.reason or "tenant_connection_record_not_found",
                )
                return _result(
                    request,
                    context,
                    sections,
                    [],
                    generated_at,
                    temporal_mode,
                    degraded_reasons=[
                        source_connections.reason or "tenant_connection_record_not_found"
                    ],
                )
        else:
            provider_identity = subject.id

        if not provider_identity:
            reason = "provider_identity_unresolved"
            sections = _unknown_sections(reason)
            return _result(
                request,
                context,
                sections,
                [],
                generated_at,
                temporal_mode,
                degraded_reasons=[reason],
            )

        raw_read = await self._safe_provider_records(tenant_id, provider_identity)
        records, record_mismatch = _validated_records(
            raw_read,
            tenant_id=tenant_id,
            provider_identity=provider_identity,
            connection_id=connection_id,
            time_bounds=time_bounds,
        )
        if record_mismatch:
            warnings.append("provider_record_provenance_mismatch")

        manifest = _manifest_summary(provider_identity)
        connection_refs = [
            _connection_ref(row) for row in connection_rows if _connection_ref(row) is not None
        ]
        record_refs = [
            _provider_record_ref(row)
            for row in records[: _page_limit(request)]
            if _provider_record_ref(row) is not None
        ]
        if len(record_refs) != min(len(records), _page_limit(request)):
            warnings.append("provider_record_evidence_reference_unavailable")

        raw_record_count, count_scope, sample_truncated = _record_count(
            request=request,
            raw_read=raw_read,
            records=records,
            connection_id=connection_id,
            time_bounds=time_bounds,
        )
        evidence_state = _evidence_state(
            raw_read=raw_read,
            refs=record_refs,
            known_count=raw_record_count,
            complete=raw_read.complete,
            mismatch=record_mismatch,
            connection_id=connection_id,
            time_bounds=time_bounds,
        )
        source_authority_lineage, lineage_complete = await self._source_authority_lineage(
            tenant_id=tenant_id,
            provider_identity=provider_identity,
            records=records,
            record_refs=record_refs,
        )
        if not lineage_complete:
            warnings.append("provider_rights_lineage_unavailable")
            if evidence_state == "available":
                evidence_state = "degraded"

        source_exists = bool(connection_rows or raw_record_count and raw_record_count > 0)
        source_lookup_complete = (
            source_connections.available
            and source_connections.complete
            and raw_read.available
            and raw_read.complete
        )
        if subject.kind == "connection":
            connection_state = (
                "degraded"
                if connection_rows and not source_connections.complete
                else "available"
                if connection_rows
                else "unknown"
            )
        elif connection_rows:
            connection_state = "available" if source_connections.complete else "degraded"
        elif source_exists and source_connections.available and source_connections.complete:
            connection_state = "missing"
        elif source_lookup_complete:
            connection_state = "missing"
        else:
            connection_state = "unknown"

        summary_state = (
            "degraded"
            if source_exists and not source_lookup_complete
            else "available"
            if source_exists
            else "missing"
            if source_lookup_complete
            else "degraded"
            if not source_connections.available or not raw_read.available
            else "unknown"
        )
        if source_connections.reason:
            warnings.append(source_connections.reason)
        if raw_read.reason:
            warnings.append(raw_read.reason)

        connection_inventory = [_public_connection(row) for row in connection_rows]
        connection_inventory = [row for row in connection_inventory if row is not None]
        manifest_state = "available" if manifest is not None else "unknown"
        summary_content = {
            "subject": {"kind": subject.kind, "id": subject.id},
            "providerIdentity": provider_identity,
            "providerManifestState": manifest_state,
            "providerManifest": manifest,
            "connectionCount": (
                len(connection_rows)
                if source_connections.available and source_connections.complete
                else None
            ),
            "connectionInventoryTruncated": (
                not source_connections.complete if source_connections.available else None
            ),
            "providerRecordCount": raw_record_count,
            "providerRecordCountScope": count_scope,
            "providerRecordSampleTruncated": sample_truncated,
        }
        state_content = {
            "subject": {"kind": subject.kind, "id": subject.id},
            "connectionLifecycle": connection_state,
            "lifecycleRecords": connection_inventory,
            "sourceEvidence": evidence_state,
            "providerHealth": "unknown",
            "freshness": "unknown",
        }
        evidence_content = {
            "subject": {"kind": subject.kind, "id": subject.id},
            "providerIdentity": provider_identity,
            "connectionEvidence": connection_refs,
            "providerRecordEvidence": record_refs,
            "providerRecordCount": raw_record_count,
            "providerRecordCountScope": count_scope,
            "sampleLimit": _page_limit(request),
            "sampleTruncated": sample_truncated,
            "timeAxis": "bronze_ingested_at",
            "rawPayloadIncluded": False,
            "rightsInterpretation": "records filtered to persisted valid tenant grant provenance",
            "sourceAuthorityLineage": source_authority_lineage,
            "sourceAuthorityLineageState": (
                "available" if lineage_complete else "degraded" if records else "unknown"
            ),
        }

        if request.includeClaims is not False:
            claims.extend(
                _connection_claims(
                    request=request,
                    connections=connection_rows,
                    domain_slot_ids=(
                        _CONNECTION_SLOTS if subject.kind == "connection" else _SOURCE_SLOTS
                    ),
                )
            )
            claims.extend(
                _record_claims(
                    request=request,
                    refs=record_refs,
                    domain_slot_ids=(
                        _CONNECTION_SLOTS if subject.kind == "connection" else _SOURCE_SLOTS
                    ),
                )
            )
        if len(claims) > _MAX_CLAIMS:
            claims = claims[:_MAX_CLAIMS]
            warnings.append("source_claim_limit_reached")

        sections = [
            ProjectionSection(
                id="summary",
                state=summary_state,
                title="Source summary",
                content=summary_content,
                warnings=sorted(set(warnings)),
            ),
            ProjectionSection(
                id="state",
                state=connection_state,
                title="Source lifecycle state",
                content=state_content,
                warnings=sorted(set(warnings)),
            ),
            ProjectionSection(
                id="evidence",
                state=evidence_state,
                title="Source evidence lineage",
                content=evidence_content,
                warnings=sorted(set(warnings)),
            ),
            ProjectionSection(
                id="health",
                state="unknown",
                title="Source health",
                warnings=[
                    "provider_health_authority_unavailable",
                    "freshness_threshold_unavailable",
                ],
            ),
            ProjectionSection(
                id="coverage",
                state="unknown",
                title="Source coverage",
                warnings=[
                    "source_schema_authority_unavailable",
                    "expected_source_coverage_authority_unavailable",
                    "historical_coverage_completeness_unavailable",
                ],
            ),
        ]
        if request.includeSections is not None:
            wanted = set(request.includeSections)
            sections = [section for section in sections if section.id in wanted]

        page = _page_info(raw_record_count, len(record_refs), raw_read, sample_truncated)
        return _result(
            request,
            context,
            sections,
            claims,
            generated_at,
            temporal_mode,
            page=page,
            degraded_reasons=sorted(set(warnings)),
        )

    async def _safe_connections(self, request: ProjectionRequest) -> SourceRowsRead:
        try:
            return await self._source.connections(
                tenant_id=request.tenantId,
                subject_kind=request.subject.kind,
                subject_id=request.subject.id,
                limit=_MAX_CONNECTIONS,
            )
        except Exception:  # noqa: BLE001 - fail-closed provider boundary
            return SourceRowsRead([], False, False, "provider_connection_authority_unavailable")

    async def _safe_provider_records(
        self, tenant_id: str, provider_identity: str
    ) -> ProviderRecordsRead:
        try:
            return await self._source.provider_records(
                tenant_id=tenant_id,
                provider_identity=provider_identity,
                limit=_MAX_PROVIDER_RECORD_SCAN,
            )
        except Exception:  # noqa: BLE001 - fail-closed provider boundary
            return ProviderRecordsRead(
                [], None, False, False, "provider_evidence_authority_unavailable"
            )

    async def _project_identity_lineage(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
        *,
        generated_at: str,
        temporal_mode: str,
    ) -> ProjectionResult:
        """Project exact Identity360 lineage without inferring provider joins."""
        subject = request.subject
        temporal_filter = bool(
            request.asOf is not None
            or temporal_mode != "window"
            or (
                request.timeRange is not None
                and (request.timeRange.from_ is not None or request.timeRange.to is not None)
            )
        )
        if temporal_filter:
            reason = "source_identity_temporal_history_unavailable"
            return _result(
                request,
                context,
                _unknown_sections(reason),
                [],
                generated_at,
                temporal_mode,
                degraded_reasons=[reason],
            )

        try:
            identity_result = await self._identity_lineage.read(
                request.tenantId, subject.kind, subject.id
            )
            if (
                getattr(identity_result, "tenant_id", None) != request.tenantId
                or getattr(identity_result, "subject_kind", None) != subject.kind
                or getattr(identity_result, "subject_id", None) != subject.id
            ):
                reason = "identity_source_lineage_scope_mismatch"
                identity_slot = None
            else:
                identity_slot = identity_result.slot("source_identifier_lineage")
                reason = getattr(identity_slot, "reason", None)
        except Exception:  # noqa: BLE001 - identity authority failures remain private
            identity_slot = None
            reason = "identity_source_lineage_authority_unavailable"

        slot_state = getattr(identity_slot, "state", "degraded")
        mapped_state = "degraded" if slot_state == "truncated" else slot_state
        if mapped_state not in {"available", "empty", "degraded", "unknown", "suppressed"}:
            mapped_state = "unknown"
        content = getattr(identity_slot, "content", {})
        source_identities = content.get("sourceIdentities", []) if isinstance(content, dict) else []
        safe_identities = [
            _safe_identity_lineage_item(row) for row in source_identities if isinstance(row, dict)
        ]
        source_identity_ids = {
            row.get("id") for row in safe_identities if isinstance(row.get("id"), str)
        }
        refs = [
            ref
            for ref in getattr(identity_slot, "evidence_refs", ())
            if isinstance(ref, EvidenceRef)
            and ref.source == "identity_source_identities"
            and ref.id in source_identity_ids
        ]
        evidence_refs = [ref.model_dump(mode="json") for ref in refs]
        coverage = content.get("coverage", {}) if isinstance(content, dict) else {}
        source_coverage = coverage.get("sourceIdentities", {}) if isinstance(coverage, dict) else {}
        if not isinstance(source_coverage, dict):
            source_coverage = {}
        if identity_slot is None:
            mapped_state = "degraded"
            safe_identities = []
            evidence_refs = []
            source_coverage = {"state": "degraded", "returned": None, "truncated": None}

        warnings = [reason] if reason else []
        summary = ProjectionSection(
            id="summary",
            state=mapped_state,
            title="Source identity lineage",
            content={
                "subject": {"kind": subject.kind, "id": subject.id},
                "sourceIdentityAuthority": "identity360.source_identifier_lineage",
                "sourceIdentities": safe_identities,
                "sourceIdentityCount": source_coverage.get("returned"),
                "providerRegistryJoin": "unknown",
                "providerConnectionJoin": "unknown",
                "providerJoinLimitation": (
                    "Identity source namespaces are not joined to provider registry identities."
                ),
            },
            warnings=warnings,
        )
        state = ProjectionSection(
            id="state",
            state="unknown",
            title="Provider connection state",
            content={
                "subject": {"kind": subject.kind, "id": subject.id},
                "connectionLifecycle": "unknown",
                "reason": "identity source lineage does not establish provider connection state",
            },
            warnings=["provider_connection_join_not_performed"],
        )
        evidence = ProjectionSection(
            id="evidence",
            state=mapped_state,
            title="Source identity evidence",
            content={
                "subject": {"kind": subject.kind, "id": subject.id},
                "identitySourceEvidence": evidence_refs,
                "providerRecordEvidence": [],
                "rawPayloadIncluded": False,
                "providerRecordJoin": "unknown",
                "sourceIdentityCoverage": source_coverage,
            },
            warnings=warnings,
        )
        health = ProjectionSection(
            id="health",
            state="unknown",
            title="Provider health",
            warnings=["provider_health_authority_not_joined_for_identity_subject"],
        )
        coverage_section = ProjectionSection(
            id="coverage",
            state=mapped_state,
            title="Source identity coverage",
            content={
                "subject": {"kind": subject.kind, "id": subject.id},
                "sourceIdentities": source_coverage,
                "providerRecordCoverage": "unknown",
                "expectedSourceCoverage": "unknown",
            },
            warnings=warnings,
        )
        claims: list[ClaimEnvelope] = []
        if request.includeClaims is not False and mapped_state == "available":
            for ref in refs[:_MAX_CLAIMS]:
                claims.append(
                    ClaimEnvelope(
                        id=f"source360:{ref.id}:identity-source-record",
                        kind="canonical_identity_source_record",
                        subject=subject,
                        evidenceRefs=[ref],
                        claims=[
                            "A tenant-scoped identity source record is associated with this subject."
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=["source_identifier_lineage"],
                    )
                )

        return _result(
            request,
            context,
            [summary, state, evidence, health, coverage_section],
            claims,
            generated_at,
            temporal_mode,
            degraded_reasons=warnings,
        )

    async def _source_authority_lineage(
        self,
        *,
        tenant_id: str,
        provider_identity: str,
        records: list[dict[str, Any]],
        record_refs: list[EvidenceRef],
    ) -> tuple[list[dict[str, Any]], bool]:
        if not records:
            return [], True
        trace_method = getattr(self._source, "source_authority", None)
        if not callable(trace_method):
            return [], False

        records_by_id = {
            evidence_id: row for row in records if (evidence_id := _record_id(row)) is not None
        }
        lineage: list[dict[str, Any]] = []
        complete = True
        traces: dict[str, Any] = {}
        for evidence_ref in record_refs[:_MAX_CLAIMS]:
            row = records_by_id.get(evidence_ref.id)
            admission = _record_rights_admission(
                row,
                tenant_id=tenant_id,
                provider_identity=provider_identity,
            )
            if admission is None:
                lineage.append(
                    {
                        "recordEvidenceId": evidence_ref.id,
                        "state": "unknown",
                        "reason": "provider_rights_admission_reference_invalid",
                    }
                )
                complete = False
                continue

            decision_ref = admission.rights_decision_ref
            if decision_ref not in traces:
                try:
                    traces[decision_ref] = await trace_method(decision_ref, tenant_id=tenant_id)
                except Exception:  # noqa: BLE001 - private authority diagnostics
                    traces[decision_ref] = None
            trace = traces[decision_ref]
            if not _trace_matches_admission(
                trace,
                admission=admission,
                tenant_id=tenant_id,
                provider_identity=provider_identity,
            ):
                lineage.append(
                    {
                        "recordEvidenceId": evidence_ref.id,
                        "state": "unknown",
                        "reason": "provider_rights_authority_trace_unavailable",
                    }
                )
                complete = False
                continue

            lineage.append(
                {
                    "recordEvidenceId": evidence_ref.id,
                    "state": "available",
                    "sourceRelationship": trace.source_relationship,
                    "rightsSourceClass": trace.rights_source_class,
                    "providerIdentity": trace.provider_identity,
                    "rightsDecisionEvidence": {
                        "id": trace.rights_decision_ref,
                        "type": "record",
                        "source": "services/api/tenancy/rights_authority/repositories.py:rights_decisions",
                    },
                    "sourceGrantEvidence": {
                        "id": trace.source_grant_ref,
                        "type": "record",
                        "source": "services/api/connectors/integrations/data_rights/repository.py:data_rights_grants",
                    },
                }
            )
        if len(record_refs) > _MAX_CLAIMS:
            complete = False
        return lineage, complete


def _result(
    request: ProjectionRequest,
    context: ProjectionContext,
    sections: list[ProjectionSection],
    claims: list[ClaimEnvelope],
    generated_at: str,
    temporal_mode: str,
    *,
    page: Optional[PageInfo] = None,
    degraded_reasons: Optional[list[str]] = None,
) -> ProjectionResult:
    if request.includeSections is not None:
        wanted = set(request.includeSections)
        sections = [section for section in sections if section.id in wanted]
    section_by_id = {section.id: section for section in sections}
    sections = [
        section_by_id[section_id] for section_id in OUTPUT_SECTIONS if section_id in section_by_id
    ]
    return ProjectionResult(
        projectionId=PROJECTION_ID,
        tenantId=request.tenantId,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        sections=sections,
        claims=claims,
        dependencyState=list(context.dependencyState),
        generatedAt=generated_at,
        page=page,
        degradedReasons=degraded_reasons or [],
        temporalMode=temporal_mode,
    )


def _unknown_sections(reason: str) -> list[ProjectionSection]:
    return [
        ProjectionSection(
            id=section_id,
            state="unknown",
            title=f"Source {section_id}",
            warnings=[reason],
        )
        for section_id in OUTPUT_SECTIONS
    ]


def _missing_connection_sections(
    request: ProjectionRequest,
    generated_at: str,
    temporal_mode: str,
    reason: str,
) -> list[ProjectionSection]:
    del request, generated_at, temporal_mode
    return [
        ProjectionSection(
            id=section_id,
            state=("missing" if section_id in {"summary", "state"} else "unknown"),
            title=f"Source {section_id}",
            warnings=[reason],
        )
        for section_id in OUTPUT_SECTIONS
    ]


def _time_bounds(
    request: ProjectionRequest,
) -> tuple[Optional[tuple[Optional[datetime], Optional[datetime]]], Optional[str]]:
    time_range = request.timeRange
    if time_range is None:
        return None, None

    def parse(value: Optional[str]) -> Optional[datetime]:
        if value is None:
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone is required")
        return parsed.astimezone(timezone.utc)

    try:
        start = parse(time_range.from_)
        end = parse(time_range.to)
    except (TypeError, ValueError):
        return None, "source_time_range_invalid"
    if start is not None and end is not None and end < start:
        return None, "source_time_range_reversed"
    return (start, end), None


def _validated_records(
    read: ProviderRecordsRead,
    *,
    tenant_id: str,
    provider_identity: str,
    connection_id: Optional[str],
    time_bounds: Optional[tuple[Optional[datetime], Optional[datetime]]],
) -> tuple[list[dict[str, Any]], bool]:
    if not read.available:
        return [], False
    from shared.integration_contracts.events import RawProviderRecord, verify_checksum

    valid: list[dict[str, Any]] = []
    mismatch = False
    for row in read.rows:
        if (
            row.get("tenant_id") != tenant_id
            or row.get("source") != provider_identity
            or row.get("provenance_status") != "valid"
            or row.get("license_status") != "tenant_rights_granted"
            or row.get("terms_status") != "active_grant"
            or row.get("quarantine_status") != "not_quarantined"
        ):
            mismatch = True
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            mismatch = True
            continue
        try:
            record = RawProviderRecord.model_validate(payload)
        except Exception:  # noqa: BLE001 - malformed source data stays unknown
            mismatch = True
            continue
        if (
            record.tenant_id != tenant_id
            or record.provider_identity != provider_identity
            or not verify_checksum(record)
            or not isinstance(record.metadata, dict)
            or "aether_rights_admission" not in record.metadata
        ):
            mismatch = True
            continue
        admission = _record_rights_admission(
            row,
            tenant_id=tenant_id,
            provider_identity=provider_identity,
        )
        if admission is None:
            mismatch = True
            continue
        try:
            from connectors.provider_runtime.rights_admission import provider_source_id

            expected_source_id = provider_source_id(record)
        except Exception:  # noqa: BLE001 - unavailable source scope remains untrusted
            mismatch = True
            continue
        if (
            admission.tenant_id != tenant_id
            or admission.source_id != expected_source_id
            or admission.rights_decision_ref.strip() == ""
            or admission.source_grant_ref.strip() == ""
        ):
            mismatch = True
            continue
        if connection_id is not None and record.connection_id != connection_id:
            continue
        if time_bounds is not None:
            observed_at = _parse_timestamp(row.get("created_at"))
            if observed_at is None:
                mismatch = True
                continue
            start, end = time_bounds
            if start is not None and observed_at < start:
                continue
            if end is not None and observed_at > end:
                continue
        valid.append(row)
    return valid, mismatch


def _record_count(
    *,
    request: ProjectionRequest,
    raw_read: ProviderRecordsRead,
    records: list[dict[str, Any]],
    connection_id: Optional[str],
    time_bounds: Optional[tuple[Optional[datetime], Optional[datetime]]],
) -> tuple[Optional[int], Optional[str], Optional[bool]]:
    if not raw_read.available or not raw_read.complete:
        return None, None, None
    if request.subject.kind == "source" and time_bounds is None:
        return (
            raw_read.total_count,
            "tenant_provider_identity",
            (
                raw_read.total_count > _page_limit(request)
                if raw_read.total_count is not None
                else None
            ),
        )
    return (
        len(records),
        ("tenant_connection" if connection_id is not None else "tenant_provider_identity_window"),
        len(records) > _page_limit(request),
    )


def _evidence_state(
    *,
    raw_read: ProviderRecordsRead,
    refs: list[EvidenceRef],
    known_count: Optional[int],
    complete: bool,
    mismatch: bool,
    connection_id: Optional[str],
    time_bounds: Optional[tuple[Optional[datetime], Optional[datetime]]],
) -> str:
    if not raw_read.available or mismatch:
        return "unknown"
    if refs:
        if not complete and (connection_id is not None or time_bounds is not None):
            return "degraded"
        return "available"
    if known_count == 0:
        return "empty"
    if complete and raw_read.total_count == 0:
        return "empty"
    return "unknown"


def _manifest_summary(provider_identity: str) -> Optional[dict[str, Any]]:
    from shared.integration_contracts.catalog import manifest_by_identity

    manifest = manifest_by_identity.get(provider_identity)
    if manifest is None:
        return None
    return {
        "identity": manifest.identity_key,
        "displayName": manifest.display_name,
        "category": manifest.category,
        "dataOutputs": list(manifest.data_outputs),
        "productDestinations": list(manifest.product_destinations),
        "manifestReadiness": getattr(manifest.readiness, "value", manifest.readiness),
    }


def _scoped_connections(read: SourceRowsRead, tenant_id: str, subject: Any) -> list[dict[str, Any]]:
    if not read.available:
        return []
    rows: list[dict[str, Any]] = []
    for value in read.rows:
        row = _as_mapping(value)
        if row is None or row.get("tenant_id") != tenant_id:
            continue
        if subject.kind == "connection":
            if row.get("connection_id") != subject.id:
                continue
        elif row.get("provider_identity") != subject.id:
            continue
        rows.append(row)
    return rows


def _as_mapping(value: Any) -> Optional[dict[str, Any]]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:  # noqa: BLE001 - malformed adapter object is unknown
            return None
    return None


def _public_connection(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    connection_id = _text(row.get("connection_id"))
    provider_identity = _text(row.get("provider_identity"))
    if not connection_id or not provider_identity or not _text(row.get("tenant_id")):
        return None
    state = row.get("state")
    return {
        "connectionId": connection_id,
        "providerIdentity": provider_identity,
        "displayName": _text(row.get("display_name")) or None,
        "state": getattr(state, "value", state) if state is not None else None,
        "createdAt": _text(row.get("created_at")) or None,
        "updatedAt": _text(row.get("updated_at")) or None,
        "lastVerifiedAt": _text(row.get("last_verified_at")) or None,
        "lastSuccessfulSyncAt": _text(row.get("last_successful_sync_at")) or None,
        "externalProviderState": "not_independently_verified",
        "credentialReadiness": "unknown",
    }


def _safe_identity_lineage_item(row: dict[str, Any]) -> dict[str, Any]:
    """Retain only the already-sanitized identity lineage fields."""
    return {
        key: value
        for key, value in {
            "id": row.get("id"),
            "sourceKind": row.get("sourceKind"),
            "sourceNamespace": row.get("sourceNamespace"),
            "status": row.get("status"),
            "canonicalEntityId": row.get("canonicalEntityId"),
            "identifierTypes": row.get("identifierTypes"),
            "firstSeenAt": row.get("firstSeenAt"),
            "lastSeenAt": row.get("lastSeenAt"),
            "suppressed": row.get("suppressed"),
        }.items()
        if value is not None
    }


def _connection_ref(row: dict[str, Any]) -> Optional[EvidenceRef]:
    public = _public_connection(row)
    if public is None:
        return None
    return EvidenceRef(
        id=public["connectionId"],
        type="entity",
        source=_CONNECTION_SOURCE,
        observedAt=public.get("updatedAt") or public.get("createdAt"),
    )


def _provider_record_ref(row: dict[str, Any]) -> Optional[EvidenceRef]:
    record_id = _text(row.get("id")) or _text(row.get("provider_record_id"))
    if not record_id:
        return None
    return EvidenceRef(
        id=record_id,
        type="event",
        source=_BRONZE_SOURCE,
        observedAt=_text(row.get("created_at")) or None,
    )


def _record_id(row: dict[str, Any]) -> Optional[str]:
    return _text(row.get("id")) or _text(row.get("provider_record_id"))


def _record_rights_admission(
    row: Optional[dict[str, Any]],
    *,
    tenant_id: str,
    provider_identity: str,
) -> Any:
    if not isinstance(row, dict) or not isinstance(row.get("payload"), dict):
        return None
    try:
        from connectors.provider_runtime.rights_admission import (
            PROVIDER_RAW_RIGHTS_METADATA_KEY,
            ProviderRawRightsEvidence,
        )
        from shared.integration_contracts.events import RawProviderRecord

        record = RawProviderRecord.model_validate(row["payload"])
        if (
            record.tenant_id != tenant_id
            or record.provider_identity != provider_identity
            or not isinstance(record.metadata, dict)
        ):
            return None
        evidence = ProviderRawRightsEvidence.model_validate(
            record.metadata.get(PROVIDER_RAW_RIGHTS_METADATA_KEY)
        )
        if evidence.tenant_id != tenant_id:
            return None
        return evidence
    except Exception:  # noqa: BLE001 - malformed lineage remains unknown
        return None


def _trace_matches_admission(
    trace: Any,
    *,
    admission: Any,
    tenant_id: str,
    provider_identity: str,
) -> bool:
    return bool(
        trace is not None
        and getattr(trace, "tenant_id", None) == tenant_id
        and getattr(trace, "rights_decision_ref", None) == admission.rights_decision_ref
        and getattr(trace, "source_grant_ref", None) == admission.source_grant_ref
        and getattr(trace, "source_id", None) == admission.source_id
        and getattr(trace, "source_relationship", None) == admission.source_relationship
        and getattr(trace, "provider_identity", None) == provider_identity
    )


def _connection_claims(
    *,
    request: ProjectionRequest,
    connections: list[dict[str, Any]],
    domain_slot_ids: tuple[str, ...],
) -> list[ClaimEnvelope]:
    claims: list[ClaimEnvelope] = []
    for row in connections[:_MAX_CLAIMS]:
        evidence = _connection_ref(row)
        if evidence is None:
            continue
        connection_id = _text(row.get("connection_id"))
        claims.append(
            ClaimEnvelope(
                id=f"source360:{connection_id}:tenant-connection",
                kind="tenant_provider_connection_record",
                subject=request.subject,
                evidenceRefs=[evidence],
                claims=["A tenant-scoped provider connection record is stored."],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=list(domain_slot_ids),
            )
        )
    return claims


def _record_claims(
    *, request: ProjectionRequest, refs: list[EvidenceRef], domain_slot_ids: tuple[str, ...]
) -> list[ClaimEnvelope]:
    return [
        ClaimEnvelope(
            id=f"source360:{ref.id}:persisted-provider-evidence",
            kind="persisted_provider_evidence",
            subject=request.subject,
            evidenceRefs=[ref],
            claims=["A tenant-scoped provider record with admitted provenance is stored."],
            claimState=EpistemicStatus.OBSERVED,
            domainSlotIds=list(domain_slot_ids),
        )
        for ref in refs[:_MAX_CLAIMS]
    ]


def _page_info(
    count: Optional[int],
    evidence_sample_count: int,
    raw_read: ProviderRecordsRead,
    sample_truncated: Optional[bool],
) -> Optional[PageInfo]:
    if count is None and not raw_read.available:
        return None
    has_next: Optional[bool]
    if count is not None:
        has_next = count > evidence_sample_count
    elif sample_truncated is True or not raw_read.complete:
        has_next = True
    else:
        has_next = None
    return PageInfo(
        hasNextPage=has_next if has_next is not None else False,
        totalEstimate=count,
    )


def _page_limit(request: ProjectionRequest) -> int:
    return min(
        max(1, request.page.limit if request.page is not None else 50),
        _MAX_PROVIDER_RECORD_SCAN,
    )


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "value"):
        value = value.value
    if not isinstance(value, (str, int, float, bool)):
        return None
    text = str(value).strip()
    return text or None


def register_provider(
    registry: Any, *, source: str = "services/api/connectors/provider_runtime"
) -> str:
    """Register Source360 with the projection registry."""
    return registry.register(Source360Provider(), source=source)


__all__ = [
    "OUTPUT_SECTIONS",
    "PROJECTION_ID",
    "ProviderRecordsRead",
    "RepositorySource360Source",
    "Source360Provider",
    "Source360Source",
    "SourceRowsRead",
    "register_provider",
]
