"""Geographic360 provider tests (geographic360 G4.4).

Pins the geographic360 provider contract (blueprint test surface):

* valid ``ProjectionResult`` with ``summary``/``state``/``timeline``/``evidence``/
  ``findings`` over canonical location facts — never a competing store;
* precision never exceeds evidence: a fact renders only the labels it carries, a
  coordinate value is never echoed into a projection section, and a rendered
  ``precision_class`` is recomputed from what survives the render cap;
* the ``exact → city → metro`` privacy downgrade yields
  ``precision_reduced``/``suppressed`` typed states and findings — never a
  silent coarsening, never a differential-privacy claim;
* ``unknown`` subject, ``empty`` read, ``missing`` authority, ``stale``
  freshness and ``suppressed``/``degraded`` surfaces stay distinct typed states —
  never ``0``/``false``;
* missing-authority honest degradation (never raises), tenant isolation
  (fail-closed), registration gates (success / duplicate / version-mismatch /
  unknown id), read-only graph policy, no auto-register at import;
* the default reader is store-backed (G4.5): an empty store reads as an honest
  missing and out-of-kind subjects are reported as such; the full store-backed
  read of recorded facts is pinned in ``test_geographic360_location_store.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from shared.intelligence_projections.contracts import (
    ProjectionRequest,
    ProjectionSubject,
)
from shared.intelligence_projections.errors import (
    ContractVersionIncompatible,
    DuplicateProjection,
    ProjectionNotFound,
)
from shared.intelligence_projections.registry import ProviderRegistry

from graph.geographic360.provider import (
    Geographic360Provider,
    Geographic360Reader,
    GeographicActivityDensityRead,
    GeographicLocationReader,
    GeographicPosture,
    GeographicView,
    LOCATION_REQUIRED_SLOT_IDS,
    LocationRow,
    OUTPUT_SECTIONS,
    RepositoryGeographicActivityDensityReader,
    RENDER_CAP_CITY,
    RENDER_CAP_METRO,
    RENDER_CAP_NONE,
    STATE_FULL,
    STATE_PRECISION_REDUCED,
    STATE_SUPPRESSED,
    register_provider,
)

TENANT = "tenant_geo360_provider"
OTHER_TENANT = "tenant_geo360_foreign"

_NOW = datetime.now(timezone.utc)


def _days_ago(days: int) -> str:
    return (_NOW - timedelta(days=days)).isoformat()


# Recent / stale observed timestamps (stale horizon is STALE_AFTER_DAYS=180).
T_RECENT = _days_ago(5)
T_OLDER = _days_ago(90)
T_STALE = _days_ago(400)


# ── Canned view builders ─────────────────────────────────────────────────────


def _fact(
    location_id: str,
    *,
    role: str = "observed_presence",
    precision_class: str = "city",
    country_code: str | None = "US",
    region_name: str | None = None,
    region_code: str | None = None,
    city: str | None = None,
    place_name: str | None = None,
    jurisdiction_name: str | None = None,
    jurisdiction_kind: str | None = None,
    coarse_cell: str | None = None,
    coordinate_present: bool = False,
    precision_state: str = STATE_FULL,
    observed_at: str | None = T_RECENT,
    valid_to: str | None = None,
    provider: str | None = "geoip",
    source_observation_id: str | None = None,
    source_evidence_refs: tuple[str, ...] = (),
    schema_version: str | None = None,
) -> LocationRow:
    return LocationRow(
        location_id=location_id,
        role=role,
        precision_class=precision_class,
        region_type=None,
        country_code=country_code,
        region_name=region_name,
        region_code=region_code,
        city=city,
        place_name=place_name,
        jurisdiction_name=jurisdiction_name,
        jurisdiction_kind=jurisdiction_kind,
        coarse_cell=coarse_cell,
        coordinate_present=coordinate_present,
        precision_state=precision_state,
        observed_at=observed_at,
        valid_to=valid_to,
        provider=provider,
        source_observation_id=source_observation_id,
        source_evidence_refs=source_evidence_refs,
        schema_version=schema_version,
    )


def _posture(
    kind: str = "entity",
    sid: str = "ent-portland",
    facts: tuple[LocationRow, ...] = (),
) -> GeographicPosture:
    return GeographicPosture(subject_type=kind, subject_id=sid, facts=facts)


def _portland_facts() -> tuple[LocationRow, ...]:
    """A canonical WHERE history: primary residence at city + older egress."""
    return (
        _fact(
            "loc-primary",
            role="primary_residence",
            precision_class="city",
            region_name="Oregon",
            region_code="OR",
            city="Portland",
            jurisdiction_name="United States",
            jurisdiction_kind="country",
            observed_at=T_OLDER,
        ),
        _fact(
            "loc-egress",
            role="network_egress",
            precision_class="country",
            country_code="US",
            jurisdiction_name="United States",
            jurisdiction_kind="country",
            observed_at=T_RECENT,
        ),
    )


class _FakeGeoReader:
    """Strictly tenant-scoped canned reader over prebuilt GeographicViews."""

    def __init__(self, views: dict[tuple[str, str], GeographicView],
                 *, tenant: str = TENANT) -> None:
        self._views = views
        self._tenant = tenant
        self.calls: list[tuple[str, str, str]] = []

    async def view(self, *, tenant_id: str, subject_kind: str,
                   subject_id: str) -> GeographicView:
        self.calls.append((tenant_id, subject_kind, subject_id))
        if tenant_id != self._tenant:
            raise KeyError("tenant isolated")
        missing = GeographicView(
            kind=subject_kind, id=subject_id, posture=None,
            missing_reason="no geographic-plane observation",
        )
        return self._views.get((subject_kind, subject_id), missing)


class _ExplodingReader:
    """Reader that always fails — the provider must degrade, never raise."""

    async def view(self, *, tenant_id: str, subject_kind: str,
                   subject_id: str) -> GeographicView:
        raise RuntimeError("location authority unreachable")


class _FakeActivityReader:
    def __init__(self, read: GeographicActivityDensityRead) -> None:
        self.read = read
        self.calls: list[tuple[str, str, int]] = []

    async def activity_density(
        self, *, tenant_id: str, entity_id: str, limit: int
    ) -> GeographicActivityDensityRead:
        self.calls.append((tenant_id, entity_id, limit))
        return self.read


def _request(*, kind: str = "entity", sid: str = "ent-portland",
             temporal_mode: str | None = "window") -> ProjectionRequest:
    return ProjectionRequest(
        projectionId="geographic360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind=kind, id=sid),
        temporalMode=temporal_mode,
    )


async def _context(request: ProjectionRequest):
    # Fresh registry: dependency state for the sibling projections (profile360 /
    # temporal360) computes from the registry itself — echo only.
    return await ProviderRegistry().build_context("geographic360", request)


def _sections(result):
    return {s.id: s for s in result.sections}


def _dim(result, wanted: str) -> dict:
    dims = _sections(result)["state"].content["dimensions"]
    return next(d for d in dims if d["id"] == wanted)


def _view(kind: str, sid: str, posture: GeographicPosture | None,
          *, missing_reason: str | None = None) -> GeographicView:
    return GeographicView(kind=kind, id=sid, posture=posture,
                          missing_reason=missing_reason)


# ── Registration gates ────────────────────────────────────────────────────────


def test_no_auto_register_at_import():
    assert ProviderRegistry().get("geographic360") is None


def test_register_provider_registers_and_reports_source():
    registry = ProviderRegistry()
    register_provider(registry)
    assert registry.get("geographic360") is not None
    assert registry.sources() == {"geographic360": "services/api/graph/geographic360"}


def test_register_same_object_is_idempotent_different_object_duplicates():
    registry = ProviderRegistry()
    register_provider(registry)
    provider = registry.get("geographic360")
    registry.register(provider)  # same object: idempotent no-op
    with pytest.raises(DuplicateProjection):
        registry.register(Geographic360Provider(), source="x")


def test_register_version_mismatch_raises():
    class _WrongMajorProvider(Geographic360Provider):
        contract_version = "0.0.1"

    with pytest.raises(ContractVersionIncompatible):
        ProviderRegistry().register(_WrongMajorProvider())


def test_register_unknown_id_raises():
    class _BogusProvider(Geographic360Provider):
        projection_id = "not_a_projection_360"

    with pytest.raises(ProjectionNotFound):
        ProviderRegistry().register(_BogusProvider())


def test_provider_is_read_only_with_no_write_path():
    assert Geographic360Provider.graph_mutation_policy == "read_only"
    assert not any(name.startswith(("add_", "remove_", "write_", "apply_"))
                   for name in dir(Geographic360Provider))


# ── Valid geographic projection ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_entity_projection_is_a_valid_typed_result():
    posture = _posture(facts=_portland_facts())
    provider = Geographic360Provider(reader=_FakeGeoReader({
        ("entity", "ent-portland"): _view("entity", "ent-portland", posture),
    }))
    result = await provider.project(
        _request(), await _context(_request())
    )

    assert result.projectionId == "geographic360"
    assert result.tenantId == TENANT
    assert result.temporalMode == "window"
    assert [s.id for s in result.sections] == list(OUTPUT_SECTIONS)

    summary = _sections(result)["summary"]
    assert summary.state == "available"
    primary = summary.content["primary"]
    assert primary["label"] == "Portland, Oregon, US"
    assert primary["precision_class"] == "city"
    assert primary["precision_state"] == STATE_FULL
    assert summary.content["precision_cap"] is None
    assert summary.content["jurisdiction"]["name"] == "United States"
    assert summary.content["freshness"]["latest_observed_at"] == T_RECENT

    state = _sections(result)["state"]
    assert state.state == "available"
    assert _dim(result, "location_observation")["state"] == "available"
    assert _dim(result, "primary_location")["state"] == "available"
    assert _dim(result, "precision")["state"] == "available"
    assert _dim(result, "jurisdiction")["state"] == "available"
    assert _dim(result, "freshness")["state"] == "available"

    claims = result.claims
    assert any(c.id == "summary.primary_location" for c in claims)
    primary_claim = next(c for c in claims if c.id == "summary.primary_location")
    assert primary_claim.evidenceRefs and primary_claim.evidenceRefs[0].id == "location:loc-primary"
    temporal_claim = next(
        c for c in claims if c.kind == "profile_location_temporal_evidence"
    )
    assert temporal_claim.domainSlotIds == ["location_temporal"]
    assert {ref.id for ref in temporal_claim.evidenceRefs} == {
        "location:loc-primary",
        "location:loc-egress",
    }

    evidence = _sections(result)["evidence"]
    assert evidence.content["count"] == 2
    ids = {e["id"] for e in evidence.content["evidence"]}
    assert ids == {"location:loc-primary", "location:loc-egress"}
    assert all(e["source"] == "location_facts" for e in evidence.content["evidence"])
    required_slots = state.content["requiredSlots"]
    assert list(required_slots) == list(LOCATION_REQUIRED_SLOT_IDS)
    assert required_slots["place_summary"]["state"] == "available"
    assert required_slots["geo_hierarchy"]["state"] == "available"
    assert required_slots["evidence_trace"]["state"] == "available"
    for slot_id in (
        "timezone", "activity_density", "journeys", "campaigns", "profiles",
        "value", "risk", "normalization",
    ):
        assert required_slots[slot_id]["state"] == "unknown"
        assert required_slots[slot_id]["content"] is None
    assert required_slots["timezone"]["reasonCode"] == (
        "canonical_timezone_authority_not_joined"
    )
    assert all(
        slot["policy"]["state"] == "not_evaluated_by_projection_provider"
        for slot in required_slots.values()
    )
    assert primary_claim.domainSlotIds == ["place_summary"]
    assert next(c for c in claims if c.id == "evidence.location_fact_trace").domainSlotIds == [
        "evidence_trace"
    ]


@pytest.mark.asyncio
async def test_required_slots_preserve_source_evidence_and_temporal_provenance():
    row = _fact(
        "loc-source-linked",
        role="declared_address",
        precision_class="city",
        country_code="US",
        region_name="Oregon",
        city="Portland",
        observed_at=T_RECENT,
        provider="context_capsule",
        source_observation_id="capsule-observation-17",
        source_evidence_refs=("evidence:source-17",),
    )
    posture = _posture(facts=(row,))
    provider = Geographic360Provider(reader=_FakeGeoReader({
        ("entity", "ent-portland"): _view("entity", "ent-portland", posture),
    }))
    result = await provider.project(
        _request(), await _context(_request())
    )

    slots = _sections(result)["state"].content["requiredSlots"]
    place = slots["place_summary"]
    assert place["content"]["source_observation_id"] == "capsule-observation-17"
    assert place["content"]["source_evidence_refs"] == ["evidence:source-17"]
    assert place["content"]["currentPresenceAsserted"] is False
    assert place["freshness"]["observedAt"] == T_RECENT
    trace = slots["evidence_trace"]["content"]["sourceEvidenceRefs"][0]
    assert trace == {
        "locationId": "loc-source-linked",
        "sourceObservationId": "capsule-observation-17",
        "evidenceRefs": ["evidence:source-17"],
        "sourceProvider": "context_capsule",
    }
    normalization = slots["normalization"]
    assert normalization["state"] == "degraded"
    assert normalization["reasonCode"] == (
        "location_normalization_algorithm_lineage_unavailable"
    )
    assert normalization["content"]["lineageCompleteness"] == "partial"
    assert normalization["content"]["entries"] == [
        {
            "locationFactId": "loc-source-linked",
            "sourceLinkState": "linked",
            "sourceObservationId": "capsule-observation-17",
            "sourceProvider": "context_capsule",
            "sourceEvidenceRefs": ["evidence:source-17"],
            "sourceEvidenceRefsTruncated": False,
            "locationFactSchemaVersion": None,
            "sourceObservedAt": T_RECENT,
        }
    ]
    assert normalization["freshness"] == {
        "state": "unknown",
        "reasonCode": "location_normalization_timestamp_unavailable",
    }
    assert normalization["evidenceRefs"] == [
        {
            "id": "location:loc-source-linked",
            "type": "relationship",
            "source": "location_facts",
            "observedAt": T_RECENT,
            "confidence": None,
            "uri": None,
        }
    ]
    normalization_claim = next(
        claim
        for claim in result.claims
        if claim.id == "normalization.location_fact_lineage"
    )
    assert normalization_claim.domainSlotIds == ["normalization"]
    assert "Portland" not in str(normalization)
    assert "coarse_cell" not in str(normalization)


@pytest.mark.asyncio
async def test_timezone_is_not_inferred_from_exact_coordinates_or_place_labels():
    # A precise location fact is still not a timezone mapping. The provider
    # must not convert coordinates or a recognizable city label into an IANA
    # zone without an exact canonical/source-reported timezone authority.
    row = _fact(
        "loc-new-york-precise",
        precision_class="precise",
        country_code="US",
        region_name="New York",
        region_code="NY",
        city="New York City",
        coordinate_present=True,
        observed_at=T_RECENT,
        provider="canonical_location_facts",
        source_observation_id="observation-location-22",
        source_evidence_refs=("evidence:location-22",),
    )
    posture = _posture(facts=(row,))
    provider = Geographic360Provider(reader=_FakeGeoReader({
        ("entity", "ent-portland"): _view("entity", "ent-portland", posture),
    }))
    request = _request()

    result = await provider.project(request, await _context(request))

    slot = _sections(result)["state"].content["requiredSlots"]["timezone"]
    assert slot["state"] == "unknown"
    assert slot["reasonCode"] == "canonical_timezone_authority_not_joined"
    assert slot["content"] is None
    assert slot["evidenceRefs"] == []
    assert not any("timezone" in claim.domainSlotIds for claim in result.claims)
    assert "America/New_York" not in str(result.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_location_fact_schema_version_alone_is_not_normalization_lineage():
    row = _fact(
        "loc-schema-only",
        provider="geoip",
        source_observation_id=None,
        source_evidence_refs=(),
        schema_version="1.0.0",
    )
    posture = _posture(facts=(row,))
    provider = Geographic360Provider(
        reader=_FakeGeoReader({
            ("entity", "ent-portland"): _view("entity", "ent-portland", posture),
        })
    )
    request = _request()

    result = await provider.project(request, await _context(request))

    normalization = _sections(result)["state"].content["requiredSlots"]["normalization"]
    assert normalization["state"] == "unknown"
    assert normalization["content"] is None
    assert normalization["reasonCode"] == "location_normalization_lineage_unavailable"
    assert not any(
        claim.domainSlotIds == ["normalization"] for claim in result.claims
    )


@pytest.mark.asyncio
async def test_normalization_lineage_bounds_source_entries_and_reports_truncation():
    facts = tuple(
        _fact(
            f"loc-lineage-{index}",
            source_observation_id=f"observation-{index}",
            observed_at=T_RECENT,
        )
        for index in range(101)
    )
    posture = _posture(facts=facts)
    provider = Geographic360Provider(reader=_FakeGeoReader({
        ("entity", "ent-portland"): _view("entity", "ent-portland", posture),
    }))
    request = _request()

    result = await provider.project(request, await _context(request))

    normalization = _sections(result)["state"].content["requiredSlots"]["normalization"]
    content = normalization["content"]
    assert normalization["state"] == "degraded"
    assert content["sourceLinkedFactCount"] == 101
    assert content["listedSourceLinkedFactCount"] == 100
    assert content["omittedSourceLinkedFactCount"] == 1
    assert content["sourceLinkedFactListTruncated"] is True
    assert len(content["entries"]) == 100
    assert len(normalization["evidenceRefs"]) == 100


@pytest.mark.asyncio
async def test_activity_density_is_exact_entity_temporal_only_and_evidence_backed():
    posture = _posture(facts=_portland_facts())
    activity_reader = _FakeActivityReader(
        GeographicActivityDensityRead(
            rows=(
                {
                    "id": "gold-activity-1",
                    "tenant_id": TENANT,
                    "entity_id": "ent-portland",
                    "value": {},
                    "dimensions": {
                        "day_of_week": "monday",
                        "hour_utc": 14,
                        "activity_count": 7,
                        # These values are intentionally not a location authority.
                        "timezone": "America/Los_Angeles",
                        "city": "Portland",
                        "coarse_cell": "8628h3cell",
                        "latitude": 45.5,
                    },
                    "materialized_at": T_RECENT,
                    "lineage_id": "gold-lineage-1",
                },
            ),
            available=True,
            complete=True,
        )
    )
    provider = Geographic360Provider(
        reader=_FakeGeoReader({
            ("entity", "ent-portland"): _view("entity", "ent-portland", posture),
        }),
        activity_reader=activity_reader,
    )
    request = _request()
    result = await provider.project(request, await _context(request))

    slot = _sections(result)["state"].content["requiredSlots"]["activity_density"]
    assert activity_reader.calls == [(TENANT, "ent-portland", 200)]
    assert slot["state"] == "degraded"
    assert slot["reasonCode"] == "temporal_activity_density_not_linked_to_place"
    assert slot["content"]["locationCorrelationState"] == "unknown"
    assert slot["content"]["spatialDensityAsserted"] is False
    assert slot["content"]["points"] == [
        {
            "dayOfWeek": "monday",
            "hourUtc": 14,
            "activityCount": 7,
            "materializedAt": datetime.fromisoformat(T_RECENT).isoformat(),
        }
    ]
    assert {ref["source"] for ref in slot["evidenceRefs"]} == {
        "gold_temporal_heatmap"
    }
    assert "America/Los_Angeles" not in str(slot)
    assert "Portland" not in str(slot)
    assert "8628h3cell" not in str(slot)
    assert "latitude" not in str(slot)
    timezone_slot = _sections(result)["state"].content["requiredSlots"]["timezone"]
    assert timezone_slot["state"] == "unknown"
    assert timezone_slot["reasonCode"] == "canonical_timezone_authority_not_joined"
    assert timezone_slot["content"] is None
    assert timezone_slot["evidenceRefs"] == []
    claim = next(claim for claim in result.claims if claim.id == "activity.temporal_density")
    assert claim.domainSlotIds == ["activity_density"]
    assert claim.evidenceRefs[0].source == "gold_temporal_heatmap"
    assert "no timezone is inferred" in claim.claims[0]


@pytest.mark.asyncio
async def test_activity_density_drops_foreign_rows_and_marks_partial_coverage():
    activity_reader = _FakeActivityReader(
        GeographicActivityDensityRead(
            rows=(
                {
                    "id": "gold-activity-1",
                    "tenant_id": TENANT,
                    "entity_id": "ent-portland",
                    "dimensions": {
                        "day_of_week": "monday",
                        "hour_utc": 14,
                        "activity_count": 7,
                    },
                    "materialized_at": T_RECENT,
                },
                {
                    "id": "foreign-activity",
                    "tenant_id": OTHER_TENANT,
                    "entity_id": "ent-portland",
                    "dimensions": {
                        "day_of_week": "tuesday",
                        "hour_utc": 10,
                        "activity_count": 99,
                    },
                },
            ),
            available=True,
            complete=True,
        )
    )
    provider = Geographic360Provider(
        reader=_FakeGeoReader({
            ("entity", "ent-portland"): _view(
                "entity", "ent-portland", _posture(facts=_portland_facts())
            ),
        }),
        activity_reader=activity_reader,
    )
    request = _request()

    result = await provider.project(request, await _context(request))

    slot = _sections(result)["state"].content["requiredSlots"]["activity_density"]
    assert slot["state"] == "degraded"
    assert slot["reasonCode"] == "temporal_activity_density_read_incomplete"
    assert slot["content"]["pointCountComplete"] is False
    assert [point["activityCount"] for point in slot["content"]["points"]] == [7]
    assert "foreign-activity" not in str(slot)


@pytest.mark.asyncio
async def test_repository_activity_density_reader_uses_tenant_and_entity_and_drops_legacy(
    monkeypatch,
):
    from repositories import lake

    class _GoldRows:
        async def get_metrics(self, entity_id: str, *, tenant_id: str):
            assert entity_id == "ent-portland"
            assert tenant_id == TENANT
            return [
                {"id": "legacy", "tenant_id": "", "entity_id": entity_id},
                {"id": "current", "tenant_id": TENANT, "entity_id": entity_id},
            ]

    monkeypatch.setattr(lake, "gold_temporal_heatmap", _GoldRows())
    read = await RepositoryGeographicActivityDensityReader().activity_density(
        tenant_id=TENANT, entity_id="ent-portland", limit=20
    )

    assert read.available is True
    assert read.complete is True
    assert read.scope_mismatch is False
    assert read.rows == ({"id": "current", "tenant_id": TENANT, "entity_id": "ent-portland"},)


@pytest.mark.asyncio
async def test_context_tenant_mismatch_does_not_query_location_reader():
    reader = _FakeGeoReader({
        ("entity", "ent-portland"): _view(
            "entity", "ent-portland", _posture(facts=_portland_facts())
        ),
    })
    provider = Geographic360Provider(reader=reader)
    request = _request()
    context = await _context(request)
    mismatched_context = context.model_copy(update={"tenantId": OTHER_TENANT})

    result = await provider.project(request, mismatched_context)

    assert reader.calls == []
    assert _sections(result)["summary"].state == "unknown"
    assert _sections(result)["state"].content["requiredSlots"]["place_summary"][
        "state"
    ] == "unknown"


@pytest.mark.asyncio
async def test_mismatched_reader_subject_fails_closed():
    provider = Geographic360Provider(reader=_FakeGeoReader({
        ("entity", "ent-portland"): _view(
            "entity", "ent-other", _posture("entity", "ent-other", _portland_facts())
        ),
    }))

    result = await provider.project(_request(), await _context(_request()))

    assert _sections(result)["summary"].state == "unknown"
    assert _sections(result)["summary"].content["primary"] is None
    assert _sections(result)["state"].content["requiredSlots"]["evidence_trace"][
        "state"
    ] == "unknown"


@pytest.mark.asyncio
async def test_unparseable_observation_time_degrades_freshness_without_raising():
    posture = _posture(sid="ent-x", facts=(
        _fact("loc-bad-time", country_code="US", observed_at="not-an-iso-time"),
    ))
    provider = Geographic360Provider(reader=_FakeGeoReader({
        ("entity", "ent-x"): _view("entity", "ent-x", posture),
    }))

    result = await provider.project(
        _request(sid="ent-x"), await _context(_request(sid="ent-x"))
    )

    assert _dim(result, "freshness")["state"] == "degraded"
    assert _dim(result, "freshness")["reason"] == "location_observation_timestamp_unparseable"
    assert _sections(result)["state"].content["requiredSlots"]["place_summary"][
        "freshness"
    ]["state"] == "degraded"


@pytest.mark.asyncio
async def test_timeline_is_ordered_newest_first_and_grounded():
    posture = _posture(facts=_portland_facts())
    provider = Geographic360Provider(reader=_FakeGeoReader({
        ("entity", "ent-portland"): _view("entity", "ent-portland", posture),
    }))
    result = await provider.project(
        _request(), await _context(_request())
    )
    timeline = _sections(result)["timeline"]
    assert timeline.state == "available"
    ats = [e["at"] for e in timeline.content["events"]]
    assert ats == sorted(ats, reverse=True)
    assert ats[0] == T_RECENT  # newest first
    event = timeline.content["events"][1]
    assert event["kind"] == "location_fact"
    assert event["role"] == "primary_residence"
    assert event["precision_state"] == STATE_FULL
    assert event["location_id"] == "loc-primary"


# ── Precision never exceeds evidence ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_precision_never_exceeds_evidence_and_no_coordinate_value_is_echoed():
    # Evidence is a precise coordinate + coarse cell with NO city/region label.
    posture = _posture(sid="ent-x", facts=(
        _fact(
            "loc-precise",
            role="observed_presence",
            precision_class="precise",
            country_code="US",
            coarse_cell="8628f0007ffffff",
            coordinate_present=True,
        ),
    ))
    provider = Geographic360Provider(reader=_FakeGeoReader({
        ("entity", "ent-x"): _view("entity", "ent-x", posture),
    }))
    result = await provider.project(
        _request(sid="ent-x"), await _context(_request(sid="ent-x"))
    )

    summary = _sections(result)["summary"]
    assert summary.state == "available"
    primary = summary.content["primary"]
    # It may claim the evidence's precision class, but only the coarse country
    # label renders — the cell is shown, the coordinate VALUE never is.
    assert primary["precision_class"] == "precise"
    assert primary["country_code"] == "US"
    assert primary["coarse_cell"] == "8628f0007ffffff"
    # No coordinate value ever enters a projection section (privacy shape): the
    # row only carries a boolean presence flag, never lat/lon/radius.
    assert primary["coordinate_present"] is True
    assert not {"latitude", "longitude", "accuracy_radius_meters"} & set(primary)
    dumped = result.model_dump_json()
    assert "latitude" not in dumped and "longitude" not in dumped


# ── exact → city → metro downgrade (explicit, never silent) ──────────────────


@pytest.mark.asyncio
async def test_city_cap_downgrades_exact_to_city_precision_reduced():
    posture = _posture(sid="ent-x", facts=(
        _fact(
            "loc-exact",
            role="observed_presence",
            precision_class="precise",
            region_name="Oregon",
            region_code="OR",
            city="Portland",
            coarse_cell="8628f0007ffffff",
            coordinate_present=True,
        ),
    ))
    provider = Geographic360Provider(
        reader=_FakeGeoReader({("entity", "ent-x"): _view("entity", "ent-x", posture)}),
        render_cap=RENDER_CAP_CITY,
    )
    result = await provider.project(
        _request(sid="ent-x"), await _context(_request(sid="ent-x"))
    )

    summary = _sections(result)["summary"]
    assert summary.state == "degraded"
    assert summary.content["precision_cap"] == RENDER_CAP_CITY
    primary = summary.content["primary"]
    # city survives; coordinate + coarse cell are dropped and never echoed.
    assert primary["city"] == "Portland"
    assert primary["precision_class"] == "city"
    assert primary["precision_state"] == STATE_PRECISION_REDUCED
    assert primary["coordinate_present"] is False
    assert primary["coarse_cell"] is None
    dumped = result.model_dump_json()
    assert "8628f0007ffffff" not in dumped
    assert _dim(result, "precision")["state"] == "degraded"

    findings = _sections(result)["findings"].content["findings"]
    assert any(f["code"] == "geographic360.precision_reduced" for f in findings)


@pytest.mark.asyncio
async def test_metro_cap_downgrades_city_to_region_granularity():
    posture = _posture(sid="ent-x", facts=(
        _fact(
            "loc-exact",
            role="observed_presence",
            precision_class="precise",
            region_name="Oregon",
            region_code="OR",
            city="Portland",
            jurisdiction_name="United States",
            jurisdiction_kind="country",
            coarse_cell="8628f0007ffffff",
            coordinate_present=True,
        ),
    ))
    provider = Geographic360Provider(
        reader=_FakeGeoReader({("entity", "ent-x"): _view("entity", "ent-x", posture)}),
        render_cap=RENDER_CAP_METRO,
    )
    result = await provider.project(
        _request(sid="ent-x"), await _context(_request(sid="ent-x"))
    )

    summary = _sections(result)["summary"]
    assert summary.state == "degraded"
    assert summary.content["precision_cap"] == RENDER_CAP_METRO
    primary = summary.content["primary"]
    # Metro (admin/metro region) survives; the city label is gone — a coarsened
    # render is never mistaken for an exact one.
    assert primary["city"] is None
    assert primary["region_name"] == "Oregon"
    assert primary["label"] == "Oregon, US"
    assert primary["precision_class"] == "region"
    assert primary["precision_state"] == STATE_PRECISION_REDUCED
    dumped = result.model_dump_json()
    assert "Portland" not in dumped
    assert "8628f0007ffffff" not in dumped
    assert _dim(result, "precision")["state"] == "degraded"


@pytest.mark.asyncio
async def test_no_cap_leaves_full_evidence_alone():
    posture = _posture(facts=_portland_facts())
    provider = Geographic360Provider(reader=_FakeGeoReader({
        ("entity", "ent-portland"): _view("entity", "ent-portland", posture),
    }))
    assert provider._cap == RENDER_CAP_NONE
    result = await provider.project(
        _request(), await _context(_request())
    )
    primary = _sections(result)["summary"].content["primary"]
    assert primary["precision_state"] == STATE_FULL
    assert _sections(result)["summary"].state == "available"


@pytest.mark.asyncio
async def test_invalid_cap_falls_back_to_evidence_only():
    provider = Geographic360Provider(reader=_FakeGeoReader({}), render_cap="bogus")
    assert provider._cap == RENDER_CAP_NONE


# ── Suppression (authority blanked — never re-leaked) ─────────────────────────


@pytest.mark.asyncio
async def test_suppressed_facts_render_coarse_only_and_stay_suppressed():
    posture = _posture(sid="ent-x", facts=(
        _fact(
            "loc-suppressed",
            role="primary_residence",
            precision_class="precise",
            country_code="US",
            region_name="Oregon",
            region_code="OR",
            city="Portland",
            jurisdiction_name="United States",
            jurisdiction_kind="country",
            coarse_cell="8628f0007ffffff",
            coordinate_present=True,
            precision_state=STATE_SUPPRESSED,
        ),
    ))
    provider = Geographic360Provider(reader=_FakeGeoReader({
        ("entity", "ent-x"): _view("entity", "ent-x", posture),
    }))
    result = await provider.project(
        _request(sid="ent-x"), await _context(_request(sid="ent-x"))
    )

    summary = _sections(result)["summary"]
    assert summary.state == "suppressed"
    assert summary.content["suppressed_count"] == 1
    primary = summary.content["primary"]
    # Country-level only; city/region/cell/coordinate are never re-leaked.
    assert primary["country_code"] == "US"
    assert primary["city"] is None
    assert primary["region_name"] is None
    assert primary["coarse_cell"] is None
    assert primary["coordinate_present"] is False
    assert primary["precision_state"] == STATE_SUPPRESSED
    assert primary["precision_class"] == "country"
    dumped = result.model_dump_json()
    assert "Portland" not in dumped and "8628f0007ffffff" not in dumped

    assert _dim(result, "suppression")["state"] == "suppressed"
    findings = _sections(result)["findings"].content["findings"]
    assert any(f["code"] == "geographic360.suppressed" for f in findings)
    # A suppressed render claims no differential privacy.
    assert "differential" not in dumped.lower() and "privacy" not in dumped.lower()


# ── Typed honesty states ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_subject_is_never_zero():
    provider = Geographic360Provider(reader=_FakeGeoReader({}))
    result = await provider.project(
        _request(sid="ent-ghost"), await _context(_request(sid="ent-ghost"))
    )

    summary = _sections(result)["summary"]
    assert summary.state == "unknown"
    assert summary.content["primary"] is None
    assert summary.content["location_count"] == 0
    assert _dim(result, "subject")["state"] == "unknown"
    state = _sections(result)["state"]
    assert state.state == "unknown"
    claims = result.claims
    assert any(c.id == "summary.unknown" and c.evidenceRefs == [] for c in claims)
    assert any("no geographic-plane observation" in w for w in (summary.warnings or []))


@pytest.mark.asyncio
async def test_empty_authority_read_is_empty_not_missing_or_zero():
    provider = Geographic360Provider(reader=_FakeGeoReader({
        ("entity", "ent-x"): _view(
            "entity", "ent-x", _posture(sid="ent-x", facts=())
        ),
    }))
    result = await provider.project(
        _request(sid="ent-x"), await _context(_request(sid="ent-x"))
    )
    summary = _sections(result)["summary"]
    assert summary.state == "empty"
    assert _dim(result, "location_observation")["state"] == "empty"
    assert _sections(result)["timeline"].state == "empty"
    assert _sections(result)["evidence"].state == "empty"


@pytest.mark.asyncio
async def test_stale_freshness_is_typed_stale():
    posture = _posture(sid="ent-x", facts=(
        _fact("loc-old", role="observed_presence", precision_class="country",
              country_code="US", observed_at=T_STALE),
    ))
    provider = Geographic360Provider(reader=_FakeGeoReader({
        ("entity", "ent-x"): _view("entity", "ent-x", posture),
    }))
    result = await provider.project(
        _request(sid="ent-x"), await _context(_request(sid="ent-x"))
    )
    assert _dim(result, "freshness")["state"] == "stale"
    assert _sections(result)["state"].content["requiredSlots"]["place_summary"][
        "state"
    ] == "stale"
    findings = _sections(result)["findings"].content["findings"]
    assert any(f["code"] == "geographic360.stale_location" for f in findings)


@pytest.mark.asyncio
async def test_expired_fact_is_stale_even_when_recently_observed():
    posture = _posture(
        sid="ent-x",
        facts=(
            _fact(
                "loc-expired",
                country_code="US",
                observed_at=T_RECENT,
                valid_to=_days_ago(1),
            ),
        ),
    )
    provider = Geographic360Provider(reader=_FakeGeoReader({
        ("entity", "ent-x"): _view("entity", "ent-x", posture),
    }))

    result = await provider.project(
        _request(sid="ent-x"), await _context(_request(sid="ent-x"))
    )

    slot = _sections(result)["state"].content["requiredSlots"]["place_summary"]
    assert slot["state"] == "stale"
    assert slot["freshness"]["reasonCode"] == "location_fact_past_valid_to"


@pytest.mark.asyncio
async def test_reader_explosion_degrades_never_raises():
    provider = Geographic360Provider(reader=_ExplodingReader())
    result = await provider.project(
        _request(), await _context(_request())
    )
    assert result.degradedReasons == []
    summary = _sections(result)["summary"]
    assert summary.state == "unknown"
    assert any("unavailable" in w for w in (summary.warnings or []))


@pytest.mark.asyncio
async def test_foreign_tenant_is_fail_closed():
    views = {
        ("entity", "ent-portland"): _view("entity", "ent-portland", _posture(facts=_portland_facts())),
    }
    provider = Geographic360Provider(reader=_FakeGeoReader(views, tenant=TENANT))
    request = _request()
    foreign = request.model_copy(update={"tenantId": OTHER_TENANT})
    result = await provider.project(foreign, await _context(foreign))
    # A cross-tenant read degrades to unknown — never a leak of the other
    # tenant's Portland facts.
    summary = _sections(result)["summary"]
    assert summary.state == "unknown"
    assert summary.content["primary"] is None
    assert any("unavailable" in w for w in (summary.warnings or []))


@pytest.mark.asyncio
async def test_out_of_kind_subject_is_reported_not_fabricated():
    provider = Geographic360Provider(reader=GeographicLocationReader())
    result = await provider.project(
        _request(kind="cluster", sid="cluster-1"),
        await _context(_request(kind="cluster", sid="cluster-1")),
    )
    summary = _sections(result)["summary"]
    assert summary.state == "unknown"
    assert any("not a geographic360 subject" in w for w in (summary.warnings or []))


# ── Default reader honesty ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_default_reader_is_honest_missing_when_store_has_no_facts():
    # Store-backed (G4.5): the default reader queries the canonical store, so an
    # in-kind subject with no recorded fact still reads as an honest missing.
    reader = GeographicLocationReader()
    view = await reader.view(tenant_id=TENANT, subject_kind="entity",
                             subject_id="ent-portland")
    assert view.posture is None
    assert "no recorded location facts" in (view.missing_reason or "")


# ── Conflicts / findings ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_conflicting_country_and_jurisdiction_surface_findings():
    posture = _posture(sid="ent-x", facts=(
        _fact("loc-a", role="observed_presence", precision_class="country",
              country_code="US", jurisdiction_name="United States",
              jurisdiction_kind="country", observed_at=T_RECENT),
        _fact("loc-b", role="trip_destination", precision_class="country",
              country_code="CA", jurisdiction_name="Canada",
              jurisdiction_kind="country", observed_at=T_OLDER),
    ))
    provider = Geographic360Provider(reader=_FakeGeoReader({
        ("entity", "ent-x"): _view("entity", "ent-x", posture),
    }))
    result = await provider.project(
        _request(sid="ent-x"), await _context(_request(sid="ent-x"))
    )
    findings = {f["code"] for f in _sections(result)["findings"].content["findings"]}
    assert "geographic360.conflicting_country" in findings
    assert "geographic360.jurisdiction_conflict" in findings
