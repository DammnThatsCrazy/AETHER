"""Exact source-asserted timezone authority for Location360."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from graph.geo.location_facts import LocationFactRepository
from graph.geo.temporal_timezone import (
    GeoTemporalTimezoneAuthority,
    TIMEZONE_ASSERTION_ACTOR,
    TIMEZONE_ASSERTION_READ_CAP,
    TimezoneAssertionRepository,
    TimezoneAuthorityError,
    TimezoneSourceAssertion,
)
from graph.geographic360.provider import (
    Geographic360Provider,
    RepositoryGeographicTimezoneReader,
)
from repositories.repos import reset_in_memory_stores
from shared.geo.models import Coordinate, LocationFact, Region
from shared.intelligence_projections.contracts import (
    ProjectionRequest,
    ProjectionSubject,
)
from shared.intelligence_projections.registry import ProviderRegistry

TENANT = "tenant_geo_temporal_timezone"
SUBJECT = "entity_geo_temporal_timezone"


@pytest.fixture(autouse=True)
def _isolate_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _location_fact(
    location_id: str = "location-tz-1",
    *,
    tenant_id: str = TENANT,
    subject_id: str = SUBJECT,
    observed_at: datetime | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> LocationFact:
    now = datetime.now(timezone.utc)
    return LocationFact(
        location_id=location_id,
        tenant_id=tenant_id,
        subject_type="entity",
        subject_id=subject_id,
        role="primary_residence",
        precision_class="city",
        region_type="city",
        region=Region(
            region_id=f"region-{location_id}",
            region_type="city",
            name="Example City",
            country_code="US",
        ),
        observed_at=observed_at or now - timedelta(days=1),
        valid_from=valid_from or now - timedelta(days=1),
        valid_to=valid_to,
        provider="verified_location_source",
        evidence_refs=["location-source-evidence-1"],
    )


def _assertion(
    *,
    timezone_id: str = "America/New_York",
    source_record_id: str = "source-record-1",
    observed_at: datetime | None = None,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
) -> TimezoneSourceAssertion:
    now = datetime.now(timezone.utc)
    return TimezoneSourceAssertion(
        timezone_id=timezone_id,
        source_provider="verified_timezone_source",
        source_record_id=source_record_id,
        evidence_refs=("timezone-source-evidence-1",),
        observed_at=observed_at or now - timedelta(minutes=5),
        effective_from=effective_from or now - timedelta(days=1),
        effective_to=effective_to,
    )


def _authority() -> tuple[GeoTemporalTimezoneAuthority, LocationFactRepository]:
    location_facts = LocationFactRepository()
    authority = GeoTemporalTimezoneAuthority(
        assertions=TimezoneAssertionRepository(),
        location_facts=location_facts,
    )
    return authority, location_facts


def test_timezone_source_assertion_requires_iana_zone_aware_times_and_evidence():
    now = datetime.now(timezone.utc)
    with pytest.raises(TimezoneAuthorityError, match="canonical IANA"):
        _assertion(timezone_id="EST").validated()
    with pytest.raises(TimezoneAuthorityError, match="timezone-aware"):
        _assertion(observed_at=datetime(2026, 1, 1)).validated()
    with pytest.raises(TimezoneAuthorityError, match="later than"):
        _assertion(effective_from=now, effective_to=now).validated()
    with pytest.raises(TimezoneAuthorityError, match="evidence_ref"):
        TimezoneSourceAssertion(
            timezone_id="UTC",
            source_provider="source",
            source_record_id="record",
            evidence_refs=(),
            observed_at=now,
            effective_from=now,
        ).validated()


@pytest.mark.asyncio
async def test_record_derives_tenant_subject_and_actor_from_exact_location_fact():
    authority, location_facts = _authority()
    await location_facts.record(_location_fact())

    record = await authority.record_source_assertion(
        location_id="location-tz-1",
        assertion=_assertion(),
    )

    assert record["tenant_id"] == TENANT
    assert record["subject_type"] == "entity"
    assert record["subject_id"] == SUBJECT
    assert record["location_id"] == "location-tz-1"
    assert record["recorded_by"] == TIMEZONE_ASSERTION_ACTOR
    assert record["source_provider"] == "verified_timezone_source"
    assert record["source_record_id"] == "source-record-1"
    assert record["evidence_refs"] == ["timezone-source-evidence-1"]


@pytest.mark.asyncio
async def test_reader_requires_exact_tenant_subject_and_uses_bitemporal_anchor():
    authority, location_facts = _authority()
    await location_facts.record(_location_fact())
    await authority.record_source_assertion(
        location_id="location-tz-1",
        assertion=_assertion(),
    )
    anchor = datetime.now(timezone.utc) + timedelta(days=1)

    foreign = await authority.timezone_for_location(
        tenant_id="tenant-foreign",
        subject_kind="entity",
        subject_id=SUBJECT,
        location_id="location-tz-1",
        as_of=anchor,
        historical=True,
    )
    assert foreign.state == "unknown"
    assert foreign.reason_code == "timezone_location_subject_mismatch"

    exact = await authority.timezone_for_location(
        tenant_id=TENANT,
        subject_kind="entity",
        subject_id=SUBJECT,
        location_id="location-tz-1",
        as_of=anchor,
        historical=True,
    )
    assert exact.state == "degraded"
    assert exact.content["timezoneId"] == "America/New_York"
    assert exact.content["asOf"] == anchor.isoformat()
    assert exact.content["conversion"]["offsetMinutes"] in {-300, -240}
    assert exact.content["assertions"][0]["sourceProvider"] == "verified_timezone_source"
    assert exact.content["assertions"][0]["sourceEvidenceRefs"] == [
        "timezone-source-evidence-1"
    ]
    assert exact.evidence_refs[0].source == "geo_temporal_timezone_assertions"


@pytest.mark.asyncio
async def test_reader_keeps_future_observed_assertions_unknown_at_earlier_asof():
    authority, location_facts = _authority()
    await location_facts.record(_location_fact())
    now = datetime.now(timezone.utc)
    await authority.record_source_assertion(
        location_id="location-tz-1",
        assertion=_assertion(
            observed_at=now + timedelta(days=2),
            effective_from=now - timedelta(days=1),
        ),
    )

    result = await authority.timezone_for_location(
        tenant_id=TENANT,
        subject_kind="entity",
        subject_id=SUBJECT,
        location_id="location-tz-1",
        as_of=now + timedelta(days=1),
        historical=True,
    )
    assert result.state == "unknown"
    assert result.reason_code == "timezone_assertion_not_effective_as_of"


@pytest.mark.asyncio
async def test_reader_does_not_resurrect_erased_location_on_historical_read():
    authority, location_facts = _authority()
    await location_facts.record(_location_fact())
    await authority.record_source_assertion(
        location_id="location-tz-1",
        assertion=_assertion(),
    )
    await location_facts.revoke(
        "location-tz-1",
        actor_id="dsr_erasure_job",
        reason="dsr_erasure",
        tenant_id=TENANT,
    )

    result = await authority.timezone_for_location(
        tenant_id=TENANT,
        subject_kind="entity",
        subject_id=SUBJECT,
        location_id="location-tz-1",
        as_of=datetime.now(timezone.utc) - timedelta(days=2),
        historical=True,
    )

    assert result.state == "unknown"
    assert result.reason_code == "canonical_location_fact_erased"


@pytest.mark.asyncio
async def test_conflicting_source_zones_are_reported_without_selecting_one():
    authority, location_facts = _authority()
    await location_facts.record(_location_fact())
    await authority.record_source_assertion(
        location_id="location-tz-1",
        assertion=_assertion(timezone_id="America/New_York", source_record_id="east"),
    )
    await authority.record_source_assertion(
        location_id="location-tz-1",
        assertion=_assertion(timezone_id="America/Detroit", source_record_id="detroit"),
    )

    result = await authority.timezone_for_location(
        tenant_id=TENANT,
        subject_kind="entity",
        subject_id=SUBJECT,
        location_id="location-tz-1",
        as_of=datetime.now(timezone.utc) + timedelta(days=1),
        historical=True,
    )
    assert result.state == "conflicted"
    assert result.reason_code == "timezone_source_assertions_conflict_at_as_of"
    assert result.content["conflictingTimezoneIds"] == [
        "America/Detroit",
        "America/New_York",
    ]


@pytest.mark.asyncio
async def test_provider_joins_timezone_only_through_exact_primary_location_fact():
    authority, location_facts = _authority()
    now = datetime.now(timezone.utc)
    await location_facts.record(
        _location_fact(observed_at=now - timedelta(hours=1), valid_from=now - timedelta(days=1))
    )
    await authority.record_source_assertion(
        location_id="location-tz-1",
        assertion=_assertion(
            observed_at=now - timedelta(minutes=5),
            effective_from=now - timedelta(days=1),
        ),
    )
    provider = Geographic360Provider(
        timezone_reader=RepositoryGeographicTimezoneReader(authority=authority)
    )
    request = ProjectionRequest(
        projectionId="geographic360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id=SUBJECT),
        temporalMode="window",
    )
    context = await ProviderRegistry().build_context("geographic360", request)

    result = await provider.project(request, context)
    state = next(section for section in result.sections if section.id == "state")
    slot = state.content["requiredSlots"]["timezone"]

    assert slot["state"] == "degraded"
    assert slot["content"]["timezoneId"] == "America/New_York"
    assert slot["content"]["conversion"]["instant"]
    assert {ref["source"] for ref in slot["evidenceRefs"]} == {
        "location_facts",
        "geo_temporal_timezone_assertions",
    }
    claim = next(claim for claim in result.claims if claim.domainSlotIds == ["timezone"])
    assert "America/New_York" in claim.claims[0]
    assert claim.evidenceRefs


@pytest.mark.asyncio
async def test_provider_never_uses_place_labels_or_coordinates_as_timezone_authority():
    authority, location_facts = _authority()
    # This fact has coordinates/labels but no source timezone assertion.
    fact = _location_fact()
    fact.coordinate = Coordinate(latitude=40.7128, longitude=-74.0060)
    await location_facts.record(fact)
    provider = Geographic360Provider(
        timezone_reader=RepositoryGeographicTimezoneReader(authority=authority)
    )
    request = ProjectionRequest(
        projectionId="geographic360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id=SUBJECT),
        temporalMode="window",
    )
    context = await ProviderRegistry().build_context("geographic360", request)

    result = await provider.project(request, context)
    state = next(section for section in result.sections if section.id == "state")
    slot = state.content["requiredSlots"]["timezone"]
    assert slot["state"] == "unknown"
    assert slot["reasonCode"] == "timezone_assertion_not_effective_as_of"
    assert "timezoneId" not in str(slot)
    assert not any(claim.domainSlotIds == ["timezone"] for claim in result.claims)
