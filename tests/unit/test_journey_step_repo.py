"""Unit tests — JourneyStepRepository: bulk create, pagination, filters, adjacent."""

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


def _make_step(
    tenant_id: str = "tenant-a",
    journey_id: str | None = None,
    journey_version_id: str | None = None,
    position: int = 0,
    family: str = "web2",
    activity_type: str = "page_view",
    offset: int = 0,
    session_id: str | None = None,
    wallet_id: str | None = None,
    chain_id: str | None = None,
    campaign_id: str | None = None,
) -> dict:
    from services.measurement.contracts import JourneyStep, ActivityFamily, ActivityStatus
    return JourneyStep(
        tenant_id=tenant_id,
        journey_id=journey_id or str(uuid4()),
        journey_version_id=journey_version_id or str(uuid4()),
        step_position=position,
        occurred_at=datetime.now(timezone.utc) + timedelta(seconds=offset),
        activity_id=str(uuid4()),
        activity_family=ActivityFamily(family),
        activity_type=activity_type,
        activity_status=ActivityStatus.observed,
        session_id=session_id,
        wallet_id=wallet_id,
        chain_id=chain_id,
        campaign_id=campaign_id,
        schema_version=1,
    ).model_dump()


class TestJourneyStepRepoBulkCreate:

    @pytest.mark.asyncio
    async def test_bulk_create_and_list(self):
        from services.measurement.repositories.journey_step_repo import JourneyStepRepository
        repo = JourneyStepRepository()
        jvid = str(uuid4())
        jid = str(uuid4())
        steps = [_make_step(journey_id=jid, journey_version_id=jvid, position=i, offset=i * 10) for i in range(5)]
        await repo.bulk_create(steps)
        result = await repo.list_by_version("tenant-a", jvid, limit=20)
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_bulk_create_idempotent(self):
        from services.measurement.repositories.journey_step_repo import JourneyStepRepository
        repo = JourneyStepRepository()
        jvid = str(uuid4())
        jid = str(uuid4())
        steps = [_make_step(journey_id=jid, journey_version_id=jvid, position=i) for i in range(3)]
        await repo.bulk_create(steps)
        await repo.bulk_create(steps)  # second call should not duplicate
        result = await repo.list_by_version("tenant-a", jvid, limit=20)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_list_chronological_order(self):
        from services.measurement.repositories.journey_step_repo import JourneyStepRepository
        repo = JourneyStepRepository()
        jvid = str(uuid4())
        jid = str(uuid4())
        steps = [_make_step(journey_id=jid, journey_version_id=jvid, position=i, offset=i * 5) for i in range(4)]
        await repo.bulk_create(steps)
        result = await repo.list_by_version("tenant-a", jvid, limit=20)
        positions = [r.get("step_position") for r in result]
        assert positions == sorted(positions)


class TestJourneyStepRepoFilters:

    @pytest.mark.asyncio
    async def test_filter_by_family(self):
        from services.measurement.repositories.journey_step_repo import JourneyStepRepository
        repo = JourneyStepRepository()
        jvid = str(uuid4())
        jid = str(uuid4())
        steps = [
            _make_step(journey_id=jid, journey_version_id=jvid, position=0, family="web2"),
            _make_step(journey_id=jid, journey_version_id=jvid, position=1, family="web3"),
            _make_step(journey_id=jid, journey_version_id=jvid, position=2, family="campaign"),
        ]
        await repo.bulk_create(steps)
        web3_steps = await repo.list_by_version("tenant-a", jvid, families=["web3"], limit=20)
        assert all(s.get("activity_family") == "web3" for s in web3_steps)
        assert len(web3_steps) == 1

    @pytest.mark.asyncio
    async def test_filter_by_wallet_id(self):
        from services.measurement.repositories.journey_step_repo import JourneyStepRepository
        repo = JourneyStepRepository()
        jvid = str(uuid4())
        jid = str(uuid4())
        wallet = f"wallet-{uuid4()}"
        steps = [
            _make_step(journey_id=jid, journey_version_id=jvid, position=0, family="web3", wallet_id=wallet),
            _make_step(journey_id=jid, journey_version_id=jvid, position=1, family="web2"),
        ]
        await repo.bulk_create(steps)
        wallet_steps = await repo.list_by_version("tenant-a", jvid, wallet_id=wallet, limit=20)
        assert all(s.get("wallet_id") == wallet for s in wallet_steps)

    @pytest.mark.asyncio
    async def test_filter_by_session_id(self):
        from services.measurement.repositories.journey_step_repo import JourneyStepRepository
        repo = JourneyStepRepository()
        jvid = str(uuid4())
        jid = str(uuid4())
        session = f"sess-{uuid4()}"
        steps = [
            _make_step(journey_id=jid, journey_version_id=jvid, position=0, session_id=session),
            _make_step(journey_id=jid, journey_version_id=jvid, position=1, session_id="other-session"),
        ]
        await repo.bulk_create(steps)
        session_steps = await repo.list_by_version("tenant-a", jvid, session_id=session, limit=20)
        assert all(s.get("session_id") == session for s in session_steps)


class TestJourneyStepRepoAdjacent:

    @pytest.mark.asyncio
    async def test_get_adjacent_middle_step(self):
        from services.measurement.repositories.journey_step_repo import JourneyStepRepository
        repo = JourneyStepRepository()
        jvid = str(uuid4())
        jid = str(uuid4())
        steps = [_make_step(journey_id=jid, journey_version_id=jvid, position=i) for i in range(3)]
        await repo.bulk_create(steps)
        middle = (await repo.list_by_version("tenant-a", jvid, limit=20))[1]
        step_id = middle.get("step_id")
        if step_id:
            adjacent = await repo.get_adjacent("tenant-a", str(step_id))
            assert "previous" in adjacent
            assert "next" in adjacent

    @pytest.mark.asyncio
    async def test_get_adjacent_first_step_has_no_previous(self):
        from services.measurement.repositories.journey_step_repo import JourneyStepRepository
        repo = JourneyStepRepository()
        jvid = str(uuid4())
        jid = str(uuid4())
        steps = [_make_step(journey_id=jid, journey_version_id=jvid, position=i) for i in range(2)]
        await repo.bulk_create(steps)
        first = (await repo.list_by_version("tenant-a", jvid, limit=20))[0]
        step_id = first.get("step_id")
        if step_id:
            adjacent = await repo.get_adjacent("tenant-a", str(step_id))
            assert adjacent.get("previous") is None


class TestJourneyStepRepoPagination:

    @pytest.mark.asyncio
    async def test_cursor_pagination(self):
        from services.measurement.repositories.journey_step_repo import JourneyStepRepository
        repo = JourneyStepRepository()
        jvid = str(uuid4())
        jid = str(uuid4())
        steps = [_make_step(journey_id=jid, journey_version_id=jvid, position=i) for i in range(10)]
        await repo.bulk_create(steps)
        page1 = await repo.list_by_version("tenant-a", jvid, limit=4)
        assert len(page1) == 4
        last_pos = page1[-1].get("step_position", 0)
        page2 = await repo.list_by_version("tenant-a", jvid, limit=4, cursor=str(last_pos))
        assert len(page2) >= 1
        # Ensure no overlap
        p1_positions = {s.get("step_position") for s in page1}
        p2_positions = {s.get("step_position") for s in page2}
        assert p1_positions.isdisjoint(p2_positions)
