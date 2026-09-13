from datetime import datetime, timedelta, timezone

import pytest

from repositories.sdk_repos import SDKInstallationRepository
from services.sdk_health.service import SDKHealthService, SDKHeartbeat


@pytest.mark.asyncio
async def test_silent_installation_survives_heartbeat_cache_expiry():
    svc = SDKHealthService()
    svc._installations = SDKInstallationRepository()
    svc._installations.table_name = "sdk_installations_durability_test"
    svc._installations._store = {}
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    await svc.ingest_heartbeat(SDKHeartbeat(
        tenant_id="tenant-a", sdk_id="sdk-a", sdk_version="7.0.0",
        platform="web", reported_at=old,
    ))
    # Simulate expiry of both Redis/cache records.
    from shared.store import InMemoryStore
    svc._heartbeat_store = InMemoryStore("expired_hb")
    svc._score_store = InMemoryStore("expired_score")

    fleet = await svc.get_fleet_status("tenant-a")
    assert fleet.total_instances == 1
    assert fleet.silent_count == 1
    assert (await svc.detect_silent_sdks("tenant-a"))[0]["sdk_id"] == "sdk-a"
