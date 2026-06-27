"""Security tests — journey tenant isolation: no cross-tenant data leakage."""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")


def _act(tenant_id: str, profile_id: str, family: str = "web2") -> dict:
    from services.measurement.contracts import CanonicalActivity, ActivityFamily, ActivityStatus
    return CanonicalActivity(
        tenant_id=tenant_id,
        profile_id=profile_id,
        activity_family=ActivityFamily(family),
        activity_type="page_view",
        activity_status=ActivityStatus.observed,
        occurred_at=datetime.now(timezone.utc),
        server_received_at=datetime.now(timezone.utc),
        source_event_id=str(uuid4()),
        idempotency_key=str(uuid4()),
        privacy_class="behavioral",
    ).model_dump()


class TestActivityTenantIsolation:

    @pytest.mark.asyncio
    async def test_tenant_a_cannot_see_tenant_b_by_profile(self):
        from services.measurement.repositories.activity_repo import ActivityRepository
        repo = ActivityRepository()
        profile_id = f"iso-prof-{uuid4()}"
        idem_a = str(uuid4())
        idem_b = str(uuid4())
        act_a = {**_act("tenant-a", profile_id), "idempotency_key": idem_a}
        act_b = {**_act("tenant-b", profile_id), "idempotency_key": idem_b}
        await repo.upsert(act_a)
        await repo.upsert(act_b)
        results_a = await repo.list_by_profile("tenant-a", profile_id, limit=100)
        found_b = any(r.get("idempotency_key") == idem_b for r in results_a)
        assert not found_b, "Tenant A received Tenant B's activity — isolation breach"

    @pytest.mark.asyncio
    async def test_tenant_b_cannot_see_tenant_a_by_profile(self):
        from services.measurement.repositories.activity_repo import ActivityRepository
        repo = ActivityRepository()
        profile_id = f"iso-prof-{uuid4()}"
        idem_a = str(uuid4())
        idem_b = str(uuid4())
        act_a = {**_act("tenant-a", profile_id), "idempotency_key": idem_a}
        act_b = {**_act("tenant-b", profile_id), "idempotency_key": idem_b}
        await repo.upsert(act_a)
        await repo.upsert(act_b)
        results_b = await repo.list_by_profile("tenant-b", profile_id, limit=100)
        found_a = any(r.get("idempotency_key") == idem_a for r in results_b)
        assert not found_a, "Tenant B received Tenant A's activity — isolation breach"

    @pytest.mark.asyncio
    async def test_same_idempotency_key_different_tenants_are_independent(self):
        from services.measurement.repositories.activity_repo import ActivityRepository
        repo = ActivityRepository()
        shared_key = f"shared-{uuid4()}"
        act_a = {**_act("tenant-a", "profile-shared"), "idempotency_key": shared_key}
        act_b = {**_act("tenant-b", "profile-shared"), "idempotency_key": shared_key}
        r_a = await repo.upsert(act_a)
        r_b = await repo.upsert(act_b)
        assert r_a is not None, "Tenant A upsert should succeed"
        assert r_b is not None, "Tenant B upsert should succeed (different tenant, same key)"


class TestJourneyStepTenantIsolation:

    @pytest.mark.asyncio
    async def test_step_list_respects_tenant(self):
        from services.measurement.repositories.journey_step_repo import JourneyStepRepository
        from services.measurement.contracts import JourneyStep, ActivityFamily, ActivityStatus
        repo = JourneyStepRepository()

        jvid = str(uuid4())
        jid = str(uuid4())

        step_a = JourneyStep(
            tenant_id="tenant-a",
            journey_id=jid,
            journey_version_id=jvid,
            step_position=0,
            occurred_at=datetime.now(timezone.utc),
            activity_id=str(uuid4()),
            activity_family=ActivityFamily.web2,
            activity_type="page_view",
            activity_status=ActivityStatus.observed,
            schema_version=1,
        ).model_dump()

        step_b = JourneyStep(
            tenant_id="tenant-b",
            journey_id=jid,
            journey_version_id=jvid,
            step_position=1,
            occurred_at=datetime.now(timezone.utc),
            activity_id=str(uuid4()),
            activity_family=ActivityFamily.web2,
            activity_type="page_view",
            activity_status=ActivityStatus.observed,
            schema_version=1,
        ).model_dump()

        await repo.bulk_create([step_a])
        await repo.bulk_create([step_b])

        results_a = await repo.list_by_version("tenant-a", jvid, limit=100)
        results_b = await repo.list_by_version("tenant-b", jvid, limit=100)

        tenant_ids_a = {r.get("tenant_id") for r in results_a}
        tenant_ids_b = {r.get("tenant_id") for r in results_b}

        assert "tenant-b" not in tenant_ids_a, "Tenant A step list includes Tenant B steps"
        assert "tenant-a" not in tenant_ids_b, "Tenant B step list includes Tenant A steps"
