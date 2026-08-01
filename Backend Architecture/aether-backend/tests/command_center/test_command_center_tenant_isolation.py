"""The Command Center view is tenant-scoped end to end.

The aggregator forwards ONLY ``tenant.tenant_id`` to each composed read, and
every underlying store filters on ``tenant_id``. Tenant A therefore never
observes tenant B's campaigns, ledger, or any other section payload, and vice
versa.
"""
from __future__ import annotations

import pytest

from repositories.repos import CampaignRepository
from services.command_center.models import SectionState
from services.intelligence.repositories import (
    OutcomeRepository,
    RecommendationRepository,
)


async def _seed_tenant(tenant_id: str, campaign_name: str) -> None:
    await CampaignRepository().insert(
        f"{tenant_id}-camp",
        {
            "tenant_id": tenant_id,
            "name": campaign_name,
            "status": "active",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )
    await RecommendationRepository().insert(
        f"{tenant_id}-rec",
        {
            "tenant_id": tenant_id,
            "recommendation_id": f"{tenant_id}-rec",
            "recommendation_type": "growth",
            "expected_value": 50,
            "status": "viewed",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )
    await OutcomeRepository().insert(
        f"{tenant_id}-out",
        {
            "tenant_id": tenant_id,
            "recommendation_id": f"{tenant_id}-rec",
            "label": "success",
            "value": 60,
            "created_at": "2026-01-02T00:00:00Z",
        },
    )


@pytest.mark.asyncio
async def test_view_is_scoped_to_requested_tenant(svc):
    await _seed_tenant("tenant-A", "A-Campaign")
    await _seed_tenant("tenant-B", "B-Campaign")

    a_view = await svc.get_view("tenant-A")
    b_view = await svc.get_view("tenant-B")

    assert a_view.tenant_id == "tenant-A"
    assert b_view.tenant_id == "tenant-B"

    # A's campaign section contains only A's campaign — never B's.
    a_names = [c["name"] for c in a_view.sections["campaign_movement"].data]
    b_names = [c["name"] for c in b_view.sections["campaign_movement"].data]
    assert a_names == ["A-Campaign"]
    assert b_names == ["B-Campaign"]

    # Every campaign row A sees is stamped with A's tenant id, and none carries B's.
    for row in a_view.sections["campaign_movement"].data:
        assert row["tenant_id"] == "tenant-A"


@pytest.mark.asyncio
async def test_tenant_b_data_never_appears_in_tenant_a_view(svc):
    await _seed_tenant("tenant-A", "A-Campaign")
    await _seed_tenant("tenant-B", "B-Campaign")

    a_view = await svc.get_view("tenant-A")

    # Serialize the whole A view and assert no B identifier leaks anywhere in it.
    blob = a_view.model_dump_json()
    assert "tenant-B" not in blob
    assert "B-Campaign" not in blob
    assert "tenant-B-rec" not in blob


@pytest.mark.asyncio
async def test_empty_sibling_sees_no_data_from_populated_tenant(svc):
    """B (empty) cannot inherit A's live sections."""
    await _seed_tenant("tenant-A", "A-Campaign")

    b_view = await svc.get_view("tenant-B")
    s = b_view.sections
    assert s["campaign_movement"].state == SectionState.no_data
    assert s["campaign_movement"].data == []
    assert s["value_strip"].state == SectionState.no_data
    assert s["outcomes"].state == SectionState.no_data
