"""DB-free tests for the Reconciled Control Plane ChangeSet store (Phase 1).

Exercises ``ChangeSetRepository`` over its in-memory fallback with ``get_pool``
pinned to None, mirroring ``test_managed_integrations_repository.py``. Tenancy
is enforced on the in-memory path exactly as it is in the SQL path; the §34
status vocabulary is enforced by ``update_status`` (transition legality lives in
``change_planning.with_status`` and is exercised by the engine tests).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.managed_integrations.change_planning import build_plan  # noqa: E402
from services.managed_integrations.change_sets_repository import (  # noqa: E402
    get_change_set_repository,
    reset_change_set_in_memory_store,
)
from services.managed_integrations.contracts import (  # noqa: E402
    ChangeSetPlanView,
    DriftRecord,
)

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
ENV_1 = "env-1"
ENV_2 = "env-2"
NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _db_free(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_pool() -> Any:  # noqa: ANN401 - matches get_pool's Any return
        return None

    monkeypatch.setattr("repositories.repos.get_pool", _no_pool)
    monkeypatch.setattr(
        "services.managed_integrations.change_sets_repository.get_pool", _no_pool
    )
    reset_change_set_in_memory_store()
    yield
    reset_change_set_in_memory_store()


def _drift(drift_type: str) -> DriftRecord:
    return DriftRecord(
        drift_id="rcdr_v",
        managed_integration_ref="mi-sdk-1",
        desired_state_ref="rcds_mi-sdk-1",
        observed_state_ref="rcobs_mi-sdk-1",
        drift_type=drift_type,
        detail="runtime below the managed_stable floor",
        first_seen_at=NOW,
        last_seen_at=NOW,
    )


def _plan(**overrides: Any) -> ChangeSetPlanView:
    plan = build_plan(
        managed_integration_ref="mi-sdk-1",
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        desired_revision="1",
        observed_revision="rcobs_mi-sdk-1",
        reconcile_sequence="seq-9",
        drift=[_drift("version_drift")],
        initiator="reconciler",
        policy_ref="policy/rollout-prod-default",
        reason="candidate from reconcile seq-9",
        now=NOW,
    )
    assert plan is not None
    return plan.model_copy(update=overrides)


@pytest.mark.asyncio
async def test_create_then_scoped_read_round_trips() -> None:
    repo = get_change_set_repository()
    created = await repo.create(_plan())
    assert created["changeset_id"].startswith("rcs_")
    assert created["status"] == "draft"
    assert created["risk"]["risk_class"] == "R1"
    assert created["changes"][0]["action"] == "repository_upgrade"
    assert created["blast_radius"]["integration_count"] == 1
    row = await repo.get(TENANT_A, ENV_1, created["changeset_id"])
    assert row is not None
    assert row["desired_revision"] == "1"
    assert row["idempotency_key"].startswith("ik_")
    assert row["reason"] == "candidate from reconcile seq-9"


@pytest.mark.asyncio
async def test_scoped_read_refuses_cross_scope_rows() -> None:
    repo = get_change_set_repository()
    created = await repo.create(_plan())
    assert await repo.get(TENANT_B, ENV_1, created["changeset_id"]) is None
    assert await repo.get(TENANT_A, ENV_2, created["changeset_id"]) is None


@pytest.mark.asyncio
async def test_get_by_key_is_the_operator_aggregate_read() -> None:
    repo = get_change_set_repository()
    created = await repo.create(_plan())
    row = await repo.get_by_key(created["changeset_id"])
    assert row is not None
    assert row["tenant_id"] == TENANT_A
    assert await repo.get_by_key("absent") is None


@pytest.mark.asyncio
async def test_list_filters_and_orders_newest_created_first() -> None:
    repo = get_change_set_repository()
    a = await repo.create(
        _plan(changeset_id="rcs_a", status="planned", created_at=NOW)
    )
    b = await repo.create(
        _plan(
            changeset_id="rcs_b",
            status="superseded",
            tenant_id=TENANT_A,
            created_at=NOW.replace(minute=1),
        )
    )
    c = await repo.create(
        _plan(
            changeset_id="rcs_c",
            status="planned",
            tenant_id=TENANT_B,
            created_at=NOW.replace(minute=2),
        )
    )

    tenant_rows = await repo.list(tenant_id=TENANT_A)
    assert {r["changeset_id"] for r in tenant_rows} == {"rcs_a", "rcs_b"}
    # newest-created first: rcs_b (created later) precedes rcs_a.
    assert [r["changeset_id"] for r in tenant_rows][0] == "rcs_b"

    planned = await repo.list(tenant_id=TENANT_A, status="planned")
    assert [r["changeset_id"] for r in planned] == ["rcs_a"]

    other = await repo.list(tenant_id=TENANT_B)
    assert [r["changeset_id"] for r in other] == ["rcs_c"]
    assert a["status"] == "planned"


@pytest.mark.asyncio
async def test_update_status_enforces_s34_vocabulary() -> None:
    repo = get_change_set_repository()
    created = await repo.create(_plan())
    with pytest.raises(ValueError, match="§34"):
        await repo.update_status(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            changeset_id=created["changeset_id"],
            status="not_a_status",
        )


@pytest.mark.asyncio
async def test_update_status_moves_to_superseded_and_stamps() -> None:
    repo = get_change_set_repository()
    created = await repo.create(_plan())
    updated = await repo.update_status(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        changeset_id=created["changeset_id"],
        status="superseded",
        superseded_at=NOW,
    )
    assert updated is not None
    assert updated["status"] == "superseded"
    assert updated["superseded_at"] == NOW.isoformat()


@pytest.mark.asyncio
async def test_update_status_absent_row_returns_none() -> None:
    repo = get_change_set_repository()
    assert (
        await repo.update_status(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            changeset_id="rcs_absent",
            status="cancelled",
        )
        is None
    )


@pytest.mark.asyncio
async def test_plan_view_round_trips_risk_and_blast_radius() -> None:
    repo = get_change_set_repository()
    plan = _plan()
    await repo.create(plan)
    row = await repo.get(TENANT_A, ENV_1, plan.changeset_id)
    assert row is not None
    assert row["risk"] == plan.risk.model_dump(mode="json")
    assert row["blast_radius"] == plan.blast_radius.model_dump(mode="json")
    assert row["integration_scope"] == ["mi-sdk-1"]
    assert row["policy_ref"] == "policy/rollout-prod-default"
    # Round-trips back into the typed view without loss.
    view = ChangeSetPlanView.model_validate(row)
    assert view.changeset_id == plan.changeset_id
    assert view.risk.risk_class == plan.risk.risk_class
    assert view.changes == plan.changes
