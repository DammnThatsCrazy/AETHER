"""Focused checks for the process-local replay run identity guard."""

import pytest

from services.ingestion import replay
from shared.common.common import ConflictError


@pytest.fixture(autouse=True)
def clear_replay_journal():
    replay.reset_run_journal()
    yield
    replay.reset_run_journal()


@pytest.mark.asyncio
async def test_same_run_id_is_scoped_to_tenant(monkeypatch):
    calls = []

    async def observations(tenant_id, **kwargs):
        calls.append(tenant_id)
        return []

    monkeypatch.setattr(replay, "iter_bronze_observations", observations)
    first = await replay.replay_events("tenant-a", dry_run=True, replay_run_id="run-1")
    replayed = await replay.replay_events("tenant-a", dry_run=True, replay_run_id="run-1")
    other_tenant = await replay.replay_events(
        "tenant-b", dry_run=True, replay_run_id="run-1"
    )

    assert first == replayed
    assert other_tenant["replay_run_id"] == first["replay_run_id"]
    assert calls == ["tenant-a", "tenant-b"]


@pytest.mark.asyncio
async def test_reusing_run_id_with_different_scope_conflicts(monkeypatch):
    async def observations(tenant_id, **kwargs):
        return []

    monkeypatch.setattr(replay, "iter_bronze_observations", observations)
    await replay.replay_events("tenant-a", dry_run=True, replay_run_id="run-2")

    with pytest.raises(ConflictError):
        await replay.replay_events(
            "tenant-a", dry_run=True, event_types=["account.created"], replay_run_id="run-2"
        )


@pytest.mark.asyncio
async def test_partial_publish_failure_is_reported_and_not_retried(monkeypatch):
    async def observations(tenant_id, **kwargs):
        return [{
            "tenant_id": tenant_id,
            "event_id": "event-1",
            "event_type": "account.created",
            "event_family": None,
            "occurred_at": None,
            "flat": {"event_id": "event-1", "event_type": "account.created"},
            "bronze_ref": "bronze-1",
        }]

    monkeypatch.setattr(replay, "iter_bronze_observations", observations)
    monkeypatch.setenv("AETHER_ENV", "local")
    from repositories import repos

    async def no_pool():
        return None

    monkeypatch.setattr(repos, "get_pool", no_pool)
    monkeypatch.setattr(replay, "validate_and_stamp", lambda *a, **k: type(
        "Result", (), {"accepted": True, "envelope": {}}
    )())

    class Adapter:
        def build_observation_envelope(self, flat):
            return type("Envelope", (), {"to_bronze_additive": lambda self: {}})()

    monkeypatch.setattr(replay, "ReplayIngressAdapter", Adapter)

    class Producer:
        mode = "in-memory"
        calls = 0

        async def publish(self, event):
            self.calls += 1
            raise RuntimeError("simulated process boundary failure")

    producer = Producer()
    result = await replay.replay_events(
        "tenant-a", replay_run_id="run-3", producer=producer
    )
    repeated = await replay.replay_events(
        "tenant-a", replay_run_id="run-3", producer=producer
    )

    assert result["status"] == "partial"
    assert result["published"] == 0
    assert repeated == result
    assert producer.calls == 1
