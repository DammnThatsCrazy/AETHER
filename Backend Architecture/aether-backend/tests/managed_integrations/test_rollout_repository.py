"""DB-free tests for the Reconciled Control Plane rollout store (Phase 4).

Exercises ``RolloutRepository`` (in
``services/managed_integrations/rollout_repository.py``) over the module-local
in-memory fallback with ``get_pool`` pinned to None — the same pattern as
``test_execution_records_repository.py`` and ``test_source_authority_repository.py``.

The in-memory path is the unit-test reference: it mirrors the SQL path's
tenancy WHERE clauses, the §40 ring law (exactly one ring per advance, no
stage decrease except as a governed rollback), the §12.8 terminal
``end_state`` vocabulary and the §40 percentage law the module actually
enforces. ``RolloutRecordRow`` (the storage view) validates artifact kind /
ring / cohort / end_state vocabularies and the §40 percentage-vs-stage law on
construction, so ``create`` rejects bad rows before any write on every path.
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
    ring_percentage,
)
from services.managed_integrations.rollout_repository import (  # noqa: E402
    RolloutRecordRow,
    get_rollout_repository,
    reset_rollout_stores,
)

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
ENV_1 = "env-1"
ENV_2 = "env-2"
NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)
LATER = NOW.replace(minute=5)


@pytest.fixture(autouse=True)
def _db_free(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_pool() -> Any:  # noqa: ANN401 - matches get_pool's Any return
        return None

    monkeypatch.setattr("repositories.repos.get_pool", _no_pool)
    monkeypatch.setattr(
        "services.managed_integrations.rollout_repository.get_pool",
        _no_pool,
    )
    reset_rollout_stores()
    yield
    reset_rollout_stores()


def _json_ts(dt: datetime) -> str:
    """Timestamp string ``model_dump(mode="json")`` renders (trailing Z)."""
    return dt.isoformat().replace("+00:00", "Z")


def _rollout(**overrides: Any) -> RolloutRecordRow:
    """Storage-row factory: the percentage always matches the stage's §40
    ``ring_percentage`` unless a caller overrides it deliberately."""
    stage = overrides.get("current_stage", "olympus_internal")
    base: dict[str, Any] = dict(
        rollout_id="rcroll_1",
        changeset_ref="rcs_roll-1",
        artifact_kind="runtime_config",
        strategy="canary",
        cohorts=["1%"],
        current_stage=stage,
        percentage=ring_percentage(stage),
        health_gates=[{"axis": "latency", "operator": "lt", "threshold": 1.0}],
        advance_conditions=[],
        pause_conditions=[],
        rollback_conditions=[],
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        started_at=None,
        last_transition_at=None,
        completed_at=None,
        created_at=None,
    )
    base.update(overrides)
    return RolloutRecordRow(**base)


# ── create / get round trip ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_get_round_trip_preserves_every_field() -> None:
    repo = get_rollout_repository()
    view = _rollout(
        rollout_id="rcroll_full",
        artifact_kind="sdk_compatible_projection",
        cohorts=["1%", "5%"],
        current_stage="5%",
        health_gates=[
            {"axis": "latency", "operator": "lt", "threshold": 1.0},
            {"axis": "availability", "operator": "ge", "threshold": 1.0},
        ],
        advance_conditions=["approval:olympus_operator"],
        pause_conditions=["operator_hold"],
        rollback_conditions=["drop_spike"],
        changeset_ref="rcs_roll-9",
        started_at=NOW,
    )
    created = await repo.create(view)
    assert created["rollout_id"] == "rcroll_full"
    assert created["changeset_ref"] == "rcs_roll-9"
    assert created["artifact_kind"] == "sdk_compatible_projection"
    assert created["strategy"] == "canary"
    assert created["current_stage"] == "5%"
    assert created["percentage"] == 0.05
    assert created["cohorts"] == ["1%", "5%"]
    assert created["paused_reason"] is None
    assert created["end_state"] is None
    assert created["tenant_id"] == TENANT_A
    assert created["environment_id"] == ENV_1
    assert created["started_at"] == _json_ts(NOW)
    assert created["last_transition_at"] is None
    assert created["completed_at"] is None
    assert created["created_at"] is not None  # DB-default-equivalent stamp

    row = await repo.get(tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="rcroll_full")
    assert row is not None
    assert row["artifact_kind"] == "sdk_compatible_projection"
    assert row["current_stage"] == "5%"
    assert row["percentage"] == 0.05
    assert row["cohorts"] == ["1%", "5%"]
    assert row["health_gates"] == [
        {"axis": "latency", "operator": "lt", "threshold": 1.0},
        {"axis": "availability", "operator": "ge", "threshold": 1.0},
    ]
    assert row["advance_conditions"] == ["approval:olympus_operator"]
    assert row["pause_conditions"] == ["operator_hold"]
    assert row["rollback_conditions"] == ["drop_spike"]
    assert row["paused_reason"] is None
    assert row["end_state"] is None
    assert row["started_at"] == _json_ts(NOW)
    assert row["created_at"] is not None


@pytest.mark.asyncio
async def test_row_validates_back_into_typed_view_without_loss() -> None:
    repo = get_rollout_repository()
    view = _rollout(
        rollout_id="rcroll_typed",
        artifact_kind="mapping_revision",
        current_stage="20%",
        cohorts=["1%", "5%", "20%"],
        started_at=NOW,
        last_transition_at=LATER,
    )
    await repo.create(view)

    row = await repo.get(tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="rcroll_typed")
    assert row is not None
    reloaded = RolloutRecordRow(**row)
    assert reloaded.rollout_id == "rcroll_typed"
    assert reloaded.artifact_kind == "mapping_revision"
    assert reloaded.current_stage == "20%"
    assert reloaded.percentage == 0.2
    assert reloaded.cohorts == ["1%", "5%", "20%"]
    assert reloaded.tenant_id == TENANT_A
    assert reloaded.started_at == NOW
    assert reloaded.last_transition_at == LATER
    assert reloaded.completed_at is None
    assert reloaded.end_state is None


@pytest.mark.asyncio
async def test_get_absent_or_cross_scope_returns_none() -> None:
    repo = get_rollout_repository()
    await repo.create(_rollout(rollout_id="rcroll_a"))
    assert (
        await repo.get(tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="rcroll_absent")
        is None
    )
    assert await repo.get(tenant_id=TENANT_B, environment_id=ENV_1, rollout_id="rcroll_a") is None
    assert await repo.get(tenant_id=TENANT_A, environment_id=ENV_2, rollout_id="rcroll_a") is None


# ── start ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_stamps_started_at_once_idempotently() -> None:
    repo = get_rollout_repository()
    await repo.create(_rollout(rollout_id="rcroll_start"))
    started = await repo.start(
        tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="rcroll_start", at=NOW
    )
    assert started is not None
    assert started["started_at"] == NOW.isoformat()
    assert started["last_transition_at"] == NOW.isoformat()
    # Stage zero stays olympus_internal — §40 start is not a ring transition.
    assert started["current_stage"] == "olympus_internal"
    again = await repo.start(
        tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="rcroll_start", at=LATER
    )
    assert again is not None
    assert again["started_at"] == NOW.isoformat()
    # Absent / cross-scope starts return None.
    assert (
        await repo.start(tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="rcroll_absent")
        is None
    )
    assert (
        await repo.start(tenant_id=TENANT_B, environment_id=ENV_1, rollout_id="rcroll_start")
        is None
    )


# ── update_stage: ring law + vocab ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_stage_advances_one_ring_and_stamps_transition() -> None:
    repo = get_rollout_repository()
    await repo.create(_rollout(rollout_id="rcroll_adv"))
    row = await repo.update_stage(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="rcroll_adv",
        current_stage="test_tenants",
        percentage=ring_percentage("test_tenants"),
        at=NOW,
    )
    assert row is not None
    assert row["current_stage"] == "test_tenants"
    assert row["percentage"] == 0.0
    assert row["last_transition_at"] == NOW.isoformat()
    assert row["end_state"] is None
    assert row["paused_reason"] is None  # marker stays cleared on an advance

    row = await repo.update_stage(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="rcroll_adv",
        current_stage="1%",
        percentage=ring_percentage("1%"),
        at=LATER,
    )
    assert row is not None
    assert row["current_stage"] == "1%"
    assert row["percentage"] == 0.01
    assert row["last_transition_at"] == LATER.isoformat()


@pytest.mark.asyncio
async def test_update_stage_rejects_skipped_and_backward_rings() -> None:
    repo = get_rollout_repository()
    await repo.create(
        _rollout(rollout_id="rcroll_jump", current_stage="1%")
    )
    # 1% -> 20% skips the 5% ring: §40 advances exactly one ring at a time.
    with pytest.raises(ValueError, match="one ring at a time"):
        await repo.update_stage(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            rollout_id="rcroll_jump",
            current_stage="20%",
            percentage=ring_percentage("20%"),
        )
    # 1% -> olympus_internal decreases the stage: §40 ring order is law.
    with pytest.raises(ValueError, match="ring order is law"):
        await repo.update_stage(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            rollout_id="rcroll_jump",
            current_stage="olympus_internal",
            percentage=0.0,
        )
    # The refused writes never mutated the stored row.
    row = await repo.get(tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="rcroll_jump")
    assert row is not None and row["current_stage"] == "1%"

    # A governed rollback may mark end_state='rolled_back' from any stage
    # (here a stage decrease rides along with the terminal marking).
    row = await repo.update_stage(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="rcroll_jump",
        current_stage="olympus_internal",
        percentage=0.0,
        end_state="rolled_back",
        at=NOW,
    )
    assert row is not None
    assert row["end_state"] == "rolled_back"


@pytest.mark.asyncio
async def test_update_stage_enforces_end_state_and_ring_vocabularies() -> None:
    repo = get_rollout_repository()
    await repo.create(_rollout(rollout_id="rcroll_vocab"))
    with pytest.raises(ValueError, match="§12.8"):
        await repo.update_stage(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            rollout_id="rcroll_vocab",
            current_stage="olympus_internal",
            percentage=0.0,
            end_state="half_done",
        )
    with pytest.raises(ValueError, match="§40 rollout ring"):
        await repo.update_stage(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            rollout_id="rcroll_vocab",
            current_stage="not_a_ring",
            percentage=0.0,
        )
    # The §40 percentage law is total: a write whose percentage does not match
    # ring_percentage(current_stage) is rejected on every path.
    with pytest.raises(ValueError, match="§40"):
        await repo.update_stage(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            rollout_id="rcroll_vocab",
            current_stage="20%",
            percentage=0.05,
        )
    # The refused writes never touched the stored row.
    row = await repo.get(tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="rcroll_vocab")
    assert row is not None
    assert row["current_stage"] == "olympus_internal"
    assert row["end_state"] is None


@pytest.mark.asyncio
async def test_update_stage_absent_or_cross_scope_returns_none() -> None:
    repo = get_rollout_repository()
    await repo.create(_rollout(rollout_id="rcroll_scope"))
    assert (
        await repo.update_stage(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            rollout_id="rcroll_absent",
            current_stage="test_tenants",
            percentage=0.0,
        )
        is None
    )
    assert (
        await repo.update_stage(
            tenant_id=TENANT_B,
            environment_id=ENV_1,
            rollout_id="rcroll_scope",
            current_stage="test_tenants",
            percentage=0.0,
        )
        is None
    )
    assert (
        await repo.update_stage(
            tenant_id=TENANT_A,
            environment_id=ENV_2,
            rollout_id="rcroll_scope",
            current_stage="test_tenants",
            percentage=0.0,
        )
        is None
    )
    row = await repo.get(tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="rcroll_scope")
    assert row is not None and row["current_stage"] == "olympus_internal"


@pytest.mark.asyncio
async def test_update_stage_pause_marker_and_terminal_stamps() -> None:
    repo = get_rollout_repository()
    await repo.create(_rollout(rollout_id="rcroll_pause", current_stage="5%"))
    # §12.9 auto-pause write: stage unchanged, paused_reason durable.
    paused = await repo.update_stage(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="rcroll_pause",
        current_stage="5%",
        percentage=0.05,
        paused_reason="health_gate: latency lt 1.0 observed 5.0",
        at=NOW,
    )
    assert paused is not None
    assert paused["paused_reason"] == "health_gate: latency lt 1.0 observed 5.0"
    assert paused["current_stage"] == "5%"
    assert paused["last_transition_at"] == NOW.isoformat()
    # A later write without a paused_reason clears the marker (None = not
    # paused).
    resumed = await repo.update_stage(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="rcroll_pause",
        current_stage="5%",
        percentage=0.05,
        at=LATER,
    )
    assert resumed is not None
    assert resumed["paused_reason"] is None
    # Terminal end_state stamps completed_at (explicit value, else at, else
    # now) and clears the marker. The completion write keeps the terminal
    # "100%" stage — no §40 transition is involved.
    await repo.create(_rollout(rollout_id="rcroll_term", current_stage="100%"))
    completed = await repo.update_stage(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="rcroll_term",
        current_stage="100%",
        percentage=1.0,
        end_state="completed",
        at=LATER,
    )
    assert completed is not None
    assert completed["end_state"] == "completed"
    assert completed["completed_at"] == LATER.isoformat()
    assert completed["last_transition_at"] == LATER.isoformat()

    await repo.create(_rollout(rollout_id="rcroll_rb", current_stage="20%"))
    rolled = await repo.update_stage(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="rcroll_rb",
        current_stage="20%",
        percentage=0.2,
        end_state="rolled_back",
    )
    assert rolled is not None
    assert rolled["end_state"] == "rolled_back"
    assert rolled["completed_at"] is not None  # auto-stamped (now)


# ── create-time vocabulary + §40 percentage law ──────────────────────────────


@pytest.mark.asyncio
async def test_create_rejects_bad_artifact_kind_and_ring() -> None:
    repo = get_rollout_repository()
    with pytest.raises(ValueError, match="§40 rollout artifact kind"):
        await repo.create(_rollout(artifact_kind="not_an_artifact_kind"))
    with pytest.raises(ValueError, match="§40 rollout ring"):
        await repo.create(_rollout(current_stage="99%"))
    with pytest.raises(ValueError, match="§40 cohort"):
        await repo.create(_rollout(cohorts=["7%"]))
    with pytest.raises(ValueError, match="§12.8"):
        await repo.create(_rollout(end_state="half_done"))
    assert await repo.list() == []


@pytest.mark.asyncio
async def test_create_enforces_percentage_matches_stage() -> None:
    repo = get_rollout_repository()
    # A % ring record must carry exactly ring_percentage(stage).
    with pytest.raises(ValueError, match="§40"):
        await repo.create(_rollout(current_stage="20%", percentage=0.05))
    # olympus_internal / test_tenants carry 0.0 only.
    with pytest.raises(ValueError, match="§40"):
        await repo.create(_rollout(percentage=0.05))
    with pytest.raises(ValueError, match="§40"):
        await repo.create(_rollout(current_stage="test_tenants", percentage=0.01))
    assert await repo.list() == []


# ── list filters + ordering ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_filters_and_orders_newest_created_first() -> None:
    repo = get_rollout_repository()
    await repo.create(
        _rollout(
            rollout_id="rcroll_a",
            created_at=NOW,
        )
    )
    await repo.create(
        _rollout(
            rollout_id="rcroll_newest",
            artifact_kind="connector_release",
            created_at=LATER,
        )
    )
    await repo.create(
        _rollout(
            rollout_id="rcroll_ended",
            end_state="rolled_back",
            created_at=NOW.replace(minute=1),
        )
    )
    # Another tenant's rollout never leaks into tenant A's lists.
    await repo.create(
        _rollout(
            rollout_id="rcroll_tenant_b",
            tenant_id=TENANT_B,
            created_at=NOW.replace(minute=6),
        )
    )

    rows = await repo.list()
    assert [r["rollout_id"] for r in rows] == [
        "rcroll_tenant_b",
        "rcroll_newest",
        "rcroll_ended",
        "rcroll_a",
    ]
    scoped = await repo.list(tenant_id=TENANT_A, environment_id=ENV_1)
    assert [r["rollout_id"] for r in scoped] == [
        "rcroll_newest",
        "rcroll_ended",
        "rcroll_a",
    ]
    kinds = await repo.list(tenant_id=TENANT_A, environment_id=ENV_1, artifact_kind="runtime_config")
    assert [r["rollout_id"] for r in kinds] == ["rcroll_ended", "rcroll_a"]
    terminal = await repo.list(tenant_id=TENANT_A, environment_id=ENV_1, end_state="rolled_back")
    assert [r["rollout_id"] for r in terminal] == ["rcroll_ended"]
    assert terminal[0]["end_state"] == "rolled_back"
    limited = await repo.list(tenant_id=TENANT_A, environment_id=ENV_1, limit=1)
    assert [r["rollout_id"] for r in limited] == ["rcroll_newest"]
    # end_state=None means no end-state filter — in-flight and terminal rows
    # both appear (None is the terminal-column NULL, not a filter token).
    in_flight_and_terminal = await repo.list(tenant_id=TENANT_A, environment_id=ENV_1)
    assert {r["end_state"] for r in in_flight_and_terminal} == {None, "rolled_back"}


@pytest.mark.asyncio
async def test_list_validates_vocabularies() -> None:
    repo = get_rollout_repository()
    with pytest.raises(ValueError, match="§40 rollout artifact kind"):
        await repo.list(artifact_kind="not_an_artifact_kind")
    with pytest.raises(ValueError, match="§12.8"):
        await repo.list(end_state="half_done")
