"""Reconciled Control Plane — §40 universal progressive delivery engine (Phase 4).

Phase 4 is the *decision* half of the §40 delivery layer over the durable
``rollouts`` records (:mod:`rollout_repository`, §12.8 RolloutContract + the
coordinator-approved ``paused_reason`` / ``end_state`` columns):

* :func:`evaluate_health_gates` — evaluate §12.9 HealthContract gate
  configuration against a health snapshot. Missing or non-numeric evidence
  **fails closed** (a violation is returned — missing health evidence never
  advances a rollout). The CP-12 ``availability`` axis is text, not a number:
  its gate passes only when availability is ``available`` or ``empty``
  (``empty`` is a *healthy* empty — no traffic yet); ``missing`` /
  ``degraded`` / ``unknown`` violate.
* :func:`evaluate_and_advance` — §39 R2 moderate rollout (canary +
  health-gated automatic): decide the next ring under health. Exact §40 ring
  order is law — the engine advances exactly one ring per decision, never
  skipping (the repository rejects any skipped stage write).
* :func:`start_rollout` / :func:`rollback` / :func:`resume_after_pause` —
  governed record verbs over the same store.

Phase-4 boundary — the engine only *records delivery facts*: nothing here
applies a change, turns a ring on for tenant traffic, or grants an approval.
APPROVALS and execution tokens are not the engine's job (the executor / risk
engine phases own those); an ``advance_conditions`` token is a policy/
approval token this rollout's record requires, and the engine never waives
one — an unsatisfied token pauses the rollout. An *empty* ``advance_conditions``
list means the record requires no tokens (the operator chose that at creation;
it is a recorded decision, not an engine waiver). Rings above 0% reach real
tenants only under tenant update policy + approvals — turning rings on for
real traffic sits behind the §41+ review gate; in Phase 4 this engine is
exercised by tests only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from services.managed_integrations.contracts import (
    ROLLOUT_RINGS,
    HealthGateSpec,
    HealthSnapshotView,
    RolloutView,
    is_rollout_ring,
    ring_percentage,
)
from services.managed_integrations.rollout_repository import (
    RolloutRecordRow,
    get_rollout_repository,
)

# Violation tokens an evaluation can return (the ``violation`` field):
#   "not_observable"        — axis value missing/None or non-numeric (fail closed)
#   "threshold_breach"      — numeric compare against the gate failed
#   "availability:<status>" — CP-12 availability outside the gate pass set
NOT_OBSERVABLE = "not_observable"
THRESHOLD_BREACH = "threshold_breach"

# CP-12 availability values a §12.9 availability gate treats as healthy:
# ``available`` is the healthy-present state and ``empty`` is a healthy-empty
# state (nothing to serve yet) — §6/CP-12 distinctness means ``missing``,
# ``degraded`` and ``unknown`` must fail the gate.
AVAILABILITY_GATE_PASS_SET: frozenset[str] = frozenset({"available", "empty"})

_COMPARE: dict[str, Any] = {
    "lt": lambda observed, threshold: observed < threshold,
    "le": lambda observed, threshold: observed <= threshold,
    "gt": lambda observed, threshold: observed > threshold,
    "ge": lambda observed, threshold: observed >= threshold,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── §40 ring helpers ─────────────────────────────────────────────────────────


def ring_index(ring: str) -> int:
    """Position of a ring in the canonical §40 sequence (order is law):
    ``olympus_internal`` = 0, ``test_tenants`` = 1, ``1%`` = 2, ... ``100%``
    = 6."""
    if not is_rollout_ring(ring):
        raise ValueError(
            f"unknown §40 rollout ring {ring!r} — expected one of {ROLLOUT_RINGS}"
        )
    return ROLLOUT_RINGS.index(ring)


# Export alias: the engine and its tests read the same law under both names.
stage_index = ring_index


def ring_at(index: int) -> Optional[str]:
    """Ring at a §40 sequence position; None past the terminal ``100%``."""
    if 0 <= index < len(ROLLOUT_RINGS):
        return ROLLOUT_RINGS[index]
    return None


# ── §12.9 health-gate evaluation ─────────────────────────────────────────────


def _violation(
    gate: HealthGateSpec, observed: Any, token: str
) -> dict:
    """One §12.9 gate violation, carrying the observed value verbatim."""
    return {
        "axis": gate.axis,
        "operator": gate.operator,
        "threshold": gate.threshold,
        "observed": observed,
        "violation": token,
    }


def _numeric(value: Any) -> Optional[float]:
    """Coerce a gate observation to a number when it is one.

    Only numeric types and numeric strings coerce; booleans and non-numeric
    strings return None (they are not §12.9 numeric evidence).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def evaluate_health_gates(
    snapshot: HealthSnapshotView | dict,
    gates: list[HealthGateSpec],
) -> list[dict]:
    """Evaluate §12.9 health gates against a snapshot; returns the violations.

    One dict per failed gate (passing gates produce nothing). Every axis value
    is compared numerically per the gate operator (``lt``/``le``/``gt``/``ge``)
    except the CP-12 ``availability`` text axis, whose pass set is
    :data:`AVAILABILITY_GATE_PASS_SET` = {"available", "empty"} — ``missing``,
    ``degraded`` and ``unknown`` violate regardless of operator/threshold
    (which are carried on the violation for shape parity).

    Fail-closed: an axis that is absent, None, or non-numeric never advances
    anything — it violates with token :data:`NOT_OBSERVABLE`. Numeric breaches
    violate with token :data:`THRESHOLD_BREACH`.
    """
    view = (
        snapshot
        if isinstance(snapshot, HealthSnapshotView)
        else HealthSnapshotView.model_validate(snapshot)
    )
    violations: list[dict] = []
    for gate in gates:
        spec = gate if isinstance(gate, HealthGateSpec) else HealthGateSpec(**gate)
        observed = getattr(view, spec.axis, None)
        if observed is None:
            violations.append(_violation(spec, None, NOT_OBSERVABLE))
            continue
        if spec.axis == "availability":
            if observed not in AVAILABILITY_GATE_PASS_SET:
                violations.append(
                    _violation(spec, observed, f"availability:{observed}")
                )
            continue
        numeric = _numeric(observed)
        if numeric is None:
            # Non-numeric non-None evidence cannot be compared — fail closed.
            violations.append(_violation(spec, observed, NOT_OBSERVABLE))
            continue
        compare = _COMPARE[spec.operator]
        if not compare(numeric, spec.threshold):
            violations.append(_violation(spec, observed, THRESHOLD_BREACH))
    return violations


def rollout_health_status(violations: list[dict]) -> str:
    """§12.9 health rollup over evaluated gates: any violation is ``fail``."""
    return "fail" if violations else "pass"


def health_ok(violations: list[dict]) -> bool:
    """Fail-closed health check over evaluated gates (False on any violation)."""
    return not violations


# ── §40 rollout verbs ────────────────────────────────────────────────────────


def _rollout_repo():
    return get_rollout_repository()


async def _load_rollout(
    tenant_id: str, environment_id: str, rollout_id: str
) -> dict:
    """Fetch a rollout row for a verb, refusing unknown/cross-scope reads."""
    row = await _rollout_repo().get(
        tenant_id=tenant_id,
        environment_id=environment_id,
        rollout_id=rollout_id,
    )
    if row is None:
        raise ValueError(
            f"unknown rollout {rollout_id!r} for tenant {tenant_id!r} / "
            f"environment {environment_id!r} (§12.8)"
        )
    return row


async def create_rollout(view: RolloutView) -> dict:
    """Record a §40 rollout from its §12.8 RolloutContract fields.

    Validation rides the repository storage row (artifact kind / ring / cohort
    vocabularies, the §40 percentage law: ``percentage`` must equal
    ``ring_percentage(current_stage)``). A new rollout always starts at stage
    zero — ``current_stage`` defaults to ``olympus_internal`` and is not
    advanced by creation."""
    row = RolloutRecordRow(**view.model_dump(mode="json"))
    return await _rollout_repo().create(row)


async def start_rollout(
    *,
    tenant_id: str,
    environment_id: str,
    rollout_id: str,
    at: Optional[datetime] = None,
) -> dict:
    """Start a §40 rollout: stamp ``started_at`` (idempotent — an already
    started rollout keeps its original stamp). ``current_stage`` stays stage
    zero (``olympus_internal``): §40 start is not a ring transition. Terminal
    records refuse to start (fail closed)."""
    row = await _load_rollout(tenant_id, environment_id, rollout_id)
    if row.get("end_state") is not None:
        raise ValueError(
            f"rollout {rollout_id!r} already ended with end_state "
            f"{row['end_state']!r} — cannot start (§12.8)"
        )
    updated = await _rollout_repo().start(
        tenant_id=tenant_id,
        environment_id=environment_id,
        rollout_id=rollout_id,
        at=at or _now(),
    )
    return updated if updated is not None else row


async def evaluate_and_advance(
    *,
    tenant_id: str,
    environment_id: str,
    rollout_id: str,
    health_snapshot: HealthSnapshotView | dict,
    satisfied_condition_tokens: list[str],
    at: Optional[datetime] = None,
) -> dict:
    """§39 R2 moderate decision: evaluate health, then advance exactly one
    §40 ring — or pause / roll back durably.

    Decision order (all persist through the rollout repository):

    1. gate violations (fail closed) -> ``paused`` with a durable
       ``health_gate: <axis> <op> <threshold> observed <value>`` pause reason;
    2. any satisfied ``rollback_conditions`` token -> ``rolled_back``
       (end_state stamped, terminal);
    3. any satisfied ``pause_conditions`` token -> ``paused``
       (``condition: <token>``);
    4. non-empty ``advance_conditions`` not all satisfied -> ``paused``
       (``awaiting_advance_conditions``) — approval tokens are never waived
       by this engine;
    5. otherwise advance one ring -> ``advanced``; from the terminal ``100%``
       ring an advance completes the rollout (``completed``, ``completed_at``
       stamped).

    ``health_snapshot`` is a §12.9 HealthSnapshotView (or dict form);
    ``satisfied_condition_tokens`` are the currently-satisfied policy/approval
    tokens the caller observed. A rollout that already reached a terminal
    ``end_state`` cannot be evaluated again (fail closed).
    """
    row = await _load_rollout(tenant_id, environment_id, rollout_id)
    if row.get("end_state") is not None:
        raise ValueError(
            f"rollout {rollout_id!r} already ended with end_state "
            f"{row['end_state']!r} — cannot evaluate (§40)"
        )
    stage = row["current_stage"]
    percentage = row["percentage"]
    gates = row["health_gates"]
    violations = evaluate_health_gates(health_snapshot, gates)
    if violations:
        first = violations[0]
        reason = (
            f"health_gate: {first['axis']} {first['operator']} "
            f"{first['threshold']} observed {first['observed']}"
        )
        await _rollout_repo().update_stage(
            tenant_id=tenant_id,
            environment_id=environment_id,
            rollout_id=rollout_id,
            current_stage=stage,
            percentage=percentage,
            paused_reason=reason,
            at=at,
        )
        return {
            "decision": "paused",
            "reason": reason,
            "violations": violations,
            "current_stage": stage,
            "percentage": percentage,
        }
    satisfied = set(satisfied_condition_tokens)
    rollback_hits = satisfied.intersection(row["rollback_conditions"])
    if rollback_hits:
        token = sorted(rollback_hits)[0]
        await _rollout_repo().update_stage(
            tenant_id=tenant_id,
            environment_id=environment_id,
            rollout_id=rollout_id,
            current_stage=stage,
            percentage=percentage,
            end_state="rolled_back",
            at=at,
        )
        return {
            "decision": "rolled_back",
            "reason": token,
            "current_stage": stage,
            "percentage": percentage,
        }
    pause_hits = satisfied.intersection(row["pause_conditions"])
    if pause_hits:
        token = sorted(pause_hits)[0]
        reason = f"condition: {token}"
        await _rollout_repo().update_stage(
            tenant_id=tenant_id,
            environment_id=environment_id,
            rollout_id=rollout_id,
            current_stage=stage,
            percentage=percentage,
            paused_reason=reason,
            at=at,
        )
        return {
            "decision": "paused",
            "reason": reason,
            "violations": [],
            "current_stage": stage,
            "percentage": percentage,
        }
    advance_conditions = row["advance_conditions"]
    if advance_conditions and not all(
        token in satisfied for token in advance_conditions
    ):
        reason = "awaiting_advance_conditions"
        await _rollout_repo().update_stage(
            tenant_id=tenant_id,
            environment_id=environment_id,
            rollout_id=rollout_id,
            current_stage=stage,
            percentage=percentage,
            paused_reason=reason,
            at=at,
        )
        return {
            "decision": "paused",
            "reason": reason,
            "violations": [],
            "current_stage": stage,
            "percentage": percentage,
        }
    next_ring = ring_at(ring_index(stage) + 1)
    if next_ring is None:
        # Terminal "100%" ring: an attempted advance completes the rollout.
        await _rollout_repo().update_stage(
            tenant_id=tenant_id,
            environment_id=environment_id,
            rollout_id=rollout_id,
            current_stage=stage,
            percentage=percentage,
            end_state="completed",
            at=at,
        )
        return {
            "decision": "completed",
            "current_stage": stage,
            "percentage": ring_percentage(stage),
        }
    next_percentage = ring_percentage(next_ring)
    await _rollout_repo().update_stage(
        tenant_id=tenant_id,
        environment_id=environment_id,
        rollout_id=rollout_id,
        current_stage=next_ring,
        percentage=next_percentage,
        at=at,
    )
    return {
        "decision": "advanced",
        "current_stage": next_ring,
        "percentage": next_percentage,
    }


async def rollback(
    *,
    tenant_id: str,
    environment_id: str,
    rollout_id: str,
    at: Optional[datetime] = None,
) -> dict:
    """Explicit governed §40 rollback: mark the record ``rolled_back`` (a
    terminal state) from whatever ring it is in — §40 permits a rollback from
    any stage. Not legal for an already-rolled-back (or otherwise terminal)
    record — the revert itself is the executor's job, never this engine's."""
    row = await _load_rollout(tenant_id, environment_id, rollout_id)
    end_state = row.get("end_state")
    if end_state is not None:
        raise ValueError(
            f"rollout {rollout_id!r} already ended with end_state "
            f"{end_state!r} — rollback is not legal (§12.8)"
        )
    stage = row["current_stage"]
    percentage = row["percentage"]
    await _rollout_repo().update_stage(
        tenant_id=tenant_id,
        environment_id=environment_id,
        rollout_id=rollout_id,
        current_stage=stage,
        percentage=percentage,
        end_state="rolled_back",
        at=at,
    )
    return {
        "decision": "rolled_back",
        "reason": "explicit_governed_rollback",
        "current_stage": stage,
        "percentage": percentage,
    }


async def resume_after_pause(
    *,
    tenant_id: str,
    environment_id: str,
    rollout_id: str,
    at: Optional[datetime] = None,
) -> dict:
    """Clear a durable pause marker (``paused_reason`` -> None) and stamp
    ``last_transition_at``. Resume only clears the marker — the next
    :func:`evaluate_and_advance` re-checks health from a fresh snapshot and
    pauses again if evidence is still failing (the engine never lets a resume
    bypass a gate)."""
    row = await _load_rollout(tenant_id, environment_id, rollout_id)
    if row.get("end_state") is not None:
        raise ValueError(
            f"rollout {rollout_id!r} already ended with end_state "
            f"{row['end_state']!r} — cannot resume (§12.8)"
        )
    updated = await _rollout_repo().update_stage(
        tenant_id=tenant_id,
        environment_id=environment_id,
        rollout_id=rollout_id,
        current_stage=row["current_stage"],
        percentage=row["percentage"],
        paused_reason=None,
        at=at,
    )
    return updated if updated is not None else row


__all__ = [
    "AVAILABILITY_GATE_PASS_SET",
    "NOT_OBSERVABLE",
    "THRESHOLD_BREACH",
    "ring_index",
    "stage_index",
    "ring_at",
    "evaluate_health_gates",
    "rollout_health_status",
    "health_ok",
    "create_rollout",
    "start_rollout",
    "evaluate_and_advance",
    "rollback",
    "resume_after_pause",
]
