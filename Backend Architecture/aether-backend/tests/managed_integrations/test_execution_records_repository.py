"""DB-free tests for the Reconciled Control Plane execution-record stores (Phase 2).

Exercises ``ChangeSetEventRepository``, ``ChangeEvidenceRepository``,
``LastKnownGoodRepository``, ``ChangeSetRollbackRepository``,
``ChangeSetApprovalRepository`` and ``ActionRequiredRepository`` (all in
``services/managed_integrations/execution_records_repository.py``) over the
module-local in-memory fallback with ``get_pool`` pinned to None — the same
pattern as ``test_change_sets_repository.py``.

The in-memory path is the unit-test reference: it mirrors the SQL path's
tenancy WHERE clauses, the LKG replace-on-establish semantics, and the §12.11 /
§12.14 status vocabularies the module actually enforces. Vocabularies the
module does not check (event ``to_status``) are asserted only for what the
module does — a non-vocab value is stored, never rejected.
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

from services.managed_integrations.contracts import (  # noqa: E402
    ActionRequiredView,
    ChangeEvidenceView,
    ChangeSetApprovalView,
    LastKnownGoodView,
    RollbackRecordView,
)
from services.managed_integrations.execution_records_repository import (  # noqa: E402
    get_action_required_repository,
    get_change_evidence_repository,
    get_change_set_approval_repository,
    get_change_set_event_repository,
    get_change_set_rollback_repository,
    get_last_known_good_repository,
    reset_execution_record_stores,
)

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
ENV_1 = "env-1"
ENV_2 = "env-2"
CHANGESET_1 = "rcs_exec-1"
INTEGRATION = "mi-sdk-1"
NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _db_free(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_pool() -> Any:  # noqa: ANN401 - matches get_pool's Any return
        return None

    monkeypatch.setattr("repositories.repos.get_pool", _no_pool)
    monkeypatch.setattr(
        "services.managed_integrations.execution_records_repository.get_pool",
        _no_pool,
    )
    reset_execution_record_stores()
    yield
    reset_execution_record_stores()


def _json_ts(dt: datetime) -> str:
    """Timestamp string ``model_dump(mode="json")`` renders (trailing Z)."""
    return dt.isoformat().replace("+00:00", "Z")


def _evidence(**overrides: Any) -> ChangeEvidenceView:
    base: dict[str, Any] = dict(
        change_evidence_id="rcev_a",
        changeset_ref=CHANGESET_1,
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        initiator="executor",
        policy_ref="policy/rollout-prod-default",
        before_state_refs=["rcds_mi-sdk-1"],
        after_state_refs=["rcobs_mi-sdk-1"],
        reason="actuator apply completed",
        claim_type="verified",
        confidence="high",
        risk_ref="risk/r1",
        simulation_ref="sim/1",
        rollout_ref="rcroll_1",
        validation_refs=["rcvrf_1"],
        approval_refs=["rcap_1"],
        rollback_ref="rcrb_1",
        tenant_action_required=False,
        evidence_refs=["rcev_0"],
        contradictory_evidence_refs=[],
        started_at=NOW,
        completed_at=NOW.replace(minute=2),
    )
    base.update(overrides)
    return ChangeEvidenceView(**base)


def _lkg(**overrides: Any) -> LastKnownGoodView:
    base: dict[str, Any] = dict(
        lkg_id="rclkg_1",
        managed_integration_ref=INTEGRATION,
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        desired_state_ref="rcds_mi-sdk-1",
        artifact_ref="artifact/v1",
        mapping_refs=["mapping/mi-sdk-1@v1"],
        established_at=NOW,
    )
    base.update(overrides)
    return LastKnownGoodView(**base)


def _rollback(**overrides: Any) -> RollbackRecordView:
    base: dict[str, Any] = dict(
        rollback_id="rcrb_1",
        changeset_ref=CHANGESET_1,
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        last_known_good_ref="rclkg_1",
        rollback_actions=["actuator.revert", "actuator.pin"],
        queue_recovery_policy="rebuild",
        replay_policy="drop",
        validation_requirements=["rcvrf_1"],
        created_at=NOW,
    )
    base.update(overrides)
    return RollbackRecordView(**base)


def _approval(**overrides: Any) -> ChangeSetApprovalView:
    base: dict[str, Any] = dict(
        approval_id="rcap_a",
        changeset_ref=CHANGESET_1,
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        required_approval_ref="approval:olympus_operator",
        granted_role="operator",
        granted_by_actor="actor/olympus-1",
        decision="approved",
        note="verified by policy",
        decided_at=NOW,
    )
    base.update(overrides)
    return ChangeSetApprovalView(**base)


def _action(**overrides: Any) -> ActionRequiredView:
    base: dict[str, Any] = dict(
        action_id="rcact_a",
        tenant_ref=TENANT_A,
        managed_integration_ref=INTEGRATION,
        environment_id=ENV_1,
        action_type="approval_missing",
        reason="plan held at waiting_approval with no §21 approval recorded",
        impact="release held",
        deadline=NOW.replace(minute=30),
        required_actor="actor/olympus-operator",
        required_action="grant approval:olympus_operator",
        continuity_state="managed_holding",
        data_loss_expected=False,
        created_at=NOW,
    )
    base.update(overrides)
    return ActionRequiredView(**base)


# ── §34 append-only status history ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_events_round_trip_and_list_is_scoped_newest_first() -> None:
    repo = get_change_set_event_repository()
    appended = await repo.append(
        event_id="rcevt_a",
        changeset_id=CHANGESET_1,
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        from_status="planned",
        to_status="executing",
        reason="candidate approved",
        occurred_at=NOW,
    )
    assert appended["event_id"] == "rcevt_a"
    assert appended["from_status"] == "planned"
    assert appended["to_status"] == "executing"
    assert appended["actor"] == "executor"  # default actor
    assert appended["reason"] == "candidate approved"
    assert appended["occurred_at"] == NOW.isoformat()

    # Appended out of chronological order: list must order by occurred_at
    # (newest first), not insertion order.
    await repo.append(
        event_id="rcevt_c",
        changeset_id=CHANGESET_1,
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        from_status="executing",
        to_status="committed",
        occurred_at=NOW.replace(minute=2),
    )
    await repo.append(
        event_id="rcevt_b",
        changeset_id=CHANGESET_1,
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        from_status="committed",
        to_status="verifying",
        occurred_at=NOW.replace(minute=1),
    )
    # Same changeset id under another tenant / environment: must stay out of
    # tenant A's list even though both events are newer.
    await repo.append(
        event_id="rcevt_other_tenant",
        changeset_id=CHANGESET_1,
        tenant_id=TENANT_B,
        environment_id=ENV_1,
        to_status="executing",
        occurred_at=NOW.replace(minute=5),
    )
    await repo.append(
        event_id="rcevt_other_env",
        changeset_id=CHANGESET_1,
        tenant_id=TENANT_A,
        environment_id=ENV_2,
        to_status="executing",
        occurred_at=NOW.replace(minute=6),
    )

    rows = await repo.list_for_changeset(
        tenant_id=TENANT_A, environment_id=ENV_1, changeset_id=CHANGESET_1
    )
    assert [r["event_id"] for r in rows] == ["rcevt_c", "rcevt_b", "rcevt_a"]
    assert rows[0]["to_status"] == "committed"
    assert rows[0]["occurred_at"] == NOW.replace(minute=2).isoformat()
    assert rows[-1]["from_status"] == "planned"
    assert rows[-1]["reason"] == "candidate approved"
    assert rows[-1]["occurred_at"] == NOW.isoformat()


@pytest.mark.asyncio
async def test_events_append_does_not_enforce_to_status_vocabulary() -> None:
    repo = get_change_set_event_repository()
    # The event store records §34 transitions as facts and never validates
    # to_status (no status constant is consulted by append). Assert the module
    # behavior: an arbitrary status string is stored and round-trips.
    appended = await repo.append(
        event_id="rcevt_free",
        changeset_id=CHANGESET_1,
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        to_status="not_a_s34_status",
        actor="reconciler",
        occurred_at=NOW,
    )
    assert appended["to_status"] == "not_a_s34_status"
    rows = await repo.list_for_changeset(
        tenant_id=TENANT_A, environment_id=ENV_1, changeset_id=CHANGESET_1
    )
    assert [r["event_id"] for r in rows] == ["rcevt_free"]
    assert rows[0]["to_status"] == "not_a_s34_status"
    assert rows[0]["actor"] == "reconciler"


# ── §12.13 change evidence ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evidence_create_get_round_trip_preserves_every_field() -> None:
    repo = get_change_evidence_repository()
    view = _evidence(
        change_evidence_id="rcev_full",
        before_state_refs=["rcds_mi-sdk-1", "rcobs_mi-sdk-1@pre"],
        after_state_refs=["rcobs_mi-sdk-1@post"],
        validation_refs=["rcvrf_1", "rcvrf_2"],
        approval_refs=["rcap_1", "rcap_2"],
        evidence_refs=["rcev_prior"],
        contradictory_evidence_refs=["rcev_rival"],
    )
    created = await repo.create(view)
    assert created["change_evidence_id"] == "rcev_full"
    assert created["claim_type"] == "verified"
    assert created["confidence"] == "high"

    row = await repo.get(TENANT_A, ENV_1, "rcev_full")
    assert row is not None
    assert row["changeset_ref"] == CHANGESET_1
    assert row["tenant_id"] == TENANT_A
    assert row["environment_id"] == ENV_1
    assert row["initiator"] == "executor"
    assert row["policy_ref"] == "policy/rollout-prod-default"
    assert row["before_state_refs"] == ["rcds_mi-sdk-1", "rcobs_mi-sdk-1@pre"]
    assert row["after_state_refs"] == ["rcobs_mi-sdk-1@post"]
    assert row["reason"] == "actuator apply completed"
    assert row["risk_ref"] == "risk/r1"
    assert row["simulation_ref"] == "sim/1"
    assert row["rollout_ref"] == "rcroll_1"
    assert row["validation_refs"] == ["rcvrf_1", "rcvrf_2"]
    assert row["approval_refs"] == ["rcap_1", "rcap_2"]
    assert row["rollback_ref"] == "rcrb_1"
    assert row["tenant_action_required"] is False
    assert row["evidence_refs"] == ["rcev_prior"]
    assert row["contradictory_evidence_refs"] == ["rcev_rival"]
    # Both timestamps survive as stored (JSON-mode) timestamps.
    assert row["started_at"] == _json_ts(NOW)
    assert row["completed_at"] == _json_ts(NOW.replace(minute=2))


@pytest.mark.asyncio
async def test_evidence_row_validates_back_into_typed_view_without_loss() -> None:
    repo = get_change_evidence_repository()
    view = _evidence(
        change_evidence_id="rcev_typed",
        claim_type="correlated",
        confidence="medium",
        before_state_refs=["rcds_mi-sdk-1"],
        after_state_refs=["rcobs_mi-sdk-1@post"],
        contradictory_evidence_refs=["rcev_other"],
    )
    await repo.create(view)

    row = await repo.get(TENANT_A, ENV_1, "rcev_typed")
    assert row is not None
    reloaded = ChangeEvidenceView.model_validate(row)
    assert reloaded.change_evidence_id == "rcev_typed"
    assert reloaded.changeset_ref == view.changeset_ref
    assert reloaded.tenant_id == TENANT_A
    assert reloaded.environment_id == ENV_1
    assert reloaded.initiator == view.initiator
    assert reloaded.claim_type == "correlated"
    assert reloaded.confidence == "medium"
    assert reloaded.started_at == NOW
    assert reloaded.completed_at == NOW.replace(minute=2)
    assert reloaded.before_state_refs == view.before_state_refs
    assert reloaded.after_state_refs == view.after_state_refs
    assert reloaded.contradictory_evidence_refs == view.contradictory_evidence_refs
    assert reloaded.reason == view.reason
    assert reloaded.rollback_ref == view.rollback_ref


@pytest.mark.asyncio
async def test_evidence_get_and_list_are_scope_refusing() -> None:
    repo = get_change_evidence_repository()
    await repo.create(
        _evidence(
            change_evidence_id="rcev_a",
            started_at=NOW,
            completed_at=NOW.replace(minute=1),
        )
    )
    await repo.create(
        _evidence(
            change_evidence_id="rcev_late",
            started_at=NOW.replace(minute=2),
            completed_at=NOW.replace(minute=3),
        )
    )
    await repo.create(
        _evidence(
            change_evidence_id="rcev_mid",
            started_at=NOW.replace(minute=1),
            completed_at=NOW.replace(minute=3),
        )
    )
    await repo.create(
        _evidence(
            change_evidence_id="rcev_tenant_b",
            tenant_id=TENANT_B,
            changeset_ref=CHANGESET_1,
            started_at=NOW.replace(minute=4),
            completed_at=NOW.replace(minute=5),
        )
    )
    await repo.create(
        _evidence(
            change_evidence_id="rcev_other_changeset",
            changeset_ref="rcs_other",
            started_at=NOW.replace(minute=6),
            completed_at=NOW.replace(minute=7),
        )
    )

    # Cross-scope reads return None — the in-memory twin of the SQL WHERE
    # tenant_id=$1 AND environment_id=$2 clause.
    assert await repo.get(TENANT_B, ENV_1, "rcev_a") is None
    assert await repo.get(TENANT_A, ENV_2, "rcev_a") is None
    assert await repo.get(TENANT_A, ENV_1, "rcev_absent") is None

    # Newest-started first, and rows outside the (tenant, env, changeset)
    # scope never leak in.
    rows = await repo.list_for_changeset(
        tenant_id=TENANT_A, environment_id=ENV_1, changeset_ref=CHANGESET_1
    )
    assert [r["change_evidence_id"] for r in rows] == [
        "rcev_late",
        "rcev_mid",
        "rcev_a",
    ]
    assert rows[0]["started_at"] == _json_ts(NOW.replace(minute=2))


# ── §12.12 last-known-good ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lkg_establish_and_get_for_integration_round_trip() -> None:
    repo = get_last_known_good_repository()
    created = await repo.establish(_lkg(lkg_id="rclkg_1"))
    assert created["lkg_id"] == "rclkg_1"
    assert created["managed_integration_ref"] == INTEGRATION
    assert created["tenant_id"] == TENANT_A
    assert created["desired_state_ref"] == "rcds_mi-sdk-1"
    assert created["artifact_ref"] == "artifact/v1"
    assert created["mapping_refs"] == ["mapping/mi-sdk-1@v1"]
    assert created["established_at"] == _json_ts(NOW)
    assert created["schema_ref"] is None
    assert created["integration_contract_ref"] is None

    row = await repo.get_for_integration(TENANT_A, ENV_1, INTEGRATION)
    assert row is not None
    assert row["lkg_id"] == "rclkg_1"
    assert row["artifact_ref"] == "artifact/v1"
    assert row["mapping_refs"] == ["mapping/mi-sdk-1@v1"]
    assert row["established_at"] == _json_ts(NOW)

    # Unknown integration and unknown tenant scope both read as None.
    assert (
        await repo.get_for_integration(TENANT_A, ENV_1, "mi-other") is None
    )
    assert (
        await repo.get_for_integration(TENANT_B, ENV_1, INTEGRATION) is None
    )


@pytest.mark.asyncio
async def test_lkg_establish_replaces_prior_row_for_the_same_integration() -> None:
    repo = get_last_known_good_repository()
    await repo.establish(_lkg(lkg_id="rclkg_1", established_at=NOW))
    await repo.establish(
        _lkg(
            lkg_id="rclkg_2",
            artifact_ref="artifact/v2",
            mapping_refs=["mapping/mi-sdk-1@v1", "mapping/mi-sdk-1@v2"],
            established_at=NOW.replace(minute=1),
        )
    )

    row = await repo.get_for_integration(TENANT_A, ENV_1, INTEGRATION)
    assert row is not None
    assert row["lkg_id"] == "rclkg_2"
    assert row["artifact_ref"] == "artifact/v2"
    assert row["mapping_refs"] == [
        "mapping/mi-sdk-1@v1",
        "mapping/mi-sdk-1@v2",
    ]
    # In-memory mirror of the SQL unique-index ON CONFLICT replace: exactly one
    # LKG row remains for the integration and the old lkg id is dropped.
    assert list(repo._store) == ["rclkg_2"]  # noqa: SLF001 - in-memory twin

    # A second tenant establishing its own LKG leaves tenant A's untouched.
    await repo.establish(
        _lkg(
            lkg_id="rclkg_b",
            tenant_id=TENANT_B,
            artifact_ref="artifact/b",
            established_at=NOW.replace(minute=2),
        )
    )
    assert list(repo._store) == ["rclkg_2", "rclkg_b"]
    row_a = await repo.get_for_integration(TENANT_A, ENV_1, INTEGRATION)
    assert row_a is not None
    assert row_a["lkg_id"] == "rclkg_2"
    row_b = await repo.get_for_integration(TENANT_B, ENV_1, INTEGRATION)
    assert row_b is not None
    assert row_b["lkg_id"] == "rclkg_b"
    assert row_b["artifact_ref"] == "artifact/b"


# ── §12.11 change-set rollbacks ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rollback_create_and_get_for_changeset_round_trip() -> None:
    repo = get_change_set_rollback_repository()
    created = await repo.create(_rollback(rollback_id="rcrb_1"))
    assert created["rollback_id"] == "rcrb_1"
    assert created["changeset_ref"] == CHANGESET_1
    assert created["tenant_id"] == TENANT_A
    assert created["environment_id"] == ENV_1
    assert created["status"] == "pending"  # view default
    assert created["last_known_good_ref"] == "rclkg_1"
    assert created["rollback_actions"] == ["actuator.revert", "actuator.pin"]
    assert created["queue_recovery_policy"] == "rebuild"
    assert created["replay_policy"] == "drop"
    assert created["validation_requirements"] == ["rcvrf_1"]
    assert created["created_at"] == _json_ts(NOW)
    assert created["completed_at"] is None

    row = await repo.get_for_changeset(
        tenant_id=TENANT_A, environment_id=ENV_1, changeset_ref=CHANGESET_1
    )
    assert row is not None
    assert row["rollback_id"] == "rcrb_1"
    assert row["status"] == "pending"
    assert row["rollback_actions"] == ["actuator.revert", "actuator.pin"]
    assert row["validation_requirements"] == ["rcvrf_1"]

    # Absent changeset and cross-tenant reads return None.
    assert (
        await repo.get_for_changeset(
            tenant_id=TENANT_A, environment_id=ENV_1, changeset_ref="rcs_absent"
        )
        is None
    )
    assert (
        await repo.get_for_changeset(
            tenant_id=TENANT_B, environment_id=ENV_1, changeset_ref=CHANGESET_1
        )
        is None
    )


@pytest.mark.asyncio
async def test_rollback_update_status_enforces_s1211_vocabulary() -> None:
    repo = get_change_set_rollback_repository()
    await repo.create(_rollback(rollback_id="rcrb_1"))
    with pytest.raises(ValueError, match="§12.11"):
        await repo.update_status(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            rollback_id="rcrb_1",
            status="not_a_status",
        )


@pytest.mark.asyncio
async def test_rollback_update_status_absent_or_cross_scope_returns_none() -> None:
    repo = get_change_set_rollback_repository()
    await repo.create(_rollback(rollback_id="rcrb_1"))
    assert (
        await repo.update_status(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            rollback_id="rcrb_absent",
            status="failed",
        )
        is None
    )
    assert (
        await repo.update_status(
            tenant_id=TENANT_B,
            environment_id=ENV_1,
            rollback_id="rcrb_1",
            status="failed",
        )
        is None
    )
    assert (
        await repo.update_status(
            tenant_id=TENANT_A,
            environment_id=ENV_2,
            rollback_id="rcrb_1",
            status="failed",
        )
        is None
    )
    # The refused updates never mutated the stored row.
    row = await repo.get_for_changeset(
        tenant_id=TENANT_A, environment_id=ENV_1, changeset_ref=CHANGESET_1
    )
    assert row is not None
    assert row["status"] == "pending"
    assert row["completed_at"] is None


@pytest.mark.asyncio
async def test_rollback_update_to_rolled_back_stamps_completed_at() -> None:
    repo = get_change_set_rollback_repository()
    await repo.create(
        _rollback(rollback_id="rcrb_explicit", created_at=NOW)
    )
    updated = await repo.update_status(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollback_id="rcrb_explicit",
        status="rolled_back",
        completed_at=NOW.replace(minute=5),
    )
    assert updated is not None
    assert updated["status"] == "rolled_back"
    # Explicit completed_at is respected (isoformat on the in-memory path).
    assert updated["completed_at"] == NOW.replace(minute=5).isoformat()

    await repo.create(
        _rollback(
            rollback_id="rcrb_implicit",
            changeset_ref="rcs_exec-2",
            created_at=NOW.replace(minute=1),
        )
    )
    updated = await repo.update_status(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollback_id="rcrb_implicit",
        status="rolled_back",
    )
    assert updated is not None
    assert updated["status"] == "rolled_back"
    # No completed_at given: rolled_back stamps now — non-None.
    assert updated["completed_at"] is not None
    assert updated["created_at"] == _json_ts(NOW.replace(minute=1))

    # The update is durable: a later read sees rolled_back + stamp.
    row = await repo.get_for_changeset(
        tenant_id=TENANT_A, environment_id=ENV_1, changeset_ref="rcs_exec-2"
    )
    assert row is not None
    assert row["rollback_id"] == "rcrb_implicit"
    assert row["status"] == "rolled_back"
    assert row["completed_at"] is not None


# ── §21 change-set approvals ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approvals_round_trip_filter_and_order_by_decided_at() -> None:
    repo = get_change_set_approval_repository()
    created = await repo.create(
        _approval(
            approval_id="rcap_denied",
            decision="denied",
            note="insufficient evidence",
            decided_at=NOW,
        )
    )
    assert created["approval_id"] == "rcap_denied"
    assert created["changeset_ref"] == CHANGESET_1
    assert created["required_approval_ref"] == "approval:olympus_operator"
    assert created["granted_role"] == "operator"
    assert created["granted_by_actor"] == "actor/olympus-1"
    assert created["decision"] == "denied"
    assert created["decided_at"] == _json_ts(NOW)

    await repo.create(
        _approval(
            approval_id="rcap_newest",
            required_approval_ref="approval:tenant_owner",
            granted_role="tenant_owner",
            note="tenant confirmed",
            decided_at=NOW.replace(minute=2),
        )
    )
    await repo.create(
        _approval(
            approval_id="rcap_second",
            granted_by_actor="actor/olympus-2",
            decided_at=NOW.replace(minute=1),
        )
    )
    # Another changeset's approval must never appear in this changeset's list.
    await repo.create(
        _approval(
            approval_id="rcap_other_cs",
            changeset_ref="rcs_other",
            decided_at=NOW.replace(minute=3),
        )
    )

    rows = await repo.list_for_changeset(
        tenant_id=TENANT_A, environment_id=ENV_1, changeset_ref=CHANGESET_1
    )
    # Newest-decided first, scoped to the changeset.
    assert [r["approval_id"] for r in rows] == [
        "rcap_newest",
        "rcap_second",
        "rcap_denied",
    ]

    approved = await repo.list_for_changeset(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        changeset_ref=CHANGESET_1,
        decision="approved",
    )
    assert [r["approval_id"] for r in approved] == [
        "rcap_newest",
        "rcap_second",
    ]
    denied = await repo.list_for_changeset(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        changeset_ref=CHANGESET_1,
        decision="denied",
    )
    assert [r["approval_id"] for r in denied] == ["rcap_denied"]
    assert denied[0]["note"] == "insufficient evidence"
    assert denied[0]["decided_at"] == _json_ts(NOW)


# ── §12.14 action required ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_action_required_list_filters_and_orders_newest_created() -> None:
    repo = get_action_required_repository()
    created = await repo.create(_action(action_id="rcact_a", created_at=NOW))
    assert created["action_id"] == "rcact_a"
    assert created["tenant_ref"] == TENANT_A
    assert created["managed_integration_ref"] == INTEGRATION
    assert created["environment_id"] == ENV_1
    assert created["action_type"] == "approval_missing"
    assert created["status"] == "open"  # view default
    assert created["impact"] == "release held"
    assert created["deadline"] == _json_ts(NOW.replace(minute=30))
    assert created["required_actor"] == "actor/olympus-operator"
    assert created["continuity_state"] == "managed_holding"
    assert created["data_loss_expected"] is False
    assert created["resolution_ref"] is None
    assert created["created_at"] == _json_ts(NOW)

    await repo.create(
        _action(
            action_id="rcact_b",
            action_type="data_loss_decision",
            required_actor="actor/tenant-owner",
            created_at=NOW.replace(minute=2),
        )
    )
    await repo.create(
        _action(
            action_id="rcact_resolved",
            status="resolved",
            resolution_ref="rcresolve_0",
            created_at=NOW.replace(minute=1),
        )
    )
    await repo.create(
        _action(
            action_id="rcact_tenant_b",
            tenant_ref=TENANT_B,
            created_at=NOW.replace(minute=3),
        )
    )

    rows = await repo.list(tenant_ref=TENANT_A)
    # Newest-created first.
    assert [r["action_id"] for r in rows] == [
        "rcact_b",
        "rcact_resolved",
        "rcact_a",
    ]
    open_rows = await repo.list(tenant_ref=TENANT_A, status="open")
    assert [r["action_id"] for r in open_rows] == ["rcact_b", "rcact_a"]
    resolved_rows = await repo.list(tenant_ref=TENANT_A, status="resolved")
    assert [r["action_id"] for r in resolved_rows] == ["rcact_resolved"]
    assert resolved_rows[0]["resolution_ref"] == "rcresolve_0"

    all_rows = await repo.list()
    assert [r["action_id"] for r in all_rows] == [
        "rcact_tenant_b",
        "rcact_b",
        "rcact_resolved",
        "rcact_a",
    ]
    tenant_b_open = await repo.list(tenant_ref=TENANT_B, status="open")
    assert [r["action_id"] for r in tenant_b_open] == ["rcact_tenant_b"]


@pytest.mark.asyncio
async def test_action_required_list_enforces_s1214_vocabulary() -> None:
    repo = get_action_required_repository()
    with pytest.raises(ValueError, match="§12.14"):
        await repo.list(status="not_a_status")


@pytest.mark.asyncio
async def test_action_required_resolve_marks_open_row_resolved() -> None:
    repo = get_action_required_repository()
    await repo.create(_action(action_id="rcact_1", created_at=NOW))
    resolved = await repo.resolve(
        tenant_ref=TENANT_A,
        action_id="rcact_1",
        resolution_ref="rcresolve_1",
    )
    assert resolved is not None
    assert resolved["action_id"] == "rcact_1"
    assert resolved["status"] == "resolved"
    assert resolved["resolution_ref"] == "rcresolve_1"
    assert resolved["created_at"] == _json_ts(NOW)

    # Durable in the store: the row now only shows up under status=resolved.
    assert await repo.list(tenant_ref=TENANT_A, status="open") == []
    resolved_rows = await repo.list(tenant_ref=TENANT_A, status="resolved")
    assert [r["action_id"] for r in resolved_rows] == ["rcact_1"]
    assert resolved_rows[0]["resolution_ref"] == "rcresolve_1"


@pytest.mark.asyncio
async def test_action_required_resolve_absent_or_cross_tenant_returns_none() -> None:
    repo = get_action_required_repository()
    await repo.create(_action(action_id="rcact_1", created_at=NOW))
    assert (
        await repo.resolve(
            tenant_ref=TENANT_A,
            action_id="rcact_absent",
            resolution_ref="rcresolve_absent",
        )
        is None
    )
    assert (
        await repo.resolve(
            tenant_ref=TENANT_B,
            action_id="rcact_1",
            resolution_ref="rcresolve_other",
        )
        is None
    )
    # The refused resolves never touched the stored row.
    rows = await repo.list(tenant_ref=TENANT_A, status="open")
    assert [r["action_id"] for r in rows] == ["rcact_1"]


@pytest.mark.asyncio
async def test_action_required_resolve_already_resolved_returns_none() -> None:
    # SQL guard parity: resolve() carries WHERE ... AND status='open', so
    # re-resolving an already-resolved row must return None on every path.
    repo = get_action_required_repository()
    await repo.create(_action(action_id="rcact_1", created_at=NOW))
    await repo.resolve(
        tenant_ref=TENANT_A,
        action_id="rcact_1",
        resolution_ref="rcresolve_1",
    )
    assert (
        await repo.resolve(
            tenant_ref=TENANT_A,
            action_id="rcact_1",
            resolution_ref="rcresolve_2",
        )
        is None
    )
    # The original resolution is untouched.
    rows = await repo.list(tenant_ref=TENANT_A, status="resolved")
    assert [r["action_id"] for r in rows] == ["rcact_1"]
    assert rows[0]["resolution_ref"] == "rcresolve_1"
