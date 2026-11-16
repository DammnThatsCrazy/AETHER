"""Simultaneous first submissions of one objective idempotency key.

Before the claim record, ``create_objective`` scanned for the key and then
inserted, so two requests that both missed the scan created two objectives.
These stores yield between every read and write to force that interleaving.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from actions.agent import runtime_repository as rr  # noqa: E402
from shared.common.common import ConflictError  # noqa: E402
from shared.store import InMemoryStore  # noqa: E402


class _YieldingStore(InMemoryStore):
    async def find(self, **filters):
        result = await super().find(**filters)
        await asyncio.sleep(0)
        return result

    async def get_versioned(self, key):
        result = await super().get_versioned(key)
        await asyncio.sleep(0)
        return result


def _repo(name: str) -> rr.AgentRuntimeRepository:
    repo = rr.AgentRuntimeRepository()
    repo.objectives = _YieldingStore(f"{name}_objectives")
    repo.plans = _YieldingStore(f"{name}_plans")
    repo.events = _YieldingStore(f"{name}_events")
    repo.objective_claims = _YieldingStore(f"{name}_claims")
    return repo


def _create(repo, tenant="t1", key="k1", goal="g", request_id="r"):
    return repo.create_objective(
        tenant_id=tenant, goal=goal, objective_type="ops", severity="low",
        priority=1, payload={"a": 1}, opened_by="u", idempotency_key=key,
        request_id=request_id,
    )


@pytest.mark.asyncio
async def test_simultaneous_first_requests_create_one_objective():
    repo = _repo("race")
    results = await asyncio.gather(*[_create(repo, request_id=f"r{i}") for i in range(20)])
    assert len({r["objective_id"] for r in results}) == 1
    assert len(await repo.objectives.find(tenant_id="t1")) == 1
    assert len(await repo.plans.find(tenant_id="t1")) == 1


@pytest.mark.asyncio
async def test_simultaneous_conflicting_content_is_rejected():
    repo = _repo("conflict")
    outcomes = await asyncio.gather(
        _create(repo, goal="first"), _create(repo, goal="second"), return_exceptions=True,
    )
    assert sum(isinstance(o, ConflictError) for o in outcomes) == 1
    assert len(await repo.objectives.find(tenant_id="t1")) == 1


@pytest.mark.asyncio
async def test_same_key_in_two_tenants_is_independent():
    repo = _repo("tenants")
    a, b = await asyncio.gather(_create(repo, tenant="ta"), _create(repo, tenant="tb"))
    assert a["objective_id"] != b["objective_id"]


@pytest.mark.asyncio
async def test_stale_claim_without_objective_is_finished_once():
    repo = _repo("stale")
    objective = {
        "objective_id": "obj_orphan", "tenant_id": "t1", "type": "ops", "goal": "g",
        "severity": "low", "priority": 1, "payload": {"a": 1}, "opened_by": "u",
        "idempotency_key": "k1", "status": "queued",
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
        "paused_at": None, "cancelled_at": None,
    }
    old = (datetime.now(timezone.utc) - timedelta(seconds=rr.OBJECTIVE_CLAIM_STALE_SECONDS + 5)).isoformat()
    await repo.objective_claims.set(rr.objective_claim_key("t1", "k1"), {
        "tenant_id": "t1", "idempotency_key": "k1",
        "fingerprint": rr.objective_request_fingerprint("t1", "g", "ops", "low", 1, {"a": 1}),
        "objective": objective, "claimed_at": old,
    })
    results = await asyncio.gather(*[_create(repo, request_id=f"r{i}") for i in range(5)])
    assert {r["objective_id"] for r in results} == {"obj_orphan"}
    assert len(await repo.objectives.find(tenant_id="t1")) == 1
    assert len(await repo.plans.find(tenant_id="t1")) == 1


@pytest.mark.asyncio
async def test_failed_takeover_releases_its_lease_so_the_key_recovers():
    """A takeover whose write fails must not leave the key stuck forever."""
    repo = _repo("lease")
    objective = {
        "objective_id": "obj_orphan2", "tenant_id": "t1", "type": "ops", "goal": "g",
        "severity": "low", "priority": 1, "payload": {"a": 1}, "opened_by": "u",
        "idempotency_key": "k1", "status": "queued",
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
        "paused_at": None, "cancelled_at": None,
    }
    old = (datetime.now(timezone.utc) - timedelta(seconds=rr.OBJECTIVE_CLAIM_STALE_SECONDS + 5)).isoformat()
    await repo.objective_claims.set(rr.objective_claim_key("t1", "k1"), {
        "tenant_id": "t1", "idempotency_key": "k1",
        "fingerprint": rr.objective_request_fingerprint("t1", "g", "ops", "low", 1, {"a": 1}),
        "objective": objective, "claimed_at": old,
    })

    original_set = repo.objectives.set
    failures = {"left": 1}

    async def flaky_set(key, value, ttl_seconds=0):
        if failures["left"]:
            failures["left"] -= 1
            raise RuntimeError("store unavailable")
        return await original_set(key, value, ttl_seconds)

    repo.objectives.set = flaky_set
    with pytest.raises(RuntimeError):
        await _create(repo)
    recovered = await _create(repo)
    assert recovered["objective_id"] == "obj_orphan2"
    assert await repo.objectives.get("obj_orphan2") is not None


@pytest.mark.asyncio
async def test_expired_lease_from_a_dead_repairer_is_taken_over():
    repo = _repo("dead-lease")
    old = (datetime.now(timezone.utc) - timedelta(seconds=rr.OBJECTIVE_CLAIM_STALE_SECONDS + 5)).isoformat()
    objective = {
        "objective_id": "obj_orphan3", "tenant_id": "t1", "type": "ops", "goal": "g",
        "severity": "low", "priority": 1, "payload": {"a": 1}, "opened_by": "u",
        "idempotency_key": "k1", "status": "queued", "created_at": old, "updated_at": old,
        "paused_at": None, "cancelled_at": None,
    }
    await repo.objective_claims.set(rr.objective_claim_key("t1", "k1"), {
        "tenant_id": "t1", "idempotency_key": "k1",
        "fingerprint": rr.objective_request_fingerprint("t1", "g", "ops", "low", 1, {"a": 1}),
        "objective": objective, "claimed_at": old,
        "repair_token": "repair_dead", "repair_started_at": old,
    })
    result = await _create(repo)
    assert result["objective_id"] == "obj_orphan3"
    assert await repo.objectives.get("obj_orphan3") is not None
