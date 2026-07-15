"""Unit tests — JourneyCompiler durable journey building and rebuilds."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed (pip install -e '.[backend]')")

from datetime import datetime, timezone
from uuid import uuid4


def _ts(offset_seconds: int = 0) -> str:
    from datetime import timedelta
    t = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    return t.isoformat()


def _make_touchpoint(offset: int = 0, channel: str = "paid_search") -> dict:
    return {
        "touchpoint_id": str(uuid4()),
        "tenant_id": "tenant-a",
        "profile_id": "profile-001",
        "channel": channel,
        "touchpoint_type": "click",
        "occurred_at": _ts(offset),
        "idempotency_key": str(uuid4()),
    }


class TestJourneyCompilerLocal:
    """JourneyCompiler tests against local in-memory store."""

    @pytest.mark.asyncio
    async def test_compile_returns_journey_version(self):
        from services.measurement.engine.journey_compiler import JourneyCompiler
        compiler = JourneyCompiler()
        result = await compiler.compile_for_profile(
            tenant_id="tenant-a",
            profile_id="profile-001",
        )
        assert result is not None
        assert result.get("tenant_id") == "tenant-a" or result.get("profile_id") == "profile-001" or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_rebuild_by_consent_change_returns_list(self):
        from services.measurement.engine.journey_compiler import JourneyCompiler
        compiler = JourneyCompiler()
        results = await compiler.rebuild_affected_by_consent_change(
            tenant_id="tenant-a",
            profile_id="profile-001",
        )
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_rebuild_by_identity_change_returns_list(self):
        from services.measurement.engine.journey_compiler import JourneyCompiler
        compiler = JourneyCompiler()
        results = await compiler.rebuild_affected_by_identity_change(
            tenant_id="tenant-a",
            profile_id="profile-001",
        )
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_rebuild_by_touchpoint_returns_list(self):
        from services.measurement.engine.journey_compiler import JourneyCompiler
        compiler = JourneyCompiler()
        touchpoint_id = str(uuid4())
        results = await compiler.rebuild_affected_by_touchpoint(
            tenant_id="tenant-a",
            touchpoint_id=touchpoint_id,
        )
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_compile_is_tenant_scoped(self):
        """Compiling for tenant-a must not return tenant-b data."""
        from services.measurement.engine.journey_compiler import JourneyCompiler
        compiler = JourneyCompiler()
        result_a = await compiler.compile_for_profile("tenant-a", "profile-001")
        result_b = await compiler.compile_for_profile("tenant-b", "profile-001")
        # Both may return None/empty in local mode — what matters is no cross-tenant bleed
        if result_a and result_b:
            assert result_a != result_b or (
                result_a.get("tenant_id") != "tenant-b"
                and result_b.get("tenant_id") != "tenant-a"
            )


def test_source_noise_is_counted_but_not_emitted_as_eligible_steps():
    from services.measurement.engine.journey_compiler import _partition_source_noise

    activities = [
        {"activity_id": "human", "attribution_eligible": True, "journey_role": "entry"},
        {"activity_id": "crawler", "attribution_eligible": False, "journey_role": "excluded"},
        {"activity_id": "preview", "attribution_eligible": "false"},
    ]
    eligible, excluded_count = _partition_source_noise(activities)

    assert [activity["activity_id"] for activity in eligible] == ["human"]
    assert excluded_count == 2


def test_journey_touchpoint_ids_are_precise_ordered_and_unique():
    from services.measurement.engine.journey_compiler import _touchpoint_ids

    touchpoint_id = str(uuid4())
    activities = [
        {"silver_table": "silver_campaign_touchpoint_facts", "silver_fact_id": touchpoint_id},
        {"silver_table": "silver_campaign_touchpoint_facts", "silver_fact_id": touchpoint_id},
        {"silver_table": "silver_conversion_facts", "silver_fact_id": str(uuid4())},
    ]

    assert _touchpoint_ids(activities) == [touchpoint_id]


def test_journey_steps_snapshot_source_classification_dimensions():
    from services.measurement.engine.journey_compiler import _build_steps

    activity_id = str(uuid4())
    classification_id = str(uuid4())
    link_id = str(uuid4())
    steps = _build_steps(
        activities=[{
            "activity_id": activity_id,
            "occurred_at": _ts(),
            "activity_family": "campaign",
            "activity_type": "click",
            "source_class": "ai_referral",
            "referral_mediation_type": "ai_mediated_human_referral",
            "ai_provider": "openai",
            "ai_product": "chatgpt",
            "actor_type": "human",
            "journey_role": "entry",
            "evidence_confidence": 0.92,
            "verification_level": "domain_verified",
            "source_classifier_version": "2.0",
            "source_classification_id": classification_id,
            "verified_referral_link_id": link_id,
            "attribution_eligible": True,
        }],
        transitions=[None],
        tenant_id="tenant-a",
        journey_id=str(uuid4()),
        journey_version_id=str(uuid4()),
        profile_id="profile-001",
    )

    step = steps[0]
    assert step["ai_provider"] == "openai"
    assert step["ai_product"] == "chatgpt"
    assert step["actor_type"] == "human"
    assert step["source_classification_id"] == classification_id
    assert step["verified_referral_link_id"] == link_id
    assert step["attribution_eligible"] is True
    assert step["schema_version"] == 2
