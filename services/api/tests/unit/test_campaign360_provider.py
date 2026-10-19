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
    Campaign360Provider,
    CampaignRead,
    OUTPUT_SECTIONS,
    RowsRead,
    register_provider,
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
        self.campaign_calls: list[tuple[str, object]] = []
        self.touchpoint_calls: list[dict[str, object]] = []
        self.attribution_calls: list[dict[str, object]] = []

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
        "campaign_identity_and_state",
        "touchpoints_and_communications",
        "journey_and_episode_context",
        "attribution_and_outcomes",
        "population_context",
        "economic_context",
    }
    assert {slot["id"] for slot in _section(result, "state").content["slots"]} == expected_slots
    assert _slot(result, "campaign_identity_and_state")["state"] == "available"
    assert _slot(result, "touchpoints_and_communications")["state"] == "degraded"
    assert _slot(result, "touchpoints_and_communications")["dimensionStates"] == {
        "touchpoints": "available",
        "communicationFacts": "unknown",
    }
    assert _slot(result, "attribution_and_outcomes")["state"] == "degraded"
    assert _slot(result, "attribution_and_outcomes")["dimensionStates"] == {
        "attributionCredits": "available",
        "outcomes": "unknown",
    }
    assert _slot(result, "journey_and_episode_context")["state"] == "unknown"
    assert _slot(result, "population_context")["state"] == "unknown"
    assert _slot(result, "economic_context")["state"] == "unknown"

    assert all(claim.evidenceRefs for claim in result.claims)
    assert all(claim.domainSlotIds for claim in result.claims)
    assert {slot for claim in result.claims for slot in claim.domainSlotIds or []} >= {
        "campaign_identity_and_state",
        "touchpoints_and_communications",
        "attribution_and_outcomes",
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
async def test_unprovisioned_attribution_stays_missing_without_zero_claims() -> None:
    source = FakeCampaign360Source(
        attribution=AttributionRead(
            credits=[], available=True, data_quality="not_provisioned"
        )
    )
    result = await Campaign360Provider(source).project(_request(), _context())

    assert _slot(result, "attribution_and_outcomes")["state"] == "missing"
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

    assert _slot(result, "touchpoints_and_communications")["state"] == "unknown"
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

    assert _slot(result, "touchpoints_and_communications")["state"] == "degraded"
    assert _slot(result, "attribution_and_outcomes")["state"] == "degraded"
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
    assert _slot(result, "campaign_identity_and_state")["state"] == "unknown"
    assert _section(result, "summary").state == "unknown"
    assert result.asOf is None


@pytest.mark.asyncio
async def test_non_campaign_subject_is_not_resolved_or_read() -> None:
    source = FakeCampaign360Source()
    result = await Campaign360Provider(source).project(
        _request(subject_kind="episode", subject_id="episode-1"), _context()
    )

    assert not source.campaign_calls
    assert not source.touchpoint_calls
    assert not source.attribution_calls
    assert _slot(result, "campaign_identity_and_state")["state"] == "not_applicable"
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
    assert "campaign_identity_and_state" in slots
    assert "touchpoints_and_communications" in slots


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
    assert _slot(result, "touchpoints_and_communications")["state"] == "unknown"
    assert _slot(result, "attribution_and_outcomes")["state"] == "unknown"
    assert "comparison_window_contract_unavailable" in result.degradedReasons
