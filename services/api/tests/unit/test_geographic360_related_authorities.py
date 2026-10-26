"""Location360 cross-authority joins must use exact persisted references."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from graph.geographic360.related_authorities import (
    RepositoryGeographicRelatedAuthorityReader,
)
from graph.geographic360.provider import (
    Geographic360Provider,
    GeographicPosture,
    GeographicView,
    LocationRow,
)
from shared.intelligence_projections.contracts import ProjectionRequest, ProjectionSubject
from shared.intelligence_projections.registry import ProviderRegistry

TENANT = "tenant_location_related"
ENTITY = "entity-location-related"
EVENT = "location-observation-exact-1"


def _scope(**overrides):
    values = {
        "tenant_id": TENANT,
        "subject_kind": "entity",
        "subject_id": ENTITY,
        "source_observation_id": EVENT,
        "as_of": None,
    }
    values.update(overrides)
    return values


@pytest.mark.asyncio
async def test_campaign_slot_joins_only_exact_tenant_source_event(monkeypatch):
    from journeys.measurement.repositories import touchpoint_repo

    class FakeTouchpoints:
        async def list_by_source_event(self, tenant_id, source_event_id, *, limit):
            assert (tenant_id, source_event_id) == (TENANT, EVENT)
            assert limit == 101
            return [
                {
                    "tenant_id": TENANT,
                    "source_event_id": EVENT,
                    "campaign_id": "campaign-exact",
                    "touchpoint_id": "touchpoint-exact",
                    "occurred_at": "2026-10-24T10:00:00+00:00",
                    "channel": "email",
                    "privacy_class": "behavioral",
                }
            ]

    monkeypatch.setattr(touchpoint_repo, "TouchpointRepository", FakeTouchpoints)
    slots = await RepositoryGeographicRelatedAuthorityReader().related_slots(**_scope())

    campaign = slots["campaigns"]
    assert campaign["state"] == "degraded"
    assert campaign["content"]["locationSpecific"] is True
    assert campaign["content"]["joinBasis"].endswith(
        "touchpoint.source_event_id_equals_location.source_observation_id"
    )
    assert campaign["content"]["records"][0]["campaignId"] == "campaign-exact"
    assert {ref["id"] for ref in campaign["evidenceRefs"]} == {
        "touchpoint-exact",
        EVENT,
    }


@pytest.mark.asyncio
async def test_campaign_slot_rejects_a_foreign_tenant_result(monkeypatch):
    from journeys.measurement.repositories import touchpoint_repo

    class ForeignTouchpoints:
        async def list_by_source_event(self, tenant_id, source_event_id, *, limit):
            return [
                {
                    "tenant_id": "tenant-foreign",
                    "source_event_id": EVENT,
                    "campaign_id": "campaign-foreign",
                    "touchpoint_id": "touchpoint-foreign",
                }
            ]

    monkeypatch.setattr(touchpoint_repo, "TouchpointRepository", ForeignTouchpoints)
    slots = await RepositoryGeographicRelatedAuthorityReader().related_slots(**_scope())

    assert slots["campaigns"]["state"] == "unknown"
    assert slots["campaigns"]["reasonCode"] == "campaign_touchpoint_scope_mismatch"


@pytest.mark.asyncio
async def test_journey_slot_requires_explicit_event_membership(monkeypatch):
    from journeys.measurement.repositories import journey_repo

    class FakeJourneys:
        async def find_current_for_profile(self, tenant_id, profile_id, *, identity_type, limit):
            assert (tenant_id, profile_id, identity_type) == (TENANT, ENTITY, "profile")
            assert limit == 101
            return [
                {
                    "tenant_id": TENANT,
                    "profile_id": ENTITY,
                    "journey_id": "journey-1",
                    "journey_version_id": "journey-version-1",
                    "is_current": True,
                    "event_ids": [EVENT],
                    "journey_type": "profile",
                    "journey_state": "open",
                    "computed_at": "2026-10-24T10:00:00+00:00",
                },
                {
                    "tenant_id": TENANT,
                    "profile_id": ENTITY,
                    "journey_id": "journey-2",
                    "journey_version_id": "journey-version-2",
                    "is_current": True,
                    "event_ids": ["different-event"],
                    "computed_at": "2026-10-24T10:00:00+00:00",
                },
            ]

    monkeypatch.setattr(journey_repo, "JourneyRepository", FakeJourneys)
    slots = await RepositoryGeographicRelatedAuthorityReader().related_slots(**_scope())

    journey = slots["journeys"]
    assert journey["state"] == "degraded"
    assert [item["journeyId"] for item in journey["content"]["records"]] == ["journey-1"]
    assert journey["content"]["records"][0]["matchedEventId"] == EVENT


@pytest.mark.asyncio
async def test_profile_slot_uses_only_exact_entity_identity(monkeypatch):
    from identity.profile import profile360_provider

    class FakeProfileSource:
        async def canonical_entity(self, tenant_id, subject):
            return profile360_provider.CanonicalEntityRead(
                record={"tenant_id": TENANT, "entity_id": ENTITY},
                available=True,
                scope_known=True,
            )

        async def identity_record(self, tenant_id, subject):
            return profile360_provider.ProfileRead(
                record={
                    "tenant_id": TENANT,
                    "user_id": ENTITY,
                    "updated_at": "2026-10-24T10:00:00+00:00",
                    "email": "sensitive@example.invalid",
                },
                available=True,
                scope_known=True,
            )

    monkeypatch.setattr(profile360_provider, "RepositoryProfile360Source", FakeProfileSource)
    slots = await RepositoryGeographicRelatedAuthorityReader().related_slots(**_scope())

    profile = slots["profiles"]
    assert profile["state"] == "degraded"
    assert profile["content"]["locationSpecific"] is False
    assert profile["content"]["entityId"] == ENTITY
    assert "sensitive@example.invalid" not in str(profile)


@pytest.mark.asyncio
async def test_risk_and_value_require_exact_source_event_evidence(monkeypatch):
    from intelligence.risk360 import store as risk_store
    from value.economic import economic360_provider

    class FakeRiskSignals:
        async def list_by_subject(self, tenant_id, subject_kind, subject_id, *, limit):
            assert (tenant_id, subject_kind, subject_id) == (TENANT, "entity", ENTITY)
            return [
                {
                    "tenant_id": TENANT,
                    "subject_kind": "entity",
                    "subject_id": ENTITY,
                    "signal_id": "risk-event-linked",
                    "risk_dimension": "identity",
                    "claim_state": "inferred",
                    "source": "risk.detector",
                    "observed_at": "2026-10-24T10:00:00+00:00",
                    "evidence_refs": [
                        {"id": EVENT, "type": "event", "source": "canonical.events"}
                    ],
                },
                {
                    "tenant_id": TENANT,
                    "subject_kind": "entity",
                    "subject_id": ENTITY,
                    "signal_id": "risk-unlinked",
                    "risk_dimension": "geographic",
                    "claim_state": "inferred",
                    "source": "risk.detector",
                    "evidence_refs": [
                        {"id": "other-event", "type": "event", "source": "canonical.events"}
                    ],
                },
            ]

    class FakeEconomicReader:
        async def records(self, *, tenant_id, subject):
            assert tenant_id == TENANT
            assert subject.kind == "entity" and subject.id == ENTITY
            return [
                {
                    "tenant_id": TENANT,
                    "_source": "economic-source",
                    "_evidence_id": EVENT,
                    "_evidence_type": "event",
                    "_evidence_source": "canonical.events",
                    "amount": "12.50",
                    "currency": "USD",
                    "_metric_name": "observed_value",
                },
                {
                    "tenant_id": TENANT,
                    "_source": "economic-source",
                    "_evidence_id": "other-event",
                    "_evidence_type": "event",
                    "amount": "900.00",
                    "currency": "USD",
                },
            ]

    monkeypatch.setattr(risk_store, "RiskSignalRepository", FakeRiskSignals)
    monkeypatch.setattr(economic360_provider, "RepositoryEconomicSourceReader", FakeEconomicReader)
    slots = await RepositoryGeographicRelatedAuthorityReader().related_slots(**_scope())

    risk = slots["risk"]
    assert risk["state"] == "degraded"
    assert [row["signalId"] for row in risk["content"]["signals"]] == ["risk-event-linked"]
    assert risk["content"]["locationSpecific"] is True
    value = slots["value"]
    assert value["state"] == "degraded"
    assert [row["evidenceId"] for row in value["content"]["records"]] == [EVENT]
    assert value["content"]["records"][0]["amount"] == "12.50"


@pytest.mark.asyncio
async def test_historical_related_reads_remain_unknown_without_bitemporal_sources():
    slots = await RepositoryGeographicRelatedAuthorityReader().related_slots(
        **_scope(as_of=datetime(2026, 10, 1, tzinfo=timezone.utc))
    )

    assert all(slots[slot]["state"] == "unknown" for slot in slots)
    assert slots["campaigns"]["reasonCode"] == "campaign_touchpoints_not_bitemporal"
    assert slots["risk"]["reasonCode"] == "risk_signals_not_bitemporal"


@pytest.mark.asyncio
async def test_provider_places_related_slots_in_required_slot_contract():
    fact = LocationRow(
        location_id="location-contract-1",
        role="primary_residence",
        precision_class="city",
        country_code="US",
        city="Boston",
        precision_state="full",
        observed_at="2026-10-24T10:00:00+00:00",
        source_observation_id=EVENT,
    )
    view = GeographicView(
        kind="entity",
        id=ENTITY,
        posture=GeographicPosture("entity", ENTITY, (fact,)),
        missing_reason=None,
    )

    class FakeLocationReader:
        async def view(self, *, tenant_id, subject_kind, subject_id):
            assert tenant_id == TENANT
            return view

    class FakeRelatedReader:
        async def related_slots(self, **kwargs):
            assert kwargs["tenant_id"] == TENANT
            assert kwargs["source_observation_id"] == EVENT
            return {
                slot_id: {
                    "state": "degraded",
                    "reasonCode": f"{slot_id}_test_source_freshness_unknown",
                    "content": {"exactJoin": True},
                    "evidenceRefs": [],
                    "freshness": {"state": "unknown"},
                    "policy": {"state": "not_evaluated_by_projection_provider"},
                    "canonicalAuthorities": [f"{slot_id}_authority"],
                }
                for slot_id in ("campaigns", "journeys", "profiles", "risk", "value")
            }

    request = ProjectionRequest(
        projectionId="geographic360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id=ENTITY),
        temporalMode="window",
    )
    context = await ProviderRegistry().build_context("geographic360", request)
    result = await Geographic360Provider(
        reader=FakeLocationReader(),
        related_authority_reader=FakeRelatedReader(),
    ).project(request, context)

    state = next(section for section in result.sections if section.id == "state")
    slots = state.content["requiredSlots"]
    assert all(slots[slot_id]["content"] == {"exactJoin": True} for slot_id in (
        "campaigns", "journeys", "profiles", "risk", "value"
    ))
    assert {"campaigns_authority", "journeys_authority", "profiles_authority", "risk_authority", "value_authority"}.issubset(
        set(state.canonicalAuthorityRefs)
    )
