"""End-to-end Phase-1 ChangeSet flow (§32 steps 11–15, §34, §35) — no executor.

The honest Phase-1 path an operator surface will support: a reconcile run
classifies actionable *version* drift → ``build_plan`` turns it into a
candidate ChangeSet (draft) with one ``repository_upgrade`` remediation →
§35 guards pass while the guard revisions hold → promotion to ``planned``
persists through ``ChangeSetRepository`` → a guard invalidation (desired
revision advanced since planning) fails closed → the plan moves to
``superseded`` with a stamp. An illegal move toward an execution status
(``committed``) raises — nothing here ever executes a plan.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.managed_integrations.change_planning import (
    build_plan,
    validate_guards,
    with_status,
)
from services.managed_integrations.change_sets_repository import (
    get_change_set_repository,
)
from services.managed_integrations.contracts import (
    DesiredStateSpec,
    ObservedStateSnapshot,
)
from services.managed_integrations.desired_policy import build_desired_state
from services.managed_integrations.reconciler import (
    DEFAULT_FRESHNESS_WINDOW_SECONDS,
    reconcile,
)

TENANT = "tenant-a"
ENV = "env-1"
NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _flow_db_free(monkeypatch: pytest.MonkeyPatch) -> None:
    # The in-memory store is cleared by the shared _reset_rcp_stores fixture;
    # this only pins get_pool None so repo writes never reach a live DB.
    async def _no_pool():
        return None

    monkeypatch.setattr(
        "services.managed_integrations.change_sets_repository.get_pool", _no_pool
    )


def _desired() -> DesiredStateSpec:
    return build_desired_state(
        managed_integration_id="mi-sdk-1",
        tenant_id=TENANT,
        environment_id=ENV,
        release_channel="managed_stable",
    )


def _observed() -> ObservedStateSnapshot:
    return ObservedStateSnapshot(
        observed_state_id="rcobs_mi-sdk-1",
        managed_integration_ref="mi-sdk-1",
        tenant_id=TENANT,
        environment_id=ENV,
        observed_at=NOW - timedelta(seconds=5),
        received_at=NOW,
        availability="available",
        runtime_version="6.4.2",  # read_compatible: below the managed_stable floor
        reported_source_identity="mi-sdk-1",
    )


def _reconcile_view():
    return reconcile(
        managed_integration_id="mi-sdk-1",
        tenant_id=TENANT,
        environment_id=ENV,
        integration_kind="sdk_web",
        expected_identity="mi-sdk-1",
        desired=_desired(),
        observed=_observed(),
        observed_capabilities=None,
        freshness_window_seconds=DEFAULT_FRESHNESS_WINDOW_SECONDS,
        now=NOW,
    )


@pytest.mark.asyncio
async def test_reconcile_to_promote_to_supersede_full_flow() -> None:
    # 1. Reconcile classifies actionable version drift (no writes yet).
    view = _reconcile_view()
    assert view.result == "actionable_drift"
    assert [d.drift_type for d in view.drift] == ["version_drift"]

    # 2. The run becomes a candidate ChangeSet (draft) with one remediation.
    plan = build_plan(
        managed_integration_ref=view.managed_integration_ref,
        tenant_id=TENANT,
        environment_id=ENV,
        desired_revision=view.desired_revision,
        observed_revision=view.observed_revision,
        reconcile_sequence=view.reconcile_id,
        drift=view.drift,
        initiator="reconciler",
        policy_ref="policy/rollout-prod-default",
        now=NOW,
    )
    assert plan is not None
    assert plan.status == "draft"
    assert [c.action for c in plan.changes] == ["repository_upgrade"]
    # Version remediation is behavioral -> R1; automatic under policy (simulate
    # first), no approval required.
    assert plan.risk.risk_class == "R1"
    assert plan.risk.automation_allowed is True
    assert plan.risk.required_approval_refs == []
    assert plan.blast_radius.integration_count == 1
    assert plan.blast_radius.actionable_drift_types == ["version_drift"]

    # 3. §35 guards hold against the revisions it was planned against.
    ok = validate_guards(
        plan,
        current_desired_revision=view.desired_revision,
        current_observed_revision=view.observed_revision,
    )
    assert ok.ok is True

    # 4. Promote to planned and persist; the operator list surface sees it.
    promoted = with_status(plan, "planned", now=NOW)
    assert promoted.superseded_at is None
    repo = get_change_set_repository()
    await repo.create(promoted)
    rows = await repo.list(tenant_id=TENANT, status="planned")
    assert [r["changeset_id"] for r in rows] == [plan.changeset_id]
    stored = await repo.get(TENANT, ENV, plan.changeset_id)
    assert stored is not None
    assert stored["desired_revision"] == view.desired_revision
    assert stored["risk"]["risk_class"] == "R1"

    # 5. Guard invalidation: desired state advanced after planning.
    advanced = validate_guards(
        plan,
        current_desired_revision=f"{view.desired_revision}-next",
        current_observed_revision=view.observed_revision,
    )
    assert advanced.ok is False
    assert "desired_revision advanced" in (advanced.reason or "")

    # 6. Supersede and persist the move with a stamp.
    superseded = with_status(promoted, "superseded", now=NOW)
    assert superseded.status == "superseded"
    assert superseded.superseded_at == NOW
    updated = await repo.update_status(
        tenant_id=TENANT,
        environment_id=ENV,
        changeset_id=plan.changeset_id,
        status="superseded",
        superseded_at=NOW,
    )
    assert updated is not None
    assert updated["status"] == "superseded"
    assert updated["superseded_at"] == NOW.isoformat()

    # 7. Terminal: a superseded plan cannot move again, and no Phase-1 plan may
    #    move toward an execution status (fail closed; no executor exists).
    with pytest.raises(ValueError, match="illegal ChangeSet transition"):
        with_status(superseded, "cancelled", now=NOW)
    with pytest.raises(ValueError, match="illegal ChangeSet transition"):
        with_status(plan, "committed", now=NOW)
