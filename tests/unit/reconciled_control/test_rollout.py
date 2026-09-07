"""Reconciled Control Plane — §40 universal progressive-delivery engine tests (Phase 4).

Covers the Phase-4 rollout engine (``services/managed_integrations/rollout.py``)
and the durable record store it drives (``rollout_repository.py``):

* §40 ring law — the canonical ring sequence
  (``olympus_internal -> test_tenants -> 1% -> 5% -> 20% -> 50% -> 100%``) is
  exact order: the repository advances one ring at a time, never skipping, and
  never moves a stage backward except as a governed rollback.
* §12.9 health gates — numeric pass/fail per operator, fail-closed
  ``not_observable`` on missing/non-numeric evidence, and the CP-12
  availability pass set (``available``/``empty`` pass; ``missing`` /
  ``degraded`` / ``unknown`` violate).
* §39 R2 moderate decisions — :func:`evaluate_and_advance` auto-pauses on a
  gate breach (durable ``paused_reason`` + ``last_transition_at``), pauses on
  pause-condition tokens, auto-rolls-back on rollback-condition tokens,
  requires advance-condition approval tokens (never waives them), advances
  exactly one ring with the ring's ``ring_percentage``, and completes from the
  terminal ``100%`` ring.
* Governed verbs — start (idempotent), explicit rollback, resume (clears the
  pause marker; the next evaluation re-checks health).
* Flag-OFF parity — everything is importable/callable while every RCP flag
  is OFF (Phase-4 engine is exercised by tests only).

No live database is touched: the local ``_reset_rollout_stores`` fixture
empties the rollout in-memory store before/after every test, and the local
``_rollout_db_free`` fixture pins the repository ``get_pool`` import to None.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from services.managed_integrations import flags
from services.managed_integrations.contracts import (
    ROLLOUT_RINGS,
    HealthGateSpec,
    HealthSnapshotView,
    RolloutView,
    ring_percentage,
)
from services.managed_integrations.rollout import (
    create_rollout,
    evaluate_and_advance,
    evaluate_health_gates,
    health_ok,
    ring_at,
    ring_index,
    rollback,
    rollout_health_status,
    resume_after_pause,
    stage_index,
    start_rollout,
)
from services.managed_integrations.rollout_repository import (
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
def _reset_rollout_stores() -> None:
    """Empty the rollout in-memory store before and after each test."""
    reset_rollout_stores()
    yield
    reset_rollout_stores()


@pytest.fixture
def _rollout_db_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``get_pool`` to None on the rollout repository module so repo
    reads/writes always hit the in-memory store (mirrors the executor /
    change-set-flow db-free fixtures)."""

    async def _no_pool() -> Any:  # noqa: ANN401 - matches get_pool's Any return
        return None

    monkeypatch.setattr("repositories.repos.get_pool", _no_pool)
    monkeypatch.setattr(
        "services.managed_integrations.rollout_repository.get_pool",
        _no_pool,
    )


def _view(**overrides: Any) -> RolloutView:
    """§12.8 RolloutContract factory: stage-zero defaults are §40-consistent
    (``olympus_internal`` percentage 0.0); stage overrides must supply a
    matching percentage (``ring_percentage(stage)``)."""
    base: dict[str, Any] = dict(
        rollout_id="rollout-1",
        changeset_ref="rcs_roll-1",
        artifact_kind="runtime_config",
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        strategy="canary",
    )
    base.update(overrides)
    return RolloutView(**base)


def _snapshot(**overrides: Any) -> HealthSnapshotView:
    """§12.9 health snapshot factory. Healthy by default: CP-12 availability
    ``available`` and a low latency observation (gates that reference other
    axes must set them explicitly — None evidence fails closed)."""
    base: dict[str, Any] = dict(
        health_id="health-1",
        subject_ref="mi-sdk-1",
        window="5m",
        availability="available",
        latency=0.2,
        freshness=2.0,
        computed_at=NOW,
    )
    base.update(overrides)
    return HealthSnapshotView(**base)


# ── §40 ring order + advance legality ────────────────────────────────────────


def test_ring_sequence_is_law() -> None:
    # Canonical §40 order: olympus_internal is stage zero (operator/console
    # surface, not tenant traffic); test_tenants is non-production tenant
    # traffic; the % rings are the production tenant-traffic rings.
    assert ROLLOUT_RINGS == (
        "olympus_internal",
        "test_tenants",
        "1%",
        "5%",
        "20%",
        "50%",
        "100%",
    )
    assert [stage_index(ring) for ring in ROLLOUT_RINGS] == [0, 1, 2, 3, 4, 5, 6]
    assert ring_index("olympus_internal") == 0
    assert ring_index("100%") == 6
    assert ring_at(0) == "olympus_internal"
    assert ring_at(3) == "5%"
    assert ring_at(6) == "100%"
    assert ring_at(7) is None
    assert ring_at(-1) is None
    # ring_percentage: stage-zero/one rings carry no tenant traffic.
    assert ring_percentage("olympus_internal") == 0.0
    assert ring_percentage("test_tenants") == 0.0
    assert ring_percentage("1%") == 0.01
    assert ring_percentage("5%") == 0.05
    assert ring_percentage("100%") == 1.0
    with pytest.raises(ValueError, match="§40"):
        stage_index("everything_at_once")


@pytest.mark.asyncio
async def test_advance_legality_one_ring_at_a_time(_rollout_db_free) -> None:
    repo = get_rollout_repository()
    await repo.create(RolloutRecordRow(**_view().model_dump(mode="json")))
    # olympus_internal -> test_tenants -> "1%" -> "5%": consecutive advances
    # are legal and never skip a stage.
    row = await repo.update_stage(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="rollout-1",
        current_stage="test_tenants",
        percentage=ring_percentage("test_tenants"),
        at=NOW,
    )
    assert row is not None and row["current_stage"] == "test_tenants"
    row = await repo.update_stage(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="rollout-1",
        current_stage="1%",
        percentage=ring_percentage("1%"),
        at=LATER,
    )
    assert row is not None and row["current_stage"] == "1%"
    # Skipping the 5% ring from the 1% ring contradicts §40: exactly one ring
    # at a time.
    with pytest.raises(ValueError, match="one ring at a time"):
        await repo.update_stage(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            rollout_id="rollout-1",
            current_stage="20%",
            percentage=ring_percentage("20%"),
        )
    row = await repo.update_stage(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="rollout-1",
        current_stage="5%",
        percentage=ring_percentage("5%"),
        at=LATER,
    )
    assert row is not None and row["current_stage"] == "5%"
    # A stage decrease contradicts §40 order.
    with pytest.raises(ValueError, match="ring order is law"):
        await repo.update_stage(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            rollout_id="rollout-1",
            current_stage="1%",
            percentage=ring_percentage("1%"),
        )
    # ... but a governed rollback may set end_state='rolled_back' from any
    # stage (§40: a rollout can be rolled back wherever it is).
    row = await repo.update_stage(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="rollout-1",
        current_stage="1%",
        percentage=ring_percentage("1%"),
        end_state="rolled_back",
        at=LATER,
    )
    assert row is not None
    assert row["end_state"] == "rolled_back"
    # The refused writes never mutated the stored stage.
    final = await repo.get(tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="rollout-1")
    assert final is not None and final["end_state"] == "rolled_back"


# ── §12.9 health-gate evaluation ─────────────────────────────────────────────


def test_gates_numeric_pass_and_breach() -> None:
    snapshot = _snapshot(latency=0.5)
    # latency must stay below 1.0: healthy.
    assert evaluate_health_gates(
        snapshot, [HealthGateSpec(axis="latency", operator="lt", threshold=1.0)]
    ) == []
    # latency 5.0 breaches the same gate — the violation carries the observed
    # value, the operator and the threshold.
    assert evaluate_health_gates(
        _snapshot(latency=5.0),
        [HealthGateSpec(axis="latency", operator="lt", threshold=1.0)],
    ) == [
        {
            "axis": "latency",
            "operator": "lt",
            "threshold": 1.0,
            "observed": 5.0,
            "violation": "threshold_breach",
        }
    ]
    # Higher-is-better axis: ingestion_success must stay >= 0.99.
    assert evaluate_health_gates(
        _snapshot(ingestion_success=0.995),
        [HealthGateSpec(axis="ingestion_success", operator="ge", threshold=0.99)],
    ) == []
    assert evaluate_health_gates(
        _snapshot(ingestion_success=0.5),
        [HealthGateSpec(axis="ingestion_success", operator="ge", threshold=0.99)],
    ) == [
        {
            "axis": "ingestion_success",
            "operator": "ge",
            "threshold": 0.99,
            "observed": 0.5,
            "violation": "threshold_breach",
        }
    ]
    # Boundary semantics are the operator's: le passes at the threshold, lt
    # breaches at it.
    assert evaluate_health_gates(
        _snapshot(latency=1.0),
        [HealthGateSpec(axis="latency", operator="le", threshold=1.0)],
    ) == []
    assert evaluate_health_gates(
        _snapshot(latency=1.0),
        [HealthGateSpec(axis="latency", operator="lt", threshold=1.0)],
    ) != []
    # Two breached gates report two violations, each with its own payload.
    violations = evaluate_health_gates(
        _snapshot(latency=5.0, ingestion_success=0.5),
        [
            HealthGateSpec(axis="latency", operator="lt", threshold=1.0),
            HealthGateSpec(axis="ingestion_success", operator="ge", threshold=0.99),
        ],
    )
    assert [v["axis"] for v in violations] == ["latency", "ingestion_success"]
    assert [v["violation"] for v in violations] == [
        "threshold_breach",
        "threshold_breach",
    ]


def test_gate_missing_evidence_fails_closed() -> None:
    # None evidence on a numeric axis is not_observable — missing health
    # evidence never advances a rollout.
    assert evaluate_health_gates(
        _snapshot(freshness=None),
        [HealthGateSpec(axis="freshness", operator="lt", threshold=5.0)],
    ) == [
        {
            "axis": "freshness",
            "operator": "lt",
            "threshold": 5.0,
            "observed": None,
            "violation": "not_observable",
        }
    ]
    # A non-numeric status token on a status axis cannot be compared
    # numerically — fail closed (only numeric types and numeric strings
    # coerce).
    assert evaluate_health_gates(
        _snapshot(schema_validity="valid"),
        [HealthGateSpec(axis="schema_validity", operator="ge", threshold=90.0)],
    ) == [
        {
            "axis": "schema_validity",
            "operator": "ge",
            "threshold": 90.0,
            "observed": "valid",
            "violation": "not_observable",
        }
    ]
    # A numeric string DOES coerce (status axes are string-typed in §12.9).
    assert evaluate_health_gates(
        _snapshot(schema_validity="99.5"),
        [HealthGateSpec(axis="schema_validity", operator="ge", threshold=99.0)],
    ) == []


def test_availability_gate_pass_set_is_cp12_distinct() -> None:
    gate = [HealthGateSpec(axis="availability", operator="ge", threshold=1.0)]
    # available = healthy-present; empty = a *healthy* empty (no traffic yet).
    assert evaluate_health_gates(_snapshot(availability="available"), gate) == []
    assert evaluate_health_gates(_snapshot(availability="empty"), gate) == []
    # missing/degraded/unknown are CP-12-distinct from healthy — they violate
    # the gate (pass set = {"available", "empty"}).
    for unhealthy in ("missing", "degraded", "unknown"):
        violations = evaluate_health_gates(_snapshot(availability=unhealthy), gate)
        assert violations == [
            {
                "axis": "availability",
                "operator": "ge",
                "threshold": 1.0,
                "observed": unhealthy,
                "violation": f"availability:{unhealthy}",
            }
        ]


def test_health_status_rollup() -> None:
    assert rollout_health_status([]) == "pass"
    assert health_ok([]) is True
    violations = evaluate_health_gates(
        _snapshot(latency=5.0),
        [HealthGateSpec(axis="latency", operator="lt", threshold=1.0)],
    )
    assert rollout_health_status(violations) == "fail"
    assert health_ok(violations) is False


# ── engine verbs: create + start ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_rollout_records_stage_zero(_rollout_db_free) -> None:
    created = await create_rollout(_view(rollout_id="r-new"))
    assert created["rollout_id"] == "r-new"
    assert created["artifact_kind"] == "runtime_config"
    assert created["strategy"] == "canary"
    # §40: a new rollout sits at stage zero — olympus_internal, no tenant
    # traffic, no timeline stamps, in flight.
    assert created["current_stage"] == "olympus_internal"
    assert created["percentage"] == 0.0
    assert created["started_at"] is None
    assert created["last_transition_at"] is None
    assert created["completed_at"] is None
    assert created["paused_reason"] is None
    assert created["end_state"] is None
    assert created["created_at"] is not None  # DB-default-equivalent stamp
    row = await get_rollout_repository().get(
        tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-new"
    )
    assert row is not None and row["current_stage"] == "olympus_internal"


@pytest.mark.asyncio
async def test_start_rollout_is_idempotent_and_keeps_stage_zero(
    _rollout_db_free,
) -> None:
    await create_rollout(_view(rollout_id="r-start"))
    started = await start_rollout(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="r-start",
        at=NOW,
    )
    assert started["started_at"] == NOW.isoformat()
    assert started["last_transition_at"] == NOW.isoformat()
    # §40: starting is not a ring transition — stage zero stays olympus_internal.
    assert started["current_stage"] == "olympus_internal"
    # Idempotent: a second start keeps the original started_at stamp.
    again = await start_rollout(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="r-start",
        at=LATER,
    )
    assert again["started_at"] == NOW.isoformat()
    assert again["last_transition_at"] == NOW.isoformat()
    row = await get_rollout_repository().get(
        tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-start"
    )
    assert row is not None and row["started_at"] == NOW.isoformat()


@pytest.mark.asyncio
async def test_unknown_rollout_verbs_raise(_rollout_db_free) -> None:
    with pytest.raises(ValueError, match="unknown rollout"):
        await start_rollout(
            tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-absent"
        )
    with pytest.raises(ValueError, match="unknown rollout"):
        await evaluate_and_advance(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            rollout_id="r-absent",
            health_snapshot=_snapshot(),
            satisfied_condition_tokens=[],
        )
    with pytest.raises(ValueError, match="unknown rollout"):
        await rollback(
            tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-absent"
        )
    with pytest.raises(ValueError, match="unknown rollout"):
        await resume_after_pause(
            tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-absent"
        )
    # A rollout that exists under another scope is equally unknown here.
    await create_rollout(_view(rollout_id="r-other-tenant", tenant_id=TENANT_B))
    with pytest.raises(ValueError, match="unknown rollout"):
        await evaluate_and_advance(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            rollout_id="r-other-tenant",
            health_snapshot=_snapshot(),
            satisfied_condition_tokens=[],
        )


# ── §39 R2 moderate decisions ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_green_evaluation_advances_exactly_one_ring(_rollout_db_free) -> None:
    await create_rollout(_view(rollout_id="r-green"))
    decision = await evaluate_and_advance(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="r-green",
        health_snapshot=_snapshot(),
        satisfied_condition_tokens=[],
        at=NOW,
    )
    # An empty advance_conditions list means THIS record requires no approval
    # tokens (the operator chose that at creation) — a healthy evaluation
    # advances exactly one §40 ring.
    assert decision == {
        "decision": "advanced",
        "current_stage": "test_tenants",
        "percentage": 0.0,
    }
    row = await get_rollout_repository().get(
        tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-green"
    )
    assert row is not None
    assert row["current_stage"] == "test_tenants"
    assert row["percentage"] == 0.0
    assert row["last_transition_at"] == NOW.isoformat()


@pytest.mark.asyncio
async def test_advance_carries_the_ring_percentage(_rollout_db_free) -> None:
    # At the 1% ring the next ring is 5% — tenant-traffic share 0.05.
    await create_rollout(
        _view(rollout_id="r-pct", current_stage="1%", percentage=0.01)
    )
    decision = await evaluate_and_advance(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="r-pct",
        health_snapshot=_snapshot(),
        satisfied_condition_tokens=[],
        at=NOW,
    )
    assert decision == {
        "decision": "advanced",
        "current_stage": "5%",
        "percentage": 0.05,
    }
    row = await get_rollout_repository().get(
        tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-pct"
    )
    assert row is not None and row["percentage"] == 0.05


@pytest.mark.asyncio
async def test_gate_breach_auto_pauses_durably(_rollout_db_free) -> None:
    await create_rollout(
        _view(
            rollout_id="r-breach",
            current_stage="5%",
            percentage=0.05,
            health_gates=[
                HealthGateSpec(axis="latency", operator="lt", threshold=1.0)
            ],
        )
    )
    decision = await evaluate_and_advance(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="r-breach",
        health_snapshot=_snapshot(latency=5.0),
        satisfied_condition_tokens=[],
        at=NOW,
    )
    assert decision["decision"] == "paused"
    assert decision["reason"] == "health_gate: latency lt 1.0 observed 5.0"
    assert decision["violations"] == [
        {
            "axis": "latency",
            "operator": "lt",
            "threshold": 1.0,
            "observed": 5.0,
            "violation": "threshold_breach",
        }
    ]
    assert decision["current_stage"] == "5%"
    # §12.9 auto-pause is durable: paused_reason + last_transition_at persist.
    row = await get_rollout_repository().get(
        tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-breach"
    )
    assert row is not None
    assert row["paused_reason"] == "health_gate: latency lt 1.0 observed 5.0"
    assert row["last_transition_at"] == NOW.isoformat()
    # The breach never advanced the rollout.
    assert row["current_stage"] == "5%"
    assert row["end_state"] is None


@pytest.mark.asyncio
async def test_rollback_condition_auto_rolls_back(_rollout_db_free) -> None:
    await create_rollout(
        _view(
            rollout_id="r-rb-auto",
            current_stage="20%",
            percentage=0.2,
            rollback_conditions=["drop_spike"],
        )
    )
    decision = await evaluate_and_advance(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="r-rb-auto",
        health_snapshot=_snapshot(),
        satisfied_condition_tokens=["drop_spike"],
        at=NOW,
    )
    assert decision["decision"] == "rolled_back"
    assert decision["reason"] == "drop_spike"
    row = await get_rollout_repository().get(
        tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-rb-auto"
    )
    assert row is not None
    assert row["end_state"] == "rolled_back"
    assert row["completed_at"] == NOW.isoformat()  # terminal stamp
    assert row["current_stage"] == "20%"


@pytest.mark.asyncio
async def test_pause_condition_pauses_with_reason(_rollout_db_free) -> None:
    await create_rollout(
        _view(
            rollout_id="r-pause-cond",
            pause_conditions=["operator_hold"],
        )
    )
    decision = await evaluate_and_advance(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="r-pause-cond",
        health_snapshot=_snapshot(),
        satisfied_condition_tokens=["operator_hold"],
        at=NOW,
    )
    assert decision["decision"] == "paused"
    assert decision["reason"] == "condition: operator_hold"
    row = await get_rollout_repository().get(
        tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-pause-cond"
    )
    assert row is not None
    assert row["paused_reason"] == "condition: operator_hold"
    assert row["current_stage"] == "olympus_internal"
    assert row["end_state"] is None


@pytest.mark.asyncio
async def test_advance_conditions_required_and_never_waived(_rollout_db_free) -> None:
    await create_rollout(
        _view(
            rollout_id="r-approval",
            advance_conditions=["approval:olympus_operator"],
        )
    )
    # No approval token satisfied: the engine pauses — it never auto-skips an
    # approval token recorded on the rollout.
    decision = await evaluate_and_advance(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="r-approval",
        health_snapshot=_snapshot(),
        satisfied_condition_tokens=[],
        at=NOW,
    )
    assert decision["decision"] == "paused"
    assert decision["reason"] == "awaiting_advance_conditions"
    row = await get_rollout_repository().get(
        tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-approval"
    )
    assert row is not None
    assert row["paused_reason"] == "awaiting_advance_conditions"
    assert row["current_stage"] == "olympus_internal"
    # An unrelated token never substitutes for the recorded one.
    decision = await evaluate_and_advance(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="r-approval",
        health_snapshot=_snapshot(),
        satisfied_condition_tokens=["approval:someone_else"],
        at=LATER,
    )
    assert decision["decision"] == "paused"
    # The recorded token satisfied + healthy evidence advances exactly one ring.
    decision = await evaluate_and_advance(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="r-approval",
        health_snapshot=_snapshot(),
        satisfied_condition_tokens=["approval:olympus_operator"],
        at=LATER,
    )
    assert decision["decision"] == "advanced"
    assert decision["current_stage"] == "test_tenants"


@pytest.mark.asyncio
async def test_terminal_completion_only_from_100_percent(_rollout_db_free) -> None:
    await create_rollout(
        _view(rollout_id="r-term", current_stage="50%", percentage=0.5)
    )
    # 50% -> 100% is one ordinary ring advance: percentage 1.0, and
    # completed_at is NOT stamped yet (completion happens only when advancing
    # FROM the terminal 100% ring is attempted).
    decision = await evaluate_and_advance(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="r-term",
        health_snapshot=_snapshot(),
        satisfied_condition_tokens=[],
        at=NOW,
    )
    assert decision == {
        "decision": "advanced",
        "current_stage": "100%",
        "percentage": 1.0,
    }
    row = await get_rollout_repository().get(
        tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-term"
    )
    assert row is not None
    assert row["current_stage"] == "100%"
    assert row["percentage"] == 1.0
    assert row["end_state"] is None
    assert row["completed_at"] is None
    # Advancing from the terminal ring completes the rollout: end_state
    # 'completed' + completed_at stamped.
    decision = await evaluate_and_advance(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="r-term",
        health_snapshot=_snapshot(),
        satisfied_condition_tokens=[],
        at=LATER,
    )
    assert decision["decision"] == "completed"
    assert decision["current_stage"] == "100%"
    assert decision["percentage"] == 1.0
    row = await get_rollout_repository().get(
        tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-term"
    )
    assert row is not None
    assert row["end_state"] == "completed"
    assert row["completed_at"] == LATER.isoformat()
    assert row["last_transition_at"] == LATER.isoformat()


@pytest.mark.asyncio
async def test_terminal_rollout_refuses_further_verbs(_rollout_db_free) -> None:
    await create_rollout(
        _view(
            rollout_id="r-ended",
            rollback_conditions=["drop_spike"],
        )
    )
    await evaluate_and_advance(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="r-ended",
        health_snapshot=_snapshot(),
        satisfied_condition_tokens=["drop_spike"],
        at=NOW,
    )
    # A rolled-back rollout is terminal: no evaluation, no re-start, no
    # rollback-again — fail closed.
    with pytest.raises(ValueError, match="cannot evaluate"):
        await evaluate_and_advance(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            rollout_id="r-ended",
            health_snapshot=_snapshot(),
            satisfied_condition_tokens=[],
        )
    with pytest.raises(ValueError, match="cannot start"):
        await start_rollout(
            tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-ended"
        )
    with pytest.raises(ValueError, match="rollback is not legal"):
        await rollback(
            tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-ended"
        )


@pytest.mark.asyncio
async def test_explicit_rollback_is_governed_and_durable(_rollout_db_free) -> None:
    await create_rollout(
        _view(rollout_id="r-rb", current_stage="5%", percentage=0.05)
    )
    decision = await rollback(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="r-rb",
        at=NOW,
    )
    assert decision["decision"] == "rolled_back"
    assert decision["reason"] == "explicit_governed_rollback"
    row = await get_rollout_repository().get(
        tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-rb"
    )
    assert row is not None
    assert row["end_state"] == "rolled_back"
    assert row["completed_at"] == NOW.isoformat()
    assert row["last_transition_at"] == NOW.isoformat()


@pytest.mark.asyncio
async def test_resume_clears_pause_marker_and_health_recheck_decides(
    _rollout_db_free,
) -> None:
    await create_rollout(
        _view(
            rollout_id="r-resume",
            current_stage="5%",
            percentage=0.05,
            health_gates=[
                HealthGateSpec(axis="latency", operator="lt", threshold=1.0)
            ],
        )
    )
    await evaluate_and_advance(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="r-resume",
        health_snapshot=_snapshot(latency=5.0),
        satisfied_condition_tokens=[],
        at=NOW,
    )
    row = await get_rollout_repository().get(
        tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-resume"
    )
    assert row is not None and row["paused_reason"] is not None
    # Resume only clears the marker and stamps last_transition_at — it does
    # not itself advance anything.
    resumed = await resume_after_pause(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="r-resume",
        at=LATER,
    )
    assert resumed["paused_reason"] is None
    assert resumed["last_transition_at"] == LATER.isoformat()
    assert resumed["current_stage"] == "5%"
    row = await get_rollout_repository().get(
        tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-resume"
    )
    assert row is not None and row["paused_reason"] is None
    # The next evaluation re-checks health from a fresh snapshot: healthy
    # evidence advances (and the advance write keeps the marker cleared).
    decision = await evaluate_and_advance(
        tenant_id=TENANT_A,
        environment_id=ENV_1,
        rollout_id="r-resume",
        health_snapshot=_snapshot(latency=0.2),
        satisfied_condition_tokens=[],
        at=LATER,
    )
    assert decision["decision"] == "advanced"
    assert decision["current_stage"] == "20%"
    row = await get_rollout_repository().get(
        tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-resume"
    )
    assert row is not None
    assert row["paused_reason"] is None
    assert row["current_stage"] == "20%"


# ── record vocabulary + scoping ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_enforces_percentage_law_and_vocabularies(
    _rollout_db_free,
) -> None:
    # §40 percentage law: a % ring record must carry ring_percentage(stage).
    with pytest.raises(ValueError, match="§40"):
        await create_rollout(
            _view(rollout_id="r-bad-pct", current_stage="20%", percentage=0.0)
        )
    with pytest.raises(ValueError, match="§40"):
        RolloutRecordRow(
            rollout_id="r-row-bad",
            artifact_kind="runtime_config",
            current_stage="olympus_internal",
            percentage=0.5,
        )
    # Stage-zero/one rings carry 0.0 only.
    with pytest.raises(ValueError, match="§40"):
        RolloutRecordRow(
            rollout_id="r-row-bad-zero",
            artifact_kind="runtime_config",
            current_stage="test_tenants",
            percentage=0.25,
        )
    # §40 artifact-kind vocab.
    with pytest.raises(ValueError, match="§40 rollout artifact kind"):
        RolloutRecordRow(
            rollout_id="r-row-bad-kind",
            artifact_kind="not_an_artifact_kind",
            current_stage="olympus_internal",
        )
    # §40 ring vocab for current_stage.
    with pytest.raises(ValueError, match="§40 rollout ring"):
        RolloutRecordRow(
            rollout_id="r-row-bad-ring",
            artifact_kind="runtime_config",
            current_stage="99%",
        )
    # Cohort ids are §40 ring members.
    with pytest.raises(ValueError, match="§40 cohort"):
        RolloutRecordRow(
            rollout_id="r-row-bad-cohort",
            artifact_kind="runtime_config",
            cohorts=["7%"],
        )
    # end_state vocab (§12.8).
    with pytest.raises(ValueError, match="§12.8"):
        RolloutRecordRow(
            rollout_id="r-row-bad-end",
            artifact_kind="runtime_config",
            end_state="half_done",
        )
    with pytest.raises(ValueError, match="§12.8"):
        await get_rollout_repository().update_stage(
            tenant_id=TENANT_A,
            environment_id=ENV_1,
            rollout_id="r-row-bad-end",
            current_stage="olympus_internal",
            percentage=0.0,
            end_state="half_done",
        )


@pytest.mark.asyncio
async def test_repo_round_trip_and_cross_scope_none(_rollout_db_free) -> None:
    repo = get_rollout_repository()
    view = _view(
        rollout_id="r-round",
        current_stage="5%",
        percentage=0.05,
        cohorts=["1%", "5%"],
        health_gates=[HealthGateSpec(axis="latency", operator="lt", threshold=1.0)],
        advance_conditions=["approval:olympus_operator"],
        pause_conditions=["operator_hold"],
        rollback_conditions=["drop_spike"],
    )
    created = await create_rollout(view)
    assert created["cohorts"] == ["1%", "5%"]
    row = await repo.get(tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-round")
    assert row is not None
    assert row["artifact_kind"] == "runtime_config"
    assert row["current_stage"] == "5%"
    assert row["percentage"] == 0.05
    assert row["cohorts"] == ["1%", "5%"]
    assert row["health_gates"] == [
        {"axis": "latency", "operator": "lt", "threshold": 1.0}
    ]
    assert row["advance_conditions"] == ["approval:olympus_operator"]
    assert row["pause_conditions"] == ["operator_hold"]
    assert row["rollback_conditions"] == ["drop_spike"]
    # Cross-scope reads are None — the in-memory twin of the SQL WHERE
    # tenant_id=$1 AND environment_id=$2 clause.
    assert await repo.get(tenant_id=TENANT_B, environment_id=ENV_1, rollout_id="r-round") is None
    assert await repo.get(tenant_id=TENANT_A, environment_id=ENV_2, rollout_id="r-round") is None
    assert await repo.get(tenant_id=TENANT_A, environment_id=ENV_1, rollout_id="r-absent") is None


def test_flags_off_import_parity() -> None:
    # The Phase-4 engine must be inert-by-default: every RCP flag is OFF and
    # the rollout modules stay importable/callable under that default (the
    # engine is exercised by tests only — it never turns a ring on itself).
    assert flags.enabled() is False
    assert flags.reconciler_enabled() is False
    assert flags.kyber_route_enabled() is False
    assert flags.scheduler_enabled() is False
    assert ring_index("olympus_internal") == 0
    assert evaluate_health_gates(
        _snapshot(), [HealthGateSpec(axis="latency", operator="lt", threshold=1.0)]
    ) == []
