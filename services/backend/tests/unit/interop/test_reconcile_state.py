"""Interop reconciliation-state write path (agent 1E).

Proves the durable per-adapter reconciliation STATE is persisted as an
idempotent ``interop_reconciliation_records`` row carrying the operational
fields (configured, credential_status, reachable, latest_cursor,
latest_observation_at, lag, decode_failures, reorg_count,
reconciliation_conflicts, dead_letter_count, last_success, last_failure) plus
the source-vs-delivered snapshot — the write-path closure for the reconcile
engine.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.interop_repos import InteropReconciliationRepo
from repositories.typed_repo import reset_typed_in_memory_stores
from services.interop.reconcile import InteropReconciler


@pytest.fixture(autouse=True)
def _reset():
    reset_typed_in_memory_stores()
    yield


def _operational() -> dict:
    return {
        "provider_id": "debridge",
        "configured": True,
        "credential_status": "configured",
        "reachable": True,
        "latest_cursor": 42,
        "latest_observation_at": "2026-08-08T00:00:00+00:00",
        "lag": 3,
        "decode_failures": 1,
        "reorg_count": 2,
        "reconciliation_conflicts": 4,
        "dead_letter_count": 0,
        "last_success": "2026-08-08T00:00:00+00:00",
        "last_failure": None,
    }


async def test_persist_reconciliation_state_writes_one_current_state_row():
    repo = InteropReconciliationRepo()
    reconciler = InteropReconciler(record_repo=repo)
    row = await reconciler.persist_reconciliation_state(
        tenant_id="t1", provider_id="debridge",
        operational=_operational(), reconciliation_conflicts=4,
        source=[{"correlation_key": "c1"}],
        delivered=[{"correlation_key": "c1"}],
    )
    assert row["tenant_id"] == "t1"
    assert row["status"] == "variance_detected"
    assert row["execution_by_aether"] is False
    assert row["interop_message_id"] == ""
    compared = row["sources_compared"]
    assert compared["source"] == [{"correlation_key": "c1"}]
    assert compared["delivered"] == [{"correlation_key": "c1"}]
    assert compared["operational"]["reconciliation_conflicts"] == 4

    # A second cycle over the same provider collapses into the same row
    # (deterministic id + conflict key) — current-state, not a fork.
    await reconciler.persist_reconciliation_state(
        tenant_id="t1", provider_id="debridge",
        operational=_operational(), reconciliation_conflicts=6,
    )
    rows = await repo.find_many({"tenant_id": "t1", "correlation_key": "provider:debridge"})
    assert len(rows) == 1


async def test_reconciled_status_when_no_conflicts():
    repo = InteropReconciliationRepo()
    reconciler = InteropReconciler(record_repo=repo)
    row = await reconciler.persist_reconciliation_state(
        tenant_id="t1", provider_id="ibc", operational=_operational(),
        reconciliation_conflicts=0,
    )
    assert row["status"] == "reconciled"
    assert "reconciled" in row["difference_note"]


async def test_deterministic_id_across_instances():
    repo = InteropReconciliationRepo()
    r1 = InteropReconciler(record_repo=repo)
    r2 = InteropReconciler(record_repo=repo)
    a = await r1.persist_reconciliation_state(tenant_id="t1", provider_id="wormhole", operational={})
    b = await r2.persist_reconciliation_state(tenant_id="t1", provider_id="wormhole", operational={})
    assert a["reconciliation_id"] == b["reconciliation_id"]
    assert a["idempotency_key"] == b["idempotency_key"]
