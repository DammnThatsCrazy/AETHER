"""DSR erasure must tombstone the subject's canonical activity before rebuilding.

``JourneyCompiler.rebuild_affected_by_consent_change`` only produces a
privacy-correct journey because ``ActivityRepository`` skips tombstoned rows.
The erasure handler never tombstoned them, so on staging the erased subject's
page views and orders stayed ``observed``/``confirmed`` and the "erasure"
rebuild re-derived the same journey from them.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from services.measurement.privacy import MeasurementPrivacyHandler
from services.measurement.repositories.activity_repo import ActivityRepository

pytestmark = pytest.mark.asyncio


async def _seed_activity(
    tenant_id: str, profile_id: str | None, status: str, anonymous_id: str | None = None
) -> None:
    activity_id = str(uuid4())
    await ActivityRepository().upsert({
        "activity_id": activity_id,
        "tenant_id": tenant_id,
        "idempotency_key": f"erasure-activity-{activity_id}",
        "profile_id": profile_id,
        "anonymous_id": anonymous_id,
        "activity_family": "web2",
        "activity_type": "page_view",
        "activity_status": status,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    })


async def test_erasure_tombstones_only_the_subjects_activity():
    tenant_id = f"tenant-{uuid4().hex[:8]}"
    subject, bystander = f"alice-{uuid4().hex[:8]}", f"bob-{uuid4().hex[:8]}"
    for status in ("observed", "confirmed"):
        await _seed_activity(tenant_id, subject, status)
        await _seed_activity(tenant_id, bystander, status)

    result = await MeasurementPrivacyHandler().handle_erasure(tenant_id, subject)

    repo = ActivityRepository()
    assert result["activities_tombstoned"] == 2
    assert not any(e.startswith("activity_tombstone") for e in result["errors"])
    assert await repo.list_by_profile(tenant_id, subject) == []
    assert len(await repo.list_by_profile(tenant_id, bystander)) == 2


async def test_erasure_tombstones_activity_under_the_requested_anonymous_id():
    tenant_id = f"tenant-{uuid4().hex[:8]}"
    subject, anon, other_anon = f"alice-{uuid4().hex[:8]}", f"anon-{uuid4().hex[:8]}", f"anon-{uuid4().hex[:8]}"
    await _seed_activity(tenant_id, subject, "observed")
    await _seed_activity(tenant_id, None, "observed", anonymous_id=anon)
    await _seed_activity(tenant_id, None, "observed", anonymous_id=other_anon)

    result = await MeasurementPrivacyHandler().handle_erasure(tenant_id, subject, anon)

    repo = ActivityRepository()
    assert result["activities_tombstoned"] == 2
    assert not any(e.startswith("anonymous_tombstone") for e in result["errors"])
    assert await repo.list_by_profile(tenant_id, anon, identity_type="anonymous") == []
    assert len(await repo.list_by_profile(tenant_id, other_anon, identity_type="anonymous")) == 1
