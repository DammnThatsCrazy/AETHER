"""In-memory round-trip for the managed-integration + reconcile-run stores.

The repository in-memory fallback (``get_pool()`` None under ``AETHER_ENV=local``
or the pinned ``db_free`` fixture) exercises the same columnar path the operator
surface reads without a live Postgres. Tenancy is enforced in the SQL/WHERE
shape even on the in-memory path: scoped ``get`` refuses cross-tenant/cross-env
rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.managed_integrations.contracts import ReconcileRunView
from services.managed_integrations.repository import (
    ManagedIntegrationRepository,
    ReconcileRunRepository,
    get_managed_integration_repository,
    get_reconcile_run_repository,
)

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
ENV_1 = "env-1"
ENV_2 = "env-2"
NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


async def _register(repo: ManagedIntegrationRepository, **overrides) -> dict:
    kwargs = {
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


async def test_register_then_scoped_get_round_trips(db_free) -> None:
    repo = get_managed_integration_repository()
    created = await _register(repo)
    assert created["managed_integration_id"] == "mi-sdk-1"
    assert created["tenant_id"] == TENANT_A
    assert created["release_channel"] == "managed_stable"

    row = await repo.get(TENANT_A, ENV_1, "mi-sdk-1")
    assert row is not None
    assert row["integration_kind"] == "sdk_web"
    assert row["source_origin"] == "tenant"


async def test_scoped_get_refuses_cross_tenant_and_cross_env(db_free) -> None:
    repo = get_managed_integration_repository()
    await _register(repo)
    assert await repo.get(TENANT_B, ENV_1, "mi-sdk-1") is None
    assert await repo.get(TENANT_A, ENV_2, "mi-sdk-1") is None


async def test_aggregate_get_by_key_reads_any_tenant_row(db_free) -> None:
    repo = get_managed_integration_repository()
    await _register(repo, managed_integration_id="mi-sdk-global")
    row = await repo.get_by_key("mi-sdk-global")
    assert row is not None
    assert row["tenant_id"] == TENANT_A
    assert await repo.get_by_key("no-such-integration") is None


async def test_re_register_preserves_first_seen_and_created_at(db_free) -> None:
    repo = get_managed_integration_repository()
    first = await _register(repo, health_state="unknown")
    second = await _register(
        repo, health_state="healthy", release_channel="patch_auto"
    )
    assert first["first_seen_at"] == second["first_seen_at"]
    assert first["created_at"] == second["created_at"]
    assert second["health_state"] == "healthy"
    assert second["release_channel"] == "patch_auto"


async def test_list_filters_and_orders_newest_last_seen_first(db_free) -> None:
    repo = get_managed_integration_repository()
    await _register(repo, managed_integration_id="mi-a", integration_kind="sdk_web")
    await _register(repo, managed_integration_id="mi-b", integration_kind="webhook")
    await _register(repo, managed_integration_id="mi-c", integration_kind="sdk_web")

    web = await repo.list(integration_kind="sdk_web")
    assert {r["managed_integration_id"] for r in web} == {"mi-a", "mi-c"}

    tenant_rows = await repo.list(tenant_id=TENANT_A, limit=10)
    assert len(tenant_rows) == 3

    other = await repo.list(tenant_id=TENANT_B)
    assert other == []


async def test_mark_reconciled_stamps_last_run(db_free) -> None:
    repo = get_managed_integration_repository()
    await _register(repo)
    stamped = await repo.mark_reconciled(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        managed_integration_id="mi-sdk-1",
        result="actionable_drift",
        observed_state_ref="rcobs_mi-sdk-1",
        at=NOW,
    )
    assert stamped is True
    row = await repo.get(TENANT_A, ENV_1, "mi-sdk-1")
    assert row is not None
    assert row["last_reconcile_result"] == "actionable_drift"
    assert row["observed_state_ref"] == "rcobs_mi-sdk-1"


async def test_mark_reconciled_absent_row_returns_false(db_free) -> None:
    repo = get_managed_integration_repository()
    assert (
        await repo.mark_reconciled(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            managed_integration_id="nope",
            result="match",
        )
        is False
    )


async def test_reconcile_run_repo_persists_evidence_and_latest_wins(
    db_free,
) -> None:
    rr_repo = get_reconcile_run_repository()
    earlier = _run_view("mi-sdk-1", created_at=NOW)
    later = _run_view(
        "mi-sdk-1",
        created_at=NOW + timedelta(seconds=30),
        result="actionable_drift",
    )

    await rr_repo.create(earlier)
    await rr_repo.create(later)

    latest = await rr_repo.latest_for_integration(
        tenant_id=TENANT_A, environment_id=ENV_1, managed_integration_id="mi-sdk-1"
    )
    assert latest is not None
    assert latest["reconcile_id"] == later.reconcile_id
    assert latest["result"] == "actionable_drift"

    all_runs = await rr_repo.list_for_integration(
        tenant_id=TENANT_A, environment_id=ENV_1, managed_integration_id="mi-sdk-1"
    )
    assert [r["reconcile_id"] for r in all_runs] == [
        later.reconcile_id,
        earlier.reconcile_id,
    ]


async def test_reconcile_run_round_trips_drift_evidence(db_free) -> None:
    from services.managed_integrations.contracts import DriftRecord

    rr_repo = get_reconcile_run_repository()
    drift = [
        DriftRecord(
            drift_id="rcdr_abc",
            managed_integration_ref="mi-sdk-1",
            desired_state_ref="rcds_mi-sdk-1",
            observed_state_ref="rcobs_mi-sdk-1",
            drift_type="version_drift",
            detail="runtime below the managed_stable floor",
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
    ]
    view = _run_view("mi-sdk-1", created_at=NOW, result="actionable_drift")
    view = view.model_copy(update={"drift": drift})
    await rr_repo.create(view)

    latest = await rr_repo.latest_for_integration(
        tenant_id=TENANT_A, environment_id=ENV_1, managed_integration_id="mi-sdk-1"
    )
    assert latest is not None
    assert latest["drift"][0]["drift_type"] == "version_drift"
    assert latest["drift"][0]["detail"].startswith("runtime below")


async def test_reconcile_run_latest_absent_when_no_runs(db_free) -> None:
    rr_repo = get_reconcile_run_repository()
    latest = await rr_repo.latest_for_integration(
        tenant_id=TENANT_A, environment_id=ENV_1, managed_integration_id="mi-sdk-1"
    )
    assert latest is None


def _run_view(
    mi: str,
    *,
    created_at: datetime,
    result: str = "match",
    reconcile_id: str | None = None,
) -> ReconcileRunView:
    import uuid

    return ReconcileRunView(
        reconcile_id=reconcile_id or f"rcr_{uuid.uuid4().hex[:16]}",
        managed_integration_ref=mi,
        desired_state_ref=f"rcds_{mi[:12]}",
        observed_state_ref=f"rcobs_{mi[:12]}",
        desired_revision="1",
        observed_revision=f"rcobs_{mi[:12]}",
        freshness_ok=True,
        result=result,  # type: ignore[arg-type]
        created_at=created_at,
    )
