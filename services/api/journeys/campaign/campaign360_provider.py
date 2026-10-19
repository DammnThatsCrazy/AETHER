"""Read-only Campaign360 projection over canonical campaign measurements.

Campaign360 projects tenant-scoped campaign registry facts, campaign
touchpoints, and active attribution-credit rows. Journey/episode, communication,
population, economic, and policy/authority dimensions remain sibling-owned and
are reported as unknown until their canonical providers are composed. This
module does not resolve campaign aliases, write graph state, or turn missing
measurement into a zero.

The provider is deliberately import-safe: repository imports/construction are
lazy, and ``register_provider`` is an explicit runtime wiring seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional, Protocol
from uuid import UUID

from graph.operational_intelligence.models import EvidenceRef, PageInfo
from shared.contracts_models.epistemic import EpistemicStatus
from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    ProjectionContext,
    ProjectionDegradation,
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


PROJECTION_ID = "campaign360"
# Exact output order declared by the generated runtime registry.
OUTPUT_SECTIONS: tuple[str, ...] = (
    "evidence",
    "findings",
    "outcomes",
    "state",
    "summary",
)

SLOT_CAMPAIGN_IDENTITY = "campaign_identity_and_state"
SLOT_TOUCHPOINTS = "touchpoints_and_communications"
SLOT_JOURNEY_EPISODE = "journey_and_episode_context"
SLOT_ATTRIBUTION_OUTCOMES = "attribution_and_outcomes"
SLOT_POPULATION = "population_context"
SLOT_ECONOMIC = "economic_context"

_SLOT_REQUIREMENTS: tuple[tuple[str, str], ...] = (
    (SLOT_CAMPAIGN_IDENTITY, "required"),
    (SLOT_TOUCHPOINTS, "required"),
    (SLOT_JOURNEY_EPISODE, "required"),
    (SLOT_ATTRIBUTION_OUTCOMES, "required"),
    (SLOT_POPULATION, "optional"),
    (SLOT_ECONOMIC, "optional"),
)

# Keep this allowlist narrow. Campaign ``properties`` are source-controlled
# JSON and are not safe to project without field-level policy evaluation.
_CAMPAIGN_FIELDS: tuple[str, ...] = (
    "name",
    "status",
    "channel",
    "origin",
    "primary_platform",
    "sync_status",
    "first_seen_at",
    "last_seen_at",
    "created_at",
    "updated_at",
)

_TOUCHPOINT_FIELDS: tuple[tuple[str, str], ...] = (
    ("touchpointId", "touchpoint_id"),
    ("occurredAt", "occurred_at"),
    ("channel", "channel"),
    ("sourceClass", "source_class"),
    ("touchpointType", "touchpoint_type"),
    ("interactionType", "interaction_type"),
    ("isClickThrough", "is_click_through"),
    ("isViewThrough", "is_view_through"),
    ("communicationFactId", "communication_fact_id"),
)

_ATTRIBUTION_FIELDS: tuple[tuple[str, str], ...] = (
    ("creditId", "credit_id"),
    ("attributionRunId", "attribution_run_id"),
    ("conversionId", "conversion_id"),
    ("touchpointId", "touchpoint_id"),
    ("modelType", "model_type"),
    ("modelVersion", "model_version"),
    ("creditWeight", "credit_weight"),
    ("attributedConversionCount", "attributed_conversion_count"),
    ("attributedGrossRevenue", "attributed_gross_revenue"),
    ("attributedNetRevenue", "attributed_net_revenue"),
    ("createdAt", "created_at"),
    ("runCompletedAt", "run_completed_at"),
)

MAX_PAGE_LIMIT = 500
MAX_ATTRIBUTION_CREDITS = 500
DEFAULT_PAGE_LIMIT = 100


@dataclass(frozen=True)
class CampaignRead:
    """Campaign registry read; empty and unavailable are separate outcomes."""

    record: Optional[dict[str, Any]]
    available: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class RowsRead:
    """Tenant-scoped rows with an explicit source-availability signal."""

    rows: list[dict[str, Any]]
    available: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class AttributionRead:
    """Attribution records plus the repository's declared quality state."""

    credits: list[dict[str, Any]]
    available: bool
    data_quality: Optional[str] = None
    reason: Optional[str] = None


class Campaign360Source(Protocol):
    """Injected tenant-scoped read seam for Campaign360 canonical sources."""

    async def campaign(
        self, tenant_id: str, campaign_id: UUID
    ) -> CampaignRead: ...

    async def touchpoints(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        start: Optional[datetime],
        end: Optional[datetime],
        limit: int,
        cursor: Optional[str],
    ) -> RowsRead: ...

    async def attribution(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        start: Optional[datetime],
        end: Optional[datetime],
    ) -> AttributionRead: ...


class RepositoryCampaign360Source:
    """Adapter over the canonical CampaignRegistry, touchpoint, and credit repos.

    The repositories themselves tenant-filter their SQL/local-store reads. The
    provider independently checks every returned row before exposing it.
    """

    async def campaign(
        self, tenant_id: str, campaign_id: UUID
    ) -> CampaignRead:
        try:
            from journeys.campaign.repository import CampaignRegistryRepository

            record = await CampaignRegistryRepository().get_by_id(
                tenant_id, campaign_id
            )
        except Exception:  # noqa: BLE001 - source failure is a typed state
            return CampaignRead(
                record=None,
                available=False,
                reason="campaign_registry_unavailable",
            )
        return CampaignRead(record=record, available=True)

    async def touchpoints(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        start: Optional[datetime],
        end: Optional[datetime],
        limit: int,
        cursor: Optional[str],
    ) -> RowsRead:
        try:
            from journeys.measurement.repositories.touchpoint_repo import (
                TouchpointRepository,
            )

            rows = await TouchpointRepository().list_by_campaign(
                tenant_id,
                campaign_id,
                after_occurred=start,
                before_occurred=end,
                limit=limit,
                cursor=cursor,
            )
        except Exception:  # noqa: BLE001 - source failure is a typed state
            return RowsRead(
                rows=[], available=False, reason="touchpoint_repository_unavailable"
            )
        return RowsRead(rows=list(rows), available=True)

    async def attribution(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        start: Optional[datetime],
        end: Optional[datetime],
    ) -> AttributionRead:
        try:
            from journeys.measurement.repositories.attribution_run_repo import (
                AttributionRunRepository,
            )

            summary = await AttributionRunRepository().campaign_credit_summary(
                tenant_id,
                campaign_id,
                start_date=start,
                end_date=end,
            )
        except Exception:  # noqa: BLE001 - source failure is a typed state
            return AttributionRead(
                credits=[],
                available=False,
                reason="attribution_repository_unavailable",
            )
        if not isinstance(summary, dict) or not isinstance(
            summary.get("credits"), list
        ):
            return AttributionRead(
                credits=[],
                available=False,
                reason="attribution_result_unavailable",
            )
        return AttributionRead(
            credits=[row for row in summary["credits"] if isinstance(row, dict)],
            available=True,
            data_quality=_string_or_none(summary.get("data_quality")),
        )


@dataclass(frozen=True)
class _TemporalScope:
    mode: str
    start: Optional[datetime]
    end: Optional[datetime]
    observations_supported: bool
    reason: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "start": _scalar(self.start),
            "end": _scalar(self.end),
            "sourceBounds": {
                "touchpoints": {"from": "exclusive", "to": "exclusive"},
                "attributionCredits": {"from": "inclusive", "to": "exclusive"},
            },
            "observationsSupported": self.observations_supported,
            "reason": self.reason,
        }


def _temporal_scope(request: ProjectionRequest) -> _TemporalScope:
    """Normalize only temporal questions the repositories can answer honestly."""
    mode = request.temporalMode or "window"
    if request.asOf is not None:
        return _TemporalScope(
            mode=mode,
            start=None,
            end=None,
            observations_supported=False,
            reason="historical_campaign_snapshot_unavailable",
        )
    if mode == "compare":
        return _TemporalScope(
            mode=mode,
            start=None,
            end=None,
            observations_supported=False,
            reason="comparison_window_contract_unavailable",
        )
    if mode not in {"window", "relative"}:
        return _TemporalScope(
            mode=mode,
            start=None,
            end=None,
            observations_supported=False,
            reason="unsupported_temporal_mode",
        )

    raw_start = request.timeRange.from_ if request.timeRange is not None else None
    raw_end = request.timeRange.to if request.timeRange is not None else None
    if mode == "relative" and raw_start is None and raw_end is None:
        return _TemporalScope(
            mode=mode,
            start=None,
            end=None,
            observations_supported=False,
            reason="relative_window_not_resolved",
        )
    try:
        start = _parse_instant(raw_start) if raw_start is not None else None
        end = _parse_instant(raw_end) if raw_end is not None else None
    except ValueError:
        return _TemporalScope(
            mode=mode,
            start=None,
            end=None,
            observations_supported=False,
            reason="invalid_temporal_window",
        )
    if start is not None and end is not None and end <= start:
        return _TemporalScope(
            mode=mode,
            start=None,
            end=None,
            observations_supported=False,
            reason="invalid_temporal_window",
        )
    return _TemporalScope(
        mode=mode,
        start=start,
        end=end,
        observations_supported=True,
    )


def _parse_instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(timezone.utc)


def _scalar(value: Any) -> Any:
    """Make repository scalars JSON-safe without inventing or rounding values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        return [_scalar(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _scalar(item) for key, item in value.items()}
    return str(value)


def _string_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _campaign_evidence(record: dict[str, Any], campaign_id: str) -> EvidenceRef:
    return EvidenceRef(
        id=campaign_id,
        type="entity",
        source="services/api/journeys/campaign/repository.py:campaigns",
        observedAt=_string_or_none(record.get("updated_at") or record.get("created_at")),
        uri=f"store://campaigns/{campaign_id}",
    )


def _touchpoint_evidence(row: dict[str, Any]) -> Optional[EvidenceRef]:
    touchpoint_id = row.get("touchpoint_id")
    source_event_id = row.get("source_event_id")
    evidence_id = touchpoint_id or source_event_id
    if evidence_id is None or not str(evidence_id).strip():
        return None
    return EvidenceRef(
        id=str(evidence_id),
        type="event",
        source="services/api/journeys/measurement/repositories/touchpoint_repo.py:silver_campaign_touchpoint_facts",
        observedAt=_string_or_none(row.get("occurred_at")),
        uri=(
            f"store://silver_campaign_touchpoint_facts/{touchpoint_id}"
            if touchpoint_id is not None
            else None
        ),
    )


def _credit_evidence(row: dict[str, Any]) -> Optional[EvidenceRef]:
    credit_id = row.get("credit_id")
    if credit_id is None or not str(credit_id).strip():
        return None
    return EvidenceRef(
        id=str(credit_id),
        type="model_output",
        source="services/api/journeys/measurement/repositories/attribution_run_repo.py:attribution_credits",
        observedAt=_string_or_none(row.get("created_at") or row.get("run_completed_at")),
        uri=f"store://attribution_credits/{credit_id}",
    )


def _claim(
    *,
    claim_id: str,
    kind: str,
    subject: ProjectionSubject,
    evidence: EvidenceRef,
    text: str,
    slot_id: str,
) -> ClaimEnvelope:
    return ClaimEnvelope(
        id=claim_id,
        kind=kind,
        subject=subject,
        evidenceRefs=[evidence],
        claims=[text],
        claimState=EpistemicStatus.OBSERVED,
        domainSlotIds=[slot_id],
    )


def _section(
    section_id: str,
    state: str,
    content: Any,
    *,
    warnings: Optional[list[str]] = None,
) -> ProjectionSection:
    return ProjectionSection(
        id=section_id,
        state=state,
        content=content,
        warnings=warnings,
    )


class Campaign360Provider(IntelligenceProjectionProvider):
    """Project evidence-grounded Campaign360 sections from canonical reads."""

    projection_id = PROJECTION_ID
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    def __init__(self, source: Optional[Campaign360Source] = None) -> None:
        self._source = source or RepositoryCampaign360Source()

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        generated_at = datetime.now(timezone.utc).isoformat()
        subject = request.subject
        temporal = _temporal_scope(request)
        claims: list[ClaimEnvelope] = []
        evidence_by_key: dict[tuple[str, str], EvidenceRef] = {}
        findings: list[dict[str, Any]] = []
        degraded_reasons: list[str] = []
        slot_states: dict[str, dict[str, Any]] = {
            slot_id: {
                "id": slot_id,
                "requirement": requirement,
                "state": "unknown",
                "reason": "campaign_subject_not_resolved",
                "sourceAuthorities": [],
            }
            for slot_id, requirement in _SLOT_REQUIREMENTS
        }
        campaign_facts: Optional[dict[str, Any]] = None
        touchpoint_items: list[dict[str, Any]] = []
        credit_items: list[dict[str, Any]] = []
        touchpoint_page: Optional[PageInfo] = None
        campaign_found = False
        campaign_id: Optional[str] = None

        if subject.kind != "campaign":
            for slot_id, requirement in _SLOT_REQUIREMENTS:
                slot_states[slot_id].update(
                    state="not_applicable" if slot_id == SLOT_CAMPAIGN_IDENTITY else "unknown",
                    reason=(
                        "subject_kind_is_not_campaign"
                        if slot_id == SLOT_CAMPAIGN_IDENTITY
                        else "campaign_binding_for_subject_kind_unavailable"
                    ),
                )
            findings.append(
                {
                    "code": "campaign_subject_required",
                    "domainSlotIds": [slot_id for slot_id, _ in _SLOT_REQUIREMENTS],
                    "state": "unknown",
                }
            )
        else:
            try:
                parsed_campaign_id = UUID(subject.id)
            except (ValueError, TypeError, AttributeError):
                parsed_campaign_id = None
            if parsed_campaign_id is None:
                slot_states[SLOT_CAMPAIGN_IDENTITY].update(
                    state="unknown", reason="campaign_identifier_unresolved"
                )
                findings.append(
                    {
                        "code": "campaign_identifier_unresolved",
                        "domainSlotIds": [SLOT_CAMPAIGN_IDENTITY],
                        "state": "unknown",
                    }
                )
            elif request.asOf is not None:
                # The campaign registry is a current-state store and cannot
                # answer a historical knowledge-time query.
                for slot_id, _ in _SLOT_REQUIREMENTS:
                    slot_states[slot_id].update(
                        state="unknown", reason="historical_campaign_snapshot_unavailable"
                    )
                findings.append(
                    {
                        "code": "historical_campaign_snapshot_unavailable",
                        "domainSlotIds": [slot_id for slot_id, _ in _SLOT_REQUIREMENTS],
                        "state": "unknown",
                    }
                )
                degraded_reasons.append("historical_campaign_snapshot_unavailable")
            else:
                campaign_id = str(parsed_campaign_id)
                campaign_read = await self._source.campaign(
                    request.tenantId, parsed_campaign_id
                )
                if not campaign_read.available:
                    slot_states[SLOT_CAMPAIGN_IDENTITY].update(
                        state="degraded",
                        reason="campaign_registry_unavailable",
                        sourceAuthorities=["campaign_facts"],
                    )
                    degraded_reasons.append("campaign_registry_unavailable")
                elif campaign_read.record is None:
                    slot_states[SLOT_CAMPAIGN_IDENTITY].update(
                        state="missing",
                        reason="tenant_scoped_campaign_record_not_found",
                        sourceAuthorities=["campaign_facts"],
                    )
                elif not isinstance(campaign_read.record, dict) or not _campaign_matches_scope(
                    campaign_read.record, request.tenantId, parsed_campaign_id
                ):
                    slot_states[SLOT_CAMPAIGN_IDENTITY].update(
                        state="unknown",
                        reason="campaign_record_scope_mismatch",
                        sourceAuthorities=["campaign_facts"],
                    )
                    findings.append(
                        {
                            "code": "campaign_record_scope_mismatch",
                            "domainSlotIds": [SLOT_CAMPAIGN_IDENTITY],
                            "state": "conflicted",
                        }
                    )
                else:
                    campaign_found = True
                    campaign_record = campaign_read.record
                    campaign_facts = {
                        "campaignId": campaign_id,
                        **{
                            key: _scalar(campaign_record.get(value))
                            for key, value in (
                                ("name", "name"),
                                ("status", "status"),
                                ("channel", "channel"),
                                ("origin", "origin"),
                                ("primaryPlatform", "primary_platform"),
                                ("syncStatus", "sync_status"),
                                ("firstSeenAt", "first_seen_at"),
                                ("lastSeenAt", "last_seen_at"),
                                ("createdAt", "created_at"),
                                ("updatedAt", "updated_at"),
                            )
                            if value in _CAMPAIGN_FIELDS
                        },
                    }
                    campaign_ref = _campaign_evidence(campaign_record, campaign_id)
                    _add_evidence(evidence_by_key, campaign_ref)
                    claims.append(
                        _claim(
                            claim_id=f"campaign360:{campaign_id}:registry-record",
                            kind="campaign_registry_record",
                            subject=subject,
                            evidence=campaign_ref,
                            text="A tenant-scoped canonical campaign registry record exists.",
                            slot_id=SLOT_CAMPAIGN_IDENTITY,
                        )
                    )
                    slot_states[SLOT_CAMPAIGN_IDENTITY].update(
                        state="available",
                        reason=None,
                        sourceAuthorities=["campaign_facts"],
                    )

                if campaign_found:
                    if temporal.observations_supported:
                        touchpoint_page = await self._read_touchpoints(
                            request=request,
                            subject=subject,
                            campaign_id=campaign_id,
                            temporal=temporal,
                            slot_states=slot_states,
                            touchpoint_items=touchpoint_items,
                            evidence_by_key=evidence_by_key,
                            claims=claims,
                            degraded_reasons=degraded_reasons,
                        )
                        await self._read_attribution(
                            request=request,
                            subject=subject,
                            campaign_id=campaign_id,
                            temporal=temporal,
                            slot_states=slot_states,
                            credit_items=credit_items,
                            evidence_by_key=evidence_by_key,
                            claims=claims,
                            degraded_reasons=degraded_reasons,
                        )
                    else:
                        for slot_id in (
                            SLOT_TOUCHPOINTS,
                            SLOT_ATTRIBUTION_OUTCOMES,
                        ):
                            slot_states[slot_id].update(
                                state="unknown",
                                reason=temporal.reason or "temporal_scope_unavailable",
                                sourceAuthorities=(
                                    ["touchpoints"]
                                    if slot_id == SLOT_TOUCHPOINTS
                                    else ["attribution_credits", "outcomes"]
                                ),
                            )
                        findings.append(
                            {
                                "code": temporal.reason or "temporal_scope_unavailable",
                                "domainSlotIds": [
                                    SLOT_TOUCHPOINTS,
                                    SLOT_ATTRIBUTION_OUTCOMES,
                                ],
                                "state": "unknown",
                            }
                        )
                        degraded_reasons.append(
                            temporal.reason or "temporal_scope_unavailable"
                        )

                if not campaign_found:
                    slot_states[SLOT_TOUCHPOINTS].update(
                        state="missing",
                        reason="campaign_registry_subject_not_available",
                        sourceAuthorities=["touchpoints"],
                    )
                    slot_states[SLOT_ATTRIBUTION_OUTCOMES].update(
                        state="unknown",
                        reason="campaign_registry_subject_not_available",
                        sourceAuthorities=["attribution_credits", "outcomes"],
                    )

                # These required/optional slots are provided by sibling 360s.
                slot_states[SLOT_JOURNEY_EPISODE].update(
                    state="unknown",
                    reason="episode360_is_canonical_provider_for_journey_and_episode_context",
                    sourceAuthorities=["journeys", "episode_facts"],
                )
                slot_states[SLOT_POPULATION].update(
                    state="unknown",
                    reason="population360_is_canonical_provider_for_population_context",
                    sourceAuthorities=["population", "population_definitions"],
                )
                slot_states[SLOT_ECONOMIC].update(
                    state="unknown",
                    reason="economic360_is_canonical_provider_for_economic_context",
                    sourceAuthorities=["economic", "economic_facts"],
                )

        if temporal.reason is not None and temporal.reason not in {
            finding.get("code") for finding in findings
        }:
            findings.append(
                {
                    "code": temporal.reason,
                    "domainSlotIds": [SLOT_TOUCHPOINTS, SLOT_ATTRIBUTION_OUTCOMES],
                    "state": "unknown",
                }
            )

        # Provider-level claims are optional at request time; evidence sections
        # remain present to let callers inspect grounded source references.
        if request.includeClaims is False:
            claims = []

        evidence_items = [
            {
                "evidence": ref.model_dump(by_alias=True, exclude_none=True),
                "domainSlotIds": _slots_for_evidence(ref, claims, campaign_id),
            }
            for ref in evidence_by_key.values()
        ]
        evidence_section_state = (
            "available" if evidence_items else "empty" if campaign_found else "unknown"
        )

        # A measured credit can make this section available, but a missing
        # attribution run is explicitly missing. No zero conversion/revenue is
        # emitted by this provider.
        attribution_state = slot_states[SLOT_ATTRIBUTION_OUTCOMES]["state"]
        if not campaign_found:
            outcomes_section_state = "unknown"
        elif attribution_state == "unknown":
            outcomes_section_state = (
                slot_states[SLOT_ATTRIBUTION_OUTCOMES]["state"]
                if slot_states[SLOT_ATTRIBUTION_OUTCOMES]["state"]
                in {"degraded", "missing", "not_applicable", "suppressed", "stale"}
                else "unknown"
            )
        elif attribution_state == "available":
            outcomes_section_state = "available"
        elif attribution_state == "degraded":
            outcomes_section_state = "degraded"
        else:
            outcomes_section_state = "missing"

        if campaign_found:
            summary_state = "available"
        elif slot_states[SLOT_CAMPAIGN_IDENTITY]["state"] == "degraded":
            summary_state = "degraded"
        elif slot_states[SLOT_CAMPAIGN_IDENTITY]["state"] == "not_applicable":
            summary_state = "not_applicable"
        elif slot_states[SLOT_CAMPAIGN_IDENTITY]["state"] == "missing":
            summary_state = "missing"
        else:
            summary_state = "unknown"

        state_content = {
            "temporalScope": temporal.as_dict(),
            "slots": [slot_states[slot_id] for slot_id, _ in _SLOT_REQUIREMENTS],
            "dependencyState": [
                item.model_dump(by_alias=True, exclude_none=True)
                for item in context.dependencyState
            ],
            "policy": {
                "state": "unknown",
                "reason": "policy_is_evaluated_before_projection_by_the_frame_runtime",
            },
            "actorAttribution": {
                "state": "unknown",
                "reason": "campaign_touchpoint_actor_fields_are_not_a_canonical_actor_resolution",
            },
        }
        sections = [
            _section(
                "evidence",
                evidence_section_state,
                {
                    "items": evidence_items,
                    "touchpoints": touchpoint_items,
                    "domainSlotIds": [
                        SLOT_CAMPAIGN_IDENTITY,
                        SLOT_TOUCHPOINTS,
                        SLOT_ATTRIBUTION_OUTCOMES,
                    ],
                    "provenance": {
                        "projectionId": PROJECTION_ID,
                        "tenantId": request.tenantId,
                    },
                },
            ),
            _section(
                "findings",
                "available",
                {
                    "items": findings,
                    "domainSlotIds": [slot_id for slot_id, _ in _SLOT_REQUIREMENTS],
                    "limitations": [
                        "journey_and_episode_context is supplied by episode360",
                        "population_context is supplied by population360",
                        "economic_context is supplied by economic360",
                        "communication facts are supplied by communication360",
                        "actor attribution, delegation, and authority are not resolved by this provider",
                        "current campaign state is not a historical snapshot",
                    ],
                },
            ),
            _section(
                "outcomes",
                outcomes_section_state,
                {
                    "attribution": {
                        "state": attribution_state,
                        "dataQuality": slot_states[SLOT_ATTRIBUTION_OUTCOMES].get(
                            "qualityState", "unknown"
                        ),
                        "credits": credit_items,
                        "creditsTruncated": slot_states[
                            SLOT_ATTRIBUTION_OUTCOMES
                        ].get("creditsTruncated", False),
                        "domainSlotIds": [SLOT_ATTRIBUTION_OUTCOMES],
                        "zeroDefaulted": False,
                    },
                    "outcome360Dependency": _dependency_state(
                        context, "outcome360"
                    ),
                    "populationAndEconomicOutcomeData": "sibling_provider_required",
                },
            ),
            _section("state", "available", state_content),
            _section(
                "summary",
                summary_state,
                {
                    "subject": {"kind": subject.kind, "id": subject.id},
                    "campaign": campaign_facts,
                    "domainSlotIds": [SLOT_CAMPAIGN_IDENTITY],
                    "tenantScope": {"tenantId": request.tenantId},
                    "temporalScope": temporal.as_dict(),
                    "readOnly": True,
                },
            ),
        ]
        section_by_id = {item.id: item for item in sections}
        sections = [section_by_id[section_id] for section_id in OUTPUT_SECTIONS]

        degradation_level = "none"
        if degraded_reasons:
            degradation_level = "partial" if campaign_found else "full"
        elif any(
            item["state"] in {"unknown", "missing"}
            and item["requirement"] == "required"
            for item in slot_states.values()
        ):
            degradation_level = "partial"
        degradation = ProjectionDegradation(
            level=degradation_level,
            reasons=list(dict.fromkeys(degraded_reasons)),
            missingDependencies=[
                item.projectionId
                for item in context.dependencyState
                if item.state != "available"
            ] or None,
        )
        return ProjectionResult(
            projectionId=PROJECTION_ID,
            tenantId=request.tenantId,
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=sections,
            claims=claims,
            dependencyState=context.dependencyState,
            generatedAt=generated_at,
            page=touchpoint_page,
            degradedReasons=list(dict.fromkeys(degraded_reasons)),
            temporalMode=request.temporalMode,
            degradation=degradation,
        )

    async def _read_touchpoints(
        self,
        *,
        request: ProjectionRequest,
        subject: ProjectionSubject,
        campaign_id: str,
        temporal: _TemporalScope,
        slot_states: dict[str, dict[str, Any]],
        touchpoint_items: list[dict[str, Any]],
        evidence_by_key: dict[tuple[str, str], EvidenceRef],
        claims: list[ClaimEnvelope],
        degraded_reasons: list[str],
    ) -> Optional[PageInfo]:
        page = request.page
        limit = min(page.limit if page is not None else DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT)
        cursor = page.cursor if page is not None else None
        if cursor is not None:
            try:
                _parse_instant(cursor)
            except ValueError:
                slot_states[SLOT_TOUCHPOINTS].update(
                    state="unknown",
                    reason="touchpoint_cursor_invalid",
                    sourceAuthorities=["touchpoints"],
                )
                degraded_reasons.append("touchpoint_cursor_invalid")
                return None
        result = await self._source.touchpoints(
            request.tenantId,
            campaign_id,
            start=temporal.start,
            end=temporal.end,
            limit=limit + 1,
            cursor=cursor,
        )
        if not result.available:
            slot_states[SLOT_TOUCHPOINTS].update(
                state="degraded",
                reason="touchpoint_repository_unavailable",
                sourceAuthorities=[
                    "touchpoints",
                    "campaign_touchpoints",
                    "communication_facts",
                ],
                dimensionStates={
                    "touchpoints": "unavailable",
                    "communicationFacts": "unknown",
                },
            )
            degraded_reasons.append("touchpoint_repository_unavailable")
            return None
        if any(not isinstance(row, dict) for row in result.rows):
            slot_states[SLOT_TOUCHPOINTS].update(
                state="unknown",
                reason="touchpoint_row_shape_invalid",
                sourceAuthorities=[
                    "touchpoints",
                    "campaign_touchpoints",
                    "communication_facts",
                ],
                dimensionStates={
                    "touchpoints": "unknown",
                    "communicationFacts": "unknown",
                },
            )
            degraded_reasons.append("touchpoint_row_shape_invalid")
            return None
        rows = result.rows
        if any(not _row_matches_campaign_scope(row, request.tenantId, campaign_id) for row in rows):
            slot_states[SLOT_TOUCHPOINTS].update(
                state="unknown",
                reason="touchpoint_row_scope_mismatch",
                sourceAuthorities=[
                    "touchpoints",
                    "campaign_touchpoints",
                    "communication_facts",
                ],
                dimensionStates={
                    "touchpoints": "unknown",
                    "communicationFacts": "unknown",
                },
            )
            degraded_reasons.append("touchpoint_row_scope_mismatch")
            return None
        has_more = len(rows) > limit
        rows = rows[:limit]
        unreferenced_rows = 0
        for row in rows:
            evidence = _touchpoint_evidence(row)
            if evidence is None:
                unreferenced_rows += 1
                continue
            _add_evidence(evidence_by_key, evidence)
            payload = {
                out_key: _scalar(row.get(in_key))
                for out_key, in_key in _TOUCHPOINT_FIELDS
                if row.get(in_key) is not None
            }
            touchpoint_items.append(
                {"touchpoint": payload, "domainSlotIds": [SLOT_TOUCHPOINTS]}
            )
            claims.append(
                _claim(
                    claim_id=f"campaign360:{campaign_id}:touchpoint:{evidence.id}",
                    kind="campaign_touchpoint_observation",
                    subject=subject,
                    evidence=evidence,
                    text="A tenant-scoped campaign touchpoint is recorded in the measurement facts.",
                    slot_id=SLOT_TOUCHPOINTS,
                )
            )
        if unreferenced_rows:
            degraded_reasons.append("touchpoint_evidence_reference_missing")
        if has_more:
            last_occurred = _string_or_none(rows[-1].get("occurred_at")) if rows else None
            page_info = PageInfo(
                nextCursor=last_occurred,
                hasNextPage=last_occurred is not None,
                hasPreviousPage=cursor is not None,
            )
        else:
            page_info = PageInfo(
                hasNextPage=False,
                hasPreviousPage=cursor is not None,
            )
        touchpoint_dimension_state = (
            "truncated"
            if has_more
            else "available"
            if rows and not unreferenced_rows
            else "partial"
            if rows
            else "empty"
        )
        # The product slot includes communication_facts. Touchpoints alone are
        # only a partial contribution; Communication360 supplies the missing
        # communication dimension during frame composition.
        slot_state = "degraded"
        slot_states[SLOT_TOUCHPOINTS].update(
            state=slot_state,
            reason=(
                "touchpoint_page_truncated"
                if has_more
                else "touchpoint_rows_missing_evidence_reference"
                if unreferenced_rows
                else "communication_facts_require_communication360"
            ),
            sourceAuthorities=[
                "touchpoints",
                "campaign_touchpoints",
                "communication_facts",
            ],
            dimensionStates={
                "touchpoints": touchpoint_dimension_state,
                "communicationFacts": "unknown",
            },
        )
        return page_info

    async def _read_attribution(
        self,
        *,
        request: ProjectionRequest,
        subject: ProjectionSubject,
        campaign_id: str,
        temporal: _TemporalScope,
        slot_states: dict[str, dict[str, Any]],
        credit_items: list[dict[str, Any]],
        evidence_by_key: dict[tuple[str, str], EvidenceRef],
        claims: list[ClaimEnvelope],
        degraded_reasons: list[str],
    ) -> None:
        result = await self._source.attribution(
            request.tenantId,
            campaign_id,
            start=temporal.start,
            end=temporal.end,
        )
        if not result.available:
            slot_states[SLOT_ATTRIBUTION_OUTCOMES].update(
                state="degraded",
                reason="attribution_repository_unavailable",
                sourceAuthorities=["attribution_credits", "outcomes"],
                dimensionStates={
                    "attributionCredits": "unavailable",
                    "outcomes": "unknown",
                },
                qualityState="unknown",
            )
            degraded_reasons.append("attribution_repository_unavailable")
            return
        if any(not isinstance(row, dict) for row in result.credits):
            slot_states[SLOT_ATTRIBUTION_OUTCOMES].update(
                state="unknown",
                reason="attribution_credit_row_shape_invalid",
                sourceAuthorities=["attribution_credits", "outcomes"],
                dimensionStates={
                    "attributionCredits": "unknown",
                    "outcomes": "unknown",
                },
                qualityState="unknown",
            )
            degraded_reasons.append("attribution_credit_row_shape_invalid")
            return
        credits = result.credits
        if any(not _row_matches_campaign_scope(row, request.tenantId, campaign_id, attribution=True) for row in credits):
            slot_states[SLOT_ATTRIBUTION_OUTCOMES].update(
                state="unknown",
                reason="attribution_credit_scope_mismatch",
                sourceAuthorities=["attribution_credits", "outcomes"],
                dimensionStates={
                    "attributionCredits": "unknown",
                    "outcomes": "unknown",
                },
                qualityState=result.data_quality or "unknown",
            )
            degraded_reasons.append("attribution_credit_scope_mismatch")
            return
        if not credits:
            if result.data_quality == "not_provisioned":
                slot_state = "missing"
                reason = "active_attribution_run_not_provisioned"
            elif result.data_quality is None:
                slot_state = "unknown"
                reason = "attribution_data_quality_unavailable"
            else:
                # An empty credit set can be a known empty measurement only if
                # the authority explicitly attests to a complete run. The
                # current repository's empty summary reports not_provisioned.
                slot_state = "unknown"
                reason = "no_credit_rows_without_complete_run_evidence"
            slot_states[SLOT_ATTRIBUTION_OUTCOMES].update(
                state=slot_state,
                reason=reason,
                sourceAuthorities=["attribution_credits", "outcomes"],
                dimensionStates={
                    "attributionCredits": "missing"
                    if slot_state == "missing"
                    else "empty"
                    if result.data_quality == "complete"
                    else "unknown",
                    "outcomes": "unknown",
                },
                qualityState=result.data_quality or "unknown",
                creditsTruncated=False,
            )
            return

        credits_truncated = len(credits) > MAX_ATTRIBUTION_CREDITS
        credits = credits[:MAX_ATTRIBUTION_CREDITS]
        unreferenced = 0
        for row in credits:
            evidence = _credit_evidence(row)
            if evidence is None:
                unreferenced += 1
                continue
            _add_evidence(evidence_by_key, evidence)
            payload = {
                out_key: _scalar(row.get(in_key))
                for out_key, in_key in _ATTRIBUTION_FIELDS
                if in_key in row
            }
            credit_items.append(
                {"credit": payload, "domainSlotIds": [SLOT_ATTRIBUTION_OUTCOMES]}
            )
            claims.append(
                _claim(
                    claim_id=f"campaign360:{campaign_id}:credit:{evidence.id}",
                    kind="campaign_attribution_credit",
                    subject=subject,
                    evidence=evidence,
                    text="An active tenant-scoped attribution credit record is associated with this campaign.",
                    slot_id=SLOT_ATTRIBUTION_OUTCOMES,
                )
            )
        slot_state = "degraded"
        if credits_truncated:
            reason = "attribution_credit_page_truncated"
        elif unreferenced:
            reason = "attribution_credit_evidence_reference_missing"
        elif result.data_quality == "partial":
            reason = "attribution_repository_reports_partial_data_quality"
        else:
            reason = "outcome_records_require_outcome360"
        slot_states[SLOT_ATTRIBUTION_OUTCOMES].update(
            state=slot_state,
            reason=reason,
            sourceAuthorities=["attribution_credits", "outcomes"],
            dimensionStates={
                "attributionCredits": "truncated"
                if credits_truncated
                else "partial"
                if unreferenced
                else "available",
                "outcomes": "unknown",
            },
            qualityState=result.data_quality or "unknown",
            creditsTruncated=credits_truncated,
        )
        degraded_reasons.append(reason)


def _campaign_matches_scope(
    row: dict[str, Any], tenant_id: str, campaign_id: UUID
) -> bool:
    if str(row.get("tenant_id") or "") != tenant_id:
        return False
    try:
        row_id = UUID(str(row.get("campaign_id")))
    except (ValueError, TypeError, AttributeError):
        return False
    return row_id == campaign_id


def _row_matches_campaign_scope(
    row: dict[str, Any],
    tenant_id: str,
    campaign_id: str,
    *,
    attribution: bool = False,
) -> bool:
    if str(row.get("tenant_id") or "") != tenant_id:
        return False
    raw_campaign_id = row.get("campaign_id")
    if raw_campaign_id is None:
        return False
    if attribution:
        return str(raw_campaign_id) == campaign_id
    try:
        return str(UUID(str(raw_campaign_id))) == campaign_id
    except (ValueError, TypeError, AttributeError):
        return False


def _add_evidence(
    target: dict[tuple[str, str], EvidenceRef], evidence: EvidenceRef
) -> None:
    target[(evidence.source, evidence.id)] = evidence


def _slots_for_evidence(
    evidence: EvidenceRef,
    claims: list[ClaimEnvelope],
    campaign_id: Optional[str],
) -> list[str]:
    slots = [
        slot_id
        for claim in claims
        if any(
            item.id == evidence.id and item.source == evidence.source
            for item in claim.evidenceRefs
        )
        for slot_id in (claim.domainSlotIds or [])
    ]
    if not slots:
        if campaign_id is not None and evidence.source.endswith(":campaigns"):
            slots.append(SLOT_CAMPAIGN_IDENTITY)
        elif "touchpoint_repo.py:silver_campaign_touchpoint_facts" in evidence.source:
            slots.append(SLOT_TOUCHPOINTS)
        elif "attribution_run_repo.py:attribution_credits" in evidence.source:
            slots.append(SLOT_ATTRIBUTION_OUTCOMES)
    return list(dict.fromkeys(slots))


def _dependency_state(
    context: ProjectionContext, projection_id: str
) -> Optional[dict[str, Any]]:
    dependency = next(
        (item for item in context.dependencyState if item.projectionId == projection_id),
        None,
    )
    return dependency.model_dump(by_alias=True, exclude_none=True) if dependency else None


def register_provider(registry: ProviderRegistry) -> Campaign360Provider:
    """Register Campaign360 explicitly; importing this module has no effects."""
    provider = Campaign360Provider()
    registry.register(provider, source="services/api/journeys/campaign")
    return provider


__all__ = [
    "AttributionRead",
    "Campaign360Provider",
    "Campaign360Source",
    "CampaignRead",
    "OUTPUT_SECTIONS",
    "PROJECTION_ID",
    "RepositoryCampaign360Source",
    "RowsRead",
    "register_provider",
]
