"""Read-only Profile360 projection over existing identity and temporal stores.

This provider is deliberately narrower than the legacy Kyber profile route.
It reads the tenant-scoped identity profile repository and canonical entity
registry, plus tenant-scoped analytics events and ``graph_history_replay`` when
requested sections need those authorities. It does not resolve arbitrary
identifiers, compute risk, join financial/outcome projections, infer semantic
interactions, or evaluate field-level policy. Missing authorities remain
explicit in the section states and findings.

Historical requests use only ``GraphHistoryReplay`` at the requested knowledge
instant. Current identity rows and analytics events are never presented as
historical facts. For ``window`` and bounded ``relative`` requests, analytics
events use their canonical occurrence timestamps; graph ledger transitions
are filtered by valid-time when bounded and labelled as ledger transitions.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from shared.contracts_models.epistemic import EpistemicStatus
from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    PROJECTION_SECTION_STATES,
)
from shared.intelligence_projections.provider import IntelligenceProjectionProvider
from shared.intelligence_projections.registry import ProviderRegistry
from shared.temporal.instant import parse_instant_strict, to_iso_utc
from graph.operational_intelligence.models import EvidenceRef
from graph.temporal360.history_replay import GraphHistoryReplay, SubjectHistory
from journeys.communication360.contracts import CommunicationMessage


PROJECTION_ID = "profile360"

# Canonical registry section order for provider result sorting.
OUTPUT_SECTIONS: tuple[str, ...] = (
    "agent_delegations",
    "evidence",
    "findings",
    "interactions",
    "journeys",
    "sessions",
    "state",
    "summary",
    "syndicates",
    "timeline",
)

# These are the exact Profile 360 product slots from SSOT §11.4. Generic
# observations and graph mutations support evidence_trace; they are not
# promoted to session_history without a session authority.
SLOT_ENTITY_IDENTITY = "identity_spine"
SLOT_KNOWN_UNKNOWN_RESOLUTION = "known_unknown_resolution"
SLOT_EVIDENCE_LIMITATIONS = "evidence_trace"
SLOT_AGENT_DELEGATIONS = "agent_delegations"
AGENT_DELEGATION_AUTHORITIES = ("agent_access", "agent_executions", "identity")
SLOT_SYNDICATES = "syndicates"
SYNDICATE_AUTHORITIES = ("cohort_membership", "evidence", "population_definitions")

DEFAULT_EVENT_LIMIT = 200
MAX_EVENT_LIMIT = 500
MAX_JOURNEY_LIMIT = 100
MAX_SESSION_IDENTITY_LIMIT = 100
MAX_COMMUNICATION_LIMIT = 100
MAX_SYNDICATE_MEMBERSHIPS = 100
MAX_SYNDICATE_LEDGER_ROWS = 1_000


@dataclass(frozen=True)
class ProfileRead:
    """Identity-profile read with availability distinct from no matching row."""

    record: Optional[dict[str, Any]]
    available: bool
    scope_known: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class CanonicalEntityRead:
    """Exact tenant + entity-id lookup in the canonical entity registry."""

    record: Optional[dict[str, Any]]
    available: bool
    scope_known: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class EventRead:
    """Tenant-scoped observation-event read with explicit completeness."""

    rows: list[dict[str, Any]]
    available: bool
    scope_known: bool
    truncated: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class JourneyRead:
    """Exact current profile journeys with an explicit read boundary."""

    rows: list[dict[str, Any]]
    available: bool
    scope_known: bool
    truncated: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class SessionIdentityRead:
    """Resolved source identities carrying a session claim for this entity."""

    rows: list[dict[str, Any]]
    available: bool
    scope_known: bool
    truncated: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class CommunicationRead:
    """Exact tenant/profile recipient messages with an explicit source boundary."""

    rows: list[CommunicationMessage]
    available: bool
    scope_known: bool
    truncated: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class SyndicateMembership:
    """Exact current membership in an explicitly opted-in Syndicates group."""

    tenant_id: str
    entity_id: str
    population_id: str
    population_type: str
    joined_at: Optional[str]
    evidence_ref: EvidenceRef


@dataclass(frozen=True)
class SyndicateMembershipRead:
    """Bounded read of current, tenant-owned Syndicates memberships."""

    rows: list[SyndicateMembership]
    available: bool
    scope_known: bool
    truncated: bool = False
    reason: Optional[str] = None


@dataclass(frozen=True)
class HistoryRead:
    """Read outcome from the graph-history replay authority."""

    history: Optional[SubjectHistory]
    available: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class IdentityBindingRead:
    """Exact tenant-scoped link from a journey or episode to a user profile."""

    tenant_id: str
    resolved_subject: Optional[ProjectionSubject]
    evidence_ref: Optional[EvidenceRef]
    authority: Optional[str]
    relationship: Optional[str]
    observed_at: Optional[str]
    available: bool
    scope_known: bool
    reason: Optional[str] = None


def _binding_read_unknown(
    tenant_id: str,
    authority: Optional[str],
    relationship: Optional[str],
    reason: str,
) -> IdentityBindingRead:
    return IdentityBindingRead(
        tenant_id=tenant_id,
        resolved_subject=None,
        evidence_ref=None,
        authority=authority,
        relationship=relationship,
        observed_at=None,
        available=True,
        scope_known=False,
        reason=reason,
    )


def _binding_read_unavailable(
    tenant_id: str, authority: str, relationship: str, reason: str
) -> IdentityBindingRead:
    return IdentityBindingRead(
        tenant_id=tenant_id,
        resolved_subject=None,
        evidence_ref=None,
        authority=authority,
        relationship=relationship,
        observed_at=None,
        available=False,
        scope_known=False,
        reason=reason,
    )


class Profile360Source(Protocol):
    """Injectable read seam for canonical Profile360 authorities.

    Implementations must scope every call by ``tenant_id``. The provider also
    rechecks tenant-bearing identity and analytics rows before projecting them.
    """

    async def identity_record(
        self, tenant_id: str, subject: ProjectionSubject
    ) -> ProfileRead: ...

    async def canonical_entity(
        self, tenant_id: str, subject: ProjectionSubject
    ) -> CanonicalEntityRead: ...

    async def identity_binding(
        self, tenant_id: str, subject: ProjectionSubject
    ) -> IdentityBindingRead: ...

    async def analytics_events(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        limit: int,
        start: Optional[str],
        end: Optional[str],
    ) -> EventRead: ...

    async def current_journeys(
        self, tenant_id: str, subject: ProjectionSubject, *, limit: int
    ) -> JourneyRead: ...

    async def resolved_session_identities(
        self, tenant_id: str, subject: ProjectionSubject, *, limit: int
    ) -> SessionIdentityRead: ...

    async def communications_for_profile(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        limit: int,
        start: Optional[str],
    ) -> CommunicationRead: ...

    async def syndicate_memberships(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        limit: int,
    ) -> SyndicateMembershipRead: ...

    async def subject_history(
        self,
        tenant_id: str,
        subject_id: str,
        *,
        as_of: Optional[str],
    ) -> HistoryRead: ...


class RepositoryProfile360Source:
    """Adapter over IdentityRepository, AnalyticsRepository and history replay.

    Imports and repository construction are lazy so importing this module has
    no database or application-startup side effects.
    """

    async def identity_record(
        self, tenant_id: str, subject: ProjectionSubject
    ) -> ProfileRead:
        if subject.kind != "entity":
            return ProfileRead(
                record=None,
                available=True,
                scope_known=False,
                reason="agent_profile_identity_binding_unavailable",
            )
        try:
            from dependencies.providers import get_cache, get_graph
            from repositories.repos import IdentityRepository

            record = await IdentityRepository(get_graph(), get_cache()).get_profile(
                tenant_id, subject.id
            )
        except Exception as exc:  # noqa: BLE001 - typed provider degradation
            return ProfileRead(
                record=None,
                available=False,
                scope_known=False,
                reason=f"identity_repository_{type(exc).__name__}",
            )
        if not isinstance(record, dict) or record.get("tenant_id") != tenant_id:
            return ProfileRead(
                record=None,
                available=True,
                scope_known=False,
                reason="tenant_scoped_identity_record_not_found",
            )
        if str(record.get("user_id") or "") != subject.id:
            return ProfileRead(
                record=None,
                available=True,
                scope_known=False,
                reason="identity_record_subject_mismatch",
            )
        return ProfileRead(record=record, available=True, scope_known=True)

    async def canonical_entity(
        self, tenant_id: str, subject: ProjectionSubject
    ) -> CanonicalEntityRead:
        """Read one exact canonical entity; never resolve an arbitrary identifier."""
        if subject.kind != "entity":
            return CanonicalEntityRead(
                record=None,
                available=True,
                scope_known=False,
                reason="entity_registry_subject_kind_unsupported",
            )
        try:
            from repositories.repos import EntityRepository

            rows = await EntityRepository().find_many(
                filters={"tenant_id": tenant_id, "entity_id": subject.id},
                limit=2,
            )
        except Exception as exc:  # noqa: BLE001 - typed provider degradation
            return CanonicalEntityRead(
                record=None,
                available=False,
                scope_known=False,
                reason=f"entity_registry_{type(exc).__name__}",
            )
        if not isinstance(rows, list):
            return CanonicalEntityRead(
                record=None,
                available=True,
                scope_known=False,
                reason="entity_registry_invalid_response",
            )
        if len(rows) > 1:
            return CanonicalEntityRead(
                record=None,
                available=True,
                scope_known=False,
                reason="entity_registry_identity_ambiguous",
            )
        if not rows:
            return CanonicalEntityRead(
                record=None,
                available=True,
                scope_known=False,
                reason="entity_registry_identity_not_found",
            )
        row = rows[0]
        if not isinstance(row, dict):
            return CanonicalEntityRead(
                record=None,
                available=True,
                scope_known=False,
                reason="entity_registry_invalid_row",
            )
        if row.get("tenant_id") != tenant_id or str(row.get("entity_id") or "") != subject.id:
            return CanonicalEntityRead(
                record=None,
                available=True,
                scope_known=False,
                reason="entity_registry_scope_mismatch",
            )
        return CanonicalEntityRead(record=row, available=True, scope_known=True)

    async def current_journeys(
        self, tenant_id: str, subject: ProjectionSubject, *, limit: int
    ) -> JourneyRead:
        """Read current versions for one typed profile, never a colliding cluster ID."""
        if subject.kind != "entity" or not tenant_id or not subject.id:
            return JourneyRead([], available=True, scope_known=False,
                               reason="profile_journey_subject_kind_unsupported")
        try:
            from journeys.measurement.repositories.journey_repo import JourneyRepository

            rows = await JourneyRepository().find_current_for_profile(
                tenant_id, subject.id, identity_type="profile", limit=limit + 1
            )
        except Exception as exc:  # noqa: BLE001 - typed authority degradation
            return JourneyRead([], available=False, scope_known=False,
                               reason=f"profile_journey_source_{type(exc).__name__}")
        if not isinstance(rows, list):
            return JourneyRead([], available=False, scope_known=False,
                               reason="profile_journey_source_invalid_response")
        if any(
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or row.get("profile_id") != subject.id
            or row.get("journey_type") == "anonymous"
            or row.get("is_current") is not True
            for row in rows
        ):
            return JourneyRead([], available=True, scope_known=False,
                               reason="profile_journey_source_scope_mismatch")
        return JourneyRead(rows[:limit], available=True, scope_known=True,
                           truncated=len(rows) > limit)

    async def resolved_session_identities(
        self, tenant_id: str, subject: ProjectionSubject, *, limit: int
    ) -> SessionIdentityRead:
        """Read canonical identity links; never equate an SDK user ID with a profile."""
        if subject.kind != "entity" or not tenant_id or not subject.id:
            return SessionIdentityRead(
                [], available=True, scope_known=False,
                reason="profile_session_subject_kind_unsupported",
            )
        try:
            from identity.identity.repository import IdentityResolutionRepository

            rows = await IdentityResolutionRepository()._source_identities.find_many(
                filters={
                    "tenant_id": tenant_id,
                    "canonical_entity_id": subject.id,
                    "status": "resolved",
                },
                limit=limit + 1,
            )
        except Exception as exc:  # noqa: BLE001 - typed authority degradation
            return SessionIdentityRead(
                [], available=False, scope_known=False,
                reason=f"profile_session_identity_source_{type(exc).__name__}",
            )
        if not isinstance(rows, list) or any(
            not isinstance(row, dict)
            or row.get("tenant_id") != tenant_id
            or row.get("canonical_entity_id") != subject.id
            or row.get("status") != "resolved"
            for row in rows
        ):
            return SessionIdentityRead(
                [], available=True, scope_known=False,
                reason="profile_session_identity_scope_mismatch",
            )
        return SessionIdentityRead(
            rows[:limit], available=True, scope_known=True,
            truncated=len(rows) > limit,
        )

    async def communications_for_profile(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        limit: int,
        start: Optional[str],
    ) -> CommunicationRead:
        """Read the silver message spine by exact profile entity endpoint.

        The reader's participant filter is tenant-scoped and only returns the
        exact sender/recipient entity columns. The projector below narrows this
        to the recipient side, where source identity and stored consent proofs
        are available together.
        """
        if subject.kind != "entity" or not tenant_id or not subject.id:
            return CommunicationRead(
                [], available=True, scope_known=False,
                reason="profile_communication_subject_kind_unsupported",
            )
        try:
            from journeys.communication360.reader import SilverCommsSource

            source = SilverCommsSource()
            if not await source.available(tenant_id):
                return CommunicationRead(
                    [], available=False, scope_known=False,
                    reason="profile_communication_source_unavailable",
                )
            rows = await source.messages(
                tenant_id,
                participant_entity_id=subject.id,
                since=start,
                limit=limit + 1,
            )
        except Exception as exc:  # noqa: BLE001 - typed provider degradation
            return CommunicationRead(
                [], available=False, scope_known=False,
                reason=f"profile_communication_source_{type(exc).__name__}",
            )
        if not isinstance(rows, list) or any(
            not isinstance(row, CommunicationMessage) for row in rows
        ):
            return CommunicationRead(
                [], available=True, scope_known=False,
                reason="profile_communication_source_invalid_response",
            )
        return CommunicationRead(
            rows=rows[:limit],
            available=True,
            scope_known=True,
            truncated=len(rows) > limit,
        )

    async def syndicate_memberships(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        limit: int,
    ) -> SyndicateMembershipRead:
        """Verify exact current candidates against bounded edge-ledger slices.

        The membership materialization only enumerates candidate population IDs.
        A positive fact requires replaying the exact tenant-owned
        ``MEMBER_OF:<entity>:<population>`` ledger aggregate and finding that
        directed edge live. The population registry supplies the exact target's
        type and explicit Syndicates opt-in. No labels, similarity, generic
        cluster edges, or membership-row evidence IDs establish a fact.
        """
        if subject.kind != "entity" or not tenant_id or not subject.id:
            return SyndicateMembershipRead(
                [],
                available=True,
                scope_known=False,
                reason="profile_syndicate_subject_kind_unsupported",
            )

        bounded_limit = min(max(limit, 1), MAX_SYNDICATE_MEMBERSHIPS)
        try:
            from identity.population.models import PopulationType
            from identity.population.registry import membership_repo, population_repo
            from repositories.graph_mutation_ledger import GraphMutationLedgerRepository
            from replay.projections.syndicates_restatement_capability import (
                is_syndicates_group,
            )
            from shared.graph.graph import EdgeType

            membership_rows = await membership_repo.find_many(
                filters={"tenant_id": tenant_id, "entity_id": subject.id},
                limit=bounded_limit + 1,
            )
            if (
                not isinstance(membership_rows, list)
                or any(
                    not isinstance(row, dict)
                    or row.get("tenant_id") != tenant_id
                    or str(row.get("entity_id") or "") != subject.id
                    for row in membership_rows
                )
            ):
                return SyndicateMembershipRead(
                    [],
                    available=True,
                    scope_known=False,
                    reason="profile_syndicate_membership_scope_mismatch",
                )

            candidate_truncated = len(membership_rows) > bounded_limit
            memberships: list[SyndicateMembership] = []
            reasons: list[str] = []
            truncated = candidate_truncated
            seen_population_ids: set[str] = set()
            known_population_types = {item.value for item in PopulationType}
            ledger = GraphMutationLedgerRepository()
            for membership_row in membership_rows[:bounded_limit]:
                membership_state = (
                    membership_row.get("membership_state")
                    or membership_row.get("status")
                    or "active"
                )
                if membership_state in {"left", "expired"}:
                    continue
                if membership_state != "active":
                    reasons.append("profile_syndicate_membership_state_unrecognized")
                    continue
                population_id = membership_row.get("population_id")
                if not isinstance(population_id, str) or not population_id.strip():
                    return SyndicateMembershipRead(
                        [],
                        available=True,
                        scope_known=False,
                        truncated=truncated,
                        reason="profile_syndicate_population_id_invalid",
                    )
                if population_id in seen_population_ids:
                    continue
                seen_population_ids.add(population_id)

                population = await population_repo.find_by_id(population_id)
                if (
                    not isinstance(population, dict)
                    or population.get("tenant_id") != tenant_id
                    or str(population.get("id") or "") != population_id
                ):
                    return SyndicateMembershipRead(
                        [],
                        available=True,
                        scope_known=False,
                        truncated=truncated,
                        reason="profile_syndicate_population_scope_unverified",
                    )
                population_type = population.get("population_type")
                if population_type not in known_population_types:
                    reasons.append("profile_syndicate_population_type_unavailable")
                    continue
                if not is_syndicates_group(population):
                    continue

                aggregate_id = f"{EdgeType.MEMBER_OF}:{subject.id}:{population_id}"
                ledger_rows = await ledger.list_records(
                    tenant_id,
                    aggregate_id=aggregate_id,
                    limit=MAX_SYNDICATE_LEDGER_ROWS + 1,
                )
                if not isinstance(ledger_rows, list):
                    return SyndicateMembershipRead(
                        [],
                        available=False,
                        scope_known=False,
                        truncated=truncated,
                        reason="profile_syndicate_ledger_invalid_response",
                    )
                if len(ledger_rows) > MAX_SYNDICATE_LEDGER_ROWS:
                    truncated = True
                    reasons.append("profile_syndicate_edge_ledger_scan_truncated")
                    continue

                valid_ledger_rows: list[dict[str, Any]] = []
                for ledger_row in ledger_rows:
                    payload = ledger_row.get("payload") if isinstance(ledger_row, dict) else None
                    if (
                        not isinstance(ledger_row, dict)
                        or ledger_row.get("tenant_id") != tenant_id
                        or ledger_row.get("aggregate_type") != "edge"
                        or ledger_row.get("aggregate_id") != aggregate_id
                        or not isinstance(payload, dict)
                        or payload.get("kind") not in {"edge", "edge_revocation"}
                        or payload.get("edge_type") != EdgeType.MEMBER_OF
                        or payload.get("from_vertex_id") != subject.id
                        or payload.get("to_vertex_id") != population_id
                    ):
                        return SyndicateMembershipRead(
                            [],
                            available=True,
                            scope_known=False,
                            truncated=truncated,
                            reason="profile_syndicate_ledger_scope_mismatch",
                        )
                    if payload.get("kind") == "edge":
                        properties = payload.get("properties")
                        if not isinstance(properties, dict) or properties.get("tenant_id") != tenant_id:
                            return SyndicateMembershipRead(
                                [],
                                available=True,
                                scope_known=False,
                                truncated=truncated,
                                reason="profile_syndicate_ledger_edge_tenant_mismatch",
                            )
                    valid_ledger_rows.append(ledger_row)

                history = GraphHistoryReplay._history_from_rows(
                    subject.id, None, valid_ledger_rows
                )
                edge_key = (EdgeType.MEMBER_OF, subject.id, population_id)
                if edge_key not in set(history.live_edges):
                    reasons.append("profile_syndicate_candidate_edge_not_live")
                    continue

                live_adds = [
                    event
                    for event in history.events
                    if event.kind == "edge_added"
                    and (event.edge_type, event.from_vertex_id, event.to_vertex_id)
                    == edge_key
                ]
                if not live_adds:
                    reasons.append("profile_syndicate_live_edge_evidence_unavailable")
                    continue
                latest_add = max(live_adds, key=lambda event: event.ledger_offset)
                if not latest_add.mutation_id.strip():
                    reasons.append("profile_syndicate_live_edge_evidence_unavailable")
                    continue
                latest_row = next(
                    (
                        ledger_row
                        for ledger_row in valid_ledger_rows
                        if ledger_row.get("mutation_id") == latest_add.mutation_id
                        and int(ledger_row.get("ledger_offset") or 0)
                        == latest_add.ledger_offset
                    ),
                    None,
                )
                latest_payload = (
                    latest_row.get("payload") if isinstance(latest_row, dict) else None
                )
                if not isinstance(latest_payload, dict):
                    reasons.append("profile_syndicate_live_edge_evidence_unavailable")
                    continue
                latest_properties = latest_payload.get("properties")
                if (
                    isinstance(latest_properties, dict)
                    and latest_properties.get("membership_state")
                    not in (None, "", "active")
                ):
                    reasons.append("profile_syndicate_edge_membership_inactive")
                    continue

                evidence_ref = EvidenceRef(
                    id=latest_add.mutation_id,
                    type="relationship",
                    source="graph_mutation_ledger",
                    observedAt=latest_add.recorded_at or None,
                )
                if not evidence_ref.id.strip():
                    return SyndicateMembershipRead(
                        [],
                        available=True,
                        scope_known=True,
                        truncated=truncated,
                        reason="profile_syndicate_live_edge_evidence_unavailable",
                    )
                seen_population_ids.add(population_id)
                joined_at = (
                    latest_properties.get("valid_from")
                    if isinstance(latest_properties, dict)
                    else None
                ) or evidence_ref.observedAt
                memberships.append(
                    SyndicateMembership(
                        tenant_id=tenant_id,
                        entity_id=subject.id,
                        population_id=population_id,
                        population_type=str(population_type),
                        joined_at=joined_at if isinstance(joined_at, str) else None,
                        evidence_ref=evidence_ref,
                    )
                )
        except Exception:  # noqa: BLE001 - fail closed at the membership boundary
            return SyndicateMembershipRead(
                [],
                available=False,
                scope_known=False,
                reason="profile_syndicate_membership_authority_unavailable",
            )

        return SyndicateMembershipRead(
            memberships,
            available=True,
            scope_known=True,
            truncated=truncated,
            reason="|".join(sorted(set(reasons))) or None,
        )

    async def identity_binding(
        self, tenant_id: str, subject: ProjectionSubject
    ) -> IdentityBindingRead:
        """Resolve only exact, current journey/episode links to user profiles."""
        if subject.kind == "journey":
            authority = "journey_versions"
            relationship = "journey_profile_id"
            try:
                from journeys.measurement.repositories.journey_repo import JourneyRepository

                rows = await JourneyRepository().list_versions(tenant_id, subject.id)
            except Exception as exc:  # noqa: BLE001 - typed provider degradation
                return _binding_read_unavailable(
                    tenant_id, authority, relationship, f"journey_identity_binding_{type(exc).__name__}"
                )
            if not isinstance(rows, list):
                return _binding_read_unavailable(
                    tenant_id, authority, relationship, "journey_identity_binding_invalid_read"
                )
            scoped_rows: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    return _binding_read_unknown(
                        tenant_id, authority, relationship, "journey_identity_binding_invalid_row"
                    )
                if row.get("tenant_id") != tenant_id or str(row.get("journey_id") or "") != subject.id:
                    return _binding_read_unknown(
                        tenant_id, authority, relationship, "journey_identity_binding_scope_mismatch"
                    )
                scoped_rows.append(row)
            current = [row for row in scoped_rows if row.get("is_current") is True]
            if len(current) != 1:
                return _binding_read_unknown(
                    tenant_id,
                    authority,
                    relationship,
                    "journey_identity_binding_ambiguous"
                    if len(current) > 1
                    else "journey_identity_binding_not_found",
                )
            row = current[0]
            profile_id = _safe_text(row.get("profile_id"))
            version_id = _safe_text(row.get("journey_version_id"))
            if row.get("journey_type") != "profile" or profile_id is None or version_id is None:
                return _binding_read_unknown(
                    tenant_id, authority, relationship, "journey_subject_not_exact_profile"
                )
            observed_at = _safe_text(row.get("computed_at"))
            return IdentityBindingRead(
                tenant_id=tenant_id,
                resolved_subject=ProjectionSubject(kind="entity", id=profile_id),
                evidence_ref=EvidenceRef(
                    id=version_id,
                    type="relationship",
                    source="services/api/journeys/measurement/repositories/journey_repo.py:journey_versions",
                    observedAt=observed_at,
                    uri=f"store://journey_versions/{version_id}",
                ),
                authority=authority,
                relationship=relationship,
                observed_at=observed_at,
                available=True,
                scope_known=True,
            )

        if subject.kind == "episode":
            authority = "episode_records"
            relationship = "episode_user_subject"
            try:
                from shared.backend_interpretation.stores import EpisodeStore

                episode = await EpisodeStore().get(tenant_id, subject.id)
            except Exception as exc:  # noqa: BLE001 - typed provider degradation
                return _binding_read_unavailable(
                    tenant_id, authority, relationship, f"episode_identity_binding_{type(exc).__name__}"
                )
            if episode is None:
                return _binding_read_unknown(
                    tenant_id, authority, relationship, "episode_identity_binding_not_found"
                )
            if (
                getattr(episode, "tenant_id", None) != tenant_id
                or str(getattr(episode, "episode_id", "") or "") != subject.id
            ):
                return _binding_read_unknown(
                    tenant_id, authority, relationship, "episode_identity_binding_scope_mismatch"
                )
            episode_subject = getattr(episode, "subject", None)
            profile_id = _safe_text(getattr(episode_subject, "id", None))
            if getattr(episode_subject, "kind", None) != "user" or profile_id is None:
                return _binding_read_unknown(
                    tenant_id, authority, relationship, "episode_subject_not_exact_user_profile"
                )
            observed_at = _safe_text(getattr(episode, "created_at", None))
            episode_id = str(getattr(episode, "episode_id"))
            return IdentityBindingRead(
                tenant_id=tenant_id,
                resolved_subject=ProjectionSubject(kind="entity", id=profile_id),
                evidence_ref=EvidenceRef(
                    id=episode_id,
                    type="relationship",
                    source="services/api/shared/backend_interpretation/stores.py:episodes",
                    observedAt=observed_at,
                    uri=f"store://episodes/{episode_id}",
                ),
                authority=authority,
                relationship=relationship,
                observed_at=observed_at,
                available=True,
                scope_known=True,
            )

        return _binding_read_unknown(
            tenant_id, None, None, "identity_binding_subject_kind_unsupported"
        )

    async def analytics_events(
        self,
        tenant_id: str,
        subject: ProjectionSubject,
        *,
        limit: int,
        start: Optional[str],
        end: Optional[str],
    ) -> EventRead:
        try:
            from dependencies.providers import get_cache
            from repositories.repos import AnalyticsRepository

            query: dict[str, Any] = {"canonical_entity_id": subject.id}
            if start is not None:
                query["start_date"] = start
            if end is not None:
                query["end_date"] = end
            rows = await AnalyticsRepository(get_cache()).query_events(
                tenant_id, query, limit=limit + 1
            )
        except Exception as exc:  # noqa: BLE001 - typed provider degradation
            return EventRead(
                rows=[],
                available=False,
                scope_known=False,
                reason=f"analytics_repository_{type(exc).__name__}",
            )

        scoped = [
            row
            for row in rows
            if isinstance(row, dict) and row.get("tenant_id") == tenant_id
        ]
        if len(scoped) != len(rows):
            return EventRead(
                rows=[],
                available=True,
                scope_known=False,
                reason="analytics_row_tenant_mismatch",
            )
        return EventRead(
            rows=scoped[:limit],
            available=True,
            scope_known=True,
            truncated=len(scoped) > limit,
        )

    async def subject_history(
        self,
        tenant_id: str,
        subject_id: str,
        *,
        as_of: Optional[str],
    ) -> HistoryRead:
        try:
            history = await GraphHistoryReplay().subject_history(
                tenant_id, subject_id, as_of=as_of
            )
        except Exception as exc:  # noqa: BLE001 - typed provider degradation
            return HistoryRead(
                history=None,
                available=False,
                reason=f"graph_history_replay_{type(exc).__name__}",
            )
        return HistoryRead(history=history, available=True)


@dataclass(frozen=True)
class _TemporalRequest:
    mode: str
    as_of: Optional[str]
    start: Optional[str]
    end: Optional[str]
    error: Optional[str] = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _temporal_request(request: ProjectionRequest) -> _TemporalRequest:
    """Normalize supported modes without relabeling an unsupported question."""
    mode = request.temporalMode or "window"
    time_range = request.timeRange
    start = time_range.from_ if time_range is not None else None
    end = time_range.to if time_range is not None else None

    if mode == "as_of":
        raw_anchor = request.asOf or start
        if raw_anchor is None:
            return _TemporalRequest(
                mode=mode,
                as_of=None,
                start=start,
                end=end,
                error="as_of_anchor_missing",
            )
        try:
            anchor = to_iso_utc(parse_instant_strict(raw_anchor))
        except ValueError:
            return _TemporalRequest(
                mode=mode,
                as_of=None,
                start=start,
                end=end,
                error="as_of_anchor_invalid",
            )
        return _TemporalRequest(mode=mode, as_of=anchor, start=None, end=None)

    if mode not in {"window", "relative"}:
        return _TemporalRequest(
            mode=mode,
            as_of=None,
            start=start,
            end=end,
            error="temporal_mode_unsupported",
        )

    if mode == "relative" and start is None and end is None:
        return _TemporalRequest(
            mode=mode,
            as_of=None,
            start=None,
            end=None,
            error="relative_time_bounds_missing",
        )

    # ``asOf`` is an exact anchor in ProjectionRequest even when a caller uses
    # the older contract without an explicit temporalMode.
    if request.asOf is not None:
        try:
            anchor = to_iso_utc(parse_instant_strict(request.asOf))
        except ValueError:
            return _TemporalRequest(
                mode=mode,
                as_of=None,
                start=start,
                end=end,
                error="as_of_anchor_invalid",
            )
        # An explicit valid-time range can still filter history events, while
        # the graph reader reconstructs what was known at the exact anchor.
        return _TemporalRequest(
            mode=mode,
            as_of=anchor,
            start=start,
            end=end,
        )

    try:
        normalized_start = (
            to_iso_utc(parse_instant_strict(start)) if start is not None else None
        )
        normalized_end = (
            to_iso_utc(parse_instant_strict(end)) if end is not None else None
        )
    except ValueError:
        return _TemporalRequest(
            mode=mode,
            as_of=None,
            start=start,
            end=end,
            error="time_range_invalid",
        )
    if normalized_start and normalized_end and normalized_start > normalized_end:
        return _TemporalRequest(
            mode=mode,
            as_of=None,
            start=normalized_start,
            end=normalized_end,
            error="time_range_inverted",
        )
    return _TemporalRequest(
        mode=mode,
        as_of=None,
        start=normalized_start,
        end=normalized_end,
    )


def _safe_text(value: Any) -> Optional[str]:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    text = str(value).strip()
    return text or None


def _safe_instant(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        try:
            return to_iso_utc(value)
        except ValueError:
            return None
    text = _safe_text(value)
    if text is None:
        return None
    try:
        return to_iso_utc(parse_instant_strict(text))
    except ValueError:
        return None


def _profile_evidence(record: dict[str, Any]) -> Optional[EvidenceRef]:
    profile_id = _safe_text(record.get("user_id"))
    if profile_id is None:
        return None
    return EvidenceRef(
        id=profile_id,
        type="entity",
        source="identity_profiles",
        observedAt=_safe_text(record.get("updated_at")),
    )


def _entity_evidence(record: dict[str, Any]) -> Optional[EvidenceRef]:
    entity_id = _safe_text(record.get("entity_id"))
    if entity_id is None:
        return None
    return EvidenceRef(
        id=entity_id,
        type="entity",
        source="entity_registry",
        observedAt=_safe_text(record.get("updated_at") or record.get("created_at")),
    )


def _event_evidence(row: dict[str, Any]) -> Optional[EvidenceRef]:
    event_id = _safe_text(row.get("event_id") or row.get("id"))
    if event_id is None:
        return None
    return EvidenceRef(
        id=event_id,
        type="event",
        source="analytics_events",
        observedAt=_safe_text(row.get("occurred_at") or row.get("created_at")),
    )


def _mutation_evidence(event: Any) -> Optional[EvidenceRef]:
    mutation_id = _safe_text(getattr(event, "mutation_id", None))
    if mutation_id is None:
        return None
    return EvidenceRef(
        id=mutation_id,
        type="event",
        source="graph_mutation_ledger",
        observedAt=_safe_text(getattr(event, "recorded_at", None)),
    )


def _dedupe_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    seen: set[tuple[str, str]] = set()
    unique: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.source, ref.id)
        if key not in seen:
            seen.add(key)
            unique.append(ref)
    return unique


def _within(value: Optional[str], start: Optional[str], end: Optional[str]) -> bool:
    """Return whether an aware ISO instant falls within inclusive UTC bounds."""
    if value is None:
        return False
    try:
        instant = parse_instant_strict(value)
    except ValueError:
        return False
    if start is not None and instant < parse_instant_strict(start):
        return False
    if end is not None and instant > parse_instant_strict(end):
        return False
    return True


def _safe_profile(record: dict[str, Any]) -> dict[str, Any]:
    """Project a minimal identity allowlist; never echo source metadata/raw PII."""
    return {
        "id": _safe_text(record.get("user_id")),
        "displayName": _safe_text(record.get("display_name") or record.get("name")),
        "status": _safe_text(record.get("status")),
        "createdAt": _safe_text(record.get("created_at")),
        "updatedAt": _safe_text(record.get("updated_at")),
    }


def _safe_entity(record: dict[str, Any]) -> dict[str, Any]:
    """Project the canonical entity allowlist; omit raw metadata and extra fields."""
    return {
        "id": _safe_text(record.get("entity_id")),
        "type": _safe_text(record.get("entity_type")),
        "displayName": _safe_text(record.get("display_name")),
        "createdAt": _safe_text(record.get("created_at")),
        "updatedAt": _safe_text(record.get("updated_at")),
    }


def _age_seconds(observed_at: Optional[str]) -> Optional[float]:
    """Compute descriptive age only; the provider has no freshness threshold."""
    if observed_at is None:
        return None
    try:
        delta = datetime.now(timezone.utc) - parse_instant_strict(observed_at)
    except ValueError:
        return None
    return max(delta.total_seconds(), 0.0)


class Profile360Provider:
    """Read-only profile projection with tenant-scoped source and slot boundaries.

    The frame runtime evaluates policy before dispatch and passes only sections
    for requested, permitted slots. Source reads follow ``includeSections`` so
    an identity-only request does not read activity or graph history.
    """

    projection_id = PROJECTION_ID
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    graph_mutation_policy = "read_only"

    def __init__(
        self,
        source: Optional[Profile360Source] = None,
        *,
        agent_provider: Optional[IntelligenceProjectionProvider] = None,
    ) -> None:
        self._source = source if source is not None else RepositoryProfile360Source()
        self._agent_provider = agent_provider

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        """Compose tenant-scoped identity, observation and temporal evidence."""
        temporal = _temporal_request(request)
        requested_sections = set(request.includeSections or OUTPUT_SECTIONS)
        needs_journeys = "journeys" in requested_sections
        needs_sessions = "sessions" in requested_sections
        needs_agent_delegations = SLOT_AGENT_DELEGATIONS in requested_sections
        needs_syndicates = SLOT_SYNDICATES in requested_sections
        needs_identity = bool(
            {"summary", "state", "evidence", "journeys", "sessions", "interactions"}
            & requested_sections
        )
        needs_entity = bool(
            {
                "summary",
                "state",
                "evidence",
                "journeys",
                "sessions",
                "interactions",
                SLOT_AGENT_DELEGATIONS,
            }
            & requested_sections
            or (needs_syndicates and request.subject.kind == "entity")
            or ("timeline" in requested_sections and request.subject.kind == "entity")
        )
        needs_events = bool({"timeline", "evidence"} & requested_sections)
        needs_history = bool({"timeline", "evidence"} & requested_sections)
        limit = min(
            max(request.page.limit if request.page is not None else DEFAULT_EVENT_LIMIT, 1),
            MAX_EVENT_LIMIT,
        )

        if request.subject.kind in {"journey", "episode"}:
            related_result = await self._project_related_user_context(
                request, context, temporal
            )
            return _filter_projection_result(related_result, request)

        # A historical profile request must never read current identity rows or
        # current analytics and mislabel them as what was known then.
        historical = temporal.as_of is not None
        if historical:
            identity = ProfileRead(
                record=None,
                available=True,
                scope_known=False,
                reason="identity_profile_not_temporally_replayed",
            )
            events = EventRead(
                rows=[],
                available=True,
                scope_known=False,
                reason="analytics_events_not_replayed_at_as_of",
            )
            canonical_entity = CanonicalEntityRead(
                record=None,
                available=True,
                scope_known=False,
                reason="entity_registry_not_temporally_replayed",
            )
            history_subject_id = request.subject.id
        elif temporal.error is None:
            identity, canonical_entity, events = await _read_profile_and_events(
                self._source,
                request.tenantId,
                request.subject,
                limit=limit,
                start=temporal.start,
                end=temporal.end,
                include_identity=needs_identity,
                include_entity=needs_entity,
                include_events=needs_events,
            )
            history_subject_id = request.subject.id
        else:
            identity = ProfileRead(
                record=None,
                available=False,
                scope_known=False,
                reason=temporal.error,
            )
            events = EventRead(
                rows=[],
                available=False,
                scope_known=False,
                reason=temporal.error,
            )
            canonical_entity = CanonicalEntityRead(
                record=None,
                available=False,
                scope_known=False,
                reason=temporal.error,
            )
            history_subject_id = request.subject.id

        if needs_history and (historical or temporal.error is None):
            if not historical and identity.record is not None:
                # IdentityRepository stores a natural user ID while graph
                # history stores the tenant-prefixed canonical user vertex ID.
                # Derive that exact repository ID only after the scoped profile
                # record proves the subject is a user profile.
                from shared.graph.graph import user_vertex_id

                history_subject_id = user_vertex_id(
                    request.tenantId,
                    str(identity.record.get("user_id") or request.subject.id),
                )
            elif (
                not historical
                and canonical_entity.record is not None
                and canonical_entity.record.get("entity_type") == "human"
            ):
                # A timeline-only read may omit the profile row by policy. A
                # verified canonical human entity still lets us address its
                # tenant-prefixed graph-history vertex without reading profile
                # attributes.
                from shared.graph.graph import user_vertex_id

                history_subject_id = user_vertex_id(request.tenantId, request.subject.id)
            history = await _safe_history(
                self._source,
                request.tenantId,
                history_subject_id,
                as_of=temporal.as_of,
            )
        else:
            history = HistoryRead(
                history=None,
                available=True,
                reason=(temporal.error or "graph_history_not_requested"),
            )

        result = self._result(
            request,
            context,
            temporal,
            identity,
            canonical_entity,
            events,
            history,
            limit=limit,
        )
        if needs_agent_delegations:
            agent_delegation_section, agent_delegation_claims = (
                await self._agent_delegations(request, temporal, canonical_entity)
            )
            result = result.model_copy(
                update={
                    "sections": sorted(
                        [*result.sections, agent_delegation_section],
                        key=lambda section: OUTPUT_SECTIONS.index(section.id),
                    ),
                    "claims": [*result.claims, *agent_delegation_claims],
                }
            )
        if needs_syndicates:
            syndicates_section, syndicates_claims = await self._syndicates(
                request, temporal, canonical_entity
            )
            base_claims = (
                result.claims
                if requested_sections != {SLOT_SYNDICATES}
                else []
            )
            result = result.model_copy(
                update={
                    "sections": sorted(
                        [*result.sections, syndicates_section],
                        key=lambda section: OUTPUT_SECTIONS.index(section.id),
                    ),
                    "claims": [*base_claims, *syndicates_claims],
                }
            )
        if needs_journeys:
            journey_section, journey_claims = await self._journey_participation(
                request, temporal, identity, canonical_entity
            )
            base_claims = (
                result.claims
                if {"summary", "state", "evidence"} & requested_sections
                else []
            )
            result = result.model_copy(
                update={
                    "sections": sorted(
                        [*result.sections, journey_section],
                        key=lambda section: OUTPUT_SECTIONS.index(section.id),
                    ),
                    "claims": [*base_claims, *journey_claims],
                }
            )
        if needs_sessions:
            session_section, session_claims = await self._session_history(
                request, context, temporal, identity, canonical_entity
            )
            base_claims = result.claims if requested_sections != {"sessions"} else []
            result = result.model_copy(
                update={
                    "sections": sorted(
                        [*result.sections, session_section],
                        key=lambda section: OUTPUT_SECTIONS.index(section.id),
                    ),
                    "claims": [*base_claims, *session_claims],
                }
            )
        if "interactions" in requested_sections:
            communication_section, communication_claims = await self._profile_communications(
                request, context, temporal, identity, canonical_entity
            )
            sections = [
                communication_section if section.id == "interactions" else section
                for section in result.sections
            ]
            base_claims = result.claims if requested_sections != {"interactions"} else []
            result = result.model_copy(
                update={
                    "sections": sections,
                    "claims": [*base_claims, *communication_claims],
                }
            )
        return _filter_projection_result(result, request)

    async def _syndicates(
        self,
        request: ProjectionRequest,
        temporal: _TemporalRequest,
        canonical_entity: CanonicalEntityRead,
    ) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
        """Project only explicit, current, tenant-owned Syndicates membership.

        This intentionally uses the Population 360 Syndicates opt-in contract;
        labels, profile resemblance, generic populations, and Cluster360 groups
        do not establish Syndicates membership. The membership materialization
        enumerates candidates only; each positive row is checked against its
        exact current graph-ledger aggregate. The reader has no historical
        replay, roster completeness watermark, or freshness SLA.
        """

        def unknown(
            reason: str, *, state: str = "unknown"
        ) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
            return (
                ProjectionSection(
                    id=SLOT_SYNDICATES,
                    state=state,  # type: ignore[arg-type]
                    title="Syndicate and cohort memberships",
                    content={
                        "state": state,
                        "memberships": [],
                        "observedMembershipCount": None,
                        "coverage": "unknown",
                        "complete": False,
                        "temporalInterpretation": "current_membership_candidates_verified_against_graph_ledger",
                        "freshness": {
                            "state": "unknown",
                            "observedAt": None,
                            "reason": "Profile360 has no membership freshness threshold.",
                        },
                        "reasonCode": reason,
                        "limitations": [
                            "historical membership replay is unavailable",
                            "membership roster completeness is unknown",
                            "only explicitly opted-in Syndicates groups are eligible",
                        ],
                    },
                    canonicalAuthorityRefs=(
                        list(SYNDICATE_AUTHORITIES) if state == "degraded" else None
                    ),
                ),
                [],
            )

        if request.subject.kind != "entity":
            return unknown("profile_syndicate_subject_kind_unsupported")
        if temporal.error is not None:
            return unknown("profile_syndicate_temporal_request_unavailable", state="degraded")
        if temporal.as_of is not None or temporal.start is not None or temporal.end is not None:
            return unknown("profile_syndicate_historical_replay_unavailable")
        entity = (
            canonical_entity.record
            if canonical_entity.available and canonical_entity.scope_known
            else None
        )
        if (
            entity is None
            or entity.get("tenant_id") != request.tenantId
            or str(entity.get("entity_id") or "") != request.subject.id
        ):
            return unknown("profile_syndicate_exact_entity_unavailable")

        try:
            read = await self._source.syndicate_memberships(
                request.tenantId,
                request.subject,
                limit=MAX_SYNDICATE_MEMBERSHIPS,
            )
        except Exception:  # noqa: BLE001 - fail closed at the membership boundary
            return unknown(
                "profile_syndicate_membership_authority_unavailable", state="degraded"
            )
        if not isinstance(read, SyndicateMembershipRead) or not isinstance(
            read.rows, list
        ):
            return unknown(
                "profile_syndicate_membership_source_invalid_response", state="degraded"
            )
        if not read.available:
            return unknown(
                "profile_syndicate_membership_authority_unavailable", state="degraded"
            )
        if not read.scope_known:
            return unknown(
                read.reason or "profile_syndicate_membership_scope_unverified"
            )
        if len(read.rows) > MAX_SYNDICATE_MEMBERSHIPS:
            return unknown(
                "profile_syndicate_membership_source_limit_exceeded", state="degraded"
            )

        memberships: list[dict[str, Any]] = []
        evidence_refs: list[EvidenceRef] = []
        seen: set[str] = set()
        for row in read.rows:
            if (
                not isinstance(row, SyndicateMembership)
                or row.tenant_id != request.tenantId
                or row.entity_id != request.subject.id
                or not row.population_id
                or row.population_type not in {
                    "segment",
                    "cohort",
                    "cluster",
                    "community",
                    "batch",
                    "archetype",
                    "anomaly",
                    "lookalike",
                    "risk",
                    "lifecycle",
                }
                or not isinstance(row.evidence_ref, EvidenceRef)
                or row.evidence_ref.type != "relationship"
                or row.evidence_ref.source != "graph_mutation_ledger"
                or not row.evidence_ref.id.strip()
            ):
                return unknown("profile_syndicate_membership_scope_or_evidence_invalid")
            if row.population_id in seen:
                continue
            seen.add(row.population_id)
            memberships.append(
                {
                    "populationId": row.population_id,
                    "populationType": row.population_type,
                    "membershipState": "active",
                    "joinedAt": row.joined_at,
                    "evidenceRef": row.evidence_ref.model_dump(mode="json"),
                }
            )
            evidence_refs.append(row.evidence_ref)

        if read.truncated:
            state = "degraded"
            reason = "profile_syndicate_membership_scan_truncated"
        elif read.reason:
            state = "degraded"
            reason = read.reason
        elif memberships:
            state = "degraded"
            reason = "profile_syndicate_membership_completeness_unknown"
        else:
            state = "unknown"
            reason = "profile_syndicate_membership_not_observed_completeness_unknown"

        section = ProjectionSection(
            id=SLOT_SYNDICATES,
            state=state,  # type: ignore[arg-type]
            title="Syndicate and cohort memberships",
            content={
                "state": state,
                "memberships": memberships,
                "observedMembershipCount": len(memberships),
                "coverage": "unknown",
                "complete": False,
                "temporalInterpretation": "current_membership_candidates_verified_against_graph_ledger",
                "freshness": {
                    "state": "unknown",
                    "observedAt": None,
                    "reason": "Profile360 has no membership freshness threshold.",
                },
                "readAuthority": "population_memberships+population_definitions+graph_mutation_ledger",
                "reasonCode": reason,
                "limitations": [
                    "membership rows enumerate candidate population IDs; exact active membership is verified from the tenant-scoped MEMBER_OF ledger aggregate",
                    "membership roster completeness is unknown",
                    "historical membership replay is unavailable",
                    "Profile360 membership freshness policy is unavailable",
                ],
            },
            warnings=(
                ["membership read was bounded"] if read.truncated else None
            ),
            canonicalAuthorityRefs=list(SYNDICATE_AUTHORITIES),
        )
        claims = [
            ClaimEnvelope(
                id=f"profile360.syndicate_membership.{row.population_id}",
                kind="profile_syndicate_membership",
                subject=request.subject,
                evidenceRefs=[row.evidence_ref],
                claims=[
                    "The exact tenant entity has an observed active MEMBER_OF edge to an explicitly opted-in Syndicates group."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=[SLOT_SYNDICATES],
            )
            for row in read.rows
            if isinstance(row, SyndicateMembership)
            and row.tenant_id == request.tenantId
            and row.entity_id == request.subject.id
            and row.population_id in seen
            and row.evidence_ref in evidence_refs
        ]
        return section, claims

    async def _agent_delegations(
        self,
        request: ProjectionRequest,
        temporal: _TemporalRequest,
        canonical_entity: CanonicalEntityRead,
    ) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
        """Reuse Agent360's tenant-scoped authority path for exact Agent subjects.

        A human/profile entity is not linked to an agent merely because it is
        present in Profile360. Entity subjects are accepted only when Agent360
        resolves that exact entity ID as a canonical Agent entity. Runtime
        agent references are accepted only after Agent360 resolves them through
        its tenant-owned identity authority.
        """

        def unknown(reason: str, *, state: str = "unknown") -> tuple[ProjectionSection, list[ClaimEnvelope]]:
            return (
                ProjectionSection(
                    id=SLOT_AGENT_DELEGATIONS,
                    state=state,  # type: ignore[arg-type]
                    title="Agent delegation and authority",
                    content={
                        "state": state,
                        "identityBinding": {"state": "unknown", "reason": reason},
                        "delegationAuthority": {"state": state, "reason": reason},
                        "policy": {
                            "state": "not_evaluated_by_projection",
                            "effectiveAuthorizationDecision": "unknown",
                            "reason": (
                                "Profile access policy is enforced by the frame runtime; "
                                "stored delegation evidence does not authorize a new action."
                            ),
                        },
                        "freshness": {
                            "state": "unknown",
                            "observedAt": None,
                            "reason": "No Profile360 agent-authority freshness threshold is available.",
                        },
                        "temporalSemantics": temporal.mode,
                    },
                ),
                [],
            )

        if request.subject.kind not in {"agent", "entity"}:
            return unknown("profile_subject_has_no_exact_agent_binding")
        if request.subject.kind == "entity":
            entity = canonical_entity.record
            if (
                entity is None
                or entity.get("tenant_id") != request.tenantId
                or _safe_text(entity.get("entity_id")) != request.subject.id
            ):
                return unknown("profile_entity_registry_binding_unavailable")
            if entity.get("entity_type") != "agent":
                return unknown("profile_entity_is_not_a_canonical_agent")
        if temporal.error is not None:
            return unknown(temporal.error)
        if temporal.as_of is not None or temporal.mode == "compare":
            return unknown("agent_authority_historical_replay_unavailable")

        try:
            if self._agent_provider is None:
                from actions.agent.agent360_provider import Agent360Provider

                self._agent_provider = Agent360Provider()
            agent_request = ProjectionRequest(
                projectionId="agent360",
                tenantId=request.tenantId,
                subject=request.subject,
                page=request.page,
                timeRange=request.timeRange,
                includeSections=["state"],
                includeClaims=request.includeClaims,
                temporalMode=temporal.mode,
            )
            agent_context = await ProviderRegistry().build_context(
                "agent360", agent_request
            )
            agent_result = await self._agent_provider.project(agent_request, agent_context)
        except Exception:  # noqa: BLE001 - fail closed at the cross-projection boundary
            return unknown("agent360_authority_provider_unavailable", state="degraded")

        if (
            agent_result.projectionId != "agent360"
            or agent_result.tenantId != request.tenantId
        ):
            return unknown("agent360_authority_result_scope_mismatch", state="degraded")

        state_sections = [section for section in agent_result.sections if section.id == "state"]
        state_content = state_sections[0].content if len(state_sections) == 1 else None
        dimensions = state_content.get("dimensions") if isinstance(state_content, dict) else None
        if not isinstance(dimensions, list):
            return unknown("agent360_exact_agent_identity_unavailable")

        def dimension(name: str) -> Optional[dict[str, Any]]:
            matches = [
                item
                for item in dimensions
                if isinstance(item, dict) and item.get("id") == name
            ]
            return matches[0] if len(matches) == 1 else None

        identity_dimension = dimension("agent_identity")
        actor_dimension = dimension("actor_attribution")
        authority_dimension = dimension("authority_and_delegation")
        identity_content = (
            identity_dimension.get("content")
            if isinstance(identity_dimension, dict)
            else None
        )
        actor_content = (
            actor_dimension.get("content") if isinstance(actor_dimension, dict) else None
        )
        authority_content = (
            authority_dimension.get("content")
            if isinstance(authority_dimension, dict)
            else None
        )
        if not all(
            isinstance(value, dict)
            for value in (identity_content, actor_content, authority_content)
        ):
            return unknown("agent360_exact_agent_identity_unavailable")

        canonical_agent_id = _safe_text(identity_content.get("canonicalAgentEntityId"))
        attributed_agent_id = _safe_text(actor_content.get("resolvedCanonicalActor"))
        identity_refs: list[EvidenceRef] = []
        raw_identity_refs = identity_content.get("evidenceRefs")
        if isinstance(raw_identity_refs, list):
            for raw_ref in raw_identity_refs:
                try:
                    ref = EvidenceRef.model_validate(raw_ref)
                except Exception:  # noqa: BLE001 - malformed identity evidence is omitted
                    continue
                if (
                    ref.type == "entity"
                    and ref.source in {"entities", "agent_deployment_identity_bindings"}
                ):
                    identity_refs.append(ref)
        if (
            not canonical_agent_id
            or attributed_agent_id != canonical_agent_id
            or not identity_refs
            or actor_content.get("state") != "matched"
        ):
            return unknown("agent360_exact_agent_identity_unavailable")
        if request.subject.kind == "entity" and canonical_agent_id != request.subject.id:
            return unknown("profile_entity_is_not_the_resolved_canonical_agent")

        authority_state = (
            authority_dimension.get("state")
            if isinstance(authority_dimension, dict)
            else None
        )
        if not isinstance(authority_state, str):
            return unknown("agent360_authority_state_invalid", state="degraded")
        if authority_state in PROJECTION_SECTION_STATES:
            section_state = authority_state
        elif authority_state in {"partial", "conflicted", "truncated", "unavailable"}:
            # Keep more specific incomplete states in the authority payload,
            # while mapping them to the shared section-state contract.
            section_state = "degraded"
        else:
            return unknown("agent360_authority_state_invalid", state="degraded")

        # Agent360 has already tenant-validated these records and party joins.
        # Keep an explicit allowlist at the Profile360 boundary so new internal
        # Agent360 fields do not silently become part of the Profile contract.
        authority_view = {
            "state": authority_state,
            **{
                key: authority_content[key]
                for key in (
                    "delegationRecords",
                    "delegationReadConflicts",
                    "actionScopedDecisions",
                    "actionScopedDecisionState",
                    "activeIncomingCount",
                    "capabilityAccessProfile",
                    "temporalSemantics",
                    "truncated",
                    "evidenceRefs",
                )
                if key in authority_content
            },
            "effectiveAuthorizationDecision": "unknown",
        }
        content = {
            "state": section_state,
            "identityBinding": {
                "state": "matched",
                "sourceAgentId": request.subject.id,
                "canonicalAgentEntityId": canonical_agent_id,
                "evidenceRefs": [
                    ref.model_dump(mode="json", exclude_none=True)
                    for ref in _dedupe_refs(identity_refs)
                ],
            },
            "delegationAuthority": authority_view,
            "policy": {
                "state": "not_evaluated_by_projection",
                "effectiveAuthorizationDecision": "unknown",
                "reason": (
                    "Profile access policy is enforced by the frame runtime. Agent360 "
                    "reports stored grants and recorded action decisions; it does not "
                    "authorize a new action or resource request."
                ),
            },
            "freshness": {
                "state": "unknown",
                "observedAt": None,
                "reason": "Agent360 exposes current repository state without a Profile360 freshness threshold.",
            },
            "temporalSemantics": authority_content.get(
                "temporalSemantics", "current_repository_state; no historical replay"
            ),
        }
        if request.timeRange is not None:
            content["requestedTemporalMode"] = temporal.mode

        exact_claim_kinds = {
            "agent_delegation_record",
            "agent_delegation_active_state_conflict",
            "canonically_resolved_delegation_party",
            "delegation_party_identity_resolution",
            "server_recorded_delegation_decision",
            "agent_capability_access_profile",
        }
        claims: list[ClaimEnvelope] = []
        if request.includeClaims is not False:
            for claim in agent_result.claims:
                if (
                    claim.kind not in exact_claim_kinds
                    or claim.subject != request.subject
                    or not claim.evidenceRefs
                ):
                    continue
                claims.append(
                    claim.model_copy(
                        update={
                            "subject": request.subject,
                            "domainSlotIds": [SLOT_AGENT_DELEGATIONS],
                        }
                    )
                )

        return (
            ProjectionSection(
                id=SLOT_AGENT_DELEGATIONS,
                state=section_state,  # type: ignore[arg-type]
                title="Agent delegation and authority",
                content=content,
                canonicalAuthorityRefs=list(AGENT_DELEGATION_AUTHORITIES),
            ),
            claims,
        )

    async def _profile_communications(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
        temporal: _TemporalRequest,
        identity: ProfileRead,
        canonical_entity: CanonicalEntityRead,
    ) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
        """Join only consent-backed messages whose exact recipient is this profile."""

        def unknown(
            reason: str, *, state: str = "unknown"
        ) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
            return (
                ProjectionSection(
                    id="interactions",
                    state=state,  # type: ignore[arg-type]
                    title="Profile communication activity",
                    content={
                        "state": state,
                        "items": [],
                        "complete": False,
                        "coverage": "recipient_message_spine_with_recorded_consent_only",
                        "reasonCode": reason,
                    },
                    warnings=[reason],
                    canonicalAuthorityRefs=["communication_facts"],
                ),
                [],
            )

        if context.tenantId != request.tenantId:
            return unknown("profile_communication_tenant_scope_mismatch")
        if temporal.as_of is not None or temporal.error is not None:
            return unknown(
                temporal.error or "profile_communication_historical_state_unavailable"
            )
        if temporal.mode not in {"window", "relative"}:
            return unknown("profile_communication_temporal_mode_unsupported")
        if request.subject.kind != "entity":
            return unknown("profile_communication_subject_kind_unsupported")
        if request.page is not None and request.page.cursor is not None:
            return unknown("profile_communication_cursor_paging_unavailable")

        profile = identity.record if identity.available and identity.scope_known else None
        entity = (
            canonical_entity.record
            if canonical_entity.available and canonical_entity.scope_known
            else None
        )
        if (
            not isinstance(profile, dict)
            or profile.get("tenant_id") != request.tenantId
            or str(profile.get("user_id") or "") != request.subject.id
            or not isinstance(entity, dict)
            or entity.get("tenant_id") != request.tenantId
            or str(entity.get("entity_id") or "") != request.subject.id
            or entity.get("entity_type") != "human"
        ):
            return unknown("profile_communication_canonical_subject_unproven")

        reader = getattr(self._source, "communications_for_profile", None)
        if not callable(reader):
            return unknown("profile_communication_source_unavailable", state="degraded")
        limit = min(
            max(request.page.limit if request.page is not None else MAX_COMMUNICATION_LIMIT, 1),
            MAX_COMMUNICATION_LIMIT,
        )
        try:
            read = await reader(
                request.tenantId,
                request.subject,
                limit=limit,
                start=temporal.start,
            )
        except Exception:  # noqa: BLE001 - source errors stay content-free
            return unknown("profile_communication_source_unavailable", state="degraded")
        if not isinstance(read, CommunicationRead):
            return unknown("profile_communication_source_invalid_response", state="degraded")
        if not read.available:
            return unknown(
                read.reason or "profile_communication_source_unavailable", state="degraded"
            )
        if not read.scope_known:
            return unknown(read.reason or "profile_communication_scope_unknown")
        if not isinstance(read.rows, list) or len(read.rows) > limit:
            return unknown("profile_communication_source_limit_exceeded", state="degraded")

        items: list[dict[str, Any]] = []
        claims: list[ClaimEnvelope] = []
        incomplete_reasons: set[str] = set()
        for message in read.rows:
            if not isinstance(message, CommunicationMessage):
                return unknown("profile_communication_source_invalid_row")
            if message.tenant_id != request.tenantId:
                return unknown("profile_communication_source_scope_mismatch")
            if message.sender_entity_id != request.subject.id and message.recipient_entity_id != request.subject.id:
                return unknown("profile_communication_source_scope_mismatch")
            # This first slice covers the recipient side only. A sender-side
            # identity binding currently has no shared human-profile consent
            # bridge in the message contract.
            if message.recipient_entity_id != request.subject.id:
                incomplete_reasons.add("profile_communication_sender_identity_not_joined")
                continue
            binding_ref = message.recipient_identity_evidence_ref
            if not message.recipient_identity_binding_id:
                incomplete_reasons.add("profile_communication_identity_binding_missing")
                continue
            if (
                binding_ref is None
                or binding_ref.id != message.recipient_identity_binding_id
                or binding_ref.source != "comms_provider_identities"
                or binding_ref.uri
                != f"store://comms_provider_identities/{message.recipient_identity_binding_id}"
            ):
                incomplete_reasons.add("profile_communication_identity_binding_unproven")
                continue

            consent = message.consent_evidence
            consent_refs = list(getattr(consent, "evidence_refs", []) or [])
            receipt_id = _safe_text(getattr(consent, "receipt_id", None))
            consent_binding_id = _safe_text(getattr(consent, "identity_binding_id", None))
            consent_subject_id = _safe_text(getattr(consent, "subject_entity_id", None))
            purpose = _safe_text(getattr(consent, "purpose", None))
            consent_recorded = (
                getattr(getattr(consent, "state", None), "value", getattr(consent, "state", None))
                == "recorded"
                and consent_subject_id == request.subject.id
                and consent_binding_id == message.recipient_identity_binding_id
                and bool(receipt_id and purpose)
                and any(
                    ref.id == receipt_id
                    and ref.source == "governance.consent.authority"
                    and ref.uri == f"store://consent_receipts/{receipt_id}"
                    for ref in consent_refs
                )
                and any(
                    ref.id == consent_binding_id
                    and ref.source == "comms_provider_identities"
                    and ref.uri == f"store://comms_provider_identities/{consent_binding_id}"
                    for ref in consent_refs
                )
            )
            if not consent_recorded:
                incomplete_reasons.add("profile_communication_consent_evidence_unavailable")
                continue

            fact_id = _safe_text(message.fact_id)
            message_id = _safe_text(message.message_id)
            occurred_at = _safe_instant(message.occurred_at)
            message_ref = next(
                (
                    ref
                    for ref in message.evidence_refs
                    if fact_id is not None
                    and ref.id == fact_id
                    and ref.source == "services/api/journeys/comms/silver_comms_facts"
                    and ref.uri == f"store://silver_comms_facts/{fact_id}"
                ),
                None,
            )
            if (
                fact_id is None
                or message_id is None
                or occurred_at is None
                or message_ref is None
                or getattr(message.claim_state, "value", message.claim_state) != "observed"
            ):
                incomplete_reasons.add("profile_communication_message_provenance_incomplete")
                continue
            if not _within(occurred_at, temporal.start, temporal.end):
                if temporal.start is not None or temporal.end is not None:
                    continue

            evidence_refs = _dedupe_refs(
                [message_ref, binding_ref, *consent_refs]
            )
            item = {
                "messageId": message_id,
                "occurredAt": occurred_at,
                "channel": _safe_text(message.channel),
                "direction": _safe_text(message.direction),
                "communicationState": _safe_text(
                    getattr(message.communication_state, "value", message.communication_state)
                ),
                "consentPurpose": purpose,
                "evidenceRefs": [ref.model_dump(mode="json") for ref in evidence_refs],
            }
            items.append(item)
            claims.append(
                ClaimEnvelope(
                    id=f"profile360.communication.{message_id}",
                    kind="profile_recipient_communication",
                    subject=request.subject,
                    evidenceRefs=evidence_refs,
                    claims=[
                        f"Communication message {message_id} is linked to this exact profile as its consent-bound recipient."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=["communications"],
                )
            )

        if not items:
            reason = (
                sorted(incomplete_reasons)[0]
                if incomplete_reasons
                else "profile_communication_links_not_observed"
            )
            return unknown(reason, state="degraded" if read.truncated else "unknown")

        reasons = {
            "profile_communication_recipient_message_spine_only",
            *incomplete_reasons,
        }
        if read.truncated:
            reasons.add("profile_communication_read_truncated")
        return (
            ProjectionSection(
                id="interactions",
                state="degraded",
                title="Profile communication activity",
                content={
                    "coverage": "recipient_message_spine_with_recorded_consent_only",
                    "complete": False,
                    "count": len(items),
                    "items": items,
                    "reasonCodes": sorted(reasons),
                },
                warnings=sorted(reasons),
                canonicalAuthorityRefs=["communication_facts"],
            ),
            claims,
        )

    async def _session_history(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
        temporal: _TemporalRequest,
        identity: ProfileRead,
        canonical_entity: CanonicalEntityRead,
    ) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
        """Project resolved session identity observations, not SDK rollup ownership."""

        def unknown(reason: str, *, state: str = "unknown") -> tuple[ProjectionSection, list[ClaimEnvelope]]:
            return (
                ProjectionSection(
                    id="sessions",
                    state=state,  # type: ignore[arg-type]
                    title="Profile session identity history",
                    content={
                        "state": state,
                        "reasonCode": reason,
                        "coverage": "resolved_source_identity_links_only",
                    },
                    warnings=[reason],
                    canonicalAuthorityRefs=["identity"],
                ),
                [],
            )

        if context.tenantId != request.tenantId:
            return unknown("profile_session_tenant_scope_mismatch")
        if (
            request.asOf is not None
            or request.timeRange is not None
            or temporal.mode != "window"
            or temporal.error is not None
        ):
            return unknown("profile_session_temporal_history_unavailable")
        if request.subject.kind != "entity":
            return unknown("profile_session_subject_kind_unsupported")
        profile = identity.record if identity.available and identity.scope_known else None
        entity = (
            canonical_entity.record
            if canonical_entity.available and canonical_entity.scope_known
            else None
        )
        if (
            not isinstance(profile, dict)
            or profile.get("tenant_id") != request.tenantId
            or profile.get("user_id") != request.subject.id
            or not isinstance(entity, dict)
            or entity.get("tenant_id") != request.tenantId
            or entity.get("entity_id") != request.subject.id
            or entity.get("entity_type") != "human"
        ):
            return unknown("profile_session_canonical_subject_unproven")
        reader = getattr(self._source, "resolved_session_identities", None)
        if not callable(reader):
            return unknown("profile_session_identity_source_unavailable", state="degraded")
        limit = min(
            max(request.page.limit if request.page is not None else MAX_SESSION_IDENTITY_LIMIT, 1),
            MAX_SESSION_IDENTITY_LIMIT,
        )
        try:
            read = await reader(request.tenantId, request.subject, limit=limit)
        except Exception:  # noqa: BLE001 - source errors stay content-free
            return unknown("profile_session_identity_source_unavailable", state="degraded")
        if not isinstance(read, SessionIdentityRead):
            return unknown("profile_session_identity_source_invalid_response", state="degraded")
        if not read.available:
            return unknown(read.reason or "profile_session_identity_source_unavailable", state="degraded")
        if not read.scope_known:
            return unknown(read.reason or "profile_session_identity_scope_unknown")
        if not isinstance(read.rows, list) or len(read.rows) > limit:
            return unknown("profile_session_identity_source_limit_exceeded", state="degraded")

        items: list[dict[str, Any]] = []
        claims: list[ClaimEnvelope] = []
        seen: set[str] = set()
        for row in read.rows:
            if (
                not isinstance(row, dict)
                or row.get("tenant_id") != request.tenantId
                or row.get("canonical_entity_id") != request.subject.id
                or row.get("status") != "resolved"
            ):
                return unknown("profile_session_identity_scope_mismatch")
            source_id = _safe_text(row.get("id"))
            session_id = _safe_text(row.get("session_id"))
            source_namespace = _safe_text(row.get("source_namespace"))
            source_system_id = _safe_text(row.get("source_system_id"))
            if session_id is None:
                continue
            if source_id is None or source_namespace is None or source_system_id is None:
                return unknown("profile_session_identity_provenance_incomplete")
            if source_id in seen:
                return unknown("profile_session_identity_duplicate_source")
            seen.add(source_id)
            first_seen = _safe_instant(row.get("first_seen_at"))
            last_seen = _safe_instant(row.get("last_seen_at"))
            evidence_ref = EvidenceRef(
                id=source_id,
                type="document",
                source="identity_source_identities",
                observedAt=last_seen,
            )
            items.append(
                {
                    "sourceIdentityId": source_id,
                    "sourceNamespace": source_namespace,
                    "sourceSystemId": source_system_id,
                    "firstSeenAt": first_seen,
                    "lastSeenAt": last_seen,
                    "sessionIdentifierPresent": True,
                    "evidenceRef": evidence_ref.model_dump(mode="json"),
                }
            )
            claims.append(
                ClaimEnvelope(
                    id=f"profile360.session_identity.{source_id}",
                    kind="resolved_session_source_identity",
                    subject=request.subject,
                    evidenceRefs=[evidence_ref],
                    claims=[
                        "A resolved tenant-scoped source identity with a session identifier is linked to this canonical profile."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=["session_history"],
                )
            )
        if not items:
            return unknown("profile_session_identity_links_not_observed")
        reasons = ["profile_session_event_timeline_not_joined"]
        if read.truncated:
            reasons.append("profile_session_identity_read_capped")
        return (
            ProjectionSection(
                id="sessions",
                state="degraded",
                title="Profile session identity history",
                content={
                    "coverage": "resolved_source_identity_links_only",
                    "complete": False,
                    "count": len(items),
                    "items": items,
                },
                warnings=reasons,
                canonicalAuthorityRefs=["identity"],
            ),
            claims,
        )

    async def _journey_participation(
        self,
        request: ProjectionRequest,
        temporal: _TemporalRequest,
        identity: ProfileRead,
        canonical_entity: CanonicalEntityRead,
    ) -> tuple[ProjectionSection, list[ClaimEnvelope]]:
        """Project only current versions with an exact typed profile join."""

        def unknown(reason: str, *, state: str = "unknown") -> tuple[ProjectionSection, list[ClaimEnvelope]]:
            return (
                ProjectionSection(
                    id="journeys",
                    state=state,  # type: ignore[arg-type]
                    title="Profile journey participation",
                    content={"state": state, "reasonCode": reason, "currentOnly": True},
                    warnings=[reason],
                    canonicalAuthorityRefs=["journeys"],
                ),
                [],
            )

        if (
            request.asOf is not None
            or request.timeRange is not None
            or temporal.mode != "window"
            or temporal.error is not None
        ):
            return unknown("profile_journey_valid_time_unavailable")
        if request.subject.kind != "entity":
            return unknown("profile_journey_subject_kind_unsupported")
        identity_record = identity.record if identity.available and identity.scope_known else None
        entity_record = (
            canonical_entity.record
            if canonical_entity.available and canonical_entity.scope_known
            else None
        )
        if (
            not isinstance(identity_record, dict)
            or identity_record.get("tenant_id") != request.tenantId
            or identity_record.get("user_id") != request.subject.id
            or not isinstance(entity_record, dict)
            or entity_record.get("tenant_id") != request.tenantId
            or entity_record.get("entity_id") != request.subject.id
            or entity_record.get("entity_type") != "human"
        ):
            return unknown("profile_journey_canonical_subject_unproven")
        reader = getattr(self._source, "current_journeys", None)
        if not callable(reader):
            return unknown("profile_journey_source_unavailable", state="degraded")
        limit = min(
            max(request.page.limit if request.page is not None else MAX_JOURNEY_LIMIT, 1),
            MAX_JOURNEY_LIMIT,
        )
        try:
            read = await reader(request.tenantId, request.subject, limit=limit)
        except Exception:  # noqa: BLE001 - source failure stays content-free
            return unknown("profile_journey_source_unavailable", state="degraded")
        if not isinstance(read, JourneyRead):
            return unknown("profile_journey_source_invalid_response", state="degraded")
        if not read.available:
            return unknown(read.reason or "profile_journey_source_unavailable", state="degraded")
        if not read.scope_known:
            return unknown(read.reason or "profile_journey_source_scope_unknown")
        if not isinstance(read.rows, list) or len(read.rows) > limit:
            return unknown("profile_journey_source_limit_exceeded", state="degraded")

        items: list[dict[str, Any]] = []
        claims: list[ClaimEnvelope] = []
        missing_timestamp = False
        for row in read.rows:
            if (
                not isinstance(row, dict)
                or row.get("tenant_id") != request.tenantId
                or row.get("profile_id") != request.subject.id
                or row.get("journey_type") == "anonymous"
                or row.get("is_current") is not True
            ):
                return unknown("profile_journey_source_scope_mismatch")
            journey_id = _safe_text(row.get("journey_id"))
            version_id = _safe_text(row.get("journey_version_id"))
            if journey_id is None or version_id is None:
                return unknown("profile_journey_identity_incomplete")
            computed_at = row.get("computed_at")
            if isinstance(computed_at, datetime):
                try:
                    computed_at = to_iso_utc(computed_at)
                except ValueError:
                    computed_at = None
            if isinstance(computed_at, str):
                try:
                    computed_at = to_iso_utc(parse_instant_strict(computed_at))
                except ValueError:
                    computed_at = None
            else:
                computed_at = None
            if computed_at is None:
                missing_timestamp = True
            evidence_ref = EvidenceRef(
                id=version_id,
                type="document",
                source="journey_versions",
                observedAt=computed_at,
            )
            items.append(
                {
                    "journeyId": journey_id,
                    "versionId": version_id,
                    "journeyState": _safe_text(row.get("journey_state")),
                    "computedAt": computed_at,
                    "evidenceRef": evidence_ref.model_dump(mode="json"),
                }
            )
            claims.append(
                ClaimEnvelope(
                    id=f"profile360.journey.{version_id}",
                    kind="current_profile_journey_version",
                    subject=request.subject,
                    evidenceRefs=[evidence_ref],
                    claims=[
                        "A current tenant-scoped journey version records this exact typed profile ID."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=["journey_participation"],
                )
            )
        state = "degraded" if read.truncated or missing_timestamp else "available" if items else "empty"
        reasons = []
        if read.truncated:
            reasons.append("profile_journey_read_capped")
        if missing_timestamp:
            reasons.append("profile_journey_source_timestamp_missing")
        section = ProjectionSection(
            id="journeys",
            state=state,  # type: ignore[arg-type]
            title="Profile journey participation",
            content={
                "currentOnly": True,
                "complete": not read.truncated,
                "count": len(items),
                "items": items,
            },
            warnings=reasons or None,
            canonicalAuthorityRefs=["journeys"],
        )
        return section, claims

    async def _project_related_user_context(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
        temporal: _TemporalRequest,
    ) -> ProjectionResult:
        """Expose an exact current journey/episode-to-user profile relationship.

        A journey or episode is not re-labelled as a profile. This path emits
        only the relationship and minimal linked profile state needed by the
        Journey360 entity-context slot. Current links have no bitemporal proof,
        so historical or bounded requests remain unknown without reading the
        current relationship.
        """
        requested_sections = set(request.includeSections or OUTPUT_SECTIONS)
        if not {"summary", "state", "evidence"} & requested_sections:
            return self._related_context_result(
                request,
                context,
                state="unknown",
                reason="linked_profile_context_not_requested",
            )
        if (
            request.asOf is not None
            or request.timeRange is not None
            or temporal.mode != "window"
            or temporal.error is not None
        ):
            return self._related_context_result(
                request,
                context,
                state="unknown",
                reason="identity_binding_valid_time_unavailable",
            )

        try:
            binding = await self._source.identity_binding(request.tenantId, request.subject)
        except Exception as exc:  # noqa: BLE001 - relationship authority fails closed
            return self._related_context_result(
                request,
                context,
                state="degraded",
                reason=f"identity_binding_source_{type(exc).__name__}",
            )

        if not isinstance(binding, IdentityBindingRead):
            return self._related_context_result(
                request,
                context,
                state="unknown",
                reason="identity_binding_contract_invalid",
            )
        if binding.tenant_id != request.tenantId:
            return self._related_context_result(
                request,
                context,
                state="unknown",
                reason="identity_binding_tenant_mismatch",
            )
        if not binding.available:
            return self._related_context_result(
                request,
                context,
                state="degraded",
                reason=binding.reason or "identity_binding_authority_unavailable",
            )
        linked_subject = binding.resolved_subject
        relation_ref = binding.evidence_ref
        if (
            not binding.scope_known
            or linked_subject is None
            or linked_subject.kind != "entity"
            or relation_ref is None
            or not relation_ref.id.strip()
            or not relation_ref.source.strip()
        ):
            return self._related_context_result(
                request,
                context,
                state="unknown",
                reason=binding.reason or "identity_binding_unresolved_or_unproven",
                binding=binding,
            )

        try:
            profile = await self._source.identity_record(request.tenantId, linked_subject)
        except Exception as exc:  # noqa: BLE001 - profile authority fails closed
            return self._related_context_result(
                request,
                context,
                state="degraded",
                reason=f"identity_profile_source_{type(exc).__name__}",
                binding=binding,
            )
        record = profile.record if profile.available and profile.scope_known else None
        if (
            record is None
            or record.get("tenant_id") != request.tenantId
            or str(record.get("user_id") or "") != linked_subject.id
        ):
            state = "degraded" if not profile.available else "unknown"
            return self._related_context_result(
                request,
                context,
                state=state,
                reason=profile.reason or "identity_profile_scope_mismatch_or_not_found",
                binding=binding,
            )

        profile_ref = _profile_evidence(record)
        if profile_ref is None:
            return self._related_context_result(
                request,
                context,
                state="unknown",
                reason="identity_profile_evidence_missing",
                binding=binding,
            )
        return self._related_context_result(
            request,
            context,
            state="available",
            binding=binding,
            profile_id=linked_subject.id,
            profile_status=_safe_text(record.get("status")),
            evidence_refs=[relation_ref, profile_ref],
        )

    def _related_context_result(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
        *,
        state: str,
        reason: Optional[str] = None,
        binding: Optional[IdentityBindingRead] = None,
        profile_id: Optional[str] = None,
        profile_status: Optional[str] = None,
        evidence_refs: Optional[list[EvidenceRef]] = None,
    ) -> ProjectionResult:
        refs = _dedupe_refs(evidence_refs or [])
        relation_authority = (
            {"journey_versions": "journeys", "episode_records": "episode_facts"}.get(
                binding.authority if binding is not None else None
            )
        )
        section_authorities = (
            sorted({"identity", relation_authority})
            if state == "available" and profile_id is not None and relation_authority is not None
            else None
        )
        related_context = {
            "state": state,
            "requestSubject": {
                "kind": request.subject.kind,
                "id": request.subject.id,
            },
            "resolvedEntity": (
                {"kind": "entity", "id": profile_id, "status": profile_status}
                if profile_id is not None
                else None
            ),
            "relationship": binding.relationship if binding is not None else None,
            "authority": binding.authority if binding is not None else None,
            "evidenceRefs": [ref.model_dump(mode="json") for ref in refs],
            "interpretation": (
                "the entity is a linked user profile; it is not the journey or episode subject"
            ),
            "reason": reason,
        }
        generated_at = _utc_now_iso()
        sections = [
            ProjectionSection(
                id="evidence",
                state=state,  # type: ignore[arg-type]
                title="Journey or episode identity link evidence",
                content={
                    "count": len(refs) if state == "available" else None,
                    "evidence": [ref.model_dump(mode="json") for ref in refs],
                    "relatedEntityContext": related_context,
                },
                canonicalAuthorityRefs=section_authorities,
            ),
            ProjectionSection(
                id="findings",
                state="not_applicable",
                title="Profile findings",
                content={"reason": "only linked identity context is projected for this subject"},
            ),
            ProjectionSection(
                id="interactions",
                state="not_applicable",
                title="Profile interactions",
                content={"reason": "only linked identity context is projected for this subject"},
            ),
            ProjectionSection(
                id="state",
                state=state,  # type: ignore[arg-type]
                title="Linked user profile context",
                content={
                    "dimensions": [
                        {
                            "id": "related_user_profile",
                            "state": state,
                            "content": related_context,
                        }
                    ]
                },
                canonicalAuthorityRefs=section_authorities,
            ),
            ProjectionSection(
                id="summary",
                state=state,  # type: ignore[arg-type]
                title="Linked user profile context",
                content={
                    "subject": {
                        "kind": request.subject.kind,
                        "id": request.subject.id,
                    },
                    "relatedEntityContext": related_context,
                },
                canonicalAuthorityRefs=section_authorities,
            ),
            ProjectionSection(
                id="timeline",
                state="not_applicable",
                title="Profile timeline",
                content={"reason": "profile history is not substituted for journey or episode history"},
            ),
        ]
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=sections,
            claims=[],
            dependencyState=list(context.dependencyState),
            asOf=None,
            generatedAt=generated_at,
            degradedReasons=([] if state in {"available", "unknown"} else [reason or "related_context_degraded"]),
            temporalMode=request.temporalMode or "window",
            lensIds=request.lensIds,
        )

    def _result(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
        temporal: _TemporalRequest,
        identity: ProfileRead,
        canonical_entity: CanonicalEntityRead,
        events: EventRead,
        history: HistoryRead,
        *,
        limit: int,
    ) -> ProjectionResult:
        record = identity.record if identity.available and identity.scope_known else None
        if record is not None and (
            record.get("tenant_id") != request.tenantId
            or request.subject.kind != "entity"
            or str(record.get("user_id") or "") != request.subject.id
        ):
            record = None
            identity = ProfileRead(
                record=None, available=True, scope_known=False,
                reason=(
                    "identity_record_tenant_mismatch"
                    if identity.record is not None
                    and identity.record.get("tenant_id") != request.tenantId
                    else "identity_record_subject_mismatch"
                ),
            )

        entity_record = (
            canonical_entity.record
            if canonical_entity.available and canonical_entity.scope_known
            else None
        )
        if entity_record is not None and (
            entity_record.get("tenant_id") != request.tenantId
            or str(entity_record.get("entity_id") or "") != request.subject.id
            or request.subject.kind != "entity"
        ):
            entity_record = None
            canonical_entity = CanonicalEntityRead(
                record=None,
                available=True,
                scope_known=False,
                reason="entity_registry_scope_mismatch",
            )

        scoped_events = [
            row
            for row in events.rows
            if isinstance(row, dict)
            and row.get("tenant_id") == request.tenantId
            and str(row.get("canonical_entity_id") or "") == request.subject.id
        ]
        if len(scoped_events) != len(events.rows):
            events = EventRead(
                rows=[],
                available=True,
                scope_known=False,
                reason="analytics_row_scope_mismatch",
            )
            scoped_events = []
        if len(scoped_events) > limit:
            scoped_events = scoped_events[:limit]
            events = EventRead(
                rows=scoped_events,
                available=True,
                scope_known=True,
                truncated=True,
            )

        history_obj = history.history if history.available else None
        historical = temporal.as_of is not None
        graph_events = list(history_obj.events) if history_obj is not None else []
        if temporal.start is not None or temporal.end is not None:
            # For graph mutations, ``valid_from`` is the only valid-time field.
            # Events without it are excluded from a bounded valid-time view.
            graph_events = [
                event
                for event in graph_events
                if _within(event.valid_from, temporal.start, temporal.end)
            ]

        refs: list[EvidenceRef] = []
        profile_ref = _profile_evidence(record) if record else None
        if profile_ref:
            refs.append(profile_ref)
        entity_ref = _entity_evidence(entity_record) if entity_record else None
        if entity_ref:
            refs.append(entity_ref)
        event_refs = {
            id(row): _event_evidence(row) for row in scoped_events
        }
        for ref in event_refs.values():
            if ref:
                refs.append(ref)
        mutation_refs = {
            id(event): _mutation_evidence(event) for event in graph_events
        }
        for ref in mutation_refs.values():
            if ref:
                refs.append(ref)
        refs = _dedupe_refs(refs)

        profile_state = (
            "degraded"
            if not identity.available
            else "available"
            if record is not None
            else "unknown"
        )
        entity_state = (
            "degraded"
            if not canonical_entity.available
            else "available"
            if entity_record is not None
            else "unknown"
        )
        subject_known = bool(
            record is not None
            or entity_record is not None
            or (
                history_obj is not None
                and (history_obj.present or history_obj.event_count > 0)
            )
        )
        event_state = (
            "degraded"
            if not events.available
            else "unknown"
            if not events.scope_known
            else "available"
            if scoped_events
            else "empty"
            if subject_known
            else "unknown"
        )
        history_state = (
            "degraded"
            if not history.available
            else "available"
            if history_obj is not None and (history_obj.present or history_obj.event_count)
            else "unknown"
        )
        freshness_state = "unknown"

        summary_state = (
            "degraded"
            if profile_state == "degraded"
            or (record is not None and entity_state != "available")
            else "available"
            if record is not None
            else "unknown"
        )
        if temporal.error is not None:
            summary_state = "degraded"
        state_state = (
            "degraded"
            if "degraded" in {profile_state, entity_state, event_state, history_state}
            else "available"
            if "available" in {profile_state, entity_state, event_state, history_state}
            else "unknown"
        )
        if freshness_state == "unknown" and state_state == "available":
            state_state = "degraded"

        limited_profile = _safe_profile(record) if record else None
        identity_content = {
            "state": profile_state,
            "record": limited_profile,
            "source": "identity_profiles" if record else None,
            "evidenceRef": profile_ref.model_dump() if profile_ref else None,
            "canonicalEntity": {
                "state": entity_state,
                "record": _safe_entity(entity_record) if entity_record else None,
                "source": "entity_registry" if entity_record else None,
                "evidenceRef": entity_ref.model_dump() if entity_ref else None,
                "freshness": {
                    "state": "unknown",
                    "observedAt": (
                        _safe_text(entity_record.get("updated_at") or entity_record.get("created_at"))
                        if entity_record
                        else None
                    ),
                    "ageSeconds": _age_seconds(
                        _safe_text(entity_record.get("updated_at") or entity_record.get("created_at"))
                        if entity_record
                        else None
                    ),
                    "policy": "not_evaluated",
                },
                "reason": canonical_entity.reason,
            },
            "canonicalResolution": {
                "state": entity_state,
                "authority": "entity_registry",
                "scope": "exact_tenant_and_entity_id_only",
                "reason": (
                    "exact_tenant_entity_id_match"
                    if entity_state == "available"
                    else canonical_entity.reason
                    or "arbitrary_identifier_resolution_not_performed"
                ),
            },
            "reason": identity.reason,
        }

        timeline_items: list[dict[str, Any]] = []
        for row in scoped_events:
            evidence_ref = event_refs.get(id(row))
            timeline_items.append(
                {
                    "kind": "observation",
                    "id": evidence_ref.id if evidence_ref else None,
                    "eventType": _safe_text(row.get("event_type")),
                    "timestamp": _safe_text(row.get("occurred_at") or row.get("created_at")),
                    "timeBasis": "occurred_at" if row.get("occurred_at") else "created_at",
                    "source": "analytics_events",
                    "evidenceRef": evidence_ref.model_dump() if evidence_ref else None,
                }
            )
        for event in graph_events:
            evidence_ref = mutation_refs.get(id(event))
            timeline_items.append(
                {
                    "kind": "graph_mutation",
                    "id": evidence_ref.id if evidence_ref else None,
                    "eventType": _safe_text(event.kind),
                    "operation": _safe_text(event.operation),
                    "recordedAt": _safe_text(event.recorded_at),
                    "validAt": _safe_text(event.valid_from),
                    "timeBasis": "valid_from" if event.valid_from else "recorded_at",
                    "source": "graph_mutation_ledger",
                    "evidenceRef": evidence_ref.model_dump() if evidence_ref else None,
                    "changedPropertyNames": sorted((event.changed or {}).keys()),
                }
            )
        timeline_items.sort(
            key=lambda item: (
                _safe_text(item.get("timestamp") or item.get("validAt") or item.get("recordedAt"))
                or "",
                _safe_text(item.get("id")) or "",
            )
        )

        evidence_state = "available" if refs else "unknown"
        evidence_content = {
            "state": evidence_state,
            "references": [ref.model_dump() for ref in refs],
            "coverage": {
                "identity": profile_state,
                "canonicalEntity": entity_state,
                "observations": event_state,
                "graphHistory": history_state,
            },
            "limitations": [
                "profile freshness policy is not available to this provider",
                "field-level policy/redaction is applied by the governed frame boundary",
                "communication activity joins only exact recipient messages with recorded consent and does not establish semantic interaction meaning",
                "session history and profile fanout slots require their own canonical authorities",
                "no separate evidence index is wired; references identify their canonical source records",
            ],
        }

        findings: list[dict[str, Any]] = [
            {
                "code": "profile_freshness_unknown",
                "state": "unknown",
                "authority": "profile_freshness_policy",
                "reason": "No profile freshness threshold or freshness authority is bound to this provider.",
            },
            {
                "code": "semantic_interactions_unavailable",
                "state": "unknown",
                "authority": "interaction_facts",
                "reason": "Message lifecycle observations and graph mutations do not establish semantic user interactions.",
            },
            {
                "code": "session_history_unknown",
                "state": "unknown",
                "authority": "session_facts",
                "reason": "Observed events and graph mutations do not establish canonical session membership or continuity.",
            },
            {
                "code": "profile_fanout_unknown",
                "state": "unknown",
                "authority": "identity_relationship_facts",
                "reason": "This provider does not enumerate member, agent, account, wallet-cluster, or other linked profiles.",
            },
        ]
        if entity_state != "available":
            findings.append(
                {
                    "code": "canonical_entity_resolution_unknown",
                    "state": "degraded" if entity_state == "degraded" else "unknown",
                    "authority": "entity_registry",
                    "reason": canonical_entity.reason
                    or "This provider does not resolve arbitrary identifiers to canonical entities.",
                }
            )
        if identity.reason:
            findings.append(
                {
                    "code": "identity_source_limitation",
                    "state": "unknown" if identity.available else "degraded",
                    "reason": identity.reason,
                }
            )
        if events.reason:
            findings.append(
                {
                    "code": "observation_source_limitation",
                    "state": "unknown" if events.available else "degraded",
                    "reason": events.reason,
                }
            )
        if canonical_entity.reason:
            findings.append(
                {
                    "code": "canonical_entity_source_limitation",
                    "state": "unknown" if canonical_entity.available else "degraded",
                    "authority": "entity_registry",
                    "reason": canonical_entity.reason,
                }
            )
        if history.reason:
            findings.append(
                {
                    "code": "graph_history_limitation",
                    "state": "degraded",
                    "reason": history.reason,
                }
            )
        if temporal.error:
            findings.append(
                {
                    "code": "temporal_request_not_satisfied",
                    "state": "degraded",
                    "reason": temporal.error,
                }
            )
        if events.truncated:
            findings.append(
                {
                    "code": "observation_timeline_truncated",
                    "state": "degraded",
                    "limit": limit,
                }
            )

        requested_sections = set(request.includeSections or OUTPUT_SECTIONS)
        activity_requested = bool({"timeline", "evidence"} & requested_sections)
        identity_authorities: set[str] = set()
        if (
            not historical
            and temporal.error is None
            and request.subject.kind == "entity"
        ):
            if identity.reason != "identity_profile_not_requested":
                identity_authorities.add("identity")
            if canonical_entity.reason != "entity_registry_not_requested":
                identity_authorities.add("entity_registry")
        identity_source_refs = sorted(identity_authorities) or None
        activity_authorities: set[str] = set()
        if activity_requested and not historical and temporal.error is None:
            activity_authorities.add("observations")
        if (
            activity_requested
            and history.available
            and history.reason != "graph_history_not_requested"
            and temporal.error is None
        ):
            activity_authorities.update({"graph", "temporal"})
        timeline_source_refs = sorted(activity_authorities) or None
        evidence_source_refs = (
            sorted(set(identity_source_refs or []) | activity_authorities) or None
        )

        sections = [
            ProjectionSection(
                id="evidence",
                state=evidence_state,
                title="Evidence and coverage",
                content=evidence_content,
                canonicalAuthorityRefs=evidence_source_refs,
            ),
            ProjectionSection(
                id="findings",
                state="available",
                title="Known limitations",
                content={"items": findings},
            ),
            ProjectionSection(
                id="interactions",
                state="unknown",
                title="Profile communication activity",
                content={
                    "state": "unknown",
                    "items": [],
                    "reason": "No policy-authorized exact recipient message link was read for this request.",
                },
            ),
            ProjectionSection(
                id="state",
                state=state_state,
                title="Profile identity and resolution state",
                content={
                    "dimensions": [
                        {
                            "id": "identity",
                            "state": profile_state,
                            "reason": identity.reason,
                            "freshness": {
                                "state": freshness_state,
                                "observedAt": _safe_text(record.get("updated_at")) if record else None,
                                "ageSeconds": _age_seconds(
                                    _safe_text(record.get("updated_at")) if record else None
                                ),
                                "policy": "not_evaluated",
                            },
                        },
                        {
                            "id": SLOT_KNOWN_UNKNOWN_RESOLUTION,
                            "state": entity_state,
                            "authority": "entity_registry",
                            "resolution": identity_content["canonicalResolution"],
                            "reason": canonical_entity.reason,
                            "freshness": {
                                "state": "unknown",
                                "observedAt": (
                                    _safe_text(entity_record.get("updated_at") or entity_record.get("created_at"))
                                    if entity_record
                                    else None
                                ),
                                "ageSeconds": _age_seconds(
                                    _safe_text(entity_record.get("updated_at") or entity_record.get("created_at"))
                                    if entity_record
                                    else None
                                ),
                                "policy": "not_evaluated",
                            },
                        },
                        {
                            "id": "freshness",
                            "state": "unknown",
                            "reason": "No canonical Profile360 freshness policy is available.",
                        },
                        {
                            "id": "session_history",
                            "state": "unknown",
                            "reason": "Observed events are not a canonical session-continuity record.",
                        },
                    ],
                    "temporalMode": temporal.mode,
                    "requestedAsOf": temporal.as_of,
                },
                canonicalAuthorityRefs=identity_source_refs,
            ),
            ProjectionSection(
                id="summary",
                state=summary_state,
                title="Profile summary",
                content={
                    "subject": request.subject.model_dump(),
                    "identity": identity_content,
                    "sessionHistory": {
                        "state": "unknown",
                        "reason": "No canonical session identity or continuity authority is bound to Profile360.",
                    },
                    "temporalMode": temporal.mode,
                    "asOf": temporal.as_of,
                    "freshness": {
                        "state": "unknown",
                        "reason": "No canonical Profile360 freshness policy is available.",
                    },
                },
                warnings=[temporal.error] if temporal.error else None,
                canonicalAuthorityRefs=identity_source_refs,
            ),
            ProjectionSection(
                id="timeline",
                state=(
                    "degraded"
                    if (
                        not history.available
                        or temporal.error
                        or (not historical and not events.available)
                    )
                    else "available"
                    if timeline_items
                    else "empty"
                    if subject_known
                    else "unknown"
                ),
                title="Observed activity and graph history",
                content={
                    "items": timeline_items,
                    "temporalMode": temporal.mode,
                    "window": {"from": temporal.start, "to": temporal.end},
                    "asOf": temporal.as_of,
                    "limit": limit,
                    "truncated": events.truncated if events.available else None,
                    "timeBasisNote": (
                        "Analytics observations use occurrence time when present; graph mutations "
                        "retain their valid-time and recorded-time labels."
                    ),
                },
                canonicalAuthorityRefs=timeline_source_refs,
            ),
        ]

        claims: list[ClaimEnvelope] = []
        if record is not None and profile_ref is not None:
            claims.append(
                ClaimEnvelope(
                    id="profile360.identity_record_present",
                    kind="identity_record",
                    subject=request.subject,
                    evidenceRefs=[profile_ref],
                    claims=[
                        "A tenant-scoped identity profile record is present for this exact subject ID."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=[SLOT_ENTITY_IDENTITY],
                )
            )
        if entity_record is not None and entity_ref is not None:
            claims.append(
                ClaimEnvelope(
                    id="profile360.canonical_entity_record_present",
                    kind="canonical_entity_record",
                    subject=request.subject,
                    evidenceRefs=[entity_ref],
                    claims=[
                        "A canonical entity registry record exists for this exact tenant and entity ID."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=[SLOT_ENTITY_IDENTITY, SLOT_KNOWN_UNKNOWN_RESOLUTION],
                )
            )
        activity_refs = [
            ref
            for ref in [*event_refs.values(), *mutation_refs.values()]
            if ref is not None
        ]
        if activity_refs:
            claims.append(
                ClaimEnvelope(
                    id="profile360.activity_records_observed",
                    kind="observed_activity_coverage",
                    subject=request.subject,
                    evidenceRefs=_dedupe_refs(activity_refs),
                    claims=[
                        "The listed tenant-scoped observation and graph-ledger records were returned by their named authorities."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=[SLOT_EVIDENCE_LIMITATIONS],
                )
            )
        if refs:
            claims.append(
                ClaimEnvelope(
                    id="profile360.evidence_coverage",
                    kind="evidence_coverage",
                    subject=request.subject,
                    evidenceRefs=refs,
                    claims=[
                        "These references identify the canonical records used by this Profile360 projection."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=[SLOT_EVIDENCE_LIMITATIONS],
                )
            )

        return ProjectionResult(
            projectionId=PROJECTION_ID,
            tenantId=request.tenantId,
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=sections,
            claims=claims,
            dependencyState=list(context.dependencyState),
            asOf=temporal.as_of,
            generatedAt=_utc_now_iso(),
            degradedReasons=[],
            temporalMode=temporal.mode,
            lensIds=request.lensIds,
        )


async def _read_profile_and_events(
    source: Profile360Source,
    tenant_id: str,
    subject: ProjectionSubject,
    *,
    limit: int,
    start: Optional[str],
    end: Optional[str],
    include_identity: bool = True,
    include_entity: bool = True,
    include_events: bool = True,
) -> tuple[ProfileRead, CanonicalEntityRead, EventRead]:
    """Isolate independent canonical identity and observation reads."""

    async def read_identity() -> ProfileRead:
        if not include_identity:
            return ProfileRead(
                record=None,
                available=True,
                scope_known=False,
                reason="identity_profile_not_requested",
            )
        try:
            return await source.identity_record(tenant_id, subject)
        except Exception as exc:  # noqa: BLE001 - isolate source failure
            return ProfileRead(
                record=None,
                available=False,
                scope_known=False,
                reason=f"identity_source_{type(exc).__name__}",
            )

    async def read_entity() -> CanonicalEntityRead:
        if not include_entity:
            return CanonicalEntityRead(
                record=None,
                available=True,
                scope_known=False,
                reason="entity_registry_not_requested",
            )
        try:
            return await source.canonical_entity(tenant_id, subject)
        except Exception as exc:  # noqa: BLE001 - isolate source failure
            return CanonicalEntityRead(
                record=None,
                available=False,
                scope_known=False,
                reason=f"entity_registry_source_{type(exc).__name__}",
            )

    async def read_events() -> EventRead:
        if not include_events:
            return EventRead(
                rows=[],
                available=True,
                scope_known=False,
                reason="analytics_events_not_requested",
            )
        try:
            return await source.analytics_events(
                tenant_id, subject, limit=limit, start=start, end=end
            )
        except Exception as exc:  # noqa: BLE001 - isolate source failure
            return EventRead(
                rows=[],
                available=False,
                scope_known=False,
                reason=f"analytics_source_{type(exc).__name__}",
            )

    return await asyncio.gather(read_identity(), read_entity(), read_events())


async def _safe_history(
    source: Profile360Source,
    tenant_id: str,
    subject_id: str,
    *,
    as_of: Optional[str],
) -> HistoryRead:
    try:
        return await source.subject_history(
            tenant_id, subject_id, as_of=as_of
        )
    except Exception as exc:  # noqa: BLE001 - isolate temporal source failure
        return HistoryRead(
            history=None,
            available=False,
            reason=f"graph_history_source_{type(exc).__name__}",
        )


def _filter_projection_result(
    result: ProjectionResult, request: ProjectionRequest
) -> ProjectionResult:
    """Return only requested sections and claims to preserve slot read scope."""
    updates: dict[str, Any] = {}
    if request.includeSections is not None:
        requested = set(request.includeSections)
        updates["sections"] = [
            section for section in result.sections if section.id in requested
        ]
    if request.includeClaims is False:
        updates["claims"] = []
    return result.model_copy(update=updates) if updates else result


def register_provider(registry: ProviderRegistry) -> None:
    """Register Profile360 explicitly; importing the module never registers it."""
    registry.register(Profile360Provider(), source="services/api/identity/profile")


__all__ = [
    "EventRead",
    "HistoryRead",
    "OUTPUT_SECTIONS",
    "PROJECTION_ID",
    "Profile360Provider",
    "Profile360Source",
    "ProfileRead",
    "RepositoryProfile360Source",
    "register_provider",
]
