"""§16 integration admission engine + repository tests (Phase 3).

Covers the admission half of the Reconciled Control Plane: the §16 drawn stage
line (discover -> understand -> classify -> reconcile_source_authority ->
authorize -> simulate -> approve -> compile -> activate -> observe) and the
continuous lifecycle edges (monitor -> drift -> reconcile -> change / review /
suspend / revoke). Per CP-03 ("discovery never equals authorization") the
admission record is a lifecycle fact, never an enablement — the engine only
moves its own row, and only reaching ``activate`` flips ``active``.

The module-local autouse fixture isolates this module's in-memory store (the
shared ``_reset_rcp_stores`` conftest fixture resets the Phase-1/Phase-2
stores, not admission records) and pins ``get_pool`` to None on both the repo
module and ``repositories.repos`` so every write exercises the columnar
in-memory path the engine uses under ``AETHER_ENV=local``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.managed_integrations.admission import (
    IntegrationAdmissionFacts,
    activate,
    admit,
    advance_stage,
    get_or_create,
    next_stage,
    set_lifecycle_state,
    validate_lifecycle_move,
    validate_stage_move,
)
from services.managed_integrations.admission_repository import (
    AdmissionRecordView,
    get_admission_record_repository,
    reset_admission_record_stores,
)
from services.managed_integrations.contracts import (
    ADMISSION_STAGES,
    CONTINUOUS_LIFECYCLE_ACTIONS,
)

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
ENV = "env-1"
INTEGRATION = "mi-sdk-1"
SOURCE_REF = "sdk/install/abc123"
INTEGRATION_KIND = "sdk_web"
SOURCE_ORIGIN = "tenant"
NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _admission_db_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the admission-record store and pin ``get_pool`` to None.

    The repo module resolves ``get_pool`` from its own namespace at call time,
    so patching the module attribute (and ``repositories.repos`` for any other
    importer) keeps every write on the in-memory path regardless of the
    ambient AETHER_ENV.
    """
    async def _no_pool():
        return None

    monkeypatch.setattr(
        "services.managed_integrations.admission_repository.get_pool", _no_pool
    )
    monkeypatch.setattr("repositories.repos.get_pool", _no_pool)
    reset_admission_record_stores()
    yield
    reset_admission_record_stores()


def _facts(
    *,
    tenant_id: str = TENANT_A,
    integration: str = INTEGRATION,
    source_origin: str = SOURCE_ORIGIN,
) -> IntegrationAdmissionFacts:
    return IntegrationAdmissionFacts(
        managed_integration_ref=integration,
        tenant_id=tenant_id,
        environment_id=ENV,
        source_ref=SOURCE_REF,
        integration_kind=INTEGRATION_KIND,
        source_origin=source_origin,
    )


def _repo_view(
    admission_id: str = "adm_1",
    *,
    tenant_id: str = TENANT_A,
    current_stage: str = "discover",
    lifecycle_state: str = "monitor",
) -> AdmissionRecordView:
    return AdmissionRecordView(
        admission_id=admission_id,
        managed_integration_ref=INTEGRATION,
        tenant_id=tenant_id,
        environment_id=ENV,
        source_ref=SOURCE_REF,
        integration_kind=INTEGRATION_KIND,
        source_origin=SOURCE_ORIGIN,
        current_stage=current_stage,
        lifecycle_state=lifecycle_state,
        created_at=NOW,
        updated_at=NOW,
    )


# ── 1. shared §16 vocabulary ─────────────────────────────────────────────────


def test_admission_stages_are_the_canonical_ten_in_order() -> None:
    assert list(ADMISSION_STAGES) == [
        "discover",
        "understand",
        "classify",
        "reconcile_source_authority",
        "authorize",
        "simulate",
        "approve",
        "compile",
        "activate",
        "observe",
    ]
    # The continuous lifecycle is a disjoint vocabulary — no token is shared.
    assert set(ADMISSION_STAGES).isdisjoint(CONTINUOUS_LIFECYCLE_ACTIONS)
    assert list(CONTINUOUS_LIFECYCLE_ACTIONS) == [
        "monitor",
        "drift",
        "reconcile",
        "change",
        "review",
        "suspend",
        "revoke",
    ]


def test_stage_adjacency_matches_the_drawn_line() -> None:
    # Every stage advances to exactly the next canonical stage; observe and
    # unknown tokens have no successor (the admission terminal).
    for from_stage, to_stage in zip(ADMISSION_STAGES, ADMISSION_STAGES[1:]):
        validate_stage_move(from_stage, to_stage)  # must not raise
        assert next_stage(from_stage) == to_stage
    assert next_stage("observe") is None
    assert next_stage("not_a_stage") is None


# ── 2. stage legality: the drawn order only ──────────────────────────────────


def test_stage_skips_reverse_and_reentry_all_raise() -> None:
    with pytest.raises(ValueError, match="illegal §16 admission stage move"):
        validate_stage_move("discover", "classify")  # skipping
    with pytest.raises(ValueError, match="illegal §16 admission stage move"):
        validate_stage_move("discover", "authorize")  # deep skip
    with pytest.raises(ValueError, match="illegal §16 admission stage move"):
        validate_stage_move("activate", "compile")  # reverse
    with pytest.raises(ValueError, match="illegal §16 admission stage move"):
        validate_stage_move("approve", "approve")  # invented re-entry/no-op
    with pytest.raises(ValueError, match="illegal §16 admission stage move"):
        validate_stage_move("observe", "discover")  # exit from the terminal
    with pytest.raises(ValueError, match="illegal §16 admission stage move"):
        validate_stage_move("observe", "understand")  # any exit from observe
    with pytest.raises(ValueError, match="illegal §16 admission stage move"):
        validate_stage_move("not_a_stage", "understand")  # unknown from
    with pytest.raises(ValueError, match="illegal §16 admission stage move"):
        validate_stage_move("discover", "not_a_stage")  # unknown to


# ── 3. continuous-lifecycle legality ─────────────────────────────────────────


def test_lifecycle_drawn_edges_are_legal() -> None:
    for from_state, to_state in [
        ("monitor", "drift"),
        ("drift", "reconcile"),
        ("reconcile", "change"),
        ("reconcile", "review"),
        ("reconcile", "suspend"),
        ("reconcile", "revoke"),
        ("change", "monitor"),  # the change arm closes back into monitoring
        ("review", "monitor"),
    ]:
        validate_lifecycle_move(from_state, to_state)  # must not raise


def test_lifecycle_undrawn_edges_raise() -> None:
    with pytest.raises(ValueError, match="illegal §16"):
        validate_lifecycle_move("monitor", "reconcile")  # skipped drift
    with pytest.raises(ValueError, match="illegal §16"):
        validate_lifecycle_move("drift", "review")  # skipped reconcile
    with pytest.raises(ValueError, match="illegal §16"):
        validate_lifecycle_move("reconcile", "approve")  # approve is a stage
    with pytest.raises(ValueError, match="illegal §16"):
        validate_lifecycle_move("change", "review")  # not drawn
    with pytest.raises(ValueError, match="illegal §16"):
        validate_lifecycle_move("review", "reconcile")  # not drawn
    with pytest.raises(ValueError, match="illegal §16"):
        validate_lifecycle_move("suspend", "monitor")  # suspend has no exit
    with pytest.raises(ValueError, match="illegal §16"):
        validate_lifecycle_move("suspend", "change")  # suspend has no exit
    with pytest.raises(ValueError, match="illegal §16"):
        validate_lifecycle_move("revoke", "monitor")  # revoke has no exit
    with pytest.raises(ValueError, match="illegal §16"):
        validate_lifecycle_move("monitor", "not_an_action")  # unknown token


# ── 4. repository round-trip + engine idempotency ────────────────────────────


@pytest.mark.asyncio
async def test_create_get_and_get_for_integration_roundtrip() -> None:
    repo = get_admission_record_repository()
    created = await repo.create(_repo_view())
    assert created["current_stage"] == "discover"
    assert created["lifecycle_state"] == "monitor"
    assert created["active"] is False
    assert created["created_at"] == NOW.isoformat()

    got = await repo.get(
        tenant_id=TENANT_A, environment_id=ENV, admission_id="adm_1"
    )
    assert got == created
    by_integration = await repo.get_for_integration(
        tenant_id=TENANT_A, environment_id=ENV, managed_integration_ref=INTEGRATION
    )
    assert by_integration is not None
    assert by_integration["admission_id"] == "adm_1"
    assert by_integration["source_ref"] == SOURCE_REF
    assert by_integration["source_origin"] == SOURCE_ORIGIN
    # The row is a lifecycle fact for its own scope only — no cross-tenant read.
    assert (
        await repo.get(tenant_id=TENANT_B, environment_id=ENV, admission_id="adm_1")
        is None
    )


@pytest.mark.asyncio
async def test_engine_get_or_create_and_admit_are_idempotent() -> None:
    facts = _facts()
    first = await get_or_create(facts, at=NOW)
    second = await admit(facts, at=NOW)
    assert first["admission_id"] == second["admission_id"]
    assert first["admission_id"].startswith("adm_")
    assert second["current_stage"] == "discover"
    # One integration -> exactly one admission record.
    rows = await get_admission_record_repository().list(
        tenant_id=TENANT_A, environment_id=ENV
    )
    assert len(rows) == 1
    assert rows[0]["admission_id"] == first["admission_id"]


@pytest.mark.asyncio
async def test_distinct_integrations_and_tenants_get_distinct_records() -> None:
    await admit(_facts(), at=NOW)
    await admit(_facts(integration="mi-sdk-2"), at=NOW)
    await admit(_facts(tenant_id=TENANT_B), at=NOW)
    rows_a = await get_admission_record_repository().list(
        tenant_id=TENANT_A, environment_id=ENV
    )
    assert len(rows_a) == 2
    rows_b = await get_admission_record_repository().list(
        tenant_id=TENANT_B, environment_id=ENV
    )
    assert len(rows_b) == 1
    assert rows_b[0]["managed_integration_ref"] == INTEGRATION


@pytest.mark.asyncio
async def test_list_orders_newest_updated_first() -> None:
    first = await admit(_facts(), at=NOW)
    later = NOW + timedelta(hours=1)
    await admit(_facts(integration="mi-sdk-2"), at=later)
    rows = await get_admission_record_repository().list(
        tenant_id=TENANT_A, environment_id=ENV
    )
    assert [r["managed_integration_ref"] for r in rows] == ["mi-sdk-2", INTEGRATION]
    # An advance re-stamps updated_at (strictly newer than every prior stamp)
    # and re-orders the aggregate newest-updated first.
    await advance_stage(
        tenant_id=TENANT_A,
        environment_id=ENV,
        admission_id=first["admission_id"],
        at=later + timedelta(seconds=1),
    )
    rows = await get_admission_record_repository().list(
        tenant_id=TENANT_A, environment_id=ENV
    )
    assert rows[0]["managed_integration_ref"] == INTEGRATION


# ── 5. engine stage walk: evidence-bearing, fail-closed ──────────────────────


@pytest.mark.asyncio
async def test_advance_stage_walks_the_full_line_to_observe() -> None:
    row = await admit(_facts(), at=NOW)
    admission_id = row["admission_id"]
    assert row["current_stage"] == "discover"
    assert row["active"] is False

    for target in ADMISSION_STAGES[1:]:  # understand -> ... -> observe
        row = await advance_stage(
            tenant_id=TENANT_A,
            environment_id=ENV,
            admission_id=admission_id,
            actor="operator",
            at=NOW,
        )
        assert row["current_stage"] == target
        assert row["updated_at"] == NOW.isoformat()
        if target == "activate":
            # Reaching activate is the ONLY thing that sets active.
            assert row["active"] is True
        elif target == "observe":
            # Reaching observe leaves active as-is (continuous lifecycle takes
            # over).
            assert row["active"] is True
        else:
            assert row["active"] is False

    # observe is the admission terminal — no further advance exists.
    with pytest.raises(ValueError, match="illegal §16 admission stage move"):
        await advance_stage(
            tenant_id=TENANT_A,
            environment_id=ENV,
            admission_id=admission_id,
            actor="operator",
            at=NOW,
        )


@pytest.mark.asyncio
async def test_advance_stage_never_skips_or_reverses() -> None:
    row = await admit(_facts(), at=NOW)
    # The engine derives each move from the row's own position — a caller can
    # only ever persist one adjacency step at a time. The direct validator
    # covers skip/reverse; here a full walk reaches exactly the 10th stage.
    for target in ADMISSION_STAGES[1:]:
        row = await advance_stage(
            tenant_id=TENANT_A,
            environment_id=ENV,
            admission_id=row["admission_id"],
            actor="operator",
            at=NOW,
        )
        assert row["current_stage"] == target
    assert row["current_stage"] == "observe"


@pytest.mark.asyncio
async def test_advance_stage_on_unknown_or_missing_record_raises() -> None:
    with pytest.raises(ValueError, match="no §16 admission record"):
        await advance_stage(
            tenant_id=TENANT_A,
            environment_id=ENV,
            admission_id="adm_missing",
            actor="operator",
            at=NOW,
        )
    row = await admit(_facts(), at=NOW)
    # Cross-tenant advance fails closed too — the record is not visible.
    with pytest.raises(ValueError, match="no §16 admission record"):
        await advance_stage(
            tenant_id=TENANT_B,
            environment_id=ENV,
            admission_id=row["admission_id"],
            actor="operator",
            at=NOW,
        )


@pytest.mark.asyncio
async def test_activate_requires_the_full_walk_and_sets_active() -> None:
    row = await admit(_facts(), at=NOW)
    admission_id = row["admission_id"]
    # A record at discover cannot jump to activate — the full walk is owed.
    with pytest.raises(ValueError, match="illegal §16 activation"):
        await activate(
            tenant_id=TENANT_A,
            environment_id=ENV,
            admission_id=admission_id,
            actor="operator",
            at=NOW,
        )
    for _ in range(7):  # discover -> ... -> compile
        row = await advance_stage(
            tenant_id=TENANT_A,
            environment_id=ENV,
            admission_id=admission_id,
            actor="operator",
            at=NOW,
        )
    assert row["current_stage"] == "compile"
    assert row["active"] is False
    row = await activate(
        tenant_id=TENANT_A,
        environment_id=ENV,
        admission_id=admission_id,
        actor="operator",
        at=NOW,
    )
    assert row["current_stage"] == "activate"
    assert row["active"] is True
    # An already-activated record re-entering activate fails closed.
    with pytest.raises(ValueError, match="illegal §16 activation"):
        await activate(
            tenant_id=TENANT_A,
            environment_id=ENV,
            admission_id=admission_id,
            actor="operator",
            at=NOW,
        )


@pytest.mark.asyncio
async def test_engine_rejects_unknown_source_origin_facts() -> None:
    with pytest.raises(ValueError, match="source_origin"):
        await admit(_facts(source_origin="shadow_tenant"), at=NOW)
    assert (
        await get_admission_record_repository().list(
            tenant_id=TENANT_A, environment_id=ENV
        )
        == []
    )


# ── 5b. continuous-lifecycle moves through the engine ────────────────────────


@pytest.mark.asyncio
async def test_set_lifecycle_state_persists_only_drawn_edges() -> None:
    row = await admit(_facts(), at=NOW)
    admission_id = row["admission_id"]
    assert row["lifecycle_state"] == "monitor"

    # monitor -> reconcile would skip drift — fail closed, nothing persisted.
    with pytest.raises(ValueError, match="illegal §16"):
        await set_lifecycle_state(
            tenant_id=TENANT_A,
            environment_id=ENV,
            admission_id=admission_id,
            to_state="reconcile",
            actor="operator",
            at=NOW,
        )
    # reconcile -> approve — approve is an admission stage, not an action.
    row = await set_lifecycle_state(
        tenant_id=TENANT_A,
        environment_id=ENV,
        admission_id=admission_id,
        to_state="drift",
        actor="operator",
        at=NOW,
    )
    assert row["lifecycle_state"] == "drift"
    assert row["current_stage"] == "discover"  # stage position untouched
    with pytest.raises(ValueError, match="illegal §16"):
        await set_lifecycle_state(
            tenant_id=TENANT_A,
            environment_id=ENV,
            admission_id=admission_id,
            to_state="monitor",  # drift has only one drawn exit
            actor="operator",
            at=NOW,
        )
    row = await set_lifecycle_state(
        tenant_id=TENANT_A,
        environment_id=ENV,
        admission_id=admission_id,
        to_state="reconcile",
        actor="operator",
        at=NOW,
    )
    assert row["lifecycle_state"] == "reconcile"

    # change and review close the loop back into monitoring...
    row = await set_lifecycle_state(
        tenant_id=TENANT_A,
        environment_id=ENV,
        admission_id=admission_id,
        to_state="change",
        actor="operator",
        at=NOW,
    )
    row = await set_lifecycle_state(
        tenant_id=TENANT_A,
        environment_id=ENV,
        admission_id=admission_id,
        to_state="monitor",
        actor="operator",
        at=NOW,
    )
    assert row["lifecycle_state"] == "monitor"


@pytest.mark.asyncio
async def test_suspend_and_revoke_are_operator_governed_with_no_exit() -> None:
    row = await admit(_facts(), at=NOW)
    admission_id = row["admission_id"]

    async def _to(state: str) -> dict:
        return await set_lifecycle_state(
            tenant_id=TENANT_A,
            environment_id=ENV,
            admission_id=admission_id,
            to_state=state,
            actor="operator",
            at=NOW,
        )

    for state in ("drift", "reconcile", "revoke"):
        row = await _to(state)
        assert row["lifecycle_state"] == state
    # Revoke is terminal for the auto-loop: every exit raises.
    for attempted in ("monitor", "change", "review", "drift"):
        with pytest.raises(ValueError, match="illegal §16"):
            await _to(attempted)

    # A second record walks to suspend; same operator-governed dead end.
    other = await admit(_facts(integration="mi-sdk-2"), at=NOW)
    for state in ("drift", "reconcile", "suspend"):
        other = await set_lifecycle_state(
            tenant_id=TENANT_A,
            environment_id=ENV,
            admission_id=other["admission_id"],
            to_state=state,
            actor="operator",
            at=NOW,
        )
        assert other["lifecycle_state"] == state
    with pytest.raises(ValueError, match="illegal §16"):
        await set_lifecycle_state(
            tenant_id=TENANT_A,
            environment_id=ENV,
            admission_id=other["admission_id"],
            to_state="monitor",
            actor="operator",
            at=NOW,
        )


@pytest.mark.asyncio
async def test_set_lifecycle_state_on_missing_record_raises() -> None:
    with pytest.raises(ValueError, match="no §16 admission record"):
        await set_lifecycle_state(
            tenant_id=TENANT_A,
            environment_id=ENV,
            admission_id="adm_missing",
            to_state="drift",
            actor="operator",
            at=NOW,
        )


# ── 6. repository vocabulary + scoping ───────────────────────────────────────


@pytest.mark.asyncio
async def test_repo_create_rejects_unknown_vocabulary() -> None:
    repo = get_admission_record_repository()
    with pytest.raises(ValueError, match="§16"):
        await repo.create(_repo_view(current_stage="wat"))
    with pytest.raises(ValueError, match="§16"):
        await repo.create(_repo_view(lifecycle_state="wat"))
    # Nothing partial was persisted by the failed creates.
    assert await repo.list(tenant_id=TENANT_A, environment_id=ENV) == []


@pytest.mark.asyncio
async def test_repo_update_stage_rejects_unknown_vocabulary() -> None:
    repo = get_admission_record_repository()
    await repo.create(_repo_view())
    with pytest.raises(ValueError, match="§16"):
        await repo.update_stage(
            tenant_id=TENANT_A,
            environment_id=ENV,
            admission_id="adm_1",
            current_stage="wat",
        )
    with pytest.raises(ValueError, match="§16"):
        await repo.update_stage(
            tenant_id=TENANT_A,
            environment_id=ENV,
            admission_id="adm_1",
            current_stage="understand",
            lifecycle_state="wat",
        )
    with pytest.raises(ValueError, match="§16"):
        await repo.list(tenant_id=TENANT_A, stage="wat")
    # The rejected moves never touched the row.
    row = await repo.get(tenant_id=TENANT_A, environment_id=ENV, admission_id="adm_1")
    assert row is not None
    assert row["current_stage"] == "discover"
    assert row["lifecycle_state"] == "monitor"


@pytest.mark.asyncio
async def test_repo_update_stage_cross_scope_returns_none() -> None:
    repo = get_admission_record_repository()
    await repo.create(_repo_view())
    assert (
        await repo.update_stage(
            tenant_id=TENANT_B,
            environment_id=ENV,
            admission_id="adm_1",
            current_stage="understand",
            at=NOW,
        )
        is None
    )
    assert (
        await repo.update_stage(
            tenant_id=TENANT_A,
            environment_id="env-other",
            admission_id="adm_1",
            current_stage="understand",
            at=NOW,
        )
        is None
    )
    # The record itself is untouched by cross-scope attempts.
    row = await repo.get(tenant_id=TENANT_A, environment_id=ENV, admission_id="adm_1")
    assert row is not None
    assert row["current_stage"] == "discover"
    assert row["updated_at"] == NOW.isoformat()


@pytest.mark.asyncio
async def test_repo_update_stage_stamps_updated_at_and_preserves_columns() -> None:
    repo = get_admission_record_repository()
    await repo.create(_repo_view())
    later = NOW + timedelta(hours=1)
    updated = await repo.update_stage(
        tenant_id=TENANT_A,
        environment_id=ENV,
        admission_id="adm_1",
        current_stage="understand",
        at=later,
    )
    assert updated is not None
    assert updated["current_stage"] == "understand"
    assert updated["lifecycle_state"] == "monitor"  # left as-is
    assert updated["active"] is False  # left as-is
    assert updated["updated_at"] == later.isoformat()
    assert updated["created_at"] == NOW.isoformat()  # created stamp survives
    # Explicit booleans and lifecycle actions persist through the same API.
    updated = await repo.update_stage(
        tenant_id=TENANT_A,
        environment_id=ENV,
        admission_id="adm_1",
        current_stage="activate",
        lifecycle_state="reconcile",
        active=True,
        at=later,
    )
    assert updated is not None
    assert updated["current_stage"] == "activate"
    assert updated["lifecycle_state"] == "reconcile"
    assert updated["active"] is True


# ── 7. flag-OFF parity: importable and inert ─────────────────────────────────


def test_admission_engine_imports_inert_while_flags_off() -> None:
    # Nothing about the engine auto-runs or auto-mounts while the Reconciled
    # Control Plane flags are OFF — the module is importable and pure.
    import services.managed_integrations.admission as admission_module
    from services.managed_integrations import flags

    assert flags.enabled() is False
    for name in (
        "admit",
        "get_or_create",
        "advance_stage",
        "set_lifecycle_state",
        "activate",
        "validate_stage_move",
        "validate_lifecycle_move",
    ):
        assert callable(getattr(admission_module, name))
    assert isinstance(admission_module.STAGE_ADJACENCY, dict)
    assert isinstance(admission_module.CONT_LIFECYCLE_EDGES, dict)
    assert admission_module.STAGE_ADJACENCY["observe"] is None
    assert admission_module.CONT_LIFECYCLE_EDGES["revoke"] == frozenset()
