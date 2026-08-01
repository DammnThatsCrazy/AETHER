"""Smoke tests for the new Profile 360 repositories (in-memory mode)."""

from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("AETHER_ENV", "local")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from repositories.repos import (
    BehaviorProfileRepository,
    DelegationRepository,
    EntityRepository,
    IdentityClusterRepository,
    TransferRepository,
)


def _run(coro):
    return asyncio.run(coro)


def test_entity_create_and_list():
    repo = EntityRepository()
    _run(repo.create_entity("e1", "tenant1", "human", display_name="Alice"))
    _run(repo.create_entity("e2", "tenant1", "agent", display_name="Bot"))
    rows = _run(repo.list_by_tenant("tenant1", entity_type="agent"))
    assert len(rows) == 1 and rows[0]["entity_id"] == "e2"


def test_identifier_link_unlink():
    repo = IdentityClusterRepository()
    _run(repo.link("c1", "e1", "tenant1", "wallet", "0xabc"))
    rows = _run(repo.list_for_entity("e1"))
    assert len(rows) == 1
    _run(repo.unlink("c1"))
    rows_after = _run(repo.list_for_entity("e1"))
    assert rows_after == []


def test_delegation_grant_and_active_for():
    repo = DelegationRepository()
    _run(repo.grant(
        delegation_id="d1",
        tenant_id="t1",
        grantor_entity_id="grantor",
        grantee_entity_id="grantee",
        scope={"actions": ["read"], "resources": ["*"]},
    ))
    active = _run(repo.active_for("grantee", "t1"))
    assert len(active) == 1 and active[0]["delegation_id"] == "d1"
    _run(repo.revoke("d1", revoked_by_entity_id="grantor"))
    active_after = _run(repo.active_for("grantee", "t1"))
    assert active_after == []


def test_transfer_record_and_list():
    repo = TransferRepository()
    _run(repo.record_transfer(
        transfer_id="t1",
        tenant_id="tn1",
        from_entity_id="A",
        to_entity_id="B",
        asset_id="USDC",
        amount="42",
    ))
    a_rows = _run(repo.list_for_entity("A"))
    b_rows = _run(repo.list_for_entity("B"))
    assert len(a_rows) == 1 and len(b_rows) == 1


def test_behavior_snapshot_upsert():
    repo = BehaviorProfileRepository()
    _run(repo.upsert_snapshot(
        entity_id="e1",
        tenant_id="t1",
        window_start="2026-01-01T00:00:00Z",
        window_end="2026-01-08T00:00:00Z",
        automation_ratio=0.5,
        decision_latency_ms=120,
    ))
    record = _run(repo.find_by_id("e1"))
    assert record is not None and record["automation_ratio"] == 0.5
    _run(repo.upsert_snapshot(
        entity_id="e1",
        tenant_id="t1",
        window_start="2026-01-01T00:00:00Z",
        window_end="2026-01-15T00:00:00Z",
        automation_ratio=0.8,
        decision_latency_ms=200,
    ))
    record2 = _run(repo.find_by_id("e1"))
    assert record2["automation_ratio"] == 0.8
