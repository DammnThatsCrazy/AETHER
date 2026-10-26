"""Focused Campaign360 provider contract and authority tests."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "services" / "api"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "campaign360-test-secret")

from journeys.campaign.campaign360_provider import (  # noqa: E402
    AttributionRead,
    CampaignAnomalyRead,
    Campaign360Provider,
    CampaignRead,
    CampaignSpendRead,
    ConversionRecordRead,
    MAX_CAMPAIGN_ANOMALIES,
    OUTPUT_SECTIONS,
    RepositoryCampaign360Source,
    RowsRead,
    register_provider,
)
from journeys.campaign.campaign_population_links import (  # noqa: E402
    CampaignPopulationLinkRead,
)
from shared.intelligence_projections.contracts import (  # noqa: E402
    ProjectionContext,
    ProjectionDependencyState,
    ProjectionRequest,
    ProjectionSubject,
)
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTION_DEFINITIONS,
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.registry import ProviderRegistry  # noqa: E402


CAMPAIGN_ID = "46d19f14-9a0f-4b15-9bd0-df52d468791a"


class FakeCampaign360Source:
    def __init__(
        self,
        *,
        campaign: CampaignRead | None = None,
        touchpoints: RowsRead | None = None,
        attribution: AttributionRead | None = None,
        anomalies: CampaignAnomalyRead | None = None,
        signals: RowsRead | None = None,
    ) -> None:
        self.campaign_result = campaign or CampaignRead(
            record={
                "campaign_id": CAMPAIGN_ID,
                "tenant_id": "tenant-a",
                "name": "Spring launch",
                "status": "active",
                "channel": "email",
                "origin": "custom",
                "primary_platform": None,
                "sync_status": "not_synced",
                "properties": {"private": "must not appear"},
                "created_at": "2026-10-01T00:00:00Z",
                "updated_at": "2026-10-10T00:00:00Z",
            },
            available=True,
        )
        self.touchpoint_result = touchpoints or RowsRead(
            rows=[
                {
                    "touchpoint_id": "tp-1",
                    "tenant_id": "tenant-a",
                    "campaign_id": CAMPAIGN_ID,
                    "occurred_at": "2026-10-05T10:00:00Z",
                    "channel": "email",
                    "source_class": "owned",
                    "touchpoint_type": "email_open",
                    "interaction_type": "open",
                    "is_click_through": False,
                    "is_view_through": None,
                    "communication_fact_id": "comm-1",
                    "profile_id": "private-profile-id",
                }
            ],
            available=True,
        )
        self.attribution_result = attribution or AttributionRead(
            credits=[
                {
                    "credit_id": "credit-1",
                    "tenant_id": "tenant-a",
                    "campaign_id": CAMPAIGN_ID,
                    "attribution_run_id": "run-1",
                    "conversion_id": "conversion-1",
                    "touchpoint_id": "tp-1",
                    "model_type": "last_touch",
                    "model_version": "v1",
                    "credit_weight": "1.000000",
                    "attributed_conversion_count": "1.000000",
                    "attributed_gross_revenue": None,
                    "attributed_net_revenue": None,
                    "created_at": "2026-10-06T10:00:00Z",
                    "run_completed_at": "2026-10-06T10:05:00Z",
                }
            ],
            available=True,
            data_quality="complete",
        )
        self.anomaly_result = anomalies or CampaignAnomalyRead(
            rows=[], available=True, complete=True
        )
        self.signal_result = signals or RowsRead(rows=[], available=True)
        self.campaign_calls: list[tuple[str, object]] = []
        self.touchpoint_calls: list[dict[str, object]] = []
        self.attribution_calls: list[dict[str, object]] = []
        self.anomaly_calls: list[dict[str, object]] = []
        self.signal_calls: list[dict[str, object]] = []


    async def campaign(self, tenant_id: str, campaign_id: object) -> CampaignRead:
        self.campaign_calls.append((tenant_id, campaign_id))
        return self.campaign_result

    async def touchpoints(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        cursor: str | None,
    ) -> RowsRead:
        self.touchpoint_calls.append(
            {
                "tenant_id": tenant_id,
                "campaign_id": campaign_id,
                "start": start,
                "end": end,
                "limit": limit,
                "cursor": cursor,
            }
        )
        return self.touchpoint_result

    async def attribution(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        start: datetime | None,
        end: datetime | None,
    ) -> AttributionRead:
        self.attribution_calls.append(
            {
                "tenant_id": tenant_id,
                "campaign_id": campaign_id,
                "start": start,
                "end": end,
            }
        )
        return self.attribution_result

    async def campaign_anomalies(
        self, tenant_id: str, campaign_id: str, *, limit: int
    ) -> CampaignAnomalyRead:
        self.anomaly_calls.append(
            {"tenant_id": tenant_id, "campaign_id": campaign_id, "limit": limit}
        )
        return self.anomaly_result

    async def signal_events(
        self, tenant_id: str, event_ids: list[str], *, limit: int
    ) -> RowsRead:
        self.signal_calls.append(
            {"tenant_id": tenant_id, "event_ids": list(event_ids), "limit": limit}
        )
        return self.signal_result


class ConversionCampaign360Source(FakeCampaign360Source):
    def __init__(self, conversion: ConversionRecordRead) -> None:
        super().__init__()
        self.conversion_result = conversion
        self.conversion_calls: list[tuple[str, str]] = []

    async def conversion_record(self, tenant_id: str, conversion_id: str) -> ConversionRecordRead:
        self.conversion_calls.append((tenant_id, conversion_id))
        return self.conversion_result


class PerformanceCampaign360Source(ConversionCampaign360Source):
    def __init__(
        self,
        *,
        conversion: ConversionRecordRead,
        credits: list[dict[str, object]],
        spend: CampaignSpendRead,
        data_quality: str = "complete",
    ) -> None:
        super().__init__(conversion)
        self.attribution_result = AttributionRead(
            credits=credits,
            available=True,
            data_quality=data_quality,
        )
        self.spend_result = spend
        self.spend_calls: list[dict[str, object]] = []

    async def campaign_spend(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        start: datetime | None,
        end: datetime | None,
        limit: int,
    ) -> CampaignSpendRead:
        self.spend_calls.append(
            {
                "tenant_id": tenant_id,
                "campaign_id": campaign_id,
                "start": start,
                "end": end,
                "limit": limit,
            }
        )
        return self.spend_result


class PopulationLinkCampaign360Source(FakeCampaign360Source):
    def __init__(self, read: CampaignPopulationLinkRead) -> None:
        super().__init__()
        self.population_link_read = read
        self.population_link_calls: list[tuple[str, str, int]] = []

    async def campaign_population_links(self, tenant_id: str, campaign_id: str, *, limit: int):
        self.population_link_calls.append((tenant_id, campaign_id, limit))
        return self.population_link_read


class ContextCampaign360Source(FakeCampaign360Source):
    def __init__(
        self,
        *,
        journeys: RowsRead | None = None,
        episode: CampaignRead | None = None,
    ) -> None:
        super().__init__()
        self.journey_result = journeys or RowsRead(
            rows=[
                {
                    "tenant_id": "tenant-a",
                    "journey_id": "journey-1",
                    "journey_version_id": "journey-version-1",
                    "is_current": True,
                    "journey_state": "open",
                    "campaign_ids": [CAMPAIGN_ID],
                    "started_at": "2026-10-05T00:00:00Z",
                    "computed_at": "2026-10-10T00:00:00Z",
                    "data_watermark": "2026-10-09T23:59:00Z",
                }
            ],
            available=True,
        )
        self.episode_result = episode or CampaignRead(
            record={
                "tenant_id": "tenant-a",
                "episode_id": "episode-1",
                "kind": "support_case",
                "status": "closed",
                "occurred_from": "2026-10-09T10:00:00Z",
                "occurred_to": "2026-10-09T11:00:00Z",
                "created_at": "2026-10-09T11:01:00Z",
                "evidence_refs": [],
            },
            available=True,
        )
        self.journey_calls: list[dict[str, object]] = []
        self.episode_calls: list[tuple[str, str]] = []

    async def journeys_for_campaign(
        self,
        tenant_id: str,
        campaign_id: str,
        *,
        start: datetime | None,
        end: datetime | None,
        limit: int,
    ) -> RowsRead:
        self.journey_calls.append(
            {
                "tenant_id": tenant_id,
                "campaign_id": campaign_id,
                "start": start,
                "end": end,
                "limit": limit,
            }
        )
        return self.journey_result

    async def episode_record(self, tenant_id: str, episode_id: str) -> CampaignRead:
        self.episode_calls.append((tenant_id, episode_id))
        return self.episode_result


def _request(
    *,
    tenant_id: str = "tenant-a",
    subject_kind: str = "campaign",
    subject_id: str = CAMPAIGN_ID,
    temporal_mode: str | None = "window",
    as_of: str | None = None,
    time_range: dict[str, str] | None = None,
    include_claims: bool | None = None,
) -> ProjectionRequest:
    return ProjectionRequest(
        projectionId="campaign360",
        tenantId=tenant_id,
        subject=ProjectionSubject(kind=subject_kind, id=subject_id),
        temporalMode=temporal_mode,
        asOf=as_of,
        timeRange=time_range,
        includeClaims=include_claims,
    )


def _context(tenant_id: str = "tenant-a") -> ProjectionContext:
    return ProjectionContext(
        projectionId="campaign360",
        tenantId=tenant_id,
        registryState="in_flight",
        dependencyState=[
            ProjectionDependencyState(
                projectionId="episode360",
                state="unknown",
                reason="provider_not_registered",
            ),
            ProjectionDependencyState(
                projectionId="outcome360",
                state="available",
            ),
        ],
        warnings=[],
    )


def _section(result: object, section_id: str) -> object:
    return next(section for section in result.sections if section.id == section_id)


def _slot(result: object, slot_id: str) -> dict[str, object]:
    section = _section(result, "state")
    return next(slot for slot in section.content["slots"] if slot["id"] == slot_id)


@pytest.mark.asyncio
async def test_provider_emits_exact_sections_and_evidence_bound_slot_claims() -> None:
    source = FakeCampaign360Source()
    result = await Campaign360Provider(source).project(
        _request(time_range={"from": "2026-10-01T00:00:00Z", "to": "2026-10-11T00:00:00Z"}),
        _context(),
    )

    assert [section.id for section in result.sections] == list(OUTPUT_SECTIONS)
    assert set(section.id for section in result.sections) == set(
        INTELLIGENCE_PROJECTION_DEFINITIONS["campaign360"]["outputSections"]
    )
    assert result.contractVersion == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    assert result.tenantId == "tenant-a"
    assert source.campaign_calls[0][0] == "tenant-a"
    assert source.touchpoint_calls[0]["tenant_id"] == "tenant-a"
    assert source.attribution_calls[0]["tenant_id"] == "tenant-a"
    assert source.touchpoint_calls[0]["start"] == datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert source.touchpoint_calls[0]["end"] == datetime(2026, 10, 11, tzinfo=timezone.utc)

    expected_slots = {
        "campaign_identity",
        "source_classification",
        "signal_sources",
        "touchpoints",
        "journeys",
        "conversions",
        "attribution",
        "cohorts_syndicates",
        "performance",
        "anomalies",
        "evidence_trace",
    }
    assert {slot["id"] for slot in _section(result, "state").content["slots"]} == expected_slots
    assert _slot(result, "campaign_identity")["state"] == "available"
    assert _slot(result, "source_classification")["state"] == "unknown"
    assert _slot(result, "signal_sources")["state"] == "unknown"
    assert _slot(result, "touchpoints")["state"] == "degraded"
    assert _slot(result, "touchpoints")["dimensionStates"] == {
        "touchpoints": "available",
        "communicationFacts": "unknown",
    }
    assert _slot(result, "attribution")["state"] == "available"
    assert _slot(result, "attribution")["dimensionStates"] == {
        "attributionCredits": "available",
    }
    assert _slot(result, "journeys")["state"] == "unknown"
    assert _slot(result, "conversions")["state"] == "unknown"
    assert _slot(result, "cohorts_syndicates")["state"] == "unknown"
    assert _slot(result, "performance")["state"] == "unknown"
    assert _slot(result, "anomalies")["state"] == "partial"
    assert _slot(result, "anomalies")["dimensionStates"] == {
        "targetingLeakageFindings": "empty",
        "riskOutputs": "unknown",
        "sourceAnomalies": "unknown",
    }
    assert _slot(result, "evidence_trace")["state"] == "available"

    assert all(claim.evidenceRefs for claim in result.claims)
    assert all(claim.domainSlotIds for claim in result.claims)
    assert {slot for claim in result.claims for slot in claim.domainSlotIds or []} >= {
        "campaign_identity",
        "touchpoints",
        "attribution",
        "evidence_trace",
    }
    summary = _section(result, "summary").content
    assert "properties" not in summary["campaign"]
    touchpoint_payload = _section(result, "evidence").content["touchpoints"][0]["touchpoint"]
    assert "profileId" not in touchpoint_payload
    assert touchpoint_payload["isClickThrough"] is False
    assert _section(result, "outcomes").content["attribution"]["credits"][0]["credit"][
        "attributedNetRevenue"
    ] is None


@pytest.mark.asyncio
async def test_campaign_conversion_joins_exact_canonical_record_through_active_credit() -> None:
    source = ConversionCampaign360Source(
        ConversionRecordRead(
            {
                "tenant_id": "tenant-a",
                "conversion_id": "conversion-1",
                "conversion_type": "purchase",
                "conversion_name": "Order complete",
                "conversion_status": "confirmed",
                "occurred_at": "2026-10-05T10:05:00Z",
                "observed_at": "2026-10-05T10:05:01Z",
                "currency": "USD",
                "gross_value": "39.00",
                "net_value": "35.00",
                "quantity": 1,
            },
            available=True,
        )
    )
    result = await Campaign360Provider(source).project(_request(), _context())

    assert source.conversion_calls == [("tenant-a", "conversion-1")]
    slot = _slot(result, "conversions")
    assert slot["state"] == "available"
    assert slot["joinCoverage"] == "active_attribution_credits_only"
    outcomes = _section(result, "outcomes").content
    assert outcomes["conversions"]["state"] == "available"
    conversion = outcomes["conversions"]["items"][0]["conversion"]
    assert conversion["conversionId"] == "conversion-1"
    assert conversion["campaignAttribution"] == "exact_active_credit"
    assert conversion["grossValue"] == "39.00"
    # The canonical conversion record is distinct from the attribution credit's
    # measured contribution fields.
    assert "attributedGrossRevenue" not in conversion
    refs = outcomes["conversions"]["items"][0]["evidenceRefs"]
    assert {ref["source"] for ref in refs} >= {
        "services/api/journeys/measurement/repositories/conversion_repo.py:canonical_conversions",
        "services/api/journeys/measurement/repositories/attribution_run_repo.py:attribution_credits",
    }


@pytest.mark.asyncio
async def test_campaign_conversion_rejects_cross_tenant_record() -> None:
    source = ConversionCampaign360Source(
        ConversionRecordRead(
            {"tenant_id": "tenant-other", "conversion_id": "conversion-1"},
            available=True,
        )
    )
    result = await Campaign360Provider(source).project(_request(), _context())
    assert _slot(result, "conversions")["state"] == "unknown"
    assert _slot(result, "conversions")["reason"] == "canonical_conversion_scope_mismatch"
    assert _section(result, "outcomes").content["conversions"]["items"] == []


@pytest.mark.asyncio
async def test_campaign_performance_joins_active_attributed_outcome_to_observed_spend_without_synthetic_roas() -> None:
    conversion = ConversionRecordRead(
        {
            "tenant_id": "tenant-a",
            "conversion_id": "conversion-1",
            "conversion_type": "purchase",
            "conversion_status": "confirmed",
            "occurred_at": "2026-10-05T10:05:00Z",
            "observed_at": "2026-10-05T10:05:01Z",
            "currency": "USD",
            "normalized_currency": "USD",
            "gross_value": "39.00",
            "net_value": "35.00",
            "quantity": 1,
        },
        available=True,
    )
    credit = {
        "credit_id": "credit-performance-1",
        "tenant_id": "tenant-a",
        "campaign_id": CAMPAIGN_ID,
        "attribution_run_id": "run-performance-1",
        "conversion_id": "conversion-1",
        "touchpoint_id": "tp-1",
        "credit_weight": "1.000000",
        "attributed_conversion_count": "1.000000",
        "attributed_gross_revenue": "39.00",
        "attributed_net_revenue": "35.00",
        "run_completed_at": "2026-10-06T10:05:00Z",
    }
    spend = CampaignSpendRead(
        rows=[
            {
                "spend_record_id": "spend-1",
                "tenant_id": "tenant-a",
                "campaign_id": CAMPAIGN_ID,
                "period_start": "2026-10-01T00:00:00Z",
                "period_end": "2026-10-02T00:00:00Z",
                "total_cost": "100.00",
                "billing_currency": "USD",
                "normalized_currency": "USD",
            }
        ],
        available=True,
        complete=False,
        reason="campaign_spend_coverage_watermark_unavailable",
    )
    source = PerformanceCampaign360Source(
        conversion=conversion,
        credits=[credit],
        spend=spend,
    )

    result = await Campaign360Provider(source).project(_request(), _context())

    assert source.spend_calls == [
        {
            "tenant_id": "tenant-a",
            "campaign_id": CAMPAIGN_ID,
            "start": None,
            "end": None,
            "limit": 501,
        }
    ]
    assert _slot(result, "performance")["state"] == "partial"
    performance = _section(result, "state").content["domainContexts"]["performance"]
    assert performance["attributedOutcome"]["state"] == "available"
    assert performance["attributedOutcome"]["grossRevenue"]["byCurrency"] == {
        "USD": "39.00"
    }
    assert performance["attributedOutcome"]["netRevenue"]["byCurrency"] == {
        "USD": "35.00"
    }
    assert performance["spendObservations"]["state"] == "partial"
    assert performance["spendObservations"]["records"][0]["amount"] == "100.00"
    assert performance["spendObservations"]["coverage"] == "bounded_rows_without_coverage_attestation"
    assert performance["roas"]["state"] == "unknown"
    assert performance["roi"]["state"] == "unknown"
    assert any(claim.kind == "campaign_attributed_gross_revenue" for claim in result.claims)
    assert any(claim.kind == "campaign_spend_record" for claim in result.claims)


@pytest.mark.asyncio
async def test_campaign_performance_keeps_incomplete_amounts_unknown() -> None:
    source = PerformanceCampaign360Source(
        conversion=ConversionRecordRead(
            {
                "tenant_id": "tenant-a",
                "conversion_id": "conversion-1",
                "occurred_at": "2026-10-05T10:05:00Z",
                "currency": "USD",
                "normalized_currency": "USD",
                "gross_value": "39.00",
                "net_value": "35.00",
            },
            available=True,
        ),
        credits=[
            {
                "credit_id": "credit-incomplete-1",
                "tenant_id": "tenant-a",
                "campaign_id": CAMPAIGN_ID,
                "attribution_run_id": "run-incomplete-1",
                "conversion_id": "conversion-1",
                "credit_weight": "1.000000",
                "attributed_conversion_count": "1.000000",
                "attributed_gross_revenue": None,
                "attributed_net_revenue": None,
                "run_completed_at": "2026-10-06T10:05:00Z",
            }
        ],
        spend=CampaignSpendRead(
            rows=[
                {
                    "spend_record_id": "spend-unknown",
                    "tenant_id": "tenant-a",
                    "campaign_id": CAMPAIGN_ID,
                    "period_start": "2026-10-01T00:00:00Z",
                    "period_end": "2026-10-02T00:00:00Z",
                    "total_cost": None,
                    "billing_currency": "USD",
                    "normalized_currency": "USD",
                }
            ],
            available=True,
            complete=False,
        ),
    )

    result = await Campaign360Provider(source).project(_request(), _context())

    performance = _section(result, "state").content["domainContexts"]["performance"]
    assert performance["attributedOutcome"]["grossRevenue"]["state"] == "unknown"
    assert performance["attributedOutcome"]["netRevenue"]["state"] == "unknown"
    assert performance["attributedOutcome"]["grossRevenue"]["byCurrency"] == {}
    assert performance["spendObservations"]["records"][0]["amount"] is None
    assert performance["spendObservations"]["records"][0]["amountState"] == "unknown"
    assert performance["roas"]["state"] == "unknown"
    assert not any(
        claim.kind in {"campaign_attributed_gross_revenue", "campaign_attributed_net_revenue"}
        for claim in result.claims
    )


@pytest.mark.asyncio
async def test_campaign_performance_drops_cross_tenant_spend_rows() -> None:
    source = PerformanceCampaign360Source(
        conversion=ConversionRecordRead(
            {
                "tenant_id": "tenant-a",
                "conversion_id": "conversion-1",
                "occurred_at": "2026-10-05T10:05:00Z",
                "currency": "USD",
                "normalized_currency": "USD",
                "gross_value": "39.00",
                "net_value": "35.00",
            },
            available=True,
        ),
        credits=[
            {
                "credit_id": "credit-cross-tenant-spend-1",
                "tenant_id": "tenant-a",
                "campaign_id": CAMPAIGN_ID,
                "attribution_run_id": "run-cross-tenant-spend-1",
                "conversion_id": "conversion-1",
                "credit_weight": "1.000000",
                "attributed_conversion_count": "1.000000",
                "attributed_gross_revenue": "39.00",
                "attributed_net_revenue": "35.00",
                "run_completed_at": "2026-10-06T10:05:00Z",
            }
        ],
        spend=CampaignSpendRead(
            rows=[
                {
                    "spend_record_id": "foreign-spend-1",
                    "tenant_id": "tenant-other",
                    "campaign_id": CAMPAIGN_ID,
                    "period_start": "2026-10-01T00:00:00Z",
                    "period_end": "2026-10-02T00:00:00Z",
                    "total_cost": "100.00",
                    "billing_currency": "USD",
                    "normalized_currency": "USD",
                }
            ],
            available=True,
            complete=True,
        ),
    )

    result = await Campaign360Provider(source).project(_request(), _context())

    performance = _section(result, "state").content["domainContexts"]["performance"]
    assert performance["spendObservations"]["records"] == []
    assert performance["spendObservations"]["invalidRowCount"] == 1
    assert not any(claim.kind == "campaign_spend_record" for claim in result.claims)


@pytest.mark.asyncio
async def test_campaign_population_links_bind_exact_explicit_cohort_association():
    row = {
        "tenant_id": "tenant-a",
        "campaign_id": CAMPAIGN_ID,
        "population_id": "population-1",
        "event_type": "linked",
        "link_event_id": "link-event-1",
        "source_id": "aether.operator:operator-1",
        "source_record_id": "operator-record-1",
        "source_revision_id": "revision-2",
        "source_event_id": "operator-event-1",
        "actor_id": "operator-1",
        "actor_type": "tenant_user",
        "source_observed_at": "2026-10-05T10:00:00Z",
        "effective_at": "2026-10-05T10:00:00Z",
        "evidence_refs": [
            {
                "id": CAMPAIGN_ID,
                "type": "entity",
                "source": "services/api/journeys/campaign/repository.py:campaigns",
            },
            {"id": "population-1", "type": "entity", "source": "identity_populations"},
        ],
    }
    source = PopulationLinkCampaign360Source(
        CampaignPopulationLinkRead("tenant-a", CAMPAIGN_ID, (row,), available=True)
    )
    result = await Campaign360Provider(source).project(_request(), _context())

    assert source.population_link_calls == [("tenant-a", CAMPAIGN_ID, 101)]
    slot = _slot(result, "cohorts_syndicates")
    assert slot["state"] == "partial"
    assert slot["explicitPopulationLinkCount"] == 1
    assert slot["dimensionStates"] == {
        "explicitPopulationLinks": "available",
        "broaderCohortMembership": "unknown",
        "syndicateMembership": "unknown",
    }
    context = _section(result, "state").content["domainContexts"]["cohorts_syndicates"]
    assert context["associations"][0]["populationId"] == "population-1"
    assert context["associations"][0]["associationState"] == "explicitly_linked"
    assert any(claim.kind == "campaign_population_link_observation" for claim in result.claims)


@pytest.mark.asyncio
async def test_exact_touchpoint_source_classification_is_degraded_and_evidenced() -> None:
    source = FakeCampaign360Source(
        touchpoints=RowsRead(
            rows=[
                {
                    "touchpoint_id": "tp-classified",
                    "tenant_id": "tenant-a",
                    "campaign_id": CAMPAIGN_ID,
                    "occurred_at": "2026-10-05T10:00:00Z",
                    "source_event_id": "event-classified",
                    "source_class": "owned",
                    "source_classifier_version": "v1",
                    "source_classification_id": "classification-1",
                    "source_classified_at": "2026-10-05T10:01:00Z",
                    "profile_id": "private-profile-id",
                }
            ],
            available=True,
        )
    )
    result = await Campaign360Provider(source).project(_request(), _context())

    assert _slot(result, "source_classification")["state"] == "degraded"
    context = _section(result, "state").content["domainContexts"]["source_classification"]
    assert context["touchpointClassifications"] == [
        {
            "touchpointId": "tp-classified",
            "sourceEventId": "event-classified",
            "sourceClass": "owned",
            "classifierVersion": "v1",
            "classificationId": "classification-1",
            "classifiedAt": "2026-10-05T10:01:00Z",
            "domainSlotIds": ["source_classification"],
        }
    ]
    assert "private-profile-id" not in str(context)
    claim = next(
        item for item in result.claims if item.kind == "campaign_touchpoint_source_classification"
    )
    assert claim.domainSlotIds == ["source_classification"]
    assert {ref.id for ref in claim.evidenceRefs} == {"tp-classified", "classification-1"}


@pytest.mark.asyncio
async def test_source_class_without_classification_revision_stays_unknown() -> None:
    result = await Campaign360Provider(FakeCampaign360Source()).project(
        _request(), _context()
    )

    assert _slot(result, "source_classification")["state"] == "unknown"
    assert not any(
        item.domainSlotIds == ["source_classification"] for item in result.claims
    )


@pytest.mark.asyncio
async def test_unprovisioned_attribution_stays_missing_without_zero_claims() -> None:
    source = FakeCampaign360Source(
        attribution=AttributionRead(
            credits=[], available=True, data_quality="not_provisioned"
        )
    )
    result = await Campaign360Provider(source).project(_request(), _context())

    assert _slot(result, "attribution")["state"] == "missing"
    assert _section(result, "outcomes").state == "missing"
    assert _section(result, "outcomes").content["attribution"]["credits"] == []
    assert not any("0" in claim for item in result.claims for claim in item.claims)


@pytest.mark.asyncio
async def test_cross_tenant_touchpoint_rows_are_not_projected() -> None:
    foreign = {
        "touchpoint_id": "tp-foreign",
        "tenant_id": "tenant-b",
        "campaign_id": CAMPAIGN_ID,
        "occurred_at": "2026-10-05T10:00:00Z",
        "touchpoint_type": "click",
    }
    source = FakeCampaign360Source(touchpoints=RowsRead([foreign], available=True))
    result = await Campaign360Provider(source).project(_request(), _context())

    assert _slot(result, "touchpoints")["state"] == "unknown"
    assert _section(result, "evidence").content["touchpoints"] == []
    assert all(claim.evidenceRefs[0].id != "tp-foreign" for claim in result.claims)
    assert "touchpoint_row_scope_mismatch" in result.degradedReasons


@pytest.mark.asyncio
async def test_unavailable_sources_are_degraded_and_do_not_raise() -> None:
    source = FakeCampaign360Source(
        touchpoints=RowsRead([], available=False, reason="secret backend detail"),
        attribution=AttributionRead([], available=False, reason="secret credit detail"),
    )
    result = await Campaign360Provider(source).project(_request(), _context())

    assert _slot(result, "touchpoints")["state"] == "degraded"
    assert _slot(result, "attribution")["state"] == "degraded"
    assert result.degradedReasons == [
        "touchpoint_repository_unavailable",
        "attribution_repository_unavailable",
    ]
    assert "secret" not in str(result.model_dump())


@pytest.mark.asyncio
async def test_historical_request_is_unknown_without_current_state_reads() -> None:
    source = FakeCampaign360Source()
    result = await Campaign360Provider(source).project(
        _request(as_of="2026-10-05T00:00:00Z"), _context()
    )

    assert not source.campaign_calls
    assert not source.touchpoint_calls
    assert not source.attribution_calls
    assert not source.anomaly_calls
    assert _slot(result, "campaign_identity")["state"] == "unknown"
    assert _section(result, "summary").state == "unknown"
    assert result.asOf is None


@pytest.mark.asyncio
@pytest.mark.parametrize("subject_kind", ["episode", "population", "source"])
async def test_non_campaign_subject_is_not_resolved_or_read(subject_kind: str) -> None:
    source = ContextCampaign360Source()
    result = await Campaign360Provider(source).project(
        _request(subject_kind=subject_kind, subject_id="external-id-1"), _context()
    )

    assert not source.campaign_calls
    assert not source.touchpoint_calls
    assert not source.attribution_calls
    assert not source.episode_calls
    assert _slot(result, "campaign_identity")["state"] == "not_applicable"
    assert not result.claims


@pytest.mark.asyncio
async def test_claims_can_be_omitted_without_losing_evidence_slot_bindings() -> None:
    source = FakeCampaign360Source()
    result = await Campaign360Provider(source).project(
        _request(include_claims=False), _context()
    )

    assert result.claims == []
    slots = {
        slot
        for item in _section(result, "evidence").content["items"]
        for slot in item["domainSlotIds"]
    }
    assert "campaign_identity" in slots
    assert "touchpoints" in slots


def test_register_provider_is_explicit_and_registry_compatible() -> None:
    registry = ProviderRegistry()
    provider = register_provider(registry)

    assert registry.get("campaign360") is provider
    assert provider.projection_id == "campaign360"


@pytest.mark.asyncio
async def test_compare_without_two_windows_preserves_unknown_temporal_state() -> None:
    source = FakeCampaign360Source()
    result = await Campaign360Provider(source).project(
        _request(temporal_mode="compare"), _context()
    )

    assert source.campaign_calls
    assert not source.touchpoint_calls
    assert not source.attribution_calls
    assert _slot(result, "touchpoints")["state"] == "unknown"
    assert _slot(result, "attribution")["state"] == "unknown"
    assert "comparison_window_contract_unavailable" in result.degradedReasons


def _targeting_leakage_finding(
    *,
    tenant_id: str = "tenant-a",
    campaign_id: str = CAMPAIGN_ID,
    finding_id: str = "elf_campaign-1",
    computed_at: str = "2026-10-05T10:05:00Z",
) -> dict[str, object]:
    return {
        "findingId": finding_id,
        "tenantId": tenant_id,
        "campaignId": campaign_id,
        "targetingIntentId": "intent-1",
        "clusterId": "cluster-private-id",
        "reasonCode": "manual_tenant_exclusion",
        "excludedEntityCount": 20,
        "reachedEntityCount": 4,
        "leakageRate": 0.2,
        "likelyCauses": ["provider_ignored_exclusion"],
        "severity": "medium",
        "evidenceRefs": [
            {
                "id": "tob-observation-1",
                "type": "event",
                "source": "targeting_observation",
                "observedAt": "2026-10-05T10:00:00Z",
            },
            {
                "id": "tes-snapshot-1",
                "type": "annotation",
                "source": "eligibility_snapshot",
                "observedAt": "2026-10-04T23:00:00Z",
            },
        ],
        "computedAt": computed_at,
    }


@pytest.mark.asyncio
async def test_targeting_anomalies_join_exact_campaign_and_preserve_evidence_chain() -> None:
    source = FakeCampaign360Source(
        anomalies=CampaignAnomalyRead(
            rows=[_targeting_leakage_finding()], available=True, complete=True
        )
    )
    result = await Campaign360Provider(source).project(
        _request(time_range={"from": "2026-10-01T00:00:00Z", "to": "2026-10-11T00:00:00Z"}),
        _context(),
    )

    assert source.anomaly_calls == [
        {"tenant_id": "tenant-a", "campaign_id": CAMPAIGN_ID, "limit": 101}
    ]
    slot = _slot(result, "anomalies")
    assert slot["state"] == "partial"
    assert slot["sourceAuthorities"] == [
        "targeting_leakage_findings",
        "risk_outputs",
        "source_provenance",
    ]
    assert slot["dimensionStates"] == {
        "targetingLeakageFindings": "available",
        "riskOutputs": "unknown",
        "sourceAnomalies": "unknown",
    }
    context = _section(result, "state").content["domainContexts"]["anomalies"]
    assert context["state"] == "partial"
    assert context["freshness"] == {
        "state": "available",
        "sourceTimestamp": "2026-10-05T10:05:00Z",
        "sourceTimestampsPreserved": True,
        "missingTimestamp": "unknown",
    }
    item = context["findings"][0]
    assert item["findingId"] == "elf_campaign-1"
    assert item["severity"] == "medium"
    assert item["reasonCode"] == "manual_tenant_exclusion"
    assert item["computedAt"] == "2026-10-05T10:05:00Z"
    assert "clusterId" not in item
    assert {ref["id"] for ref in item["evidenceRefs"]} == {
        "elf_campaign-1",
        "tob-observation-1",
        "tes-snapshot-1",
    }
    claim = next(
        claim for claim in result.claims if claim.kind == "campaign_targeting_leakage_finding"
    )
    assert claim.domainSlotIds == ["anomalies"]
    assert {ref.id for ref in claim.evidenceRefs} == {
        "elf_campaign-1",
        "tob-observation-1",
        "tes-snapshot-1",
    }
    evidence_by_id = {
        item["evidence"]["id"]: item
        for item in _section(result, "evidence").content["items"]
    }
    assert evidence_by_id["elf_campaign-1"]["domainSlotIds"] == [
        "anomalies",
        "evidence_trace",
    ]


@pytest.mark.asyncio
async def test_campaign_anomaly_join_rejects_foreign_scope_as_a_unit() -> None:
    foreign = _targeting_leakage_finding(tenant_id="tenant-b")
    source = FakeCampaign360Source(
        anomalies=CampaignAnomalyRead(rows=[foreign], available=True, complete=True)
    )

    result = await Campaign360Provider(source).project(_request(), _context())

    context = _section(result, "state").content["domainContexts"]["anomalies"]
    assert _slot(result, "anomalies")["state"] == "unknown"
    assert context["findings"] == []
    assert context["reason"] == "campaign_anomaly_record_scope_mismatch"
    assert "tob-observation-1" not in str(_section(result, "evidence").content)


@pytest.mark.asyncio
async def test_campaign_anomaly_source_outage_is_degraded_without_backend_details() -> None:
    source = FakeCampaign360Source(
        anomalies=CampaignAnomalyRead(
            rows=[], available=False, complete=False, reason="secret db exception"
        )
    )

    result = await Campaign360Provider(source).project(_request(), _context())

    assert _slot(result, "anomalies")["state"] == "degraded"
    assert "targeting_anomaly_authority_unavailable" in result.degradedReasons
    assert "secret" not in str(result.model_dump())


@pytest.mark.asyncio
async def test_campaign_anomaly_truncation_is_not_reported_as_complete() -> None:
    source = FakeCampaign360Source(
        anomalies=CampaignAnomalyRead(
            rows=[_targeting_leakage_finding()], available=True, complete=False
        )
    )

    result = await Campaign360Provider(source).project(_request(), _context())

    context = _section(result, "state").content["domainContexts"]["anomalies"]
    assert _slot(result, "anomalies")["state"] == "truncated"
    assert context["findingsTruncated"] is True
    assert context["dimensionStates"]["targetingLeakageFindings"] == "truncated"
    assert "campaign_targeting_leakage_findings_truncated" in result.degradedReasons


@pytest.mark.asyncio
async def test_campaign_anomaly_time_window_uses_computed_at_half_open_bounds() -> None:
    source = FakeCampaign360Source(
        anomalies=CampaignAnomalyRead(
            rows=[
                _targeting_leakage_finding(
                    finding_id="elf-inside",
                    computed_at="2026-10-05T10:05:00Z",
                ),
                _targeting_leakage_finding(
                    finding_id="elf-end-boundary",
                    computed_at="2026-10-11T00:00:00Z",
                ),
            ],
            available=True,
            complete=True,
        )
    )

    result = await Campaign360Provider(source).project(
        _request(time_range={"from": "2026-10-01T00:00:00Z", "to": "2026-10-11T00:00:00Z"}),
        _context(),
    )

    context = _section(result, "state").content["domainContexts"]["anomalies"]
    assert [item["findingId"] for item in context["findings"]] == ["elf-inside"]
    assert context["freshness"]["sourceTimestamp"] == "2026-10-05T10:05:00Z"
    assert context["temporalBounds"]["toExclusive"] is True


@pytest.mark.asyncio
async def test_repository_campaign_anomaly_source_uses_exact_tenant_and_campaign_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class _LeakageRepository:
        async def list_for_tenant(
            self, tenant_id: str, *, limit: int = 100, **filters: object
        ) -> list[dict[str, object]]:
            calls.append({"tenant_id": tenant_id, "limit": limit, **filters})
            return [_targeting_leakage_finding()]

    class _Repositories:
        leakage = _LeakageRepository()

    from intelligence.targeting_intelligence import repository as targeting_repository

    monkeypatch.setattr(
        targeting_repository, "get_targeting_repositories", lambda: _Repositories()
    )

    read = await RepositoryCampaign360Source().campaign_anomalies(
        "tenant-a", CAMPAIGN_ID, limit=MAX_CAMPAIGN_ANOMALIES + 1
    )

    assert calls == [
        {"tenant_id": "tenant-a", "limit": 101, "campaignId": CAMPAIGN_ID}
    ]
    assert read.available is True
    assert read.complete is True
    assert read.rows[0]["campaignId"] == CAMPAIGN_ID


@pytest.mark.asyncio
async def test_campaign_journey_context_uses_exact_tenant_campaign_membership_and_evidence() -> None:
    source = ContextCampaign360Source()
    result = await Campaign360Provider(source).project(
        _request(),
        _context(),
    )

    assert source.journey_calls[0]["tenant_id"] == "tenant-a"
    assert source.journey_calls[0]["campaign_id"] == CAMPAIGN_ID
    assert source.journey_calls[0]["limit"] > 0
    state = _section(result, "state").content
    slot = _slot(result, "journeys")
    context = state["domainContexts"]["journeys"]
    assert slot["state"] == "available"
    assert slot["dimensionStates"] == {"journeys": "available", "episodes": "unknown"}
    assert context["journeys"][0]["journeyVersionId"] == "journey-version-1"
    assert context["journeys"][0]["campaignIds"] == [CAMPAIGN_ID]
    assert context["freshness"]["state"] == "available"
    assert context["freshness"]["sourceTimestamp"] == "2026-10-09T23:59:00Z"
    claim = next(item for item in result.claims if item.kind == "campaign_journey_membership")
    assert claim.domainSlotIds == ["journeys"]
    assert claim.evidenceRefs[0].id == "journey-version-1"
    assert claim.evidenceRefs[0].source.endswith("journey_repo.py:journey_versions")


@pytest.mark.asyncio
async def test_campaign_journey_evidence_slot_binding_survives_claim_omission() -> None:
    result = await Campaign360Provider(ContextCampaign360Source()).project(
        _request(include_claims=False),
        _context(),
    )

    evidence_items = _section(result, "evidence").content["items"]
    journey_evidence = next(
        item for item in evidence_items if item["evidence"]["id"] == "journey-version-1"
    )
    assert result.claims == []
    assert journey_evidence["domainSlotIds"] == ["journeys", "evidence_trace"]


@pytest.mark.asyncio
async def test_campaign_journey_context_rejects_foreign_tenant_rows() -> None:
    foreign = {
        "tenant_id": "tenant-b",
        "journey_id": "foreign-journey",
        "journey_version_id": "foreign-version",
        "is_current": True,
        "campaign_ids": [CAMPAIGN_ID],
        "computed_at": "2026-10-10T00:00:00Z",
    }
    source = ContextCampaign360Source(journeys=RowsRead([foreign], available=True))
    result = await Campaign360Provider(source).project(_request(), _context())

    context = _section(result, "state").content["domainContexts"][
        "journeys"
    ]
    assert context["journeys"] == []
    assert context["state"] == "unknown"
    assert context["reason"] == "journey_row_scope_mismatch"
    assert not any(claim.evidenceRefs[0].id == "foreign-version" for claim in result.claims)


@pytest.mark.asyncio
async def test_campaign_journey_context_degrades_on_authority_outage() -> None:
    source = ContextCampaign360Source(
        journeys=RowsRead([], available=False, reason="private backend detail")
    )
    result = await Campaign360Provider(source).project(_request(), _context())

    context = _section(result, "state").content["domainContexts"][
        "journeys"
    ]
    assert context["state"] == "degraded"
    assert context["dimensionStates"] == {"journeys": "unavailable", "episodes": "unknown"}
    assert "private" not in str(context)
    assert "journey_authority_unavailable" in result.degradedReasons


@pytest.mark.asyncio
async def test_campaign_signal_sources_join_exact_touchpoint_event_with_partial_coverage() -> None:
    touchpoint = {
        "touchpoint_id": "tp-linked-event",
        "tenant_id": "tenant-a",
        "campaign_id": CAMPAIGN_ID,
        "occurred_at": "2026-10-05T10:00:00Z",
        "source_event_id": "event-campaign-1",
        "profile_id": "must-not-be-projected",
    }
    event = {
        "event_id": "event-campaign-1",
        "tenant_id": "tenant-a",
        "event_type": "campaign_conversion",
        "event_family": "conversion",
        "source": "sdk",
        "occurred_at": "2026-10-05T10:00:00Z",
        "user_id": "must-not-be-projected",
        "properties": {"private": "must-not-be-projected"},
    }
    source = FakeCampaign360Source(
        touchpoints=RowsRead([touchpoint], available=True),
        signals=RowsRead([event], available=True),
    )

    result = await Campaign360Provider(source).project(_request(), _context())

    assert source.signal_calls == [
        {
            "tenant_id": "tenant-a",
            "event_ids": ["event-campaign-1"],
            "limit": 100,
        }
    ]
    slot = _slot(result, "signal_sources")
    assert slot["state"] == "partial"
    assert slot["dimensionStates"] == {
        "events": "available",
        "observations": "unknown",
        "sourceFacts": "unknown",
    }
    context = _section(result, "state").content["domainContexts"]["signal_sources"]
    assert context["coverage"] == "exact_touchpoint_linked_events_only"
    assert context["events"][0]["eventId"] == "event-campaign-1"
    assert context["events"][0]["linkedTouchpointIds"] == ["tp-linked-event"]
    assert "profile_id" not in str(context)
    assert "must-not-be-projected" not in str(context)
    assert context["freshness"]["state"] == "unknown"
    assert context["freshness"]["sourceTimestampsPreserved"] is True
    claim = next(
        claim for claim in result.claims if claim.kind == "campaign_linked_signal_event"
    )
    assert claim.domainSlotIds == ["signal_sources"]
    assert {(ref.source, ref.id) for ref in claim.evidenceRefs} == {
        ("services/api/repositories/repos.py:events", "event-campaign-1"),
        (
            "services/api/journeys/measurement/repositories/touchpoint_repo.py:silver_campaign_touchpoint_facts",
            "tp-linked-event",
        ),
    }


@pytest.mark.asyncio
async def test_campaign_signal_sources_fail_closed_on_foreign_event_row() -> None:
    touchpoint = {
        "touchpoint_id": "tp-linked-event",
        "tenant_id": "tenant-a",
        "campaign_id": CAMPAIGN_ID,
        "occurred_at": "2026-10-05T10:00:00Z",
        "source_event_id": "event-campaign-1",
    }
    foreign_event = {
        "event_id": "event-campaign-1",
        "tenant_id": "tenant-b",
        "event_type": "foreign_event",
        "occurred_at": "2026-10-05T10:00:00Z",
    }
    source = FakeCampaign360Source(
        touchpoints=RowsRead([touchpoint], available=True),
        signals=RowsRead([foreign_event], available=True),
    )

    result = await Campaign360Provider(source).project(_request(), _context())

    assert _slot(result, "signal_sources")["state"] == "unknown"
    context = _section(result, "state").content["domainContexts"]["signal_sources"]
    assert context["reason"] == "campaign_event_record_scope_mismatch"
    assert context["events"] == []
    assert "foreign_event" not in str(result.model_dump())


@pytest.mark.asyncio
async def test_campaign_signal_source_with_missing_event_time_stays_unknown_in_window() -> None:
    touchpoint = {
        "touchpoint_id": "tp-linked-event",
        "tenant_id": "tenant-a",
        "campaign_id": CAMPAIGN_ID,
        "occurred_at": "2026-10-05T10:00:00Z",
        "source_event_id": "event-campaign-1",
    }
    event = {
        "event_id": "event-campaign-1",
        "tenant_id": "tenant-a",
        "event_type": "campaign_conversion",
    }
    source = FakeCampaign360Source(
        touchpoints=RowsRead([touchpoint], available=True),
        signals=RowsRead([event], available=True),
    )

    result = await Campaign360Provider(source).project(
        _request(
            time_range={"from": "2026-10-01T00:00:00Z", "to": "2026-10-11T00:00:00Z"}
        ),
        _context(),
    )

    assert _slot(result, "signal_sources")["state"] == "unknown"
    context = _section(result, "state").content["domainContexts"]["signal_sources"]
    assert context["events"] == []
    assert (
        context["reason"]
        == "campaign_signal_event_timestamp_unavailable_for_temporal_scope"
    )


@pytest.mark.asyncio
async def test_campaign_signal_sources_do_not_read_when_projection_tenant_disagrees() -> None:
    touchpoint = {
        "touchpoint_id": "tp-linked-event",
        "tenant_id": "tenant-a",
        "campaign_id": CAMPAIGN_ID,
        "occurred_at": "2026-10-05T10:00:00Z",
        "source_event_id": "event-campaign-1",
    }
    source = FakeCampaign360Source(touchpoints=RowsRead([touchpoint], available=True))

    result = await Campaign360Provider(source).project(
        _request(tenant_id="tenant-a"), _context(tenant_id="tenant-b")
    )

    assert source.signal_calls == []
    assert _slot(result, "signal_sources")["state"] == "unknown"
    context = _section(result, "state").content["domainContexts"]["signal_sources"]
    assert context["reason"] == "projection_context_tenant_scope_mismatch"


@pytest.mark.asyncio
async def test_repository_signal_event_reader_queries_exact_tenant_and_event_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dependencies import providers
    from repositories import repos

    calls: list[tuple[str, dict[str, str], int]] = []

    class FakeAnalyticsRepository:
        def __init__(self, cache: object) -> None:
            assert cache == "shared-cache"

        async def query_events(
            self, tenant_id: str, filters: dict[str, str], *, limit: int
        ) -> list[dict[str, object]]:
            calls.append((tenant_id, filters, limit))
            event_id = filters["event_id"]
            row_tenant = "tenant-b" if event_id == "event-foreign" else tenant_id
            return [
                {
                    "event_id": event_id,
                    "tenant_id": row_tenant,
                    "event_type": "conversion",
                }
            ]

    monkeypatch.setattr(providers, "get_cache", lambda: "shared-cache")
    monkeypatch.setattr(repos, "AnalyticsRepository", FakeAnalyticsRepository)

    result = await RepositoryCampaign360Source().signal_events(
        "tenant-a",
        ["event-a", "event-foreign", "bad/id"],
        limit=3,
    )

    assert calls == [
        ("tenant-a", {"event_id": "event-a"}, 2),
        ("tenant-a", {"event_id": "event-foreign"}, 2),
    ]
    assert result.available is True
    assert [row["event_id"] for row in result.rows] == ["event-a"]
