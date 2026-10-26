"""Focused tests for explicit Campaign360 population link authority."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "campaign-population-link-test-secret")

from journeys.campaign.campaign_population_links import (  # noqa: E402
    CampaignPopulationLinkAuthority,
    CampaignPopulationLinkAuthorityError,
    CampaignPopulationLinkConflict,
    CampaignPopulationLinkInput,
    RepositoryCampaignPopulationLinkStore,
)

CAMPAIGN_ID = "46d19f14-9a0f-4b15-9bd0-df52d468791a"
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


class CampaignReader:
    async def get_by_id(self, tenant_id, campaign_id):
        return {
            "tenant_id": tenant_id,
            "campaign_id": str(campaign_id),
            "created_at": NOW.isoformat(),
        }


class PopulationReader:
    def __init__(self, tenant_id="tenant-a"):
        self.tenant_id = tenant_id

    async def find_by_id(self, population_id):
        return {
            "id": population_id,
            "tenant_id": self.tenant_id,
            "created_at": NOW.isoformat(),
        }


def _event(event_type="linked", source_event_id="operator-event-1"):
    return CampaignPopulationLinkInput(
        population_id="population-1",
        event_type=event_type,
        source_record_id="operator-campaign-record-1",
        source_revision_id="revision-2",
        source_event_id=source_event_id,
        source_observed_at=NOW,
        effective_at=NOW,
    )


def _authority(population_reader=None):
    store = RepositoryCampaignPopulationLinkStore()
    store._local_events.clear()
    return CampaignPopulationLinkAuthority(
        store=store,
        campaign_reader=CampaignReader(),
        population_reader=population_reader or PopulationReader(),
    )


@pytest.mark.asyncio
async def test_link_uses_exact_campaign_population_and_actor_evidence():
    authority = _authority()
    row = await authority.record(
        "tenant-a",
        CAMPAIGN_ID,
        _event(),
        actor_id="operator-1",
        actor_type="tenant_user",
    )
    assert row["tenant_id"] == "tenant-a"
    assert row["campaign_id"] == CAMPAIGN_ID
    assert row["population_id"] == "population-1"
    assert row["actor_id"] == "operator-1"
    assert row["source_id"] == "aether.operator:operator-1"
    assert {ref["id"] for ref in row["evidence_refs"]} == {CAMPAIGN_ID, "population-1"}

    read = await authority.read_current("tenant-a", CAMPAIGN_ID)
    assert read.available is True
    assert len(read.rows) == 1
    assert read.rows[0]["event_type"] == "linked"


@pytest.mark.asyncio
async def test_population_link_rejects_foreign_population_scope():
    authority = _authority(PopulationReader(tenant_id="tenant-b"))
    with pytest.raises(CampaignPopulationLinkAuthorityError, match="exact tenant population"):
        await authority.record(
            "tenant-a",
            CAMPAIGN_ID,
            _event(),
            actor_id="operator-1",
            actor_type="tenant_user",
        )


@pytest.mark.asyncio
async def test_latest_population_event_replaces_old_link_and_replays_idempotently(monkeypatch):
    import repositories.repos

    async def no_database_pool():
        return None

    monkeypatch.setattr(repositories.repos, "get_pool", no_database_pool)
    authority = _authority()
    linked = await authority.record(
        "tenant-a", CAMPAIGN_ID, _event(), actor_id="operator-1", actor_type="tenant_user"
    )
    replay = await authority.record(
        "tenant-a", CAMPAIGN_ID, _event(), actor_id="operator-1", actor_type="tenant_user"
    )
    assert replay["link_event_id"] == linked["link_event_id"]
    assert replay["recorded_at"] == linked["recorded_at"]

    unlinked = await authority.record(
        "tenant-a",
        CAMPAIGN_ID,
        _event(event_type="unlinked", source_event_id="operator-event-2"),
        actor_id="operator-1",
        actor_type="tenant_user",
    )
    read = await authority.read_current("tenant-a", CAMPAIGN_ID)
    assert len(read.rows) == 1
    assert read.rows[0]["link_event_id"] == unlinked["link_event_id"]
    assert read.rows[0]["event_type"] == "unlinked"


@pytest.mark.asyncio
async def test_future_effective_unlink_does_not_replace_current_association(monkeypatch):
    import repositories.repos

    async def no_database_pool():
        return None

    monkeypatch.setattr(repositories.repos, "get_pool", no_database_pool)
    authority = _authority()
    now = datetime.now(timezone.utc)
    await authority.record(
        "tenant-a",
        CAMPAIGN_ID,
        _event(source_event_id="link-now").model_copy(
            update={"effective_at": now - timedelta(minutes=1)}
        ),
        actor_id="operator-1",
        actor_type="tenant_user",
    )
    future_unlink = now + timedelta(days=1)
    await authority.record(
        "tenant-a",
        CAMPAIGN_ID,
        _event(event_type="unlinked", source_event_id="unlink-tomorrow").model_copy(
            update={"effective_at": future_unlink}
        ),
        actor_id="operator-1",
        actor_type="tenant_user",
    )

    current = await authority.read_current("tenant-a", CAMPAIGN_ID)
    assert current.available is True
    assert len(current.rows) == 1
    assert current.rows[0]["event_type"] == "linked"

    scheduled, truncated = await authority._store.latest_for_campaign(
        "tenant-a",
        CAMPAIGN_ID,
        limit=100,
        effective_as_of=future_unlink + timedelta(seconds=1),
    )
    assert truncated is False
    assert scheduled[0]["event_type"] == "unlinked"


@pytest.mark.asyncio
async def test_same_source_event_with_changed_population_link_conflicts(monkeypatch):
    import repositories.repos

    async def no_database_pool():
        return None

    monkeypatch.setattr(repositories.repos, "get_pool", no_database_pool)
    authority = _authority()
    await authority.record(
        "tenant-a", CAMPAIGN_ID, _event(), actor_id="operator-1", actor_type="tenant_user"
    )
    with pytest.raises(CampaignPopulationLinkConflict):
        await authority.record(
            "tenant-a",
            CAMPAIGN_ID,
            _event(event_type="unlinked"),
            actor_id="operator-1",
            actor_type="tenant_user",
        )
