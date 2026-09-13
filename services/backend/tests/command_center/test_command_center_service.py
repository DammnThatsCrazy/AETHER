"""Composition + live-empty behavior of the Command Center aggregator.

Two contracts are exercised here against ``CommandCenterService`` directly:

* **Composition** — with real seeded rows, the sections that read those rows go
  ``live`` and carry the seeded numbers verbatim (never a rounded-up or invented
  stand-in).
* **Live-empty honesty** — a brand-new tenant with nothing seeded gets an honest
  ``no_data`` (or ``unavailable``) for every read-backed section and NEVER a
  synthetic forward value. Activation is the one section that is legitimately
  ``live`` for a fresh tenant: an authenticated caller already has a real,
  derived ``account_verified`` state — genuine data, not a fabricated value.
"""
from __future__ import annotations

import pytest

from repositories.repos import CampaignRepository
from services.command_center.models import SectionState
from services.intelligence.repositories import (
    OutcomeRepository,
    RecommendationRepository,
)

_ALL_SECTIONS = {
    "activation",
    "value_strip",
    "ops_feed",
    "graph_snapshot",
    "campaign_movement",
    "data_confidence",
    "integration_health",
    "outcomes",
    "next_best_actions",
}


async def _seed_ledger(tenant_id: str) -> None:
    """Seed one recommendation + its success outcome for ``tenant_id``."""
    await RecommendationRepository().insert(
        f"{tenant_id}-rec-1",
        {
            "tenant_id": tenant_id,
            "recommendation_id": f"{tenant_id}-rec-1",
            "recommendation_type": "growth",
            "expected_value": 100,
            "status": "viewed",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )
    await OutcomeRepository().insert(
        f"{tenant_id}-out-1",
        {
            "tenant_id": tenant_id,
            "recommendation_id": f"{tenant_id}-rec-1",
            "label": "success",
            "value": 120,
            "created_at": "2026-01-02T00:00:00Z",
        },
    )


async def _seed_campaign(tenant_id: str, name: str = "Launch") -> None:
    await CampaignRepository().insert(
        f"{tenant_id}-camp-1",
        {
            "tenant_id": tenant_id,
            "name": name,
            "status": "active",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )


# ── Structure ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_view_always_has_all_nine_sections(svc):
    view = await svc.get_view("shape-tenant")
    assert view.tenant_id == "shape-tenant"
    assert set(view.sections.keys()) == _ALL_SECTIONS
    for key, env in view.sections.items():
        assert env.key == key
        assert env.source  # provenance is always stamped
        assert env.generated_at
        # data is present for live/no_data, and None for a degraded read.
        if env.state in (SectionState.unavailable, SectionState.error):
            assert env.data is None


# ── Live-empty: no synthetic values ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_tenant_degrades_without_synthetic_values(svc):
    """An empty tenant: every read-backed section is no_data, none fabricates."""
    view = await svc.get_view("empty-tenant")
    s = view.sections

    # Graph is empty -> the graph_health read itself reports no_data.
    assert s["graph_snapshot"].state == SectionState.no_data
    assert s["graph_snapshot"].data["status"] == "no_data"
    assert s["graph_snapshot"].data["node_count"] == 0
    assert s["graph_snapshot"].data["edge_count"] == 0

    # The outcome ledger is empty on both slices — and the summary it carries is
    # genuinely zeroed, not a made-up headline number.
    assert s["value_strip"].state == SectionState.no_data
    summary = s["value_strip"].data
    assert summary["recommendations_generated"] == 0
    assert summary["outcomes_observed"] == 0
    assert summary["expected_value"] == 0
    assert summary["observed_value"] == 0
    assert summary["success_rate"] == 0.0

    assert s["outcomes"].state == SectionState.no_data
    assert s["outcomes"].data["items"] == []

    # No campaigns, no configured integrations, no suggestions, no quality score.
    assert s["campaign_movement"].state == SectionState.no_data
    assert s["campaign_movement"].data == []
    assert s["integration_health"].state == SectionState.no_data
    assert s["integration_health"].data["sdk_fleet"]["total_instances"] == 0
    assert s["next_best_actions"].state == SectionState.no_data
    assert s["next_best_actions"].data == []
    assert s["data_confidence"].state == SectionState.no_data
    assert s["ops_feed"].state == SectionState.no_data

    # Activation is legitimately live for an authenticated tenant: a real,
    # derived state — NOT a synthetic forward value.
    assert s["activation"].state == SectionState.live
    assert s["activation"].data["state"] in {"not_started", "account_verified"}

    # Belt-and-suspenders: no section is live while hiding a fabricated metric.
    for key in ("value_strip", "outcomes", "campaign_movement", "next_best_actions"):
        assert s[key].state != SectionState.live


# ── Composition: seeded rows drive sections live ─────────────────────────────


@pytest.mark.asyncio
async def test_seeded_ledger_makes_value_strip_and_outcomes_live(svc):
    await _seed_ledger("seeded-tenant")
    view = await svc.get_view("seeded-tenant")
    s = view.sections

    assert s["value_strip"].state == SectionState.live
    # The headline reflects EXACTLY the seeded rows — read, not invented.
    assert s["value_strip"].data["recommendations_generated"] == 1
    assert s["value_strip"].data["outcomes_observed"] == 1
    assert s["value_strip"].data["success_rate"] == 1.0

    assert s["outcomes"].state == SectionState.live
    assert len(s["outcomes"].data["items"]) == 1


@pytest.mark.asyncio
async def test_seeded_campaign_makes_campaign_movement_live(svc):
    await _seed_campaign("camp-tenant", name="Spring Launch")
    view = await svc.get_view("camp-tenant")
    section = view.sections["campaign_movement"]
    assert section.state == SectionState.live
    assert [c["name"] for c in section.data] == ["Spring Launch"]


@pytest.mark.asyncio
async def test_value_strip_and_outcomes_share_one_ledger_read(svc, monkeypatch):
    """value_strip + outcomes must slice ONE ledger read — not double-fetch."""
    await _seed_ledger("shared-read-tenant")

    calls = {"n": 0}
    import services.intelligence.routes as intel_routes

    original = intel_routes._tenant_ledger

    async def _counting_ledger(tenant_id, *args, **kwargs):
        calls["n"] += 1
        return await original(tenant_id, *args, **kwargs)

    monkeypatch.setattr(intel_routes, "_tenant_ledger", _counting_ledger)

    view = await svc.get_view("shared-read-tenant")
    assert view.sections["value_strip"].state == SectionState.live
    assert view.sections["outcomes"].state == SectionState.live
    # Read once, slice twice.
    assert calls["n"] == 1
