"""Reconciled Control Plane — §34 executor (Phase 2) tests.

Covers the Phase-2 governed execution path end to end against the in-memory
repositories: §34 transition legality (reserved simulating/canary/rolling_out
statuses unreachable), §35 stale-plan supersession before any apply, §21/§39
token gating with the approval-record surface, the §36 actuator apply →
verify → rollback lifecycle with attempted/applied evidence (§12.13/§12.15),
LKG establishment only after verification (§12.12), §12.11 rollback records,
§12.14 ActionRequired surfacing (no fabrication when an authority is absent),
lease expiry, terminal short-circuiting and flag-OFF import parity.

No live database is touched: the shared ``_reset_rcp_stores`` fixture empties
the in-memory stores before/after every test, and the module-local
``_executor_db_free`` fixture pins every ``get_pool`` the repositories import
to None.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from services.managed_integrations.actuators import (
    Actuator,
    ActuatorApplyResult,
    ActuatorAuthority,
    ActuatorVerifyResult,
    RepositoryUpgradeActuator,
    get_actuator_registry,
    registry_with_authorities,
)
from services.managed_integrations.change_sets_repository import (
    get_change_set_repository,
)
from services.managed_integrations.contracts import (
    BlastRadiusView,
    ChangeSetApprovalView,
    ChangeSetPlanView,
    ChangeSpec,
    CONTROL_FINDING_KINDS,
    RiskAssessmentView,
)
from services.managed_integrations.execution_records_repository import (
    get_action_required_repository,
    get_change_evidence_repository,
    get_change_set_approval_repository,
    get_change_set_event_repository,
    get_change_set_rollback_repository,
    get_last_known_good_repository,
)
from services.managed_integrations.executor import (
    S34_TRANSITIONS,
    RunOutcome,
    TargetSnapshot,
    acquire_lease,
    lease_valid,
    legal_transitions,
    missing_tokens,
    required_tokens,
    rollout_required,
    run_changeset,
    validate_transition,
)

TENANT = "tenant-a"
ENV = "env-1"
INTEGRATION = "mi-sdk-1"
NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)

_DEFAULT_APPROVAL_REFS: dict[str, list[str]] = {
    "R3": ["approval:olympus_operator"],
    "R4": ["approval:tenant_owner"],
    "R5": ["approval:governed"],
    "security_emergency": ["approval:olympus_security"],
}


@pytest.fixture(autouse=True)
def _executor_db_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``get_pool`` to None on every repository module the executor uses.

    The in-memory stores are cleared by the shared ``_reset_rcp_stores``
    fixture; this only guarantees repo writes never reach a live Postgres even
    under an ambient non-local ``AETHER_ENV``.
    """
    import services.managed_integrations.change_sets_repository as cs_module
    import services.managed_integrations.execution_records_repository as er_module

    async def _no_pool() -> None:
        return None

    monkeypatch.setattr(cs_module, "get_pool", _no_pool)
    monkeypatch.setattr(er_module, "get_pool", _no_pool)
    try:
        import repositories.repos as repos_module
    except Exception:  # noqa: BLE001 - import-defensive; optional patch target
        return
    monkeypatch.setattr(repos_module, "get_pool", _no_pool)


# ── helpers ──────────────────────────────────────────────────────────────────


def _plan(
    status: str = "planned",
    risk_class: str = "R0",
    actions: tuple[str, ...] = ("repository_upgrade",),
    approval_refs: Optional[list[str]] = None,
    changeset_id: str = "rcs_e2e_1",
) -> ChangeSetPlanView:
    """One typed ChangeSet plan over the e2e integration (Phase-2 vocabulary)."""
    if approval_refs is None:
        approval_refs = _DEFAULT_APPROVAL_REFS.get(risk_class, [])
    return ChangeSetPlanView(
        changeset_id=changeset_id,
        tenant_id=TENANT,
        environment_id=ENV,
        integration_scope=[INTEGRATION],
        desired_revision="rev-1",
        observed_revision="rev-0",
        reconcile_sequence="rc_e2e_1",
        idempotency_key="ik_e2e_1",
        changes=[
            ChangeSpec(action=action, target_ref=INTEGRATION, reason="e2e drift")
            for action in actions
        ],
        reason="e2e plan",
        initiator="reconciler",
        policy_ref="policy/rollout-prod-default",
        risk=RiskAssessmentView(
            risk_class=risk_class,
            automation_allowed=risk_class in {"R0", "R1", "R2"},
            required_approval_refs=approval_refs,
            explanation_refs=[],
        ),
        blast_radius=BlastRadiusView(
            integration_count=1,
            tenant_count=1,
            environment_count=1,
            source_origins=["tenant"],
            actionable_drift_types=["version_drift"],
        ),
        status=status,
        created_at=NOW,
    )


def _target() -> TargetSnapshot:
    return TargetSnapshot(
        managed_integration_ref=INTEGRATION,
        desired_state_ref="ds:0",
        last_known_good_ref="lkg:prior",
        replay_after_recovery=False,
    )


async def _persist(plan: ChangeSetPlanView) -> None:
    """Create the plan row (the caller owns row creation, never the executor)."""
    await get_change_set_repository().create(plan)


async def _run(
    plan: ChangeSetPlanView,
    *,
    registry=None,
    current_desired_revision: Optional[str] = None,
    current_observed_revision: Optional[str] = None,
    lease_seconds: int = 300,
) -> RunOutcome:
    return await run_changeset(
        plan,
        target=_target(),
        current_desired_revision=current_desired_revision or plan.desired_revision,
        current_observed_revision=current_observed_revision or plan.observed_revision,
        actor="operator",
        now=NOW,
        registry=registry,
        lease_seconds=lease_seconds,
    )


class RecordingAuthority:
    """§36 authority handler recording every lifecycle call it receives.

    apply/verify/rollback results are injectable so one handler covers the
    applied, applied-with-failed-verify and failed-rollback behaviours.
    """

    def __init__(
        self,
        *,
        apply_result: Optional[ActuatorApplyResult] = None,
        rollback_result: Optional[ActuatorApplyResult] = None,
    ) -> None:
        self.calls: list[tuple[str, ChangeSpec]] = []
        self.apply_result = apply_result or ActuatorApplyResult(
            outcome="applied", before_state_ref="ds:1", after_state_ref="ds:2"
        )
        self.rollback_result = rollback_result or ActuatorApplyResult(
            outcome="applied", before_state_ref="ds:2", after_state_ref="ds:0"
        )

    async def apply(self, change: ChangeSpec, actuator: Actuator) -> ActuatorApplyResult:
        self.calls.append(("apply", change))
        return self.apply_result

    async def verify(self, change: ChangeSpec, actuator: Actuator) -> ActuatorVerifyResult:
        self.calls.append(("verify", change))
        return ActuatorVerifyResult()

    async def rollback(self, change: ChangeSpec, actuator: Actuator) -> ActuatorApplyResult:
        self.calls.append(("rollback", change))
        return self.rollback_result


def _admitted_registry(handler: RecordingAuthority):
    """A §36 registry admitting ``repository_upgrade`` through ``handler``."""
    return registry_with_authorities({"repository_upgrade": handler})


class _FailingVerifyAuthority(RecordingAuthority):
    """§36 authority whose §32 step-19 verify attestation fails.

    The base ``Actuator.verify`` delegates to an admitted authority's handler
    verify (mirroring apply/rollback), so the failure is injected exactly where
    the §36 verify contract lives — at the authority, not the actuator.
    ``inner`` keeps the apply/rollback results and the shared call log so tests
    observe the same handler end to end.
    """

    def __init__(self, inner: RecordingAuthority) -> None:
        super().__init__(
            apply_result=inner.apply_result, rollback_result=inner.rollback_result
        )
        self.calls = inner.calls  # shared call log

    async def verify(self, change: ChangeSpec, actuator: Actuator) -> ActuatorVerifyResult:
        self.calls.append(("verify", change))
        return ActuatorVerifyResult(
            technical="failed", semantic="passed", note="test: verify failure"
        )


def _failing_verify_registry(handler: RecordingAuthority):
    """A §36 registry admitting ``repository_upgrade`` through a handler whose
    verify attestation fails — drives the executor's rollback path."""
    return registry_with_authorities(
        {"repository_upgrade": _FailingVerifyAuthority(handler)}
    )


# ── 1. §34 transition legality ───────────────────────────────────────────────


def test_s34_legal_transitions_and_reserved_statuses_fail_closed() -> None:
    # The full Phase-2 apply path is legal step by step.
    chain = [
        "draft",
        "planned",
        "preparing",
        "validating",
        "ready",
        "verifying",
        "committed",
    ]
    for from_status, to_status in zip(chain, chain[1:]):
        validate_transition(from_status, to_status)  # must not raise

    # Illegal moves raise; terminals have no outgoing transitions.
    with pytest.raises(ValueError, match="illegal §34 transition"):
        validate_transition("draft", "committed")
    with pytest.raises(ValueError, match="illegal §34 transition"):
        validate_transition("planned", "committed")
    for terminal in ("committed", "rolled_back", "cancelled", "failed", "superseded"):
        assert legal_transitions(terminal) == frozenset()
        with pytest.raises(ValueError, match="illegal §34 transition"):
            validate_transition(terminal, "planned")

    # simulating/canary/rolling_out are Phase-3/4 reservations: no Phase-2
    # status may move toward them.
    reserved = {"simulating", "canary", "rolling_out"}
    for status in S34_TRANSITIONS:
        assert not (reserved & set(legal_transitions(status))), status
        for to_status in reserved:
            with pytest.raises(ValueError, match="illegal §34 transition"):
                validate_transition(status, to_status)


# ── 2. §39 token gating ──────────────────────────────────────────────────────


def test_required_and_missing_tokens_and_rollout_required() -> None:
    r1 = _plan(risk_class="R1")
    assert required_tokens(r1) == ["gate:simulation"]
    assert missing_tokens(r1, []) == ["gate:simulation"]
    assert missing_tokens(r1, ["gate:simulation"]) == []

    r3 = _plan(risk_class="R3")
    tokens = required_tokens(r3)
    assert "approval:olympus_operator" in tokens
    assert tokens == ["approval:olympus_operator"]

    r2 = _plan(risk_class="R2")
    assert required_tokens(r2) == ["gate:canary", "gate:health"]
    assert missing_tokens(r2, ["gate:canary", "gate:health"]) == []
    assert missing_tokens(r2, ["gate:health"]) == ["gate:canary"]

    assert rollout_required("R2") is True
    assert rollout_required("R0") is False
    assert rollout_required("R3") is False


# ── 3. R0 automatic commit ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_r0_automatic_commit_applies_records_lkg_and_evidence() -> None:
    plan = _plan()
    handler = RecordingAuthority()
    await _persist(plan)

    outcome = await _run(plan, registry=_admitted_registry(handler))

    assert outcome.reached_status == "committed"
    assert outcome.ok is True
    assert outcome.lkg_id is not None
    assert outcome.missing_tokens == []
    assert outcome.reason == "all §32 step-19 checks passed; committed"

    # §32 step-19 report passed on both dimensions.
    assert outcome.verify_report is not None
    assert outcome.verify_report.technical_health == "passed"
    assert outcome.verify_report.semantic_health == "passed"

    # The plan row moved through the §34 path and ended committed.
    row = await get_change_set_repository().get(TENANT, ENV, plan.changeset_id)
    assert row is not None and row["status"] == "committed"

    # LKG is established only now — after verification (§32 step 21).
    lkg = await get_last_known_good_repository().get_for_integration(TENANT, ENV, INTEGRATION)
    assert lkg is not None
    assert lkg["lkg_id"] == outcome.lkg_id
    assert lkg["managed_integration_ref"] == INTEGRATION

    # Every transition was persisted as an append-only event.
    events = await get_change_set_event_repository().list_for_changeset(
        tenant_id=TENANT, environment_id=ENV, changeset_id=plan.changeset_id
    )
    assert any(e["to_status"] == "preparing" for e in events)
    assert any(e["to_status"] == "verifying" for e in events)
    assert any(e["to_status"] == "committed" for e in events)

    # Evidence: one applied-change row (observed) + one verified aggregate
    # whose validation_refs point at the per-change rows.
    evidence = await get_change_evidence_repository().list_for_changeset(
        tenant_id=TENANT, environment_id=ENV, changeset_ref=plan.changeset_id
    )
    assert all(r["claim_type"] in CONTROL_FINDING_KINDS for r in evidence)
    per_change = [r for r in evidence if r["claim_type"] == "observed"]
    assert len(per_change) == 1
    assert per_change[0]["after_state_refs"] == ["ds:2"]
    assert per_change[0]["before_state_refs"] == ["ds:0", "ds:1"]
    verified = [r for r in evidence if r["claim_type"] == "verified"]
    assert len(verified) == 1
    assert verified[0]["after_state_refs"] == ["ds:2"]
    assert set(verified[0]["validation_refs"]) == {r["change_evidence_id"] for r in per_change}

    # The admitted §36 authority really performed the apply.
    assert ("apply", plan.changes[0]) in handler.calls


# ── 4. verify failure → rollback → rolled_back ───────────────────────────────


@pytest.mark.asyncio
async def test_verify_failure_rolls_back_to_rolled_back_without_lkg() -> None:
    plan = _plan()
    handler = RecordingAuthority()
    await _persist(plan)

    outcome = await _run(plan, registry=_failing_verify_registry(handler))

    assert outcome.reached_status == "rolled_back"
    assert outcome.ok is True
    assert outcome.rollback_id is not None
    assert outcome.verify_report is not None
    assert outcome.verify_report.technical_health == "failed"
    assert outcome.verify_report.semantic_health == "passed"

    # The rollback record ran to completion with a stamp (§12.11).
    record = await get_change_set_rollback_repository().get_for_changeset(
        tenant_id=TENANT, environment_id=ENV, changeset_ref=plan.changeset_id
    )
    assert record is not None
    assert record["status"] == "rolled_back"
    assert record["completed_at"] is not None
    assert record["rollback_id"] == outcome.rollback_id
    assert record["last_known_good_ref"] == "lkg:prior"
    assert record["rollback_actions"] == [f"{plan.changes[0].action}:{INTEGRATION}"]

    # Events recorded the whole rollback walk.
    events = await get_change_set_event_repository().list_for_changeset(
        tenant_id=TENANT, environment_id=ENV, changeset_id=plan.changeset_id
    )
    assert any(e["to_status"] == "rolling_back" for e in events)
    assert any(e["to_status"] == "rolled_back" for e in events)
    assert not any(e["to_status"] == "committed" for e in events)

    # The §36 authority rolled the applied change back (reverse order).
    assert ("rollback", plan.changes[0]) in handler.calls

    # LKG is never established when verification did not pass (§32 step 21).
    assert (
        await get_last_known_good_repository().get_for_integration(TENANT, ENV, INTEGRATION)
    ) is None

    row = await get_change_set_repository().get(TENANT, ENV, plan.changeset_id)
    assert row is not None and row["status"] == "rolled_back"


# ── 5. rollback failure → failed + ActionRequired ────────────────────────────


@pytest.mark.asyncio
async def test_rollback_failure_fails_and_surfaces_action_required() -> None:
    plan = _plan()
    handler = RecordingAuthority(
        rollback_result=ActuatorApplyResult(
            outcome="not_applied", detail="rollback substrate unavailable (test)"
        )
    )
    await _persist(plan)

    outcome = await _run(plan, registry=_failing_verify_registry(handler))

    assert outcome.reached_status == "failed"
    assert outcome.ok is False
    assert outcome.rollback_id is not None
    assert outcome.action_required_ids, "a manual-rollback action must be surfaced"

    # The rollback record is marked failed — no fabricated rollback.
    record = await get_change_set_rollback_repository().get_for_changeset(
        tenant_id=TENANT, environment_id=ENV, changeset_ref=plan.changeset_id
    )
    assert record is not None
    assert record["status"] == "failed"
    assert record["rollback_id"] == outcome.rollback_id

    # §12.14 ActionRequired: manual rollback with degraded continuity and
    # data loss expected — never a silent success.
    actions = await get_action_required_repository().list(tenant_ref=TENANT)
    rollback_actions = [a for a in actions if a["action_type"] == "rollback_failed"]
    assert len(rollback_actions) == 1
    surfaced = rollback_actions[0]
    assert surfaced["action_id"] == outcome.action_required_ids[0]
    assert surfaced["status"] == "open"
    assert surfaced["continuity_state"] == "degraded"
    assert surfaced["data_loss_expected"] is True
    assert "manual rollback required" in surfaced["required_action"]

    # Contradictory evidence is recorded, never dropped (§12.13).
    evidence = await get_change_evidence_repository().list_for_changeset(
        tenant_id=TENANT, environment_id=ENV, changeset_ref=plan.changeset_id
    )
    failed_rollback = [
        r for r in evidence if r["claim_type"] == "observed" and r["confidence"] == "low"
    ]
    assert len(failed_rollback) == 1
    assert failed_rollback[0]["rollback_ref"] == outcome.rollback_id
    assert failed_rollback[0]["contradictory_evidence_refs"]

    row = await get_change_set_repository().get(TENANT, ENV, plan.changeset_id)
    assert row is not None and row["status"] == "failed"
    assert ("rollback", plan.changes[0]) in handler.calls


# ── 6. §35 guard invalidation supersedes before apply ────────────────────────


@pytest.mark.asyncio
async def test_guard_invalidation_supersedes_before_any_apply() -> None:
    plan = _plan()
    handler = RecordingAuthority()
    await _persist(plan)

    # Desired state advanced since the plan was built: never apply it (§35).
    outcome = await run_changeset(
        plan,
        target=_target(),
        current_desired_revision=f"{plan.desired_revision}-next",
        current_observed_revision=plan.observed_revision,
        actor="operator",
        now=NOW,
        registry=_admitted_registry(handler),
    )

    assert outcome.reached_status == "superseded"
    assert outcome.superseded is True
    assert outcome.ok is False
    assert outcome.missing_tokens == []
    assert outcome.reason is not None and "desired_revision advanced" in outcome.reason
    assert not handler.calls, "no actuator may run against a stale plan"

    row = await get_change_set_repository().get(TENANT, ENV, plan.changeset_id)
    assert row is not None
    assert row["status"] == "superseded"
    assert row["superseded_at"] is not None

    events = await get_change_set_event_repository().list_for_changeset(
        tenant_id=TENANT, environment_id=ENV, changeset_id=plan.changeset_id
    )
    assert len(events) == 1
    assert events[0]["to_status"] == "superseded"


# ── 7. missing approval token defers; grant lets the run proceed ─────────────


@pytest.mark.asyncio
async def test_missing_gate_token_defers_then_commits_after_grant() -> None:
    plan = _plan(risk_class="R1")  # R1 declares the Phase-3 simulation gate
    handler = RecordingAuthority()
    await _persist(plan)

    first = await _run(plan, registry=_admitted_registry(handler))
    assert first.reached_status == "waiting_approval"
    assert first.ok is False
    assert first.missing_tokens == ["gate:simulation"]
    assert not handler.calls
    assert first.events and first.events[-1]["reason"] == (
        "awaiting approval tokens: ['gate:simulation']"
    )

    # Approvals are the explicit Phase-2 workflow surface (no ActionRequired
    # row is fabricated for a missing approval token).
    actions = await get_action_required_repository().list(tenant_ref=TENANT)
    assert actions == []

    # The operator records the §21 grant for the declared gate token.
    await get_change_set_approval_repository().create(
        ChangeSetApprovalView(
            approval_id="rca_1",
            changeset_ref=plan.changeset_id,
            tenant_id=TENANT,
            environment_id=ENV,
            required_approval_ref="gate:simulation",
            granted_role="olympus_operator",
            granted_by_actor="operator-1",
            decision="approved",
            note=None,
            decided_at=NOW,
        )
    )

    # Re-run drives from the persisted waiting_approval row to committed.
    second = await _run(plan, registry=_admitted_registry(handler))
    assert second.reached_status == "committed"
    assert second.ok is True
    assert second.lkg_id is not None
    assert second.missing_tokens == []
    assert ("apply", plan.changes[0]) in handler.calls


# ── 8. R2 rollout deferral (Phase-4 engine) ──────────────────────────────────


@pytest.mark.asyncio
async def test_r2_rollout_deferral_blocks_without_applying() -> None:
    plan = _plan(risk_class="R2")
    handler = RecordingAuthority()
    await _persist(plan)

    # Gate tokens granted — but progressive delivery is still Phase 4.
    for index, token in enumerate(("gate:canary", "gate:health")):
        await get_change_set_approval_repository().create(
            ChangeSetApprovalView(
                approval_id=f"rca_r2_{index}",
                changeset_ref=plan.changeset_id,
                tenant_id=TENANT,
                environment_id=ENV,
                required_approval_ref=token,
                granted_role="olympus_operator",
                granted_by_actor="operator-1",
                decision="approved",
                note=None,
                decided_at=NOW,
            )
        )

    outcome = await _run(plan, registry=_admitted_registry(handler))

    assert outcome.reached_status == "blocked"
    assert outcome.ok is False
    assert outcome.missing_tokens == []
    assert not handler.calls, "an R2 change must never apply directly in Phase 2"

    actions = await get_action_required_repository().list(tenant_ref=TENANT)
    deferrals = [a for a in actions if a["action_type"] == "rollout_engine_required"]
    assert len(deferrals) == 1
    assert deferrals[0]["continuity_state"] == "unchanged"
    assert deferrals[0]["required_actor"] == "olympus_operator"

    row = await get_change_set_repository().get(TENANT, ENV, plan.changeset_id)
    assert row is not None and row["status"] == "blocked"


# ── 9'. no admitted authority → preflight fails closed with evidence ─────────


@pytest.mark.asyncio
async def test_default_registry_preflight_failure_blocks_with_attempt_evidence() -> None:
    # The default §36 registry admits no authority: preflight fails closed and
    # the attempted change is recorded as before-state-only evidence — the
    # executor never claims applied for a change that did not run.
    plan = _plan()
    await _persist(plan)

    outcome = await run_changeset(
        plan,
        target=_target(),
        current_desired_revision=plan.desired_revision,
        current_observed_revision=plan.observed_revision,
        actor="operator",
        now=NOW,
        registry=get_actuator_registry(),
    )

    assert outcome.reached_status == "blocked"
    assert outcome.ok is False

    actions = await get_action_required_repository().list(tenant_ref=TENANT)
    assert [a["action_type"] for a in actions] == ["preflight_failed"]
    assert "no admitted authority" in actions[0]["reason"]

    evidence = await get_change_evidence_repository().list_for_changeset(
        tenant_id=TENANT, environment_id=ENV, changeset_ref=plan.changeset_id
    )
    assert len(evidence) == 1
    attempted = evidence[0]
    assert attempted["claim_type"] == "observed"
    assert attempted["confidence"] == "medium"
    assert attempted["after_state_refs"] == []
    assert attempted["before_state_refs"] == ["ds:0"]

    row = await get_change_set_repository().get(TENANT, ENV, plan.changeset_id)
    assert row is not None and row["status"] == "blocked"


# ── 11. terminal short-circuit ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_terminal_row_short_circuits_without_new_events() -> None:
    committed = _plan(status="committed")
    await _persist(committed)
    handler = RecordingAuthority()

    outcome = await _run(committed, registry=_admitted_registry(handler))

    assert outcome.reached_status == "committed"
    assert outcome.ok is True
    assert outcome.reason == "already terminal"
    assert outcome.events == []
    assert outcome.evidence_ids == []
    assert not handler.calls

    cancelled = _plan(status="cancelled", changeset_id="rcs_e2e_2")
    await _persist(cancelled)
    outcome = await _run(cancelled, registry=_admitted_registry(handler))
    assert outcome.reached_status == "cancelled"
    assert outcome.ok is False
    assert outcome.reason == "already terminal"
    assert outcome.events == []
    assert not handler.calls


# ── 12. flag-OFF parity ──────────────────────────────────────────────────────


def test_executor_is_importable_and_inert_without_an_explicit_caller() -> None:
    # Every Reconciled Control Plane flag defaults OFF; nothing here registers
    # a trigger, worker or route. A caller may still drive run_changeset
    # explicitly through the governed path.
    from services.managed_integrations import flags

    assert flags.enabled() is False
    assert callable(run_changeset)


# ── 13. lease expiry ─────────────────────────────────────────────────────────


def test_lease_helpers_expire_after_lease_seconds() -> None:
    lease = acquire_lease(owner="run:operator", now=NOW, lease_seconds=300)
    assert lease.owner == "run:operator"
    assert lease.expires_at == NOW + timedelta(seconds=300)
    assert lease_valid(lease, NOW) is True
    assert lease_valid(lease, NOW + timedelta(seconds=299)) is True
    assert lease_valid(lease, NOW + timedelta(seconds=300)) is False
    assert lease_valid(lease, NOW + timedelta(seconds=301)) is False

    # A zero-second lease is already expired at its acquisition instant.
    expired = acquire_lease(owner="run:operator", now=NOW, lease_seconds=0)
    assert lease_valid(expired, NOW) is False


@pytest.mark.asyncio
async def test_expired_lease_blocks_with_action_required_before_apply() -> None:
    plan = _plan()
    handler = RecordingAuthority()
    await _persist(plan)

    # A lease acquired at NOW with zero seconds is expired at the first apply
    # boundary (the clock is pinned to NOW when ``now`` is supplied).
    outcome = await _run(plan, registry=_admitted_registry(handler), lease_seconds=0)

    assert outcome.reached_status == "blocked"
    assert outcome.ok is False
    assert not handler.calls, "an expired lease must gate every apply"

    actions = await get_action_required_repository().list(tenant_ref=TENANT)
    expired = [a for a in actions if a["action_type"] == "lease_expired"]
    assert len(expired) == 1
    assert expired[0]["required_actor"] == "operator"
    assert expired[0]["required_action"] == ("re-acquire lease and reconcile before re-running")

    row = await get_change_set_repository().get(TENANT, ENV, plan.changeset_id)
    assert row is not None and row["status"] == "blocked"
