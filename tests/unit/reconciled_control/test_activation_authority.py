"""Program B — durable production activation authority law.

Pins the activation contract: one-step ordered advance, freeze-from-anywhere,
resume-to-frozen-state, readiness-gated advance/resume, flags-as-kill-switches,
revision CAS, scope validation and append-only transition evidence.
"""

from __future__ import annotations

import pytest

from connectors.managed_integrations.activation import (
    ActivationScope,
    ActivationTransitionError,
    ControlPlaneActivationService,
    RuntimeActivationResolver,
    combine_runtime_states,
    effective_state,
    next_activation_state,
    readiness_from_controls,
    runtime_capabilities,
)
from connectors.managed_integrations.activation_repository import (
    get_activation_repository,
)
from connectors.managed_integrations.contracts import (
    ControlPlaneActivationReadinessView,
)

READY = readiness_from_controls(
    {"control_plane_api": True, "readiness_model": True},
    evidence_ref="evidence:ready-1",
)


def _all_flags_on():
    return dict(enabled=True, reconciler_enabled=True, scheduler_enabled=True)


def _service() -> ControlPlaneActivationService:
    return ControlPlaneActivationService(repository=get_activation_repository())


# ── scope ───────────────────────────────────────────────────────────────────


def test_global_scope_id_is_stable():
    assert ActivationScope().activation_id == "rcpa:global:global:-:-"


def test_tenant_scope_requires_both_ids():
    with pytest.raises(ValueError):
        ActivationScope(scope_kind="tenant_environment", tenant_id="t1")
    with pytest.raises(ValueError):
        ActivationScope(
            scope_kind="tenant_environment", environment_id="prod"
        )


def test_global_scope_rejects_tenant_narrowing():
    with pytest.raises(ValueError):
        ActivationScope(scope_kind="global", tenant_id="t1")


# ── effective-state law ─────────────────────────────────────────────────────


def test_master_kill_switch_is_inclusive_disabled():
    state, blockers = effective_state(
        "fully_managed",
        enabled=False,
        reconciler_enabled=True,
        scheduler_enabled=True,
    )
    assert state == "disabled"
    assert blockers == ["master_kill_switch_off"]


def test_reconciler_kill_switch_caps_at_shadow():
    state, blockers = effective_state(
        "fully_managed",
        enabled=True,
        reconciler_enabled=False,
        scheduler_enabled=True,
    )
    assert state == "shadow"
    assert "reconciler_kill_switch_off" in blockers


def test_scheduler_kill_switch_caps_at_plan():
    state, blockers = effective_state(
        "r2",
        enabled=True,
        reconciler_enabled=True,
        scheduler_enabled=False,
    )
    assert state == "plan"
    assert "scheduler_kill_switch_off" in blockers


def test_kill_switch_never_raises_durable_state():
    state, blockers = effective_state(
        "shadow",
        enabled=True,
        reconciler_enabled=False,
        scheduler_enabled=False,
    )
    assert state == "shadow"
    assert blockers == [
        "reconciler_kill_switch_off",
        "scheduler_kill_switch_off",
    ]


def test_frozen_survives_non_master_flags_off():
    state, blockers = effective_state(
        "emergency_frozen",
        enabled=True,
        reconciler_enabled=False,
        scheduler_enabled=False,
    )
    assert state == "emergency_frozen"
    assert blockers == ["emergency_frozen"]


def test_master_kill_switch_disables_even_a_frozen_state():
    state, blockers = effective_state(
        "emergency_frozen",
        enabled=False,
        reconciler_enabled=True,
        scheduler_enabled=True,
    )
    assert state == "disabled"
    assert blockers == ["master_kill_switch_off"]


# ── advance law ─────────────────────────────────────────────────────────────


def test_next_state_is_one_step_and_terminal_at_fully_managed():
    assert next_activation_state("shadow") == "detect"
    assert next_activation_state("r1") == "r2"
    assert next_activation_state("fully_managed") is None
    with pytest.raises(ValueError):
        next_activation_state("emergency_frozen")


async def test_default_scope_is_shadow_not_live():
    view = await _service().get(ActivationScope())
    assert view.state == "shadow"
    assert view.revision == 0
    assert view.effective_state in {"disabled", "shadow"}


async def test_advance_requires_a_readiness_snapshot(rcp_flags):
    rcp_flags(**_all_flags_on())
    with pytest.raises(ActivationTransitionError) as exc:
        await _service().transition(ActivationScope(), "advance")
    assert exc.value.reason == "readiness_snapshot_missing"


async def test_advance_denied_when_readiness_not_ready(rcp_flags):
    rcp_flags(**_all_flags_on())
    not_ready = readiness_from_controls({"control_plane_api": False})
    with pytest.raises(ActivationTransitionError) as exc:
        await _service().transition(
            ActivationScope(), "advance", readiness=not_ready
        )
    assert exc.value.reason == "readiness_not_ready"


async def test_advance_denied_when_readiness_snapshot_has_no_controls(rcp_flags):
    rcp_flags(**_all_flags_on())
    empty = ControlPlaneActivationReadinessView(
        ready=True, controls={}, blockers=[]
    )
    with pytest.raises(ActivationTransitionError) as exc:
        await _service().transition(ActivationScope(), "advance", readiness=empty)
    assert exc.value.reason == "readiness_snapshot_empty"


async def test_advance_denied_when_ready_contradicts_blockers(rcp_flags):
    rcp_flags(**_all_flags_on())
    contradictory = ControlPlaneActivationReadinessView(
        ready=True,
        controls={"control_plane_api": False},
        blockers=["control_plane_api_unavailable"],
    )
    with pytest.raises(ActivationTransitionError) as exc:
        await _service().transition(
            ActivationScope(), "advance", readiness=contradictory
        )
    assert exc.value.reason == "readiness_not_ready"


async def test_advance_moves_one_step_and_records_evidence(rcp_flags):
    rcp_flags(**_all_flags_on())
    scope = ActivationScope(scope_kind="tenant_environment", tenant_id="t1", environment_id="prod")
    service = _service()
    view = await service.transition(
        scope, "advance", readiness=READY, actor="operator-1", reason="pilot"
    )
    assert view.state == "detect"
    assert view.previous_state == "shadow"
    assert view.revision == 1

    history = await service.transitions(scope)
    assert [row["transition"] for row in history] == ["advance"]
    assert history[0]["actor"] == "operator-1"
    assert history[0]["readiness_ref"] == "evidence:ready-1"


async def test_transitions_are_one_step_only(rcp_flags):
    # There is no "advance to X" API: each call moves exactly one state, so a
    # caller cannot jump rings or smuggle a target state.
    rcp_flags(**_all_flags_on())
    service = _service()
    scope = ActivationScope()
    await service.transition(scope, "advance", readiness=READY)
    assert (await service.get(scope)).state == "detect"
    await service.transition(scope, "advance", readiness=READY)
    assert (await service.get(scope)).state == "plan"


async def test_advance_is_terminal_at_fully_managed(rcp_flags):
    rcp_flags(**_all_flags_on())
    service = _service()
    scope = ActivationScope()
    for _ in range(6):
        await service.transition(scope, "advance", readiness=READY)
    view = await service.get(scope)
    assert view.state == "fully_managed"
    with pytest.raises(ActivationTransitionError) as exc:
        await service.transition(scope, "advance", readiness=READY)
    assert exc.value.reason == "terminal"


# ── freeze / resume law ─────────────────────────────────────────────────────


async def test_freeze_requires_reason_and_never_waits_for_readiness(rcp_flags):
    rcp_flags(**_all_flags_on())
    service = _service()
    scope = ActivationScope()
    await service.transition(scope, "advance", readiness=READY)
    with pytest.raises(ActivationTransitionError) as exc:
        await service.transition(scope, "freeze")
    assert exc.value.reason == "reason_required"
    with pytest.raises(ActivationTransitionError) as exc:
        await service.transition(scope, "freeze", reason="   ")
    assert exc.value.reason == "reason_required"

    frozen = await service.transition(
        scope, "freeze", reason="change freeze", actor="oncall"
    )
    assert frozen.state == "emergency_frozen"
    assert frozen.frozen_from_state == "detect"


async def test_freeze_records_an_unready_snapshot_as_not_ready(rcp_flags):
    rcp_flags(**_all_flags_on())
    service = _service()
    scope = ActivationScope()
    not_ready = readiness_from_controls({"control_plane_api": False})
    await service.transition(
        scope,
        "freeze",
        reason="safety",
        readiness=not_ready,
        actor="operator@example.com",
    )
    evidence = await service.transitions(scope)
    assert evidence[0]["readiness_ready"] is False


async def test_resume_restores_pre_freeze_state(rcp_flags):
    rcp_flags(**_all_flags_on())
    service = _service()
    scope = ActivationScope()
    await service.transition(scope, "advance", readiness=READY)
    await service.transition(scope, "freeze", reason="incident")
    resumed = await service.transition(scope, "resume", readiness=READY)
    assert resumed.state == "detect"
    assert resumed.frozen_from_state is None


async def test_resume_requires_readiness_and_frozen_state(rcp_flags):
    rcp_flags(**_all_flags_on())
    service = _service()
    scope = ActivationScope()
    with pytest.raises(ActivationTransitionError) as exc:
        await service.transition(scope, "resume", readiness=READY)
    assert exc.value.reason == "not_frozen"

    await service.transition(scope, "freeze", reason="incident")
    with pytest.raises(ActivationTransitionError) as exc:
        await service.transition(scope, "resume")
    assert exc.value.reason == "readiness_snapshot_missing"


async def test_advance_after_freeze_is_refused_until_resume(rcp_flags):
    rcp_flags(**_all_flags_on())
    service = _service()
    scope = ActivationScope()
    await service.transition(scope, "freeze", reason="incident")
    with pytest.raises(ActivationTransitionError) as exc:
        await service.transition(scope, "advance", readiness=READY)
    assert exc.value.reason == "frozen"


# ── durability / isolation ──────────────────────────────────────────────────


async def test_flags_lower_effective_but_not_durable_state(rcp_flags):
    rcp_flags(**_all_flags_on())
    service = _service()
    scope = ActivationScope()
    await service.transition(scope, "advance", readiness=READY)

    rcp_flags(enabled=True, reconciler_enabled=True, scheduler_enabled=False)
    assert (await service.get(scope)).state == "detect"
    view = await service.get(scope)
    assert view.effective_state == "detect"  # ceiling plan is above detect

    rcp_flags(enabled=True, reconciler_enabled=False, scheduler_enabled=False)
    assert (await service.get(scope)).effective_state == "shadow"
    assert (await service.get(scope)).state == "detect"


async def test_revision_cas_rejects_stale_writer():
    repo = get_activation_repository()
    created = await repo.create(
        {
            "activation_id": "rcpa:test",
            "scope_kind": "global",
            "region": "global",
            "state": "shadow",
            "revision": 0,
            "readiness_ready": False,
        }
    )
    assert created is not None and created["revision"] == 0
    first = await repo.update(
        "rcpa:test",
        expected_revision=0,
        state="detect",
        previous_state="shadow",
        frozen_from_state=None,
        readiness_ref=None,
        readiness_ready=False,
        reason=None,
        updated_by="a",
    )
    assert first is not None and first["revision"] == 1
    stale = await repo.update(
        "rcpa:test",
        expected_revision=0,
        state="plan",
        previous_state="shadow",
        frozen_from_state=None,
        readiness_ref=None,
        readiness_ready=False,
        reason=None,
        updated_by="b",
    )
    assert stale is None
    assert (await repo.get("rcpa:test"))["state"] == "detect"


async def test_scopes_are_isolated(rcp_flags):
    rcp_flags(**_all_flags_on())
    service = _service()
    tenant_a = ActivationScope(scope_kind="tenant_environment", tenant_id="a", environment_id="prod")
    tenant_b = ActivationScope(scope_kind="tenant_environment", tenant_id="b", environment_id="prod")
    await service.transition(tenant_a, "advance", readiness=READY)
    assert (await service.get(tenant_a)).state == "detect"
    assert (await service.get(tenant_b)).state == "shadow"
    assert len(await service.list(scope_kind="tenant_environment", tenant_id="a")) == 1
    assert await service.list(scope_kind="tenant_environment", tenant_id="c") == []


async def test_tenant_scope_is_isolated_in_list(rcp_flags):
    rcp_flags(**_all_flags_on())
    service = _service()
    await service.transition(
        ActivationScope(scope_kind="tenant_environment", tenant_id="a", environment_id="prod"),
        "advance",
        readiness=READY,
    )
    rows = await service.list(tenant_id="b")
    assert rows == []


async def test_freeze_reason_is_stripped_in_state_and_evidence(rcp_flags):
    rcp_flags(**_all_flags_on())
    service = _service()
    scope = ActivationScope()
    await service.transition(scope, "freeze", reason="  incident  ")
    assert (await service.get(scope)).reason == "incident"
    history = await service.transitions(scope)
    assert history[0]["reason"] == "incident"


async def test_apply_transition_writes_state_and_evidence_or_neither():
    repo = get_activation_repository()
    kwargs = dict(
        activation_id="rcpa:atomic",
        scope_kind="global",
        tenant_id=None,
        environment_id=None,
        region="global",
        expected_revision=0,
        state="detect",
        previous_state="shadow",
        frozen_from_state=None,
        readiness_ref="evidence:ready",
        readiness_ready=True,
        reason="test",
        updated_by="operator",
        transition="advance",
    )
    first = await repo.apply_transition(**kwargs)
    assert first is not None and first["revision"] == 1
    assert first["state"] == "detect"
    assert len(await repo.list_transitions(activation_id="rcpa:atomic")) == 1

    raced = await repo.apply_transition(**kwargs)
    assert raced is None
    assert len(await repo.list_transitions(activation_id="rcpa:atomic")) == 1
    assert (await repo.get("rcpa:atomic"))["state"] == "detect"


# ── Program C — runtime activation gate ─────────────────────────────────────


def test_runtime_capabilities_are_monotone_over_the_advance_path():
    assert runtime_capabilities("disabled") == frozenset()
    assert runtime_capabilities("shadow") == frozenset({"observe"})
    assert runtime_capabilities("detect") == frozenset({"observe", "detect"})
    assert runtime_capabilities("plan") == frozenset(
        {"observe", "detect", "plan"}
    )
    for state in ("r0", "r1", "r2", "fully_managed"):
        assert runtime_capabilities(state) == frozenset(
            {"observe", "detect", "plan", "execute"}
        )
    assert runtime_capabilities("emergency_frozen") == frozenset()
    with pytest.raises(ValueError):
        runtime_capabilities("not-a-state")


def test_combine_runtime_states_never_raises_above_the_global_scope():
    assert combine_runtime_states("fully_managed", "plan") == "plan"
    assert combine_runtime_states("plan", "fully_managed") == "plan"
    assert combine_runtime_states("r2", "r2") == "r2"
    assert combine_runtime_states("fully_managed", "emergency_frozen") == (
        "emergency_frozen"
    )
    assert combine_runtime_states("disabled", "fully_managed") == "disabled"


async def test_get_recorded_distinguishes_absent_scope_from_shadow(rcp_flags):
    rcp_flags(**_all_flags_on())
    service = _service()
    assert await service.get_recorded(ActivationScope()) is None
    assert (await service.get(ActivationScope())).state == "shadow"


async def test_resolver_inherits_global_when_tenant_row_is_absent(rcp_flags):
    rcp_flags(**_all_flags_on())
    service = _service()
    global_scope = ActivationScope()
    for _ in range(6):
        await service.transition(global_scope, "advance", readiness=READY)

    decision = await RuntimeActivationResolver(service).resolve(
        tenant_id="tenant-a", environment_id="prod"
    )
    assert decision.state == "fully_managed"
    assert decision.global_state == "fully_managed"
    assert decision.tenant_state is None
    assert decision.can("execute")


async def test_resolver_allows_a_tenant_scope_to_narrow_global(rcp_flags):
    rcp_flags(**_all_flags_on())
    service = _service()
    global_scope = ActivationScope()
    for _ in range(6):
        await service.transition(global_scope, "advance", readiness=READY)
    tenant = ActivationScope(
        scope_kind="tenant_environment", tenant_id="tenant-a", environment_id="prod"
    )
    await service.transition(tenant, "advance", readiness=READY)
    await service.transition(tenant, "advance", readiness=READY)

    decision = await RuntimeActivationResolver(service).resolve(
        tenant_id="tenant-a", environment_id="prod"
    )
    assert decision.state == "plan"
    assert decision.tenant_state == "plan"
    assert decision.can("plan")
    assert not decision.can("execute")


async def test_resolver_never_lets_a_tenant_exceed_global(rcp_flags):
    rcp_flags(**_all_flags_on())
    service = _service()
    global_scope = ActivationScope()
    await service.transition(global_scope, "advance", readiness=READY)
    await service.transition(global_scope, "advance", readiness=READY)
    tenant = ActivationScope(
        scope_kind="tenant_environment", tenant_id="tenant-a", environment_id="prod"
    )
    for _ in range(6):
        await service.transition(tenant, "advance", readiness=READY)

    decision = await RuntimeActivationResolver(service).resolve(
        tenant_id="tenant-a", environment_id="prod"
    )
    assert decision.state == "plan"
    assert decision.global_state == "plan"
    assert decision.tenant_state == "fully_managed"
    assert not decision.can("execute")


async def test_resolver_freeze_stops_the_runtime(rcp_flags):
    rcp_flags(**_all_flags_on())
    service = _service()
    global_scope = ActivationScope()
    await service.transition(global_scope, "advance", readiness=READY)
    await service.transition(global_scope, "freeze", reason="incident")

    decision = await RuntimeActivationResolver(service).resolve(
        tenant_id="tenant-a", environment_id="prod"
    )
    assert decision.state == "emergency_frozen"
    assert decision.capabilities == frozenset()
    assert "emergency_frozen" in decision.blockers


async def test_resolver_master_kill_switch_stops_the_runtime(rcp_flags):
    rcp_flags(
        enabled=False, reconciler_enabled=True, scheduler_enabled=True
    )
    decision = await RuntimeActivationResolver(_service()).resolve(
        tenant_id="tenant-a", environment_id="prod"
    )
    assert decision.state == "disabled"
    assert decision.capabilities == frozenset()
    assert "master_kill_switch_off" in decision.blockers
