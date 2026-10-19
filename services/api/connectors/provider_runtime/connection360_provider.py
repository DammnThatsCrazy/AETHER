"""Read-only Connection360 over tenant-scoped provider and sync records.

The provider lifecycle repository is the canonical server-authored connection
state. ``comms_sync_runs`` is the durable record of connector work. Neither is
an independent provider-health probe, a credential-readiness authority, nor a
complete source-coverage ledger. In particular, a successful sync record is
reported as a sync-ledger observation; it is not upgraded into a live health
claim or proof that downstream facts were reconciled.

The connection row is mutable and has no lifecycle history. Point-in-time
requests therefore omit its current state. Only closed sync-run records whose
completion precedes the requested anchor are eligible for an as-of response;
coverage still reports that history completeness and the reconciled control
plane are unresolved.
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
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.registry import ProviderRegistry
from shared.integration_contracts.lifecycle import ConnectionState

PROJECTION_ID = "connection360"
OUTPUT_SECTIONS: tuple[str, ...] = (
    "summary",
    "state",
    "evidence",
    "health",
    "coverage",
)
SUPPORTED_TEMPORAL_MODES: frozenset[str] = frozenset(
    {"window", "as_of", "relative"}
)

_WORKFLOW_SLOT = "integration_and_sync_context"
_MAX_CONNECTIONS = 100
_MAX_SYNC_RUNS_PER_CONNECTION = 100
_MAX_SYNC_RUNS = 500
_MAX_CLAIMS = 200
_CONNECTION_SOURCE = "provider_connections"
_SYNC_RUN_SOURCE = "comms_sync_runs"
_CLOSED_RUN_STATES = frozenset({"completed", "failed", "partial"})
_SYNC_RUN_STATES = frozenset(
    {"queued", "running", "completed", "failed", "partial", "rolled_back"}
)
_SYNC_MODES = frozenset({"initial", "backfill", "incremental"})
_RECONCILIATION_STATES = frozenset({"not_run", "pending", "reconciled", "drift"})
_CONNECTION_STATES = frozenset(state.value for state in ConnectionState)


@dataclass(frozen=True)
class AuthorityRead:
    """One bounded authority read, with completeness represented explicitly."""

    rows: list[dict[str, Any]]
    available: bool
    complete: bool
    reason: Optional[str] = None


class Connection360ReadAuthority(Protocol):
    """Tenant-bound read seam for provider connection and sync authorities."""

    async def connections(
        self, *, tenant_id: str, subject_kind: str, subject_id: str, limit: int
    ) -> AuthorityRead:
        """Read one connection or connections belonging to a provider source."""

    async def sync_runs(
        self, *, tenant_id: str, connection_id: str, limit: int
    ) -> AuthorityRead:
        """Read the durable sync ledger for one tenant connection."""


class RepositoryConnection360ReadAuthority:
    """Read through the existing tenant-filtered connection and sync APIs."""

    def __init__(self, *, connections: Any = None, sync_runs: Any = None) -> None:
        self._connections = connections
        self._sync_runs = sync_runs

    def _connection_repository(self) -> Any:
        if self._connections is None:
            from connectors.provider_runtime.connection import ProviderConnectionRepository

            self._connections = ProviderConnectionRepository()
        return self._connections

    def _sync_run_service(self) -> Any:
        if self._sync_runs is None:
            from journeys.comms.sync_runs import SyncRunService

            self._sync_runs = SyncRunService()
        return self._sync_runs

    async def connections(
        self, *, tenant_id: str, subject_kind: str, subject_id: str, limit: int
    ) -> AuthorityRead:
        repository = self._connection_repository()
        try:
            if subject_kind == "connection":
                # Match both identifiers in the repository query. This avoids
                # loading another tenant's row and then trying to redact it.
                rows = await repository.find_many(
                    filters={"tenant_id": tenant_id, "connection_id": subject_id},
                    limit=2,
                )
                complete = len(rows) < 2
            elif subject_kind == "source":
                # Read the exact tenant/provider scope from the repository.
                # Scanning an arbitrary prefix of the tenant's connections
                # could miss this source behind unrelated rows and mistake
                # tenant-wide truncation for source-coverage truncation.
                source_limit = min(max(limit, 1), _MAX_CONNECTIONS)
                rows = await repository.find_many(
                    filters={
                        "tenant_id": tenant_id,
                        "provider_identity": subject_id,
                    },
                    limit=source_limit + 1,
                )
                complete = len(rows) < source_limit + 1
                rows = [_connection_row(row) for row in rows]
            else:
                return AuthorityRead([], True, False, "unsupported_connection_subject")
        except Exception:  # noqa: BLE001 - hide persistence diagnostics at projection boundary
            return AuthorityRead([], False, False, "provider_connection_authority_unavailable")

        normalized = [_connection_row(row) for row in rows]
        scoped = [
            row
            for row in normalized
            if row.get("tenant_id") == tenant_id
            and (
                row.get("connection_id") == subject_id
                if subject_kind == "connection"
                else row.get("provider_identity") == subject_id
            )
        ]
        return AuthorityRead(
            scoped[:limit],
            True,
            complete,
            None if complete else "connection_read_truncated",
        )

    async def sync_runs(
        self, *, tenant_id: str, connection_id: str, limit: int
    ) -> AuthorityRead:
        try:
            rows = await self._sync_run_service().list_for_connector(
                tenant_id,
                connection_id,
                limit=min(limit, _MAX_SYNC_RUNS_PER_CONNECTION) + 1,
            )
        except Exception:  # noqa: BLE001 - hide persistence diagnostics at projection boundary
            return AuthorityRead([], False, False, "sync_run_authority_unavailable")
        scoped = [
            row
            for row in rows
            if isinstance(row, dict)
            and row.get("tenant_id") == tenant_id
            and row.get("connector_instance_id") == connection_id
        ]
        complete = len(rows) < min(limit, _MAX_SYNC_RUNS_PER_CONNECTION) + 1
        return AuthorityRead(
            scoped[:limit],
            True,
            complete,
            None if complete else "sync_run_read_truncated",
        )


@dataclass(frozen=True)
class _TemporalView:
    mode: str
    anchor: Optional[datetime]
    lower: Optional[datetime]
    upper: Optional[datetime]
    issue: Optional[str]


class Connection360Provider:
    """Tenant-scoped projection of connection lifecycle and sync evidence."""

    projection_id = PROJECTION_ID
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    graph_mutation_policy = "read_only"

    def __init__(self, reader: Optional[Connection360ReadAuthority] = None) -> None:
        self._reader = reader if reader is not None else RepositoryConnection360ReadAuthority()

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        generated_at = _now_iso()
        temporal = _resolve_temporal_view(request)
        warnings: list[str] = []
        if context.registryState == "in_flight":
            warnings.append("connection360_registry_implementation_state_is_in_flight")
        if temporal.issue:
            warnings.append(temporal.issue)

        source_dependency = next(
            (item for item in context.dependencyState if item.projectionId == "source360"),
            None,
        )
        dependency_state = source_dependency.state if source_dependency is not None else "missing"
        if dependency_state != "available":
            warnings.append("source360_projection_dependency_not_available")

        connection_read = AuthorityRead([], False, False, "connection_read_not_attempted")
        run_reads: list[AuthorityRead] = []
        allowed_connection_ids: set[str] = set()
        subject_id = _safe_text(request.subject.id, limit=200)
        if context.tenantId != request.tenantId:
            warnings.append("tenant_scope_mismatch")
        elif subject_id is None:
            warnings.append("connection_subject_reference_invalid")
        elif temporal.issue is None:
            subject_kind = request.subject.kind
            if subject_kind not in {"source", "connection"}:
                warnings.append("connection_subject_kind_unsupported")
            elif temporal.mode == "as_of" and subject_kind == "source":
                # Source-to-connection membership has no temporal authority;
                # current connection rows cannot be used to enumerate past runs.
                connection_read = AuthorityRead(
                    [], False, False, "source_connection_history_unavailable"
                )
                warnings.append("source_connection_membership_history_unavailable")
            elif temporal.mode == "as_of" and subject_kind == "connection":
                # The mutable connection row is not queried for a historical
                # request. The tenant-scoped sync ledger can still provide
                # closed runs for this explicit connection reference.
                connection_read = AuthorityRead(
                    [], False, False, "connection_lifecycle_history_unavailable"
                )
                run_reads.append(
                    await self._reader.sync_runs(
                        tenant_id=request.tenantId,
                        connection_id=subject_id,
                        limit=_MAX_SYNC_RUNS_PER_CONNECTION,
                    )
                )
                allowed_connection_ids.add(subject_id)
                if not run_reads[-1].available:
                    warnings.append(run_reads[-1].reason or "sync_run_authority_unavailable")
                elif not run_reads[-1].complete:
                    warnings.append(run_reads[-1].reason or "sync_run_coverage_truncated")
            else:
                connection_read = await self._reader.connections(
                    tenant_id=request.tenantId,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    limit=_MAX_CONNECTIONS,
                )
                expected_connection_match = (
                    lambda row: row.get("connection_id") == subject_id
                    if subject_kind == "connection"
                    else row.get("provider_identity") == subject_id
                )
                scoped_connection_rows = [
                    row
                    for row in connection_read.rows
                    if isinstance(row, dict)
                    and row.get("tenant_id") == request.tenantId
                    and expected_connection_match(row)
                ]
                if len(scoped_connection_rows) != len(connection_read.rows):
                    warnings.append("unscoped_connection_authority_rows_dropped")
                    connection_read = AuthorityRead(
                        scoped_connection_rows,
                        connection_read.available,
                        False,
                        "unscoped_connection_authority_rows_dropped",
                    )
                else:
                    connection_read = AuthorityRead(
                        scoped_connection_rows,
                        connection_read.available,
                        connection_read.complete,
                        connection_read.reason,
                    )
                if not connection_read.available:
                    warnings.append(connection_read.reason or "provider_connection_authority_unavailable")
                elif not connection_read.complete:
                    warnings.append(connection_read.reason or "provider_connection_coverage_truncated")

                connection_ids = [
                    _safe_text(row.get("connection_id"), limit=200)
                    for row in connection_read.rows
                ]
                connection_ids = [value for value in connection_ids if value]
                if subject_kind == "connection":
                    # The sync ledger is itself tenant-scoped. It remains
                    # queryable for an explicit tenant connection subject even
                    # when its mutable lifecycle row was removed or unavailable.
                    # The request's exact ID plus tenant-scoped repository
                    # filter are sufficient; no provider identity is inferred.
                    connection_ids.append(subject_id)
                allowed_connection_ids.update(connection_ids)
                remaining = _MAX_SYNC_RUNS
                for connection_id in dict.fromkeys(connection_ids):
                    if remaining <= 0:
                        break
                    run_read = await self._reader.sync_runs(
                        tenant_id=request.tenantId,
                        connection_id=connection_id,
                        limit=min(remaining, _MAX_SYNC_RUNS_PER_CONNECTION),
                    )
                    run_reads.append(run_read)
                    remaining -= len(run_read.rows)
                    if not run_read.available:
                        warnings.append(run_read.reason or "sync_run_authority_unavailable")
                    elif not run_read.complete:
                        warnings.append(run_read.reason or "sync_run_coverage_truncated")

        connection_rows = [
            public_row
            for row in connection_read.rows
            if (public_row := _public_connection(row)) is not None
        ]
        raw_runs: list[dict[str, Any]] = []
        for read in run_reads:
            if not read.available:
                continue
            scoped_rows = [
                row
                for row in read.rows
                if isinstance(row, dict)
                and row.get("tenant_id") == request.tenantId
                and row.get("connector_instance_id") in allowed_connection_ids
            ]
            if len(scoped_rows) != len(read.rows):
                warnings.append("unscoped_sync_authority_rows_dropped")
            raw_runs.extend(scoped_rows)
        sync_rows, temporal_warnings = _filter_runs(raw_runs, temporal)
        warnings.extend(temporal_warnings)
        sync_rows = _dedupe_runs(sync_rows)
        page_rows, page = _page_runs(sync_rows, request)
        run_records = [record for row in page_rows if (record := _public_sync_run(row)) is not None]
        connection_refs = [_connection_evidence(row) for row in connection_rows]
        run_refs = [_sync_run_evidence(row) for row in run_records]

        temporal_is_as_of = temporal.mode == "as_of"
        live_connection_data_allowed = not temporal_is_as_of and temporal.issue is None
        connection_state = (
            "unknown"
            if temporal_is_as_of
            else "missing"
            if request.subject.kind == "connection"
            and connection_read.available
            and not connection_rows
            else _authority_availability(connection_read, connection_rows)
        )
        any_sync_truncated = any(not read.complete for read in run_reads if read.available)
        has_run_observation = bool(sync_rows)

        rejected_subject = request.subject.kind not in {"source", "connection"} or subject_id is None
        if temporal.issue is not None or context.tenantId != request.tenantId or rejected_subject:
            summary_state = state_state = evidence_state = health_state = coverage_state = "unknown"
        else:
            summary_state = (
                "available"
                if connection_rows or has_run_observation
                else "missing"
                if request.subject.kind == "connection" and connection_read.available and not connection_rows and not has_run_observation
                else "empty"
                if connection_read.available and connection_read.complete and not connection_rows
                else "unknown"
            )
            state_state = (
                "unknown"
                if temporal_is_as_of
                else "available"
                if connection_rows
                else "missing"
                if request.subject.kind == "connection" and connection_read.available
                else "unknown"
            )
            evidence_state = (
                "unknown"
                if temporal_is_as_of and request.subject.kind == "source"
                or not run_reads
                else "unknown"
                if any(not read.available for read in run_reads)
                else "degraded"
                if any_sync_truncated
                else "available"
                if run_records
                else "empty"
                if run_reads
                else "missing"
            )
            health_state = "unknown"
            coverage_state = (
                "degraded"
                if temporal_is_as_of and run_reads and all(read.available for read in run_reads)
                else "unknown"
                if temporal_is_as_of or not connection_read.available
                else "degraded"
            )

        section_warnings = sorted(set(warnings))
        sections = [
            ProjectionSection(
                id="summary",
                state=summary_state,
                title="Connection summary",
                content={
                    "subject": {"kind": request.subject.kind, "id": request.subject.id},
                    "connectionCount": 0 if temporal_is_as_of else len(connection_rows),
                    "syncRunCount": len(sync_rows),
                    "connections": connection_rows if live_connection_data_allowed else [],
                    "syncRuns": run_records,
                    "temporalView": temporal.mode,
                    "currentLifecycleOmittedForAsOf": temporal_is_as_of,
                },
                warnings=section_warnings,
            ),
            ProjectionSection(
                id="state",
                state=state_state,
                title="Connection state",
                content={
                    "lifecycleRecords": [
                        {
                            "connectionId": row["connectionId"],
                            "providerIdentity": row["providerIdentity"],
                            "state": row["state"],
                            "recordedAt": row.get("updatedAt"),
                            "authority": _CONNECTION_SOURCE,
                            "externalProviderState": "not_independently_verified",
                        }
                        for row in connection_rows
                    ]
                    if live_connection_data_allowed
                    else [],
                    "latestSyncByConnection": _latest_sync_by_connection(sync_rows),
                    "credentialReadiness": "unknown",
                },
                warnings=section_warnings,
            ),
            ProjectionSection(
                id="evidence",
                state=evidence_state,
                title="Connection evidence",
                content={
                    "connectionRecords": connection_refs if live_connection_data_allowed else [],
                    "syncRuns": [
                        {"record": row, "evidence": evidence}
                        for row, evidence in zip(run_records, run_refs)
                    ],
                    "claimInterpretation": "server_recorded_connector_lifecycle_and_sync_ledger_only",
                },
                warnings=section_warnings,
            ),
            ProjectionSection(
                id="health",
                state=health_state,
                title="Provider health",
                content={
                    "providerHealth": "unknown",
                    "credentialReadiness": "unknown",
                    "freshness": "unknown",
                    "recordedVerificationAt": [
                        {"connectionId": row["connectionId"], "at": row.get("lastVerifiedAt")}
                        for row in connection_rows
                        if row.get("lastVerifiedAt")
                    ]
                    if live_connection_data_allowed
                    else [],
                    "latestSyncLedgerAt": _latest_sync_timestamp(sync_rows),
                    "reason": "provider_health_and_credential_readiness_authorities_not_resolved",
                },
                warnings=section_warnings,
            ),
            ProjectionSection(
                id="coverage",
                state=coverage_state,
                title="Connection coverage",
                content={
                    "connectionRecords": (
                        "unknown" if temporal_is_as_of else connection_state
                    ),
                    "syncRunLedger": (
                        "unknown"
                        if any(not read.available for read in run_reads)
                        else "truncated"
                        if any_sync_truncated
                        else "available"
                        if sync_rows
                        else "empty"
                        if run_reads
                        else "unknown"
                    ),
                    "sourceCoverage": "unknown",
                    "providerHealth": "unknown",
                    "credentialReadiness": "unknown",
                    "reconciledControlPlane": "unavailable",
                    "source360Dependency": dependency_state,
                    "historyCompleteness": (
                        "mutable_connection_state_not_historized"
                        if temporal_is_as_of
                        else "bounded_sync_ledger"
                        if any_sync_truncated
                        else "not_established"
                    ),
                },
                warnings=section_warnings,
            ),
        ]

        if request.includeSections is not None:
            wanted = set(request.includeSections)
            sections = [section for section in sections if section.id in wanted]
        claims = (
            _claims(
                request,
                connection_rows if live_connection_data_allowed else [],
                run_records,
                connection_refs,
                run_refs,
            )
            if request.includeClaims is not False
            else []
        )
        if len(claims) > _MAX_CLAIMS:
            claims = claims[:_MAX_CLAIMS]
            warnings.append("connection_claim_limit_reached")

        result_as_of = (
            temporal.anchor.isoformat()
            if temporal.mode == "as_of" and temporal.anchor is not None
            else generated_at
            if temporal.issue is None
            else None
        )
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=list(context.dependencyState),
            asOf=result_as_of,
            generatedAt=generated_at,
            page=page,
            degradedReasons=sorted(set(warnings)),
            temporalMode=temporal.mode,
            lensIds=request.lensIds,
        )


def register_provider(registry: ProviderRegistry) -> Connection360Provider:
    """Explicit registration helper; importing the module has no side effect."""
    provider = Connection360Provider()
    registry.register(provider, source="services/api/connectors/provider_runtime")
    return provider


def _connection_row(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except TypeError:
            return dump()
    return {}


def _public_connection(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    connection_id = _safe_text(row.get("connection_id"), limit=200)
    provider = _safe_text(row.get("provider_identity"), limit=200)
    tenant_id = _safe_text(row.get("tenant_id"), limit=200)
    if not connection_id or not provider or not tenant_id:
        return None
    state_value = row.get("state")
    state_value = getattr(state_value, "value", state_value)
    state = state_value if isinstance(state_value, str) and state_value in _CONNECTION_STATES else "unknown"
    return {
        "connectionId": connection_id,
        "providerIdentity": provider,
        "state": state,
        "createdAt": _safe_timestamp(row.get("created_at")),
        "updatedAt": _safe_timestamp(row.get("updated_at")),
        "lastVerifiedAt": _safe_timestamp(row.get("last_verified_at")),
    }


def _public_sync_run(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    sync_run_id = _safe_text(row.get("sync_run_id"), limit=200)
    connection_id = _safe_text(row.get("connector_instance_id"), limit=200)
    tenant_id = _safe_text(row.get("tenant_id"), limit=200)
    if not sync_run_id or not connection_id or not tenant_id:
        return None
    status_value = row.get("status")
    status = status_value if isinstance(status_value, str) and status_value in _SYNC_RUN_STATES else "unknown"
    mode_value = row.get("mode")
    mode = mode_value if isinstance(mode_value, str) and mode_value in _SYNC_MODES else "unknown"
    reconciliation = row.get("reconciliation_status")
    if reconciliation not in _RECONCILIATION_STATES:
        reconciliation = "unknown"
    counts = {
        key: value
        for key in (
            "pages_requested",
            "records_received",
            "records_deduplicated",
            "records_rejected",
            "facts_written",
            "campaigns_created",
            "messages_created",
            "profiles_resolved",
            "profiles_unresolved",
            "replies_correlated",
            "suppressions_updated",
            "rate_limit_events",
            "retry_count",
        )
        if isinstance((value := row.get(key)), int) and not isinstance(value, bool) and value >= 0
    }
    error_code = _safe_error_code(row.get("safe_error_code"))
    return {
        "syncRunId": sync_run_id,
        "connectionId": connection_id,
        "provider": _safe_text(row.get("provider"), limit=200),
        "mode": mode,
        "status": status,
        "startedAt": _safe_timestamp(row.get("started_at")),
        "completedAt": _safe_timestamp(row.get("completed_at")),
        "counts": counts,
        "reconciliationStatus": reconciliation,
        "safeErrorCode": error_code,
    }


def _connection_evidence(row: dict[str, Any]) -> EvidenceRef:
    return EvidenceRef(
        id=f"provider_connection:{row['connectionId']}",
        type="entity",
        source=_CONNECTION_SOURCE,
        observedAt=row.get("updatedAt"),
    )


def _sync_run_evidence(row: dict[str, Any]) -> EvidenceRef:
    return EvidenceRef(
        id=f"provider_sync_run:{row['syncRunId']}",
        type="event",
        source=_SYNC_RUN_SOURCE,
        observedAt=row.get("completedAt") or row.get("startedAt"),
    )


def _claims(
    request: ProjectionRequest,
    connections: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    connection_refs: list[EvidenceRef],
    run_refs: list[EvidenceRef],
) -> list[ClaimEnvelope]:
    claims: list[ClaimEnvelope] = []
    refs_by_connection = {ref.id.rsplit(":", 1)[-1]: ref for ref in connection_refs}
    for row in connections:
        evidence = refs_by_connection.get(row["connectionId"])
        if evidence is None:
            continue
        claims.append(
            ClaimEnvelope(
                id=f"connection-lifecycle:{row['connectionId']}",
                kind="server_recorded_connection_lifecycle",
                subject=request.subject,
                evidenceRefs=[evidence],
                claims=[f"Provider connection lifecycle is server-recorded as {row['state']}"],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=[_WORKFLOW_SLOT],
            )
        )
    for row, evidence in zip(runs, run_refs):
        claims.append(
            ClaimEnvelope(
                id=f"connection-sync-run:{row['syncRunId']}",
                kind="server_recorded_sync_run_status",
                subject=request.subject,
                evidenceRefs=[evidence],
                claims=[f"Sync ledger records run status {row['status']} for this connection"],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=[_WORKFLOW_SLOT],
            )
        )
    return claims


def _authority_availability(read: AuthorityRead, rows: list[dict[str, Any]]) -> str:
    if not read.available:
        return "unknown"
    if not rows:
        return "missing" if read.reason and "not_found" in read.reason else "empty"
    if not read.complete:
        return "degraded"
    return "available"


def _filter_runs(
    rows: list[dict[str, Any]], temporal: _TemporalView
) -> tuple[list[dict[str, Any]], list[str]]:
    if temporal.issue is not None:
        return [], []
    warnings: list[str] = []
    selected: list[dict[str, Any]] = []
    for row in rows:
        if temporal.mode == "as_of":
            completed = _parse_aware_timestamp(row.get("completed_at"))
            status = row.get("status")
            if completed is None:
                warnings.append("sync_run_without_completion_time_excluded_from_as_of")
                continue
            if temporal.anchor is None or completed > temporal.anchor or status not in _CLOSED_RUN_STATES:
                continue
            selected.append(row)
            continue
        if temporal.lower is None and temporal.upper is None:
            selected.append(row)
            continue
        started = _parse_aware_timestamp(row.get("started_at"))
        if started is None:
            warnings.append("untimed_sync_run_excluded_from_window")
            continue
        if temporal.lower is not None and started < temporal.lower:
            continue
        if temporal.upper is not None and started > temporal.upper:
            continue
        selected.append(row)
    return sorted(
        selected,
        key=lambda row: (
            _parse_aware_timestamp(row.get("started_at")) or datetime.min.replace(tzinfo=timezone.utc),
            str(row.get("sync_run_id") or ""),
        ),
    ), sorted(set(warnings))


def _dedupe_runs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _safe_text(row.get("sync_run_id"), limit=200)
        if key:
            by_id[key] = row
    return sorted(
        by_id.values(),
        key=lambda row: (
            _parse_aware_timestamp(row.get("started_at")) or datetime.min.replace(tzinfo=timezone.utc),
            str(row.get("sync_run_id") or ""),
        ),
    )


def _page_runs(
    rows: list[dict[str, Any]], request: ProjectionRequest
) -> tuple[list[dict[str, Any]], PageInfo]:
    limit = min(request.page.limit if request.page is not None else 50, 200)
    offset = 0
    cursor = request.page.cursor if request.page is not None else None
    if cursor:
        try:
            offset = max(0, int(cursor))
        except (TypeError, ValueError):
            offset = 0
    selected = rows[offset : offset + limit]
    next_offset = offset + len(selected)
    has_next = next_offset < len(rows)
    return selected, PageInfo(
        nextCursor=str(next_offset) if has_next else None,
        previousCursor=str(max(0, offset - limit)) if offset > 0 else None,
        hasNextPage=has_next,
        hasPreviousPage=offset > 0,
        totalEstimate=len(rows),
    )


def _latest_sync_by_connection(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        connection_id = str(row.get("connector_instance_id") or "")
        public = _public_sync_run(row)
        if not connection_id or public is None:
            continue
        prior = latest.get(connection_id)
        timestamp = _parse_aware_timestamp(row.get("started_at"))
        prior_timestamp = _parse_aware_timestamp(prior.get("started_at")) if prior else None
        if prior is None or (timestamp is not None and (prior_timestamp is None or timestamp > prior_timestamp)):
            latest[connection_id] = {
                "connectionId": connection_id,
                "status": public["status"],
                "completedAt": public["completedAt"],
                "startedAt": public["startedAt"],
            }
    return [latest[key] for key in sorted(latest)]


def _latest_sync_timestamp(rows: list[dict[str, Any]]) -> Optional[str]:
    values = [
        row.get("completedAt") or row.get("startedAt")
        for raw in rows
        if (row := _public_sync_run(raw)) is not None
        and (row.get("completedAt") or row.get("startedAt"))
    ]
    return max(values) if values else None


def _resolve_temporal_view(request: ProjectionRequest) -> _TemporalView:
    mode = request.temporalMode or ("as_of" if request.asOf else "window")
    if mode not in SUPPORTED_TEMPORAL_MODES:
        return _TemporalView(mode, None, None, None, "unsupported_temporal_mode")
    if mode == "as_of":
        anchor_value = request.asOf or (request.timeRange.from_ if request.timeRange else None)
        anchor = _parse_aware_timestamp(anchor_value)
        if anchor is None:
            return _TemporalView(mode, None, None, None, "as_of_anchor_unavailable")
        return _TemporalView(mode, anchor, None, anchor, None)
    if mode == "relative" and request.timeRange is None:
        return _TemporalView(mode, None, None, None, "relative_time_range_not_resolved")
    lower = _parse_aware_timestamp(request.timeRange.from_) if request.timeRange else None
    upper = _parse_aware_timestamp(request.timeRange.to) if request.timeRange else None
    if request.timeRange and (
        (request.timeRange.from_ and lower is None) or (request.timeRange.to and upper is None)
    ):
        return _TemporalView(mode, None, None, None, "time_range_anchor_invalid")
    if lower is not None and upper is not None and lower > upper:
        return _TemporalView(mode, None, None, None, "time_range_order_invalid")
    return _TemporalView(mode, None, lower, upper, None)


def _parse_aware_timestamp(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _safe_timestamp(value: Any) -> Optional[str]:
    parsed = _parse_aware_timestamp(value)
    return parsed.isoformat() if parsed is not None else None


def _safe_text(value: Any, *, limit: int = 256) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > limit or any(ord(char) < 32 or ord(char) == 127 for char in text):
        return None
    return text


def _safe_error_code(value: Any) -> Optional[str]:
    text = _safe_text(value, limit=100)
    if text is None or any(not (char.isalnum() or char in "_.-") for char in text):
        return None
    return text


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "OUTPUT_SECTIONS",
    "SUPPORTED_TEMPORAL_MODES",
    "AuthorityRead",
    "Connection360Provider",
    "Connection360ReadAuthority",
    "RepositoryConnection360ReadAuthority",
    "register_provider",
]
