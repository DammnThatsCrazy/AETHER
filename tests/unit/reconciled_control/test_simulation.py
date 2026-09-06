"""Reconciled Control Plane — §37 simulation/shadow + §20 digital-twin engine tests.

Covers the Phase-3 simulation plane against the in-memory repositories: the
ten canonical §37 axis comparisons (numeric equal/improved/regressed deltas,
non-numeric equal/changed, one-sided missing, ``unknown``-token and
not-observable axes), the §12.7 run-result aggregation (any fail -> fail; any
conditional/warning/unknown -> conditional; else pass), the shadow/digital-twin
mode + result vocabularies at both the engine and repository write boundaries,
cross-scope/ordering semantics of the ``simulation_runs`` repository, the §37
no-mutation invariant (after ``compare_paths`` the managed-integration and
change-set stores still contain no rows), field round-trips through the stored
row, and flag-OFF import parity (imports fine, nothing auto-runs).

No live database is touched: the shared ``_reset_rcp_stores`` conftest fixture
empties the Phase-0/1/2 in-memory stores before/after every test, the
module-local ``_simulation_db_free`` fixture additionally empties the
simulation store and pins every ``get_pool`` this suite can reach to None.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest

from services.managed_integrations.contracts import SIMULATION_RESULT_VALUES
from services.managed_integrations.simulation import (
    SIMULATION_AXES,
    compare_paths,
    digital_twin_dry_run,
    is_axis,
    run_result,
)
from services.managed_integrations.simulation_repository import (
    SimulationRunView,
    get_simulation_repository,
)

TENANT_A = "tenant-sim-a"
TENANT_B = "tenant-sim-b"
ENV = "env-1"
NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _simulation_db_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``get_pool`` to None on every repository module this suite touches
    and empty every store the engine must not grow.

    The shared ``_reset_rcp_stores`` conftest fixture clears the Phase-0/1/2
    stores before/after every test; this fixture additionally clears the
    simulation store and guarantees no repository write reaches a live
    Postgres even under an ambient non-local ``AETHER_ENV``.
    """
    import services.managed_integrations.change_sets_repository as cs_module
    import services.managed_integrations.repository as mi_module
    import services.managed_integrations.simulation_repository as sim_module

    from services.managed_integrations.change_sets_repository import (
        reset_change_set_in_memory_store,
    )
    from services.managed_integrations.repository import (
        reset_managed_integration_in_memory_store,
    )
    from services.managed_integrations.simulation_repository import (
        reset_simulation_stores,
    )

    reset_simulation_stores()
    reset_managed_integration_in_memory_store()
    reset_change_set_in_memory_store()

    async def _no_pool() -> None:
        return None

    monkeypatch.setattr(sim_module, "get_pool", _no_pool)
    monkeypatch.setattr(cs_module, "get_pool", _no_pool)
    monkeypatch.setattr(mi_module, "get_pool", _no_pool)
    repos_module = None
    try:
        import repositories.repos as repos_module
    except Exception:  # noqa: BLE001 - import-defensive; optional patch target
        pass
    if repos_module is not None:
        monkeypatch.setattr(repos_module, "get_pool", _no_pool)
    yield
    reset_simulation_stores()


# ── helpers ──────────────────────────────────────────────────────────────────


def _path(**overrides: Any) -> dict[str, Any]:
    """One full §37 path: every canonical axis present on both sides, equal
    values across the board (so a clean run is ``pass`` by construction)."""
    base: dict[str, Any] = {
        "schema_acceptance": 0.99,
        "mapping_coverage": 0.97,
        "policy_decisions": ["policy/p1"],
        "identity_joinability": 1.0,
        "outcome_continuity": 0.98,
        "metric_reconciliation": 0.0,
        "latency": 120.0,
        "drop_rate": 0.001,
        "duplicates": 0,
        "cost_volume": 12.5,
    }
    base.update(overrides)
    return base


def _view(
    simulation_id: str,
    *,
    tenant_id: str = TENANT_A,
    environment_id: str = ENV,
    mode: str = "shadow",
    changeset_ref: Optional[str] = None,
    result: str = "pass",
    ran_at: Optional[datetime] = None,
) -> SimulationRunView:
    return SimulationRunView(
        simulation_id=simulation_id,
        changeset_ref=changeset_ref,
        tenant_id=tenant_id,
        environment_id=environment_id,
        simulation_mode=mode,
        result=result,
        ran_at=ran_at or NOW,
    )


async def _store_row(simulation_id: str, **overrides: Any) -> dict:
    return await get_simulation_repository().create(
        _view(simulation_id, **overrides)
    )


# ── 1. numeric equal / improved / regressed deltas ───────────────────────────


async def test_numeric_equal_deltas_pass() -> None:
    row = await compare_paths(
        tenant_id=TENANT_A,
        environment_id=ENV,
        current=_path(),
        candidate=_path(),
    )
    assert row["result"] == "pass"
    assert row["simulation_mode"] == "shadow"
    assert set(row["axis_results"]) == set(SIMULATION_AXES)
    assert all(v == "pass" for v in row["axis_results"].values())
    assert all(v == "equal" for v in row["deltas"].values())
    assert row["unknowns"] == []
    assert row["warnings"] == []


async def test_numeric_improved_deltas_pass() -> None:
    # mapping_coverage is higher-is-better; latency/drop_rate lower-is-better.
    row = await compare_paths(
        tenant_id=TENANT_A,
        environment_id=ENV,
        current=_path(latency=120.0, mapping_coverage=0.90),
        candidate=_path(latency=95.0, mapping_coverage=0.95),
    )
    assert row["result"] == "pass"
    assert row["axis_results"]["latency"] == "pass"
    assert row["deltas"]["latency"] == "improved"
    assert row["axis_results"]["mapping_coverage"] == "pass"
    assert row["deltas"]["mapping_coverage"] == "improved"
    assert row["deltas"]["drop_rate"] == "equal"
    assert row["unknowns"] == []


async def test_numeric_regression_fails_run() -> None:
    row = await compare_paths(
        tenant_id=TENANT_A,
        environment_id=ENV,
        current=_path(latency=90.0, duplicates=1),
        candidate=_path(latency=150.0, duplicates=2),
    )
    assert row["result"] == "fail"  # any axis fail -> run fail
    assert row["axis_results"]["latency"] == "fail"
    assert row["deltas"]["latency"].startswith("regressed (+")
    assert "(+60.0)" in row["deltas"]["latency"]
    assert row["axis_results"]["duplicates"] == "fail"
    assert row["deltas"]["duplicates"].startswith("regressed (+")
    assert all(
        v == "pass"
        for axis, v in row["axis_results"].items()
        if axis not in {"latency", "duplicates"}
    )


# ── 2. one-sided missing axes + clean all-pass ───────────────────────────────


async def test_one_sided_missing_axis_is_conditional() -> None:
    candidate = _path()
    candidate.pop("cost_volume")  # candidate path never observed the axis
    row = await compare_paths(
        tenant_id=TENANT_A,
        environment_id=ENV,
        current=_path(),
        candidate=candidate,
        changeset_ref="rcs_missing_candidate",
    )
    assert row["result"] == "conditional"
    assert row["changeset_ref"] == "rcs_missing_candidate"
    assert row["axis_results"]["cost_volume"] == "conditional"
    assert row["deltas"]["cost_volume"] == "missing_on_candidate"
    assert row["unknowns"] == []  # a known one-sided absence is not unknown

    current = _path()
    current.pop("duplicates")
    row2 = await compare_paths(
        tenant_id=TENANT_A,
        environment_id=ENV,
        current=current,
        candidate=_path(),
    )
    assert row2["result"] == "conditional"
    assert row2["axis_results"]["duplicates"] == "conditional"
    assert row2["deltas"]["duplicates"] == "missing_on_current"


async def test_all_pass_with_no_warnings_is_pass() -> None:
    row = await compare_paths(
        tenant_id=TENANT_A,
        environment_id=ENV,
        current=_path(),
        candidate=_path(),
    )
    assert row["result"] == "pass"
    assert row["warnings"] == []
    assert row["unknowns"] == []


# ── 3. unknown tokens anywhere ───────────────────────────────────────────────


async def test_unknown_token_is_conditional_and_listed() -> None:
    row = await compare_paths(
        tenant_id=TENANT_A,
        environment_id=ENV,
        current=_path(),
        candidate=_path(schema_acceptance="unknown"),
    )
    assert row["result"] == "conditional"
    assert "schema_acceptance" in row["unknowns"]
    assert row["axis_results"]["schema_acceptance"] == "conditional"
    assert row["deltas"]["schema_acceptance"] == "unknown"

    row2 = await compare_paths(
        tenant_id=TENANT_A,
        environment_id=ENV,
        current=_path(outcome_continuity="unknown"),
        candidate=_path(),
    )
    assert row2["result"] == "conditional"
    assert "outcome_continuity" in row2["unknowns"]
    assert row2["deltas"]["outcome_continuity"] == "unknown"


async def test_axis_unobservable_on_both_sides_is_unknown() -> None:
    # Explicit None on both sides: not observable, never a fabricated pass.
    row = await compare_paths(
        tenant_id=TENANT_A,
        environment_id=ENV,
        current=_path(latency=None),
        candidate=_path(latency=None),
    )
    assert row["result"] == "conditional"
    assert "latency" in row["unknowns"]
    assert row["axis_results"]["latency"] == "conditional"
    assert row["deltas"]["latency"] == "not_observable"


def test_run_result_never_passes_with_unknowns() -> None:
    all_pass = {axis: "pass" for axis in SIMULATION_AXES}
    assert run_result(all_pass) == "pass"
    assert run_result(all_pass, warnings=["w1"]) == "conditional"
    assert run_result(all_pass, unknowns=["latency"]) == "conditional"
    failing = dict(all_pass)
    failing["latency"] = "fail"
    assert run_result(failing, unknowns=["schema_acceptance"]) == "fail"
    with pytest.raises(ValueError, match="§12.7"):
        run_result({"latency": "banana"})


# ── 4. mode + result vocabulary enforcement ──────────────────────────────────


async def test_mode_vocab_enforced_at_engine_and_repo() -> None:
    with pytest.raises(ValueError, match="§37"):
        await compare_paths(
            tenant_id=TENANT_A,
            environment_id=ENV,
            current=_path(),
            candidate=_path(),
            mode="wat",
        )
    # digital_twin through the same harness is legal; the dry run stores it.
    twin = await digital_twin_dry_run(
        tenant_id=TENANT_A,
        environment_id=ENV,
        current=_path(),
        candidate=_path(),
    )
    assert twin["result"] == "pass"
    assert twin["simulation_mode"] == "digital_twin"
    with pytest.raises(ValueError, match="§37"):
        await _store_row("sim_bad_mode", mode="wat")


async def test_result_vocab_enforced_on_repo_create() -> None:
    with pytest.raises(ValueError, match="§12.7"):
        await _store_row("sim_bad_result", result="banana")
    for i, value in enumerate(SIMULATION_RESULT_VALUES):
        row = await _store_row(f"sim_result_{i}", result=value)
        assert row["result"] == value
        assert row["simulation_mode"] == "shadow"


# ── 5. scope + ordering semantics ────────────────────────────────────────────


async def test_cross_scope_get_returns_none() -> None:
    row = await _store_row("sim_scoped_1")
    repo = get_simulation_repository()
    got = await repo.get(
        tenant_id=TENANT_A, environment_id=ENV, simulation_id="sim_scoped_1"
    )
    assert got is not None and got["simulation_id"] == row["simulation_id"]
    assert (
        await repo.get(
            tenant_id=TENANT_B, environment_id=ENV, simulation_id="sim_scoped_1"
        )
        is None
    )
    assert (
        await repo.get(
            tenant_id=TENANT_A, environment_id="env-9", simulation_id="sim_scoped_1"
        )
        is None
    )


async def test_list_for_changeset_is_scoped_and_newest_first() -> None:
    await _store_row("sim_cs1_early", changeset_ref="rcs_1", ran_at=NOW)
    await _store_row(
        "sim_cs1_late",
        changeset_ref="rcs_1",
        ran_at=NOW + timedelta(seconds=5),
    )
    await _store_row("sim_cs2", changeset_ref="rcs_2", ran_at=NOW)
    await _store_row("sim_cs1_other_tenant", changeset_ref="rcs_1", tenant_id=TENANT_B)
    repo = get_simulation_repository()
    for_changeset = await repo.list_for_changeset(
        tenant_id=TENANT_A, environment_id=ENV, changeset_ref="rcs_1"
    )
    assert [r["simulation_id"] for r in for_changeset] == [
        "sim_cs1_late",
        "sim_cs1_early",
    ]
    other = await repo.list_for_changeset(
        tenant_id=TENANT_A, environment_id=ENV, changeset_ref="rcs_2"
    )
    assert [r["simulation_id"] for r in other] == ["sim_cs2"]
    with pytest.raises(ValueError):
        await repo.list_for_changeset(
            tenant_id=TENANT_A, environment_id=ENV, changeset_ref=None
        )


async def test_list_filters_mode_and_orders_newest_first() -> None:
    await _store_row("sim_shadow_1", ran_at=NOW)
    await _store_row(
        "sim_shadow_2", ran_at=NOW + timedelta(seconds=1), tenant_id=TENANT_B
    )
    twin = await digital_twin_dry_run(
        tenant_id=TENANT_A,
        environment_id=ENV,
        current=_path(),
        candidate=_path(),
        now=NOW + timedelta(seconds=2),
    )
    repo = get_simulation_repository()
    shadows = await repo.list(mode="shadow")
    assert {r["simulation_id"] for r in shadows} == {"sim_shadow_1", "sim_shadow_2"}
    twins = await repo.list(mode="digital_twin")
    assert [r["simulation_id"] for r in twins] == [twin["simulation_id"]]
    latest = await repo.list(tenant_id=TENANT_A, limit=1)
    assert latest[0]["simulation_id"] == twin["simulation_id"]
    with pytest.raises(ValueError, match="§37"):
        await repo.list(mode="wat")


# ── 6. §37 no-mutation invariant ─────────────────────────────────────────────


async def test_no_mutation_invariant_after_compare_paths() -> None:
    from services.managed_integrations.change_sets_repository import (
        get_change_set_repository,
    )
    from services.managed_integrations.repository import (
        get_managed_integration_repository,
    )

    mi_repo = get_managed_integration_repository()
    cs_repo = get_change_set_repository()
    sim_repo = get_simulation_repository()
    assert await mi_repo.list() == []
    assert await cs_repo.list() == []

    row = await compare_paths(
        tenant_id=TENANT_A,
        environment_id=ENV,
        current=_path(latency=90.0),
        candidate=_path(latency=150.0),
        changeset_ref="rcs_shadow_never_applied",
    )
    assert row["result"] == "fail"

    # §37 invariant: no shadow result mutates canonical graph state — the
    # managed-integration and change-set stores still hold no rows.
    assert await mi_repo.list() == []
    assert await cs_repo.list() == []
    assert (
        await mi_repo.get(TENANT_A, ENV, "mi-anything") is None
    )
    assert (
        await cs_repo.get(TENANT_A, ENV, "rcs-anything") is None
    )
    # The only store that may grow is the simulation evidence store itself.
    evidence = await sim_repo.list(tenant_id=TENANT_A, environment_id=ENV)
    assert [r["simulation_id"] for r in evidence] == [row["simulation_id"]]


# ── 7. field round-trips ─────────────────────────────────────────────────────


async def test_simulation_run_view_round_trips_into_stored_row() -> None:
    view = SimulationRunView(
        simulation_id="sim_roundtrip_1",
        changeset_ref="rcs_claims_9",
        tenant_id=TENANT_A,
        environment_id=ENV,
        simulation_mode="shadow",
        input_snapshot_refs=["snap/current-a", "snap/candidate-b"],
        fixture_refs=["fx/payload-1"],
        axis_results={"latency": "fail", "schema_acceptance": "pass"},
        deltas={"latency": "regressed (+5.0)"},
        unknowns=["duplicates"],
        warnings=["approval_still_required_cp03"],
        result="conditional",
        ran_at=NOW,
    )
    repo = get_simulation_repository()
    stored = await repo.create(view)
    expected = view.model_dump(mode="json")
    for key in (
        "simulation_id",
        "changeset_ref",
        "tenant_id",
        "environment_id",
        "simulation_mode",
        "input_snapshot_refs",
        "fixture_refs",
        "axis_results",
        "deltas",
        "unknowns",
        "warnings",
        "result",
    ):
        assert stored[key] == expected[key], key
    # Timestamps are normalized to the canonical ISO instant on every row
    # (create and read shapes agree — mirrors the sibling repositories).
    assert stored["ran_at"] == NOW.isoformat()
    fetched = await repo.get(
        tenant_id=TENANT_A, environment_id=ENV, simulation_id="sim_roundtrip_1"
    )
    assert fetched == stored


async def test_engine_claim_fields_survive_into_stored_row() -> None:
    row = await compare_paths(
        tenant_id=TENANT_A,
        environment_id=ENV,
        current=_path(latency=90.0),
        candidate=_path(latency=110.0),
        mode="shadow",
        changeset_ref="rcs_claims_10",
        input_snapshot_refs=["snap/current-1", "snap/candidate-1"],
        fixture_refs=["fx/shape-1"],
        now=NOW,
    )
    assert row["result"] == "fail"
    assert row["changeset_ref"] == "rcs_claims_10"
    assert row["input_snapshot_refs"] == ["snap/current-1", "snap/candidate-1"]
    assert row["fixture_refs"] == ["fx/shape-1"]
    assert row["ran_at"] == NOW.isoformat()
    fetched = await get_simulation_repository().get(
        tenant_id=TENANT_A, environment_id=ENV, simulation_id=row["simulation_id"]
    )
    assert fetched == row


# ── 8. flag-OFF parity ───────────────────────────────────────────────────────


def test_axis_token_helper() -> None:
    assert is_axis("latency")
    assert is_axis("cost_volume")
    assert not is_axis("volume")
    assert not is_axis("")


async def test_flag_off_parity_imports_clean_and_nothing_auto_runs() -> None:
    import importlib

    import services.managed_integrations.flags as flags

    assert flags.enabled() is False
    assert flags.reconciler_enabled() is False
    # Re-executing both Phase-3 modules under all-flags-OFF must import cleanly
    # and register no wiring / auto-run no comparison.
    simulation_repository_module = importlib.reload(
        importlib.import_module("services.managed_integrations.simulation_repository")
    )
    simulation_module = importlib.reload(
        importlib.import_module("services.managed_integrations.simulation")
    )
    assert simulation_repository_module.SIMULATION_MODES == (
        "shadow",
        "digital_twin",
    )
    assert simulation_module.SIMULATION_AXES[0] == "schema_acceptance"
    repo = get_simulation_repository()
    assert await repo.list() == []
