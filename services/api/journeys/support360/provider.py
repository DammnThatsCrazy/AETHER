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
from shared.backend_interpretation.primitives import EpisodeRecord
from shared.contracts_models.epistemic import EpistemicStatus
from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    ProjectionContext,
    PageInfo,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.intelligence_projections.errors import ProjectionError
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.provider import IntelligenceProjectionProvider
from shared.intelligence_projections.registry import ProviderRegistry
from journeys.support360.cases import SupportCaseAuthorityRead, SupportCaseRepository
from journeys.support360.callbacks import (
    SupportCallbackRead,
    SupportCallbackRepository,
    SupportCallbacksRead,
)
from journeys.support360.assignments import (
    SupportAgentAssignmentRead,
    SupportAgentAssignmentRepository,
)
from journeys.support360.context_authorities import (
    SupportCaseContextRead,
    SupportCaseContextRepository,
)
from repositories.repos import EntityRepository

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
_REASON_CASE_COMMUNICATION_SCOPE_MISMATCH = "support_case_conversation_tenant_scope_mismatch"
_REASON_CASE_COMMUNICATION_TRUNCATED = "support_case_conversation_read_truncated"
_REASON_CASE_COMMUNICATION_HISTORY_UNVERIFIED = (
    "support_case_communication_source_history_coverage_unverified"
)
_REASON_JOURNEY_JOIN_MISSING = "canonical_support_case_journey_join_unavailable"
_REASON_JOURNEY_EPISODE_AUTHORITY_UNAVAILABLE = "support_case_journey_episode_authority_unavailable"
_REASON_JOURNEY_EPISODE_RELATION_MISSING = "support_case_journey_episode_exact_relation_unavailable"
_REASON_JOURNEY_EPISODE_READ_TRUNCATED = "support_case_journey_episode_read_truncated"
_REASON_JOURNEY_EPISODE_TEMPORAL_UNAVAILABLE = "support_case_journey_episode_window_read_unavailable"
_REASON_JOURNEY_EPISODE_POPULATION_UNVERIFIED = "support_case_journey_episode_population_unverified"
_REASON_JOURNEY_EPISODE_FRESHNESS_UNKNOWN = "support_case_journey_episode_freshness_sla_unavailable"
_REASON_JOURNEY_EPISODE_POLICY_UNVERIFIED = "support_case_journey_episode_policy_unverified"
_REASON_OUTCOME_JOIN_MISSING = "canonical_support_outcome_join_unavailable"
_REASON_CALLBACK_AUTHORITY_MISSING = "canonical_support_callback_authority_unavailable"
_REASON_CALLBACK_AUTHORITY_UNAVAILABLE = "support_callback_authority_unavailable"
_REASON_CALLBACK_NOT_FOUND = "support_callback_not_found_for_tenant"
_REASON_CALLBACK_SCOPE_MISMATCH = "support_callback_tenant_case_provider_scope_mismatch"
_REASON_CALLBACK_EVIDENCE_UNAVAILABLE = "support_callback_event_evidence_unavailable"
_REASON_CALLBACK_HISTORY_PARTIAL = "support_callback_event_history_truncated"
_REASON_CALLBACK_SOURCE_HISTORY_UNVERIFIED = "support_callback_source_history_coverage_unverified"
_REASON_CALLBACK_FRESHNESS_UNKNOWN = "support_callback_freshness_sla_unavailable"
_REASON_PARTICIPANT_AUTHORITY_MISSING = "canonical_support_case_participants_unavailable"
_REASON_PARTICIPANT_AUTHORITY_UNAVAILABLE = "support_case_participant_authority_unavailable"
_REASON_PARTICIPANT_SCOPE_MISMATCH = "support_case_participant_tenant_case_provider_scope_mismatch"
_REASON_PARTICIPANT_HISTORY_UNVERIFIED = "support_case_participant_source_roster_history_unverified"
_REASON_PARTICIPANT_IDENTITY_UNAVAILABLE = "support_case_participant_identity_unavailable"
_REASON_CONTEXT_SOURCE_AUTHENTICATION_UNVERIFIED = "support_case_context_provider_origin_unverified"
_REASON_SLA_AUTHORITY_MISSING = "canonical_support_sla_authority_unavailable"
_REASON_SLA_AUTHORITY_UNAVAILABLE = "support_case_sla_authority_unavailable"
_REASON_SLA_SCOPE_MISMATCH = "support_case_sla_tenant_case_provider_scope_mismatch"
_REASON_SLA_HISTORY_UNVERIFIED = "support_case_sla_source_history_unverified"
_REASON_SLA_POLICY_NOT_CANONICAL = "support_case_sla_policy_not_joined_to_measurement_contract"
_REASON_AGENT_ASSIGNMENT_MISSING = "canonical_support_case_agent_assignment_unavailable"
_REASON_AGENT_ASSIGNMENT_AUTHORITY_UNAVAILABLE = "support_case_agent_assignment_authority_unavailable"
_REASON_AGENT_ASSIGNMENT_SCOPE_MISMATCH = "support_case_agent_assignment_tenant_case_provider_scope_mismatch"
_REASON_AGENT_ASSIGNMENT_EVIDENCE_UNAVAILABLE = "support_case_agent_assignment_evidence_unavailable"
_REASON_AGENT_ASSIGNMENT_IDENTITY_UNAVAILABLE = "support_case_agent_assignment_identity_unavailable"
_REASON_AGENT_ASSIGNMENT_HISTORY_UNVERIFIED = "support_case_agent_assignment_source_history_coverage_unverified"
_REASON_AGENT_ASSIGNMENT_FRESHNESS_UNKNOWN = "support_case_agent_assignment_freshness_sla_unavailable"
_REASON_AGENT_ASSIGNMENT_READ_TRUNCATED = "support_case_agent_assignment_read_truncated"
_REASON_JOURNEY_SCOPE_MISMATCH = "support_case_journey_link_tenant_case_provider_scope_mismatch"
_REASON_JOURNEY_AUTHORITY_UNAVAILABLE = "support_case_journey_link_authority_unavailable"
_REASON_JOURNEY_HISTORY_UNVERIFIED = "support_case_journey_link_source_history_unverified"
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
        _REASON_CASE_COMMUNICATION_JOIN_MISSING,
        _REASON_CASE_COMMUNICATION_SCOPE_MISMATCH,
    }
)
_CANONICAL_SUBJECT_AUTHORITY_REASONS = {
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
    # Exact provider/account/conversation keys established from communications
    # already joined to the canonical support case and provider connection.
    conversation_scopes: tuple[tuple[str, str, str], ...] = ()
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

    async def support_facts_for_case(
        self,
        tenant_id: str,
        connection_id: str,
        source_case_id: str,
        *,
        limit: int,
        after: Optional[str] = None,
        before: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> SupportFactsRead:
        """Read facts for an exact canonical case/connection/source-case tuple."""

    async def support_participants_for_case(
        self,
        tenant_id: str,
        connection_id: str,
        source_case_id: str,
        provider_identity: str,
        *,
        limit: int,
    ) -> SupportFactsRead:
        """Join authenticated Communication360 participant bindings to exact case conversations."""

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
        communication360_facts: Any = None,
        episodes: Any = None,
        connections: Any = None,
    ) -> None:
        self._facts = facts
        self._communication360_facts = communication360_facts
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

    async def support_facts_for_case(
        self,
        tenant_id: str,
        connection_id: str,
        source_case_id: str,
        *,
        limit: int,
        after: Optional[str] = None,
        before: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> SupportFactsRead:
        try:
            rows, next_cursor = await self._facts_repository().list_for_support_case(
                tenant_id,
                connection_id,
                source_case_id,
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
                subject_join="support_case_connection_and_source_case_id_exact_match",
                join_reference_ids=(connection_id,),
                canonical_authority_refs=(
                    "communication_facts",
                    "provider_connections",
                    "support_cases",
                    "evidence",
                ),
            )
        return SupportFactsRead(
            rows=[row for row in rows if isinstance(row, dict)],
            available=True,
            truncated=next_cursor is not None,
            complete=next_cursor is None,
            next_cursor=next_cursor,
            subject_join="support_case_connection_and_source_case_id_exact_match",
            join_reference_ids=(connection_id,),
            canonical_authority_refs=(
                "communication_facts",
                "provider_connections",
                "support_cases",
                "evidence",
            ),
        )

    async def support_participants_for_case(
        self,
        tenant_id: str,
        connection_id: str,
        source_case_id: str,
        provider_identity: str,
        *,
        limit: int,
    ) -> SupportFactsRead:
        """Join provider rosters through exact case-linked account/thread keys."""
        exact_tenant = str(tenant_id or "").strip()
        exact_connection = str(connection_id or "").strip()
        exact_case = str(source_case_id or "").strip()
        exact_provider = str(provider_identity or "").strip()
        if not all((exact_tenant, exact_connection, exact_case, exact_provider)):
            return SupportFactsRead(
                rows=[],
                available=True,
                scope_known=False,
                reason=_REASON_PARTICIPANT_AUTHORITY_MISSING,
                subject_join="support_case_connection_source_case_to_provider_account_conversation_exact_match",
                canonical_authority_refs=("communication_facts", "communication360_facts", "support_cases", "evidence"),
            )

        scoped_limit = min(max(int(limit), 1), _MAX_LIMIT)
        try:
            case_rows, next_cursor = await self._facts_repository().list_for_support_case(
                exact_tenant,
                exact_connection,
                exact_case,
                category="support",
                limit=scoped_limit,
            )
        except Exception:  # noqa: BLE001 - case-message read failure is typed unknown
            return SupportFactsRead(
                rows=[],
                available=False,
                reason=_REASON_SOURCE_UNAVAILABLE,
                subject_join="support_case_connection_source_case_to_provider_account_conversation_exact_match",
                canonical_authority_refs=("communication_facts", "communication360_facts", "support_cases", "evidence"),
            )

        try:
            connection = await self._connection_repository().find(exact_connection)
        except Exception:  # noqa: BLE001 - connection membership is part of the exact join
            connection = None
        connection_value = (
            (lambda key: connection.get(key))
            if isinstance(connection, dict)
            else (lambda key: getattr(connection, key, None))
        )
        selected_accounts = connection_value("selected_accounts")
        connection_state = connection_value("state")
        if isinstance(connection_state, Enum):
            connection_state = connection_state.value
        verified_at = _utc_timestamp(connection_value("last_verified_at"))
        if (
            connection is None
            or connection_value("tenant_id") != exact_tenant
            or connection_value("connection_id") != exact_connection
            or connection_value("provider_identity") != exact_provider
            or connection_state not in {"verified", "connected"}
            or verified_at is None
            or not isinstance(selected_accounts, (list, tuple, set))
        ):
            return SupportFactsRead(
                rows=[],
                available=False,
                reason=_REASON_PARTICIPANT_AUTHORITY_UNAVAILABLE,
                subject_join="support_case_connection_source_case_to_provider_account_conversation_exact_match",
                join_reference_ids=(exact_connection,),
                canonical_authority_refs=("communication_facts", "communication360_facts", "provider_connections", "support_cases", "evidence"),
            )
        selected_account_ids = {
            str(value).strip() for value in selected_accounts if isinstance(value, str) and value.strip()
        }
        if not selected_account_ids:
            return SupportFactsRead(
                rows=[],
                available=True,
                scope_known=False,
                reason=_REASON_CASE_COMMUNICATION_SCOPE_MISMATCH,
                subject_join="support_case_connection_source_case_to_provider_account_conversation_exact_match",
                join_reference_ids=(exact_connection,),
                canonical_authority_refs=("communication_facts", "communication360_facts", "provider_connections", "support_cases", "evidence"),
            )

        keys: set[tuple[str, str, str]] = set()
        case_evidence: list[EvidenceRef] = []
        incomplete_case_links = False
        for row in case_rows:
            if (
                not isinstance(row, dict)
                or row.get("tenant_id") != exact_tenant
                or str(row.get("source_connector_id") or "") != exact_connection
                or str(row.get("support_case_id") or "") != exact_case
                or str(row.get("message_category") or "") != "support"
                or str(row.get("provider") or "") != exact_provider
            ):
                return SupportFactsRead(
                    rows=[],
                    available=True,
                    scope_known=False,
                    reason=_REASON_CASE_COMMUNICATION_SCOPE_MISMATCH,
                    subject_join="support_case_connection_source_case_to_provider_account_conversation_exact_match",
                    canonical_authority_refs=("communication_facts", "communication360_facts", "support_cases", "evidence"),
                )
            account = _safe_reference(_text(row.get("provider_account_id")))
            conversation = _safe_reference(_text(row.get("external_thread_id")))
            if account is None or conversation is None:
                incomplete_case_links = True
                continue
            if account not in selected_account_ids:
                return SupportFactsRead(
                    rows=[],
                    available=True,
                    scope_known=False,
                    reason=_REASON_CASE_COMMUNICATION_SCOPE_MISMATCH,
                    subject_join="support_case_connection_source_case_to_provider_account_conversation_exact_match",
                    join_reference_ids=(exact_connection, account),
                    canonical_authority_refs=("communication_facts", "communication360_facts", "provider_connections", "support_cases", "evidence"),
                )
            keys.add((exact_provider, account, conversation))
            if reference := _row_evidence(row):
                case_evidence.append(reference)

        connection_ref = EvidenceRef(
            id=exact_connection,
            type="entity",
            source="provider_connections",
            observedAt=verified_at.isoformat(),
            uri=f"store://provider_connections/{quote(exact_connection, safe='')}",
        )
        case_evidence.append(connection_ref)

        if not keys:
            return SupportFactsRead(
                rows=[],
                available=True,
                scope_known=False,
                truncated=next_cursor is not None or incomplete_case_links,
                complete=False,
                reason=_REASON_CASE_COMMUNICATION_JOIN_MISSING,
                subject_join="support_case_connection_source_case_to_provider_account_conversation_exact_match",
                join_reference_ids=(exact_connection,),
                join_evidence_refs=tuple(_dedupe_evidence_refs(case_evidence)),
                canonical_authority_refs=("communication_facts", "communication360_facts", "support_cases", "evidence"),
            )

        try:
            participant_repository = self._communication360_facts_repository()
            rows: list[dict[str, Any]] = []
            participants_complete = True
            remaining = scoped_limit
            scopes_by_provider_account: dict[tuple[str, str], set[str]] = {}
            for provider, account, conversation in sorted(keys):
                scopes_by_provider_account.setdefault((provider, account), set()).add(conversation)
            for (provider, account), conversations in sorted(scopes_by_provider_account.items()):
                if remaining <= 0:
                    participants_complete = False
                    break
                scoped_rows, read_complete = await participant_repository.participant_bindings_for_conversations(
                    exact_tenant,
                    provider,
                    account,
                    sorted(conversations),
                    limit=remaining,
                )
                rows.extend(row for row in scoped_rows if isinstance(row, dict))
                remaining -= len(scoped_rows)
                participants_complete = participants_complete and read_complete
        except Exception:  # noqa: BLE001 - canonical roster read failure remains typed unknown
            return SupportFactsRead(
                rows=[],
                available=False,
                reason=_REASON_PARTICIPANT_AUTHORITY_UNAVAILABLE,
                subject_join="support_case_connection_source_case_to_provider_account_conversation_exact_match",
                join_reference_ids=tuple(sorted({exact_connection, *(key[2] for key in keys)})),
                join_evidence_refs=tuple(_dedupe_evidence_refs(case_evidence)),
                conversation_scopes=tuple(sorted(keys)),
                canonical_authority_refs=("communication_facts", "communication360_facts", "support_cases", "evidence"),
            )
        complete = next_cursor is None and not incomplete_case_links and participants_complete
        return SupportFactsRead(
            rows=rows,
            available=True,
            truncated=next_cursor is not None or incomplete_case_links or not participants_complete,
            complete=complete,
            reason=("support_case_participant_conversation_join_incomplete" if incomplete_case_links else None),
            subject_join="support_case_connection_source_case_to_provider_account_conversation_exact_match",
            join_reference_ids=tuple(sorted({exact_connection, *(key[2] for key in keys)})),
            join_evidence_refs=tuple(_dedupe_evidence_refs(case_evidence)),
            conversation_scopes=tuple(sorted(keys)),
            canonical_authority_refs=("communication_facts", "communication360_facts", "support_cases", "evidence"),
        )

    def _communication360_facts_repository(self) -> Any:
        if self._communication360_facts is None:
            from journeys.communication360.repository import Communication360FactsRepository

            self._communication360_facts = Communication360FactsRepository()
        return self._communication360_facts

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
        callback_repository: Optional[SupportCallbackRepository] = None,
        agent_assignment_repository: Optional[SupportAgentAssignmentRepository] = None,
        canonical_agent_entity_repository: Any = None,
        case_context_repository: Optional[SupportCaseContextRepository] = None,
        canonical_journey_repository: Any = None,
        canonical_episode_store: Any = None,
        risk_projection_registry: Any = None,
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
        self._callback_repository = (
            callback_repository
            if callback_repository is not None
            else SupportCallbackRepository()
        )
        self._agent_assignment_repository = (
            agent_assignment_repository
            if agent_assignment_repository is not None
            else SupportAgentAssignmentRepository()
        )
        self._canonical_agent_entities = (
            canonical_agent_entity_repository
            if canonical_agent_entity_repository is not None
            else EntityRepository()
        )
        self._case_context_repository = (
            case_context_repository
            if case_context_repository is not None
            else SupportCaseContextRepository()
        )
        self._canonical_journeys = canonical_journey_repository
        self._canonical_episodes = canonical_episode_store
        self._risk_projection_registry = risk_projection_registry

    async def _support_case_risk_slot(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
        case_record: dict[str, Any],
    ) -> tuple[dict[str, Any], list[EvidenceRef], list[str]]:
        """Compose Risk360 only after this provider has proven the exact case."""
        if (
            case_record.get("tenant_id") != request.tenantId
            or str(case_record.get("case_id")) != request.subject.id
        ):
            return (
                {"state": "unknown", "reasonCode": _REASON_RISK_COMPOSITION_MISSING},
                [],
                [_REASON_RISK_COMPOSITION_MISSING],
            )
        try:
            if self._risk_projection_registry is None:
                from shared.intelligence_projections.registry import projection_registry

                registry = projection_registry
            else:
                registry = self._risk_projection_registry
            risk_request = ProjectionRequest(
                projectionId="risk360",
                tenantId=request.tenantId,
                subject=ProjectionSubject(kind="support_case", id=request.subject.id),
                includeSections=["summary", "state", "financial_risk", "evidence", "findings", "health"],
                timeRange=request.timeRange,
                temporalMode=request.temporalMode,
                lensIds=request.lensIds,
                includeClaims=False,
            )
            result = await registry.project(
                "risk360",
                risk_request,
                experience360_read_authorizations=context.experience360ReadAuthorizations,
            )
        except Exception:  # noqa: BLE001 - missing dependency remains explicit
            return (
                {"state": "unknown", "reasonCode": _REASON_RISK_COMPOSITION_MISSING},
                [],
                [_REASON_RISK_COMPOSITION_MISSING],
            )
        if (
            getattr(result, "tenantId", None) != request.tenantId
            or getattr(result, "projectionId", None) != "risk360"
        ):
            return (
                {"state": "unknown", "reasonCode": _REASON_RISK_COMPOSITION_MISSING},
                [],
                [_REASON_RISK_COMPOSITION_MISSING],
            )
        section_rows: list[dict[str, Any]] = []
        evidence_refs: list[EvidenceRef] = []
        states: list[str] = []
        for section in getattr(result, "sections", []):
            if not isinstance(section, ProjectionSection):
                continue
            states.append(section.state)
            content = section.content
            section_rows.append(
                {
                    "sectionId": section.id,
                    "state": section.state,
                    "content": content,
                    "warnings": list(section.warnings or []),
                }
            )
            if section.id == "evidence" and isinstance(content, dict):
                refs = content.get("evidence")
                if isinstance(refs, list):
                    for raw_ref in refs:
                        try:
                            evidence_refs.append(EvidenceRef.model_validate(raw_ref))
                        except (TypeError, ValueError):
                            continue
        evidence_refs = _dedupe_evidence_refs(evidence_refs)
        reasons = sorted(
            {
                reason
                for section in section_rows
                for reason in section["warnings"]
                if isinstance(reason, str)
            }
        )
        if not section_rows or all(state in {"missing", "unknown", "empty"} for state in states):
            state = "unknown"
            reasons.append("support_case_risk_observations_unavailable")
        elif any(value in {"degraded", "unavailable", "conflicted"} for value in states):
            state = "degraded"
        elif any(value in {"available", "ready"} for value in states):
            state = "ready"
        else:
            state = "empty"
        slot = {
            "state": state,
            "reasonCodes": sorted(set(reasons)),
            "sections": section_rows,
            "evidenceRefs": evidence_refs,
            "projectionId": "risk360",
            "claimState": "observed",
        }
        return slot, evidence_refs, sorted(set(reasons))

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

        if request.subject.kind not in {
            "entity",
            "agent",
            "episode",
            "source",
            "support_case",
            "callback",
        }:
            # Remaining valid SSOT subject identifiers do not all have a
            # canonical authority. Preserve them as typed unknowns instead of
            # labeling a supported contract subject as invalid.
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
        if request.subject.kind == "callback":
            return await self._project_callback(request, context, limit=limit)
        if request.subject.kind == "support_case":
            return await self._project_case(
                request,
                context,
                limit=limit,
                after=after,
                before=before,
            )
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
            "state": read_state,
            "count": len(events),
            "factIds": [event["factId"] for event in events],
            "categoryFilter": "support",
            "mode": "metadata_only",
            "bodyState": "suppressed",
            "order": "occurred_at_ascending",
            "historyCoverage": "persisted_support_communication_facts_only",
            "readCompleteness": (
                "unknown"
                if not read.available or not read.scope_known
                else "partial"
                if read.truncated or not read.complete
                else "complete_current_store_read"
            ),
            "sourceHistoryComplete": False,
            "freshness": {
                "state": "unknown",
                "newestObservedAt": newest_observed_at,
                "reasonCode": "support_source_freshness_sla_unavailable",
            },
            "entries": events,
            "evidenceRefs": evidence_refs,
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
        after: Optional[str] = None,
        before: Optional[str] = None,
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

        try:
            callback_read = await self._callback_repository.list_for_case(
                request.tenantId,
                request.subject.id,
                limit=limit,
                after=after,
                before=before,
            )
        except Exception:  # noqa: BLE001 - callback authority failure is a typed unknown slot
            callback_read = SupportCallbacksRead([], False, False, reason=_REASON_CALLBACK_AUTHORITY_UNAVAILABLE)
        callback_slot, callback_evidence_refs, callback_reasons = _validated_callback_slot(
            callback_read,
            tenant_id=request.tenantId,
            case_record=record,
        )

        # The `agents` product slot is policy-filtered by the frame runtime.
        # Avoid reading it unless its bound state section is in the post-policy
        # include set (or the caller requested the full frame).
        if request.includeSections is None or {"state", "evidence"}.intersection(
            request.includeSections
        ):
            try:
                assignment_read = await self._agent_assignment_repository.list_for_case(
                    request.tenantId,
                    request.subject.id,
                    connection_id=str(record.get("source_connection_id") or ""),
                    limit=min(limit, 100),
                )
            except Exception:  # noqa: BLE001 - an authority outage is typed unknown
                assignment_read = SupportAgentAssignmentRead(
                    events=[],
                    available=False,
                    complete=False,
                    reason=_REASON_AGENT_ASSIGNMENT_AUTHORITY_UNAVAILABLE,
                )
            (
                agent_assignment_slot,
                agent_assignment_evidence_refs,
                agent_assignment_reasons,
            ) = await _validated_agent_assignment_slot(
                assignment_read,
                tenant_id=request.tenantId,
                case_record=record,
                entity_repository=self._canonical_agent_entities,
            )
        else:
            agent_assignment_slot = {
                "state": "unknown",
                "reasonCode": _REASON_AGENT_ASSIGNMENT_MISSING,
                "assignmentEvents": None,
            }
            agent_assignment_evidence_refs = []
            agent_assignment_reasons = []

        context_slots_requested = request.includeSections is None or bool(
            {"state", "evidence"}.intersection(request.includeSections)
        )
        if context_slots_requested:
            context_reads: dict[str, SupportCaseContextRead] = {}
            for kind in ("sla", "journey_links"):
                try:
                    context_reads[kind] = await self._case_context_repository.list_for_case(
                        request.tenantId,
                        request.subject.id,
                        connection_id=str(record.get("source_connection_id") or ""),
                        kind=kind,
                        limit=min(limit, 200),
                    )
                except Exception:  # noqa: BLE001 - each source fails independently
                    context_reads[kind] = SupportCaseContextRead(
                        [], False, False, reason="support_case_context_read_unavailable"
                    )
            participant_read = await self._case_participant_read(
                request.tenantId,
                record,
                limit=min(limit, 500),
            )
            (
                participants_slot,
                participant_evidence_refs,
                participant_reasons,
            ) = await _validated_canonical_support_participant_slot(
                participant_read,
                tenant_id=request.tenantId,
                case_record=record,
                entity_repository=self._canonical_agent_entities,
            )
            sla_slot, sla_evidence_refs, sla_reasons = _validated_support_sla_slot(
                context_reads["sla"],
                tenant_id=request.tenantId,
                case_record=record,
            )
            (
                journey_links_slot,
                journey_link_evidence_refs,
                journey_link_reasons,
            ) = await _validated_support_journey_link_slot(
                context_reads["journey_links"],
                tenant_id=request.tenantId,
                case_record=record,
                journey_repository=self._canonical_journeys,
            )
            if journey_links_slot.get("links") and (
                not context_reads["journey_links"].complete
                or context_reads["journey_links"].truncated
            ):
                journey_links_slot["episodeFacts"] = {
                    "state": "unknown",
                    "reasonCode": "support_case_context_read_truncated",
                    "relations": None,
                }
            elif journey_links_slot.get("links"):
                episode_facts, episode_refs, episode_reasons = await _validated_case_journey_episodes(
                    tenant_id=request.tenantId,
                    links=journey_links_slot["links"],
                    episode_store=self._canonical_episodes,
                    windowed=request.timeRange is not None,
                )
                journey_links_slot["episodeFacts"] = episode_facts
                journey_link_evidence_refs = _dedupe_evidence_refs(
                    journey_link_evidence_refs + episode_refs
                )
                journey_link_reasons.extend(episode_reasons)
                journey_links_slot["reasonCodes"] = sorted(
                    set(journey_links_slot.get("reasonCodes", []) + episode_reasons)
                )
        else:
            participants_slot = {
                "state": "unknown",
                "reasonCode": _REASON_PARTICIPANT_AUTHORITY_MISSING,
                "participants": None,
            }
            participant_evidence_refs = []
            participant_reasons = []
            sla_slot = {"state": "unknown", "reasonCode": _REASON_SLA_AUTHORITY_MISSING}
            sla_evidence_refs = []
            sla_reasons = []
            journey_links_slot = {
                "state": "unknown",
                "reasonCode": _REASON_JOURNEY_JOIN_MISSING,
                "links": None,
            }
            journey_link_evidence_refs = []
            journey_link_reasons = []

        if context_slots_requested:
            risk_slot, risk_evidence_refs, risk_reasons = await self._support_case_risk_slot(
                request, context, record
            )
        else:
            risk_slot = {
                "state": "unknown",
                "reasonCode": _REASON_RISK_COMPOSITION_MISSING,
            }
            risk_evidence_refs = []
            risk_reasons = []

        events = [event for event in read.events if isinstance(event, dict)]
        case_record_evidence_ref = _support_case_record_evidence(record)
        evidence_refs: list[EvidenceRef] = (
            [case_record_evidence_ref] if case_record_evidence_ref is not None else []
        )
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
        case_lifecycle_evidence_refs = list(evidence_refs)
        context_evidence_refs = _dedupe_evidence_refs(
            participant_evidence_refs
            + sla_evidence_refs
            + journey_link_evidence_refs
            + risk_evidence_refs
        )
        evidence_refs = _dedupe_evidence_refs(
            evidence_refs
            + callback_evidence_refs
            + agent_assignment_evidence_refs
            + context_evidence_refs
        )

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
            "persistedStoreReadComplete": read.complete,
            "sourceHistoryComplete": False,
            "freshness": {
                "state": "unknown",
                "newestObservedAt": newest_received_at,
                "reasonCode": "support_case_freshness_sla_unavailable",
            },
            "reasonCodes": partial_reasons,
        }
        slots = _unknown_support_slots(_REASON_CASE_COMMUNICATION_JOIN_MISSING)
        slots["callbacks"] = callback_slot
        slots["agents"] = agent_assignment_slot
        slots["participants"] = participants_slot
        slots["sla"] = sla_slot
        slots["journey_links"] = journey_links_slot
        slots["risk"] = risk_slot
        slots["case_summary"] = {
            "state": "degraded",
            "reasonCodes": partial_reasons,
            "canonicalCaseId": request.subject.id,
            "lifecycleState": lifecycle_state,
            "claimState": "observed",
            "sourceOccurredAt": lifecycle_observed_at,
            "persistedStoreReadComplete": read.complete,
            "sourceHistoryComplete": False,
            "freshness": {
                "state": "unknown",
                "newestObservedAt": newest_received_at,
                "reasonCode": "support_case_freshness_sla_unavailable",
            },
            "evidenceRefs": case_lifecycle_evidence_refs,
        }
        slots["evidence_trace"] = {
            "state": "degraded",
            "reasonCodes": partial_reasons,
            "count": len(evidence_refs),
            "evidenceRefs": evidence_refs,
        }
        communication_slot_readable = (
            request.includeSections is None or "interactions" in request.includeSections
        )
        if communication_slot_readable:
            communication_read = await self._case_communication_read(
                request,
                record,
                limit=limit,
                after=after,
                before=before,
            )
            communication_rows, communication_scope_known, communication_reasons = (
                self._validated_case_communication_rows(
                    communication_read,
                    tenant_id=request.tenantId,
                    record=record,
                    after=after,
                    before=before,
                )
            )
        else:
            # Experience360 only includes this section when its exact
            # conversation_history slot is requested and allowed by policy.
            # Do not read communication facts for sibling case slots that share
            # the broad Support360 projection provider.
            communication_read = SupportFactsRead(
                rows=[],
                available=True,
                scope_known=False,
                reason=_REASON_CASE_COMMUNICATION_JOIN_MISSING,
                subject_join="support_case_connection_and_source_case_id_exact_match",
                canonical_authority_refs=(
                    "communication_facts",
                    "provider_connections",
                    "support_cases",
                    "evidence",
                ),
            )
            communication_rows = []
            communication_scope_known = False
            communication_reasons = []
        communication_refs = [
            reference for row in communication_rows if (reference := _row_evidence(row)) is not None
        ]
        communication_refs = _dedupe_evidence_refs(communication_refs)
        communication_freshness = {
            "state": "unknown",
            "newestObservedAt": (
                _newest_timestamp(communication_rows) if communication_scope_known else None
            ),
            "reasonCode": "support_communication_freshness_sla_unavailable",
        }
        case_join_evidence_refs = list(case_lifecycle_evidence_refs)
        case_communication_evidence = _dedupe_evidence_refs(
            case_join_evidence_refs + communication_refs
        )
        conversation_entries = [
            _case_communication_timeline_entry(
                row,
                evidence_ref,
                canonical_case_id=request.subject.id,
                case_join_evidence_refs=case_join_evidence_refs,
            )
            for row in communication_rows
            if (evidence_ref := _row_evidence(row)) is not None
        ]
        if not communication_scope_known:
            slots["conversation_history"] = {
                "state": "unknown",
                "reasonCodes": communication_reasons,
                "contentMode": "metadata_only",
                "contentAccessState": "unknown",
                "messageBodyState": "suppressed",
                "messageBodyReasonCode": _REASON_CONTENT_PERMISSION_UNVERIFIED,
                "entryCount": None,
                "entries": None,
                "evidenceRefs": None,
                "freshness": communication_freshness,
            }
        else:
            communication_state = (
                "degraded"
                if communication_read.truncated
                or not communication_read.complete
                or communication_reasons
                or conversation_entries
                else "empty"
            )
            slots["conversation_history"] = {
                "state": communication_state,
                "reasonCodes": communication_reasons,
                "contentMode": "metadata_only",
                "contentAccessState": "unknown",
                "messageBodyState": "suppressed",
                "messageBodyReasonCode": _REASON_CONTENT_PERMISSION_UNVERIFIED,
                "entryCount": len(conversation_entries),
                "historyCoverage": "persisted_support_communication_facts_only",
                "readCompleteness": (
                    "partial"
                    if communication_read.truncated or not communication_read.complete
                    else "complete_current_store_read"
                ),
                "sourceHistoryComplete": False,
                "freshness": communication_freshness,
                "entries": {
                    "order": "occurred_at_ascending",
                    "causalRelationsDeclared": False,
                    "entries": conversation_entries,
                },
                "evidenceRefs": case_communication_evidence,
                "caseJoinEvidenceRefs": case_join_evidence_refs,
            }
            evidence_refs = _dedupe_evidence_refs(
                case_communication_evidence
                + callback_evidence_refs
                + agent_assignment_evidence_refs
                + context_evidence_refs
            )
            slots["evidence_trace"] = {
                "state": "degraded",
                "reasonCodes": sorted(
                    set(
                        partial_reasons
                        + communication_reasons
                        + participant_reasons
                        + sla_reasons
                        + journey_link_reasons
                        + risk_reasons
                    )
                ),
                "count": len(evidence_refs),
                "evidenceRefs": evidence_refs,
            }
        case_degraded_reasons = sorted(
            set(
                partial_reasons
                + callback_reasons
                + communication_reasons
                + agent_assignment_reasons
                + participant_reasons
                + sla_reasons
                + journey_link_reasons
                + risk_reasons
            )
        )
        resolution_slot = _case_resolution_slot(record, events)
        if resolution_slot is not None:
            slots["resolution"] = resolution_slot
        state_content = {
            "supportCommunications": {
                "state": (
                    "unknown"
                    if not communication_scope_known
                    else "degraded"
                    if communication_reasons or conversation_entries
                    else "empty"
                ),
                "subjectJoin": communication_read.subject_join,
                "reasonCodes": communication_reasons,
                "observedCount": len(conversation_entries) if communication_scope_known else None,
                "joinEvidenceRefs": case_join_evidence_refs if communication_scope_known else None,
                "readCompleteness": (
                    "unknown"
                    if not communication_scope_known
                    else "partial"
                    if communication_read.truncated or not communication_read.complete
                    else "complete_current_store_read"
                ),
                "sourceHistoryComplete": False,
                "freshness": communication_freshness,
            },
            "supportCases": {
                "state": "observed",
                "canonicalCaseId": request.subject.id,
                "lifecycleState": lifecycle_state,
                "claimState": "observed",
                "sourceOccurredAt": lifecycle_observed_at,
                "sourceEventCount": len(events),
                "sourceHistoryComplete": False,
                "persistedReadCompleteness": (
                    "complete_current_store_read" if read.complete else "partial"
                ),
            },
            "journeyLinkage": {
                "state": journey_links_slot.get("state", "unknown"),
                "reasonCode": journey_links_slot.get("reasonCode"),
                "links": journey_links_slot.get("links"),
                "episodeFacts": journey_links_slot.get("episodeFacts"),
            },
            "measuredOutcomes": {
                "state": "unknown",
                "reasonCode": _REASON_OUTCOME_JOIN_MISSING,
            },
            "agentAssignments": agent_assignment_slot,
            "participants": participants_slot,
            "supportSLA": sla_slot,
            "supportRisk": risk_slot,
            "requiredSlots": slots,
        }
        timeline_content = {
            "order": "source_occurred_at_descending",
            "causalRelationsDeclared": False,
            "entryCount": len(timeline_entries),
            "entries": timeline_entries,
            "coverage": "persisted_case_events_only",
            "callbacks": callback_slot,
            "communicationHistory": {
                "state": slots["conversation_history"]["state"],
                "contentMode": "metadata_only",
                "messageBodyState": "suppressed",
                "entries": conversation_entries if communication_scope_known else None,
                "evidenceRefs": case_communication_evidence if communication_scope_known else None,
                "freshness": communication_freshness,
            },
        }
        evidence_content = {
            "count": len(evidence_refs),
            "evidenceRefs": evidence_refs,
            "supportCallbackEvidenceRefs": callback_evidence_refs,
            "supportAgentAssignmentEvidenceRefs": agent_assignment_evidence_refs,
            "supportParticipantEvidenceRefs": participant_evidence_refs,
            "supportSLAEvidenceRefs": sla_evidence_refs,
            "supportJourneyLinkEvidenceRefs": journey_link_evidence_refs,
            "supportRiskEvidenceRefs": risk_evidence_refs,
            "caseLifecycleEvidenceRefs": case_lifecycle_evidence_refs,
            "supportCommunicationEvidenceRefs": (
                communication_refs if communication_scope_known else None
            ),
            "caseCommunicationJoinEvidenceRefs": (
                case_join_evidence_refs if communication_scope_known else None
            ),
        }
        claims = [
            ClaimEnvelope(
                id=f"support360.case.{request.subject.id}.{record['last_source_event_id']}",
                kind="support_case_lifecycle_observation",
                subject=request.subject,
                evidenceRefs=case_lifecycle_evidence_refs,
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
        claims.extend(
            ClaimEnvelope(
                id=f"support360.assignment.{event['assignmentEventId']}",
                kind="support_agent_assignment_observation",
                subject=request.subject,
                evidenceRefs=event["evidenceRefs"],
                claims=[
                    "The authenticated tenant principal recorded this source-observed support agent assignment or handoff for the exact canonical support case and provider connection."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["agents", "evidence_trace"],
            )
            for event in agent_assignment_slot.get("assignmentEvents", [])
            if isinstance(event, dict) and event.get("evidenceRefs")
        )
        claims.extend(
            ClaimEnvelope(
                id=f"support360.context.{event['contextEventId']}",
                kind=f"support_case_{claim_kind}_observation",
                subject=request.subject,
                evidenceRefs=event["evidenceRefs"],
                claims=[
                    f"An authenticated tenant principal recorded this exact source-reported support case {claim_kind} event."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=[slot_id, "evidence_trace"],
            )
            for claim_kind, slot_id, slot in (
                ("SLA", "sla", sla_slot),
                ("journey_link", "journey_links", journey_links_slot),
            )
            for event in slot.get("events", [])
            if isinstance(event, dict) and event.get("evidenceRefs")
        )
        claims.extend(
            ClaimEnvelope(
                id=f"support360.episode_journey.{relation['canonicalEpisodeId']}.{relation['contextEventId']}",
                kind="support_case_episode_journey_observation",
                subject=request.subject,
                evidenceRefs=relation["evidenceRefs"],
                claims=[
                    "The exact tenant EpisodeRecord references this verified support case journey-link event and names the same canonical journey."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["journey_links", "evidence_trace"],
            )
            for relation in ((journey_links_slot.get("episodeFacts") or {}).get("relations") or [])
        )
        claims.extend(
            ClaimEnvelope(
                id=f"support360.participant.{participant['sourceRosterId']}.{participant['sourceBindingId']}",
                kind="communication_participant_binding_observation",
                subject=request.subject,
                evidenceRefs=[
                    reference
                    for reference in participant.get("evidenceRefs", [])
                    if isinstance(reference, EvidenceRef)
                ],
                claims=[
                    "The provider-authenticated Communication360 roster asserted this exact canonical participant role for a provider conversation linked to the support case."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["participants", "evidence_trace"],
            )
            for participant in (participants_slot.get("participants") or [])
            if isinstance(participant, dict)
            and participant.get("sourceRosterId")
            and participant.get("sourceBindingId")
            and participant.get("evidenceRefs")
        )
        if callback_slot["state"] not in {"unknown", "degraded_unavailable"}:
            for callback in callback_slot.get("callbacks", []):
                callback_refs = [
                    reference
                    for reference in callback.get("evidenceRefs", [])
                    if isinstance(reference, EvidenceRef)
                ]
                if callback_refs:
                    claims.append(
                        ClaimEnvelope(
                            id=f"support360.callback.{callback['callbackId']}.{callback['lastSourceEventId']}",
                            kind="support_callback_schedule_execution_observation",
                            subject=ProjectionSubject(kind="callback", id=callback["callbackId"]),
                            evidenceRefs=callback_refs,
                            claims=[
                                "The tenant-authorized ingress accepted this source-asserted callback schedule or execution event for the exact canonical support case under the verified provider connection."
                            ],
                            claimState=EpistemicStatus.OBSERVED,
                            domainSlotIds=["callbacks", "evidence_trace"],
                        )
                    )
        claims.extend(
            ClaimEnvelope(
                id=f"support360.case.communication.{request.subject.id}.{reference.id}",
                kind="support_case_communication_metadata",
                subject=request.subject,
                evidenceRefs=_dedupe_evidence_refs(case_communication_evidence + [reference]),
                claims=[
                    "Support communication metadata is observed for the exact tenant-scoped canonical case."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["conversation_history", "evidence_trace"],
            )
            for reference in communication_refs
        )
        episode_authority_refs = (
            ["episode_facts"]
            if (journey_links_slot.get("episodeFacts") or {}).get("relations")
            else []
        )
        sections = [
            ProjectionSection(
                id="summary",
                state="degraded",
                content=case_summary,
                warnings=partial_reasons,
                canonicalAuthorityRefs=[
                    "support_cases",
                    "support_case_events",
                    "support_callbacks",
                    "support_callback_events",
                    "support_case_agent_assignment_events",
                    "support_case_context_events",
                    "provider_connections",
                    "communication_facts",
                    "entities",
                    "journey_versions",
                    "measurement_contract",
                    "risk_outputs",
                    "evidence",
                ],
            ),
            ProjectionSection(
                id="state",
                state="degraded",
                content=state_content,
                warnings=case_degraded_reasons,
                canonicalAuthorityRefs=[
                    "support_cases",
                    "support_case_events",
                    "support_callbacks",
                    "support_callback_events",
                    "support_case_agent_assignment_events",
                    "support_case_context_events",
                    "provider_connections",
                    "communication_facts",
                    "entities",
                    "journey_versions",
                    "measurement_contract",
                    "risk_outputs",
                    "evidence",
                ] + episode_authority_refs,
            ),
            ProjectionSection(
                id="timeline",
                state="degraded",
                content=timeline_content,
                warnings=case_degraded_reasons,
                canonicalAuthorityRefs=[
                    "support_case_events",
                    "support_callbacks",
                    "support_callback_events",
                    "support_case_agent_assignment_events",
                    "support_case_context_events",
                    "communication_facts",
                    "entities",
                    "journey_versions",
                    "measurement_contract",
                    "risk_outputs",
                    "evidence",
                ],
            ),
            ProjectionSection(
                id="evidence",
                state="degraded",
                content=evidence_content,
                warnings=case_degraded_reasons,
                canonicalAuthorityRefs=[
                    "support_case_events",
                    "support_callbacks",
                    "support_callback_events",
                    "support_case_agent_assignment_events",
                    "support_case_context_events",
                    "provider_connections",
                    "communication_facts",
                    "entities",
                    "journey_versions",
                    "risk_outputs",
                    "evidence",
                ] + episode_authority_refs,
            ),
            ProjectionSection(
                id="interactions",
                state=(
                    "unknown"
                    if not communication_scope_known
                    else "degraded"
                    if communication_reasons
                    else "ready"
                    if conversation_entries
                    else "empty"
                ),
                content=(
                    {
                        "mode": "metadata_only",
                        "state": slots["conversation_history"]["state"],
                        "entryCount": len(conversation_entries),
                        "bodyState": "suppressed",
                        "historyCoverage": "persisted_support_communication_facts_only",
                        "readCompleteness": slots["conversation_history"].get(
                            "readCompleteness", "unknown"
                        ),
                        "sourceHistoryComplete": False,
                        "freshness": communication_freshness,
                        "entries": conversation_entries,
                        "evidenceRefs": case_communication_evidence,
                        "caseJoinEvidenceRefs": case_join_evidence_refs,
                    }
                    if communication_scope_known
                    else None
                ),
                warnings=communication_reasons or None,
                canonicalAuthorityRefs=["communication_facts"],
            ),
            ProjectionSection(
                id="outcomes",
                state="unknown",
                content=None,
                warnings=[_REASON_SUPPORT_BUSINESS_OUTCOME_MISSING],
                canonicalAuthorityRefs=["outcome_facts", "measurement_contract"],
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
            degradedReasons=case_degraded_reasons,
            page=PageInfo(
                nextCursor=communication_read.next_cursor,
                hasNextPage=communication_read.truncated
                or communication_read.next_cursor is not None,
            ),
        )

    async def _project_callback(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
        *,
        limit: int,
    ) -> ProjectionResult:
        """Resolve a callback ID within tenant scope, then verify its exact case join."""
        try:
            callback_read = await self._callback_repository.get_callback(
                request.tenantId,
                request.subject.id,
                limit=min(limit, 50),
            )
        except Exception:  # noqa: BLE001 - callback authority failure is unknown
            return self._unknown_result(request, context, _REASON_CALLBACK_AUTHORITY_UNAVAILABLE)
        if not isinstance(callback_read, SupportCallbackRead) or not callback_read.available:
            return self._unknown_result(request, context, _REASON_CALLBACK_AUTHORITY_UNAVAILABLE)
        if callback_read.expired:
            return self._unknown_result(request, context, "support_callback_retention_expired")
        record = callback_read.record
        if not isinstance(record, dict):
            return self._unknown_result(request, context, _REASON_CALLBACK_NOT_FOUND)
        if record.get("tenant_id") != request.tenantId or record.get("callback_id") != request.subject.id:
            return self._unknown_result(request, context, _REASON_CALLBACK_SCOPE_MISMATCH)
        case_id = _safe_reference(_text(record.get("case_id")))
        if case_id is None:
            return self._unknown_result(request, context, _REASON_CALLBACK_SCOPE_MISMATCH)
        try:
            case_read = await self._case_repository.get_case(request.tenantId, case_id, limit=100)
        except Exception:  # noqa: BLE001 - case join outage is unknown
            return self._unknown_result(request, context, _REASON_CASE_AUTHORITY_UNAVAILABLE)
        if not isinstance(case_read, SupportCaseAuthorityRead) or not case_read.available:
            return self._unknown_result(request, context, _REASON_CASE_AUTHORITY_UNAVAILABLE)
        if case_read.expired:
            return self._unknown_result(request, context, _REASON_CASE_RETENTION_EXPIRED)
        case_record = case_read.record
        if (
            not isinstance(case_record, dict)
            or case_record.get("tenant_id") != request.tenantId
            or str(case_record.get("case_id")) != case_id
            or case_record.get("source_connection_id") != record.get("source_connection_id")
            or case_record.get("source_provider_identity") != record.get("source_provider_identity")
        ):
            return self._unknown_result(request, context, _REASON_CALLBACK_SCOPE_MISMATCH)

        callback_with_events = dict(record)
        callback_with_events["events"] = callback_read.events
        callback_with_events["events_complete"] = callback_read.complete
        callback_with_events["event_count"] = max(
            len(callback_read.events), int(record.get("event_count") or 0)
        )
        callback_source_read = SupportCallbacksRead(
            [callback_with_events],
            True,
            callback_read.complete,
            not callback_read.complete,
        )
        callback_slot, callback_refs, callback_reasons = _validated_callback_slot(
            callback_source_read,
            tenant_id=request.tenantId,
            case_record=case_record,
        )
        if callback_slot.get("state") == "unknown":
            return self._unknown_result(
                request,
                context,
                (callback_slot.get("reasonCodes") or [_REASON_CALLBACK_EVIDENCE_UNAVAILABLE])[0],
            )

        case_ref = _support_case_record_evidence(case_record)
        if case_ref is None:
            return self._unknown_result(request, context, _REASON_CASE_EVIDENCE_UNAVAILABLE)
        latest_case_event = next(
            (
                event
                for event in case_read.events
                if isinstance(event, dict)
                and event.get("source_event_id") == case_record.get("last_source_event_id")
            ),
            None,
        )
        if not isinstance(latest_case_event, dict):
            return self._unknown_result(request, context, _REASON_CASE_EVIDENCE_UNAVAILABLE)
        case_event_refs = _case_event_evidence_refs(case_record, latest_case_event)
        if not case_event_refs:
            return self._unknown_result(request, context, _REASON_CASE_EVIDENCE_UNAVAILABLE)
        evidence_refs = _dedupe_evidence_refs([case_ref, *case_event_refs, *callback_refs])
        if not evidence_refs:
            return self._unknown_result(request, context, _REASON_CALLBACK_EVIDENCE_UNAVAILABLE)

        callback_entry = (callback_slot.get("callbacks") or [{}])[0]
        case_lifecycle = _safe_reference(_text(case_record.get("lifecycle_state")))
        freshness = {
            "state": "unknown",
            "newestObservedAt": callback_slot.get("freshness", {}).get("newestObservedAt"),
            "reasonCode": _REASON_CALLBACK_FRESHNESS_UNKNOWN,
        }
        case_summary = {
            "canonicalCallbackId": request.subject.id,
            "canonicalCaseId": case_id,
            "callbackState": callback_entry.get("state"),
            "scheduledFor": callback_entry.get("scheduledFor"),
            "sourceProvider": _safe_reference(_text(record.get("source_provider_identity"))),
            "claimState": "observed",
            "freshness": freshness,
            "reasonCodes": callback_reasons,
        }
        slots = _unknown_support_slots(_REASON_CALLBACK_SCOPE_MISMATCH)
        slots["case_summary"] = {
            "state": "degraded",
            "canonicalCaseId": case_id,
            "lifecycleState": case_lifecycle,
            "claimState": "observed",
            "evidenceRefs": [case_ref, *case_event_refs],
            "reasonCodes": ["support_case_source_history_coverage_unverified"],
        }
        slots["callbacks"] = callback_slot
        slots["evidence_trace"] = {
            "state": "degraded",
            "count": len(evidence_refs),
            "evidenceRefs": evidence_refs,
            "reasonCodes": callback_reasons,
        }
        event_entries = callback_entry.get("events", [])
        state_content = {
            "supportCommunications": {
                "state": "unknown",
                "reasonCode": "support_callback_conversation_join_unavailable",
            },
            "supportCases": {
                "state": "observed",
                "canonicalCaseId": case_id,
                "lifecycleState": case_lifecycle,
                "claimState": "observed",
            },
            "journeyLinkage": {"state": "unknown", "reasonCode": _REASON_JOURNEY_JOIN_MISSING},
            "measuredOutcomes": {"state": "unknown", "reasonCode": _REASON_OUTCOME_JOIN_MISSING},
            "requiredSlots": slots,
        }
        claims = [
            ClaimEnvelope(
                id=f"support360.callback.{request.subject.id}.{callback_entry.get('lastSourceEventId')}",
                kind="support_callback_schedule_execution_observation",
                subject=request.subject,
                evidenceRefs=callback_refs,
                claims=[
                    "The tenant-authorized ingress accepted this source-asserted callback schedule or execution event for the exact canonical support case under the verified provider connection."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=["callbacks", "evidence_trace"],
            )
        ]
        warnings = sorted(set(callback_reasons + ["support_case_source_history_coverage_unverified"]))
        canonical_refs = [
            "support_callbacks",
            "support_callback_events",
            "support_cases",
            "support_case_events",
            "provider_connections",
            "evidence",
        ]
        sections = [
            ProjectionSection(
                id="summary",
                state="degraded",
                content=case_summary,
                warnings=warnings,
                canonicalAuthorityRefs=canonical_refs,
            ),
            ProjectionSection(
                id="state",
                state="degraded",
                content=state_content,
                warnings=warnings,
                canonicalAuthorityRefs=canonical_refs,
            ),
            ProjectionSection(
                id="timeline",
                state="degraded",
                content={
                    "order": "source_occurred_at_descending",
                    "causalRelationsDeclared": False,
                    "entryCount": len(event_entries),
                    "entries": event_entries,
                    "callback": callback_entry,
                },
                warnings=warnings,
                canonicalAuthorityRefs=canonical_refs,
            ),
            ProjectionSection(
                id="evidence",
                state="degraded",
                content={
                    "count": len(evidence_refs),
                    "evidenceRefs": evidence_refs,
                    "supportCallbackEvidenceRefs": callback_refs,
                    "supportCaseEvidenceRefs": [case_ref, *case_event_refs],
                },
                warnings=warnings,
                canonicalAuthorityRefs=canonical_refs,
            ),
            ProjectionSection(
                id="interactions",
                state="unknown",
                content=None,
                warnings=["support_callback_conversation_join_unavailable"],
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
            degradedReasons=warnings,
            page=PageInfo(nextCursor=None, hasNextPage=not callback_read.complete),
        )

    async def _case_communication_read(
        self,
        request: ProjectionRequest,
        record: dict[str, Any],
        *,
        limit: int,
        after: Optional[str],
        before: Optional[str],
    ) -> SupportFactsRead:
        """Read communication facts using the case authority's exact source key."""
        connection_id = _safe_reference(_text(record.get("source_connection_id")))
        source_case_id = _safe_reference(_text(record.get("source_case_id")))
        if connection_id is None or source_case_id is None:
            return SupportFactsRead(
                rows=[],
                available=True,
                scope_known=False,
                reason=_REASON_CASE_COMMUNICATION_JOIN_MISSING,
                subject_join="support_case_connection_and_source_case_id_exact_match",
                canonical_authority_refs=(
                    "communication_facts",
                    "provider_connections",
                    "support_cases",
                    "evidence",
                ),
            )
        reader = getattr(self._source, "support_facts_for_case", None)
        if not callable(reader):
            return SupportFactsRead(
                rows=[],
                available=True,
                scope_known=False,
                reason=_REASON_CASE_COMMUNICATION_JOIN_MISSING,
                subject_join="support_case_connection_and_source_case_id_exact_match",
                join_reference_ids=(connection_id,),
                canonical_authority_refs=(
                    "communication_facts",
                    "provider_connections",
                    "support_cases",
                    "evidence",
                ),
            )
        try:
            result = await reader(
                request.tenantId,
                connection_id,
                source_case_id,
                limit=limit,
                after=after,
                before=before,
                cursor=request.page.cursor if request.page is not None else None,
            )
        except Exception:  # noqa: BLE001 - source failure remains typed unknown
            return SupportFactsRead(
                rows=[],
                available=False,
                reason=_REASON_SOURCE_UNAVAILABLE,
                subject_join="support_case_connection_and_source_case_id_exact_match",
                join_reference_ids=(connection_id,),
                canonical_authority_refs=(
                    "communication_facts",
                    "provider_connections",
                    "support_cases",
                    "evidence",
                ),
            )
        if not isinstance(result, SupportFactsRead):
            return SupportFactsRead(
                rows=[],
                available=False,
                reason=_REASON_SOURCE_UNAVAILABLE,
                subject_join="support_case_connection_and_source_case_id_exact_match",
                join_reference_ids=(connection_id,),
                canonical_authority_refs=(
                    "communication_facts",
                    "provider_connections",
                    "support_cases",
                    "evidence",
                ),
            )
        return result

    async def _case_participant_read(
        self,
        tenant_id: str,
        record: dict[str, Any],
        *,
        limit: int,
    ) -> SupportFactsRead:
        """Join Communication360's authenticated roster to this exact support case."""
        connection_id = _safe_reference(_text(record.get("source_connection_id")))
        source_case_id = _safe_reference(_text(record.get("source_case_id")))
        provider_identity = _safe_reference(_text(record.get("source_provider_identity")))
        if not connection_id or not source_case_id or not provider_identity:
            return SupportFactsRead(
                rows=[],
                available=True,
                scope_known=False,
                reason=_REASON_PARTICIPANT_AUTHORITY_MISSING,
                subject_join="support_case_connection_source_case_to_provider_account_conversation_exact_match",
                canonical_authority_refs=("communication_facts", "communication360_facts", "support_cases", "evidence"),
            )
        reader = getattr(self._source, "support_participants_for_case", None)
        if not callable(reader):
            return SupportFactsRead(
                rows=[],
                available=False,
                reason=_REASON_PARTICIPANT_AUTHORITY_UNAVAILABLE,
                subject_join="support_case_connection_source_case_to_provider_account_conversation_exact_match",
                join_reference_ids=(connection_id,),
                canonical_authority_refs=("communication_facts", "communication360_facts", "support_cases", "evidence"),
            )
        try:
            result = await reader(
                tenant_id,
                connection_id,
                source_case_id,
                provider_identity,
                limit=limit,
            )
        except Exception:  # noqa: BLE001 - participant source failure is typed unknown
            return SupportFactsRead(
                rows=[],
                available=False,
                reason=_REASON_PARTICIPANT_AUTHORITY_UNAVAILABLE,
                subject_join="support_case_connection_source_case_to_provider_account_conversation_exact_match",
                join_reference_ids=(connection_id,),
                canonical_authority_refs=("communication_facts", "communication360_facts", "support_cases", "evidence"),
            )
        if not isinstance(result, SupportFactsRead):
            return SupportFactsRead(
                rows=[],
                available=False,
                reason=_REASON_PARTICIPANT_AUTHORITY_UNAVAILABLE,
                subject_join="support_case_connection_source_case_to_provider_account_conversation_exact_match",
                join_reference_ids=(connection_id,),
                canonical_authority_refs=("communication_facts", "communication360_facts", "support_cases", "evidence"),
            )
        return result

    @staticmethod
    def _validated_case_communication_rows(
        read: SupportFactsRead,
        *,
        tenant_id: str,
        record: dict[str, Any],
        after: Optional[str],
        before: Optional[str],
    ) -> tuple[list[dict[str, Any]], bool, list[str]]:
        """Recheck the exact case binding after the communication repository read."""
        if not read.available or not read.scope_known or not isinstance(read.rows, list):
            reason = (
                _REASON_SOURCE_UNAVAILABLE
                if not read.available
                else read.reason
                if read.reason in _SAFE_SUPPORT_READ_REASONS
                else _REASON_CASE_COMMUNICATION_SCOPE_MISMATCH
            )
            return [], False, [reason]
        connection_id = _safe_reference(_text(record.get("source_connection_id")))
        source_case_id = _safe_reference(_text(record.get("source_case_id")))
        raw_rows = [row for row in read.rows if isinstance(row, dict)]
        mismatch = any(
            row.get("tenant_id") != tenant_id
            or _safe_reference(row.get("source_connector_id")) != connection_id
            or _safe_reference(row.get("support_case_id")) != source_case_id
            or _text(row.get("message_category")) != "support"
            for row in raw_rows
        )
        if mismatch:
            return [], False, [_REASON_CASE_COMMUNICATION_SCOPE_MISMATCH]
        rows = [row for row in raw_rows if _row_in_window(row, after=after, before=before)]
        rows.sort(key=lambda row: str(row.get("occurred_at") or ""))
        reasons: list[str] = []
        if read.truncated:
            reasons.append(_REASON_CASE_COMMUNICATION_TRUNCATED)
        if not read.complete:
            reasons.append("support_case_communication_history_scope_incomplete")
        reasons.append(_REASON_CASE_COMMUNICATION_HISTORY_UNVERIFIED)
        return rows, True, reasons

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


async def _validated_agent_assignment_slot(
    read: SupportAgentAssignmentRead,
    *,
    tenant_id: str,
    case_record: dict[str, Any],
    entity_repository: Any,
) -> tuple[dict[str, Any], list[EvidenceRef], list[str]]:
    """Validate exact case/provider, canonical agent identities, and receipts."""
    if not isinstance(read, SupportAgentAssignmentRead) or not read.available or not read.scope_known:
        return (
            {
                "state": "unknown",
                "reasonCode": _REASON_AGENT_ASSIGNMENT_AUTHORITY_UNAVAILABLE,
                "assignmentEvents": None,
            },
            [],
            [_REASON_AGENT_ASSIGNMENT_AUTHORITY_UNAVAILABLE],
        )
    case_id = _safe_reference(_text(case_record.get("case_id")))
    connection_id = _safe_reference(_text(case_record.get("source_connection_id")))
    provider_identity = _safe_reference(_text(case_record.get("source_provider_identity")))
    if (
        case_record.get("tenant_id") != tenant_id
        or case_id is None
        or connection_id is None
        or provider_identity is None
        or not isinstance(read.events, list)
    ):
        reason = _REASON_AGENT_ASSIGNMENT_SCOPE_MISMATCH
        return (
            {"state": "unknown", "reasonCode": reason, "assignmentEvents": None},
            [],
            [reason],
        )

    agent_ids: set[str] = set()
    for event in read.events:
        if not isinstance(event, dict):
            reason = _REASON_AGENT_ASSIGNMENT_SCOPE_MISMATCH
            return (
                {"state": "unknown", "reasonCode": reason, "assignmentEvents": None},
                [],
                [reason],
            )
        if event.get("agent_entity_id"):
            agent_ids.add(str(event["agent_entity_id"]))
        if event.get("previous_agent_entity_id"):
            agent_ids.add(str(event["previous_agent_entity_id"]))

    canonical_agents: dict[str, dict[str, Any]] = {}
    if agent_ids:
        try:
            rows, truncated = await entity_repository.find_many_for_tenant_entity_ids(
                tenant_id,
                sorted(agent_ids),
            )
        except Exception:  # noqa: BLE001 - never infer identity during an authority outage
            reason = _REASON_AGENT_ASSIGNMENT_IDENTITY_UNAVAILABLE
            return (
                {"state": "unknown", "reasonCode": reason, "assignmentEvents": None},
                [],
                [reason],
            )
        for row in rows:
            if (
                isinstance(row, dict)
                and row.get("tenant_id") == tenant_id
                and row.get("entity_type") == "agent"
                and row.get("entity_id") in agent_ids
            ):
                entity_id = str(row["entity_id"])
                if entity_id in canonical_agents:
                    truncated = True
                canonical_agents[entity_id] = row
        if truncated or set(canonical_agents) != agent_ids:
            reason = _REASON_AGENT_ASSIGNMENT_IDENTITY_UNAVAILABLE
            return (
                {"state": "unknown", "reasonCode": reason, "assignmentEvents": None},
                [],
                [reason],
            )

    assignments: list[dict[str, Any]] = []
    all_refs: list[EvidenceRef] = []
    newest_received_at: Optional[str] = None
    for event in read.events:
        if (
            event.get("tenant_id") != tenant_id
            or str(event.get("case_id")) != case_id
            or event.get("source_connection_id") != connection_id
            or event.get("source_provider_identity") != provider_identity
        ):
            reason = _REASON_AGENT_ASSIGNMENT_SCOPE_MISMATCH
            return (
                {"state": "unknown", "reasonCode": reason, "assignmentEvents": None},
                [],
                [reason],
            )
        event_type = _safe_reference(_text(event.get("event_type")))
        assigned_agent_id = _safe_reference(_text(event.get("agent_entity_id")))
        previous_agent_id = _safe_reference(_text(event.get("previous_agent_entity_id")))
        source_assignment_id = _safe_reference(_text(event.get("source_assignment_id")))
        source_revision_id = _safe_reference(_text(event.get("source_revision_id")))
        source_event_id = _safe_reference(_text(event.get("source_event_id")))
        assignment_event_id = _safe_reference(_text(event.get("assignment_event_id")))
        source_observed_at = _utc_timestamp(event.get("source_observed_at"))
        effective_at = _utc_timestamp(event.get("effective_at"))
        received_at = _utc_timestamp(event.get("received_at"))
        valid_shape = (
            event_type == "support_agent_assigned"
            and assigned_agent_id is not None
            and previous_agent_id is None
        ) or (
            event_type == "support_agent_handoff"
            and assigned_agent_id is not None
            and previous_agent_id is not None
            and assigned_agent_id != previous_agent_id
        ) or (
            event_type == "support_agent_unassigned"
            and assigned_agent_id is None
            and previous_agent_id is not None
        )
        required_agents = {value for value in (assigned_agent_id, previous_agent_id) if value}
        if (
            not valid_shape
            or not required_agents.issubset(canonical_agents)
            or not all(
                (source_assignment_id, source_revision_id, source_event_id, assignment_event_id)
            )
            or source_observed_at is None
            or effective_at is None
            or received_at is None
        ):
            reason = _REASON_AGENT_ASSIGNMENT_SCOPE_MISMATCH
            return (
                {"state": "unknown", "reasonCode": reason, "assignmentEvents": None},
                [],
                [reason],
            )
        event_refs = _assignment_event_evidence_refs(
            event,
            tenant_id=tenant_id,
            case_id=case_id,
            connection_id=connection_id,
            provider_identity=provider_identity,
            required_agent_ids=required_agents,
        )
        if not event_refs:
            reason = _REASON_AGENT_ASSIGNMENT_EVIDENCE_UNAVAILABLE
            return (
                {"state": "unknown", "reasonCode": reason, "assignmentEvents": None},
                [],
                [reason],
            )
        all_refs.extend(event_refs)
        observed_at = received_at.isoformat()
        newest_received_at = max(newest_received_at or observed_at, observed_at)
        assignments.append(
            {
                "assignmentEventId": assignment_event_id,
                "sourceAssignmentId": source_assignment_id,
                "sourceRevisionId": source_revision_id,
                "sourceEventId": source_event_id,
                "eventType": event_type,
                "canonicalAgentEntityId": assigned_agent_id,
                "previousCanonicalAgentEntityId": previous_agent_id,
                "assigningPrincipal": {
                    "id": _safe_reference(_text(event.get("assigning_principal_id"))),
                    "kind": _safe_reference(_text(event.get("assigning_principal_type"))),
                },
                "sourceObservedAt": source_observed_at.isoformat(),
                "effectiveAt": effective_at.isoformat(),
                "receivedAt": observed_at,
                "evidenceRefs": event_refs,
            }
        )

    reasons = [_REASON_AGENT_ASSIGNMENT_HISTORY_UNVERIFIED, _REASON_AGENT_ASSIGNMENT_FRESHNESS_UNKNOWN]
    if not read.complete or read.truncated:
        reasons.append(_REASON_AGENT_ASSIGNMENT_READ_TRUNCATED)
    complete = read.complete and not read.truncated
    slot = {
        "state": "degraded",
        "reasonCodes": sorted(set(reasons)),
        "count": len(assignments),
        "assignmentEvents": assignments,
        "readCompleteness": "complete_current_store_read" if complete else "partial",
        "sourceHistoryComplete": False,
        "freshness": {
            "state": "unknown",
            "newestObservedAt": newest_received_at,
            "reasonCode": _REASON_AGENT_ASSIGNMENT_FRESHNESS_UNKNOWN,
        },
        "executionState": "not_joined",
        "outcomeState": "not_joined",
        "evidenceRefs": _dedupe_evidence_refs(all_refs),
    }
    return slot, _dedupe_evidence_refs(all_refs), sorted(set(reasons))


def _assignment_event_evidence_refs(
    event: dict[str, Any],
    *,
    tenant_id: str,
    case_id: str,
    connection_id: str,
    provider_identity: str,
    required_agent_ids: set[str],
) -> list[EvidenceRef]:
    """Require exact source, case, connection, principal, and agent receipts."""
    assignment_event_id = str(event["assignment_event_id"])
    source_assignment_id = str(event["source_assignment_id"])
    source_revision_id = str(event["source_revision_id"])
    source_event_id = str(event["source_event_id"])
    assigning_principal_id = _safe_reference(_text(event.get("assigning_principal_id")))
    assigning_principal_type = _safe_reference(_text(event.get("assigning_principal_type")))
    source_observed_at = _utc_timestamp(event.get("source_observed_at"))
    received_at = _utc_timestamp(event.get("received_at"))
    raw_refs = event.get("evidence_refs")
    if isinstance(raw_refs, str):
        try:
            raw_refs = json.loads(raw_refs)
        except json.JSONDecodeError:
            return []
    if (
        not isinstance(raw_refs, (list, tuple))
        or assigning_principal_id is None
        or assigning_principal_type is None
        or source_observed_at is None
        or received_at is None
    ):
        return []
    expected: dict[str, tuple[str, str, str, str, Optional[datetime]]] = {
        "assignment_event": (
            assignment_event_id,
            "event",
            "support_case_agent_assignment_events",
            "store://support_case_agent_assignment_events/"
            f"{quote(assignment_event_id, safe='')}",
            received_at,
        ),
        "case": (
            case_id,
            "entity",
            "support_cases",
            f"store://support_cases/{quote(case_id, safe='')}",
            None,
        ),
        "connection": (
            connection_id,
            "entity",
            "provider_connections",
            f"store://provider_connections/{quote(connection_id, safe='')}",
            None,
        ),
        "source_event": (
            source_event_id,
            "event",
            provider_identity,
            "provider-event://"
            f"{quote(connection_id, safe='')}/{quote(source_event_id, safe='')}",
            source_observed_at,
        ),
        "source_record": (
            source_assignment_id,
            "event",
            provider_identity,
            "provider-record://"
            f"{quote(connection_id, safe='')}/{quote(source_assignment_id, safe='')}/"
            f"{quote(source_revision_id, safe='')}",
            source_observed_at,
        ),
        "assigning_principal": (
            assigning_principal_id,
            "entity",
            "authenticated_principal",
            f"actor://{quote(assigning_principal_type, safe='')}/"
            f"{quote(assigning_principal_id, safe='')}",
            received_at,
        ),
    }
    for agent_id in required_agent_ids:
        expected[f"agent:{agent_id}"] = (
            agent_id,
            "entity",
            "entities",
            f"store://entities/{quote(agent_id, safe='')}",
            None,
        )
    found: dict[str, EvidenceRef] = {}
    for raw_ref in raw_refs:
        try:
            ref = raw_ref if isinstance(raw_ref, EvidenceRef) else EvidenceRef.model_validate(raw_ref)
        except (TypeError, ValueError):
            continue
        for name, (expected_id, expected_type, expected_source, expected_uri, expected_at) in expected.items():
            if (
                ref.id == expected_id
                and ref.type == expected_type
                and ref.source == expected_source
                and ref.uri == expected_uri
                and (expected_at is None or _utc_timestamp(ref.observedAt) == expected_at)
            ):
                found[name] = ref
    if set(found) != set(expected):
        return []
    return [found[name] for name in expected]


def _validated_support_context_events(
    read: SupportCaseContextRead,
    *,
    kind: str,
    tenant_id: str,
    case_record: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[EvidenceRef], list[str], Optional[str]]:
    """Validate the append-only context ledger's exact case/provider receipts."""
    if not isinstance(read, SupportCaseContextRead) or not read.available:
        reason = (
            _REASON_SLA_AUTHORITY_UNAVAILABLE
            if kind == "sla"
            else _REASON_JOURNEY_AUTHORITY_UNAVAILABLE
        )
        return [], [], [reason], reason
    tenant = _safe_reference(_text(case_record.get("tenant_id")))
    case_id = _safe_reference(_text(case_record.get("case_id")))
    connection_id = _safe_reference(_text(case_record.get("source_connection_id")))
    provider_identity = _safe_reference(_text(case_record.get("source_provider_identity")))
    if (
        tenant != tenant_id
        or case_id is None
        or connection_id is None
        or provider_identity is None
        or not isinstance(read.events, list)
    ):
        reason = _REASON_SLA_SCOPE_MISMATCH if kind == "sla" else _REASON_JOURNEY_SCOPE_MISMATCH
        return [], [], [reason], reason

    validated: list[dict[str, Any]] = []
    all_refs: list[EvidenceRef] = []
    for event in read.events:
        if not isinstance(event, dict):
            reason = _REASON_SLA_SCOPE_MISMATCH if kind == "sla" else _REASON_JOURNEY_SCOPE_MISMATCH
            return [], [], [reason], reason
        payload = event.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = None
        if (
            event.get("tenant_id") != tenant_id
            or str(event.get("case_id")) != case_id
            or event.get("source_connection_id") != connection_id
            or event.get("source_provider_identity") != provider_identity
            or event.get("context_kind") != kind
            or not isinstance(payload, dict)
            or payload.get("case_id") != case_id
            or payload.get("event_type") != event.get("event_type")
            or payload.get("source_event_id") != event.get("source_event_id")
            or payload.get("source_revision_id") != event.get("source_revision_id")
            or not _safe_reference(_text(event.get("actor_id")))
            or not _safe_reference(_text(event.get("actor_type")))
            or _utc_timestamp(event.get("source_observed_at")) is None
            or _utc_timestamp(event.get("effective_at")) is None
            or _utc_timestamp(event.get("received_at")) is None
        ):
            reason = _REASON_SLA_SCOPE_MISMATCH if kind == "sla" else _REASON_JOURNEY_SCOPE_MISMATCH
            return [], [], [reason], reason

        context_event_id = _safe_reference(_text(event.get("context_event_id")))
        source_record_id = _safe_reference(_text(event.get("source_record_id")))
        source_revision_id = _safe_reference(_text(event.get("source_revision_id")))
        source_event_id = _safe_reference(_text(event.get("source_event_id")))
        source_item_id = _safe_reference(_text(event.get("source_item_id")))
        actor_id = _safe_reference(_text(event.get("actor_id")))
        actor_type = _safe_reference(_text(event.get("actor_type")))
        source_observed_at = _utc_timestamp(event.get("source_observed_at"))
        received_at = _utc_timestamp(event.get("received_at"))
        if kind == "sla":
            expected_record = payload.get("source_sla_id")
            expected_item = f"{payload.get('timer_kind')}:{payload.get('event_type')}"
            expected_entity = None
        else:
            expected_record = payload.get("source_link_id")
            expected_item = payload.get("journey_id")
            expected_entity = payload.get("journey_id")
        if (
            context_event_id is None
            or source_record_id is None
            or source_revision_id is None
            or source_event_id is None
            or source_observed_at is None
            or received_at is None
            or source_record_id != expected_record
            or source_item_id != expected_item
            or not actor_id
            or not actor_type
        ):
            reason = _REASON_SLA_SCOPE_MISMATCH if kind == "sla" else _REASON_JOURNEY_SCOPE_MISMATCH
            return [], [], [reason], reason
        refs = _support_context_event_evidence_refs(
            event,
            kind=kind,
            tenant_id=tenant_id,
            case_id=case_id,
            connection_id=connection_id,
            provider_identity=provider_identity,
            context_event_id=context_event_id,
            source_record_id=str(source_record_id),
            source_revision_id=str(source_revision_id),
            source_event_id=str(source_event_id),
            actor_id=str(actor_id),
            actor_type=str(actor_type),
            source_observed_at=source_observed_at,
            received_at=received_at,
            subject_entity_id=str(expected_entity) if expected_entity else None,
        )
        if not refs:
            reason = (
                _REASON_SLA_AUTHORITY_UNAVAILABLE
                if kind == "sla"
                else _REASON_JOURNEY_AUTHORITY_UNAVAILABLE
            )
            return [], [], [reason], reason
        all_refs.extend(refs)
        validated.append(
            {
                "contextEventId": context_event_id,
                "sourceRecordId": source_record_id,
                "sourceRevisionId": source_revision_id,
                "sourceItemId": source_item_id,
                "sourceEventId": source_event_id,
                "eventType": event.get("event_type"),
                "sourceObservedAt": source_observed_at.isoformat(),
                "effectiveAt": _utc_timestamp(event.get("effective_at")).isoformat(),
                "receivedAt": received_at.isoformat(),
                "actor": {"id": actor_id, "type": actor_type},
                "payload": payload,
                "evidenceRefs": refs,
            }
        )
    return validated, _dedupe_evidence_refs(all_refs), [], None


def _support_context_event_evidence_refs(
    event: dict[str, Any],
    *,
    kind: str,
    tenant_id: str,
    case_id: str,
    connection_id: str,
    provider_identity: str,
    context_event_id: str,
    source_record_id: str,
    source_revision_id: str,
    source_event_id: str,
    actor_id: str,
    actor_type: str,
    source_observed_at: datetime,
    received_at: datetime,
    subject_entity_id: Optional[str],
) -> list[EvidenceRef]:
    raw_refs = event.get("evidence_refs")
    if isinstance(raw_refs, str):
        try:
            raw_refs = json.loads(raw_refs)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw_refs, (list, tuple)):
        return []
    expected: dict[str, tuple[str, str, str, str, Optional[datetime]]] = {
        "context_event": (
            context_event_id, "event", "support_case_context_events",
            f"store://support_case_context_events/{quote(context_event_id, safe='')}", received_at,
        ),
        "case": (
            case_id, "entity", "support_cases",
            f"store://support_cases/{quote(case_id, safe='')}", None,
        ),
        "connection": (
            connection_id, "entity", "provider_connections",
            f"store://provider_connections/{quote(connection_id, safe='')}", None,
        ),
        "source_event": (
            source_event_id, "event", provider_identity,
            f"provider-event://{quote(connection_id, safe='')}/{quote(source_event_id, safe='')}",
            source_observed_at,
        ),
        "source_record": (
            source_record_id, "event", provider_identity,
            f"provider-record://{quote(connection_id, safe='')}/{quote(source_record_id, safe='')}/"
            f"{quote(str(event.get('source_revision_id') or ''), safe='')}",
            source_observed_at,
        ),
        "actor": (
            actor_id, "entity", "authenticated_principal",
            f"actor://{quote(actor_type, safe='')}/{quote(actor_id, safe='')}", received_at,
        ),
    }
    if kind == "journey_links" and subject_entity_id:
        expected["journey"] = (
            subject_entity_id, "entity", "journey_versions",
            f"store://journey_versions/{quote(subject_entity_id, safe='')}", None,
        )
    found: dict[str, EvidenceRef] = {}
    for raw_ref in raw_refs:
        try:
            ref = raw_ref if isinstance(raw_ref, EvidenceRef) else EvidenceRef.model_validate(raw_ref)
        except (TypeError, ValueError):
            continue
        for name, (expected_id, expected_type, expected_source, expected_uri, expected_at) in expected.items():
            if (
                ref.id == expected_id
                and ref.type == expected_type
                and ref.source == expected_source
                and ref.uri == expected_uri
                and (expected_at is None or _utc_timestamp(ref.observedAt) == expected_at)
            ):
                found[name] = ref
    return [found[name] for name in expected] if set(found) == set(expected) else []


async def _validated_canonical_support_participant_slot(
    read: SupportFactsRead,
    *,
    tenant_id: str,
    case_record: dict[str, Any],
    entity_repository: Any,
) -> tuple[dict[str, Any], list[EvidenceRef], list[str]]:
    if not isinstance(read, SupportFactsRead) or not read.available or not read.scope_known:
        reason = (
            _REASON_PARTICIPANT_AUTHORITY_UNAVAILABLE
            if not isinstance(read, SupportFactsRead) or not read.available
            else read.reason
            if read.reason in {
                _REASON_PARTICIPANT_AUTHORITY_MISSING,
                _REASON_CASE_COMMUNICATION_JOIN_MISSING,
                _REASON_CASE_COMMUNICATION_SCOPE_MISMATCH,
            }
            else _REASON_PARTICIPANT_SCOPE_MISMATCH
        )
        return {"state": "unknown", "reasonCode": reason, "participants": None}, [], [reason]

    connection_id = _safe_reference(_text(case_record.get("source_connection_id")))
    provider_identity = _safe_reference(_text(case_record.get("source_provider_identity")))
    if (
        case_record.get("tenant_id") != tenant_id
        or not connection_id
        or not provider_identity
        or read.subject_join
        != "support_case_connection_source_case_to_provider_account_conversation_exact_match"
        or not read.conversation_scopes
        or any(provider != provider_identity for provider, _, _ in read.conversation_scopes)
    ):
        reason = _REASON_PARTICIPANT_SCOPE_MISMATCH
        return {"state": "unknown", "reasonCode": reason, "participants": None}, [], [reason]

    from journeys.communication360.contracts import CommunicationParticipantRole
    from journeys.communication360.provider import _trusted_participant_source_evidence

    expected_scopes = set(read.conversation_scopes)
    validated: list[dict[str, Any]] = []
    evidence_refs = list(read.join_evidence_refs)
    entity_ids: set[str] = set()
    role_values = {role.value for role in CommunicationParticipantRole}
    for row in read.rows:
        payload = row.get("payload") if isinstance(row, dict) else None
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = None
        if (
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or row.get("kind") != "participant_binding"
            or not isinstance(payload, dict)
        ):
            reason = _REASON_PARTICIPANT_SCOPE_MISMATCH
            return {"state": "unknown", "reasonCode": reason, "participants": None}, [], [reason]
        provider = _safe_reference(_text(payload.get("provider")))
        account_id = _safe_reference(_text(payload.get("provider_account_id")))
        conversation_id = _safe_reference(_text(payload.get("provider_conversation_id")))
        entity_id = _safe_reference(_text(payload.get("entity_id")))
        source_identity = payload.get("source_identity")
        actor = payload.get("actor_attribution")
        occurred_at = _utc_timestamp(row.get("occurred_at"))
        roster_id = _safe_reference(_text(payload.get("roster_id")))
        binding_id = _safe_reference(_text(payload.get("binding_id")))
        source_event_id = _safe_reference(_text(row.get("source_event_id")))
        source_evidence = _trusted_participant_source_evidence(row)
        if (
            provider != provider_identity
            or account_id is None
            or conversation_id is None
            or (provider, account_id, conversation_id) not in expected_scopes
            or payload.get("communication_scope_kind") != "provider_conversation"
            or payload.get("communication_scope") != conversation_id
            or entity_id is None
            or not isinstance(source_identity, dict)
            or source_identity.get("resolution_status") != "resolved"
            or not _safe_reference(_text(source_identity.get("identity_binding_id")))
            or payload.get("claim_state") != "observed"
            or payload.get("role") not in role_values
            or not roster_id
            or not binding_id
            or not source_event_id
            or occurred_at is None
            or not isinstance(actor, dict)
            or actor.get("actor_id") != row.get("actor_id")
            or not source_evidence
        ):
            reason = _REASON_PARTICIPANT_SCOPE_MISMATCH
            return {"state": "unknown", "reasonCode": reason, "participants": None}, [], [reason]
        for key in ("valid_from", "valid_to"):
            if payload.get(key) is not None and _utc_timestamp(payload.get(key)) is None:
                reason = _REASON_PARTICIPANT_SCOPE_MISMATCH
                return {"state": "unknown", "reasonCode": reason, "participants": None}, [], [reason]
        entity_ids.add(entity_id)
        store_ref = _row_evidence(row)
        if store_ref is None:
            reason = _REASON_PARTICIPANT_AUTHORITY_UNAVAILABLE
            return {"state": "unknown", "reasonCode": reason, "participants": None}, [], [reason]
        row_refs = _dedupe_evidence_refs([store_ref, *source_evidence])
        evidence_refs.extend(row_refs)
        validated.append(
            {
                "row": row,
                "payload": payload,
                "entityId": entity_id,
                "provider": provider,
                "providerAccountId": account_id,
                "providerConversationId": conversation_id,
                "sourceEventId": source_event_id,
                "occurredAt": occurred_at.isoformat(),
                "evidenceRefs": row_refs,
            }
        )

    canonical_entities: dict[str, dict[str, Any]] = {}
    if entity_ids:
        try:
            entity_rows, truncated = await entity_repository.find_many_for_tenant_entity_ids(
                tenant_id, sorted(entity_ids)
            )
        except Exception:  # noqa: BLE001 - identity is never guessed
            reason = _REASON_PARTICIPANT_IDENTITY_UNAVAILABLE
            return {"state": "unknown", "reasonCode": reason, "participants": None}, [], [reason]
        for entity in entity_rows:
            if (
                isinstance(entity, dict)
                and entity.get("tenant_id") == tenant_id
                and entity.get("entity_id") in entity_ids
            ):
                canonical_entities[str(entity["entity_id"])] = entity
        if truncated or set(canonical_entities) != entity_ids:
            reason = _REASON_PARTICIPANT_IDENTITY_UNAVAILABLE
            return {"state": "unknown", "reasonCode": reason, "participants": None}, [], [reason]
    participants = [
        {
            "canonicalEntityId": item["entityId"],
            "entityType": canonical_entities[item["entityId"]].get("entity_type"),
            "providerAccountId": item["providerAccountId"],
            "providerConversationId": item["providerConversationId"],
            "sourceRosterId": item["payload"]["roster_id"],
            "sourceBindingId": item["payload"]["binding_id"],
            "sourceEventId": item["sourceEventId"],
            "role": item["payload"]["role"],
            "sourceRosterState": item["payload"].get("roster_completeness_state", "unknown"),
            "sourceExpectedBindingCount": item["payload"].get("roster_expected_binding_count"),
            "sourceObservedBindingCount": item["payload"].get("roster_binding_count"),
            "occurredAt": item["occurredAt"],
            "validFrom": item["payload"].get("valid_from"),
            "validTo": item["payload"].get("valid_to"),
            "claimState": "observed",
            "evidenceRefs": item["evidenceRefs"],
        }
        for item in validated
    ]
    reasons = [_REASON_PARTICIPANT_HISTORY_UNVERIFIED]
    if not read.complete or read.truncated:
        reasons.append("support_case_participant_read_truncated_or_incomplete")
    if read.reason:
        reasons.append("support_case_participant_conversation_join_incomplete")
    if not validated:
        reasons.append("communication360_participant_roster_not_observed_for_case_conversations")
    state = "empty" if not validated and read.complete else "degraded"
    refs = _dedupe_evidence_refs(evidence_refs)
    return (
        {
            "state": state,
            "reasonCodes": reasons,
            "participants": participants,
            "sourceAuthority": "communication360_facts",
            "sourceAuthenticationState": "tenant_webhook_hmac_verified",
            "caseConversationJoin": read.subject_join,
            "caseConversationScopes": [
                {
                    "provider": provider,
                    "providerAccountId": account,
                    "providerConversationId": conversation,
                }
                for provider, account, conversation in read.conversation_scopes
            ],
            "sourceHistoryComplete": False,
            "freshness": {
                "state": "unknown",
                "reasonCode": "support_case_participant_freshness_sla_unavailable",
            },
            "caseJoinEvidenceRefs": list(read.join_evidence_refs),
            "evidenceRefs": refs,
        },
        refs,
        reasons,
    )


def _validated_support_sla_slot(
    read: SupportCaseContextRead,
    *,
    tenant_id: str,
    case_record: dict[str, Any],
) -> tuple[dict[str, Any], list[EvidenceRef], list[str]]:
    rows, refs, reasons, failure = _validated_support_context_events(
        read, kind="sla", tenant_id=tenant_id, case_record=case_record
    )
    if failure:
        return {"state": "unknown", "reasonCode": failure, "events": None}, [], reasons
    latest_timers: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        payload = row["payload"]
        key = (str(payload["source_sla_id"]), str(payload["timer_kind"]))
        prior = latest_timers.get(key)
        if prior is None or (row["effectiveAt"], row["receivedAt"]) > (
            prior["effectiveAt"], prior["receivedAt"]
        ):
            latest_timers[key] = row
    timers = [
        {
            "sourceSlaId": row["payload"]["source_sla_id"],
            "sourceRevisionId": row["payload"]["source_revision_id"],
            "timerKind": row["payload"]["timer_kind"],
            "customTimerName": row["payload"].get("custom_timer_name"),
            "sourcePolicyId": row["payload"]["source_policy_id"],
            "sourcePolicyVersion": row["payload"]["source_policy_version"],
            "eventType": row["eventType"],
            "sourceTimerState": row["payload"].get("source_timer_state"),
            "targetDurationSeconds": row["payload"].get("target_duration_seconds"),
            "dueAt": row["payload"].get("due_at"),
            "effectiveAt": row["effectiveAt"],
            "claimState": "observed",
            "evidenceRefs": row["evidenceRefs"],
        }
        for row in latest_timers.values()
    ]
    reasons = [_REASON_SLA_HISTORY_UNVERIFIED]
    if not rows:
        state = "empty"
    else:
        state = "degraded"
        reasons.extend(
            [
                _REASON_SLA_POLICY_NOT_CANONICAL,
                _REASON_CONTEXT_SOURCE_AUTHENTICATION_UNVERIFIED,
                "support_case_sla_freshness_sla_unavailable",
            ]
        )
    if not read.complete or read.truncated:
        reasons.append("support_case_context_read_truncated")
    return (
        {
            "state": state,
            "reasonCodes": reasons,
            "timers": timers,
            "events": rows,
            "policyAuthority": "source_reported_not_joined_to_measurement_contract",
            "sourceAuthenticationState": "tenant_authorized_principal_only",
            "sourceHistoryComplete": False,
            "freshness": {"state": "unknown", "reasonCode": "support_case_sla_freshness_sla_unavailable"},
            "breachEvaluation": "source_reported_only_no_local_timer_inference",
            "evidenceRefs": refs,
        },
        refs,
        reasons,
    )


async def _validated_support_journey_link_slot(
    read: SupportCaseContextRead,
    *,
    tenant_id: str,
    case_record: dict[str, Any],
    journey_repository: Any,
) -> tuple[dict[str, Any], list[EvidenceRef], list[str]]:
    rows, refs, reasons, failure = _validated_support_context_events(
        read, kind="journey_links", tenant_id=tenant_id, case_record=case_record
    )
    if failure:
        return {"state": "unknown", "reasonCode": failure, "links": None}, [], reasons
    if journey_repository is None:
        from journeys.measurement.repositories.journey_repo import JourneyRepository
        journey_repository = JourneyRepository()
    current_journeys: dict[str, dict[str, Any]] = {}
    try:
        for journey_id in sorted({str(row["payload"]["journey_id"]) for row in rows}):
            journey = await journey_repository.get_current(tenant_id, journey_id)
            if (
                isinstance(journey, dict)
                and journey.get("tenant_id") == tenant_id
                and str(journey.get("journey_id")) == journey_id
                and journey.get("is_current") is True
            ):
                current_journeys[journey_id] = journey
    except Exception:  # noqa: BLE001 - no journey identity inference
        reason = _REASON_JOURNEY_AUTHORITY_UNAVAILABLE
        return {"state": "unknown", "reasonCode": reason, "links": None}, [], [reason]
    if len(current_journeys) < len({str(row["payload"]["journey_id"]) for row in rows}):
        reason = _REASON_JOURNEY_AUTHORITY_UNAVAILABLE
        return {"state": "unknown", "reasonCode": reason, "links": None}, [], [reason]
    latest_by_link: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row["payload"]["source_link_id"])
        prior = latest_by_link.get(key)
        if prior is None or (row["effectiveAt"], row["receivedAt"]) > (
            prior["effectiveAt"], prior["receivedAt"]
        ):
            latest_by_link[key] = row
    active = [
        {
            "canonicalJourneyId": row["payload"]["journey_id"],
            "contextEventId": row["contextEventId"],
            "journeyVersionId": current_journeys[str(row["payload"]["journey_id"])].get("journey_version_id"),
            "journeyState": current_journeys[str(row["payload"]["journey_id"])].get("journey_state"),
            "sourceLinkId": row["payload"]["source_link_id"],
            "sourceRevisionId": row["payload"]["source_revision_id"],
            "eventType": row["eventType"],
            "effectiveAt": row["effectiveAt"],
            "claimState": "observed",
            "evidenceRefs": row["evidenceRefs"],
        }
        for row in latest_by_link.values()
        if row["eventType"] == "support_case_journey_linked"
    ]
    reasons = (
        []
        if not rows
        else [
            _REASON_JOURNEY_HISTORY_UNVERIFIED,
            _REASON_CONTEXT_SOURCE_AUTHENTICATION_UNVERIFIED,
        ]
    )
    if not read.complete or read.truncated:
        reasons.append("support_case_context_read_truncated")
    return (
        {
            "state": "empty" if not active else "degraded",
            "reasonCodes": reasons,
            "links": active,
            "events": rows,
            "sourceAuthenticationState": "tenant_authorized_principal_only",
            "sourceHistoryComplete": False,
            "evidenceRefs": refs,
        },
        refs,
        reasons,
    )


async def _validated_case_journey_episodes(
    *,
    tenant_id: str,
    links: list[dict[str, Any]],
    episode_store: Any,
    windowed: bool,
) -> tuple[dict[str, Any], list[EvidenceRef], list[str]]:
    """Join only EpisodeRecords explicitly citing an exact case journey-link event.

    Journey ID alone is shared by many cases and episodes. The verified context
    event is the case-specific bridge; the episode must cite that exact event
    and independently carry the same canonical journey ID. This bounded tenant
    scan does not establish the complete episode population.
    """
    if windowed:
        reason = _REASON_JOURNEY_EPISODE_TEMPORAL_UNAVAILABLE
        return {"state": "unknown", "reasonCode": reason, "relations": None}, [], [reason]
    try:
        if episode_store is None:
            from shared.backend_interpretation.stores import EpisodeStore

            episode_store = EpisodeStore()
        page = await episode_store.list_page_by_tenant(tenant_id, limit=100)
    except Exception:  # noqa: BLE001 - no episode relation inference on source failure
        reason = _REASON_JOURNEY_EPISODE_AUTHORITY_UNAVAILABLE
        return {"state": "unknown", "reasonCode": reason, "relations": None}, [], [reason]

    expected: dict[tuple[str, str], EvidenceRef] = {}
    for link in links:
        journey_id = _safe_reference(link.get("canonicalJourneyId"))
        context_event_id = _safe_reference(link.get("contextEventId"))
        if journey_id is None or context_event_id is None:
            continue
        expected_uri = f"store://support_case_context_events/{quote(context_event_id, safe='')}"
        for ref in link.get("evidenceRefs", []):
            if (
                isinstance(ref, EvidenceRef)
                and ref.id == context_event_id
                and ref.type == "event"
                and ref.source == "support_case_context_events"
                and ref.uri == expected_uri
                and _utc_timestamp(ref.observedAt) is not None
            ):
                expected[(journey_id, context_event_id)] = ref
                break

    relations: list[dict[str, Any]] = []
    refs: list[EvidenceRef] = []
    seen: set[tuple[str, str]] = set()
    for episode in page.records:
        if (
            not isinstance(episode, EpisodeRecord)
            or episode.tenant_id != tenant_id
            or not _safe_reference(episode.episode_id)
            or not _safe_reference(episode.journey_id)
        ):
            continue
        episode_ref = _episode_evidence(episode)
        if episode_ref is None:
            continue
        for (journey_id, context_event_id), context_ref in expected.items():
            key = (episode.episode_id, context_event_id)
            if key in seen or episode.journey_id != journey_id:
                continue
            if not any(
                ref.id == context_ref.id
                and ref.type == context_ref.type
                and ref.source == context_ref.source
                and ref.uri == context_ref.uri
                and _utc_timestamp(ref.observedAt) == _utc_timestamp(context_ref.observedAt)
                for ref in episode.evidence_refs
            ):
                continue
            seen.add(key)
            relation_refs = [episode_ref, context_ref]
            refs.extend(relation_refs)
            relations.append(
                {
                    "canonicalEpisodeId": episode.episode_id,
                    "canonicalJourneyId": journey_id,
                    "contextEventId": context_event_id,
                    "subjectJoin": "episode_explicit_journey_and_case_context_event_evidence_exact_match",
                    "evidenceRefs": relation_refs,
                }
            )

    relations.sort(key=lambda relation: (relation["contextEventId"], relation["canonicalEpisodeId"]))
    reasons = [
        _REASON_JOURNEY_EPISODE_POPULATION_UNVERIFIED,
        _REASON_JOURNEY_EPISODE_FRESHNESS_UNKNOWN,
        _REASON_JOURNEY_EPISODE_POLICY_UNVERIFIED,
    ]
    if not relations:
        reasons.append(_REASON_JOURNEY_EPISODE_RELATION_MISSING)
    if page.truncated or page.next_cursor or page.invalid_records:
        reasons.append(_REASON_JOURNEY_EPISODE_READ_TRUNCATED)
    return (
        {
            "state": "degraded" if relations else "unknown",
            "reasonCodes": reasons,
            "relations": relations,
            "sourceHistoryComplete": False,
            "populationComplete": False,
            "temporalState": "current_store_only",
            "policy": {"state": "unknown", "reasonCode": _REASON_JOURNEY_EPISODE_POLICY_UNVERIFIED},
            "freshness": {"state": "unknown", "reasonCode": _REASON_JOURNEY_EPISODE_FRESHNESS_UNKNOWN},
            "evidenceRefs": _dedupe_evidence_refs(refs),
        },
        _dedupe_evidence_refs(refs),
        reasons,
    )


def _validated_callback_slot(
    read: SupportCallbacksRead,
    *,
    tenant_id: str,
    case_record: dict[str, Any],
) -> tuple[dict[str, Any], list[EvidenceRef], list[str]]:
    """Recheck exact callback, case, connection, provider, and event evidence."""
    if not isinstance(read, SupportCallbacksRead) or not read.available or not read.scope_known:
        reason = (
            _REASON_CALLBACK_AUTHORITY_UNAVAILABLE
            if not isinstance(read, SupportCallbacksRead) or not read.available
            else _REASON_CALLBACK_SCOPE_MISMATCH
        )
        return (
            {"state": "unknown", "reasonCode": reason, "reasonCodes": [reason], "callbacks": None},
            [],
            [reason],
        )
    case_id = _safe_reference(_text(case_record.get("case_id")))
    connection_id = _safe_reference(_text(case_record.get("source_connection_id")))
    provider_identity = _safe_reference(_text(case_record.get("source_provider_identity")))
    if case_record.get("tenant_id") != tenant_id or not case_id or not connection_id or not provider_identity:
        reason = _REASON_CALLBACK_SCOPE_MISMATCH
        return ({"state": "unknown", "reasonCode": reason, "reasonCodes": [reason], "callbacks": None}, [], [reason])

    callbacks: list[dict[str, Any]] = []
    all_refs: list[EvidenceRef] = []
    newest_observed_at: Optional[str] = None
    if not isinstance(read.callbacks, list):
        reason = _REASON_CALLBACK_SCOPE_MISMATCH
        return ({"state": "unknown", "reasonCode": reason, "reasonCodes": [reason], "callbacks": None}, [], [reason])

    for callback in read.callbacks:
        if not isinstance(callback, dict):
            reason = _REASON_CALLBACK_SCOPE_MISMATCH
            return ({"state": "unknown", "reasonCode": reason, "reasonCodes": [reason], "callbacks": None}, [], [reason])
        callback_id = _safe_reference(_text(callback.get("callback_id")))
        state = _safe_reference(_text(callback.get("callback_state")))
        scheduled_for = _utc_timestamp(callback.get("scheduled_for"))
        last_source_event_id = _safe_reference(_text(callback.get("last_source_event_id")))
        if (
            callback.get("tenant_id") != tenant_id
            or str(callback.get("case_id")) != case_id
            or callback.get("source_connection_id") != connection_id
            or callback.get("source_provider_identity") != provider_identity
            or callback_id is None
            or state not in {"scheduled", "attempted", "completed", "failed", "cancelled"}
            or scheduled_for is None
            or last_source_event_id is None
            or not isinstance(callback.get("events"), list)
        ):
            reason = _REASON_CALLBACK_SCOPE_MISMATCH
            return ({"state": "unknown", "reasonCode": reason, "reasonCodes": [reason], "callbacks": None}, [], [reason])

        event_entries: list[dict[str, Any]] = []
        callback_refs: list[EvidenceRef] = []
        latest_event_found = False
        for event in callback["events"]:
            if not isinstance(event, dict):
                reason = _REASON_CALLBACK_SCOPE_MISMATCH
                return ({"state": "unknown", "reasonCode": reason, "reasonCodes": [reason], "callbacks": None}, [], [reason])
            event_id = _safe_reference(_text(event.get("source_event_id")))
            event_type = _safe_reference(_text(event.get("event_type")))
            occurred_at = _utc_timestamp(event.get("source_occurred_at"))
            received_at = _utc_timestamp(event.get("received_at"))
            event_callback_id = _safe_reference(_text(event.get("callback_id")))
            case_source_event_id = _safe_reference(_text(event.get("case_source_event_id")))
            if (
                event.get("tenant_id") != tenant_id
                or str(event.get("case_id")) != case_id
                or event.get("source_connection_id") != connection_id
                or event_callback_id != callback_id
                or event_id is None
                or event_type is None
                or occurred_at is None
                or received_at is None
                or case_source_event_id is None
                or event_type
                not in {
                    "support_callback_scheduled",
                    "support_callback_rescheduled",
                    "support_callback_attempted",
                    "support_callback_completed",
                    "support_callback_failed",
                    "support_callback_cancelled",
                }
            ):
                reason = _REASON_CALLBACK_SCOPE_MISMATCH
                return ({"state": "unknown", "reasonCode": reason, "reasonCodes": [reason], "callbacks": None}, [], [reason])
            if event.get("source_provider_identity") not in {None, provider_identity}:
                reason = _REASON_CALLBACK_SCOPE_MISMATCH
                return ({"state": "unknown", "reasonCode": reason, "reasonCodes": [reason], "callbacks": None}, [], [reason])
            refs = _callback_event_evidence_refs(
                event,
                callback_id=callback_id,
                case_id=case_id,
                connection_id=connection_id,
                provider_identity=provider_identity,
            )
            if not refs:
                reason = _REASON_CALLBACK_EVIDENCE_UNAVAILABLE
                return ({"state": "unknown", "reasonCode": reason, "reasonCodes": [reason], "callbacks": None}, [], [reason])
            if event_id == last_source_event_id and event.get("state_applied") is True:
                latest_event_found = True
            if newest_observed_at is None or received_at.isoformat() > newest_observed_at:
                newest_observed_at = received_at.isoformat()
            callback_refs.extend(refs)
            event_entries.append(
                {
                    "eventType": event_type,
                    "occurredAt": occurred_at.isoformat(),
                    "receivedAt": received_at.isoformat(),
                    "scheduledFor": (
                        _utc_timestamp(event.get("scheduled_for")).isoformat()
                        if event.get("scheduled_for") is not None
                        and _utc_timestamp(event.get("scheduled_for")) is not None
                        else None
                    ),
                    "stateApplied": event.get("state_applied") is True,
                    "sourceEventId": event_id,
                    "evidenceRefs": refs,
                }
            )
        if not latest_event_found:
            reason = _REASON_CALLBACK_EVIDENCE_UNAVAILABLE
            return ({"state": "unknown", "reasonCode": reason, "reasonCodes": [reason], "callbacks": None}, [], [reason])
        if not callback_refs:
            reason = _REASON_CALLBACK_EVIDENCE_UNAVAILABLE
            return ({"state": "unknown", "reasonCode": reason, "reasonCodes": [reason], "callbacks": None}, [], [reason])
        callback_refs = _dedupe_evidence_refs(callback_refs)
        all_refs.extend(callback_refs)
        callbacks.append(
            {
                "callbackId": callback_id,
                "canonicalCaseId": case_id,
                "state": state,
                "scheduledFor": scheduled_for.isoformat(),
                "lastSourceEventId": last_source_event_id,
                "lastObservedAt": _safe_reference(_text(callback.get("last_observed_at"))),
                "eventCount": int(callback.get("event_count") or len(event_entries)),
                "eventsComplete": callback.get("events_complete") is True,
                "events": event_entries,
                "evidenceRefs": callback_refs,
            }
        )

    reasons = [_REASON_CALLBACK_SOURCE_HISTORY_UNVERIFIED, _REASON_CALLBACK_FRESHNESS_UNKNOWN]
    events_complete = all(callback.get("eventsComplete") is True for callback in callbacks)
    if not read.complete or read.truncated or not events_complete:
        reasons.append(_REASON_CALLBACK_HISTORY_PARTIAL)
    complete = read.complete and not read.truncated and events_complete
    slot_state = "empty" if not callbacks and complete else "degraded"
    slot = {
        "state": slot_state,
        "reasonCodes": sorted(set(reasons)),
        "count": len(callbacks),
        "callbacks": callbacks,
        "readCompleteness": "complete_current_store_read" if complete else "partial",
        "sourceHistoryComplete": False,
        "freshness": {
            "state": "unknown",
            "newestObservedAt": newest_observed_at,
            "reasonCode": _REASON_CALLBACK_FRESHNESS_UNKNOWN,
        },
        "evidenceRefs": _dedupe_evidence_refs(all_refs),
    }
    return slot, _dedupe_evidence_refs(all_refs), sorted(set(reasons))


def _callback_event_evidence_refs(
    event: dict[str, Any],
    *,
    callback_id: str,
    case_id: str,
    connection_id: str,
    provider_identity: str,
) -> list[EvidenceRef]:
    """Validate the persisted source receipts for one exact callback event."""
    source_event_id = _safe_reference(_text(event.get("source_event_id")))
    case_source_event_id = _safe_reference(_text(event.get("case_source_event_id")))
    event_at = _utc_timestamp(event.get("source_occurred_at"))
    raw_refs = event.get("evidence_refs")
    if isinstance(raw_refs, str):
        try:
            raw_refs = json.loads(raw_refs)
        except json.JSONDecodeError:
            return []
    if (
        source_event_id is None
        or case_source_event_id is None
        or event_at is None
        or not isinstance(raw_refs, (list, tuple))
    ):
        return []
    expected = {
        "callback": (callback_id, "entity", "support_callbacks", f"store://support_callbacks/{quote(callback_id, safe='')}", None),
        "case": (case_id, "entity", "support_cases", f"store://support_cases/{quote(case_id, safe='')}", None),
        "case_event": (
            case_source_event_id,
            "event",
            provider_identity,
            "provider-event://"
            f"{quote(connection_id, safe='')}/{quote(case_source_event_id, safe='')}",
            None,
        ),
        "event": (
            source_event_id,
            "event",
            provider_identity,
            "provider-event://"
            f"{quote(connection_id, safe='')}/{quote(source_event_id, safe='')}",
            event_at,
        ),
        "connection": (
            connection_id,
            "entity",
            "provider_connections",
            f"store://provider_connections/{quote(connection_id, safe='')}",
            None,
        ),
    }
    found: dict[str, EvidenceRef] = {}
    for raw_ref in raw_refs:
        try:
            ref = raw_ref if isinstance(raw_ref, EvidenceRef) else EvidenceRef.model_validate(raw_ref)
        except (TypeError, ValueError):
            continue
        for name, (expected_id, expected_type, expected_source, expected_uri, expected_at) in expected.items():
            if (
                ref.id == expected_id
                and ref.type == expected_type
                and ref.source == expected_source
                and ref.uri == expected_uri
                and (expected_at is None or _utc_timestamp(ref.observedAt) == expected_at)
            ):
                found[name] = ref
    if set(found) != set(expected):
        return []
    return [found[name] for name in ("callback", "case", "case_event", "event", "connection")]


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


def _support_case_record_evidence(record: dict[str, Any]) -> Optional[EvidenceRef]:
    """Reference the exact canonical SupportCase row that resolved this subject."""
    case_id = _safe_reference(_text(record.get("case_id")))
    if case_id is None:
        return None
    return EvidenceRef(
        id=case_id,
        type="entity",
        source="support_cases",
        observedAt=_safe_reference(_text(record.get("last_observed_at"))),
        uri=f"store://support_cases/{quote(case_id, safe='')}",
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
    """Expose current lifecycle state and explicit resolution observations."""
    lifecycle_state = _safe_reference(_text(record.get("lifecycle_state")))
    if lifecycle_state not in {"open", "pending", "escalated", "resolved", "closed"}:
        return None

    connection_id = _safe_reference(_text(record.get("source_connection_id")))
    provider_identity = _safe_reference(_text(record.get("source_provider_identity")))
    if connection_id is None or provider_identity is None:
        return None
    if lifecycle_state not in {"resolved", "closed"}:
        lifecycle_at = _utc_timestamp(record.get("lifecycle_observed_at"))
        last_event_id = _safe_reference(_text(record.get("last_source_event_id")))
        if lifecycle_at is None or last_event_id is None:
            return None
        exact_evidence = []
        for event in events:
            if (
                _safe_reference(_text(event.get("source_event_id"))) == last_event_id
                and event.get("lifecycle_applied") is True
                and _utc_timestamp(event.get("source_occurred_at")) == lifecycle_at
            ):
                exact_evidence.extend(_case_event_evidence_refs(record, event))
        evidence_refs = _dedupe_evidence_refs(exact_evidence)
        if not evidence_refs:
            return None
        return {
            "state": "observed",
            "resolutionState": lifecycle_state,
            "resolutionOccurred": False,
            "claimState": "observed",
            "sourceOccurredAt": lifecycle_at.isoformat(),
            "evidenceRefs": evidence_refs,
            "businessOutcomeState": "unknown",
            "businessOutcomeReasonCode": _REASON_SUPPORT_BUSINESS_OUTCOME_MISSING,
        }

    event_type = "support_case_resolved" if lifecycle_state == "resolved" else "support_case_closed"
    timestamp_field = "resolved_at" if lifecycle_state == "resolved" else "closed_at"
    resolution_at = _utc_timestamp(record.get(timestamp_field))
    if resolution_at is None:
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
        "resolutionOccurred": True,
        "claimState": "observed",
        "sourceOccurredAt": resolution_at.isoformat(),
        "evidenceRefs": evidence_refs,
        "reasonCode": _REASON_SUPPORT_BUSINESS_OUTCOME_MISSING,
        "businessOutcomeState": "unknown",
        "businessOutcomeReasonCode": _REASON_SUPPORT_BUSINESS_OUTCOME_MISSING,
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


def _case_communication_timeline_entry(
    row: dict[str, Any],
    evidence_ref: EvidenceRef,
    *,
    canonical_case_id: str,
    case_join_evidence_refs: list[EvidenceRef],
) -> dict[str, Any]:
    """Expose message metadata after the exact canonical case join only."""
    return {
        "factId": evidence_ref.id,
        "occurredAt": _safe_reference(_text(row.get("occurred_at"))),
        "direction": _safe_reference(_text(row.get("direction"))),
        "communicationState": _safe_reference(_text(row.get("communication_state"))),
        "sourceEventType": _safe_reference(_text(row.get("source_event_type"))),
        "canonicalSupportCaseId": canonical_case_id,
        "canonicalSupportCaseResolved": True,
        "evidenceRef": evidence_ref,
        "caseJoinEvidenceRefs": case_join_evidence_refs,
    }


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
        "callbacks": {
            "state": "unknown",
            "reasonCode": (
                reason
                if reason.startswith("support_callback_")
                else _REASON_CALLBACK_AUTHORITY_MISSING
            ),
        },
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
