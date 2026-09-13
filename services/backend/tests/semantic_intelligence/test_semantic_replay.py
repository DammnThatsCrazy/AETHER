"""Phase B — real semantic replay / historical backfill (replaces the 501 stub).

Proves reprocessing is real: dry-run counts without writing, a real run replays
durable Bronze events into semantic observations, family/time filters apply, and
replay is idempotent. Reads Bronze, writes only semantic facts.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from repositories.repos import _IN_MEMORY_STORES, reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.engine import get_store, set_store
from services.semantic_intelligence.replay import SemanticReplayRunner
from services.semantic_intelligence.repositories.replay_repo import SemanticReplayJobRepository
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore

TENANT = "tenant_replay"


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    original = get_store()
    set_store(DurableSemanticSentimentStore())
    service_mod.set_semantic_service(SemanticIntelligenceService())
    yield
    set_store(original)
    service_mod.set_semantic_service(SemanticIntelligenceService())
    reset_in_memory_stores()


def _seed_bronze(event_id: str, event_type: str, family: str, content: str) -> None:
    store = _IN_MEMORY_STORES.setdefault("bronze_sdk_events", {})
    store[event_id] = {
        "id": event_id,
        "tenant_id": TENANT,
        "event_id": event_id,
        "event_type": event_type,
        "event_family": family,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "event_id": event_id,
            "event_type": event_type,
            "user_id": "u1",
            "properties": {"content": content, "product_id": "prod_1"},
        },
    }


async def test_dry_run_counts_without_writing():
    for i in range(3):
        _seed_bronze(f"e{i}", "feedback_submitted", "outcome", "great product")
    result = await service_mod.get_semantic_service().create_replay_job(
        TENANT, dry_run=True, filters={}
    )
    assert result["dry_run"] is True
    assert result["scanned"] == 3
    assert result["replayed"] == 3  # would-replay
    # Nothing persisted on a dry run.
    assert await get_store().list_semantic(TENANT) == []


async def test_real_replay_creates_observations():
    for i in range(3):
        _seed_bronze(f"e{i}", "feedback_submitted", "outcome", "great product, recommend")
    job = await SemanticReplayJobRepository().create(TENANT, dry_run=False, filters={})
    result = await SemanticReplayRunner().run(TENANT, job["id"])
    assert result["status"] == "completed"
    assert result["replayed"] == 3
    assert len(await get_store().list_semantic(TENANT)) == 3


async def test_family_filter():
    _seed_bronze("e_out", "feedback_submitted", "outcome", "great")
    _seed_bronze("e_com", "message_sent_observed", "comms", "hello there")
    job = await SemanticReplayJobRepository().create(
        TENANT, dry_run=False, filters={"families": ["comms"]}
    )
    result = await SemanticReplayRunner().run(TENANT, job["id"])
    assert result["scanned"] == 1
    rows = await get_store().list_semantic(TENANT)
    assert len(rows) == 1


async def test_replay_is_idempotent():
    _seed_bronze("e0", "feedback_submitted", "outcome", "great product")
    job1 = await SemanticReplayJobRepository().create(TENANT, dry_run=False, filters={})
    await SemanticReplayRunner().run(TENANT, job1["id"])
    job2 = await SemanticReplayJobRepository().create(TENANT, dry_run=False, filters={})
    await SemanticReplayRunner().run(TENANT, job2["id"])
    # Idempotent on idempotency_key → still a single observation.
    assert len(await get_store().list_semantic(TENANT)) == 1


async def test_control_and_status():
    svc = service_mod.get_semantic_service()
    job = await SemanticReplayJobRepository().create(TENANT, dry_run=True, filters={})
    fetched = await svc.get_replay_job(TENANT, job["id"])
    assert fetched is not None and fetched["id"] == job["id"]

    cancelled = await svc.control_replay_job(TENANT, job["id"], "cancel")
    assert cancelled is not None and cancelled["status"] == "cancelled"

    assert await svc.control_replay_job(TENANT, "nonexistent", "cancel") is None
