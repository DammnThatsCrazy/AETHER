"""Tests for the recommendations service — engine, executor, and routes."""
from __future__ import annotations

import pytest

from repositories.repos import RecommendationRepository, reset_in_memory_stores
from services.recommendations.engine import (
    RETARGET_THRESHOLD,
    RecommendationInput,
    compute_retarget_score,
    generate_recommendation,
    select_creative_theme,
    select_platform,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


# ── Engine unit tests ──────────────────────────────────────────────────────


def test_score_is_zero_for_no_intent():
    assert compute_retarget_score(0.0, 0.5, 1.0, 1, 5) == 0.0


def test_score_above_threshold_generates_recommendation():
    inp = RecommendationInput(
        entity_id="e1", journey_id="j1",
        intent_signal=0.9, ltv_score=0.9,
        days_since_last_event=2, reached_stage_index=0, total_stages=5,
        active_signals=["YIELD_FARMER"], social_platforms=["twitter"],
        ltv_predicted_usd=5000, cpa_target_usd=20, expected_conversion_rate=0.05,
    )
    rec = generate_recommendation(inp)
    assert rec is not None
    assert rec["retarget_score"] >= RETARGET_THRESHOLD
    assert rec["status"] == "pending_review"
    assert rec["recommended_platform"] == "twitter_ads"
    assert rec["recommended_creative_theme"] == "yield_and_rewards"


def test_score_below_threshold_returns_none():
    inp = RecommendationInput(
        entity_id="e1", journey_id="j1",
        intent_signal=0.1, ltv_score=0.1,
        days_since_last_event=60, reached_stage_index=4, total_stages=5,
        active_signals=[], social_platforms=[],
        ltv_predicted_usd=100, cpa_target_usd=20, expected_conversion_rate=0.01,
    )
    assert generate_recommendation(inp) is None


def test_select_platform_defaults_twitter():
    assert select_platform([]) == "twitter_ads"
    assert select_platform(["instagram"]) == "meta_ads"
    assert select_platform(["linkedin"]) == "linkedin_ads"


def test_select_creative_theme_fallback():
    assert select_creative_theme([]) == "general_reengagement"
    assert select_creative_theme(["DEFI_NATIVE"]) == "defi_explorer"


# ── Repository tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recommendation_repository_lifecycle():
    repo = RecommendationRepository()
    rec = {
        "recommendation_id": "r1",
        "entity_id": "e1",
        "tenant_id": "t1",
        "status": "pending_review",
        "retarget_score": 7.5,
        "recommended_platform": "twitter_ads",
        "recommended_creative_theme": "yield_and_rewards",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    await repo.create(rec)

    fetched = await repo.get("r1", "t1")
    assert fetched is not None
    assert fetched["status"] == "pending_review"

    updated = await repo.update_status("r1", "t1", "approved", reviewed_by="analyst1")
    assert updated["status"] == "approved"
    assert updated["reviewed_by"] == "analyst1"


@pytest.mark.asyncio
async def test_recommendation_repository_tenant_isolation():
    repo = RecommendationRepository()
    await repo.create({"recommendation_id": "r1", "entity_id": "e1", "tenant_id": "t1", "status": "pending_review"})
    assert await repo.get("r1", "t2") is None


@pytest.mark.asyncio
async def test_list_for_entity_with_status_filter():
    repo = RecommendationRepository()
    for i, status in enumerate(["pending_review", "approved", "rejected"]):
        await repo.create({
            "recommendation_id": f"r{i}",
            "entity_id": "e1",
            "tenant_id": "t1",
            "status": status,
            "created_at": f"2026-01-0{i+1}T00:00:00+00:00",
        })
    pending = await repo.list_for_entity("e1", "t1", status="pending_review")
    assert len(pending) == 1
    assert pending[0]["recommendation_id"] == "r0"

    all_recs = await repo.list_for_entity("e1", "t1")
    assert len(all_recs) == 3
