"""Reconciled Control Plane — §37 simulation/shadow + §20 digital-twin engine (Phase 3).

Shadow comparison (§37): before semantically material or moderate-risk
automated changes, evaluate against a Digital Twin and/or shadow path.
PRODUCTION INPUT branches to a *current path* (authoritative result) and a
*candidate path* (non-authoritative result); the engine compares them along
:data:`SIMULATION_AXES` — schema acceptance, mapping coverage, policy
decisions, identity joinability, outcome continuity, metric reconciliation,
latency, drop rate, duplicates, cost/volume (the §37 comparison list).

§37 INVARIANT — no shadow result mutates canonical graph state: the engine is
a PURE function over the snapshots it is handed. It never reads or writes
managed-integration / ChangeSet / execution-record / reconciler state and
performs no writes to canonical graph state. The only row it persists is its
own ``simulation_runs`` evidence record (via
``simulation_repository``). The unit suite asserts the invariant by proving
the managed-integration and change-set stores contain no rows after
``compare_paths``.

§20 digital twin: ``digital_twin_dry_run`` is the fixture-based dry run that
every IntegrationPlan supports before initial production activation — it
simulates safe changes against a fixture-baseline *current* path (runtime
capabilities, schemas, contract versions, mapping topology, synthetic
payloads, approved sampled-shape metadata, historical volume distributions,
consent configuration, provider capabilities, dependency topology, health
baselines, release state) without raw production data. A passing dry run never
substitutes for authorization (CP-03).

Phase-3 boundary: simulation records exist to gate R1/R2 execution in a later
phase — nothing here auto-executes, and nothing in this module reads a feature
flag; wiring decides when the engine runs.

Vocabulary (§12.7): every axis result and the overall run result is one of
``pass`` | ``conditional`` | ``fail``. Aggregation: any ``fail`` -> ``fail``;
else any ``conditional`` or warning -> ``conditional``; else ``pass``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from services.managed_integrations.contracts import is_simulation_result
from services.managed_integrations.simulation_repository import (
    SIMULATION_MODES,
    SimulationRunView,
    get_simulation_repository,
)

# The ten §37 comparison axes (canonical, fixed order). Only these keys of the
# supplied path dicts are evaluated; any extra keys are ignored.
SIMULATION_AXES: tuple[str, ...] = (
    "schema_acceptance",
    "mapping_coverage",
    "policy_decisions",
    "identity_joinability",
    "outcome_continuity",
    "metric_reconciliation",
    "latency",
    "drop_rate",
    "duplicates",
    "cost_volume",
)

# Numeric axes where a LOWER candidate value is the improvement (the candidate
# reduces the metric); every other numeric axis improves when the candidate is
# higher. Documented per axis so ``improved``/``regressed`` never invert a
# metric's real direction (latency up is never ``improved``).
_LOWER_IS_BETTER_AXES = frozenset(
    {"latency", "drop_rate", "duplicates", "cost_volume"}
)


def is_axis(value: str) -> bool:
    """AXIS token helper: is ``value`` one of the canonical §37 axes?"""
    return value in SIMULATION_AXES


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_number(value: Any) -> Optional[float]:
    """Best-effort numeric coercion (int/float or numeric strings).

    Booleans are never numbers and ``None`` is never a value here. Non-numeric
    strings return None so the caller falls through to the non-numeric pair
    comparison.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _axis_outcome(
    axis: str,
    current: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> tuple[str, str, Optional[str]]:
    """Compare one canonical axis -> (axis_result, delta, unknown_axis).

    ``unknown_axis`` is the axis name when the comparison could not observe
    the axis (missing on both sides, explicit None on both sides, or an axis
    value of the token ``"unknown"``) — the caller appends it to the run's
    ``unknowns`` list and the axis itself is ``conditional``.

    Delta vocabulary: ``equal``/``improved``/``regressed (+<abs diff>)`` for
    numeric pairs, ``equal``/``changed`` for non-numeric pairs,
    ``missing_on_current``/``missing_on_candidate`` for one-sided axes,
    ``not_observable``/``unknown`` for unobservable or unknown-token axes.
    """
    if not is_axis(axis):
        raise ValueError(f"unknown simulation axis {axis!r} (§37)")
    cur = current.get(axis) if axis in current else None
    cand = candidate.get(axis) if axis in candidate else None
    cur_present = axis in current and cur is not None
    cand_present = axis in candidate and cand is not None

    # Value in neither side (absent, or explicitly None on both sides): the
    # axis is unobservable — conditional, never a fabricated pass.
    if not cur_present and not cand_present:
        return ("conditional", "not_observable", axis)
    # The token "unknown" anywhere leaves the axis unresolved.
    if (cur_present and cur == "unknown") or (cand_present and cand == "unknown"):
        return ("conditional", "unknown", axis)
    # One-sided axes are observable only as a conditional missing delta.
    if not cur_present:
        return ("conditional", "missing_on_current", None)
    if not cand_present:
        return ("conditional", "missing_on_candidate", None)

    cur_num = _as_number(cur)
    cand_num = _as_number(cand)
    if cur_num is not None and cand_num is not None:
        if cur_num == cand_num:
            return ("pass", "equal", None)
        improved = (
            cand_num < cur_num
            if axis in _LOWER_IS_BETTER_AXES
            else cand_num > cur_num
        )
        if improved:
            return ("pass", "improved", None)
        return ("fail", f"regressed (+{abs(cur_num - cand_num)})", None)

    if cur == cand:
        return ("pass", "equal", None)
    return ("conditional", "changed", None)


def run_result(
    axis_results: Mapping[str, str],
    *,
    warnings: Sequence[str] = (),
    unknowns: Sequence[str] = (),
) -> str:
    """Pure §12.7 aggregation: any fail -> fail; else any conditional, warning
    or unknown -> conditional; else pass. Exported for unit tests."""
    invalid = sorted(
        {
            token
            for token in axis_results.values()
            if not is_simulation_result(str(token))
        }
    )
    if invalid:
        raise ValueError(
            f"non-§12.7 axis result token(s) {invalid} "
            f"— vocabulary is pass | conditional | fail"
        )
    if any(token == "fail" for token in axis_results.values()):
        return "fail"
    if (
        warnings
        or unknowns
        or any(token == "conditional" for token in axis_results.values())
    ):
        return "conditional"
    return "pass"


async def _compare_and_persist(
    *,
    tenant_id: str,
    environment_id: str,
    mode: str,
    current: dict[str, Any],
    candidate: dict[str, Any],
    changeset_ref: Optional[str],
    input_snapshot_refs: Optional[list[str]],
    fixture_refs: Optional[list[str]],
    now: Optional[datetime],
) -> dict:
    """Evaluate every canonical axis over the two paths and persist one run."""
    axis_results: dict[str, str] = {}
    deltas: dict[str, str] = {}
    unknowns: list[str] = []
    for axis in SIMULATION_AXES:
        axis_result, delta, unknown_axis = _axis_outcome(axis, current, candidate)
        axis_results[axis] = axis_result
        deltas[axis] = delta
        if unknown_axis is not None:
            unknowns.append(unknown_axis)
    view = SimulationRunView(
        simulation_id=f"sim_{uuid.uuid4().hex[:16]}",
        changeset_ref=changeset_ref,
        tenant_id=tenant_id,
        environment_id=environment_id,
        simulation_mode=mode,
        input_snapshot_refs=list(input_snapshot_refs or []),
        fixture_refs=list(fixture_refs or []),
        axis_results=axis_results,
        deltas=deltas,
        unknowns=unknowns,
        result=run_result(axis_results, unknowns=unknowns),
        ran_at=now or _now(),
    )
    return await get_simulation_repository().create(view)


async def compare_paths(
    *,
    tenant_id: str,
    environment_id: str,
    current: dict[str, Any],
    candidate: dict[str, Any],
    mode: str = "shadow",
    changeset_ref: Optional[str] = None,
    input_snapshot_refs: Optional[list[str]] = None,
    fixture_refs: Optional[list[str]] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Run one §37 shadow/digital-twin comparison and persist its evidence row.

    ``current`` is the authoritative production-result path; ``candidate`` the
    non-authoritative path under evaluation. Every canonical §37 axis present
    in either side is compared (axes observable on neither side stay
    ``conditional``/``not_observable`` and are listed under ``unknowns``). The
    run is a pure function of the two path dicts — no canonical state is read
    or written, and the returned row is the new ``simulation_runs`` evidence.
    """
    if mode not in SIMULATION_MODES:
        raise ValueError(
            f"unknown simulation mode {mode!r} "
            f"— §37/§12.7 vocabulary is shadow | digital_twin"
        )
    return await _compare_and_persist(
        tenant_id=tenant_id,
        environment_id=environment_id,
        mode=mode,
        current=current,
        candidate=candidate,
        changeset_ref=changeset_ref,
        input_snapshot_refs=input_snapshot_refs,
        fixture_refs=fixture_refs,
        now=now,
    )


async def digital_twin_dry_run(
    *,
    tenant_id: str,
    environment_id: str,
    current: dict[str, Any],
    candidate: dict[str, Any],
    changeset_ref: Optional[str] = None,
    input_snapshot_refs: Optional[list[str]] = None,
    fixture_refs: Optional[list[str]] = None,
    now: Optional[datetime] = None,
) -> dict:
    """§20 fixture-based digital-twin dry run (mode ``digital_twin``).

    Identical aggregation to :func:`compare_paths` over ``candidate`` vs the
    fixture-baseline ``current`` path — safe simulation without raw production
    data (fixture payloads and approved sampled-shape metadata only). A
    passing dry run never substitutes for authorization (CP-03); the row is
    evidence, and ``changeset_ref`` may be absent because twin dry runs can
    precede any ChangeSet.
    """
    return await _compare_and_persist(
        tenant_id=tenant_id,
        environment_id=environment_id,
        mode="digital_twin",
        current=current,
        candidate=candidate,
        changeset_ref=changeset_ref,
        input_snapshot_refs=input_snapshot_refs,
        fixture_refs=fixture_refs,
        now=now,
    )
