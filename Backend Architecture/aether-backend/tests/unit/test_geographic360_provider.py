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

from services.geographic360.provider import (
    Geographic360Provider,
    Geographic360Reader,
    GeographicLocationReader,
    GeographicPosture,
    GeographicView,
    LocationRow,
    OUTPUT_SECTIONS,
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
    provider: str | None = "geoip",
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
        provider=provider,
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
    assert registry.sources() == {"geographic360": "services/geographic360"}


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

    evidence = _sections(result)["evidence"]
    assert evidence.content["count"] == 2
    ids = {e["id"] for e in evidence.content["evidence"]}
    assert ids == {"location:loc-primary", "location:loc-egress"}
    assert all(e["source"] == "location_facts" for e in evidence.content["evidence"])


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
    posture = _posture(facts=(
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
    posture = _posture(facts=(
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
    posture = _posture(facts=(
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
    posture = _posture(facts=(
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
        ("entity", "ent-x"): _view("entity", "ent-x", _posture(facts=())),
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
    posture = _posture(facts=(
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
    findings = _sections(result)["findings"].content["findings"]
    assert any(f["code"] == "geographic360.stale_location" for f in findings)


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
    posture = _posture(facts=(
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
