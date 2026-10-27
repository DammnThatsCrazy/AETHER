"""Read-only Campaign360 projection over canonical campaign measurements.

Campaign360 projects tenant-scoped campaign registry facts, campaign
touchpoints, active attribution-credit rows, canonical conversions, and
bounded exact campaign spend observations. Journey/episode, communication,
broader population, and policy/authority dimensions remain sibling-owned and
are reported as unknown until their canonical providers are composed. This
module does not resolve campaign aliases, write graph state, or turn missing
measurement into a zero.

The provider is deliberately import-safe: repository imports/construction are
lazy, and ``register_provider`` is an explicit runtime wiring seam.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional, Protocol
from urllib.parse import quote
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
from journeys.campaign.campaign_population_links import (
    CampaignPopulationLinkAuthority,
    CampaignPopulationLinkRead,
    MAX_CAMPAIGN_POPULATION_LINKS,
)


PROJECTION_ID = "campaign360"
# Exact output order declared by the generated runtime registry.
OUTPUT_SECTIONS: tuple[str, ...] = (
    "evidence",
    "findings",
    "anomalies",
    "outcomes",
    "state",
    "summary",
)

SLOT_CAMPAIGN_IDENTITY = "campaign_identity"
SLOT_SOURCE_CLASSIFICATION = "source_classification"
SLOT_SIGNAL_SOURCES = "signal_sources"
SLOT_TOUCHPOINTS = "touchpoints"
SLOT_JOURNEYS = "journeys"
SLOT_CONVERSIONS = "conversions"
SLOT_ATTRIBUTION = "attribution"
SLOT_COHORTS_SYNDICATES = "cohorts_syndicates"
SLOT_PERFORMANCE = "performance"
SLOT_ANOMALIES = "anomalies"
SLOT_EVIDENCE_TRACE = "evidence_trace"

# Kept as internal aliases for the legacy subject-context helpers below. These
# helpers are not called for Campaign360's campaign-only subject contract.
SLOT_JOURNEY_EPISODE = SLOT_JOURNEYS
SLOT_POPULATION = SLOT_COHORTS_SYNDICATES
SLOT_ATTRIBUTION_OUTCOMES = SLOT_ATTRIBUTION
SLOT_ECONOMIC = SLOT_PERFORMANCE

_SLOT_REQUIREMENTS: tuple[tuple[str, str], ...] = (
    (SLOT_CAMPAIGN_IDENTITY, "required"),
    (SLOT_SOURCE_CLASSIFICATION, "required"),
    (SLOT_SIGNAL_SOURCES, "required"),
    (SLOT_TOUCHPOINTS, "required"),
    (SLOT_JOURNEYS, "required"),
    (SLOT_CONVERSIONS, "required"),
    (SLOT_ATTRIBUTION, "required"),
    (SLOT_COHORTS_SYNDICATES, "required"),
    (SLOT_PERFORMANCE, "required"),
    (SLOT_ANOMALIES, "required"),
    (SLOT_EVIDENCE_TRACE, "required"),
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
MAX_ASSOCIATED_CONTEXT_ROWS = 100
MAX_CAMPAIGN_ANOMALIES = 100
MAX_CAMPAIGN_SIGNAL_EVENTS = 100
MAX_CAMPAIGN_PERFORMANCE_SPEND_ROWS = 500

_JOURNEY_SOURCE = (
    "services/api/journeys/measurement/repositories/journey_repo.py:journey_versions"
)
_EPISODE_SOURCE = "services/api/shared/backend_interpretation/stores.py:episodes"
_TARGETING_ANOMALY_SOURCE = (
    "services/api/intelligence/targeting_intelligence/repository.py:targeting_leakage_findings"
)
_TARGETING_ANOMALY_EVIDENCE_SOURCES = frozenset(
    {"targeting_observation", "eligibility_snapshot"}
)
_CAMPAIGN_RISK_ASSESSMENT_SOURCE = "risk_assessments"


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


@dataclass(frozen=True)
class ConversionRecordRead:
    """One exact canonical conversion lookup, scoped by tenant and ID."""

    record: Optional[dict[str, Any]]
    available: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class CampaignAnomalyRead:
    """Exact campaign-scoped targeting findings with explicit completeness."""

    rows: list[dict[str, Any]]
    available: bool
    complete: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class CampaignRiskAssessmentRead:
    """Exact campaign Risk360 assessments; producer coverage is unverified."""

    rows: list[dict[str, Any]]
    available: bool
    complete: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class CampaignSpendRead:
    """Bounded exact campaign spend rows and explicit source completeness."""

    rows: list[dict[str, Any]]
    available: bool
    complete: bool = False
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

    async def conversion_record(
        self, tenant_id: str, conversion_id: str
    ) -> ConversionRecordRead: ...

    async def journeys_for_campaign(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        start: Optional[datetime],
        end: Optional[datetime],
        limit: int,
    ) -> RowsRead: ...

    async def episode_record(self, tenant_id: str, episode_id: str) -> CampaignRead: ...

    async def campaign_anomalies(
        self, tenant_id: str, campaign_id: str, *, limit: int
    ) -> CampaignAnomalyRead: ...

    async def campaign_risk_assessments(
        self, tenant_id: str, campaign_id: str, *, limit: int
    ) -> CampaignRiskAssessmentRead: ...

    async def signal_events(
        self, tenant_id: str, event_ids: list[str], *, limit: int
    ) -> RowsRead: ...

    async def signal_observations(
        self, tenant_id: str, event_ids: list[str], *, limit: int
    ) -> RowsRead: ...

    async def campaign_population_links(
        self, tenant_id: str, campaign_id: str, *, limit: int
    ) -> CampaignPopulationLinkRead: ...

    async def campaign_spend(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        start: Optional[datetime],
        end: Optional[datetime],
        limit: int,
    ) -> CampaignSpendRead: ...


class RepositoryCampaign360Source:
    """Adapter over canonical campaign, measurement, and targeting repositories.

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

    async def conversion_record(
        self, tenant_id: str, conversion_id: str
    ) -> ConversionRecordRead:
        """Read a canonical conversion by its exact tenant/conversion key.

        Campaign membership is deliberately supplied by the separately
        validated active attribution credit. This method does not resolve a
        campaign alias or infer a campaign from profile/cluster identifiers.
        """
        try:
            from journeys.measurement.repositories.conversion_repo import (
                ConversionRepository,
            )

            record = await ConversionRepository().get(tenant_id, conversion_id)
        except Exception:  # noqa: BLE001 - source failure is a typed state
            return ConversionRecordRead(
                record=None,
                available=False,
                reason="conversion_repository_unavailable",
            )
        return ConversionRecordRead(record=record, available=True)

    async def journeys_for_campaign(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        start: Optional[datetime],
        end: Optional[datetime],
        limit: int,
    ) -> RowsRead:
        """Read current journey versions with an exact campaign_ids membership.

        JourneyRepository applies both ``tenant_id`` and the typed campaign id
        membership predicate in SQL/local storage. The provider independently
        validates the returned rows before rendering them.
        """
        try:
            from journeys.measurement.repositories.journey_repo import JourneyRepository

            rows = await JourneyRepository().list_by_campaign(
                tenant_id,
                campaign_id,
                after_started=start,
                before_started=end,
                limit=limit,
            )
        except Exception:  # noqa: BLE001 - journey read failure is slot-local
            return RowsRead([], available=False, reason="journey_authority_unavailable")
        return RowsRead(rows=list(rows), available=True)

    async def episode_record(self, tenant_id: str, episode_id: str) -> CampaignRead:
        """Read one canonical episode by its exact tenant/episode composite key."""
        try:
            from shared.backend_interpretation.stores import EpisodeStore

            record = await EpisodeStore().get(tenant_id, episode_id)
        except Exception:  # noqa: BLE001 - episode read failure is slot-local
            return CampaignRead(
                record=None,
                available=False,
                reason="episode_authority_unavailable",
            )
        if record is None:
            return CampaignRead(record=None, available=True)
        model_dump = getattr(record, "model_dump", None)
        if callable(model_dump):
            record = model_dump(mode="json")
        return CampaignRead(
            record=record if isinstance(record, dict) else None,
            available=isinstance(record, dict),
            reason=None if isinstance(record, dict) else "episode_record_shape_invalid",
        )

    async def campaign_anomalies(
        self, tenant_id: str, campaign_id: str, *, limit: int
    ) -> CampaignAnomalyRead:
        """Read exact campaign-linked targeting leakage findings.

        The targeting store applies the tenant and campaign predicates before
        returning rows. Campaign360 independently validates both fields before
        projecting any record. Other risk outputs and source anomalies remain
        outside this source and are not inferred from an empty targeting read.
        """
        try:
            from intelligence.targeting_intelligence.repository import (
                get_targeting_repositories,
            )

            rows = await get_targeting_repositories().leakage.list_for_tenant(
                tenant_id,
                campaignId=campaign_id,
                limit=limit,
            )
        except Exception:  # noqa: BLE001 - anomaly-source outage is slot-local
            return CampaignAnomalyRead(
                rows=[],
                available=False,
                complete=False,
                reason="targeting_anomaly_authority_unavailable",
            )
        return CampaignAnomalyRead(
            rows=list(rows),
            available=True,
            complete=len(rows) < limit,
        )

    async def campaign_risk_assessments(
        self, tenant_id: str, campaign_id: str, *, limit: int
    ) -> CampaignRiskAssessmentRead:
        """Read only Risk360 assessments for the exact tenant/campaign subject."""
        try:
            from intelligence.risk360.store import RiskAssessmentRepository

            rows = await RiskAssessmentRepository().list_by_subject(
                tenant_id, "campaign", campaign_id, limit=limit
            )
        except Exception:  # noqa: BLE001 - independent risk output remains unknown
            return CampaignRiskAssessmentRead([], False, False, "campaign_risk_assessment_read_unavailable")
        return CampaignRiskAssessmentRead(
            rows=list(rows), available=True, complete=len(rows) < limit
        )

    async def signal_events(
        self, tenant_id: str, event_ids: list[str], *, limit: int
    ) -> RowsRead:
        """Read exact source events linked from scoped campaign touchpoints.

        This deliberately does not search by campaign name, source label, or
        event properties. The source event ID comes from a tenant/campaign
        scoped touchpoint row, and every event lookup is independently scoped
        to the same tenant.
        """
        if not tenant_id:
            return RowsRead([], available=False, reason="event_tenant_scope_missing")
        safe_ids = [
            event_id
            for event_id in dict.fromkeys(event_ids)
            if _safe_campaign_source_id(event_id)
        ][: min(max(limit, 0), MAX_CAMPAIGN_SIGNAL_EVENTS)]
        if not safe_ids:
            return RowsRead([], available=True)
        try:
            from dependencies.providers import get_cache
            from repositories.repos import AnalyticsRepository

            analytics = AnalyticsRepository(get_cache())
            rows: list[dict[str, Any]] = []
            for event_id in safe_ids:
                matches = await analytics.query_events(
                    tenant_id,
                    {"event_id": event_id},
                    limit=2,
                )
                for row in matches:
                    if (
                        isinstance(row, dict)
                        and row.get("tenant_id") == tenant_id
                        and str(row.get("event_id") or "") == event_id
                    ):
                        rows.append(row)
            return RowsRead(rows=rows, available=True)
        except Exception:  # noqa: BLE001 - event authority failure is slot-local
            return RowsRead([], available=False, reason="campaign_event_authority_unavailable")

    async def signal_observations(
        self, tenant_id: str, event_ids: list[str], *, limit: int
    ) -> RowsRead:
        """Read only exact tenant SDK Bronze observations named by event IDs."""
        if not tenant_id:
            return RowsRead([], available=False, reason="observation_tenant_scope_missing")
        safe_ids = [
            event_id for event_id in dict.fromkeys(event_ids)
            if _safe_campaign_source_id(event_id)
        ][:min(max(limit, 0), MAX_CAMPAIGN_SIGNAL_EVENTS)]
        if not safe_ids:
            return RowsRead([], available=True)
        try:
            from repositories.lake import BronzeRepository

            repository = BronzeRepository("sdk_events")
            semaphore = asyncio.Semaphore(4)

            async def read_one(event_id: str) -> list[dict[str, Any]]:
                async with semaphore:
                    return await repository.find_many(
                        filters={"tenant_id": tenant_id, "provider_record_id": event_id},
                        limit=2,
                    )

            pages = await asyncio.gather(*(read_one(event_id) for event_id in safe_ids))
        except Exception:  # noqa: BLE001 - observation authority failure is slot-local
            return RowsRead([], available=False, reason="campaign_observation_authority_unavailable")
        if any(not isinstance(page, list) for page in pages):
            return RowsRead([], available=False, reason="campaign_observation_read_invalid")
        return RowsRead(
            rows=[row for page in pages for row in page],
            available=True,
        )

    async def campaign_population_links(
        self, tenant_id: str, campaign_id: str, *, limit: int
    ) -> CampaignPopulationLinkRead:
        """Read latest exact tenant/campaign population association events."""
        return await CampaignPopulationLinkAuthority().read_current(
            tenant_id,
            campaign_id,
            limit=min(max(limit, 1), MAX_CAMPAIGN_POPULATION_LINKS),
        )

    async def campaign_spend(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        start: Optional[datetime],
        end: Optional[datetime],
        limit: int,
    ) -> CampaignSpendRead:
        """Read bounded spend facts by their canonical tenant/campaign keys.

        The spend ledger has no coverage watermark, so its rows are observed
        facts and cannot attest that a period's campaign spend is complete.
        """
        try:
            from journeys.measurement.repositories.spend_repo import SpendRepository

            rows = await SpendRepository().list_by_campaign(
                tenant_id,
                campaign_id,
                period_start=start,
                period_end=end,
                limit=min(max(limit, 1), MAX_CAMPAIGN_PERFORMANCE_SPEND_ROWS + 1),
            )
        except Exception:  # noqa: BLE001 - economic source failure is slot-local
            return CampaignSpendRead(
                rows=[],
                available=False,
                complete=False,
                reason="campaign_spend_repository_unavailable",
            )
        return CampaignSpendRead(
            rows=list(rows),
            available=True,
            complete=False,
            reason="campaign_spend_coverage_watermark_unavailable",
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


def _safe_campaign_source_id(value: Any) -> bool:
    """Accept bounded source identifiers that cannot alter evidence URIs."""
    if not isinstance(value, str) or not value or len(value) > 128:
        return False
    return all(character.isalnum() or character in "_.:-" for character in value)


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


def _parse_temporal_value(value: Any) -> Optional[datetime]:
    """Parse an aware repository timestamp without inventing a timezone."""
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


def _finite_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except Exception:  # noqa: BLE001 - malformed numeric is unknown, not zero
        return None
    return parsed if parsed.is_finite() else None


def _currency_code(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    code = value.strip().upper()
    return code if len(code) == 3 and code.isascii() and code.isalpha() else None


def _provenance_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _conversion_monetary_state(record: dict[str, Any]) -> str:
    """Whether canonical conversion amounts have a known normalized currency."""
    source_currency = _currency_code(record.get("currency"))
    normalized_currency = _currency_code(record.get("normalized_currency"))
    if source_currency is None or normalized_currency is None:
        return "unknown"
    if source_currency == normalized_currency:
        return "normalized"
    provenance = _provenance_mapping(record.get("provenance"))
    fx = provenance.get("fx_conversion")
    if not isinstance(fx, dict) or fx.get("priced") is not True:
        return "unpriced"
    rate = _finite_decimal(record.get("exchange_rate"))
    evidence_rate = _finite_decimal(fx.get("exchange_rate"))
    if rate is None or rate <= 0 or evidence_rate is None or evidence_rate != rate:
        return "unpriced"
    return "normalized"


def _normalized_spend_amount(
    row: dict[str, Any],
) -> Optional[tuple[Decimal, str]]:
    """Return a spend amount only when its currency conversion is evidenced."""
    amount = _finite_decimal(row.get("total_cost"))
    billing_currency = _currency_code(row.get("billing_currency"))
    normalized_currency = _currency_code(row.get("normalized_currency"))
    if (
        amount is None
        or billing_currency is None
        or normalized_currency is None
    ):
        return None
    if billing_currency == normalized_currency:
        return amount, normalized_currency
    provenance = _provenance_mapping(row.get("provenance"))
    fx = provenance.get("fx_conversion")
    if not isinstance(fx, dict) or fx.get("priced") is not True:
        return None
    rate = _finite_decimal(row.get("exchange_rate"))
    evidence_rate = _finite_decimal(fx.get("exchange_rate"))
    if rate is None or rate <= 0 or evidence_rate is None or evidence_rate != rate:
        return None
    return amount * rate, normalized_currency


def _safe_evidence_ref(value: Any) -> Optional[EvidenceRef]:
    try:
        return EvidenceRef.model_validate(value)
    except Exception:  # noqa: BLE001 - malformed evidence is not projected
        return None


def _dedupe_evidence(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    unique: dict[tuple[str, str], EvidenceRef] = {}
    for ref in refs:
        unique[(ref.source, ref.id)] = ref
    return list(unique.values())


def _refs_from_wire(values: Any) -> list[EvidenceRef]:
    if not isinstance(values, list):
        return []
    return _dedupe_evidence(
        [ref for raw in values if (ref := _safe_evidence_ref(raw)) is not None]
    )


def _campaign_attributed_outcome(
    *,
    slot_states: dict[str, dict[str, Any]],
    credit_items: list[dict[str, Any]],
    conversion_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize only complete active credits joined to exact conversions."""
    attribution = slot_states.get(SLOT_ATTRIBUTION, {})
    conversions_slot = slot_states.get(SLOT_CONVERSIONS, {})
    base_metric = {"state": "unknown", "byCurrency": {}, "reason": None}
    if attribution.get("state") == "empty":
        return {
            "state": "empty",
            "conversionCount": 0,
            "creditCount": 0,
            "grossRevenue": {**base_metric, "reason": "no_active_campaign_attribution_credits"},
            "netRevenue": {**base_metric, "reason": "no_active_campaign_attribution_credits"},
            "grossEvidenceRefsByCurrency": {},
            "netEvidenceRefsByCurrency": {},
            "reason": "no_active_campaign_attribution_credits",
        }
    if attribution.get("state") != "available" or attribution.get("qualityState") != "complete":
        reason = "active_campaign_attribution_incomplete"
        return {
            "state": "unknown",
            "conversionCount": 0,
            "creditCount": len(credit_items),
            "grossRevenue": {**base_metric, "reason": reason},
            "netRevenue": {**base_metric, "reason": reason},
            "grossEvidenceRefsByCurrency": {},
            "netEvidenceRefsByCurrency": {},
            "reason": reason,
        }
    if conversions_slot.get("state") != "available":
        reason = "canonical_campaign_conversion_join_incomplete"
        return {
            "state": "unknown",
            "conversionCount": len(conversion_items),
            "creditCount": len(credit_items),
            "grossRevenue": {**base_metric, "reason": reason},
            "netRevenue": {**base_metric, "reason": reason},
            "grossEvidenceRefsByCurrency": {},
            "netEvidenceRefsByCurrency": {},
            "reason": reason,
        }
    if not credit_items:
        reason = "active_attribution_credit_amounts_unavailable"
        return {
            "state": "unknown",
            "conversionCount": len(conversion_items),
            "creditCount": 0,
            "grossRevenue": {**base_metric, "reason": reason},
            "netRevenue": {**base_metric, "reason": reason},
            "grossEvidenceRefsByCurrency": {},
            "netEvidenceRefsByCurrency": {},
            "reason": reason,
        }

    conversions: dict[str, dict[str, Any]] = {}
    for item in conversion_items:
        conversion = item.get("conversion") if isinstance(item, dict) else None
        if not isinstance(conversion, dict):
            continue
        conversion_id = conversion.get("conversionId")
        if isinstance(conversion_id, str) and conversion_id:
            if conversion_id in conversions:
                reason = "canonical_conversion_join_conflicted"
                return {
                    "state": "unknown",
                    "conversionCount": len(conversions),
                    "creditCount": len(credit_items),
                    "grossRevenue": {**base_metric, "reason": reason},
                    "netRevenue": {**base_metric, "reason": reason},
                    "grossEvidenceRefsByCurrency": {},
                    "netEvidenceRefsByCurrency": {},
                    "reason": reason,
                }
            conversions[conversion_id] = conversion

    credit_ids: set[str] = set()
    gross: dict[str, Decimal] = {}
    net: dict[str, Decimal] = {}
    evidence_by_currency: dict[str, list[EvidenceRef]] = {}
    gross_complete = True
    net_complete = True
    stale = False
    conversion_ids: set[str] = set()
    for item in credit_items:
        credit = item.get("credit") if isinstance(item, dict) else None
        if not isinstance(credit, dict):
            gross_complete = net_complete = False
            continue
        credit_id = credit.get("creditId")
        conversion_id = credit.get("conversionId")
        if not isinstance(credit_id, str) or not credit_id or credit_id in credit_ids:
            reason = "active_attribution_credit_identity_conflicted"
            return {
                "state": "unknown",
                "conversionCount": len(conversion_ids),
                "creditCount": len(credit_items),
                "grossRevenue": {**base_metric, "reason": reason},
                "netRevenue": {**base_metric, "reason": reason},
                "reason": reason,
            }
        credit_ids.add(credit_id)
        if not isinstance(conversion_id, str) or conversion_id not in conversions:
            gross_complete = net_complete = False
            continue
        conversion_ids.add(conversion_id)
        conversion = conversions[conversion_id]
        currency = _currency_code(conversion.get("normalizedCurrency"))
        if currency is None or conversion.get("conversionMonetaryState") != "normalized":
            gross_complete = net_complete = False
            continue
        currency_refs = evidence_by_currency.setdefault(currency, [])
        currency_refs.extend(_refs_from_wire(item.get("evidenceRefs", [])))
        conversion_item = next(
            (
                candidate
                for candidate in conversion_items
                if isinstance(candidate, dict)
                and isinstance(candidate.get("conversion"), dict)
                and candidate["conversion"].get("conversionId") == conversion_id
            ),
            None,
        )
        if conversion_item is not None:
            currency_refs.extend(_refs_from_wire(conversion_item.get("evidenceRefs", [])))
        run_completed = _parse_temporal_value(credit.get("runCompletedAt"))
        adjusted_at = _parse_temporal_value(conversion.get("adjustedAt"))
        if run_completed is None:
            gross_complete = net_complete = False
            stale = True
            continue
        if adjusted_at is not None and adjusted_at > run_completed:
            stale = True
            gross_complete = net_complete = False
            continue
        gross_amount = _finite_decimal(credit.get("attributedGrossRevenue"))
        net_amount = _finite_decimal(credit.get("attributedNetRevenue"))
        if gross_amount is None:
            gross_complete = False
        else:
            gross[currency] = gross.get(currency, Decimal("0")) + gross_amount
        if net_amount is None:
            net_complete = False
        else:
            net[currency] = net.get(currency, Decimal("0")) + net_amount

    if len(conversion_ids) != len(conversions):
        gross_complete = net_complete = False
    gross_state = "available" if gross_complete and gross else "unknown"
    net_state = "available" if net_complete and net else "unknown"
    gross_reason = None if gross_state == "available" else (
        "attribution_run_stale_to_conversion" if stale else "attributed_gross_amount_incomplete"
    )
    net_reason = None if net_state == "available" else (
        "attribution_run_stale_to_conversion" if stale else "attributed_net_amount_incomplete"
    )
    state = "available" if gross_state == "available" or net_state == "available" else "unknown"
    reason = None if state == "available" else gross_reason or net_reason
    return {
        "state": state,
        "conversionCount": len(conversion_ids),
        "creditCount": len(credit_items),
        "grossRevenue": {
            "state": gross_state,
            "byCurrency": {currency: format(amount, "f") for currency, amount in sorted(gross.items())}
            if gross_state == "available"
            else {},
            "reason": gross_reason,
        },
        "netRevenue": {
            "state": net_state,
            "byCurrency": {currency: format(amount, "f") for currency, amount in sorted(net.items())}
            if net_state == "available"
            else {},
            "reason": net_reason,
        },
        "grossEvidenceRefsByCurrency": {
            currency: [
                ref.model_dump(by_alias=True, exclude_none=True)
                for ref in _dedupe_evidence(refs)
            ]
            for currency, refs in evidence_by_currency.items()
        },
        "netEvidenceRefsByCurrency": {
            currency: [
                ref.model_dump(by_alias=True, exclude_none=True)
                for ref in _dedupe_evidence(refs)
            ]
            for currency, refs in evidence_by_currency.items()
        },
        "reason": reason,
    }


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

    def __init__(
        self,
        source: Optional[Campaign360Source] = None,
        *,
        population_reader: Any = None,
    ) -> None:
        self._source = source or RepositoryCampaign360Source()
        self._population_reader = population_reader

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
        source_classification_items: list[dict[str, Any]] = []
        signal_touchpoint_evidence: dict[str, list[EvidenceRef]] = {}
        signal_reference_issues: list[str] = []
        signal_context: dict[str, Any] = {
            "state": "unknown",
            "subject": {"kind": subject.kind, "id": subject.id},
            "events": [],
            "dimensionStates": {
                "events": "unknown",
                "observations": "unknown",
                "sourceFacts": "unknown",
            },
            "freshness": {"state": "unknown", "sourceTimestampsPreserved": True},
            "reason": "campaign_signal_source_join_unavailable",
        }
        credit_items: list[dict[str, Any]] = []
        conversion_items: list[dict[str, Any]] = []
        campaign_anomaly_context: dict[str, Any] = {
            "state": "unknown",
            "subject": {"kind": subject.kind, "id": subject.id},
            "findings": [],
            "dimensionStates": {
                "targetingLeakageFindings": "unknown",
                "riskOutputs": "unknown",
                "sourceAnomalies": "unknown",
            },
            "freshness": {"state": "unknown", "sourceTimestampsPreserved": True},
            "reason": "campaign_anomaly_authority_not_connected",
        }
        campaign_population_context: dict[str, Any] = {
            "state": "unknown",
            "subject": {"kind": subject.kind, "id": subject.id},
            "associations": [],
            "dimensionStates": {
                "explicitPopulationLinks": "unknown",
                "broaderCohortMembership": "unknown",
                "syndicateMembership": "unknown",
            },
            "reason": "campaign_population_link_authority_not_connected",
        }
        campaign_performance_context: dict[str, Any] = {
            "state": "unknown",
            "subject": {"kind": subject.kind, "id": subject.id},
            "attributedOutcome": {"state": "unknown", "reason": "campaign_outcome_join_unavailable"},
            "spendObservations": {"state": "unknown", "reason": "campaign_spend_authority_not_connected"},
            "roas": {"state": "unknown", "reason": "complete_spend_and_revenue_evidence_required"},
            "roi": {"state": "unknown", "reason": "complete_cost_and_return_definition_required"},
            "reason": "campaign_performance_join_unavailable",
        }
        touchpoint_page: Optional[PageInfo] = None
        campaign_found = False
        campaign_id: Optional[str] = None
        journey_context: dict[str, Any] = {
            "state": "unknown",
            "subject": {"kind": subject.kind, "id": subject.id},
            "journeys": [],
            "episodes": [],
            "dimensionStates": {"journeys": "unknown", "episodes": "unknown"},
            "freshness": {"state": "unknown", "sourceTimestampsPreserved": True},
            "reason": "journey_context_not_resolved",
        }
        source_classification: dict[str, Any] = {
            "state": "unknown",
            "subject": {"kind": subject.kind, "id": subject.id},
            "reason": "source_classification_authority_not_connected",
        }

        if subject.kind != "campaign":
            for slot_id, _requirement in _SLOT_REQUIREMENTS:
                slot_states[slot_id].update(
                    state="not_applicable",
                    reason="campaign_360_requires_campaign_subject",
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
                    # The campaign registry records whether an identity came
                    # from an external connector or a custom source, but it is
                    # not the canonical source-classification authority. Keep
                    # that distinction visible and leave the classification
                    # slot unknown until source provenance is joined.
                    source_classification = {
                        "state": "unknown",
                        "subject": {"kind": subject.kind, "id": subject.id},
                        "registryOrigin": _string_or_none(
                            campaign_record.get("origin")
                        ),
                        "primaryPlatform": _string_or_none(
                            campaign_record.get("primary_platform")
                        ),
                        "reason": "canonical_source_classification_join_unavailable",
                    }
                    slot_states[SLOT_SOURCE_CLASSIFICATION].update(
                        state="unknown",
                        reason="canonical_source_classification_join_unavailable",
                        sourceAuthorities=["source_facts", "source_provenance"],
                    )
                    slot_states[SLOT_SIGNAL_SOURCES].update(
                        state="unknown",
                        reason="campaign_signal_source_join_unavailable",
                        sourceAuthorities=["events", "observations", "source_facts"],
                    )
                    slot_states[SLOT_CONVERSIONS].update(
                        state="unknown",
                        reason="canonical_campaign_conversion_join_unavailable",
                        sourceAuthorities=["outcome_facts", "outcomes"],
                    )
                    slot_states[SLOT_COHORTS_SYNDICATES].update(
                        state="unknown",
                        reason="campaign_cohort_and_syndicate_membership_unavailable",
                        sourceAuthorities=[
                            "cohort_membership",
                            "cluster_definitions",
                            "cluster_membership",
                            "relationship_facts",
                        ],
                    )
                    slot_states[SLOT_PERFORMANCE].update(
                        state="unknown",
                        reason="campaign_performance_evidence_not_resolved",
                        sourceAuthorities=[
                            "canonical_conversions",
                            "attribution_credits",
                            "spend_records",
                        ],
                    )
                    slot_states[SLOT_ANOMALIES].update(
                        state="unknown",
                        reason="campaign_anomaly_authority_not_connected",
                        sourceAuthorities=["risk_outputs", "source_provenance"],
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
                            source_classification_items=source_classification_items,
                            signal_touchpoint_evidence=signal_touchpoint_evidence,
                            signal_reference_issues=signal_reference_issues,
                            evidence_by_key=evidence_by_key,
                            claims=claims,
                            degraded_reasons=degraded_reasons,
                        )
                        signal_context = await self._read_campaign_signal_context(
                            request=request,
                            context=context,
                            campaign_id=campaign_id,
                            temporal=temporal,
                            touchpoint_evidence_by_event=signal_touchpoint_evidence,
                            reference_issues=signal_reference_issues,
                            slot_states=slot_states,
                            evidence_by_key=evidence_by_key,
                            claims=claims,
                            degraded_reasons=degraded_reasons,
                        )
                        if source_classification_items:
                            source_classification = {
                                "state": "degraded",
                                "subject": {"kind": subject.kind, "id": subject.id},
                                "touchpointClassifications": source_classification_items,
                                "reason": "observed_touchpoint_classifications_only_campaign_registry_source_unresolved",
                            }
                            slot_states[SLOT_SOURCE_CLASSIFICATION].update(
                                state="degraded",
                                reason="observed_touchpoint_classifications_only_campaign_registry_source_unresolved",
                                sourceAuthorities=["campaign_touchpoints", "source_provenance"],
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
                        await self._read_campaign_conversions(
                            request=request,
                            campaign_id=campaign_id,
                            credit_items=credit_items,
                            conversion_items=conversion_items,
                            slot_states=slot_states,
                            evidence_by_key=evidence_by_key,
                            claims=claims,
                            degraded_reasons=degraded_reasons,
                        )
                        campaign_performance_context = await self._read_campaign_performance(
                            request=request,
                            campaign_id=campaign_id,
                            temporal=temporal,
                            credit_items=credit_items,
                            conversion_items=conversion_items,
                            slot_states=slot_states,
                            evidence_by_key=evidence_by_key,
                            claims=claims,
                            degraded_reasons=degraded_reasons,
                        )
                    else:
                        for slot_id in (
                            SLOT_TOUCHPOINTS,
                            SLOT_ATTRIBUTION,
                        ):
                            slot_states[slot_id].update(
                                state="unknown",
                                reason=temporal.reason or "temporal_scope_unavailable",
                                sourceAuthorities=(
                                    ["touchpoints"]
                                    if slot_id == SLOT_TOUCHPOINTS
                                    else ["attribution_credits"]
                                ),
                            )
                        slot_states[SLOT_CONVERSIONS].update(
                            state="unknown",
                            reason=temporal.reason or "temporal_scope_unavailable",
                            sourceAuthorities=["canonical_conversions", "attribution_credits"],
                        )
                        findings.append(
                            {
                                "code": temporal.reason or "temporal_scope_unavailable",
                                "domainSlotIds": [
                                    SLOT_TOUCHPOINTS,
                                    SLOT_ATTRIBUTION,
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
                    slot_states[SLOT_ATTRIBUTION].update(
                        state="unknown",
                        reason="campaign_registry_subject_not_available",
                        sourceAuthorities=["attribution_credits"],
                    )
                    slot_states[SLOT_CONVERSIONS].update(
                        state="unknown",
                        reason="campaign_registry_subject_not_available",
                        sourceAuthorities=["canonical_conversions", "attribution_credits"],
                    )

                # Join the canonical journey authority by its explicit
                # campaign_ids membership. Episode records have no typed
                # campaign relation, so that dimension remains unknown.
                if campaign_found and temporal.observations_supported:
                    journey_context = await self._read_campaign_journey_context(
                        request=request,
                        campaign_id=campaign_id or "",
                        temporal=temporal,
                        slot_states=slot_states,
                        evidence_by_key=evidence_by_key,
                        claims=claims,
                        degraded_reasons=degraded_reasons,
                    )
                else:
                    slot_states[SLOT_JOURNEYS].update(
                        state="unknown",
                        reason=(
                            temporal.reason
                            if campaign_found
                            else "campaign_registry_subject_not_available"
                        ),
                        sourceAuthorities=["journeys"],
                        dimensionStates={"journeys": "unknown"},
                    )
                if campaign_found and temporal.observations_supported:
                    campaign_anomaly_context = await self._read_campaign_anomalies(
                        request=request,
                        campaign_id=campaign_id or "",
                        temporal=temporal,
                        slot_states=slot_states,
                        evidence_by_key=evidence_by_key,
                        claims=claims,
                        degraded_reasons=degraded_reasons,
                    )
                else:
                    slot_states[SLOT_ANOMALIES].update(
                        state="unknown",
                        reason=(
                            temporal.reason
                            if campaign_found
                            else "campaign_registry_subject_not_available"
                        ),
                        sourceAuthorities=["risk_outputs", "source_provenance"],
                        dimensionStates={
                            "targetingLeakageFindings": "unknown",
                            "riskOutputs": "unknown",
                            "sourceAnomalies": "unknown",
                        },
                    )
                    campaign_anomaly_context.update(
                        state="unknown",
                        reason=(
                            temporal.reason
                            if campaign_found
                            else "campaign_registry_subject_not_available"
                        ),
                    )
                if campaign_found and temporal.observations_supported:
                    campaign_population_context = await self._read_campaign_population_links(
                        request=request,
                        campaign_id=campaign_id or "",
                        slot_states=slot_states,
                        evidence_by_key=evidence_by_key,
                        claims=claims,
                        degraded_reasons=degraded_reasons,
                    )
                else:
                    reason = (
                        temporal.reason
                        if campaign_found
                        else "campaign_registry_subject_not_available"
                    )
                    slot_states[SLOT_COHORTS_SYNDICATES].update(
                        state="unknown",
                        reason=reason,
                        sourceAuthorities=[
                            "campaign_population_link_events",
                            "population_definitions",
                            "cluster_membership",
                            "relationship_facts",
                        ],
                        dimensionStates={
                            "explicitPopulationLinks": "unknown",
                            "broaderCohortMembership": "unknown",
                            "syndicateMembership": "unknown",
                        },
                    )
                    campaign_population_context.update(state="unknown", reason=reason)
                if not campaign_found or not temporal.observations_supported:
                    reason = (
                        temporal.reason
                        if campaign_found
                        else "campaign_registry_subject_not_available"
                    )
                    slot_states[SLOT_PERFORMANCE].update(
                        state="unknown",
                        reason=reason,
                        sourceAuthorities=[
                            "canonical_conversions",
                            "attribution_credits",
                            "spend_records",
                        ],
                    )
                    campaign_performance_context.update(
                        state="unknown",
                        reason=reason,
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

        evidence_items = []
        for ref in evidence_by_key.values():
            slots = _slots_for_evidence(ref, claims, campaign_id)
            slots.append(SLOT_EVIDENCE_TRACE)
            slots = list(dict.fromkeys(slots))
            evidence_items.append(
                {
                    "evidence": ref.model_dump(by_alias=True, exclude_none=True),
                    "domainSlotIds": slots,
                }
            )
            if request.includeClaims is not False:
                claims.append(
                    _claim(
                        claim_id=f"campaign360:{campaign_id or subject.id}:evidence:{ref.source}:{ref.id}",
                        kind="campaign_evidence_trace_entry",
                        subject=subject,
                        evidence=ref,
                        text="A canonical source record is included in the campaign evidence trace.",
                        slot_id=SLOT_EVIDENCE_TRACE,
                    )
                )
        slot_states[SLOT_EVIDENCE_TRACE].update(
            state=(
                "available"
                if evidence_items
                else "empty"
                if campaign_found
                else "unknown"
            ),
            reason=None if evidence_items else "campaign_evidence_trace_not_resolved",
            sourceAuthorities=["evidence", "source_provenance"],
            evidenceCount=len(evidence_items),
        )
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
        elif attribution_state == "empty":
            outcomes_section_state = "empty"
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
            "domainContexts": {
                SLOT_SOURCE_CLASSIFICATION: source_classification,
                SLOT_SIGNAL_SOURCES: signal_context,
                SLOT_JOURNEYS: journey_context,
                SLOT_CONVERSIONS: {
                    "state": slot_states[SLOT_CONVERSIONS]["state"],
                    "subject": {"kind": subject.kind, "id": subject.id},
                    "reason": slot_states[SLOT_CONVERSIONS].get("reason"),
                    "conversionCount": len(conversion_items),
                    "items": conversion_items,
                },
                SLOT_COHORTS_SYNDICATES: {
                    **campaign_population_context,
                },
                SLOT_PERFORMANCE: {
                    **campaign_performance_context,
                },
                SLOT_ANOMALIES: {
                    **campaign_anomaly_context,
                },
                SLOT_EVIDENCE_TRACE: {
                    "state": slot_states[SLOT_EVIDENCE_TRACE]["state"],
                    "items": evidence_items,
                },
            },
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
                        SLOT_SOURCE_CLASSIFICATION,
                        SLOT_SIGNAL_SOURCES,
                        SLOT_TOUCHPOINTS,
                        SLOT_JOURNEYS,
                        SLOT_CONVERSIONS,
                        SLOT_ATTRIBUTION,
                        SLOT_COHORTS_SYNDICATES,
                        SLOT_PERFORMANCE,
                        SLOT_ANOMALIES,
                        SLOT_EVIDENCE_TRACE,
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
                        "touchpoint source classifications do not classify campaign registry provenance",
                        "signal_sources include exact touchpoint-linked events only; broader observations and source facts remain unknown",
                        "communication content remains governed by communication360",
                        "conversion records are joined only through exact active campaign attribution credits; unattributed conversions remain outside this view",
                        "explicit campaign-population links are operator asserted; broader cohort and syndicate membership remains unknown",
                        "campaign spend coverage is not attested, so full-period totals and ROAS remain unknown",
                        "exact campaign Risk360 assessments and targeting leakage findings have separate partial coverage; source anomalies and campaign risk producer completeness remain unresolved",
                        "actor attribution, delegation, and authority are not resolved by this provider",
                        "current campaign state is not a historical snapshot",
                    ],
                },
            ),
            _section(
                "anomalies",
                (
                    "degraded"
                    if campaign_anomaly_context.get("state")
                    in {"partial", "truncated", "degraded"}
                    else "unknown"
                ),
                campaign_anomaly_context,
            ),
            _section(
                "outcomes",
                outcomes_section_state,
                {
                    "attribution": {
                        "state": attribution_state,
                        "dataQuality": slot_states[SLOT_ATTRIBUTION].get(
                            "qualityState", "unknown"
                        ),
                        "credits": credit_items,
                        "creditsTruncated": slot_states[
                            SLOT_ATTRIBUTION
                        ].get("creditsTruncated", False),
                        "domainSlotIds": [SLOT_ATTRIBUTION],
                        "zeroDefaulted": False,
                    },
                    "conversions": {
                        "state": slot_states[SLOT_CONVERSIONS]["state"],
                        "items": conversion_items,
                        "domainSlotIds": [SLOT_CONVERSIONS],
                        "joinAuthority": "canonical_conversions_by_exact_tenant_id_via_active_campaign_credit",
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

    async def _read_campaign_risk_assessments(
        self,
        *,
        request: ProjectionRequest,
        campaign_id: str,
        temporal: _TemporalScope,
        evidence_by_key: dict[tuple[str, str], EvidenceRef],
        claims: list[ClaimEnvelope],
    ) -> dict[str, Any]:
        """Expose exact Risk360 output as assessments, not inferred anomalies."""
        source_read = getattr(self._source, "campaign_risk_assessments", None)
        if not callable(source_read):
            return {"state": "unknown", "reason": "campaign_risk_assessment_binding_unavailable", "items": []}
        try:
            read = await source_read(
                request.tenantId, campaign_id, limit=MAX_CAMPAIGN_ANOMALIES + 1
            )
        except Exception:  # noqa: BLE001 - risk authority failure is dimension-local
            read = None
        if not isinstance(read, CampaignRiskAssessmentRead) or not read.available:
            return {"state": "unavailable", "reason": "campaign_risk_assessment_authority_unavailable", "items": []}
        if not isinstance(read.rows, list) or any(not isinstance(row, dict) for row in read.rows):
            return {"state": "unknown", "reason": "campaign_risk_assessment_result_invalid", "items": []}
        if any(
            row.get("tenant_id") != request.tenantId
            or row.get("subject_kind") != "campaign"
            or row.get("subject_id") != campaign_id
            for row in read.rows
        ):
            return {"state": "unknown", "reason": "campaign_risk_assessment_scope_mismatch", "items": []}
        try:
            from intelligence.risk360.contracts import RiskAssessment

            assessments = [RiskAssessment.model_validate(row) for row in read.rows]
        except Exception:  # noqa: BLE001 - malformed canonical output cannot be projected
            return {"state": "unknown", "reason": "campaign_risk_assessment_contract_invalid", "items": []}
        assessment_ids = [assessment.assessment_id for assessment in assessments]
        if len(assessment_ids) != len(set(assessment_ids)) or any(
            not _safe_campaign_source_id(value) for value in assessment_ids
        ):
            return {"state": "unknown", "reason": "campaign_risk_assessment_id_ambiguous", "items": []}

        truncated = not read.complete or len(assessments) > MAX_CAMPAIGN_ANOMALIES
        items: list[dict[str, Any]] = []
        pending_refs: list[EvidenceRef] = []
        pending_claims: list[ClaimEnvelope] = []
        missing_time_or_evidence = False
        for assessment in assessments[:MAX_CAMPAIGN_ANOMALIES]:
            assessed_at = _scalar(assessment.assessed_at)
            try:
                at = _parse_instant(assessed_at) if isinstance(assessed_at, str) else None
            except ValueError:
                at = None
            if at is None:
                missing_time_or_evidence = True
                continue
            if (temporal.start is not None and at < temporal.start) or (
                temporal.end is not None and at >= temporal.end
            ):
                continue
            source_refs: list[EvidenceRef] = []
            for ref in assessment.evidence_refs:
                if (
                    not _safe_campaign_source_id(ref.id)
                    or not _safe_campaign_source_id(ref.source)
                    or ref.observedAt is None
                ):
                    break
                try:
                    _parse_instant(ref.observedAt)
                except ValueError:
                    break
                source_refs.append(
                    EvidenceRef(
                        id=ref.id,
                        type=ref.type,
                        source=ref.source,
                        observedAt=ref.observedAt,
                    )
                )
            else:
                if source_refs:
                    assessment_ref = EvidenceRef(
                        id=assessment.assessment_id,
                        type="model_output",
                        source=_CAMPAIGN_RISK_ASSESSMENT_SOURCE,
                        observedAt=at.isoformat(),
                        uri=(
                            "store://risk_assessments/"
                            f"{quote(request.tenantId, safe='')}:{quote(assessment.assessment_id, safe='')}"
                        ),
                    )
                    refs = [assessment_ref, *source_refs]
                    pending_refs.extend(refs)
                    items.append(
                        {
                            "assessmentId": assessment.assessment_id,
                            "assessedAt": at.isoformat(),
                            "dimensionsEvaluated": list(assessment.dimensions),
                            "claimState": assessment.claim_state.value,
                            "policyState": "unknown",
                            "evidenceRefs": [
                                ref.model_dump(by_alias=True, exclude_none=True) for ref in refs
                            ],
                            "domainSlotIds": [SLOT_ANOMALIES],
                        }
                    )
                    pending_claims.append(
                        ClaimEnvelope(
                            id=f"campaign360:{campaign_id}:risk-assessment:{assessment.assessment_id}",
                            kind="campaign_risk_assessment_exact_subject",
                            subject=request.subject,
                            evidenceRefs=refs,
                            claims=[
                                "A canonical Risk360 assessment names this exact tenant and campaign; this does not establish complete risk producer coverage, an anomaly finding, or current policy authorization."
                            ],
                            claimState=assessment.claim_state,
                            domainSlotIds=[SLOT_ANOMALIES],
                        )
                    )
                    continue
            missing_time_or_evidence = True
        for ref in pending_refs:
            _add_evidence(evidence_by_key, ref)
        claims.extend(pending_claims)
        state = (
            "truncated" if truncated else "partial" if missing_time_or_evidence
            else "available" if items else "empty"
        )
        return {
            "state": state,
            "reason": (
                "campaign_risk_assessment_read_truncated" if truncated
                else "campaign_risk_assessment_time_or_evidence_missing" if missing_time_or_evidence
                else "exact_campaign_risk_assessments_producer_coverage_unknown"
            ),
            "items": items,
            "readCompleteForExactSubject": not truncated and not missing_time_or_evidence,
            "producerCoverageState": "unknown",
        }

    async def _read_campaign_anomalies(
        self,
        *,
        request: ProjectionRequest,
        campaign_id: str,
        temporal: _TemporalScope,
        slot_states: dict[str, dict[str, Any]],
        evidence_by_key: dict[tuple[str, str], EvidenceRef],
        claims: list[ClaimEnvelope],
        degraded_reasons: list[str],
    ) -> dict[str, Any]:
        """Project exact targeting findings and separate campaign risk assessments.

        Both reads use the exact tenant/campaign key. A Risk360 assessment is
        its own output, never inferred from a signal or targeting finding. An
        empty read cannot establish all-risk clear or complete producer coverage.
        """
        base: dict[str, Any] = {
            "subject": {"kind": request.subject.kind, "id": request.subject.id},
            "campaignId": campaign_id,
            "findings": [],
            "dimensionStates": {
                "targetingLeakageFindings": "unknown",
                "riskOutputs": "unknown",
                "sourceAnomalies": "unknown",
            },
            "freshness": {"state": "unknown", "sourceTimestampsPreserved": True},
            "temporalBounds": {
                "from": _scalar(temporal.start),
                "fromInclusive": True,
                "to": _scalar(temporal.end),
                "toExclusive": True,
            },
        }
        risk_output = await self._read_campaign_risk_assessments(
            request=request,
            campaign_id=campaign_id,
            temporal=temporal,
            evidence_by_key=evidence_by_key,
            claims=claims,
        )
        base["riskAssessments"] = risk_output["items"]
        base["riskAssessmentRead"] = {
            key: value for key, value in risk_output.items() if key != "items"
        }
        base["dimensionStates"]["riskOutputs"] = risk_output["state"]
        source_read = getattr(self._source, "campaign_anomalies", None)
        if not callable(source_read):
            reason = "targeting_anomaly_authority_binding_unavailable"
            slot_states[SLOT_ANOMALIES].update(
                state="unknown",
                reason=reason,
                sourceAuthorities=["targeting_leakage_findings", "risk_outputs", "source_provenance"],
                dimensionStates={**base["dimensionStates"], "targetingLeakageFindings": "unknown"},
            )
            return {**base, "state": "unknown", "reason": reason}

        try:
            read = await source_read(
                request.tenantId,
                campaign_id,
                limit=MAX_CAMPAIGN_ANOMALIES + 1,
            )
        except Exception:  # noqa: BLE001 - source diagnostics stay private
            read = CampaignAnomalyRead([], available=False, complete=False)
        if not isinstance(read, CampaignAnomalyRead) or not read.available:
            reason = "targeting_anomaly_authority_unavailable"
            slot_states[SLOT_ANOMALIES].update(
                state="degraded",
                reason=reason,
                sourceAuthorities=["targeting_leakage_findings", "risk_outputs", "source_provenance"],
                dimensionStates={**base["dimensionStates"], "targetingLeakageFindings": "unavailable"},
            )
            degraded_reasons.append(reason)
            return {
                **base,
                "state": "degraded",
                "dimensionStates": {**base["dimensionStates"], "targetingLeakageFindings": "unavailable"},
                "reason": reason,
            }
        if any(not isinstance(row, dict) for row in read.rows):
            reason = "campaign_anomaly_record_shape_invalid"
            slot_states[SLOT_ANOMALIES].update(
                state="unknown",
                reason=reason,
                sourceAuthorities=["targeting_leakage_findings", "risk_outputs", "source_provenance"],
                dimensionStates=base["dimensionStates"],
            )
            degraded_reasons.append(reason)
            return {**base, "state": "unknown", "reason": reason}

        # Import the source authority's typed contract lazily with the repository
        # adapter so Campaign360 remains import-safe in lean deployments.
        try:
            from intelligence.targeting_intelligence.models import (
                ExclusionLeakageFinding,
            )

            validated = [ExclusionLeakageFinding.model_validate(row) for row in read.rows]
        except Exception:  # noqa: BLE001 - malformed canonical data fails closed
            reason = "campaign_anomaly_record_invalid"
            slot_states[SLOT_ANOMALIES].update(
                state="unknown",
                reason=reason,
                sourceAuthorities=["targeting_leakage_findings", "risk_outputs", "source_provenance"],
                dimensionStates=base["dimensionStates"],
            )
            degraded_reasons.append(reason)
            return {**base, "state": "unknown", "reason": reason}

        if any(
            item.tenantId != request.tenantId or item.campaignId != campaign_id
            for item in validated
        ):
            reason = "campaign_anomaly_record_scope_mismatch"
            slot_states[SLOT_ANOMALIES].update(
                state="unknown",
                reason=reason,
                sourceAuthorities=["targeting_leakage_findings", "risk_outputs", "source_provenance"],
                dimensionStates=base["dimensionStates"],
            )
            degraded_reasons.append(reason)
            return {**base, "state": "unknown", "reason": reason}

        ids = [item.findingId for item in validated]
        if len(ids) != len(set(ids)) or any(not _safe_campaign_source_id(value) for value in ids):
            reason = "campaign_anomaly_identifier_invalid_or_duplicated"
            slot_states[SLOT_ANOMALIES].update(
                state="unknown",
                reason=reason,
                sourceAuthorities=["targeting_leakage_findings", "risk_outputs", "source_provenance"],
                dimensionStates=base["dimensionStates"],
            )
            degraded_reasons.append(reason)
            return {**base, "state": "unknown", "reason": reason}

        truncated = not read.complete or len(validated) > MAX_CAMPAIGN_ANOMALIES
        validated = validated[:MAX_CAMPAIGN_ANOMALIES]
        anomaly_items: list[dict[str, Any]] = []
        pending_evidence: list[EvidenceRef] = []
        pending_claims: list[ClaimEnvelope] = []
        timestamps: list[tuple[datetime, str]] = []
        missing_timestamps = False
        missing_window_timestamps = False
        seen: set[str] = set()
        for finding in validated:
            if finding.findingId in seen:
                continue
            seen.add(finding.findingId)
            observed_at = _string_or_none(finding.computedAt)
            parsed_timestamp: Optional[datetime] = None
            if observed_at is not None:
                try:
                    parsed_timestamp = _parse_instant(observed_at)
                except ValueError:
                    missing_timestamps = True
                    observed_at = None
            else:
                missing_timestamps = True

            if parsed_timestamp is None and (temporal.start is not None or temporal.end is not None):
                # A timestamp-less finding cannot be placed into the requested
                # period. Keep the result incomplete instead of guessing.
                missing_window_timestamps = True
                continue
            if parsed_timestamp is not None and (
                (temporal.start is not None and parsed_timestamp < temporal.start)
                or (temporal.end is not None and parsed_timestamp >= temporal.end)
            ):
                continue
            if parsed_timestamp is not None and observed_at is not None:
                timestamps.append((parsed_timestamp, observed_at))

            source_refs: list[EvidenceRef] = []
            source_kinds: set[str] = set()
            for source_ref in finding.evidenceRefs:
                expected_type = {
                    "targeting_observation": "event",
                    "eligibility_snapshot": "annotation",
                }.get(source_ref.source)
                if (
                    expected_type is None
                    or source_ref.type != expected_type
                    or not _safe_campaign_source_id(source_ref.id)
                ):
                    continue
                source_kinds.add(source_ref.source)
                source_refs.append(
                    EvidenceRef(
                        id=source_ref.id,
                        type=source_ref.type,
                        source=source_ref.source,
                        observedAt=_string_or_none(source_ref.observedAt),
                    )
                )
            if not {"targeting_observation", "eligibility_snapshot"}.issubset(source_kinds):
                reason = "campaign_anomaly_evidence_chain_incomplete"
                slot_states[SLOT_ANOMALIES].update(
                    state="unknown",
                    reason=reason,
                    sourceAuthorities=["targeting_leakage_findings", "risk_outputs", "source_provenance"],
                    dimensionStates=base["dimensionStates"],
                )
                degraded_reasons.append(reason)
                return {**base, "state": "unknown", "reason": reason}

            finding_ref = EvidenceRef(
                id=finding.findingId,
                type="model_output",
                source=_TARGETING_ANOMALY_SOURCE,
                observedAt=observed_at,
                uri=f"store://targeting_leakage_findings/{finding.findingId}",
            )
            refs = [finding_ref, *source_refs]
            pending_evidence.extend(refs)
            anomaly_items.append(
                {
                    "findingId": finding.findingId,
                    "reasonCode": finding.reasonCode,
                    "severity": finding.severity,
                    "leakageRate": finding.leakageRate,
                    "excludedEntityCount": finding.excludedEntityCount,
                    "reachedEntityCount": finding.reachedEntityCount,
                    "computedAt": observed_at,
                    "evidenceRefs": [
                        item.model_dump(by_alias=True, exclude_none=True)
                        for item in refs
                    ],
                    "domainSlotIds": [SLOT_ANOMALIES],
                }
            )
            pending_claims.append(
                ClaimEnvelope(
                    id=f"campaign360:{campaign_id}:anomaly:{finding.findingId}",
                    kind="campaign_targeting_leakage_finding",
                    subject=request.subject,
                    evidenceRefs=refs,
                    claims=[
                        "A tenant-scoped canonical targeting leakage finding is recorded for this campaign; this is not a complete campaign risk assessment."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=[SLOT_ANOMALIES],
                )
            )

        for ref in pending_evidence:
            _add_evidence(evidence_by_key, ref)
        claims.extend(pending_claims)
        missing_timestamps = missing_timestamps or missing_window_timestamps
        if truncated:
            state = "truncated"
            reason = "campaign_targeting_leakage_findings_truncated"
            targeting_state = "truncated"
        else:
            state = "partial"
            reason = (
                "campaign_targeting_leakage_findings_have_unplaced_timestamps"
                if missing_window_timestamps
                else "exact_campaign_risk_assessments_and_targeting_findings_partial_coverage"
                if risk_output["items"]
                else "targeting_leakage_findings_only_other_anomaly_authorities_unresolved"
            )
            targeting_state = (
                "partial"
                if missing_window_timestamps
                else "available"
                if anomaly_items
                else "empty"
            )
        freshness_state = (
            "available"
            if timestamps and not missing_timestamps and not truncated
            else "unknown"
        )
        source_timestamp = max(timestamps, key=lambda pair: pair[0])[1] if timestamps else None
        dimension_states = {
            "targetingLeakageFindings": targeting_state,
            "riskOutputs": risk_output["state"],
            "sourceAnomalies": "unknown",
        }
        slot_states[SLOT_ANOMALIES].update(
            state=state,
            reason=reason,
            sourceAuthorities=[
                "targeting_leakage_findings",
                "risk_outputs",
                "source_provenance",
            ],
            dimensionStates=dimension_states,
            findingCount=len(anomaly_items),
            riskAssessmentCount=len(risk_output["items"]),
            freshnessState=freshness_state,
            sourceTimestamp=source_timestamp,
            findingsTruncated=truncated,
        )
        if truncated or missing_window_timestamps:
            degraded_reasons.append(reason)
        return {
            **base,
            "state": state,
            "findings": anomaly_items,
            "dimensionStates": dimension_states,
            "freshness": {
                "state": freshness_state,
                "sourceTimestamp": source_timestamp,
                "sourceTimestampsPreserved": True,
                "missingTimestamp": "unknown",
            },
            "reason": reason,
            "coverage": (
                "exact_targeting_findings_and_campaign_risk_assessments_partial"
                if risk_output["items"]
                else "targeting_leakage_findings_only"
            ),
            "findingsTruncated": truncated,
        }

    async def _read_campaign_signal_context(
        self,
        *,
        request: ProjectionRequest,
        context: ProjectionContext,
        campaign_id: str,
        temporal: _TemporalScope,
        touchpoint_evidence_by_event: dict[str, list[EvidenceRef]],
        reference_issues: list[str],
        slot_states: dict[str, dict[str, Any]],
        evidence_by_key: dict[tuple[str, str], EvidenceRef],
        claims: list[ClaimEnvelope],
        degraded_reasons: list[str],
    ) -> dict[str, Any]:
        """Join exact campaign touchpoint event references to canonical events.

        This is intentionally a partial signal view. It does not infer signal
        membership from a campaign label or event properties, and it does not
        substitute event records for source-fact authority. An exact admitted
        SDK Bronze observation may be joined, while broader coverage is unknown.
        """
        base: dict[str, Any] = {
            "state": "unknown",
            "subject": {"kind": request.subject.kind, "id": request.subject.id},
            "campaignId": campaign_id,
            "events": [],
            "dimensionStates": {
                "events": "unknown",
                "observations": "unknown",
                "sourceFacts": "unknown",
            },
            "coverage": "exact_touchpoint_linked_events_only",
            "freshness": {
                "state": "unknown",
                "sourceTimestampsPreserved": True,
                "missingTimestamp": "unknown",
                "maximumAgeConfigured": False,
            },
        }
        if context.tenantId != request.tenantId:
            reason = "projection_context_tenant_scope_mismatch"
            slot_states[SLOT_SIGNAL_SOURCES].update(
                state="unknown",
                reason=reason,
                sourceAuthorities=["events", "observations", "source_facts"],
                dimensionStates=base["dimensionStates"],
            )
            return {**base, "reason": reason}
        event_ids = list(touchpoint_evidence_by_event)
        source_read = getattr(self._source, "signal_events", None)
        if not event_ids or not callable(source_read):
            reason = (
                "campaign_touchpoint_event_references_unavailable"
                if not event_ids
                else "campaign_event_authority_binding_unavailable"
            )
            slot_states[SLOT_SIGNAL_SOURCES].update(
                state="unknown",
                reason=reason,
                sourceAuthorities=["events", "observations", "source_facts"],
                dimensionStates=base["dimensionStates"],
            )
            return {**base, "reason": reason}

        read_limit = min(len(event_ids), MAX_CAMPAIGN_SIGNAL_EVENTS)
        try:
            result = await source_read(
                request.tenantId,
                event_ids[:read_limit],
                limit=MAX_CAMPAIGN_SIGNAL_EVENTS,
            )
        except Exception:  # noqa: BLE001 - event source fails independently
            result = RowsRead([], available=False, reason="campaign_event_authority_unavailable")
        if not isinstance(result, RowsRead) or not result.available:
            reason = "campaign_event_authority_unavailable"
            slot_states[SLOT_SIGNAL_SOURCES].update(
                state="degraded",
                reason=reason,
                sourceAuthorities=["events", "observations", "source_facts"],
                dimensionStates={
                    "events": "unavailable",
                    "observations": "unknown",
                    "sourceFacts": "unknown",
                },
            )
            degraded_reasons.append(reason)
            return {
                **base,
                "state": "degraded",
                "dimensionStates": {
                    "events": "unavailable",
                    "observations": "unknown",
                    "sourceFacts": "unknown",
                },
                "reason": reason,
            }
        if any(not isinstance(row, dict) for row in result.rows):
            reason = "campaign_event_row_shape_invalid"
            slot_states[SLOT_SIGNAL_SOURCES].update(
                state="unknown",
                reason=reason,
                sourceAuthorities=["events", "observations", "source_facts"],
                dimensionStates=base["dimensionStates"],
            )
            degraded_reasons.append(reason)
            return {**base, "reason": reason}

        requested_event_ids = set(event_ids[:read_limit])
        if any(
            row.get("tenant_id") != request.tenantId
            or str(row.get("event_id") or "") not in requested_event_ids
            for row in result.rows
        ):
            reason = "campaign_event_record_scope_mismatch"
            slot_states[SLOT_SIGNAL_SOURCES].update(
                state="unknown",
                reason=reason,
                sourceAuthorities=["events", "observations", "source_facts"],
                dimensionStates=base["dimensionStates"],
            )
            degraded_reasons.append(reason)
            return {**base, "reason": reason}

        rows_by_id: dict[str, list[dict[str, Any]]] = {}
        for row in result.rows:
            rows_by_id.setdefault(str(row["event_id"]), []).append(row)
        event_items: list[dict[str, Any]] = []
        missing_timestamps = False
        temporal_timestamp_unavailable = False
        out_of_window = False
        duplicate_events = False
        for event_id in event_ids[:read_limit]:
            event_rows = rows_by_id.get(event_id, [])
            if not event_rows:
                continue
            if len(event_rows) != 1:
                duplicate_events = True
                continue
            row = event_rows[0]
            occurred_at = _string_or_none(row.get("occurred_at"))
            if occurred_at is None:
                missing_timestamps = True
                if temporal.start is not None or temporal.end is not None:
                    temporal_timestamp_unavailable = True
                    continue
            else:
                try:
                    occurred = _parse_instant(occurred_at)
                except (TypeError, ValueError):
                    missing_timestamps = True
                    occurred = None
                    if temporal.start is not None or temporal.end is not None:
                        temporal_timestamp_unavailable = True
                        continue
                if occurred is not None and (
                    (temporal.start is not None and occurred <= temporal.start)
                    or (temporal.end is not None and occurred >= temporal.end)
                ):
                    out_of_window = True
                    continue
            source_event_ref = EvidenceRef(
                id=event_id,
                type="event",
                source="services/api/repositories/repos.py:events",
                observedAt=occurred_at or _string_or_none(row.get("created_at")),
                uri=f"store://events/{quote(event_id, safe='')}",
            )
            _add_evidence(evidence_by_key, source_event_ref)
            touchpoint_refs = touchpoint_evidence_by_event[event_id]
            linked_touchpoint_refs = touchpoint_refs[:10]
            claim_evidence = [source_event_ref, *linked_touchpoint_refs]
            event_items.append(
                {
                    "eventId": event_id,
                    "eventType": _string_or_none(row.get("event_type")),
                    "eventFamily": _string_or_none(row.get("event_family")),
                    "source": _string_or_none(row.get("source")),
                    "occurredAt": occurred_at,
                    "linkedTouchpointIds": [ref.id for ref in linked_touchpoint_refs],
                    "evidenceRefs": [
                        ref.model_dump(by_alias=True, exclude_none=True)
                        for ref in claim_evidence
                    ],
                }
            )
            claims.append(
                ClaimEnvelope(
                    id=f"campaign360:{campaign_id}:signal-event:{event_id}",
                    kind="campaign_linked_signal_event",
                    subject=request.subject,
                    evidenceRefs=claim_evidence,
                    claims=[
                        "A tenant-scoped campaign touchpoint names this exact canonical event."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=[SLOT_SIGNAL_SOURCES],
                )
            )

        issues = list(reference_issues)
        returned_ids = {item["eventId"] for item in event_items}
        missing_events = requested_event_ids - returned_ids - set(rows_by_id)
        if missing_events:
            issues.append("campaign_touchpoint_event_record_unavailable")
        if len(event_ids) > read_limit:
            issues.append("campaign_signal_event_read_truncated")
        if temporal_timestamp_unavailable:
            issues.append("campaign_signal_event_timestamp_unavailable_for_temporal_scope")
        if out_of_window:
            issues.append("campaign_signal_event_outside_temporal_scope")
        if duplicate_events:
            issues.append("campaign_signal_event_identifier_ambiguous")
        if any(len(refs) > 10 for refs in touchpoint_evidence_by_event.values()):
            issues.append("campaign_signal_touchpoint_evidence_truncated")

        if event_items:
            state = "partial"
            reason = "campaign_signal_events_only"
        else:
            state = "unknown"
            reason = (
                issues[0]
                if issues
                else "campaign_touchpoint_event_record_not_resolved"
            )
        observation_context = await self._read_campaign_signal_observations(
            request=request,
            event_items=event_items,
            evidence_by_key=evidence_by_key,
            claims=claims,
        )
        dimension_states = {
            "events": "available" if event_items else "unknown",
            "observations": observation_context["state"],
            "sourceFacts": "unknown",
        }
        if event_items and observation_context["items"]:
            reason = "campaign_signal_events_and_sdk_observations_partial"
        if issues and event_items:
            reason = issues[0]
        coverage = (
            "exact_touchpoint_linked_events_and_sdk_observations_partial"
            if observation_context["items"]
            else "exact_touchpoint_linked_events_only"
        )
        slot_states[SLOT_SIGNAL_SOURCES].update(
            state=state,
            reason=reason,
            sourceAuthorities=["events", "observations", "source_facts"],
            dimensionStates=dimension_states,
            eventCount=len(event_items) if event_items else None,
            coverage=coverage,
            broaderAuthorityState="unknown",
        )
        if state == "partial":
            degraded_reasons.append("campaign_signal_sources_partial")
        elif issues:
            degraded_reasons.extend(issues)
        timestamps = [item["occurredAt"] for item in event_items if item["occurredAt"]]
        return {
            **base,
            "state": state,
            "events": event_items,
            "observations": observation_context["items"],
            "observationRead": {
                key: value for key, value in observation_context.items() if key != "items"
            },
            "dimensionStates": dimension_states,
            "coverage": coverage,
            "freshness": {
                "state": "unknown",
                "latestSourceTimestamp": max(timestamps) if timestamps else None,
                "sourceTimestampsPreserved": True,
                "missingTimestamp": "unknown" if missing_timestamps else None,
                "maximumAgeConfigured": False,
            },
            "reason": reason,
            "limitations": [
                "Only exact touchpoint-linked SDK observations are joined; broader observation and source-fact coverage remain unknown.",
                *list(dict.fromkeys(issues)),
            ],
        }

    async def _read_campaign_signal_observations(
        self,
        *,
        request: ProjectionRequest,
        event_items: list[dict[str, Any]],
        evidence_by_key: dict[tuple[str, str], EvidenceRef],
        claims: list[ClaimEnvelope],
    ) -> dict[str, Any]:
        """Join gateway-admitted SDK Bronze rows to exact canonical event IDs."""

        def unknown(reason: str) -> dict[str, Any]:
            return {"state": "unknown", "reason": reason, "items": []}

        sdk_events = {
            item["eventId"]: item for item in event_items
            if item.get("source") == "sdk"
            and item.get("eventType")
            and item.get("occurredAt")
        }
        if not sdk_events:
            return unknown("no_exact_sdk_event_available_for_observation_join")
        source_read = getattr(self._source, "signal_observations", None)
        if not callable(source_read):
            return unknown("campaign_observation_authority_binding_unavailable")
        try:
            read = await source_read(
                request.tenantId, list(sdk_events), limit=MAX_CAMPAIGN_SIGNAL_EVENTS
            )
        except Exception:  # noqa: BLE001 - independent observation read remains unknown
            return unknown("campaign_observation_authority_unavailable")
        if not isinstance(read, RowsRead) or not read.available:
            return unknown("campaign_observation_authority_unavailable")
        if not isinstance(read.rows, list) or any(not isinstance(row, dict) for row in read.rows):
            return unknown("campaign_observation_result_invalid")
        if any(
            row.get("tenant_id") != request.tenantId
            or row.get("provider_record_id") not in sdk_events
            or row.get("source") != "sdk"
            for row in read.rows
        ):
            return unknown("campaign_observation_scope_mismatch")
        rows_by_id: dict[str, list[dict[str, Any]]] = {}
        for row in read.rows:
            rows_by_id.setdefault(row["provider_record_id"], []).append(row)
        if any(len(rows) > 1 for rows in rows_by_id.values()):
            return unknown("campaign_observation_identifier_ambiguous")

        items: list[dict[str, Any]] = []
        refs_and_claims: list[tuple[EvidenceRef, EvidenceRef, str]] = []
        for event_id, rows in rows_by_id.items():
            row = rows[0]
            payload = row.get("payload")
            envelope = payload.get("observation_envelope") if isinstance(payload, dict) else None
            observation = envelope.get("observation") if isinstance(envelope, dict) else None
            tenancy = envelope.get("tenancy") if isinstance(envelope, dict) else None
            quality = envelope.get("quality") if isinstance(envelope, dict) else None
            source = envelope.get("source") if isinstance(envelope, dict) else None
            event = sdk_events[event_id]
            try:
                event_at = _parse_instant(event["occurredAt"])
                observation_at = _parse_instant(observation.get("occurred_at"))
            except (TypeError, ValueError, AttributeError):
                return unknown("campaign_observation_event_time_mismatch")
            if (
                not isinstance(observation, dict)
                or observation.get("observation_id") != event_id
                or observation.get("observation_type") != event["eventType"]
                or observation_at != event_at
                or not isinstance(tenancy, dict)
                or tenancy.get("tenant_id") != request.tenantId
                or not isinstance(source, dict)
                or source.get("source_type") != "sdk"
                or not isinstance(quality, dict)
                or quality.get("validation_state") != "gateway:accepted"
            ):
                return unknown("campaign_observation_envelope_mismatch")
            observed_at = _string_or_none(observation.get("ingested_at"))
            if observed_at is None:
                return unknown("campaign_observation_ingest_time_missing")
            try:
                _parse_instant(observed_at)
            except ValueError:
                return unknown("campaign_observation_ingest_time_invalid")
            bronze_ref = EvidenceRef(
                id=event_id,
                type="event",
                source="bronze_sdk_events",
                observedAt=observed_at,
                uri=f"store://sdk_events/{quote(request.tenantId, safe='')}:{quote(event_id, safe='')}",
            )
            event_ref = EvidenceRef.model_validate(event["evidenceRefs"][0])
            refs_and_claims.append((bronze_ref, event_ref, event_id))
            items.append({
                "observationId": event_id,
                "eventType": event["eventType"],
                "validationState": "gateway:accepted",
                "ingestedAt": observed_at,
                "evidenceRefs": [
                    bronze_ref.model_dump(by_alias=True, exclude_none=True),
                    event_ref.model_dump(by_alias=True, exclude_none=True),
                ],
            })
        for bronze_ref, event_ref, event_id in refs_and_claims:
            _add_evidence(evidence_by_key, bronze_ref)
            claims.append(ClaimEnvelope(
                id=f"campaign360:{request.subject.id}:signal-observation:{event_id}",
                kind="campaign_linked_sdk_observation",
                subject=request.subject,
                evidenceRefs=[bronze_ref, event_ref],
                claims=[
                    "A gateway-admitted SDK observation has the exact tenant, event ID, type, and occurrence time of a canonical event named by this campaign touchpoint."
                ],
                claimState=EpistemicStatus.OBSERVED,
                domainSlotIds=[SLOT_SIGNAL_SOURCES],
            ))
        return {
            "state": "available" if items else "unknown",
            "reason": (
                "exact_touchpoint_linked_sdk_observations_only"
                if items else "no_exact_sdk_observation_for_linked_events"
            ),
            "items": items,
            "producerCoverageState": "unknown",
        }

    async def _read_campaign_journey_context(
        self,
        *,
        request: ProjectionRequest,
        campaign_id: str,
        temporal: _TemporalScope,
        slot_states: dict[str, dict[str, Any]],
        evidence_by_key: dict[tuple[str, str], EvidenceRef],
        claims: list[ClaimEnvelope],
        degraded_reasons: list[str],
    ) -> dict[str, Any]:
        """Project exact current journey versions that declare this campaign.

        Campaign ids are taken only from the canonical journey version's
        ``campaign_ids`` array. Episode records have no typed campaign join;
        their separate context remains unknown and does not change Journey slot
        state.
        """
        source_read = getattr(self._source, "journeys_for_campaign", None)
        base = {
            "subject": {"kind": request.subject.kind, "id": request.subject.id},
            "campaignId": campaign_id,
            "journeys": [],
            "episodes": [],
            "dimensionStates": {"journeys": "unknown", "episodes": "unknown"},
            "freshness": {"state": "unknown", "sourceTimestampsPreserved": True},
        }
        if not callable(source_read):
            slot_states[SLOT_JOURNEY_EPISODE].update(
                state="unknown",
                reason="journey_authority_binding_unavailable",
                sourceAuthorities=["journeys"],
                dimensionStates=base["dimensionStates"],
            )
            return {**base, "state": "unknown", "reason": "journey_authority_binding_unavailable"}

        try:
            result = await source_read(
                request.tenantId,
                campaign_id,
                start=temporal.start,
                end=temporal.end,
                limit=MAX_ASSOCIATED_CONTEXT_ROWS + 1,
            )
        except Exception:  # noqa: BLE001 - optional context fails independently
            result = RowsRead([], available=False, reason="journey_authority_unavailable")

        if not isinstance(result, RowsRead) or not result.available:
            slot_states[SLOT_JOURNEY_EPISODE].update(
                state="degraded",
                reason="journey_authority_unavailable",
                sourceAuthorities=["journeys"],
                dimensionStates={"journeys": "unavailable", "episodes": "unknown"},
            )
            degraded_reasons.append("journey_authority_unavailable")
            return {
                **base,
                "state": "degraded",
                "dimensionStates": {"journeys": "unavailable", "episodes": "unknown"},
                "reason": "journey_authority_unavailable",
            }

        if any(not isinstance(row, dict) for row in result.rows):
            slot_states[SLOT_JOURNEY_EPISODE].update(
                state="unknown",
                reason="journey_row_shape_invalid",
                sourceAuthorities=["journeys"],
                dimensionStates={"journeys": "unknown", "episodes": "unknown"},
            )
            degraded_reasons.append("journey_row_shape_invalid")
            return {**base, "state": "unknown", "reason": "journey_row_shape_invalid"}

        rows = result.rows
        if any(
            row.get("tenant_id") != request.tenantId
            or row.get("is_current") is not True
            or not isinstance(row.get("campaign_ids"), list)
            or campaign_id not in row.get("campaign_ids", [])
            for row in rows
        ):
            slot_states[SLOT_JOURNEY_EPISODE].update(
                state="unknown",
                reason="journey_row_scope_mismatch",
                sourceAuthorities=["journeys"],
                dimensionStates={"journeys": "unknown", "episodes": "unknown"},
            )
            degraded_reasons.append("journey_row_scope_mismatch")
            return {**base, "state": "unknown", "reason": "journey_row_scope_mismatch"}

        truncated = len(rows) > MAX_ASSOCIATED_CONTEXT_ROWS
        rows = rows[:MAX_ASSOCIATED_CONTEXT_ROWS]
        journey_items: list[dict[str, Any]] = []
        missing_evidence = False
        missing_timestamps = False
        timestamps: list[str] = []
        for row in rows:
            journey_id = _string_or_none(row.get("journey_id"))
            version_id = _string_or_none(row.get("journey_version_id"))
            if not journey_id or not version_id:
                missing_evidence = True
                continue
            observed_at = _string_or_none(row.get("data_watermark") or row.get("computed_at"))
            if observed_at:
                timestamps.append(observed_at)
            else:
                missing_timestamps = True
            evidence = EvidenceRef(
                id=version_id,
                type="entity",
                source=_JOURNEY_SOURCE,
                observedAt=observed_at,
                uri=f"store://journey_versions/{version_id}",
            )
            _add_evidence(evidence_by_key, evidence)
            journey_items.append(
                {
                    "journeyId": journey_id,
                    "journeyVersionId": version_id,
                    "journeyState": _string_or_none(row.get("journey_state")),
                    "startedAt": _string_or_none(row.get("started_at")),
                    "endedAt": _string_or_none(row.get("ended_at")),
                    "computedAt": _string_or_none(row.get("computed_at")),
                    "dataWatermark": _string_or_none(row.get("data_watermark")),
                    "campaignIds": list(row.get("campaign_ids") or []),
                    "evidenceRefs": [evidence.model_dump(by_alias=True, exclude_none=True)],
                }
            )
            claims.append(
                _claim(
                    claim_id=f"campaign360:{campaign_id}:journey:{version_id}",
                    kind="campaign_journey_membership",
                    subject=request.subject,
                    evidence=evidence,
                    text=(
                        "A tenant-scoped current journey version explicitly lists "
                        "this campaign in its campaign_ids reference."
                    ),
                    slot_id=SLOT_JOURNEY_EPISODE,
                )
            )

        if truncated or missing_evidence:
            journey_state = "degraded"
            journey_reason = (
                "campaign_journey_read_truncated"
                if truncated
                else "campaign_journey_evidence_reference_missing"
            )
        elif journey_items:
            journey_state = "available"
            journey_reason = None
        else:
            journey_state = "empty"
            journey_reason = None
        dimension_states = {
            "journeys": journey_state,
            "episodes": "unknown",
        }
        slot_states[SLOT_JOURNEY_EPISODE].update(
            state=journey_state,
            reason=journey_reason,
            sourceAuthorities=["journeys"],
            dimensionStates=dimension_states,
            journeyCount=len(journey_items)
            if journey_state in {"available", "empty"}
            else None,
            episodeCount=None,
        )
        if journey_reason:
            degraded_reasons.append(journey_reason)
        return {
            **base,
            "state": journey_state,
            "journeys": journey_items,
            "dimensionStates": dimension_states,
            "freshness": {
                "state": "available" if timestamps and not missing_timestamps else "unknown",
                "sourceTimestamp": max(timestamps) if timestamps else None,
                "sourceTimestampsPreserved": True,
                "missingTimestamp": "unknown",
            },
            "reason": journey_reason,
        }

    async def _read_episode_context(
        self,
        *,
        request: ProjectionRequest,
        slot_states: dict[str, dict[str, Any]],
        evidence_by_key: dict[tuple[str, str], EvidenceRef],
        claims: list[ClaimEnvelope],
    ) -> dict[str, Any]:
        """Read the requested episode by its exact tenant-owned identifier."""
        source_read = getattr(self._source, "episode_record", None)
        base = {
            "subject": {"kind": request.subject.kind, "id": request.subject.id},
            "journeys": [],
            "episodes": [],
            "dimensionStates": {"journeys": "unknown", "episodes": "unknown"},
            "freshness": {"state": "unknown", "sourceTimestampsPreserved": True},
        }
        if not callable(source_read):
            slot_states[SLOT_JOURNEY_EPISODE].update(
                state="unknown",
                reason="episode_authority_binding_unavailable",
                sourceAuthorities=["episode_facts", "journeys"],
                dimensionStates=base["dimensionStates"],
            )
            return {**base, "state": "unknown", "reason": "episode_authority_binding_unavailable"}
        try:
            read = await source_read(request.tenantId, request.subject.id)
        except Exception:  # noqa: BLE001 - exact episode read is fail-isolated
            read = CampaignRead(None, False, "episode_authority_unavailable")
        if not isinstance(read, CampaignRead) or not read.available:
            slot_states[SLOT_JOURNEY_EPISODE].update(
                state="degraded",
                reason="episode_authority_unavailable",
                sourceAuthorities=["episode_facts", "journeys"],
                dimensionStates={"journeys": "unknown", "episodes": "unavailable"},
            )
            return {
                **base,
                "state": "degraded",
                "dimensionStates": {"journeys": "unknown", "episodes": "unavailable"},
                "reason": "episode_authority_unavailable",
            }
        record = read.record
        if record is None:
            slot_states[SLOT_JOURNEY_EPISODE].update(
                state="missing",
                reason="tenant_scoped_episode_record_not_found",
                sourceAuthorities=["episode_facts", "journeys"],
                dimensionStates={"journeys": "unknown", "episodes": "missing"},
            )
            return {
                **base,
                "state": "missing",
                "dimensionStates": {"journeys": "unknown", "episodes": "missing"},
                "reason": "tenant_scoped_episode_record_not_found",
            }
        if (
            not isinstance(record, dict)
            or record.get("tenant_id") != request.tenantId
            or record.get("episode_id") != request.subject.id
        ):
            slot_states[SLOT_JOURNEY_EPISODE].update(
                state="unknown",
                reason="episode_record_scope_mismatch",
                sourceAuthorities=["episode_facts", "journeys"],
                dimensionStates={"journeys": "unknown", "episodes": "unknown"},
            )
            return {**base, "state": "unknown", "reason": "episode_record_scope_mismatch"}

        episode_id = request.subject.id
        observed_at = _string_or_none(record.get("created_at") or record.get("occurred_to"))
        evidence = EvidenceRef(
            id=episode_id,
            type="entity",
            source=_EPISODE_SOURCE,
            observedAt=observed_at,
            uri=f"store://episodes/{episode_id}",
        )
        _add_evidence(evidence_by_key, evidence)
        episode_payload = {
            "episodeId": episode_id,
            "kind": _string_or_none(record.get("kind")),
            "status": _string_or_none(record.get("status")),
            "occurredFrom": _string_or_none(record.get("occurred_from")),
            "occurredTo": _string_or_none(record.get("occurred_to")),
            "createdAt": _string_or_none(record.get("created_at")),
            "evidenceRefs": [evidence.model_dump(by_alias=True, exclude_none=True)],
        }
        claims.append(
            _claim(
                claim_id=f"campaign360:episode:{episode_id}",
                kind="campaign360_episode_subject_record",
                subject=request.subject,
                evidence=evidence,
                text="A tenant-scoped canonical episode record exists for this episode subject.",
                slot_id=SLOT_JOURNEY_EPISODE,
            )
        )
        slot_states[SLOT_JOURNEY_EPISODE].update(
            state="degraded",
            reason="episode_journey_association_unavailable",
            sourceAuthorities=["episode_facts", "journeys"],
            dimensionStates={"journeys": "unknown", "episodes": "available"},
            journeyCount=None,
            episodeCount=1,
        )
        return {
            **base,
            "state": "degraded",
            "episodes": [episode_payload],
            "dimensionStates": {"journeys": "unknown", "episodes": "available"},
            "freshness": {
                "state": "available" if observed_at else "unknown",
                "sourceTimestamp": observed_at,
                "sourceTimestampsPreserved": True,
                "missingTimestamp": "unknown",
            },
            "reason": "episode_journey_association_unavailable",
        }

    async def _read_population_context(
        self,
        *,
        request: ProjectionRequest,
        slot_states: dict[str, dict[str, Any]],
        evidence_by_key: dict[tuple[str, str], EvidenceRef],
        claims: list[ClaimEnvelope],
    ) -> dict[str, Any]:
        """Read exact tenant-owned population definition metadata.

        This uses Population360's canonical reader and intentionally omits
        member counts: the Campaign360 context does not own population
        membership completeness or measurement semantics.
        """
        base = {"subject": {"kind": request.subject.kind, "id": request.subject.id}}
        try:
            reader = self._population_reader
            if reader is None:
                from identity.population360.provider import PopulationRepositoryReader

                reader = PopulationRepositoryReader()
            view = await reader.view(
                tenant_id=request.tenantId,
                subject_kind="population",
                subject_id=request.subject.id,
            )
        except Exception:  # noqa: BLE001 - population context fails independently
            slot_states[SLOT_POPULATION].update(
                state="degraded",
                reason="population_authority_unavailable",
                sourceAuthorities=["population", "population_definitions"],
            )
            return {
                **base,
                "state": "degraded",
                "reason": "population_authority_unavailable",
            }
        posture = getattr(view, "posture", None)
        if (
            getattr(view, "kind", None) != "population"
            or getattr(view, "id", None) != request.subject.id
            or posture is None
            or getattr(posture, "population_id", None) != request.subject.id
        ):
            reason = getattr(view, "missing_reason", None) or "tenant_scoped_population_not_found"
            slot_states[SLOT_POPULATION].update(
                state="missing",
                reason="tenant_scoped_population_not_found",
                sourceAuthorities=["population", "population_definitions"],
            )
            return {**base, "state": "missing", "reason": reason}

        observed_at = _string_or_none(
            getattr(posture, "updated_at", None) or getattr(posture, "created_at", None)
        )
        evidence = EvidenceRef(
            id=request.subject.id,
            type="entity",
            source="identity_populations",
            observedAt=observed_at,
            uri=f"store://populations/{request.subject.id}",
        )
        _add_evidence(evidence_by_key, evidence)
        claims.append(
            _claim(
                claim_id=f"campaign360:population:{request.subject.id}:definition",
                kind="campaign_population_definition_context",
                subject=request.subject,
                evidence=evidence,
                text="A tenant-owned canonical population definition exists for this population subject.",
                slot_id=SLOT_POPULATION,
            )
        )
        population = {
            "populationId": request.subject.id,
            "name": _string_or_none(getattr(posture, "name", None)),
            "populationType": _string_or_none(getattr(posture, "population_type", None)),
            "status": _string_or_none(getattr(posture, "status", None)),
            "definitionVersion": _string_or_none(getattr(posture, "definition_version", None)),
            "createdAt": _string_or_none(getattr(posture, "created_at", None)),
            "updatedAt": _string_or_none(getattr(posture, "updated_at", None)),
            "evidenceRefs": [evidence.model_dump(by_alias=True, exclude_none=True)],
        }
        slot_states[SLOT_POPULATION].update(
            state="available",
            reason=None,
            sourceAuthorities=["population", "population_definitions"],
            freshnessState="available" if observed_at else "unknown",
            sourceTimestamp=observed_at,
        )
        return {
            **base,
            "state": "available",
            "population": population,
            "freshness": {
                "state": "available" if observed_at else "unknown",
                "sourceTimestamp": observed_at,
                "sourceTimestampsPreserved": True,
                "missingTimestamp": "unknown",
            },
        }

    async def _read_touchpoints(
        self,
        *,
        request: ProjectionRequest,
        subject: ProjectionSubject,
        campaign_id: str,
        temporal: _TemporalScope,
        slot_states: dict[str, dict[str, Any]],
        touchpoint_items: list[dict[str, Any]],
        source_classification_items: list[dict[str, Any]],
        signal_touchpoint_evidence: dict[str, list[EvidenceRef]],
        signal_reference_issues: list[str],
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
            source_event_id = row.get("source_event_id")
            if source_event_id is not None:
                if _safe_campaign_source_id(source_event_id):
                    signal_touchpoint_evidence.setdefault(source_event_id, []).append(
                        evidence
                    )
                else:
                    signal_reference_issues.append(
                        "campaign_touchpoint_event_reference_invalid"
                    )
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
            classification_id = row.get("source_classification_id")
            source_class = row.get("source_class")
            classifier_version = row.get("source_classifier_version")
            source_event_id = row.get("source_event_id")
            if all(
                value is not None and str(value).strip()
                for value in (
                    classification_id,
                    row.get("touchpoint_id"),
                    source_class,
                    classifier_version,
                    source_event_id,
                )
            ):
                classification_ref = EvidenceRef(
                    id=str(classification_id),
                    type="event",
                    source="services/api/journeys/measurement/repositories/touchpoint_repo.py:touchpoint_source_classification_revisions",
                    observedAt=_string_or_none(row.get("source_classified_at")),
                    uri=f"store://touchpoint_source_classification_revisions/{classification_id}",
                )
                _add_evidence(evidence_by_key, classification_ref)
                source_classification_items.append(
                    {
                        "touchpointId": str(row["touchpoint_id"]),
                        "sourceEventId": str(source_event_id),
                        "sourceClass": str(source_class),
                        "classifierVersion": str(classifier_version),
                        "classificationId": str(classification_id),
                        "classifiedAt": _string_or_none(row.get("source_classified_at")),
                        "domainSlotIds": [SLOT_SOURCE_CLASSIFICATION],
                    }
                )
                claims.append(
                    ClaimEnvelope(
                        id=f"campaign360:{campaign_id}:source-classification:{classification_id}",
                        kind="campaign_touchpoint_source_classification",
                        subject=subject,
                        evidenceRefs=[evidence, classification_ref],
                        claims=[
                            "A tenant-scoped campaign touchpoint has a recorded source classification."
                        ],
                        claimState=EpistemicStatus.OBSERVED,
                        domainSlotIds=[SLOT_SOURCE_CLASSIFICATION],
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
                sourceAuthorities=["attribution_credits"],
                dimensionStates={"attributionCredits": "unavailable"},
                qualityState="unknown",
            )
            degraded_reasons.append("attribution_repository_unavailable")
            return
        if any(not isinstance(row, dict) for row in result.credits):
            slot_states[SLOT_ATTRIBUTION_OUTCOMES].update(
                state="unknown",
                reason="attribution_credit_row_shape_invalid",
                sourceAuthorities=["attribution_credits"],
                dimensionStates={"attributionCredits": "unknown"},
                qualityState="unknown",
            )
            degraded_reasons.append("attribution_credit_row_shape_invalid")
            return
        credits = result.credits
        if any(not _row_matches_campaign_scope(row, request.tenantId, campaign_id, attribution=True) for row in credits):
            slot_states[SLOT_ATTRIBUTION_OUTCOMES].update(
                state="unknown",
                reason="attribution_credit_scope_mismatch",
                sourceAuthorities=["attribution_credits"],
                dimensionStates={"attributionCredits": "unknown"},
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
            elif result.data_quality == "complete":
                slot_state = "empty"
                reason = None
            else:
                # An empty credit set can be a known empty measurement only if
                # the authority explicitly attests to a complete run. The
                # current repository's empty summary reports not_provisioned.
                slot_state = "unknown"
                reason = "no_credit_rows_without_complete_run_evidence"
            slot_states[SLOT_ATTRIBUTION_OUTCOMES].update(
                state=slot_state,
                reason=reason,
                sourceAuthorities=["attribution_credits"],
                dimensionStates={
                    "attributionCredits": "missing"
                    if slot_state == "missing"
                    else "empty"
                    if result.data_quality == "complete"
                    else "unknown",
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
                {
                    "credit": payload,
                    "evidenceRefs": [evidence.model_dump(by_alias=True, exclude_none=True)],
                    "domainSlotIds": [SLOT_ATTRIBUTION_OUTCOMES],
                }
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
        slot_state = "available"
        if credits_truncated:
            slot_state = "degraded"
            reason = "attribution_credit_page_truncated"
        elif unreferenced:
            slot_state = "degraded"
            reason = "attribution_credit_evidence_reference_missing"
        elif result.data_quality == "partial":
            slot_state = "degraded"
            reason = "attribution_repository_reports_partial_data_quality"
        elif result.data_quality not in {"complete", "partial"}:
            slot_state = "degraded"
            reason = "attribution_data_quality_unverified"
        else:
            reason = None
        slot_states[SLOT_ATTRIBUTION_OUTCOMES].update(
            state=slot_state,
            reason=reason,
            sourceAuthorities=["attribution_credits"],
            dimensionStates={
                "attributionCredits": "truncated"
                if credits_truncated
                else "partial"
                if unreferenced
                else "available",
            },
            qualityState=result.data_quality or "unknown",
            creditsTruncated=credits_truncated,
        )
        if reason is not None:
            degraded_reasons.append(reason)

    async def _read_campaign_conversions(
        self,
        *,
        request: ProjectionRequest,
        campaign_id: str,
        credit_items: list[dict[str, Any]],
        conversion_items: list[dict[str, Any]],
        slot_states: dict[str, dict[str, Any]],
        evidence_by_key: dict[tuple[str, str], EvidenceRef],
        claims: list[ClaimEnvelope],
        degraded_reasons: list[str],
    ) -> None:
        """Join canonical conversions only through exact active campaign credits.

        The attribution credit is the exact campaign relation. A canonical
        conversion lookup is independently scoped by tenant and conversion ID;
        this keeps measured attribution credits distinct from conversion
        records and prevents broad profile/cluster joins from inventing
        campaign membership.
        """
        lookup = getattr(self._source, "conversion_record", None)
        if not callable(lookup):
            reason = "canonical_conversion_authority_binding_unavailable"
            slot_states[SLOT_CONVERSIONS].update(
                state="unknown",
                reason=reason,
                sourceAuthorities=["canonical_conversions", "attribution_credits"],
            )
            return

        credit_by_conversion: dict[str, list[EvidenceRef]] = {}
        for item in credit_items:
            credit = item.get("credit") if isinstance(item, dict) else None
            conversion_id = credit.get("conversionId") if isinstance(credit, dict) else None
            if not isinstance(conversion_id, str) or not conversion_id.strip():
                continue
            refs: list[EvidenceRef] = []
            for raw in item.get("evidenceRefs", []):
                try:
                    refs.append(EvidenceRef.model_validate(raw))
                except Exception:  # noqa: BLE001 - malformed linkage evidence fails closed
                    continue
            if refs:
                credit_by_conversion.setdefault(conversion_id, []).extend(refs)

        conversion_ids = list(credit_by_conversion)
        if not conversion_ids:
            attribution_state = slot_states[SLOT_ATTRIBUTION].get("state")
            if attribution_state == "empty":
                slot_states[SLOT_CONVERSIONS].update(
                    state="empty",
                    reason=None,
                    sourceAuthorities=["canonical_conversions", "attribution_credits"],
                    joinCoverage="active_attribution_credits_only",
                    unattributedConversions="unknown",
                )
            else:
                reason = "active_campaign_attribution_credit_conversion_ids_unavailable"
                slot_states[SLOT_CONVERSIONS].update(
                    state="unknown",
                    reason=reason,
                    sourceAuthorities=["canonical_conversions", "attribution_credits"],
                    joinCoverage="active_attribution_credits_only",
                )
            return

        truncated = len(conversion_ids) > MAX_ATTRIBUTION_CREDITS
        conversion_ids = conversion_ids[:MAX_ATTRIBUTION_CREDITS]
        missing = 0
        invalid = 0
        for conversion_id in conversion_ids:
            try:
                result = await lookup(request.tenantId, conversion_id)
            except Exception:  # noqa: BLE001 - keep authority errors slot-local
                result = ConversionRecordRead(None, available=False)
            if not isinstance(result, ConversionRecordRead) or not result.available:
                missing += 1
                continue
            record = result.record
            if record is None:
                missing += 1
                continue
            if (
                str(record.get("tenant_id") or "") != request.tenantId
                or str(record.get("conversion_id") or "") != conversion_id
            ):
                invalid += 1
                continue

            occurred_at = _string_or_none(record.get("occurred_at"))
            source_currency = _currency_code(record.get("currency"))
            normalized_currency = _currency_code(record.get("normalized_currency"))
            conversion_monetary_state = _conversion_monetary_state(record)
            conversion_ref = EvidenceRef(
                id=conversion_id,
                type="event",
                source="services/api/journeys/measurement/repositories/conversion_repo.py:canonical_conversions",
                observedAt=_string_or_none(record.get("observed_at") or occurred_at),
                uri=f"store://canonical_conversions/{quote(conversion_id, safe='')}",
            )
            attribution_refs = credit_by_conversion.get(conversion_id, [])
            refs = [conversion_ref, *attribution_refs]
            _add_evidence(evidence_by_key, conversion_ref)
            value_present = record.get("net_value") is not None or record.get("gross_value") is not None
            conversion_items.append(
                {
                    "conversion": {
                        "conversionId": conversion_id,
                        "conversionType": _scalar(record.get("conversion_type")),
                        "conversionName": _scalar(record.get("conversion_name")),
                        "status": _scalar(record.get("conversion_status")),
                        "occurredAt": occurred_at,
                        "currency": source_currency,
                        "normalizedCurrency": normalized_currency,
                        "conversionMonetaryState": conversion_monetary_state,
                        "grossValue": _scalar(record.get("gross_value")),
                        "netValue": _scalar(record.get("net_value")),
                        "adjustedAt": _scalar(record.get("adjusted_at")),
                        "quantity": _scalar(record.get("quantity")),
                        "valueState": "measured" if value_present else "unknown",
                        "campaignAttribution": "exact_active_credit",
                    },
                    "evidenceRefs": [
                        ref.model_dump(by_alias=True, exclude_none=True) for ref in refs
                    ],
                    "domainSlotIds": [SLOT_CONVERSIONS],
                }
            )
            for ref in refs:
                _add_evidence(evidence_by_key, ref)
            claims.append(
                ClaimEnvelope(
                    id=f"campaign360:{campaign_id}:conversion:{conversion_id}",
                    kind="campaign_canonical_conversion",
                    subject=request.subject,
                    evidenceRefs=refs,
                    claims=[
                        "A canonical tenant-scoped conversion record is linked to this exact campaign by an active attribution credit; this is separate from measured attribution outcome."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=[SLOT_CONVERSIONS],
                )
            )

        if invalid:
            state, reason = "unknown", "canonical_conversion_scope_mismatch"
        elif missing or truncated:
            state, reason = "degraded", "canonical_conversion_join_incomplete"
        else:
            state = "available" if conversion_items else "empty"
            reason = None
        slot_states[SLOT_CONVERSIONS].update(
            state=state,
            reason=reason,
            sourceAuthorities=["canonical_conversions", "attribution_credits"],
            joinCoverage="active_attribution_credits_only",
            unattributedConversions="unknown",
            conversionCount=len(conversion_items),
            conversionReadTruncated=truncated,
            missingConversionRecords=missing,
        )
        if reason:
            degraded_reasons.append(reason)

    async def _read_campaign_performance(
        self,
        *,
        request: ProjectionRequest,
        campaign_id: str,
        temporal: _TemporalScope,
        credit_items: list[dict[str, Any]],
        conversion_items: list[dict[str, Any]],
        slot_states: dict[str, dict[str, Any]],
        evidence_by_key: dict[tuple[str, str], EvidenceRef],
        claims: list[ClaimEnvelope],
        degraded_reasons: list[str],
    ) -> dict[str, Any]:
        """Join exact campaign spend observations to active attributed outcomes.

        The spend ledger has no coverage watermark, so recorded spend amounts
        remain observations and do not support a campaign-wide ROAS/ROI claim.
        Attributed revenue is emitted only when all active credits and their
        exact canonical conversions are complete and amount-bearing.
        """
        outcome = _campaign_attributed_outcome(
            slot_states=slot_states,
            credit_items=credit_items,
            conversion_items=conversion_items,
        )
        outcome_refs: list[EvidenceRef] = []
        for item in [*credit_items, *conversion_items]:
            for raw in item.get("evidenceRefs", []) if isinstance(item, dict) else []:
                try:
                    ref = EvidenceRef.model_validate(raw)
                except Exception:  # noqa: BLE001 - incomplete evidence blocks the metric
                    continue
                _add_evidence(evidence_by_key, ref)
                outcome_refs.append(ref)
        outcome_refs = _dedupe_evidence(outcome_refs)
        if outcome.get("grossRevenue", {}).get("state") == "available" or outcome.get(
            "netRevenue", {}
        ).get("state") == "available":
            for currency, amount in sorted(
                outcome.get("grossRevenue", {}).get("byCurrency", {}).items()
            ):
                currency_refs = _refs_from_wire(
                    outcome.get("grossEvidenceRefsByCurrency", {}).get(currency, [])
                )
                if currency_refs and amount is not None:
                    claims.append(
                        ClaimEnvelope(
                            id=f"campaign360:{campaign_id}:performance:gross:{currency}",
                            kind="campaign_attributed_gross_revenue",
                            subject=request.subject,
                            evidenceRefs=currency_refs,
                            claims=[
                                f"Active exact campaign attribution credits report gross revenue of {amount} {currency} in normalized conversion currency."
                            ],
                            claimState=EpistemicStatus.OBSERVED,
                            domainSlotIds=[SLOT_PERFORMANCE],
                        )
                    )
            for currency, amount in sorted(
                outcome.get("netRevenue", {}).get("byCurrency", {}).items()
            ):
                currency_refs = _refs_from_wire(
                    outcome.get("netEvidenceRefsByCurrency", {}).get(currency, [])
                )
                if currency_refs and amount is not None:
                    claims.append(
                        ClaimEnvelope(
                            id=f"campaign360:{campaign_id}:performance:net:{currency}",
                            kind="campaign_attributed_net_revenue",
                            subject=request.subject,
                            evidenceRefs=currency_refs,
                            claims=[
                                f"Active exact campaign attribution credits report net revenue of {amount} {currency} in normalized conversion currency."
                            ],
                            claimState=EpistemicStatus.OBSERVED,
                            domainSlotIds=[SLOT_PERFORMANCE],
                        )
                    )

        spend_reader = getattr(self._source, "campaign_spend", None)
        spend_context: dict[str, Any] = {
            "state": "unknown",
            "records": [],
            "recordCount": 0,
            "amountState": "unknown",
            "coverage": "unknown",
            "reason": "campaign_spend_authority_not_connected",
        }
        if not callable(spend_reader):
            spend_read = CampaignSpendRead(
                rows=[], available=False, reason="campaign_spend_authority_not_connected"
            )
        else:
            try:
                spend_read = await spend_reader(
                    request.tenantId,
                    campaign_id,
                    start=temporal.start,
                    end=temporal.end,
                    limit=MAX_CAMPAIGN_PERFORMANCE_SPEND_ROWS + 1,
                )
            except Exception:  # noqa: BLE001 - spend source is slot-local
                spend_read = CampaignSpendRead(
                    rows=[], available=False, reason="campaign_spend_repository_unavailable"
                )

        spend_records: list[dict[str, Any]] = []
        spend_refs: list[EvidenceRef] = []
        invalid_spend_rows = 0
        spend_amounts_complete = True
        truncated = False
        if not isinstance(spend_read, CampaignSpendRead) or not spend_read.available:
            reason = (
                spend_read.reason
                if isinstance(spend_read, CampaignSpendRead) and spend_read.reason
                else "campaign_spend_repository_unavailable"
            )
            spend_context.update(state="unknown", reason=reason)
        elif any(not isinstance(row, dict) for row in spend_read.rows):
            invalid_spend_rows = 1
            spend_amounts_complete = False
            spend_context.update(state="unknown", reason="campaign_spend_row_shape_invalid")
        else:
            rows = list(spend_read.rows)
            truncated = len(rows) > MAX_CAMPAIGN_PERFORMANCE_SPEND_ROWS
            for row in rows[:MAX_CAMPAIGN_PERFORMANCE_SPEND_ROWS]:
                if (
                    str(row.get("tenant_id") or "") != request.tenantId
                    or str(row.get("campaign_id") or "") != campaign_id
                ):
                    invalid_spend_rows += 1
                    continue
                spend_record_id = str(row.get("spend_record_id") or "")
                period_start = _parse_temporal_value(row.get("period_start"))
                period_end = _parse_temporal_value(row.get("period_end"))
                if (
                    not _safe_campaign_source_id(spend_record_id)
                    or period_start is None
                    or period_end is None
                    or period_end < period_start
                ):
                    invalid_spend_rows += 1
                    continue
                if temporal.start is not None and period_end <= temporal.start:
                    continue
                if temporal.end is not None and period_start >= temporal.end:
                    continue
                full_window_row = (
                    (temporal.start is None or period_start >= temporal.start)
                    and (temporal.end is None or period_end <= temporal.end)
                )
                normalized = _normalized_spend_amount(row)
                amount = normalized[0] if normalized is not None else None
                currency = normalized[1] if normalized is not None else None
                if amount is None or currency is None or not full_window_row:
                    spend_amounts_complete = False
                spend_recorded_at = _parse_temporal_value(row.get("created_at"))
                spend_ref = EvidenceRef(
                    id=spend_record_id,
                    type="event",
                    source="services/api/journeys/measurement/repositories/spend_repo.py:spend_records",
                    observedAt=(
                        spend_recorded_at.isoformat()
                        if spend_recorded_at is not None
                        else None
                    ),
                    uri=f"store://spend_records/{quote(spend_record_id, safe='')}",
                )
                spend_refs.append(spend_ref)
                _add_evidence(evidence_by_key, spend_ref)
                spend_records.append(
                    {
                        "spendRecordId": spend_record_id,
                        "periodStart": period_start.isoformat(),
                        "periodEnd": period_end.isoformat(),
                        "recordedAt": (
                            spend_recorded_at.isoformat()
                            if spend_recorded_at is not None
                            else None
                        ),
                        "amount": None if amount is None else format(amount, "f"),
                        "currency": currency,
                        "sourceAmount": _scalar(row.get("total_cost")),
                        "sourceCurrency": _currency_code(row.get("billing_currency")),
                        "normalizedAmount": None if amount is None else format(amount, "f"),
                        "normalizedCurrency": currency,
                        "amountState": "observed" if amount is not None else "unknown",
                        "withinRequestedWindow": full_window_row,
                        "evidenceRefs": [
                            spend_ref.model_dump(by_alias=True, exclude_none=True)
                        ],
                        "domainSlotIds": [SLOT_PERFORMANCE],
                    }
                )
                if amount is not None:
                    claims.append(
                        ClaimEnvelope(
                            id=f"campaign360:{campaign_id}:spend:{spend_record_id}",
                            kind="campaign_spend_record",
                            subject=request.subject,
                            evidenceRefs=[spend_ref],
                            claims=[
                                f"A canonical tenant and campaign scoped spend record reports {format(amount, 'f')} {currency} for its recorded period."
                            ],
                            claimState=EpistemicStatus.OBSERVED,
                            domainSlotIds=[SLOT_PERFORMANCE],
                        )
                    )

            source_complete = (
                spend_read.complete
                and not truncated
                and invalid_spend_rows == 0
                and spend_amounts_complete
            )
            spend_context = {
                "state": (
                    "available"
                    if source_complete
                    else "partial"
                    if spend_records
                    else "empty"
                    if spend_read.complete and not truncated and invalid_spend_rows == 0
                    else "unknown"
                ),
                "records": spend_records,
                "recordCount": len(spend_records),
                "amountState": "complete" if source_complete else "observed_or_unknown",
                "coverage": "source_attested" if source_complete else "bounded_rows_without_coverage_attestation",
                "complete": source_complete,
                "truncated": truncated,
                "invalidRowCount": invalid_spend_rows,
                "reason": None
                if source_complete
                else spend_read.reason
                or "campaign_spend_coverage_or_amount_incomplete",
                "evidenceRefs": [
                    ref.model_dump(by_alias=True, exclude_none=True)
                    for ref in _dedupe_evidence(spend_refs)
                ],
            }

        outcome_measured = outcome.get("state") == "available"
        spend_measured = bool(spend_records)
        if outcome_measured and spend_context.get("complete") is True:
            performance_state, performance_reason = "available", None
        elif outcome_measured or spend_measured:
            performance_state, performance_reason = "partial", (
                "campaign_spend_coverage_or_amount_incomplete"
                if spend_context.get("complete") is not True
                else "campaign_attribution_or_conversion_join_incomplete"
            )
        else:
            performance_state, performance_reason = "unknown", (
                outcome.get("reason")
                or spend_context.get("reason")
                or "campaign_performance_evidence_unavailable"
            )
        slot_states[SLOT_PERFORMANCE].update(
            state=performance_state,
            reason=performance_reason,
            sourceAuthorities=[
                "canonical_conversions",
                "attribution_credits",
                "spend_records",
            ],
            dimensionStates={
                "attributedOutcome": outcome.get("state", "unknown"),
                "campaignSpend": spend_context.get("state", "unknown"),
                "roas": "unknown",
                "roi": "unknown",
            },
            conversionCount=outcome.get("conversionCount", 0),
            spendRecordCount=spend_context.get("recordCount", 0),
        )
        if performance_state == "partial" and performance_reason:
            degraded_reasons.append(performance_reason)
        return {
            "state": performance_state,
            "subject": {"kind": request.subject.kind, "id": request.subject.id},
            "attributedOutcome": outcome,
            "spendObservations": spend_context,
            "roas": {
                "state": "unknown",
                "reason": "complete_campaign_spend_and_attributed_revenue_are_not_both_attested",
            },
            "roi": {
                "state": "unknown",
                "reason": "campaign_cost_and_return_definition_are_not_both_attested",
            },
            "reason": performance_reason,
            "freshness": {
                "state": (
                    "available"
                    if outcome_measured and spend_context.get("complete") is True
                    else "partial"
                    if outcome_measured or spend_measured
                    else "unknown"
                ),
                "sourceTimestampsPreserved": True,
                "dimensionStates": {
                    "attributedOutcome": "available"
                    if outcome_measured
                    else "unknown",
                    "campaignSpend": "unknown"
                    if spend_context.get("complete") is not True
                    else "available",
                },
            },
            "evidenceRefs": [
                ref.model_dump(by_alias=True, exclude_none=True)
                for ref in _dedupe_evidence([*outcome_refs, *spend_refs])
            ],
            "limitations": [
                "attributed revenue uses active attribution credits joined to exact tenant conversion records",
                "campaign spend rows are bounded observations without a ledger coverage watermark",
                "unattributed conversions are outside this campaign outcome join",
                "ROAS and ROI remain unknown because both sides and period coverage are not jointly attested",
            ],
        }

    async def _read_campaign_population_links(
        self,
        *,
        request: ProjectionRequest,
        campaign_id: str,
        slot_states: dict[str, dict[str, Any]],
        evidence_by_key: dict[tuple[str, str], EvidenceRef],
        claims: list[ClaimEnvelope],
        degraded_reasons: list[str],
    ) -> dict[str, Any]:
        """Project exact operator-managed campaign/population link state.

        This closes only the explicit audience association dimension. It does
        not expand population members or imply that a cohort, cluster, or
        syndicate membership exists for any entity.
        """
        base = {
            "state": "unknown",
            "subject": {"kind": request.subject.kind, "id": request.subject.id},
            "campaignId": campaign_id,
            "associations": [],
            "dimensionStates": {
                "explicitPopulationLinks": "unknown",
                "broaderCohortMembership": "unknown",
                "syndicateMembership": "unknown",
            },
            "readAuthority": "campaign_population_link_events+campaign_facts+population_definitions",
            "freshness": {"state": "unknown", "sourceTimestampsPreserved": True},
        }
        reader = getattr(self._source, "campaign_population_links", None)
        if not callable(reader):
            reason = "campaign_population_link_authority_binding_unavailable"
            slot_states[SLOT_COHORTS_SYNDICATES].update(
                state="unknown",
                reason=reason,
                sourceAuthorities=["campaign_population_link_events", "population_definitions"],
                dimensionStates=base["dimensionStates"],
            )
            return {**base, "reason": reason}

        try:
            read = await reader(
                request.tenantId,
                campaign_id,
                limit=MAX_CAMPAIGN_POPULATION_LINKS + 1,
            )
        except Exception:  # noqa: BLE001 - provider details stay private
            read = None
        if (
            not isinstance(read, CampaignPopulationLinkRead)
            or not read.available
            or read.tenant_id != request.tenantId
            or read.campaign_id != campaign_id
        ):
            reason = (
                read.reason
                if isinstance(read, CampaignPopulationLinkRead) and read.reason
                else "campaign_population_link_authority_unavailable"
            )
            slot_states[SLOT_COHORTS_SYNDICATES].update(
                state="degraded",
                reason=reason,
                sourceAuthorities=["campaign_population_link_events", "population_definitions"],
                dimensionStates={
                    **base["dimensionStates"],
                    "explicitPopulationLinks": "unavailable",
                },
            )
            degraded_reasons.append(reason)
            return {
                **base,
                "state": "degraded",
                "dimensionStates": {
                    **base["dimensionStates"],
                    "explicitPopulationLinks": "unavailable",
                },
                "reason": reason,
            }

        if len(read.rows) > MAX_CAMPAIGN_POPULATION_LINKS:
            reason = "campaign_population_link_read_limit_exceeded"
            slot_states[SLOT_COHORTS_SYNDICATES].update(
                state="degraded",
                reason=reason,
                sourceAuthorities=["campaign_population_link_events", "population_definitions"],
                dimensionStates={
                    **base["dimensionStates"],
                    "explicitPopulationLinks": "truncated",
                },
            )
            degraded_reasons.append(reason)
            return {
                **base,
                "state": "degraded",
                "dimensionStates": {
                    **base["dimensionStates"],
                    "explicitPopulationLinks": "truncated",
                },
                "reason": reason,
            }

        associations: list[dict[str, Any]] = []
        local_reasons: set[str] = set()
        for row in read.rows:
            if (
                not isinstance(row, dict)
                or row.get("tenant_id") != request.tenantId
                or row.get("campaign_id") != campaign_id
                or not _safe_campaign_source_id(row.get("population_id"))
                or row.get("event_type") not in {"linked", "unlinked"}
                or not isinstance(row.get("evidence_refs"), list)
            ):
                local_reasons.add("campaign_population_link_record_scope_invalid")
                continue

            population_id = row["population_id"]
            evidence_refs: list[EvidenceRef] = []
            try:
                evidence_refs = [EvidenceRef.model_validate(item) for item in row["evidence_refs"]]
            except Exception:  # noqa: BLE001 - malformed canonical links fail closed
                local_reasons.add("campaign_population_link_evidence_invalid")
                continue
            if not all(ref.id and ref.source for ref in evidence_refs):
                local_reasons.add("campaign_population_link_evidence_invalid")
                continue
            if not any(ref.id == campaign_id and ref.source.endswith(":campaigns") for ref in evidence_refs):
                local_reasons.add("campaign_population_link_campaign_evidence_missing")
                continue
            if not any(ref.id == population_id and ref.source == "identity_populations" for ref in evidence_refs):
                local_reasons.add("campaign_population_link_population_evidence_missing")
                continue

            if row["event_type"] == "unlinked":
                continue
            effective_at = _string_or_none(row.get("effective_at"))
            observed_at = _string_or_none(row.get("source_observed_at"))
            if not _safe_campaign_source_id(row.get("link_event_id")) or not effective_at or not observed_at:
                local_reasons.add("campaign_population_link_timestamp_or_event_invalid")
                continue
            association = {
                "populationId": population_id,
                "associationState": "explicitly_linked",
                "linkEventId": row["link_event_id"],
                "sourceId": _string_or_none(row.get("source_id")),
                "sourceRecordId": _string_or_none(row.get("source_record_id")),
                "sourceRevisionId": _string_or_none(row.get("source_revision_id")),
                "sourceEventId": _string_or_none(row.get("source_event_id")),
                "actorId": _string_or_none(row.get("actor_id")),
                "actorType": _string_or_none(row.get("actor_type")),
                "sourceObservedAt": observed_at,
                "effectiveAt": effective_at,
                "evidenceRefs": [
                    ref.model_dump(by_alias=True, exclude_none=True) for ref in evidence_refs
                ],
                "domainSlotIds": [SLOT_COHORTS_SYNDICATES],
            }
            associations.append(association)
            for ref in evidence_refs:
                _add_evidence(evidence_by_key, ref)
            claims.append(
                ClaimEnvelope(
                    id=f"campaign360:{campaign_id}:population-link:{row['link_event_id']}",
                    kind="campaign_population_link_observation",
                    subject=request.subject,
                    evidenceRefs=evidence_refs,
                    claims=[
                        "An authenticated tenant operator explicitly linked this campaign to the exact canonical population; population membership is not inferred by Campaign360."
                    ],
                    claimState=EpistemicStatus.OBSERVED,
                    domainSlotIds=[SLOT_COHORTS_SYNDICATES],
                )
            )

        explicit_state = "available" if associations else "empty"
        slot_state = "degraded" if read.truncated or local_reasons else "partial"
        reason = (
            "campaign_population_link_read_truncated"
            if read.truncated
            else sorted(local_reasons)[0]
            if local_reasons
            else "broader_campaign_cohort_and_syndicate_dimensions_unresolved"
        )
        dimensions = {
            "explicitPopulationLinks": "truncated"
            if read.truncated
            else explicit_state,
            "broaderCohortMembership": "unknown",
            "syndicateMembership": "unknown",
        }
        slot_states[SLOT_COHORTS_SYNDICATES].update(
            state=slot_state,
            reason=reason,
            sourceAuthorities=["campaign_population_link_events", "campaign_facts", "population_definitions"],
            dimensionStates=dimensions,
            explicitPopulationLinkCount=len(associations),
            linkReadTruncated=read.truncated,
        )
        if slot_state == "degraded":
            degraded_reasons.append(reason)
        return {
            **base,
            "state": slot_state,
            "associations": associations,
            "dimensionStates": dimensions,
            "coverage": "explicit_operator_links_only",
            "reason": reason,
            "freshness": {
                "state": "available" if associations else "unknown",
                "sourceTimestampsPreserved": True,
                "latestEffectiveAt": max(
                    (item["effectiveAt"] for item in associations), default=None
                ),
            },
            "limitations": [
                "population membership is not expanded here",
                "broader cohort, cluster, and syndicate authorities remain unknown",
                "historical campaign-to-population link replay is unsupported",
            ],
        }


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
        elif evidence.source == _JOURNEY_SOURCE or evidence.source == _EPISODE_SOURCE:
            slots.append(SLOT_JOURNEY_EPISODE)
        elif evidence.source == "identity_populations":
            slots.append(SLOT_POPULATION)
        elif evidence.source == _TARGETING_ANOMALY_SOURCE or evidence.source in _TARGETING_ANOMALY_EVIDENCE_SOURCES:
            slots.append(SLOT_ANOMALIES)
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
    "CampaignAnomalyRead",
    "Campaign360Provider",
    "Campaign360Source",
    "CampaignRead",
    "CampaignSpendRead",
    "OUTPUT_SECTIONS",
    "PROJECTION_ID",
    "RepositoryCampaign360Source",
    "RowsRead",
    "register_provider",
]
