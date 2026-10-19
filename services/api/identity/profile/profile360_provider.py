"""Read-only Profile360 projection over existing identity and temporal stores.

This provider is deliberately narrower than the legacy Kyber profile route.
It reads the tenant-scoped identity profile repository, tenant-scoped analytics
events, and ``graph_history_replay``. It does not resolve arbitrary identifiers,
compute risk, join financial/outcome projections, infer semantic interactions,
or evaluate field-level policy. Missing authorities remain explicit in the
section states and findings.

Historical requests use only ``GraphHistoryReplay`` at the requested knowledge
instant. Current identity rows and analytics events are never presented as
historical facts. For ``window`` and bounded ``relative`` requests, analytics
events use their canonical occurrence timestamps; graph ledger transitions
are filtered by valid-time when bounded and labelled as ledger transitions.
"""

from __future__ import annotations

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
)
from shared.intelligence_projections.provider import IntelligenceProjectionProvider
from shared.intelligence_projections.registry import ProviderRegistry
from shared.temporal.instant import parse_instant_strict, to_iso_utc
from graph.operational_intelligence.models import EvidenceRef
from graph.temporal360.history_replay import GraphHistoryReplay, SubjectHistory


PROJECTION_ID = "profile360"

# Exact generated-registry outputSections order for profile360.
OUTPUT_SECTIONS: tuple[str, ...] = (
    "evidence",
    "findings",
    "interactions",
    "state",
    "summary",
    "timeline",
)

SLOT_ENTITY_IDENTITY = "entity_identity"
SLOT_EVIDENCE_LIMITATIONS = "evidence_and_limitations"
SLOT_OBSERVED_ACTIVITY = "observed_state_and_activity"

DEFAULT_EVENT_LIMIT = 200
MAX_EVENT_LIMIT = 500


@dataclass(frozen=True)
class ProfileRead:
    """Identity-profile read with availability distinct from no matching row."""

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
    """Read-only intelligence-projection provider for the profile360 contract."""

    projection_id = PROJECTION_ID
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    graph_mutation_policy = "read_only"

    def __init__(self, source: Optional[Profile360Source] = None) -> None:
        self._source = source if source is not None else RepositoryProfile360Source()

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        """Compose tenant-scoped identity, observation and temporal evidence."""
        temporal = _temporal_request(request)
        limit = min(
            max(request.page.limit if request.page is not None else DEFAULT_EVENT_LIMIT, 1),
            MAX_EVENT_LIMIT,
        )

        if request.subject.kind in {"journey", "episode"}:
            return await self._project_related_user_context(request, context, temporal)

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
            history_subject_id = request.subject.id
        elif temporal.error is None:
            identity, events = await _read_profile_and_events(
                self._source,
                request.tenantId,
                request.subject,
                limit=limit,
                start=temporal.start,
                end=temporal.end,
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
            history_subject_id = request.subject.id

        if historical or temporal.error is None:
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
            history = await _safe_history(
                self._source,
                request.tenantId,
                history_subject_id,
                as_of=temporal.as_of,
            )
        else:
            history = HistoryRead(
                history=None,
                available=False,
                reason=temporal.error,
            )

        return self._result(
            request,
            context,
            temporal,
            identity,
            events,
            history,
            limit=limit,
        )

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
        events: EventRead,
        history: HistoryRead,
        *,
        limit: int,
    ) -> ProjectionResult:
        record = identity.record if identity.available and identity.scope_known else None
        if record is not None and record.get("tenant_id") != request.tenantId:
            record = None
            identity = ProfileRead(
                record=None,
                available=True,
                scope_known=False,
                reason="identity_record_tenant_mismatch",
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
        subject_known = bool(
            record is not None
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
            else "available"
            if record is not None
            else "unknown"
        )
        if temporal.error is not None:
            summary_state = "degraded"
        state_state = (
            "degraded"
            if "degraded" in {profile_state, event_state, history_state}
            else "available"
            if "available" in {profile_state, event_state, history_state}
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
            "canonicalResolution": {
                "state": "unknown",
                "authority": "entity_registry",
                "reason": "This provider reads an exact profile key but does not resolve arbitrary entity identifiers.",
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
                "observations": event_state,
                "graphHistory": history_state,
            },
            "limitations": [
                "profile freshness policy is not available to this provider",
                "field-level policy/redaction is applied by the governed frame boundary",
                "no semantic interaction authority is wired to profile360",
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
                "reason": "Graph mutations are not promoted to semantic user interactions.",
            },
            {
                "code": "canonical_entity_resolution_unknown",
                "state": "unknown",
                "authority": "entity_registry",
                "reason": "The provider does not perform arbitrary identifier-to-entity resolution.",
            },
        ]
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

        sections = [
            ProjectionSection(
                id="evidence",
                state=evidence_state,
                title="Evidence and coverage",
                content=evidence_content,
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
                title="Interactions",
                content={
                    "state": "unknown",
                    "items": [],
                    "reason": "No semantic interaction source is bound to Profile360.",
                },
            ),
            ProjectionSection(
                id="state",
                state=state_state,
                title="Observed profile state",
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
                            "id": "observations",
                            "state": event_state,
                            "returned": len(scoped_events) if events.available and events.scope_known else None,
                            "truncated": events.truncated if events.available and events.scope_known else None,
                            "reason": events.reason,
                        },
                        {
                            "id": "graph_history",
                            "state": history_state,
                            "known": (
                                True
                                if history_obj is not None
                                and (history_obj.present or history_obj.event_count > 0)
                                else None
                            ),
                            "asOf": temporal.as_of,
                            "reason": history.reason,
                        },
                        {
                            "id": "freshness",
                            "state": "unknown",
                            "reason": "No canonical Profile360 freshness policy is available.",
                        },
                    ],
                    "temporalMode": temporal.mode,
                    "requestedAsOf": temporal.as_of,
                },
            ),
            ProjectionSection(
                id="summary",
                state=summary_state,
                title="Profile summary",
                content={
                    "subject": request.subject.model_dump(),
                    "identity": identity_content,
                    "temporalMode": temporal.mode,
                    "asOf": temporal.as_of,
                    "freshness": {
                        "state": "unknown",
                        "reason": "No canonical Profile360 freshness policy is available.",
                    },
                },
                warnings=[temporal.error] if temporal.error else None,
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
                    domainSlotIds=[SLOT_OBSERVED_ACTIVITY, SLOT_EVIDENCE_LIMITATIONS],
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
) -> tuple[ProfileRead, EventRead]:
    """Isolate independent identity and observation reads."""
    try:
        identity = await source.identity_record(tenant_id, subject)
    except Exception as exc:  # noqa: BLE001 - isolate source failure
        identity = ProfileRead(
            record=None,
            available=False,
            scope_known=False,
            reason=f"identity_source_{type(exc).__name__}",
        )
    try:
        events = await source.analytics_events(
            tenant_id, subject, limit=limit, start=start, end=end
        )
    except Exception as exc:  # noqa: BLE001 - isolate source failure
        events = EventRead(
            rows=[],
            available=False,
            scope_known=False,
            reason=f"analytics_source_{type(exc).__name__}",
        )
    return identity, events


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
