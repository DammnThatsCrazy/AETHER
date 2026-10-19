"""Bounded Support360 projection over canonical support communication facts.

The only durable support authority currently available is the tenant-scoped
``silver_comms_facts`` communication store. This provider reads the exact
support category for a canonical entity through ``CommsFactsRepository.list_for_entity``
and then retains only rows whose ``recipient_entity_id`` exactly matches. It
exposes event metadata with evidence. It does not claim that a
``support_case_id`` is a canonical case, infer a case lifecycle, attach a
journey, or infer an outcome.

The repository's entity query can select on ``profile_id``,
``recipient_entity_id`` and ``user_id``; this provider accepts only the
canonical ``recipient_entity_id`` match and treats all other candidate joins
as unbound. Sender-side joins, agent subjects, episode subjects, and source
subjects are therefore reported as unknown until the canonical repository
exposes exact joins for them. A reachable partial read is marked degraded
rather than complete.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Protocol
from urllib.parse import quote

from graph.operational_intelligence.models import EvidenceRef
from shared.intelligence_projections.contracts import (
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
_REASON_CASE_AUTHORITY_MISSING = "canonical_support_case_authority_unavailable"
_REASON_JOURNEY_JOIN_MISSING = "canonical_support_case_journey_join_unavailable"
_REASON_OUTCOME_JOIN_MISSING = "canonical_support_outcome_join_unavailable"


@dataclass(frozen=True)
class SupportFactsRead:
    """One exact scoped read with explicit availability and completeness."""

    rows: list[dict[str, Any]]
    available: bool
    truncated: bool = False
    reason: Optional[str] = None
    next_cursor: Optional[str] = None


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


class RepositorySupport360Source:
    """Adapter over the canonical communication fact repository."""

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
            from journeys.comms.repository import CommsFactsRepository

            rows, next_cursor = await CommsFactsRepository().list_for_entity(
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
            next_cursor=next_cursor,
        )


class Support360Provider(IntelligenceProjectionProvider):
    """Read-only Support360 provider with explicit unresolved case/journey state."""

    projection_id = PROJECTION_ID
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    def __init__(self, source: Optional[Support360Source] = None) -> None:
        self._source = source if source is not None else RepositorySupport360Source()

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

        if request.subject.kind != "entity":
            return self._unknown_result(request, context, _REASON_UNSUPPORTED_SUBJECT)

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
        try:
            read = await self._source.support_facts_for_entity(
                request.tenantId,
                request.subject.id,
                limit=limit,
                after=after,
                before=before,
                cursor=request.page.cursor if request.page is not None else None,
            )
        except Exception:  # noqa: BLE001 - injected source is a fail-isolated seam
            read = SupportFactsRead(
                rows=[],
                available=False,
                reason=_REASON_SOURCE_UNAVAILABLE,
            )

        source_rows = read.rows if read.available and isinstance(read.rows, list) else []
        rows = [
            row
            for row in source_rows
            if isinstance(row, dict)
            if row.get("tenant_id") == request.tenantId
            and _text(row.get("message_category")) == "support"
            and _entity_row_matches(row, request.subject.id)
            and _row_in_window(row, after=after, before=before)
        ]
        rows.sort(key=lambda row: str(row.get("occurred_at") or ""))

        read_reasons: list[str] = []
        if not read.available:
            read_reasons.append(_REASON_SOURCE_UNAVAILABLE)
        if read.truncated:
            read_reasons.append(_REASON_READ_TRUNCATED)
        # The canonical repository's lookup has candidate profile/user joins,
        # but this provider accepts only recipient_entity_id. Sender-side and
        # other exact identity mappings remain unbound.
        read_reasons.append(_REASON_PARTIAL_ENTITY_JOIN)

        evidence = [_row_evidence(row) for row in rows]
        evidence_refs = [ref for ref in evidence if ref is not None]
        events = [_timeline_entry(row, ref) for row, ref in zip(rows, evidence, strict=False) if ref]
        support_case_refs = _source_reported_case_refs(rows, evidence_refs)
        read_state = (
            "unknown"
            if not read.available
            else "degraded"
            if read.truncated or rows
            else "empty"
        )
        if not read.available:
            read_state = "unknown"
        state_content = {
            "supportCommunications": {
                "state": read_state,
                "subjectJoin": "recipient_entity_id_exact_match",
                "observedCount": len(rows) if read.available else None,
                "reasonCodes": sorted(set(read_reasons)),
            },
            "supportCases": {
                "state": "unknown",
                "reasonCode": _REASON_CASE_AUTHORITY_MISSING,
                "sourceReportedReferenceCount": (
                    len(support_case_refs) if read.available else None
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
                "tenantScoped": True,
            },
            "observedSupportCommunicationCount": len(rows) if read.available else None,
            "sourceReportedCaseReferenceCount": (
                len(support_case_refs) if read.available else None
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
        }
        interaction_content = {
            "count": len(events),
            "factIds": [event["factId"] for event in events],
            "categoryFilter": "support",
        }
        section_state = (
            "unknown"
            if not read.available
            else "degraded"
            if rows or read.truncated
            else "empty"
        )
        if not read.available:
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
                canonicalAuthorityRefs=["communication_facts", "evidence"],
            )
            for section_id, state, content in zip(OUTPUT_SECTIONS, states, section_content, strict=True)
        ]
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=sections,
            claims=[],
            dependencyState=list(context.dependencyState),
            generatedAt=datetime.now(timezone.utc).isoformat(),
            degradedReasons=sorted(set(read_reasons)) if read_reasons else [],
            page=PageInfo(
                nextCursor=read.next_cursor,
                hasNextPage=read.truncated or read.next_cursor is not None,
            ),
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
                    }
                    if section_id == "state"
                    else None
                ),
                warnings=[reason],
                canonicalAuthorityRefs=["communication_facts", "evidence"],
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


def _row_in_window(
    row: dict[str, Any], *, after: Optional[str], before: Optional[str]
) -> bool:
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
        if (timestamp := _safe_reference(_text(row.get("received_at")) or _text(row.get("occurred_at"))))
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
