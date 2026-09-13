"""DB-free tests for the Reconciled Control Plane §29 fleet stores (Phase 4).

Exercises ``FleetUpdatePolicyRepository`` and ``FleetUpgradePlanRepository``
(both in ``services/managed_integrations/fleet_controller_repository.py``)
over the module-local in-memory fallback with ``get_pool`` pinned to None —
the same pattern as ``test_execution_records_repository.py``.

The in-memory path is the unit-test reference: it mirrors the SQL path's
tenancy WHERE clauses and the vocabularies the module enforces. Vocabularies
the module checks — channel over ``MANAGED_RELEASE_CHANNELS`` (§28/§29), rings
over ``ROLLOUT_RINGS`` (§40), integration kind over ``MANAGED_INTEGRATION_KINDS``
(§6), artifact kind over ``ROLLOUT_ARTIFACT_KINDS`` (§40), behavior over
``UPGRADE_BEHAVIOR_VALUES`` (§30, plus the honest ``unknown`` sentinel for
kinds with no §30 row), candidate class + execution path over the §29 plan
vocabularies — are asserted exactly; the *eligibility policy* that decides
those values lives in the ``fleet_controller`` engine, so this file stores
whatever vocab-valid value a caller supplies and only rejects non-vocabulary
values. The one-policy-per-channel rule (§29) is asserted on ``create``.
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

from services.managed_integrations.fleet_controller_repository import (  # noqa: E402
    FleetUpdatePolicyRow,
    FleetUpgradePlanRow,
    get_fleet_update_policy_repository,
    get_fleet_upgrade_plan_repository,
    reset_fleet_controller_stores,
)

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
ENV_1 = "env-1"
ENV_2 = "env-2"
INTEGRATION = "mi-conn-1"
NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _db_free(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_pool() -> Any:  # noqa: ANN401 - matches get_pool's Any return
        return None

    monkeypatch.setattr("repositories.repos.get_pool", _no_pool)
    monkeypatch.setattr(
        "services.managed_integrations.fleet_controller_repository.get_pool",
        _no_pool,
    )
    reset_fleet_controller_stores()
    yield
    reset_fleet_controller_stores()


def _json_ts(dt: datetime) -> str:
    """Timestamp string ``model_dump(mode="json")`` renders (trailing Z)."""
    return dt.isoformat().replace("+00:00", "Z")


def _policy(**overrides: Any) -> FleetUpdatePolicyRow:
    base: dict[str, Any] = dict(
        policy_id="rcfpol_a",
        tenant_ref=TENANT_A,
        environment_id=ENV_1,
        channel="managed_stable",
        max_ring="100%",
        created_at=NOW,
        updated_at=NOW,
    )
    base.update(overrides)
    return FleetUpdatePolicyRow(**base)


def _plan(**overrides: Any) -> FleetUpgradePlanRow:
    base: dict[str, Any] = dict(
        plan_id="rcfplan_a",
        tenant_ref=TENANT_A,
        environment_id=ENV_1,
        managed_integration_ref=INTEGRATION,
        integration_kind="connector_aether_hosted",
        artifact_kind="connector_release",
        candidate_ref="1.4.1",
        candidate_class="security",
        channel="managed_stable",
        behavior="fully_managed",
        eligible=True,
        execution_path="automatic",
        eligibility_reasons=["eligible"],
        planned_ring="100%",
        rollout_ref=None,
        created_at=NOW,
    )
    base.update(overrides)
    return FleetUpgradePlanRow(**base)


# ── §28/§29 fleet_update_policies ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_policy_create_get_round_trip_preserves_every_field() -> None:
    repo = get_fleet_update_policy_repository()
    created = await repo.create(_policy())
    assert created["policy_id"] == "rcfpol_a"
    assert created["tenant_ref"] == TENANT_A
    assert created["environment_id"] == ENV_1
    assert created["channel"] == "managed_stable"
    assert created["max_ring"] == "100%"
    assert created["created_at"] == _json_ts(NOW)
    assert created["updated_at"] == _json_ts(NOW)

    row = await repo.get(
        tenant_ref=TENANT_A, environment_id=ENV_1, channel="managed_stable"
    )
    assert row is not None
    assert row == created


@pytest.mark.asyncio
async def test_policy_create_enforces_channel_and_ring_vocabularies() -> None:
    repo = get_fleet_update_policy_repository()
    with pytest.raises(ValueError, match="§28/§29"):
        await repo.create(_policy(channel="bleeding_edge"))
    with pytest.raises(ValueError, match="§40"):
        await repo.create(_policy(max_ring="55%"))
    with pytest.raises(ValueError, match="§40"):
        await repo.create(_policy(max_ring="not-a-ring"))
    # The repository never auto-coerces a ceiling: a pinned tenant's policy is
    # still expressed with a vocab ring ceiling (its channel delivers nothing).
    await repo.create(_policy(channel="pinned", max_ring="olympus_internal"))


@pytest.mark.asyncio
async def test_policy_create_rejects_duplicate_scope_one_per_channel() -> None:
    repo = get_fleet_update_policy_repository()
    await repo.create(_policy())
    with pytest.raises(ValueError, match="§29"):
        await repo.create(
            _policy(policy_id="rcfpol_dup", max_ring="5%", updated_at=NOW)
        )
    # A different channel, environment or tenant is a distinct policy scope.
    await repo.create(
        _policy(policy_id="rcfpol_b", channel="security_auto", max_ring="20%")
    )
    await repo.create(
        _policy(policy_id="rcfpol_c", environment_id=ENV_2, max_ring="50%")
    )
    await repo.create(
        _policy(policy_id="rcfpol_d", tenant_ref=TENANT_B, max_ring="5%")
    )
    assert len(await repo.list()) == 4


@pytest.mark.asyncio
async def test_policy_get_and_list_validate_channel_filter() -> None:
    repo = get_fleet_update_policy_repository()
    await repo.create(_policy())
    with pytest.raises(ValueError, match="§28/§29"):
        await repo.get(
            tenant_ref=TENANT_A, environment_id=ENV_1, channel="nope"
        )
    with pytest.raises(ValueError, match="§28/§29"):
        await repo.list(channel="nope")
    with pytest.raises(ValueError, match="§28/§29"):
        await repo.get(
            tenant_ref=TENANT_A, environment_id=ENV_1, channel=""
        )


@pytest.mark.asyncio
async def test_policy_list_filters_scope_and_orders_newest_first() -> None:
    repo = get_fleet_update_policy_repository()
    await repo.create(
        _policy(policy_id="p1", channel="managed_stable", created_at=NOW)
    )
    await repo.create(
        _policy(
            policy_id="p2",
            channel="security_auto",
            created_at=NOW.replace(minute=1),
        )
    )
    await repo.create(
        _policy(
            policy_id="p3",
            tenant_ref=TENANT_B,
            channel="managed_stable",
            created_at=NOW.replace(minute=2),
        )
    )
    tenant_a = await repo.list(tenant_ref=TENANT_A)
    assert [p["policy_id"] for p in tenant_a] == ["p2", "p1"]
    scoped = await repo.list(tenant_ref=TENANT_A, channel="managed_stable")
    assert [p["policy_id"] for p in scoped] == ["p1"]
    by_env = await repo.list(tenant_ref=TENANT_B, environment_id=ENV_1)
    assert [p["policy_id"] for p in by_env] == ["p3"]
    assert await repo.list(tenant_ref=TENANT_A, limit=1) == [tenant_a[0]]


@pytest.mark.asyncio
async def test_policy_update_max_ring_stamps_updated_at() -> None:
    repo = get_fleet_update_policy_repository()
    await repo.create(_policy())
    later = NOW.replace(minute=10)
    updated = await repo.update_max_ring(
        tenant_ref=TENANT_A,
        environment_id=ENV_1,
        channel="managed_stable",
        max_ring="20%",
        at=later,
    )
    assert updated is not None
    assert updated["policy_id"] == "rcfpol_a"
    assert updated["max_ring"] == "20%"
    # created_at is preserved; updated_at carries the stamp time.
    assert datetime.fromisoformat(updated["created_at"]) == NOW
    assert datetime.fromisoformat(updated["updated_at"]) == later
    row = await repo.get(
        tenant_ref=TENANT_A, environment_id=ENV_1, channel="managed_stable"
    )
    assert row is not None
    assert row["max_ring"] == "20%"


@pytest.mark.asyncio
async def test_policy_update_max_ring_validates_and_refuses_cross_scope() -> None:
    repo = get_fleet_update_policy_repository()
    await repo.create(_policy())
    with pytest.raises(ValueError, match="§40"):
        await repo.update_max_ring(
            tenant_ref=TENANT_A,
            environment_id=ENV_1,
            channel="managed_stable",
            max_ring="88%",
        )
    with pytest.raises(ValueError, match="§28/§29"):
        await repo.update_max_ring(
            tenant_ref=TENANT_A,
            environment_id=ENV_1,
            channel="nope",
            max_ring="20%",
        )
    # Absent scope (never created, or another tenant's row) -> None, no write.
    assert (
        await repo.update_max_ring(
            tenant_ref=TENANT_B,
            environment_id=ENV_1,
            channel="managed_stable",
            max_ring="5%",
            at=NOW,
        )
        is None
    )
    assert (
        await repo.update_max_ring(
            tenant_ref=TENANT_A,
            environment_id=ENV_1,
            channel="security_auto",
            max_ring="5%",
            at=NOW,
        )
        is None
    )
    untouched = await repo.get(
        tenant_ref=TENANT_A, environment_id=ENV_1, channel="managed_stable"
    )
    assert untouched is not None
    assert untouched["max_ring"] == "100%"


# ── §29 fleet_upgrade_plans ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_create_get_round_trip_preserves_every_field() -> None:
    repo = get_fleet_upgrade_plan_repository()
    created = await repo.create(_plan())
    assert created["plan_id"] == "rcfplan_a"
    assert created["tenant_ref"] == TENANT_A
    assert created["environment_id"] == ENV_1
    assert created["managed_integration_ref"] == INTEGRATION
    assert created["integration_kind"] == "connector_aether_hosted"
    assert created["artifact_kind"] == "connector_release"
    assert created["candidate_ref"] == "1.4.1"
    assert created["candidate_class"] == "security"
    assert created["channel"] == "managed_stable"
    assert created["behavior"] == "fully_managed"
    assert created["eligible"] is True
    assert created["execution_path"] == "automatic"
    assert created["eligibility_reasons"] == ["eligible"]
    assert created["planned_ring"] == "100%"
    assert created["rollout_ref"] is None
    assert created["created_at"] == _json_ts(NOW)

    row = await repo.get(
        tenant_ref=TENANT_A, environment_id=ENV_1, plan_id="rcfplan_a"
    )
    assert row is not None
    assert row == created


@pytest.mark.asyncio
async def test_plan_create_enforces_storage_vocabularies() -> None:
    repo = get_fleet_upgrade_plan_repository()
    with pytest.raises(ValueError, match="§6"):
        await repo.create(_plan(integration_kind="sdk_missing"))
    with pytest.raises(ValueError, match="§40"):
        await repo.create(_plan(artifact_kind="source_tarball"))
    with pytest.raises(ValueError, match="§28/§29"):
        await repo.create(_plan(channel="unstable"))
    with pytest.raises(ValueError, match="§29 candidate class"):
        await repo.create(_plan(candidate_class="major"))
    with pytest.raises(ValueError, match="§30"):
        await repo.create(_plan(behavior="fabricated"))
    with pytest.raises(ValueError, match="§29 execution path"):
        await repo.create(_plan(execution_path="self_heal"))
    with pytest.raises(ValueError, match="§40"):
        await repo.create(_plan(planned_ring="30%"))
    # The "unknown" sentinel is the one non-§30 value the store admits — the
    # engine records it for kinds with no §30 row (never a fabricated token).
    created = await repo.create(
        _plan(behavior="unknown", eligible=False, execution_path="review",
              eligibility_reasons=["unknown §30 platform behavior for kind sdk_web"])
    )
    assert created["behavior"] == "unknown"


@pytest.mark.asyncio
async def test_plan_get_is_tenant_scoped() -> None:
    repo = get_fleet_upgrade_plan_repository()
    await repo.create(_plan())
    assert (
        await repo.get(
            tenant_ref=TENANT_B, environment_id=ENV_1, plan_id="rcfplan_a"
        )
        is None
    )
    assert (
        await repo.get(
            tenant_ref=TENANT_A, environment_id=ENV_2, plan_id="rcfplan_a"
        )
        is None
    )
    assert (
        await repo.get(
            tenant_ref=TENANT_A, environment_id=ENV_1, plan_id="rcfplan_missing"
        )
        is None
    )


@pytest.mark.asyncio
async def test_plan_list_for_tenant_filters_and_orders_newest_first() -> None:
    repo = get_fleet_upgrade_plan_repository()
    await repo.create(_plan(plan_id="plan_1", created_at=NOW))
    await repo.create(
        _plan(
            plan_id="plan_2",
            candidate_ref="1.4.2",
            created_at=NOW.replace(minute=1),
        )
    )
    await repo.create(
        _plan(
            plan_id="plan_b",
            tenant_ref=TENANT_B,
            created_at=NOW.replace(minute=2),
        )
    )
    rows = await repo.list_for_tenant(tenant_ref=TENANT_A)
    assert [p["plan_id"] for p in rows] == ["plan_2", "plan_1"]
    tenant_b = await repo.list_for_tenant(tenant_ref=TENANT_B)
    assert [p["plan_id"] for p in tenant_b] == ["plan_b"]
    assert len(await repo.list_for_tenant(tenant_ref=TENANT_A, limit=1)) == 1


@pytest.mark.asyncio
async def test_plan_mark_rollout_stamps_delivery_fact() -> None:
    repo = get_fleet_upgrade_plan_repository()
    await repo.create(_plan())
    stamped = await repo.mark_rollout(
        tenant_ref=TENANT_A,
        environment_id=ENV_1,
        plan_id="rcfplan_a",
        rollout_ref="rcroll_fleet_1",
    )
    assert stamped is not None
    assert stamped["rollout_ref"] == "rcroll_fleet_1"
    assert stamped["eligible"] is True
    # The verdict fields are never rewritten by the stamp.
    assert stamped["execution_path"] == "automatic"
    assert stamped["planned_ring"] == "100%"
    # A later stamp replaces the earlier delivery fact.
    re_stamped = await repo.mark_rollout(
        tenant_ref=TENANT_A,
        environment_id=ENV_1,
        plan_id="rcfplan_a",
        rollout_ref="rcroll_fleet_2",
    )
    assert re_stamped is not None
    assert re_stamped["rollout_ref"] == "rcroll_fleet_2"


@pytest.mark.asyncio
async def test_plan_mark_rollout_refuses_absent_and_cross_tenant_rows() -> None:
    repo = get_fleet_upgrade_plan_repository()
    await repo.create(_plan())
    assert (
        await repo.mark_rollout(
            tenant_ref=TENANT_B,
            environment_id=ENV_1,
            plan_id="rcfplan_a",
            rollout_ref="rcroll_fleet_9",
        )
        is None
    )
    assert (
        await repo.mark_rollout(
            tenant_ref=TENANT_A,
            environment_id=ENV_2,
            plan_id="rcfplan_a",
            rollout_ref="rcroll_fleet_9",
        )
        is None
    )
    assert (
        await repo.mark_rollout(
            tenant_ref=TENANT_A,
            environment_id=ENV_1,
            plan_id="rcfplan_missing",
            rollout_ref="rcroll_fleet_9",
        )
        is None
    )
    row = await repo.get(
        tenant_ref=TENANT_A, environment_id=ENV_1, plan_id="rcfplan_a"
    )
    assert row is not None
    assert row["rollout_ref"] is None


@pytest.mark.asyncio
async def test_ineligible_plan_row_round_trips_with_reasons() -> None:
    repo = get_fleet_upgrade_plan_repository()
    reasons = [
        "no §29 tenant update policy for channel managed_stable",
    ]
    created = await repo.create(
        _plan(
            plan_id="rcfplan_review",
            eligible=False,
            execution_path="review",
            planned_ring=None,
            eligibility_reasons=reasons,
        )
    )
    assert created["eligible"] is False
    assert created["execution_path"] == "review"
    assert created["planned_ring"] is None
    assert created["eligibility_reasons"] == reasons
    row = await repo.get(
        tenant_ref=TENANT_A, environment_id=ENV_1, plan_id="rcfplan_review"
    )
    assert row is not None
    assert row["eligibility_reasons"] == reasons
    assert row["planned_ring"] is None
