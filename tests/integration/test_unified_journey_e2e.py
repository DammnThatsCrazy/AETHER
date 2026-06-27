"""Integration tests — Unified journey E2E scenarios."""

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


async def _seed_profile(repo, tenant_id: str, profile_id: str, activities: list[dict]) -> None:
    for a in activities:
        await repo.upsert({**a, "tenant_id": tenant_id, "profile_id": profile_id})


def _act(family: str, activity_type: str, offset: int, profile_id: str = "placeholder", **extra) -> dict:
    from services.measurement.contracts import CanonicalActivity, ActivityFamily, ActivityStatus
    return CanonicalActivity(
        tenant_id="tenant-a",
        profile_id=profile_id,
        activity_family=ActivityFamily(family),
        activity_type=activity_type,
        activity_status=ActivityStatus.observed,
        occurred_at=datetime.now(timezone.utc) + timedelta(seconds=offset),
        server_received_at=datetime.now(timezone.utc),
        source_event_id=str(uuid4()),
        idempotency_key=str(uuid4()),
        privacy_class="behavioral",
        **extra,
    ).model_dump()


class TestScenarioA_CampaignWeb2Web3Conversion:
    """Campaign → Web2 → Web3 → Web2 conversion full scenario."""

    @pytest.mark.asyncio
    async def test_full_cross_rail_journey(self):
        from services.measurement.repositories.activity_repo import ActivityRepository
        from services.measurement.engine.journey_compiler import JourneyCompiler

        repo = ActivityRepository()
        compiler = JourneyCompiler()
        profile_id = f"scenA-{uuid4()}"

        activities = [
            _act("campaign", "click", offset=0, campaign_id="camp-001"),
            _act("web2", "page_view", offset=30),
            _act("web2", "sign_up", offset=60),
            _act("web3", "wallet_connected", offset=90),
            _act("web3", "transfer", offset=120),
            _act("web2", "page_view", offset=150),
            _act("commerce", "purchase", offset=180, campaign_id="camp-001"),
        ]
        await _seed_profile(repo, "tenant-a", profile_id, activities)

        result = await compiler.compile_for_profile("tenant-a", profile_id)
        assert result is not None
        assert result.get("compiler_version") == "2.0"
        assert result.get("step_count", 0) == len(activities)


class TestScenarioB_AnonymousUserJourney:
    """Anonymous user — no profile_id, only anonymous_id."""

    @pytest.mark.asyncio
    async def test_anonymous_journey(self):
        from services.measurement.repositories.activity_repo import ActivityRepository
        from services.measurement.engine.journey_compiler import JourneyCompiler

        repo = ActivityRepository()
        compiler = JourneyCompiler()
        anon_id = f"anon-{uuid4()}"

        activities = [
            {**_act("web2", "page_view", offset=0), "anonymous_id": anon_id, "profile_id": None},
            {**_act("campaign", "click", offset=30), "anonymous_id": anon_id, "profile_id": None},
        ]
        for a in activities:
            a["tenant_id"] = "tenant-a"
            await repo.upsert(a)

        result = await compiler.compile_for_profile("tenant-a", anon_id)
        assert result is not None


class TestScenarioF_BlockchainReorg:
    """Scenario F: Blockchain reorg updates activity status and triggers rebuild."""

    @pytest.mark.asyncio
    async def test_reorg_updates_status(self):
        from services.measurement.repositories.activity_repo import ActivityRepository
        from services.measurement.engine.journey_compiler import JourneyCompiler

        repo = ActivityRepository()
        compiler = JourneyCompiler()
        profile_id = f"scenF-{uuid4()}"
        tx_hash = f"0x{uuid4().hex}"

        act = {
            **_act("web3", "transfer", offset=0, profile_id=profile_id),
            "tx_hash": tx_hash,
        }
        act["tenant_id"] = "tenant-a"
        act["profile_id"] = profile_id
        await repo.upsert(act)

        results = await compiler.rebuild_affected_by_web3_status_change("tenant-a", tx_hash, "reorged")
        assert isinstance(results, list)


class TestScenarioG_MultiTenantCollision:
    """Scenario G: Same wallet address across tenants must not leak."""

    @pytest.mark.asyncio
    async def test_same_wallet_different_tenants_isolated(self):
        from services.measurement.repositories.activity_repo import ActivityRepository

        repo = ActivityRepository()
        wallet = f"0x{uuid4().hex}"
        key_a = str(uuid4())
        key_b = str(uuid4())

        act_a = {**_act("web3", "transfer", offset=0), "wallet_id": wallet, "tenant_id": "tenant-a", "idempotency_key": key_a}
        act_b = {**_act("web3", "transfer", offset=0), "wallet_id": wallet, "tenant_id": "tenant-b", "idempotency_key": key_b}

        await repo.upsert(act_a)
        await repo.upsert(act_b)

        results_a = await repo.list_by_wallet("tenant-a", wallet, limit=100)
        results_b = await repo.list_by_wallet("tenant-b", wallet, limit=100)

        keys_a = {r.get("idempotency_key") for r in results_a}
        keys_b = {r.get("idempotency_key") for r in results_b}

        assert key_b not in keys_a, "Tenant B activity leaked into Tenant A results"
        assert key_a not in keys_b, "Tenant A activity leaked into Tenant B results"


class TestScenarioH_LateEventDeterministicReplay:
    """Scenario H: Late-arriving event inserted at correct chronological position."""

    @pytest.mark.asyncio
    async def test_late_event_sorted_correctly(self):
        from services.measurement.repositories.activity_repo import ActivityRepository
        from services.measurement.engine.journey_compiler import JourneyCompiler, _sort_deterministically

        repo = ActivityRepository()
        compiler = JourneyCompiler()
        profile_id = f"scenH-{uuid4()}"

        early = {**_act("web2", "page_view", offset=0), "tenant_id": "tenant-a", "profile_id": profile_id}
        late_arriving = {**_act("campaign", "click", offset=5), "tenant_id": "tenant-a", "profile_id": profile_id}
        later = {**_act("commerce", "purchase", offset=20), "tenant_id": "tenant-a", "profile_id": profile_id}

        await repo.upsert(early)
        await repo.upsert(later)
        await repo.upsert(late_arriving)

        activities = await repo.list_by_profile("tenant-a", profile_id, limit=100)
        sorted_acts = _sort_deterministically(activities)
        timestamps = [str(a.get("occurred_at", "")) for a in sorted_acts]
        assert timestamps == sorted(timestamps)
