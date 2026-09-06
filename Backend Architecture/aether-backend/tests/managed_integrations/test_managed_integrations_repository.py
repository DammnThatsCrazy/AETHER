"""DB-free tests for the Reconciled Control Plane durable stores (Phase 0).

Exercises ``ManagedIntegrationRepository`` and ``ReconcileRunRepository`` over
their in-memory fallback with ``get_pool`` pinned to None, mirroring the
data-exchange ``test_saved_mappings.py`` DB-free pattern. Tenancy is enforced
on the in-memory path exactly as it is in the SQL path.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.managed_integrations.contracts import ReconcileRunView  # noqa: E402
from services.managed_integrations.repository import (  # noqa: E402
    ManagedIntegrationRepository,
    ReconcileRunRepository,
    get_managed_integration_repository,
    get_reconcile_run_repository,
    reset_managed_integration_in_memory_store,
)

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
ENV_1 = "env-1"
ENV_2 = "env-2"


@pytest.fixture(autouse=True)
def _db_free(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_pool() -> Any:  # noqa: ANN401 - matches get_pool's Any return
        return None

    monkeypatch.setattr("repositories.repos.get_pool", _no_pool)
    monkeypatch.setattr(
        "services.managed_integrations.repository.get_pool", _no_pool
    )
    reset_managed_integration_in_memory_store()
    yield
    reset_managed_integration_in_memory_store()


async def _register(
    repo: ManagedIntegrationRepository, **overrides: Any
) -> dict:
    kwargs: dict[str, Any] = {
        "managed_integration_id": "mi-sdk-1",
        "tenant_id": TENANT_A,
        "environment_id": ENV_1,
        "integration_kind": "sdk_web",
        "source_ref": "installation-1",
        "source_origin": "tenant",
        "source_owner": "tenant",
    }
    kwargs.update(overrides)
    return await repo.register(**kwargs)


@pytest.mark.asyncio
async def test_register_and_scoped_read_round_trip() -> None:
    repo = get_managed_integration_repository()
    created = await _register(repo)
    assert created["release_channel"] == "managed_stable"
    row = await repo.get(TENANT_A, ENV_1, "mi-sdk-1")
    assert row is not None
    assert row["integration_kind"] == "sdk_web"
    assert row["health_state"] == "unknown"


@pytest.mark.asyncio
async def test_scoped_read_refuses_cross_scope_rows() -> None:
    repo = get_managed_integration_repository()
    await _register(repo)
    assert await repo.get(TENANT_B, ENV_1, "mi-sdk-1") is None
    assert await repo.get(TENANT_A, ENV_2, "mi-sdk-1") is None


@pytest.mark.asyncio
async def test_get_by_key_is_the_operator_aggregate_read() -> None:
    repo = get_managed_integration_repository()
    await _register(repo, managed_integration_id="mi-global-1")
    row = await repo.get_by_key("mi-global-1")
    assert row is not None
    assert row["tenant_id"] == TENANT_A
    assert await repo.get_by_key("absent") is None


@pytest.mark.asyncio
async def test_re_register_is_idempotent_on_first_seen() -> None:
    repo = get_managed_integration_repository()
    first = await _register(repo)
    second = await _register(repo, health_state="healthy", schema_fingerprint="fp-9")
    assert first["first_seen_at"] == second["first_seen_at"]
    assert first["created_at"] == second["created_at"]
    assert second["health_state"] == "healthy"
    assert second["schema_fingerprint"] == "fp-9"


@pytest.mark.asyncio
async def test_mark_reconciled_stamps_result_and_ref() -> None:
    repo = get_managed_integration_repository()
    await _register(repo)
    at = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)
    assert (
        await repo.mark_reconciled(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            managed_integration_id="mi-sdk-1",
            result="actionable_drift",
            observed_state_ref="rcobs_mi-sdk-1",
            at=at,
        )
        is True
    )
    row = await repo.get(TENANT_A, ENV_1, "mi-sdk-1")
    assert row is not None
    assert row["last_reconcile_result"] == "actionable_drift"
    assert row["observed_state_ref"] == "rcobs_mi-sdk-1"
    # mark_reconciled on an absent row is a no-op (returns False).
    assert (
        await repo.mark_reconciled(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            managed_integration_id="absent",
            result="match",
        )
        is False
    )


@pytest.mark.asyncio
async def test_list_filters_are_anded() -> None:
    repo = get_managed_integration_repository()
    await _register(repo, managed_integration_id="mi-a", integration_kind="sdk_web")
    await _register(repo, managed_integration_id="mi-b", integration_kind="webhook")
    rows = await repo.list(tenant_id=TENANT_A, environment_id=ENV_1)
    assert len(rows) == 2
    web = await repo.list(
        tenant_id=TENANT_A, environment_id=ENV_1, integration_kind="sdk_web"
    )
    assert [r["managed_integration_id"] for r in web] == ["mi-a"]
    assert await repo.list(tenant_id=TENANT_B) == []


@pytest.mark.asyncio
async def test_reconcile_run_repository_newest_wins() -> None:
    rr = get_reconcile_run_repository()
    base = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)
    older = _run_view("mi-sdk-1", base)
    newer = _run_view("mi-sdk-1", base + timedelta(seconds=30), result="blocked")
    await rr.create(older)
    await rr.create(newer)
    latest = await rr.latest_for_integration(
        tenant_id=TENANT_A, environment_id=ENV_1, managed_integration_id="mi-sdk-1"
    )
    assert latest is not None
    assert latest["reconcile_id"] == newer.reconcile_id
    assert latest["result"] == "blocked"
    history = await rr.list_for_integration(
        tenant_id=TENANT_A, environment_id=ENV_1, managed_integration_id="mi-sdk-1"
    )
    assert [r["reconcile_id"] for r in history] == [newer.reconcile_id, older.reconcile_id]


@pytest.mark.asyncio
async def test_reconcile_run_repository_absent_when_empty() -> None:
    rr = get_reconcile_run_repository()
    assert (
        await rr.latest_for_integration(
            tenant_id=TENANT_A, environment_id=ENV_1, managed_integration_id="mi-sdk-1"
        )
        is None
    )


@pytest.mark.asyncio
async def test_reconcile_view_persists_drift_evidence() -> None:
    rr = get_reconcile_run_repository()
    from services.managed_integrations.contracts import DriftRecord

    drift = [
        DriftRecord(
            drift_id="rcdr_123",
            managed_integration_ref="mi-sdk-1",
            desired_state_ref="rcds_mi-sdk-1",
            observed_state_ref="rcobs_mi-sdk-1",
            drift_type="version_drift",
            detail="runtime below the managed_stable floor",
            first_seen_at=datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc),
            last_seen_at=datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc),
        )
    ]
    view = ReconcileRunView(
        reconcile_id="rcr_abc",
        managed_integration_ref="mi-sdk-1",
        desired_state_ref="rcds_mi-sdk-1",
        observed_state_ref="rcobs_mi-sdk-1",
        desired_revision="1",
        observed_revision="rcobs_mi-sdk-1",
        freshness_ok=True,
        result="actionable_drift",
        note=None,
        drift=drift,
        created_at=datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc),
    )
    await rr.create(view)
    latest = await rr.latest_for_integration(
        tenant_id=TENANT_A, environment_id=ENV_1, managed_integration_id="mi-sdk-1"
    )
    assert latest is not None
    assert latest["result"] == "actionable_drift"
    assert latest["drift"][0]["drift_type"] == "version_drift"
    assert latest["drift"][0]["detail"].startswith("runtime below")


def _run_view(mi: str, created_at: datetime, result: str = "match") -> ReconcileRunView:
    import uuid

    return ReconcileRunView(
        reconcile_id=f"rcr_{uuid.uuid4().hex[:16]}",
        managed_integration_ref=mi,
        desired_state_ref=f"rcds_{mi[:12]}",
        observed_state_ref=f"rcobs_{mi[:12]}",
        desired_revision="1",
        observed_revision=f"rcobs_{mi[:12]}",
        freshness_ok=True,
        result=result,  # type: ignore[arg-type]
        created_at=created_at,
    )
