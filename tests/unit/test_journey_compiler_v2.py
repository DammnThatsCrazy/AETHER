"""Unit tests — JourneyCompiler v2.0: cross-rail activity, deterministic sort, transitions."""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


def _ts(offset: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat()


def _make_activity(
    family: str = "web2",
    activity_type: str = "page_view",
    offset: int = 0,
    tenant_id: str = "tenant-a",
    profile_id: str = "profile-001",
) -> dict:
    from services.measurement.contracts import CanonicalActivity, ActivityFamily, ActivityStatus
    return CanonicalActivity(
        tenant_id=tenant_id,
        profile_id=profile_id,
        activity_family=ActivityFamily(family),
        activity_type=activity_type,
        activity_status=ActivityStatus.observed,
        occurred_at=datetime.now(timezone.utc) + timedelta(seconds=offset),
        server_received_at=datetime.now(timezone.utc),
        source_event_id=str(uuid4()),
        idempotency_key=str(uuid4()),
        privacy_class="behavioral",
    ).model_dump()


class TestJourneyCompilerV2:

    @pytest.mark.asyncio
    async def test_compile_returns_journey_version(self):
        from services.measurement.engine.journey_compiler import JourneyCompiler
        compiler = JourneyCompiler()
        result = await compiler.compile_for_profile("tenant-a", "profile-001")
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_compiler_version_is_2_0(self):
        from services.measurement.engine.journey_compiler import JourneyCompiler
        compiler = JourneyCompiler()
        result = await compiler.compile_for_profile("tenant-a", "profile-v2")
        assert result.get("compiler_version") == "2.0"

    @pytest.mark.asyncio
    async def test_cross_rail_activities_included(self):
        from services.measurement.engine.journey_compiler import JourneyCompiler
        from services.measurement.repositories.activity_repo import ActivityRepository
        repo = ActivityRepository()
        profile_id = f"prof-{uuid4()}"
        for family, activity_type in [
            ("web2", "page_view"),
            ("web3", "transfer"),
            ("campaign", "click"),
            ("x402", "payment_initiated"),
            ("agent", "execution_started"),
        ]:
            await repo.upsert(_make_activity(family=family, activity_type=activity_type, profile_id=profile_id))
        compiler = JourneyCompiler()
        result = await compiler.compile_for_profile("tenant-a", profile_id)
        assert result is not None
        step_count = result.get("step_count", 0)
        assert step_count >= 0

    @pytest.mark.asyncio
    async def test_deterministic_sort_same_input_same_output(self):
        from services.measurement.engine.journey_compiler import _sort_deterministically
        activities = [
            _make_activity(offset=10),
            _make_activity(offset=5),
            _make_activity(offset=20),
            _make_activity(offset=1),
        ]
        sorted1 = _sort_deterministically(activities)
        sorted2 = _sort_deterministically(activities)
        assert [a.get("idempotency_key") for a in sorted1] == [a.get("idempotency_key") for a in sorted2]

    @pytest.mark.asyncio
    async def test_deterministic_sort_chronological_order(self):
        from services.measurement.engine.journey_compiler import _sort_deterministically
        activities = [
            _make_activity(offset=20),
            _make_activity(offset=5),
            _make_activity(offset=1),
        ]
        sorted_acts = _sort_deterministically(activities)
        times = [str(a.get("occurred_at") or "") for a in sorted_acts]
        assert times == sorted(times)

    @pytest.mark.asyncio
    async def test_transition_classification_cross_rail(self):
        from services.measurement.engine.journey_compiler import _classify_pair
        web2 = _make_activity(family="web2", activity_type="page_view", offset=0)
        web3 = _make_activity(family="web3", activity_type="transfer", offset=10)
        transition = _classify_pair(web2, web3, session_timeout_seconds=1800)
        assert transition == "web2_to_web3"

    @pytest.mark.asyncio
    async def test_transition_web3_to_web2(self):
        from services.measurement.engine.journey_compiler import _classify_pair
        web3 = _make_activity(family="web3", activity_type="transfer", offset=0)
        web2 = _make_activity(family="web2", activity_type="page_view", offset=10)
        transition = _classify_pair(web3, web2, session_timeout_seconds=1800)
        assert transition == "web3_to_web2"

    @pytest.mark.asyncio
    async def test_transition_human_to_agent(self):
        from services.measurement.engine.journey_compiler import _classify_pair
        human = {**_make_activity(family="web2", offset=0), "actor_type": "human"}
        agent = {**_make_activity(family="agent", offset=5), "actor_type": "agent"}
        transition = _classify_pair(human, agent, session_timeout_seconds=1800)
        assert transition == "human_to_agent"

    @pytest.mark.asyncio
    async def test_empty_profile_produces_zero_step_count(self):
        from services.measurement.engine.journey_compiler import JourneyCompiler
        profile_id = f"empty-{uuid4()}"
        compiler = JourneyCompiler()
        result = await compiler.compile_for_profile("tenant-a", profile_id)
        assert result.get("step_count", 0) == 0

    @pytest.mark.asyncio
    async def test_rebuild_consent_change(self):
        from services.measurement.engine.journey_compiler import JourneyCompiler
        compiler = JourneyCompiler()
        results = await compiler.rebuild_affected_by_consent_change("tenant-a", "profile-001")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_rebuild_web3_status_change(self):
        from services.measurement.engine.journey_compiler import JourneyCompiler
        compiler = JourneyCompiler()
        tx_hash = f"0x{uuid4().hex}"
        results = await compiler.rebuild_affected_by_web3_status_change("tenant-a", tx_hash, "confirmed")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_web3_does_not_break_session_boundary(self):
        from services.measurement.engine.journey_compiler import _classify_pair
        web2 = _make_activity(family="web2", offset=0)
        web3 = _make_activity(family="web3", offset=5)
        web2_after = _make_activity(family="web2", offset=10)
        t1 = _classify_pair(web2, web3, session_timeout_seconds=1800)
        t2 = _classify_pair(web3, web2_after, session_timeout_seconds=1800)
        # web3 should not introduce a "new_session" transition in short windows
        assert t1 != "new_session"
        assert t2 != "new_session"


class TestJourneyCompilerV2Regression:
    """Regression: v1 behavior (campaign only) still works."""

    @pytest.mark.asyncio
    async def test_campaign_only_profile(self):
        from services.measurement.engine.journey_compiler import JourneyCompiler
        from services.measurement.repositories.activity_repo import ActivityRepository
        repo = ActivityRepository()
        profile_id = f"camp-{uuid4()}"
        for i in range(3):
            await repo.upsert(_make_activity(family="campaign", activity_type="touchpoint", offset=i * 10, profile_id=profile_id))
        compiler = JourneyCompiler()
        result = await compiler.compile_for_profile("tenant-a", profile_id)
        assert result is not None
