"""Reconciled Control Plane — §34 ChangeSet execution engine (Phase 2).

The executor is the atomic, governed consumer of a ChangeSet *plan* (blueprint
§32 steps 12–23). A caller drives one persisted plan through the §34 state
machine: guard validation first (§35 — never apply a stale ChangeSet), lease
acquisition, §21 approval/§39 token gating, actuator apply through the §36
typed actuators (preflight → apply → verify → rollback), and evidence
persistence at every step:

* every §34 transition is persisted (``change_set_events``, append-only) and
  validated against the Phase-2 transition table before it is written —
  illegal transitions fail closed and raise;
* every executed/attempted change is recorded as §12.13 evidence with a §12.15
  epistemic ``claim_type`` — evidence is append-only and never retro-written;
* verification (§32 step 19 / §12.9 technical + semantic health) runs before
  any commit; an LKG row is established only after verification passes
  (§32 step 21 / §12.12); a failed dimension triggers the §32 step-20
  automated rollback (§12.11 rollback records, reverse-order §36 rollback);
* anything the current authority cannot resolve (no admitted actuator
  authority, a failed preflight, an expired lease, a rollback that also fails,
  a Phase-4 rollout deferral) is surfaced as §12.14 ActionRequired — never
  fabricated as applied.

Phase-2 boundary — reachable set and reservations: the reachable §34 status
set is ``draft | planned | preparing | validating | waiting_approval | ready |
verifying | rolling_back | committed | rolled_back | blocked | cancelled |
superseded | failed``. ``simulating``, ``canary`` and ``rolling_out`` are
declared by §34 but **reserved** for Phases 3/4 and are unreachable here
(no transition in ``S34_TRANSITIONS`` leads to them). Rollout-percentage
gating is Phase 4: an R2 plan whose tokens are satisfied is *deferred* to
``blocked`` with a ``rollout_engine_required`` ActionRequired, never applied
directly. Simulation/canary gates declared for R1/R2 by the §39 engine are
Phase-3/4 mechanisms; in Phase 2 they are satisfiable only through an explicit
§21 approval grant (a caller recorded an approval row), so the token machinery
is exercised end-to-end without fabricating a simulation/canary engine.

Phase-2 boundary — no autonomous trigger: nothing in this module schedules,
subscribes or auto-runs. The executor runs only when a caller drives a plan
through the governed path (``run_changeset`` with an explicit caller context);
all Reconciled Control Plane flags default OFF and nothing here reads them.

Sections cited: §32 steps 12–23 (candidate plan → ActionRequired), §34
(ChangeSet state machine), §35 (stale-plan guards), §36 (actuators), §21
(role-gated approvals), §12.9 (verify health), §12.11 (rollback records),
§12.12 (last-known-good), §12.13 (evidence), §12.14 (ActionRequired),
§12.15 (epistemic claim kinds).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Protocol

from services.managed_integrations.actuators import (
    Actuator,
    get_actuator_registry,
)
from services.managed_integrations.change_planning import (
    GuardVerdict,
    validate_guards,
)
from services.managed_integrations.change_sets_repository import (
    get_change_set_repository,
)
from services.managed_integrations.contracts import (
    ActionRequiredView,
    ChangeEvidenceView,
    ChangeSetPlanView,
    ChangeSpec,
    LastKnownGoodView,
    RollbackRecordView,
    VerifyReport,
)
from services.managed_integrations.execution_records_repository import (
    get_action_required_repository,
    get_change_evidence_repository,
    get_change_set_approval_repository,
    get_change_set_event_repository,
    get_change_set_rollback_repository,
    get_last_known_good_repository,
)

# ── §34 Phase-2 transition legality ──────────────────────────────────────────

# Phase-2 reachable transition table. simulating/canary/rolling_out are
# deliberately absent (no outgoing, and no Phase-2 status leads to them):
# they are reserved for Phases 3/4 and must never be traversed by this engine.
S34_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"planned", "superseded", "cancelled"}),
    "planned": frozenset({"preparing", "waiting_approval", "superseded", "cancelled"}),
    "waiting_approval": frozenset({"preparing", "superseded", "cancelled"}),
    "preparing": frozenset({"validating", "blocked", "superseded", "cancelled"}),
    "validating": frozenset({"ready", "blocked", "superseded", "cancelled"}),
    "ready": frozenset({"verifying", "blocked", "superseded", "cancelled"}),
    "verifying": frozenset({"committed", "rolling_back"}),
    "rolling_back": frozenset({"rolled_back", "failed"}),
    "blocked": frozenset({"cancelled"}),
    "committed": frozenset(),
    "rolled_back": frozenset(),
    "cancelled": frozenset(),
    "superseded": frozenset(),
    "failed": frozenset(),
}

# Statuses the engine may short-circuit on entry (nothing left to do).
_TERMINAL_STATUSES = frozenset({"committed", "rolled_back", "cancelled", "failed", "superseded"})


def legal_transitions(status: str) -> frozenset[str]:
    """The §34 statuses reachable from ``status`` in Phase 2.

    Reserved (simulating/canary/rolling_out) and unknown statuses have no
    outgoing transitions — nothing may move toward a reserved status.
    """
    return S34_TRANSITIONS.get(status, frozenset())


def validate_transition(from_status: str, to_status: str) -> None:
    """Raise ``ValueError`` when ``from_status -> to_status`` is not a legal
    §34 Phase-2 transition (illegal transitions fail closed)."""
    if to_status not in legal_transitions(from_status):
        raise ValueError(
            f"illegal §34 transition {from_status} -> {to_status} "
            "(fail closed; simulating/canary/rolling_out are Phase-3/4 "
            "reserved statuses)"
        )


# ── §39 token gating + Phase-2 mechanism availability ─────────────────────────

# Phase-2 satisfiable mechanism gates: NONE. Simulation is Phase 3 and canary/
# rollout delivery is Phase 4, so the only way an R1/R2 plan may satisfy its
# declared gates in Phase 2 is an explicit §21 approval grant recorded against
# the gate token (see module docstring). R3/R4/R5/security_emergency carry no
# mechanism gate — their approvals travel in ``risk.required_approval_refs``.
PHASE2_GATES_BY_RISK_CLASS: dict[str, frozenset[str]] = {
    "R0": frozenset(),
    "R1": frozenset({"gate:simulation"}),
    "R2": frozenset({"gate:canary", "gate:health"}),
    "R3": frozenset(),
    "R4": frozenset(),
    "R5": frozenset(),
    "security_emergency": frozenset(),
}


def required_tokens(plan: ChangeSetPlanView) -> list[str]:
    """Every token a plan must carry to execute: §21 approval refs plus the
    Phase-2 mechanism gates declared for its §39 risk class (stable order,
    deduplicated)."""
    gates = sorted(PHASE2_GATES_BY_RISK_CLASS.get(plan.risk.risk_class, frozenset()))
    tokens: list[str] = []
    for token in [*plan.risk.required_approval_refs, *gates]:
        if token not in tokens:
            tokens.append(token)
    return tokens


def missing_tokens(plan: ChangeSetPlanView, granted: list[str]) -> list[str]:
    """Tokens with no matching granted approval/authority record."""
    return [t for t in required_tokens(plan) if t not in granted]


def rollout_required(risk_class: str) -> bool:
    """True only for R2 — canary execution infrastructure is Phase 4, so an
    R2 plan can never be applied directly by this engine."""
    return risk_class == "R2"


# ── lease ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Lease:
    """One executor run's lease: the run is valid while ``now <= expires_at``."""

    owner: str
    expires_at: datetime


def acquire_lease(*, owner: str, now: datetime, lease_seconds: int = 300) -> Lease:
    """Acquire a run lease expiring ``lease_seconds`` after ``now``."""
    return Lease(owner=owner, expires_at=now + timedelta(seconds=lease_seconds))


def lease_valid(lease: Lease, now: datetime) -> bool:
    """A lease is valid at ``now`` only strictly before it expires.

    Strict comparison keeps a zero-second lease (``expires_at == now``)
    immediately expired at its acquisition instant — the deterministic hook
    the lease-expiry tests rely on.
    """
    return now < lease.expires_at


# ── caller-supplied target + outcome views ───────────────────────────────────


@dataclass(frozen=True)
class TargetSnapshot:
    """The integration state a ChangeSet acts on (supplied by the caller).

    Refs point at durable states owned by the driving layer; the executor
    records them as evidence but never resolves them. ``last_known_good_ref``
    is the pre-change LKG the rollback record restores toward;
    ``replay_after_recovery`` declares the rollback replay policy.
    """

    managed_integration_ref: str
    desired_state_ref: Optional[str] = None
    artifact_ref: Optional[str] = None
    runtime_config_ref: Optional[str] = None
    schema_ref: Optional[str] = None
    integration_contract_ref: Optional[str] = None
    policy_ref: Optional[str] = None
    provider_state_ref: Optional[str] = None
    verified_health_ref: Optional[str] = None
    last_known_good_ref: Optional[str] = None
    replay_after_recovery: bool = False


@dataclass
class RunOutcome:
    """One ``run_changeset`` execution's result.

    ``ok`` is True only when the run reached a terminal resolution
    (``committed`` or ``rolled_back``); ``reached_status`` names the §34
    status the plan row ended in; every persisted artifact (events, evidence,
    LKG, rollback record, ActionRequired rows) is collected for the caller.
    """

    changeset_id: str
    reached_status: str
    ok: bool
    superseded: bool = False
    events: list[dict] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    verify_report: Optional[VerifyReport] = None
    lkg_id: Optional[str] = None
    rollback_id: Optional[str] = None
    action_required_ids: list[str] = field(default_factory=list)
    missing_tokens: list[str] = field(default_factory=list)
    reason: Optional[str] = None


class _ActuatorRegistryLike(Protocol):
    """The registry surface the executor needs: ``get(kind)`` per §36."""

    def get(self, kind: str) -> Optional[Actuator]: ...


def _default_clock(now: Optional[datetime]) -> Callable[[], datetime]:
    """Deterministic clock: frozen at ``now`` when the caller pinned one,
    wall-clock otherwise (tests inject ``now_provider`` for lease expiry)."""
    if now is not None:
        return lambda: now
    return lambda: datetime.now(timezone.utc)


def _state_refs(*parts: Optional[str]) -> list[str]:
    """Ordered, de-duplicated state refs for evidence ``before_state_refs``."""
    refs: list[str] = []
    for part in parts:
        if part and part not in refs:
            refs.append(part)
    return refs


def _present_target_state_refs(target: TargetSnapshot) -> list[str]:
    """The durable state refs the caller's snapshot actually carries."""
    return _state_refs(
        target.desired_state_ref,
        target.artifact_ref,
        target.runtime_config_ref,
        target.schema_ref,
        target.integration_contract_ref,
        target.policy_ref,
        target.provider_state_ref,
        target.verified_health_ref,
    )


# ── §34 executor ─────────────────────────────────────────────────────────────


async def run_changeset(
    plan: ChangeSetPlanView,
    *,
    target: TargetSnapshot,
    current_desired_revision: str,
    current_observed_revision: str,
    actor: str = "operator",
    now: Optional[datetime] = None,
    registry: Optional[_ActuatorRegistryLike] = None,
    lease_seconds: int = 300,
    now_provider: Optional[Callable[[], datetime]] = None,
) -> RunOutcome:
    """Execute one persisted ChangeSet plan through the governed §34 path.

    The caller must persist the plan row first (``ChangeSetRepository.create``)
    and pass the *current* §35 guard revisions; the engine reads the row's
    status from the repository and never executes a plan it cannot find
    (``ValueError``). ``registry`` defaults to the §36 singleton actuator
    registry; ``now_provider`` (default wall clock, frozen at ``now`` when a
    caller pins one) drives lease-expiry checks so tests can advance time
    deterministically.
    """
    cs_repo = get_change_set_repository()
    row = await cs_repo.get(plan.tenant_id, plan.environment_id, plan.changeset_id)
    if row is None:
        raise ValueError("change set not persisted — create before execute")
    status = str(row["status"])

    clock = now_provider if now_provider is not None else _default_clock(now)
    instant = now if now is not None else clock()
    registry = registry if registry is not None else get_actuator_registry()

    events: list[dict] = []
    evidence_ids: list[str] = []
    action_ids: list[str] = []

    # ── 1. already terminal? nothing to do (§34) ────────────────────────────
    if status in _TERMINAL_STATUSES:
        return RunOutcome(
            changeset_id=plan.changeset_id,
            reached_status=status,
            ok=status in {"committed", "rolled_back"},
            reason="already terminal",
        )

    # ── 2. §35 stale-plan guard FIRST — never apply a stale ChangeSet ───────
    verdict: GuardVerdict = validate_guards(
        plan,
        current_desired_revision=current_desired_revision,
        current_observed_revision=current_observed_revision,
    )
    if not verdict.ok:
        validate_transition(status, "superseded")
        await cs_repo.update_status(
            tenant_id=plan.tenant_id,
            environment_id=plan.environment_id,
            changeset_id=plan.changeset_id,
            status="superseded",
            superseded_at=instant,
        )
        events.append(
            await _append_event(
                plan=plan,
                from_status=status,
                to_status="superseded",
                actor=actor,
                at=instant,
                reason=verdict.reason,
            )
        )
        return RunOutcome(
            changeset_id=plan.changeset_id,
            reached_status="superseded",
            superseded=True,
            ok=False,
            events=events,
            reason=verdict.reason,
        )

    event_repo = get_change_set_event_repository()

    async def _move(to_status: str, *, reason: Optional[str] = None) -> None:
        """Persist one legal §34 move + append its event (fail closed)."""
        nonlocal status
        validate_transition(status, to_status)
        await cs_repo.update_status(
            tenant_id=plan.tenant_id,
            environment_id=plan.environment_id,
            changeset_id=plan.changeset_id,
            status=to_status,
            at=instant,
        )
        events.append(
            await _append_event(
                plan=plan,
                from_status=status,
                to_status=to_status,
                actor=actor,
                at=instant,
                reason=reason or f"§34 {status}->{to_status}",
            )
        )
        status = to_status

    async def _action_required(
        *,
        action_type: str,
        required_actor: str,
        required_action: str,
        reason: str,
        impact: Optional[str] = None,
        continuity_state: Optional[str] = None,
        data_loss_expected: bool = False,
    ) -> str:
        """Surface one open §12.14 ActionRequired row for this ChangeSet."""
        row = await get_action_required_repository().create(
            ActionRequiredView(
                action_id=f"ar_{uuid.uuid4().hex[:16]}",
                tenant_ref=plan.tenant_id,
                managed_integration_ref=target.managed_integration_ref,
                environment_id=plan.environment_id,
                action_type=action_type,
                reason=reason,
                impact=impact,
                deadline=None,
                required_actor=required_actor,
                required_action=required_action,
                continuity_state=continuity_state,
                data_loss_expected=data_loss_expected,
                resolution_ref=None,
                status="open",
                created_at=instant,
            )
        )
        action_id = str(row["action_id"])
        action_ids.append(action_id)
        return action_id

    async def _block(
        *,
        action_type: str,
        required_actor: str,
        required_action: str,
        reason: str,
        impact: Optional[str] = None,
        continuity_state: Optional[str] = None,
        data_loss_expected: bool = False,
    ) -> str:
        """Move to ``blocked`` (legal only from execution statuses) and
        surface an open ActionRequired row."""
        await _move("blocked", reason=reason)
        return await _action_required(
            action_type=action_type,
            required_actor=required_actor,
            required_action=required_action,
            reason=reason,
            impact=impact,
            continuity_state=continuity_state,
            data_loss_expected=data_loss_expected,
        )

    async def _record_evidence(
        *,
        claim_type: str,
        confidence: str,
        before_state_refs: Optional[list[str]] = None,
        after_state_refs: Optional[list[str]] = None,
        validation_refs: Optional[list[str]] = None,
        contradictory_evidence_refs: Optional[list[str]] = None,
        rollback_ref: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> str:
        """Append one §12.13 evidence row (append-only — never updated)."""
        row = await get_change_evidence_repository().create(
            ChangeEvidenceView(
                change_evidence_id=f"cve_{uuid.uuid4().hex[:16]}",
                changeset_ref=plan.changeset_id,
                tenant_id=plan.tenant_id,
                environment_id=plan.environment_id,
                initiator=actor,
                policy_ref=plan.policy_ref,
                before_state_refs=before_state_refs or [],
                after_state_refs=after_state_refs or [],
                reason=reason,
                claim_type=claim_type,
                confidence=confidence,
                risk_ref=plan.risk.risk_class,
                validation_refs=validation_refs or [],
                rollback_ref=rollback_ref,
                contradictory_evidence_refs=contradictory_evidence_refs or [],
                started_at=instant,
                completed_at=instant,
            )
        )
        evidence_id = str(row["change_evidence_id"])
        evidence_ids.append(evidence_id)
        return evidence_id

    # ── 3. §21 approval / §39 token gate ────────────────────────────────────
    approvals = await get_change_set_approval_repository().list_for_changeset(
        tenant_id=plan.tenant_id,
        environment_id=plan.environment_id,
        changeset_ref=plan.changeset_id,
        decision="approved",
    )
    granted = [str(a.get("required_approval_ref")) for a in approvals]
    missing = missing_tokens(plan, granted)
    if missing:
        from_status = status
        if status != "waiting_approval":
            validate_transition(status, "waiting_approval")
            await cs_repo.update_status(
                tenant_id=plan.tenant_id,
                environment_id=plan.environment_id,
                changeset_id=plan.changeset_id,
                status="waiting_approval",
                at=instant,
            )
            status = "waiting_approval"
        reason = f"awaiting approval tokens: {missing}"
        events.append(
            await _append_event(
                plan=plan,
                from_status=from_status,
                to_status="waiting_approval",
                actor=actor,
                at=instant,
                reason=reason,
            )
        )
        return RunOutcome(
            changeset_id=plan.changeset_id,
            reached_status="waiting_approval",
            ok=False,
            events=events,
            missing_tokens=missing,
            reason=reason,
        )

    # ── 4. drive path: enter execution, then boundary gates ─────────────────
    # ``blocked`` is only reachable from execution statuses (preparing/
    # validating/ready) in §34, so the apply-path gates that may terminate in
    # ``blocked`` (lease expiry, Phase-4 rollout deferral) run after the
    # legal entry move into ``preparing``.
    await _move("preparing")
    lease = acquire_lease(owner=f"run:{actor}", now=instant, lease_seconds=lease_seconds)

    if not lease_valid(lease, clock()):
        reason = "execution lease expired before the apply path began"
        await _block(
            action_type="lease_expired",
            required_actor=actor,
            required_action="re-acquire lease and reconcile before re-running",
            reason=reason,
        )
        return RunOutcome(
            changeset_id=plan.changeset_id,
            reached_status="blocked",
            ok=False,
            events=events,
            action_required_ids=action_ids,
            reason=reason,
        )

    if rollout_required(str(plan.risk.risk_class)):
        reason = (
            "R2 change deferred: progressive-delivery rollout is a Phase-4 "
            "mechanism and cannot run through this Phase-2 executor"
        )
        await _block(
            action_type="rollout_engine_required",
            required_actor="olympus_operator",
            required_action=(
                "run through the Phase-4 progressive-delivery rollout engine "
                "(canary + health gates)"
            ),
            reason=reason,
            continuity_state="unchanged",
        )
        return RunOutcome(
            changeset_id=plan.changeset_id,
            reached_status="blocked",
            ok=False,
            events=events,
            action_required_ids=action_ids,
            reason=reason,
        )

    # ── 5. apply phase: preflight → attempted/applied evidence per change ───
    applied: list[tuple[ChangeSpec, Actuator, str]] = []
    after_refs: list[str] = []
    target_before_refs = _present_target_state_refs(target)

    for change in plan.changes:
        if not lease_valid(lease, clock()):
            reason = "execution lease expired at an apply boundary"
            await _block(
                action_type="lease_expired",
                required_actor=actor,
                required_action="re-acquire lease and reconcile before re-running",
                reason=reason,
            )
            return RunOutcome(
                changeset_id=plan.changeset_id,
                reached_status="blocked",
                ok=False,
                events=events,
                evidence_ids=evidence_ids,
                action_required_ids=action_ids,
                reason=reason,
            )

        actuator = registry.get(change.action)
        if actuator is None:
            reason = f"no actuator registered for §36 action {change.action}"
            await _block(
                action_type="unknown_actuator",
                required_actor="olympus_operator",
                required_action=f"register a §36 actuator for {change.action}",
                reason=reason,
            )
            return RunOutcome(
                changeset_id=plan.changeset_id,
                reached_status="blocked",
                ok=False,
                events=events,
                evidence_ids=evidence_ids,
                action_required_ids=action_ids,
                reason=reason,
            )

        preflight = actuator.preflight(change)
        if not preflight.ok:
            # Attempted-change evidence: nothing was applied, so the row
            # records only the before state (§32.22 executed/attempted).
            await _record_evidence(
                claim_type="observed",
                confidence="medium",
                before_state_refs=target_before_refs,
                reason=change.reason,
            )
            issues = "; ".join(preflight.issues)
            reason = f"preflight failed: {issues}"
            await _block(
                action_type="preflight_failed",
                required_actor="olympus_operator",
                required_action=(
                    f"resolve preflight issues for {change.action} on "
                    f"{change.target_ref} then re-run"
                ),
                reason=reason,
                impact=issues,
            )
            return RunOutcome(
                changeset_id=plan.changeset_id,
                reached_status="blocked",
                ok=False,
                events=events,
                evidence_ids=evidence_ids,
                action_required_ids=action_ids,
                reason=reason,
            )

        result = await actuator.apply(change)
        if result.outcome != "applied":
            # Never claim applied: the change did not run, so its evidence row
            # carries before-state refs only and the change is surfaced.
            await _record_evidence(
                claim_type="observed",
                confidence="medium",
                before_state_refs=target_before_refs,
                reason=change.reason,
            )
            reason = (
                result.detail
                or f"apply of {change.action} on {change.target_ref} returned not_applied"
            )
            await _block(
                action_type="actuator_authority_unavailable",
                required_actor="olympus_operator",
                required_action=(f"admit an authority for {change.action} or resolve manually"),
                reason=reason,
                impact=result.detail,
            )
            return RunOutcome(
                changeset_id=plan.changeset_id,
                reached_status="blocked",
                ok=False,
                events=events,
                evidence_ids=evidence_ids,
                action_required_ids=action_ids,
                reason=reason,
            )

        evidence_id = await _record_evidence(
            claim_type="observed",
            confidence="high",
            before_state_refs=_state_refs(*target_before_refs, result.before_state_ref),
            after_state_refs=_state_refs(result.after_state_ref),
            reason=change.reason,
        )
        applied.append((change, actuator, evidence_id))
        if result.after_state_ref and result.after_state_ref not in after_refs:
            after_refs.append(result.after_state_ref)

    # ── 6. validation + verification (§32 step 19) ──────────────────────────
    await _move("validating")
    await _move("ready")
    await _move("verifying", reason="begin §32 step-19 verification")

    verify_results = [await actuator.verify(change) for change, actuator, _ in applied]
    technical_health = (
        "passed" if not any(r.technical == "failed" for r in verify_results) else "failed"
    )
    semantic_health = (
        "passed" if not any(r.semantic == "failed" for r in verify_results) else "failed"
    )
    report = VerifyReport(
        changeset_id=plan.changeset_id,
        technical_health=technical_health,
        semantic_health=semantic_health,
        validation_refs=list(evidence_ids),
        note=(
            f"§32 step-19 verification of {len(applied)} applied change(s): "
            f"technical={technical_health} semantic={semantic_health}"
        ),
        verified_at=instant,
    )

    if technical_health == "passed" and semantic_health == "passed":
        # Verified-aggregate evidence row — only written when both dimensions
        # pass (a failed verification walks the rollback path instead).
        await _record_evidence(
            claim_type="verified",
            confidence="high",
            before_state_refs=target_before_refs,
            after_state_refs=after_refs,
            validation_refs=list(evidence_ids),
            reason="verification passed — §32 steps 19/21",
        )
        await _move("committed", reason="all §32 step-19 checks passed — committing")
        # LKG ONLY NOW: a rollout is not last-known-good until verification
        # passes (§32 step 21 / §12.12).
        lkg_row = await get_last_known_good_repository().establish(
            LastKnownGoodView(
                lkg_id=f"lkg_{uuid.uuid4().hex[:16]}",
                managed_integration_ref=target.managed_integration_ref,
                tenant_id=plan.tenant_id,
                environment_id=plan.environment_id,
                desired_state_ref=target.desired_state_ref,
                artifact_ref=target.artifact_ref,
                runtime_config_ref=target.runtime_config_ref,
                schema_ref=target.schema_ref,
                mapping_refs=[],
                integration_contract_ref=target.integration_contract_ref,
                policy_ref=target.policy_ref,
                provider_state_ref=target.provider_state_ref,
                verified_health_ref=target.verified_health_ref,
                established_at=instant,
            )
        )
        return RunOutcome(
            changeset_id=plan.changeset_id,
            reached_status="committed",
            ok=True,
            events=events,
            evidence_ids=evidence_ids,
            verify_report=report,
            lkg_id=str(lkg_row["lkg_id"]),
            reason="all §32 step-19 checks passed; committed",
        )

    # ── 7. rollback path (§32 step 20 / §12.11) ─────────────────────────────
    rollback_actions = [
        f"{change.action}:{change.target_ref}" for change, _, _ in reversed(applied)
    ]
    rollback_row = await get_change_set_rollback_repository().create(
        RollbackRecordView(
            rollback_id=f"crb_{uuid.uuid4().hex[:16]}",
            changeset_ref=plan.changeset_id,
            tenant_id=plan.tenant_id,
            environment_id=plan.environment_id,
            last_known_good_ref=target.last_known_good_ref,
            rollback_actions=rollback_actions,
            queue_recovery_policy=(
                "replay_after_recovery" if target.replay_after_recovery else None
            ),
            replay_policy=("replay_after_recovery" if target.replay_after_recovery else "none"),
            validation_requirements=["technical_health", "semantic_health"],
            status="pending",
            created_at=instant,
            completed_at=None,
        )
    )
    rollback_id = str(rollback_row["rollback_id"])
    await _move(
        "rolling_back",
        reason=f"§32 step-20 automated rollback after verification failure: "
        f"technical={technical_health} semantic={semantic_health}",
    )
    await get_change_set_rollback_repository().update_status(
        tenant_id=plan.tenant_id,
        environment_id=plan.environment_id,
        rollback_id=rollback_id,
        status="rolling_back",
    )

    for change, actuator, evidence_id in reversed(applied):
        result = await actuator.rollback(change)
        if result.outcome != "applied":
            await get_change_set_rollback_repository().update_status(
                tenant_id=plan.tenant_id,
                environment_id=plan.environment_id,
                rollback_id=rollback_id,
                status="failed",
            )
            reason = (
                f"automated rollback failed for {change.action}:"
                f"{change.target_ref}: {result.detail or 'not_applied'}"
            )
            await _move("failed", reason=reason)
            # The ChangeSet is already terminal-failed here — surface the
            # manual-rollback need as an ActionRequired row (no blocked move;
            # failed has no outgoing §34 transitions).
            await _action_required(
                action_type="rollback_failed",
                required_actor="olympus_operator",
                required_action=(
                    "manual rollback required — the automated rollback could not complete"
                ),
                reason=reason,
                impact=result.detail,
                continuity_state="degraded",
                data_loss_expected=True,
            )
            await _record_evidence(
                claim_type="observed",
                confidence="low",
                before_state_refs=target_before_refs,
                contradictory_evidence_refs=[evidence_id],
                rollback_ref=rollback_id,
                reason=f"rollback failed — the applied-change claim for "
                f"{change.action}:{change.target_ref} is contradicted",
            )
            return RunOutcome(
                changeset_id=plan.changeset_id,
                reached_status="failed",
                ok=False,
                events=events,
                evidence_ids=evidence_ids,
                verify_report=report,
                rollback_id=rollback_id,
                action_required_ids=action_ids,
                reason=reason,
            )

    await get_change_set_rollback_repository().update_status(
        tenant_id=plan.tenant_id,
        environment_id=plan.environment_id,
        rollback_id=rollback_id,
        status="rolled_back",
        completed_at=instant,
    )
    await _record_evidence(
        claim_type="verified",
        confidence="high",
        validation_refs=list(evidence_ids),
        rollback_ref=rollback_id,
        reason="automated rollback completed — state restored toward LKG",
    )
    await _move("rolled_back", reason="automated rollback complete")
    return RunOutcome(
        changeset_id=plan.changeset_id,
        reached_status="rolled_back",
        ok=True,
        events=events,
        evidence_ids=evidence_ids,
        verify_report=report,
        rollback_id=rollback_id,
        action_required_ids=action_ids,
        reason="automated rollback complete",
    )


async def _append_event(
    *,
    plan: ChangeSetPlanView,
    from_status: str,
    to_status: str,
    actor: str,
    at: datetime,
    reason: Optional[str] = None,
) -> dict:
    """Append one §34 status event (append-only history)."""
    return await get_change_set_event_repository().append(
        event_id=f"rcev_{uuid.uuid4().hex[:16]}",
        changeset_id=plan.changeset_id,
        tenant_id=plan.tenant_id,
        environment_id=plan.environment_id,
        to_status=to_status,
        from_status=from_status,
        actor=actor,
        reason=reason or f"§34 {from_status}->{to_status}",
        occurred_at=at,
    )


__all__ = [
    "S34_TRANSITIONS",
    "PHASE2_GATES_BY_RISK_CLASS",
    "Lease",
    "RunOutcome",
    "TargetSnapshot",
    "acquire_lease",
    "lease_valid",
    "legal_transitions",
    "missing_tokens",
    "required_tokens",
    "rollout_required",
    "run_changeset",
    "validate_transition",
]
