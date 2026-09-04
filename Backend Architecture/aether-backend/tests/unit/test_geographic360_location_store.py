"""Canonical location-fact store + store-backed default reader (geographic360 G4.5).

G4.5 ships the ONE canonical location-fact repository (``location_facts`` —
in-memory local / asyncpg prod, the same ``BaseRepository`` backend the
population plane uses) that the geographic360 provider reads through its default
:class:`GeographicLocationReader`. This suite pins the store contract:

* ``record`` is an idempotent *internal* write (no public route/consent
  surface); re-recording a row replaces it with a fresh active snapshot;
* ``active_facts_for_subject`` is tenant-scoped and returns active facts
  oldest -> newest; revoked rows are invisible to reads;
* ``revoke`` is a governed soft-revoke (lifecycle_state ``revoked`` + stamps,
  never a hard delete) that is idempotent and fail-closed across tenants;
* ``revoke_facts_for_subject`` is the DSR-erasure receipt source — it returns
  the number of governed revokes executed for one subject within one tenant;
* the store-backed default reader maps stored facts onto the projection posture
  (coordinates never echoed — presence flag only), answers an honest ``missing``
  for a subject with no recorded fact, and reports out-of-kind subjects as such.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402

from services.geo.location_facts import (  # noqa: E402
    LOCATION_FACT_ACTIVE,
    LOCATION_FACT_REVOKED,
    LocationFactRepository,
    location_fact_repo,
)
from services.geographic360.provider import (  # noqa: E402
    GeographicLocationReader,
)

from shared.geo.models import (  # noqa: E402
    Jurisdiction,
    LocationFact,
    Region,
)

pytestmark = pytest.mark.asyncio

TENANT_A = "tenant_geo_location_store_a"
TENANT_B = "tenant_geo_location_store_b"

_NOW = datetime.now(timezone.utc)


def _days_ago(days: int) -> datetime:
    return _NOW - timedelta(days=days)


@pytest.fixture(autouse=True)
def _isolate():
    """Each test starts from an empty store (and leaves it that way)."""
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _fact(
    location_id: str,
    *,
    tenant_id: str = TENANT_A,
    subject_id: str = "ent-portland",
    role: str = "primary_residence",
    observed_at: datetime = _days_ago(5),
    region_type: str = "city",
    place_name: str = "Portland",
    geo_reference: str = "OR",
    country_code: str = "US",
    provider: str = "geoip",
) -> LocationFact:
    return LocationFact(
        location_id=location_id,
        tenant_id=tenant_id,
        subject_type="entity",
        subject_id=subject_id,
        role=role,
        precision_class="city" if place_name or region_type == "city" else "country",
        region=Region(
            region_id=f"region:{location_id}",
            region_type=region_type,
            name=place_name,
            country_code=country_code,
            geo_reference=geo_reference,
        ),
        jurisdiction=Jurisdiction(
            jurisdiction_id=f"jurisdiction:{location_id}",
            name="United States",
            kind="country",
            iso_codes=("US",),
        ),
        observed_at=observed_at,
        provider=provider,
    )


# ── record / read: tenant-scoped, active-only, oldest -> newest ────────────────


async def test_record_and_active_facts_are_tenant_scoped_and_ordered():
    repo = LocationFactRepository()
    older = await repo.record(_fact("loc-older", observed_at=_days_ago(20)))
    newer = await repo.record(_fact("loc-newer", observed_at=_days_ago(2)))
    assert older["lifecycle_state"] == LOCATION_FACT_ACTIVE

    # Another tenant's fact for the SAME subject, and a different subject in A.
    await repo.record(_fact("loc-foreign", tenant_id=TENANT_B, subject_id="ent-portland"))
    await repo.record(_fact("loc-other-subject", subject_id="ent-other"))

    rows = await repo.active_facts_for_subject(TENANT_A, "entity", "ent-portland")
    assert [r["location_id"] for r in rows] == ["loc-older", "loc-newer"]
    assert all(r["lifecycle_state"] == LOCATION_FACT_ACTIVE for r in rows)

    # Tenant isolation: B sees only B's row; A never leaks B's fact.
    assert [
        r["location_id"]
        for r in await repo.active_facts_for_subject(TENANT_B, "entity", "ent-portland")
    ] == ["loc-foreign"]
    assert [
        r["location_id"]
        for r in await repo.active_facts_for_subject(TENANT_A, "entity", "ent-other")
    ] == ["loc-other-subject"]
    assert await repo.active_facts_for_subject("tenant_geo_unused", "entity", "ent-portland") == []


async def test_record_is_idempotent_and_re_recording_revives():
    repo = LocationFactRepository()
    await repo.record(_fact("loc-a", observed_at=_days_ago(3)))
    await repo.record(_fact("loc-a", observed_at=_days_ago(1)))  # same id, newer
    rows = await repo.active_facts_for_subject(TENANT_A, "entity", "ent-portland")
    assert len(rows) == 1
    assert rows[0]["location_id"] == "loc-a"

    # Soft-revoke, then re-record: the row is active again with no stale
    # revoke envelope surviving.
    await repo.revoke("loc-a", actor_id="dsr_erasure_job", reason="dsr_erasure")
    assert await repo.active_facts_for_subject(TENANT_A, "entity", "ent-portland") == []
    await repo.record(_fact("loc-a", observed_at=_days_ago(1)))
    rows = await repo.active_facts_for_subject(TENANT_A, "entity", "ent-portland")
    assert len(rows) == 1
    assert rows[0]["lifecycle_state"] == LOCATION_FACT_ACTIVE
    assert "revoked_at" not in rows[0]


# ── governed soft-revoke ───────────────────────────────────────────────────────


async def test_revoke_is_soft_idempotent_and_stamps_governance():
    repo = LocationFactRepository()
    await repo.record(_fact("loc-a"))
    revoked = await repo.revoke(
        "loc-a", actor_id="dsr_erasure_job", reason="dsr_erasure"
    )
    assert revoked is not None
    assert revoked["lifecycle_state"] == LOCATION_FACT_REVOKED
    assert revoked["revoked_by"] == "dsr_erasure_job"
    assert revoked["revoke_reason"] == "dsr_erasure"
    assert revoked["revoked_at"]

    # Invisible to reads but still present (never a hard delete).
    assert await repo.active_facts_for_subject(TENANT_A, "entity", "ent-portland") == []
    row = await repo.find_by_id("loc-a")
    assert row["lifecycle_state"] == LOCATION_FACT_REVOKED

    # Idempotent: a second revoke is a no-op; an absent id returns None.
    again = await repo.revoke("loc-a", actor_id="dsr_erasure_job", reason="dsr_erasure")
    assert again is not None and again["lifecycle_state"] == LOCATION_FACT_REVOKED
    assert await repo.revoke("loc-absent", actor_id="x", reason="r") is None


async def test_revoke_is_fail_closed_across_tenants():
    repo = LocationFactRepository()
    await repo.record(_fact("loc-a", tenant_id=TENANT_B))
    # Revoking by id through the WRONG tenant leaves the row untouched.
    foreign = await repo.revoke(
        "loc-a", actor_id="dsr_erasure_job", reason="dsr_erasure", tenant_id=TENANT_A
    )
    assert foreign is None
    row = await repo.find_by_id("loc-a")
    assert row["lifecycle_state"] == LOCATION_FACT_ACTIVE


# ── DSR erasure receipt (revoke_facts_for_subject) ─────────────────────────────


async def test_revoke_facts_for_subject_receipt_is_real_and_tenant_scoped():
    repo = LocationFactRepository()
    await repo.record(_fact("loc-a", observed_at=_days_ago(10)))
    await repo.record(_fact("loc-b", observed_at=_days_ago(1)))
    await repo.record(_fact("loc-b-foreign", tenant_id=TENANT_B))
    await repo.record(_fact("loc-other", subject_id="ent-other"))

    receipt = await repo.revoke_facts_for_subject(
        TENANT_A, "entity", "ent-portland",
        actor_id="dsr_erasure_job", reason="dsr_erasure",
    )
    assert receipt == 2  # the store's OWN count — A's two facts

    # A's subject is fully revoked; B's row and A's OTHER subject are untouched.
    assert await repo.active_facts_for_subject(TENANT_A, "entity", "ent-portland") == []
    assert [
        r["location_id"]
        for r in await repo.active_facts_for_subject(TENANT_B, "entity", "ent-portland")
    ] == ["loc-b-foreign"]
    assert [
        r["location_id"]
        for r in await repo.active_facts_for_subject(TENANT_A, "entity", "ent-other")
    ] == ["loc-other"]

    # Idempotent: an already-erased subject revokes 0 more rows.
    assert await repo.revoke_facts_for_subject(
        TENANT_A, "entity", "ent-portland",
        actor_id="dsr_erasure_job", reason="dsr_erasure",
    ) == 0


# ── store-backed default reader ────────────────────────────────────────────────


async def test_default_reader_projects_recorded_facts_store_backed():
    await location_fact_repo.record(_fact("loc-primary", observed_at=_days_ago(5)))
    await location_fact_repo.record(
        _fact("loc-egress", role="network_egress", observed_at=_days_ago(1))
    )

    reader = GeographicLocationReader()
    view = await reader.view(
        tenant_id=TENANT_A, subject_kind="entity", subject_id="ent-portland"
    )
    assert view.missing_reason is None
    assert view.posture is not None
    assert view.posture.subject_type == "entity"
    assert view.posture.subject_id == "ent-portland"
    # Oldest -> newest (store order is authoritative, not read order).
    ids = [f.location_id for f in view.posture.facts]
    assert ids == ["loc-primary", "loc-egress"]

    row = view.posture.facts[0]
    assert row.role == "primary_residence"
    # Flat labels lifted from the nested Region/Jurisdiction — no invention.
    assert row.city == "Portland"
    assert row.region_code == "OR"
    assert row.country_code == "US"
    assert row.jurisdiction_name == "United States"
    assert row.jurisdiction_kind == "country"
    assert row.provider == "geoip"
    # A coordinate value is never echoed — presence only (and none was stored).
    assert row.coordinate_present is False


async def test_default_reader_is_tenant_scoped():
    await location_fact_repo.record(_fact("loc-a", tenant_id=TENANT_A))
    await location_fact_repo.record(_fact("loc-b", tenant_id=TENANT_B))

    reader = GeographicLocationReader()
    view_a = await reader.view(
        tenant_id=TENANT_A, subject_kind="entity", subject_id="ent-portland"
    )
    view_b = await reader.view(
        tenant_id=TENANT_B, subject_kind="entity", subject_id="ent-portland"
    )
    assert [f.location_id for f in view_a.posture.facts] == ["loc-a"]
    assert [f.location_id for f in view_b.posture.facts] == ["loc-b"]

    # A third tenant reads the honest missing — never another tenant's facts.
    empty = await reader.view(
        tenant_id="tenant_geo_unused", subject_kind="entity", subject_id="ent-portland"
    )
    assert empty.posture is None
    assert "no recorded location facts" in (empty.missing_reason or "")


async def test_default_reader_reports_out_of_kind_subjects():
    reader = GeographicLocationReader()
    view = await reader.view(
        tenant_id=TENANT_A, subject_kind="cluster", subject_id="cluster-1"
    )
    assert view.posture is None
    assert "not a geographic360 subject" in (view.missing_reason or "")
