"""Support360 projection over observed support case and communication facts.

The provider reads only the exact support category from tenant-scoped
``silver_comms_facts``. Entity subjects use the canonical recipient ID;
agent subjects require an Agent360 identity binding plus the matching
server-bound sender identity receipt; episode subjects use event/fact
references carried by an exact tenant-owned EpisodeRecord; source subjects
resolve through exact tenant-owned provider connection rows and match their
connection IDs. Every candidate is rechecked after the repository read.

Communication joins expose observed metadata and provenance only. Canonical
case IDs are minted by the SupportCase authority from tenant-owned verified
provider connections; lifecycle remains an observed source assertion. This
projection never promotes ``support_case_id`` into canonical identity or
derives a journey, assignment, SLA, risk, or outcome. Connection membership has
no historical authority, and source/agent/episode coverage is degraded when a
read cannot establish a complete scoped set.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Protocol
from urllib.parse import quote

from graph.operational_intelligence.models import EvidenceRef
from shared.contracts_models.epistemic import EpistemicStatus
from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    ProjectionContext,
    PageInfo,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
)
from shared.intelligence_projections.errors import ProjectionError
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.provider import IntelligenceProjectionProvider
from shared.intelligence_projections.registry import ProviderRegistry
from journeys.support360.cases import SupportCaseAuthorityRead, SupportCaseRepository

PROJECTION_ID = "support360"
OUTPUT_SECTIONS: tuple[str, ...] = (
    "summary",
    "state",
    "timeline",
    "evidence",
    "interactions",
    "outcomes",
)

_FACT_SOURCE = "services/api/journeys/comms/silver_comms_facts"
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_REASON_UNSUPPORTED_SUBJECT = "support_subject_join_unavailable"
_REASON_SOURCE_UNAVAILABLE = "support_communication_source_unavailable"
_REASON_READ_TRUNCATED = "support_communication_read_truncated"
_REASON_PARTIAL_ENTITY_JOIN = "support_entity_join_is_recipient_only_sender_and_profile_unbound"
_REASON_AGENT_JOIN_SCOPE = "support_agent_join_requires_bound_sender_identity_evidence"
_REASON_EPISODE_JOIN_SCOPE = "support_episode_join_uses_only_episode_event_evidence_refs"
_REASON_SOURCE_JOIN_SCOPE = "support_source_join_uses_current_provider_connection_membership"
_REASON_AGENT_IDENTITY_UNAVAILABLE = "support_agent_identity_authority_unavailable"
_REASON_EPISODE_AUTHORITY_UNAVAILABLE = "support_episode_authority_unavailable"
_REASON_SOURCE_AUTHORITY_UNAVAILABLE = "support_source_connection_authority_unavailable"
_REASON_EPISODE_LINK_MISSING = "support_episode_communication_event_link_unavailable"
_REASON_SOURCE_LINK_MISSING = "support_source_connection_binding_unavailable"
_REASON_SOURCE_CONNECTION_SCOPE_MISMATCH = "support_source_connection_tenant_scope_mismatch"
_REASON_CASE_AUTHORITY_MISSING = "canonical_support_case_authority_unavailable"
_REASON_TICKET_CASE_JOIN_MISSING = "canonical_support_ticket_case_join_unavailable"
_REASON_CONVERSATION_AUTHORITY_MISSING = "canonical_support_conversation_authority_unavailable"
_REASON_CASE_NOT_FOUND = "support_case_not_found_for_tenant"
_REASON_CASE_AUTHORITY_UNAVAILABLE = "support_case_authority_unavailable"
_REASON_CASE_RETENTION_EXPIRED = "support_case_retention_expired"
_REASON_CASE_EVIDENCE_UNAVAILABLE = "support_case_lifecycle_evidence_unavailable"
_REASON_CASE_HISTORY_PARTIAL = "support_case_source_history_coverage_unverified"
_REASON_CASE_COMMUNICATION_JOIN_MISSING = "support_case_conversation_join_unavailable"
_REASON_JOURNEY_JOIN_MISSING = "canonical_support_case_journey_join_unavailable"
_REASON_OUTCOME_JOIN_MISSING = "canonical_support_outcome_join_unavailable"
_REASON_CALLBACK_AUTHORITY_MISSING = "canonical_support_callback_authority_unavailable"
_REASON_PARTICIPANT_AUTHORITY_MISSING = "canonical_support_case_participants_unavailable"
_REASON_SLA_AUTHORITY_MISSING = "canonical_support_sla_authority_unavailable"
_REASON_AGENT_ASSIGNMENT_MISSING = "canonical_support_case_agent_assignment_unavailable"
_REASON_RISK_COMPOSITION_MISSING = "support_risk_projection_composition_unavailable"
_REASON_RESOLUTION_AUTHORITY_MISSING = "canonical_support_resolution_authority_unavailable"
_REASON_SUPPORT_BUSINESS_OUTCOME_MISSING = "support_business_outcome_authority_unavailable"
_REASON_CONTENT_PERMISSION_UNVERIFIED = "support_communication_content_permission_unverified"
_REQUIRED_SUPPORT_SLOT_IDS: tuple[str, ...] = (
    "case_summary",
    "conversation_history",
    "callbacks",
    "participants",
    "sla",
    "journey_links",
    "agents",
    "risk",
    "resolution",
    "evidence_trace",
)
_SAFE_SUPPORT_READ_REASONS = frozenset(
    {
        _REASON_UNSUPPORTED_SUBJECT,
        _REASON_SOURCE_UNAVAILABLE,
        _REASON_AGENT_IDENTITY_UNAVAILABLE,
        _REASON_EPISODE_AUTHORITY_UNAVAILABLE,
        _REASON_EPISODE_LINK_MISSING,
        _REASON_SOURCE_AUTHORITY_UNAVAILABLE,
        _REASON_SOURCE_LINK_MISSING,
        _REASON_SOURCE_CONNECTION_SCOPE_MISMATCH,
    }
)
_CANONICAL_SUBJECT_AUTHORITY_REASONS = {
    "support_case": _REASON_CASE_AUTHORITY_MISSING,
    "callback": _REASON_CALLBACK_AUTHORITY_MISSING,
    "conversation": _REASON_CONVERSATION_AUTHORITY_MISSING,
    "ticket": _REASON_TICKET_CASE_JOIN_MISSING,
}


def _safe_read_reason(reason: Optional[str]) -> str:
    """Keep source-provided diagnostics from leaking into projection content."""
    return reason if reason in _SAFE_SUPPORT_READ_REASONS else _REASON_UNSUPPORTED_SUBJECT


@dataclass(frozen=True)
class SupportFactsRead:
    """One exact scoped read with explicit availability and completeness."""

    rows: list[dict[str, Any]]
    available: bool
    truncated: bool = False
    complete: bool = False
    reason: Optional[str] = None
    next_cursor: Optional[str] = None
    scope_known: bool = True
    subject_join: Optional[str] = None
    join_reference_ids: tuple[str, ...] = ()
    join_evidence_refs: tuple[EvidenceRef, ...] = ()
    canonical_authority_refs: tuple[str, ...] = ("communication_facts", "evidence")


class Support360Source(Protocol):
    async def support_facts_for_entity(
        self,
        tenant_id: str,
        entity_id: str,
        *,
        limit: int,
        after: Optional[str] = None,
        before: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> SupportFactsRead:
        """Read exact tenant/entity support communication facts."""

    async def support_facts_for_agent(
        self,
        tenant_id: str,
        canonical_agent_entity_id: str,
        *,
        sender_identity_binding_ids: list[str],
        limit: int,
        after: Optional[str] = None,
        before: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> SupportFactsRead:
        """Read support facts for an Agent360-resolved, bound sender."""

    async def support_facts_for_episode(
        self,
        tenant_id: str,
        episode_id: str,
        *,
        limit: int,
        after: Optional[str] = None,
        before: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> SupportFactsRead:
        """Read support facts referenced by an exact canonical episode record."""

    async def support_facts_for_source(
        self,
        tenant_id: str,
        source_id: str,
        *,
        limit: int,
        after: Optional[str] = None,
        before: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> SupportFactsRead:
        """Read support facts carried by current tenant-owned source connections."""


class SupportAgentIdentityReader(Protocol):
    async def resolve(self, tenant_id: str, source_agent_ref: str) -> Any:
        """Resolve a source agent ID through the canonical Agent360 authority."""


class RepositorySupport360Source:
    """Adapter over the canonical communication fact repository."""

    def __init__(
        self,
        *,
        facts: Any = None,
        episodes: Any = None,
        connections: Any = None,
    ) -> None:
        self._facts = facts
        self._episodes = episodes
        self._connections = connections

    def _facts_repository(self) -> Any:
        if self._facts is None:
            from journeys.comms.repository import CommsFactsRepository

            self._facts = CommsFactsRepository()
        return self._facts

    def _episode_store(self) -> Any:
        if self._episodes is None:
            from shared.backend_interpretation.stores import EpisodeStore

            self._episodes = EpisodeStore()
        return self._episodes

    def _connection_repository(self) -> Any:
        if self._connections is None:
            from connectors.provider_runtime.connection import ProviderConnectionRepository

            self._connections = ProviderConnectionRepository()
        return self._connections

    async def support_facts_for_entity(
        self,
        tenant_id: str,
        entity_id: str,
        *,
        limit: int,
        after: Optional[str] = None,
        before: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> SupportFactsRead:
        try:
            rows, next_cursor = await self._facts_repository().list_for_entity(
                tenant_id,
                entity_id,
                category="support",
                after=after,
                before=before,
                limit=limit,
                cursor=cursor,
            )
        except Exception:  # noqa: BLE001 - source outage remains typed unknown
            return SupportFactsRead(
                rows=[],
                available=False,
                reason=_REASON_SOURCE_UNAVAILABLE,
            )
        return SupportFactsRead(
            rows=[row for row in rows if isinstance(row, dict)],
            available=True,
            truncated=next_cursor is not None,
            complete=next_cursor is None,
            next_cursor=next_cursor,
            scope_known=True,
            subject_join="recipient_entity_id_exact_match",
            canonical_authority_refs=("communication_facts", "evidence"),
        )

    async def support_facts_for_agent(
        self,
        tenant_id: str,
        canonical_agent_entity_id: str,
        *,
        sender_identity_binding_ids: list[str],
        limit: int,
        after: Optional[str] = None,
        before: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> SupportFactsRead:
        if not sender_identity_binding_ids:
            return SupportFactsRead(
                rows=[],
                available=True,
                scope_known=False,
                reason=_REASON_AGENT_IDENTITY_UNAVAILABLE,
                subject_join="sender_entity_id_and_identity_binding_id_exact_match",
                canonical_authority_refs=("communication_facts", "identity", "evidence"),
            )
        try:
            rows, next_cursor = await self._facts_repository().list_for_sender_entity(
                tenant_id,
                canonical_agent_entity_id,
                sender_identity_binding_ids=sender_identity_binding_ids,
                category="support",
                after=after,
                before=before,
                limit=limit,
                cursor=cursor,
            )
        except Exception:  # noqa: BLE001 - source outage remains typed unknown
            return SupportFactsRead(
                rows=[],
                available=False,
                reason=_REASON_SOURCE_UNAVAILABLE,
                subject_join="sender_entity_id_and_identity_binding_id_exact_match",
                canonical_authority_refs=("communication_facts", "identity", "evidence"),
            )
        return SupportFactsRead(
            rows=[row for row in rows if isinstance(row, dict)],
            available=True,
            truncated=next_cursor is not None,
            complete=next_cursor is None,
            next_cursor=next_cursor,
            subject_join="sender_entity_id_and_identity_binding_id_exact_match",
            join_reference_ids=(canonical_agent_entity_id, *sender_identity_binding_ids),
            canonical_authority_refs=("communication_facts", "identity", "evidence"),
        )

    async def support_facts_for_episode(
        self,
        tenant_id: str,
        episode_id: str,
        *,
        limit: int,
        after: Optional[str] = None,
        before: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> SupportFactsRead:
        try:
            episode = await self._episode_store().get(tenant_id, episode_id)
        except Exception:  # noqa: BLE001 - source outage remains typed unknown
            return SupportFactsRead(
                rows=[],
                available=False,
                reason=_REASON_EPISODE_AUTHORITY_UNAVAILABLE,
                subject_join="episode_record_event_evidence_exact_match",
                canonical_authority_refs=("communication_facts", "episode_facts", "evidence"),
            )
        if (
            episode is None
            or getattr(episode, "tenant_id", None) != tenant_id
            or getattr(episode, "episode_id", None) != episode_id
        ):
            return SupportFactsRead(
                rows=[],
                available=True,
                scope_known=False,
                reason=_REASON_EPISODE_AUTHORITY_UNAVAILABLE,
                subject_join="episode_record_event_evidence_exact_match",
                canonical_authority_refs=("communication_facts", "episode_facts", "evidence"),
            )

        source_event_ids: set[str] = set()
        if (
            source_event_id := _safe_reference(getattr(episode, "source_event_id", None))
        ) is not None:
            source_event_ids.add(source_event_id)
        fact_ids: set[str] = set()
        raw_evidence = getattr(episode, "evidence_refs", ())
        if isinstance(raw_evidence, (list, tuple)):
            for reference in raw_evidence:
                source = _safe_reference(getattr(reference, "source", None))
                uri = _safe_reference(getattr(reference, "uri", None))
                evidence_id = _safe_reference(getattr(reference, "id", None))
                if evidence_id and (
                    source == _FACT_SOURCE
                    or (uri and uri.startswith("store://silver_comms_facts/"))
                ):
                    fact_ids.add(evidence_id)
        if not source_event_ids and not fact_ids:
            episode_ref = _episode_evidence(episode)
            return SupportFactsRead(
                rows=[],
                available=True,
                scope_known=False,
                reason=_REASON_EPISODE_LINK_MISSING,
                subject_join="episode_record_event_evidence_exact_match",
                join_evidence_refs=(episode_ref,) if episode_ref else (),
                canonical_authority_refs=("communication_facts", "episode_facts", "evidence"),
            )

        try:
            rows, next_cursor = await self._facts_repository().list_for_event_references(
                tenant_id,
                source_event_ids=sorted(source_event_ids),
                fact_ids=sorted(fact_ids),
                category="support",
                after=after,
                before=before,
                limit=limit,
                cursor=cursor,
            )
        except Exception:  # noqa: BLE001 - source outage remains typed unknown
            return SupportFactsRead(
                rows=[],
                available=False,
                reason=_REASON_SOURCE_UNAVAILABLE,
                subject_join="episode_record_event_evidence_exact_match",
                canonical_authority_refs=("communication_facts", "episode_facts", "evidence"),
            )
        episode_ref = _episode_evidence(episode)
        source_event_ref = (
            EvidenceRef(
                id=source_event_id,
                type="event",
                source="episode_records",
                observedAt=_safe_reference(
                    _text(getattr(episode, "occurred_from", None))
                    or _text(getattr(episode, "created_at", None))
                ),
            )
            if source_event_id is not None
            else None
        )
        return SupportFactsRead(
            rows=[row for row in rows if isinstance(row, dict)],
            available=True,
            truncated=next_cursor is not None,
            complete=next_cursor is None,
            next_cursor=next_cursor,
            subject_join="episode_record_event_evidence_exact_match",
            join_reference_ids=tuple(sorted(source_event_ids | fact_ids)),
            join_evidence_refs=((episode_ref,) if episode_ref else ())
            + ((source_event_ref,) if source_event_ref else ())
            + tuple(reference for reference in raw_evidence if isinstance(reference, EvidenceRef)),
            canonical_authority_refs=("communication_facts", "episode_facts", "evidence"),
        )

    async def support_facts_for_source(
        self,
        tenant_id: str,
        source_id: str,
        *,
        limit: int,
        after: Optional[str] = None,
        before: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> SupportFactsRead:
        source_limit = min(max(limit, 1), _MAX_LIMIT)
        try:
            rows = await self._connection_repository().find_many(
                filters={"tenant_id": tenant_id, "provider_identity": source_id},
                sort_by="created_at",
                sort_order="desc",
                limit=source_limit + 1,
            )
        except Exception:  # noqa: BLE001 - source outage remains typed unknown
            return SupportFactsRead(
                rows=[],
                available=False,
                reason=_REASON_SOURCE_AUTHORITY_UNAVAILABLE,
                subject_join="provider_identity_to_connection_to_source_connector_id_exact_match",
                canonical_authority_refs=(
                    "communication_facts",
                    "provider_connections",
                    "evidence",
                ),
            )

        complete = len(rows) <= source_limit
        scoped_connections = [
            row
            for row in rows
            if isinstance(row, dict)
            and row.get("tenant_id") == tenant_id
            and row.get("provider_identity") == source_id
            and isinstance(row.get("connection_id"), str)
            and row.get("connection_id")
        ]
        if len(scoped_connections) != len(rows):
            return SupportFactsRead(
                rows=[],
                available=True,
                scope_known=False,
                reason=_REASON_SOURCE_CONNECTION_SCOPE_MISMATCH,
                subject_join="provider_identity_to_connection_to_source_connector_id_exact_match",
                join_evidence_refs=tuple(_connection_evidence(row) for row in scoped_connections),
                canonical_authority_refs=(
                    "communication_facts",
                    "provider_connections",
                    "evidence",
                ),
            )
        connection_ids = sorted({str(row["connection_id"]) for row in scoped_connections})
        connection_refs = tuple(_connection_evidence(row) for row in scoped_connections)
        if not connection_ids:
            return SupportFactsRead(
                rows=[],
                available=True,
                scope_known=False,
                truncated=not complete,
                reason=_REASON_SOURCE_LINK_MISSING,
                subject_join="provider_identity_to_connection_to_source_connector_id_exact_match",
                canonical_authority_refs=(
                    "communication_facts",
                    "provider_connections",
                    "evidence",
                ),
            )
        try:
            facts, next_cursor = await self._facts_repository().list_for_source_connectors(
                tenant_id,
                connection_ids,
                category="support",
                after=after,
                before=before,
                limit=limit,
                cursor=cursor,
            )
        except Exception:  # noqa: BLE001 - source outage remains typed unknown
            return SupportFactsRead(
                rows=[],
                available=False,
                truncated=not complete,
                reason=_REASON_SOURCE_UNAVAILABLE,
                subject_join="provider_identity_to_connection_to_source_connector_id_exact_match",
                join_reference_ids=tuple(connection_ids),
                join_evidence_refs=connection_refs,
                canonical_authority_refs=(
                    "communication_facts",
                    "provider_connections",
                    "evidence",
                ),
            )
        return SupportFactsRead(
            rows=[row for row in facts if isinstance(row, dict)],
            available=True,
            truncated=(next_cursor is not None or not complete),
            # Current connection membership is mutable and has no historical
            # coverage authority. This is complete only as a current bounded
            # query, never a complete source-history claim.
            complete=False,
            next_cursor=next_cursor,
            subject_join="provider_identity_to_connection_to_source_connector_id_exact_match",
            join_reference_ids=tuple(connection_ids),
            join_evidence_refs=connection_refs,
            canonical_authority_refs=("communication_facts", "provider_connections", "evidence"),
        )


class RepositorySupportAgentIdentityReader:
    """Reuse Agent360's tenant-owned deployment identity binding resolver."""

    async def resolve(self, tenant_id: str, source_agent_ref: str) -> Any:
        try:
            from journeys.communication360.provider import RepositoryAgentIdentityReader

            return await RepositoryAgentIdentityReader().resolve(tenant_id, source_agent_ref)
        except Exception:  # noqa: BLE001 - an identity outage remains unknown
            return None


class Support360Provider(IntelligenceProjectionProvider):
    """Read-only Support360 provider with explicit unresolved case/journey state."""

    projection_id = PROJECTION_ID
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    def __init__(
        self,
        source: Optional[Support360Source] = None,
        *,
        agent_identity_reader: Optional[SupportAgentIdentityReader] = None,
        case_repository: Optional[SupportCaseRepository] = None,
    ) -> None:
        self._source = source if source is not None else RepositorySupport360Source()
        self._agent_identity = (
            agent_identity_reader
            if agent_identity_reader is not None
            else RepositorySupportAgentIdentityReader()
        )
        self._case_repository = (
            case_repository if case_repository is not None else SupportCaseRepository()
        )

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        if request.projectionId != self.projection_id:
            raise ProjectionError(
                "Support360 provider received a different projection id",
                projection_id=request.projectionId,
            )

        if request.subject.kind not in {"entity", "agent", "episode", "source", "support_case"}:
            # These are valid SSOT subject identifiers, but the repository
            # currently has no canonical case/callback/conversation/ticket
            # authority to resolve them. Preserve them as typed unknowns
            # instead of labeling a supported contract subject as invalid.
            subject_authority_reason = _CANONICAL_SUBJECT_AUTHORITY_REASONS.get(
                request.subject.kind
            )
            return self._unknown_result(
                request,
                context,
                subject_authority_reason or _REASON_UNSUPPORTED_SUBJECT,
            )

        if context.tenantId != request.tenantId:
            return self._unknown_result(request, context, "support_tenant_scope_mismatch")

        if not request.subject.id.strip():
            return self._unknown_result(request, context, "support_subject_id_empty")

        if request.asOf is not None or request.temporalMode == "as_of":
            return self._unknown_result(
                request,
                context,
                "support_as_of_read_unavailable",
            )
        if request.temporalMode not in {None, "live", "window"}:
            return self._unknown_result(
                request,
                context,
                "support_temporal_mode_unavailable",
            )
        if request.temporalMode == "window" and request.timeRange is None:
            return self._unknown_result(
                request,
                context,
                "support_window_bounds_required",
            )

        window, window_error = _window_bounds(request.timeRange)
        if window_error is not None:
            return self._unknown_result(request, context, window_error)
        after, before = window
        if request.temporalMode == "window" and after is None and before is None:
            return self._unknown_result(
                request,
                context,
                "support_window_bounds_required",
            )

        limit = min(
            max(request.page.limit if request.page is not None else _DEFAULT_LIMIT, 1),
            _MAX_LIMIT,
        )
        if request.subject.kind == "support_case":
            return await self._project_case(request, context, limit=limit)
        join_evidence_refs: tuple[EvidenceRef, ...] = ()
        canonical_subject_id = request.subject.id
        binding_ids: list[str] = []
        if request.subject.kind == "agent":
            try:
                identity = await self._agent_identity.resolve(request.tenantId, request.subject.id)
            except Exception:  # noqa: BLE001 - fail closed on identity resolution
                identity = None
            if (
                identity is None
                or getattr(identity, "state", None) != "resolved"
                or not isinstance(getattr(identity, "canonical_agent_entity_id", None), str)
                or not getattr(identity, "canonical_agent_entity_id", "").strip()
                or not getattr(identity, "evidence", ())
            ):
                return self._unknown_result(
                    request,
                    context,
                    _REASON_AGENT_IDENTITY_UNAVAILABLE,
                )
            canonical_subject_id = identity.canonical_agent_entity_id
            join_evidence_refs = tuple(
                reference for reference in identity.evidence if isinstance(reference, EvidenceRef)
            )
            binding_ids = sorted({reference.id for reference in join_evidence_refs if reference.id})
            if not binding_ids:
                return self._unknown_result(
                    request,
                    context,
                    _REASON_AGENT_IDENTITY_UNAVAILABLE,
                )
        try:
            read_kwargs = {
                "limit": limit,
                "after": after,
                "before": before,
                "cursor": request.page.cursor if request.page is not None else None,
            }
            if request.subject.kind == "entity":
                read = await self._source.support_facts_for_entity(
                    request.tenantId,
                    request.subject.id,
                    **read_kwargs,
                )
            elif request.subject.kind == "agent":
                read = await self._source.support_facts_for_agent(
                    request.tenantId,
                    canonical_subject_id,
                    sender_identity_binding_ids=binding_ids,
                    **read_kwargs,
                )
            elif request.subject.kind == "episode":
                read = await self._source.support_facts_for_episode(
                    request.tenantId,
                    request.subject.id,
                    **read_kwargs,
                )
            else:
                read = await self._source.support_facts_for_source(
                    request.tenantId,
                    request.subject.id,
                    **read_kwargs,
                )
        except Exception:  # noqa: BLE001 - injected source is a fail-isolated seam
            read = SupportFactsRead(
                rows=[],
                available=False,
                reason=_REASON_SOURCE_UNAVAILABLE,
            )

        source_rows = read.rows if read.available and isinstance(read.rows, list) else []
        if request.subject.kind == "entity":
            subject_matches = lambda row: _entity_row_matches(row, request.subject.id)
        elif request.subject.kind == "agent":
            subject_matches = lambda row: _agent_row_matches(
                row,
                canonical_subject_id,
                set(binding_ids),
            )
        elif request.subject.kind == "episode":
            subject_matches = lambda row: _episode_row_matches(row, set(read.join_reference_ids))
        else:
            subject_matches = lambda row: _source_row_matches(row, set(read.join_reference_ids))
        tenant_mismatch = any(
            isinstance(row, dict) and row.get("tenant_id") != request.tenantId
            for row in source_rows
        )
        rows = [
            row
            for row in source_rows
            if isinstance(row, dict)
            if row.get("tenant_id") == request.tenantId
            and _text(row.get("message_category")) == "support"
            and subject_matches(row)
            and _row_in_window(row, after=after, before=before)
        ]
        rows.sort(key=lambda row: str(row.get("occurred_at") or ""))

        read_reasons: list[str] = []
        if not read.available:
            read_reasons.append(_REASON_SOURCE_UNAVAILABLE)
        if not read.scope_known:
            read_reasons.append(_safe_read_reason(read.reason))
        if tenant_mismatch:
            read_reasons.append("support_authority_tenant_scope_mismatch")
        if read.truncated:
            read_reasons.append(_REASON_READ_TRUNCATED)
        if not read.complete and read.available and read.scope_known:
            read_reasons.append("support_subject_read_scope_incomplete")
        if request.subject.kind == "entity":
            # The canonical repository's entity lookup has candidate
            # profile/user joins; this provider accepts only the recipient.
            read_reasons.append(_REASON_PARTIAL_ENTITY_JOIN)
        elif request.subject.kind == "agent":
            read_reasons.append(_REASON_AGENT_JOIN_SCOPE)
        elif request.subject.kind == "episode":
            read_reasons.append(_REASON_EPISODE_JOIN_SCOPE)
        else:
            read_reasons.append(_REASON_SOURCE_JOIN_SCOPE)

        evidence = [_row_evidence(row) for row in rows]
        communication_evidence_refs = [ref for ref in evidence if ref is not None]
        subject_evidence_refs = list(join_evidence_refs) + list(read.join_evidence_refs)
        evidence_refs = _dedupe_evidence_refs(subject_evidence_refs + communication_evidence_refs)
        events = [
            _timeline_entry(row, ref) for row, ref in zip(rows, evidence, strict=False) if ref
        ]
        support_case_refs = _source_reported_case_refs(rows, evidence_refs)
        read_state = (
            "unknown"
            if not read.available or not read.scope_known
            else "degraded"
            if read.truncated or rows or read_reasons
            else "empty"
        )
        if not read.available or not read.scope_known:
            read_state = "unknown"
        state_content = {
            "supportCommunications": {
                "state": read_state,
                "subjectJoin": read.subject_join
                or (
                    "recipient_entity_id_exact_match"
                    if request.subject.kind == "entity"
                    else "unresolved"
                ),
                "joinState": "resolved" if read.scope_known and read.available else "unknown",
                "joinReferenceIds": list(read.join_reference_ids),
                "joinEvidenceRefs": subject_evidence_refs,
                "observedCount": len(rows) if read.available and read.scope_known else None,
                "readCompleteness": (
                    "complete"
                    if read.complete and read.scope_known and read.available
                    else "partial"
                    if read.scope_known and read.available
                    else "unknown"
                ),
                "reasonCodes": sorted(set(read_reasons)),
            },
            "supportCases": {
                "state": "unknown",
                "reasonCode": _REASON_CASE_AUTHORITY_MISSING,
                "sourceReportedReferenceCount": (
                    len(support_case_refs) if read.available and read.scope_known else None
                ),
                "sourceReportedReferencesAreCanonical": False,
            },
            "journeyLinkage": {
                "state": "unknown",
                "reasonCode": _REASON_JOURNEY_JOIN_MISSING,
            },
            "measuredOutcomes": {
                "state": "unknown",
                "reasonCode": _REASON_OUTCOME_JOIN_MISSING,
            },
        }
        newest_observed_at = _newest_timestamp(rows)
        summary = {
            "scope": {
                "subjectKind": request.subject.kind,
                "subjectId": request.subject.id,
                "canonicalSubjectId": (
                    canonical_subject_id if request.subject.kind == "agent" else None
                ),
                "tenantScoped": True,
            },
            "observedSupportCommunicationCount": (
                len(rows) if read.available and read.scope_known else None
            ),
            "sourceReportedCaseReferenceCount": (
                len(support_case_refs) if read.available and read.scope_known else None
            ),
            "supportCaseAuthorityState": "unknown",
            "journeyLinkageState": "unknown",
            "freshness": {
                "state": "unknown",
                "newestObservedAt": newest_observed_at,
                "reasonCode": "support_source_freshness_sla_unavailable",
            },
            "reasonCodes": sorted(set(read_reasons)),
        }
        timeline_content = {
            "order": "occurred_at_ascending",
            "causalRelationsDeclared": False,
            "entryCount": len(events),
            "entries": events,
        }
        evidence_content = {
            "count": len(evidence_refs),
            "evidenceRefs": evidence_refs,
            "subjectJoinEvidenceRefs": subject_evidence_refs,
            "communicationFactEvidenceRefs": communication_evidence_refs,
        }
        interaction_content = {
            "count": len(events),
            "factIds": [event["factId"] for event in events],
            "categoryFilter": "support",
        }
        section_state = (
            "unknown"
            if not read.available or not read.scope_known
            else "degraded"
            if rows or read.truncated or read_reasons or not read.complete
            else "empty"
        )
        state_content["requiredSlots"] = _required_support_slots(
            section_state=section_state,
            read=read,
            support_case_refs=support_case_refs,
            timeline_content=timeline_content,
            communication_evidence_refs=communication_evidence_refs,
            evidence_refs=evidence_refs,
        )
        claims = [
            ClaimEnvelope(
                id=f"support360.communication.{reference.id}",
                kind="support_communication_metadata",
                subject=request.subject,
                evidenceRefs=_dedupe_evidence_refs(subject_evidence_refs + [reference]),
                claims=[
                    "A support communication metadata record is observed for the exact tenant-scoped subject."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["conversation_history", "evidence_trace"],
            )
            for reference in communication_evidence_refs
        ]
        if not read.available or not read.scope_known:
            section_content = [None, state_content, None, None, None, None]
        else:
            section_content = [
                summary,
                state_content,
                timeline_content,
                evidence_content,
                interaction_content,
                None,
            ]
        states = [section_state, "degraded", section_state, section_state, section_state, "unknown"]
        sections = [
            ProjectionSection(
                id=section_id,
                state=state,
                content=content,
                warnings=sorted(set(read_reasons)) or None,
                canonicalAuthorityRefs=list(read.canonical_authority_refs),
            )
            for section_id, state, content in zip(
                OUTPUT_SECTIONS, states, section_content, strict=True
            )
        ]
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=list(context.dependencyState),
            generatedAt=datetime.now(timezone.utc).isoformat(),
            degradedReasons=sorted(set(read_reasons)) if read_reasons else [],
            page=PageInfo(
                nextCursor=read.next_cursor,
                hasNextPage=read.truncated or read.next_cursor is not None,
            ),
        )

    async def _project_case(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
        *,
        limit: int,
    ) -> ProjectionResult:
        """Read exact tenant/canonical case state without guessing related slots."""
        try:
            read = await self._case_repository.get_case(
                request.tenantId,
                request.subject.id,
                limit=limit,
            )
        except Exception:  # noqa: BLE001 - authority failure is a typed unknown
            return self._unknown_result(request, context, _REASON_CASE_AUTHORITY_UNAVAILABLE)
        if not isinstance(read, SupportCaseAuthorityRead) or not read.available:
            return self._unknown_result(request, context, _REASON_CASE_AUTHORITY_UNAVAILABLE)
        if read.expired:
            return self._unknown_result(request, context, _REASON_CASE_RETENTION_EXPIRED)
        record = read.record
        if not isinstance(record, dict):
            return self._unknown_result(request, context, _REASON_CASE_NOT_FOUND)
        if record.get("tenant_id") != request.tenantId or record.get("case_id") != request.subject.id:
            return self._unknown_result(request, context, "support_case_tenant_scope_mismatch")

        events = [event for event in read.events if isinstance(event, dict)]
        evidence_refs: list[EvidenceRef] = []
        timeline_entries: list[dict[str, Any]] = []
        case_record_for_evidence = {
            "source_connection_id": record.get("source_connection_id"),
            "source_provider_identity": record.get("source_provider_identity"),
        }
        event_evidence_incomplete = False
        for event in events:
            event_evidence_refs = _case_event_evidence_refs(
                case_record_for_evidence,
                event,
            )
            if not event_evidence_refs:
                event_evidence_incomplete = True
            evidence_refs.extend(event_evidence_refs)
            timeline_entries.append(
                {
                    "eventType": _safe_reference(_text(event.get("event_type"))),
                    "occurredAt": _safe_reference(_text(event.get("source_occurred_at"))),
                    "receivedAt": _safe_reference(_text(event.get("received_at"))),
                    "lifecycleApplied": event.get("lifecycle_applied") is True,
                    "evidenceRefs": event_evidence_refs,
                }
            )
        evidence_refs = _dedupe_evidence_refs(evidence_refs)
        if not evidence_refs or not timeline_entries:
            return self._unknown_result(request, context, _REASON_CASE_EVIDENCE_UNAVAILABLE)

        partial_reasons = [_REASON_CASE_HISTORY_PARTIAL]
        if event_evidence_incomplete:
            partial_reasons.append("support_case_event_evidence_unverifiable")
        if not read.complete:
            partial_reasons.append("support_case_event_history_truncated")
        lifecycle_state = _safe_reference(_text(record.get("lifecycle_state")))
        lifecycle_observed_at = _safe_reference(_text(record.get("lifecycle_observed_at")))
        newest_received_at = max(
            (
                _safe_reference(_text(event.get("received_at"))) or ""
                for event in events
            ),
            default="",
        ) or None
        case_summary = {
            "canonicalCaseId": request.subject.id,
            "lifecycle": {
                "state": lifecycle_state,
                "claimState": "observed",
                "sourceOccurredAt": lifecycle_observed_at,
                "lastSourceEventId": _safe_reference(_text(record.get("last_source_event_id"))),
            },
            "sourceProvider": _safe_reference(_text(record.get("source_provider_identity"))),
            "sourceConnectionId": _safe_reference(_text(record.get("source_connection_id"))),
            "sourceEventCount": len(events),
            "persistedHistoryComplete": read.complete,
            "freshness": {
                "state": "unknown",
                "newestObservedAt": newest_received_at,
                "reasonCode": "support_case_freshness_sla_unavailable",
            },
            "reasonCodes": partial_reasons,
        }
        slots = _unknown_support_slots(_REASON_CASE_COMMUNICATION_JOIN_MISSING)
        slots["case_summary"] = {
            "state": "degraded",
            "reasonCodes": partial_reasons,
            "canonicalCaseId": request.subject.id,
            "lifecycleState": lifecycle_state,
            "claimState": "observed",
            "sourceOccurredAt": lifecycle_observed_at,
            "evidenceRefs": evidence_refs,
        }
        slots["evidence_trace"] = {
            "state": "degraded",
            "reasonCodes": partial_reasons,
            "count": len(evidence_refs),
            "evidenceRefs": evidence_refs,
        }
        resolution_slot = _case_resolution_slot(record, events)
        if resolution_slot is not None:
            slots["resolution"] = resolution_slot
        state_content = {
            "supportCommunications": {
                "state": "unknown",
                "reasonCode": _REASON_CASE_COMMUNICATION_JOIN_MISSING,
            },
            "supportCases": {
                "state": "observed",
                "canonicalCaseId": request.subject.id,
                "lifecycleState": lifecycle_state,
                "claimState": "observed",
                "sourceOccurredAt": lifecycle_observed_at,
                "sourceEventCount": len(events),
                "sourceHistoryComplete": read.complete,
            },
            "journeyLinkage": {
                "state": "unknown",
                "reasonCode": _REASON_JOURNEY_JOIN_MISSING,
            },
            "measuredOutcomes": {
                "state": "unknown",
                "reasonCode": _REASON_OUTCOME_JOIN_MISSING,
            },
            "requiredSlots": slots,
        }
        timeline_content = {
            "order": "source_occurred_at_descending",
            "causalRelationsDeclared": False,
            "entryCount": len(timeline_entries),
            "entries": timeline_entries,
            "coverage": "persisted_case_events_only",
        }
        evidence_content = {
            "count": len(evidence_refs),
            "evidenceRefs": evidence_refs,
            "caseLifecycleEvidenceRefs": evidence_refs,
        }
        claims = [
            ClaimEnvelope(
                id=f"support360.case.{request.subject.id}.{record['last_source_event_id']}",
                kind="support_case_lifecycle_observation",
                subject=request.subject,
                evidenceRefs=evidence_refs,
                claims=[
                    "The tenant-owned provider connection reported this canonical support case lifecycle state."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=(
                    ["case_summary", "resolution", "evidence_trace"]
                    if resolution_slot is not None
                    else ["case_summary", "evidence_trace"]
                ),
            )
        ]
        sections = [
            ProjectionSection(
                id="summary",
                state="degraded",
                content=case_summary,
                warnings=partial_reasons,
                canonicalAuthorityRefs=["support_cases", "support_case_events", "provider_connections", "evidence"],
            ),
            ProjectionSection(
                id="state",
                state="degraded",
                content=state_content,
                warnings=partial_reasons,
                canonicalAuthorityRefs=["support_cases", "support_case_events", "provider_connections", "evidence"],
            ),
            ProjectionSection(
                id="timeline",
                state="degraded",
                content=timeline_content,
                warnings=partial_reasons,
                canonicalAuthorityRefs=["support_case_events", "evidence"],
            ),
            ProjectionSection(
                id="evidence",
                state="degraded",
                content=evidence_content,
                warnings=partial_reasons,
                canonicalAuthorityRefs=["support_case_events", "provider_connections", "evidence"],
            ),
            ProjectionSection(
                id="interactions",
                state="unknown",
                content=None,
                warnings=[_REASON_CASE_COMMUNICATION_JOIN_MISSING],
                canonicalAuthorityRefs=["communication_facts"],
            ),
            ProjectionSection(
                id="outcomes",
                state="unknown",
                content=None,
                warnings=[_REASON_RESOLUTION_AUTHORITY_MISSING],
                canonicalAuthorityRefs=["outcome_facts"],
            ),
        ]
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=list(context.dependencyState),
            generatedAt=datetime.now(timezone.utc).isoformat(),
            degradedReasons=partial_reasons,
            # History is bounded but has no stable opaque cursor yet. Mark
            # incomplete coverage in content instead of advertising a page
            # the caller cannot request.
            page=PageInfo(nextCursor=None, hasNextPage=False),
        )

    def _unknown_result(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
        reason: str,
    ) -> ProjectionResult:
        """Return no content when the requested subject/query has no exact join."""
        sections = [
            ProjectionSection(
                id=section_id,
                state="degraded" if section_id == "state" else "unknown",
                content=(
                    {
                        "supportCommunications": {
                            "state": "unknown",
                            "reasonCode": reason,
                        },
                        "supportCases": {
                            "state": "unknown",
                            "reasonCode": _REASON_CASE_AUTHORITY_MISSING,
                        },
                        "journeyLinkage": {
                            "state": "unknown",
                            "reasonCode": _REASON_JOURNEY_JOIN_MISSING,
                        },
                        "measuredOutcomes": {
                            "state": "unknown",
                            "reasonCode": _REASON_OUTCOME_JOIN_MISSING,
                        },
                        "requiredSlots": _unknown_support_slots(reason),
                    }
                    if section_id == "state"
                    else None
                ),
                warnings=[reason],
                canonicalAuthorityRefs=list(_subject_authorities(request.subject.kind)),
            )
            for section_id in OUTPUT_SECTIONS
        ]
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=sections,
            claims=[],
            dependencyState=list(context.dependencyState),
            generatedAt=datetime.now(timezone.utc).isoformat(),
            degradedReasons=[reason],
        )


def register_provider(registry: ProviderRegistry) -> str:
    """Register Support360 explicitly during projection-plane boot."""
    return registry.register(
        Support360Provider(),
        source="services/api/journeys/support360",
    )


def _entity_row_matches(row: dict[str, Any], entity_id: str) -> bool:
    return str(row.get("recipient_entity_id") or "") == entity_id


def _agent_row_matches(
    row: dict[str, Any], canonical_agent_entity_id: str, binding_ids: set[str]
) -> bool:
    """Accept only sender facts carrying an exact Agent360 binding receipt."""
    return bool(
        canonical_agent_entity_id
        and row.get("sender_entity_id") == canonical_agent_entity_id
        and _safe_reference(row.get("sender_identity_binding_id")) in binding_ids
    )


def _episode_row_matches(row: dict[str, Any], explicit_references: set[str]) -> bool:
    """Match only IDs named by the exact tenant-owned EpisodeRecord read."""
    return bool(explicit_references) and (
        str(row.get("source_event_id") or "") in explicit_references
        or str(row.get("fact_id") or "") in explicit_references
    )


def _source_row_matches(row: dict[str, Any], connection_ids: set[str]) -> bool:
    """Match a fact only to a current connection resolved by Source360 scope."""
    return bool(connection_ids) and str(row.get("source_connector_id") or "") in connection_ids


def _episode_evidence(episode: Any) -> Optional[EvidenceRef]:
    episode_id = _safe_reference(getattr(episode, "episode_id", None))
    if episode_id is None:
        return None
    return EvidenceRef(
        id=episode_id,
        type="entity",
        source="shared.backend_interpretation.stores.EpisodeStore",
        observedAt=_safe_reference(
            _text(getattr(episode, "created_at", None))
            or _text(getattr(episode, "occurred_to", None))
        ),
        uri=f"store://episode_records/{quote(episode_id, safe='')}",
    )


def _connection_evidence(row: dict[str, Any]) -> EvidenceRef:
    connection_id = str(row.get("connection_id") or "")
    return EvidenceRef(
        id=connection_id,
        type="entity",
        source="provider_connections",
        observedAt=_safe_reference(_text(row.get("updated_at")) or _text(row.get("created_at"))),
        uri=f"store://provider_connections/{quote(connection_id, safe='')}",
    )


def _dedupe_evidence_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    unique: dict[tuple[str, str], EvidenceRef] = {}
    for reference in refs:
        if not isinstance(reference, EvidenceRef) or not reference.id or not reference.source:
            continue
        unique[(reference.source, reference.id)] = reference
    return list(unique.values())


def _case_resolution_slot(
    record: dict[str, Any], events: list[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    """Expose only an exact, evidence-backed resolved/closed case lifecycle state."""
    lifecycle_state = _safe_reference(_text(record.get("lifecycle_state")))
    if lifecycle_state not in {"resolved", "closed"}:
        return None

    event_type = "support_case_resolved" if lifecycle_state == "resolved" else "support_case_closed"
    timestamp_field = "resolved_at" if lifecycle_state == "resolved" else "closed_at"
    resolution_at = _utc_timestamp(record.get(timestamp_field))
    connection_id = _safe_reference(_text(record.get("source_connection_id")))
    provider_identity = _safe_reference(_text(record.get("source_provider_identity")))
    if resolution_at is None or connection_id is None or provider_identity is None:
        return None

    exact_evidence: list[EvidenceRef] = []
    for event in events:
        source_event_id = _safe_reference(_text(event.get("source_event_id")))
        event_at = _utc_timestamp(event.get("source_occurred_at"))
        if (
            source_event_id is None
            or event.get("lifecycle_applied") is not True
            or _safe_reference(_text(event.get("event_type"))) != event_type
            or event_at != resolution_at
        ):
            continue
        exact_evidence.extend(_case_event_evidence_refs(record, event))

    evidence_refs = _dedupe_evidence_refs(exact_evidence)
    if not evidence_refs:
        return None
    return {
        "state": "degraded",
        "resolutionState": lifecycle_state,
        "claimState": "observed",
        "sourceOccurredAt": resolution_at.isoformat(),
        "evidenceRefs": evidence_refs,
        "reasonCode": _REASON_SUPPORT_BUSINESS_OUTCOME_MISSING,
    }


def _case_event_evidence_refs(
    record: dict[str, Any],
    event: dict[str, Any],
) -> list[EvidenceRef]:
    """Return only the exact provider-event and connection refs for one case event."""
    source_event_id = _safe_reference(_text(event.get("source_event_id")))
    connection_id = _safe_reference(_text(record.get("source_connection_id")))
    provider_identity = _safe_reference(_text(record.get("source_provider_identity")))
    event_at = _utc_timestamp(event.get("source_occurred_at"))
    if (
        source_event_id is None
        or connection_id is None
        or provider_identity is None
        or event_at is None
    ):
        return []

    raw_refs = event.get("evidence_refs")
    if isinstance(raw_refs, str):
        try:
            raw_refs = json.loads(raw_refs)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw_refs, (list, tuple)):
        return []

    expected_event_uri = (
        "provider-event://"
        f"{quote(connection_id, safe='')}/{quote(source_event_id, safe='')}"
    )
    expected_connection_uri = f"store://provider_connections/{quote(connection_id, safe='')}"
    event_ref: Optional[EvidenceRef] = None
    connection_ref: Optional[EvidenceRef] = None
    for raw_ref in raw_refs:
        try:
            reference = (
                raw_ref
                if isinstance(raw_ref, EvidenceRef)
                else EvidenceRef.model_validate(raw_ref)
            )
        except (TypeError, ValueError):
            continue
        if (
            reference.id == source_event_id
            and reference.type == "event"
            and reference.source == provider_identity
            and reference.uri == expected_event_uri
            and _utc_timestamp(reference.observedAt) == event_at
        ):
            event_ref = reference
        elif (
            reference.id == connection_id
            and reference.type == "entity"
            and reference.source == "provider_connections"
            and reference.uri == expected_connection_uri
        ):
            connection_ref = reference
    if event_ref is None or connection_ref is None:
        return []
    return [event_ref, connection_ref]


def _utc_timestamp(value: Any) -> Optional[datetime]:
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


def _subject_authorities(subject_kind: str) -> tuple[str, ...]:
    if subject_kind == "agent":
        return ("communication_facts", "identity", "evidence")
    if subject_kind == "episode":
        return ("communication_facts", "episode_facts", "evidence")
    if subject_kind == "source":
        return ("communication_facts", "provider_connections", "evidence")
    return ("communication_facts", "evidence")


def _required_support_slots(
    *,
    section_state: str,
    read: SupportFactsRead,
    support_case_refs: list[dict[str, Any]],
    timeline_content: dict[str, Any],
    communication_evidence_refs: list[EvidenceRef],
    evidence_refs: list[EvidenceRef],
) -> dict[str, dict[str, Any]]:
    """Expose the SSOT-required slots while preserving each missing authority."""
    scope_known = read.available and read.scope_known
    observed_case_refs = support_case_refs if scope_known else None
    communication_evidence = communication_evidence_refs if scope_known else None
    all_evidence = evidence_refs if scope_known else None
    conversation_reasons: set[str] = set()
    if not scope_known:
        conversation_reasons.add(
            _REASON_SOURCE_UNAVAILABLE if not read.available else _safe_read_reason(read.reason)
        )
    if read.truncated:
        conversation_reasons.add(_REASON_READ_TRUNCATED)
    if scope_known and not read.complete:
        conversation_reasons.add("support_communication_history_scope_incomplete")
    evidence_reason = None
    if not scope_known:
        evidence_reason = (
            _REASON_SOURCE_UNAVAILABLE if not read.available else _safe_read_reason(read.reason)
        )
    elif read.truncated:
        evidence_reason = _REASON_READ_TRUNCATED
    elif not read.complete:
        evidence_reason = "support_evidence_trace_scope_incomplete"
    slots = {
        "case_summary": {
            "state": "unknown",
            "reasonCode": _REASON_CASE_AUTHORITY_MISSING,
            "sourceReportedReferences": observed_case_refs,
            "sourceReportedReferencesAreCanonical": False,
        },
        "conversation_history": {
            "state": section_state,
            "reasonCodes": sorted(conversation_reasons),
            "contentMode": "metadata_only",
            "contentAccessState": "unknown",
            "messageBodyState": "suppressed",
            "messageBodyReasonCode": _REASON_CONTENT_PERMISSION_UNVERIFIED,
            "entryCount": timeline_content["entryCount"] if scope_known else None,
            "entries": timeline_content if scope_known else None,
            "evidenceRefs": communication_evidence,
        },
        "callbacks": {
            "state": "unknown",
            "reasonCode": _REASON_CALLBACK_AUTHORITY_MISSING,
        },
        "participants": {
            "state": "unknown",
            "reasonCode": _REASON_PARTICIPANT_AUTHORITY_MISSING,
        },
        "sla": {
            "state": "unknown",
            "reasonCode": _REASON_SLA_AUTHORITY_MISSING,
        },
        "journey_links": {
            "state": "unknown",
            "reasonCode": _REASON_JOURNEY_JOIN_MISSING,
        },
        "agents": {
            "state": "unknown",
            "reasonCode": _REASON_AGENT_ASSIGNMENT_MISSING,
        },
        "risk": {
            "state": "unknown",
            "reasonCode": _REASON_RISK_COMPOSITION_MISSING,
        },
        "resolution": {
            "state": "unknown",
            "reasonCode": _REASON_RESOLUTION_AUTHORITY_MISSING,
        },
        "evidence_trace": {
            "state": section_state,
            "count": len(evidence_refs) if scope_known else None,
            "evidenceRefs": all_evidence,
            "reasonCode": evidence_reason,
        },
    }
    return {slot_id: slots[slot_id] for slot_id in _REQUIRED_SUPPORT_SLOT_IDS}


def _unknown_support_slots(reason: str) -> dict[str, dict[str, Any]]:
    """Return a complete required-slot map when no exact source join exists."""
    slots = {
        "case_summary": {
            "state": "unknown",
            "reasonCode": _REASON_CASE_AUTHORITY_MISSING,
            "sourceReportedReferences": None,
            "sourceReportedReferencesAreCanonical": False,
        },
        "conversation_history": {
            "state": "unknown",
            "reasonCode": reason,
            "contentMode": "metadata_only",
            "contentAccessState": "unknown",
            "messageBodyState": "suppressed",
            "messageBodyReasonCode": _REASON_CONTENT_PERMISSION_UNVERIFIED,
            "entryCount": None,
            "entries": None,
            "evidenceRefs": None,
        },
        "callbacks": {"state": "unknown", "reasonCode": _REASON_CALLBACK_AUTHORITY_MISSING},
        "participants": {
            "state": "unknown",
            "reasonCode": _REASON_PARTICIPANT_AUTHORITY_MISSING,
        },
        "sla": {"state": "unknown", "reasonCode": _REASON_SLA_AUTHORITY_MISSING},
        "journey_links": {"state": "unknown", "reasonCode": _REASON_JOURNEY_JOIN_MISSING},
        "agents": {"state": "unknown", "reasonCode": _REASON_AGENT_ASSIGNMENT_MISSING},
        "risk": {"state": "unknown", "reasonCode": _REASON_RISK_COMPOSITION_MISSING},
        "resolution": {
            "state": "unknown",
            "reasonCode": _REASON_RESOLUTION_AUTHORITY_MISSING,
        },
        "evidence_trace": {
            "state": "unknown",
            "reasonCode": reason,
            "count": None,
            "evidenceRefs": None,
        },
    }
    return {slot_id: slots[slot_id] for slot_id in _REQUIRED_SUPPORT_SLOT_IDS}


def _window_bounds(time_range: Any) -> tuple[tuple[Optional[str], Optional[str]], Optional[str]]:
    """Normalize offset-aware time bounds; reject ambiguous local timestamps."""
    if time_range is None:
        return (None, None), None
    if getattr(time_range, "timezone", None):
        return (None, None), "support_window_timezone_semantics_unavailable"
    raw_after = getattr(time_range, "from_", None)
    raw_before = getattr(time_range, "to", None)

    def _bound(value: Any) -> tuple[Optional[datetime], Optional[str]]:
        if value is None:
            return None, None
        if not isinstance(value, str):
            return None, "support_window_timestamp_invalid"
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None, "support_window_timestamp_invalid"
        if parsed.tzinfo is None:
            return None, "support_window_timestamp_timezone_required"
        return parsed.astimezone(timezone.utc), None

    after_dt, after_error = _bound(raw_after)
    before_dt, before_error = _bound(raw_before)
    if after_error or before_error:
        return (None, None), after_error or before_error
    if after_dt is not None and before_dt is not None and after_dt > before_dt:
        return (None, None), "support_window_bounds_conflict"
    return (
        after_dt.isoformat() if after_dt is not None else None,
        before_dt.isoformat() if before_dt is not None else None,
    ), None


def _row_in_window(row: dict[str, Any], *, after: Optional[str], before: Optional[str]) -> bool:
    """Defensively enforce the same exact inclusive bounds as the repository."""
    if after is None and before is None:
        return True
    raw_occurred_at = row.get("occurred_at")
    if not isinstance(raw_occurred_at, str):
        return False
    try:
        occurred_at = datetime.fromisoformat(raw_occurred_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if occurred_at.tzinfo is None:
        return False
    occurred_at = occurred_at.astimezone(timezone.utc)
    if after is not None:
        lower_bound = datetime.fromisoformat(after)
        if occurred_at < lower_bound:
            return False
    if before is not None:
        upper_bound = datetime.fromisoformat(before)
        if occurred_at > upper_bound:
            return False
    return True


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.value if isinstance(value, Enum) else str(value)


def _safe_reference(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 160:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        return None
    return normalized


def _row_evidence(row: dict[str, Any]) -> Optional[EvidenceRef]:
    evidence_id = _safe_reference(
        row.get("fact_id") or row.get("idempotency_key") or row.get("source_event_id")
    )
    if evidence_id is None:
        return None
    return EvidenceRef(
        id=evidence_id,
        type="event",
        source=_FACT_SOURCE,
        observedAt=_safe_reference(_text(row.get("occurred_at")) or _text(row.get("received_at"))),
        uri=f"store://silver_comms_facts/{quote(evidence_id, safe='')}",
    )


def _source_reported_case_refs(
    rows: list[dict[str, Any]], evidence_refs: list[EvidenceRef]
) -> list[dict[str, Any]]:
    evidence_by_id = {ref.id: ref for ref in evidence_refs}
    refs: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = _safe_reference(row.get("support_case_id"))
        fact_id = _safe_reference(
            row.get("fact_id") or row.get("idempotency_key") or row.get("source_event_id")
        )
        if case_id is None or fact_id is None or fact_id not in evidence_by_id:
            continue
        refs.setdefault(
            case_id,
            {
                "id": case_id,
                "referenceKind": "source_reported_support_case_id",
                "canonicalSupportCaseResolved": False,
                "evidenceRef": evidence_by_id[fact_id],
            },
        )
    return [refs[key] for key in sorted(refs)]


def _timeline_entry(row: dict[str, Any], evidence_ref: EvidenceRef) -> dict[str, Any]:
    case_id = _safe_reference(row.get("support_case_id"))
    return {
        "factId": evidence_ref.id,
        "occurredAt": _safe_reference(_text(row.get("occurred_at"))),
        "direction": _safe_reference(_text(row.get("direction"))),
        "communicationState": _safe_reference(_text(row.get("communication_state"))),
        "sourceEventType": _safe_reference(_text(row.get("source_event_type"))),
        "sourceReportedSupportCaseRef": case_id,
        "canonicalSupportCaseResolved": False,
        "evidenceRef": evidence_ref,
    }


def _newest_timestamp(rows: list[dict[str, Any]]) -> Optional[str]:
    timestamps = [
        timestamp
        for row in rows
        if (
            timestamp := _safe_reference(
                _text(row.get("received_at")) or _text(row.get("occurred_at"))
            )
        )
    ]
    return max(timestamps) if timestamps else None


__all__ = [
    "OUTPUT_SECTIONS",
    "PROJECTION_ID",
    "RepositorySupport360Source",
    "Support360Provider",
    "Support360Source",
    "SupportFactsRead",
    "register_provider",
]
