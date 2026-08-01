"""The Kyber Mission service — a thin root over the planes that do the work.

This service persists almost nothing of its own. It records the mission root,
enforces one decision the platform must not get wrong (the completion gate), and
composes a read-time view from the planes that already own the real state — the
agent runtime, the jobs platform, the verification decision and the monitoring
conditions. There is no second runtime here and no dual-write: a
:class:`~services.kyber.ops.mission_contracts.MissionView` is assembled on read
and thrown away.

Three commitments, each a refusal rather than a convention:

**Completion is structural, not asserted.** :meth:`MissionService.transition`
carries an explicit ``ALLOWED_FROM`` map, and ``completed`` is reachable only
from ``verifying``/``committing``/``monitoring`` *and* only when the verification
gate is satisfied. An attempt to complete an unverified mission does not fail
loudly and leave the mission where it was — it comes to rest in ``verifying`` (or
``awaiting_review`` when the latest decision is ``needs_review``), which is the
honest state for work that ran but was not confirmed.
:meth:`assert_verified_before_complete` is the raising primitive for callers who
want the hard block.

**Every read is workforce-scoped.** :meth:`reconstruct` refuses without a tenant
access scope and refuses a scope granted for a different tenant, mirroring
:func:`services.kyber.ops.routes._assert_tenants_within_scope`. This is an
operator plane; it never authorizes against tenant auth.

**Composition degrades, it does not fail.** Each plane is read through its own
seam inside a guard, so a plane that has not landed contributes an empty section
rather than an ``ImportError`` — the same fail-soft reasoning the verification
plane uses when it answers ``inconclusive``.

Note on reopen: the agent runtime's ``transition_objective`` supports only
pause/resume/cancel — there is no ``reopen``. A completed mission whose
monitoring later fails is therefore not silently revived; the monitoring sweep
raises an operator signal through ``report_operational_signal`` instead (see
:mod:`services.kyber.ops.monitoring_service`).
"""
from __future__ import annotations

from typing import Any, Optional, Union

from shared.common.common import ConflictError, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger

from .mission_contracts import (
    Mission,
    MissionResult,
    MissionStatus,
    MissionView,
    MonitoringCondition,
    VerificationGate,
    now_iso,
)
from .mission_repository import (
    MissionRepository,
    MonitoringConditionRepository,
    mission_repository,
    monitoring_condition_repository,
)

logger = get_logger("aether.kyber.ops.missions")

_S = MissionStatus

#: Which source statuses may transition **into** each target status. The map is
#: keyed by target so the completion gate is legible in one place: ``completed``
#: is reachable from only three states, and even then the verification gate in
#: :meth:`MissionService.transition` has the final say. A target absent from the
#: map (``detected`` is the initial state, never a transition target) is refused.
ALLOWED_FROM: dict[str, frozenset[str]] = {
    _S.PROPOSED.value: frozenset(
        {_S.DETECTED.value, _S.NOT_IN_RELEASE.value, _S.DISABLED_INTENTIONALLY.value}
    ),
    _S.PLANNING.value: frozenset(
        {_S.DETECTED.value, _S.PROPOSED.value, _S.QUEUED.value}
    ),
    _S.QUEUED.value: frozenset(
        {_S.PROPOSED.value, _S.PLANNING.value, _S.PAUSED.value, _S.ACTIVE.value}
    ),
    _S.ACTIVE.value: frozenset(
        {
            _S.DETECTED.value, _S.PROPOSED.value, _S.PLANNING.value, _S.QUEUED.value,
            _S.WAITING.value, _S.PAUSED.value, _S.BLOCKED.value, _S.VERIFYING.value,
            _S.AWAITING_REVIEW.value, _S.MONITORING.value, _S.QUARANTINED.value,
            _S.EXTERNALLY_BLOCKED.value,
        }
    ),
    _S.WAITING.value: frozenset({_S.ACTIVE.value, _S.QUEUED.value}),
    _S.PAUSED.value: frozenset(
        {_S.QUEUED.value, _S.ACTIVE.value, _S.WAITING.value, _S.BLOCKED.value}
    ),
    _S.BLOCKED.value: frozenset(
        {
            _S.PLANNING.value, _S.ACTIVE.value, _S.WAITING.value,
            _S.AWAITING_REVIEW.value, _S.MONITORING.value, _S.EXTERNALLY_BLOCKED.value,
        }
    ),
    _S.VERIFYING.value: frozenset(
        {
            _S.ACTIVE.value, _S.WAITING.value, _S.AWAITING_REVIEW.value,
            _S.COMMITTING.value, _S.MONITORING.value, _S.BLOCKED.value,
        }
    ),
    _S.AWAITING_REVIEW.value: frozenset(
        {
            _S.ACTIVE.value, _S.VERIFYING.value, _S.COMMITTING.value,
            _S.BLOCKED.value, _S.WAITING.value,
        }
    ),
    _S.COMMITTING.value: frozenset(
        {
            _S.ACTIVE.value, _S.VERIFYING.value, _S.AWAITING_REVIEW.value,
            _S.MONITORING.value,
        }
    ),
    _S.MONITORING.value: frozenset(
        {_S.ACTIVE.value, _S.VERIFYING.value, _S.COMMITTING.value}
    ),
    # Structural completion gate: only these three states may reach completed,
    # and only when the verification gate is satisfied.
    _S.COMPLETED.value: frozenset(
        {_S.VERIFYING.value, _S.COMMITTING.value, _S.MONITORING.value}
    ),
    _S.FAILED.value: frozenset(
        {
            _S.ACTIVE.value, _S.WAITING.value, _S.BLOCKED.value, _S.VERIFYING.value,
            _S.AWAITING_REVIEW.value, _S.COMMITTING.value, _S.MONITORING.value,
            _S.QUARANTINED.value, _S.EXTERNALLY_BLOCKED.value,
        }
    ),
    _S.QUARANTINED.value: frozenset(
        {
            _S.VERIFYING.value, _S.AWAITING_REVIEW.value, _S.COMMITTING.value,
            _S.ACTIVE.value,
        }
    ),
    _S.CANCELLED.value: frozenset(
        {
            _S.DETECTED.value, _S.PROPOSED.value, _S.PLANNING.value, _S.QUEUED.value,
            _S.ACTIVE.value, _S.WAITING.value, _S.PAUSED.value, _S.BLOCKED.value,
            _S.EXTERNALLY_BLOCKED.value, _S.NOT_IN_RELEASE.value,
            _S.DISABLED_INTENTIONALLY.value, _S.QUARANTINED.value,
        }
    ),
    _S.EXTERNALLY_BLOCKED.value: frozenset(
        {_S.QUEUED.value, _S.ACTIVE.value, _S.WAITING.value, _S.BLOCKED.value}
    ),
    _S.NOT_IN_RELEASE.value: frozenset({_S.DETECTED.value, _S.PROPOSED.value}),
    _S.DISABLED_INTENTIONALLY.value: frozenset(
        {_S.DETECTED.value, _S.PROPOSED.value, _S.NOT_IN_RELEASE.value}
    ),
}


def _as_status(value: Union[str, MissionStatus]) -> str:
    """Normalize an action/target to a validated status string."""
    raw = value.value if isinstance(value, MissionStatus) else str(value)
    try:
        return MissionStatus(raw).value
    except ValueError as exc:  # noqa: TRY003 - message is the useful part
        raise ConflictError(f"unknown mission status {raw!r}") from exc


class MissionService:
    """Persist the mission root, gate completion, and compose the read view."""

    def __init__(
        self,
        missions: Optional[MissionRepository] = None,
        conditions: Optional[MonitoringConditionRepository] = None,
    ) -> None:
        self._missions = missions or mission_repository
        self._conditions = conditions or monitoring_condition_repository

    # ── Load ─────────────────────────────────────────────────────────────────

    async def require(self, mission_id: str) -> Mission:
        """Load a mission, raising :class:`NotFoundError` when absent."""
        row = await self._missions.get(mission_id)
        if row is None:
            raise NotFoundError(f"kyber mission {mission_id}")
        return Mission(**row)

    # ── Open ─────────────────────────────────────────────────────────────────

    async def open_mission_from_objective(
        self,
        objective_id: str,
        tenant_id: str,
        title: str,
        *,
        incident_id: Optional[str] = None,
        plan_id: str = "",
        command_ids: Optional[list[str]] = None,
        verification_required: bool = True,
        status: MissionStatus = MissionStatus.DETECTED,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Mission:
        """Open (or return) the single mission bound to an objective.

        Idempotent by construction: the migration declares one mission per
        objective, so a second open returns the mission that already exists
        rather than forking a second run against the same objective — the same
        answer the unique index would force, made explicit so a retry never
        surfaces a constraint violation to an operator.
        """
        existing = await self._missions.find_by_objective(objective_id)
        if existing is not None:
            return Mission(**existing)

        mission = Mission(
            tenant_id=tenant_id,
            title=title,
            status=status,
            objective_id=objective_id,
            incident_id=incident_id,
            command_ids=list(command_ids or []),
            plan_id=plan_id,
            verification_gate=VerificationGate(required=verification_required),
            metadata=metadata or {},
        )
        await self._missions.save_or_update(mission.model_dump(mode="json"))
        logger.info(
            "kyber mission opened id=%s objective=%s tenant=%s",
            mission.mission_id, objective_id, tenant_id,
        )
        return mission

    # ── Completion gate ──────────────────────────────────────────────────────

    def assert_verified_before_complete(self, mission: Union[Mission, dict[str, Any]]) -> None:
        """Raise unless the mission's verification gate permits completion.

        The raising counterpart to the structural guard in :meth:`transition`.
        A mission may complete only when its gate is not required or its latest
        verification decision is ``passed``; anything else — including a missing
        decision — is refused, because ``executed but not verified`` is a real
        state and completing out of it would erase the distinction.
        """
        model = mission if isinstance(mission, Mission) else Mission(**mission)
        gate = model.verification_gate
        if not gate.is_satisfied:
            raise ForbiddenError(
                f"mission {model.mission_id} cannot complete: verification gate is "
                f"required and the latest decision is {gate.decision or 'unset'!r}",
                details={
                    "denial_reason": "verification_gate_unsatisfied",
                    "verification_required": gate.required,
                    "verification_decision": gate.decision,
                },
            )

    async def transition(
        self, mission_id: str, action: Union[str, MissionStatus]
    ) -> Mission:
        """Move a mission to ``action``, or refuse the move.

        ``action`` is the target status. A move whose source is not in
        ``ALLOWED_FROM[target]`` raises :class:`ConflictError`. The completion
        gate is enforced structurally: a request to enter ``completed`` while
        the verification gate is unsatisfied does not complete the mission — it
        comes to rest in ``verifying`` (or ``awaiting_review`` when the latest
        decision is ``needs_review``), the honest state for confirmed-executed,
        not-yet-verified work. Re-entering the current status is an idempotent
        no-op.
        """
        mission = await self.require(mission_id)
        current = mission.status.value
        target = _as_status(action)

        if target == current:
            return mission

        allowed = ALLOWED_FROM.get(target, frozenset())
        if current not in allowed:
            raise ConflictError(
                f"cannot transition mission {mission_id} from {current!r} to {target!r}"
            )

        if target == MissionStatus.COMPLETED.value and not mission.verification_gate.is_satisfied:
            # Structurally forbidden: rest in the verification state instead of
            # completing. This is not a silent success — the mission's status
            # after the call is verifying/awaiting_review, never completed.
            rest = (
                MissionStatus.AWAITING_REVIEW
                if mission.verification_gate.decision == "needs_review"
                else MissionStatus.VERIFYING
            )
            new_status = rest
            logger.info(
                "kyber mission completion blocked id=%s decision=%s -> resting in %s",
                mission_id, mission.verification_gate.decision, rest.value,
            )
        else:
            new_status = MissionStatus(target)

        mission.status = new_status
        mission.updated_at = now_iso()
        await self._missions.save_or_update(mission.model_dump(mode="json"))
        logger.info(
            "kyber mission transition id=%s (%s -> %s)",
            mission_id, current, mission.status.value,
        )
        return mission

    # ── Read-time composition ────────────────────────────────────────────────

    async def reconstruct(
        self, mission_id: str, *, scope_tenant: Optional[str] = None
    ) -> MissionView:
        """Compose the full mission view, enforcing the operator's tenant scope.

        ``scope_tenant`` is the tenant the caller's durable access scope was
        granted for — ``context.scope.tenant_id`` at the route. It is required
        (a workforce session with no scope is denied) and must equal the
        mission's tenant (a scope for another tenant is denied). The comparison
        is against the granted scope, never a client-asserted tenant, for the
        same reason it is in the scoped graph gateway.
        """
        mission = await self.require(mission_id)
        self._enforce_scope(mission, scope_tenant)
        return await self._compose_view(mission)

    def _enforce_scope(self, mission: Mission, scope_tenant: Optional[str]) -> None:
        if not scope_tenant:
            raise ForbiddenError(
                "reading a mission requires a tenant access scope",
                details={"denial_reason": "scope_missing"},
            )
        if scope_tenant != mission.tenant_id:
            raise ForbiddenError(
                "the active access scope was not granted for this mission's tenant",
                details={"denial_reason": "scope_tenant_mismatch"},
            )

    async def _compose_view(self, mission: Mission) -> MissionView:
        """Assemble the view from every plane, each read behind its own guard."""
        tenant = mission.tenant_id
        objective_id = mission.objective_id

        objective, plan, steps, worker_runs, events, approvals = await self._read_runtime(
            tenant, objective_id
        )
        jobs = await self._read_jobs(tenant, mission.command_ids)
        conditions = [
            MonitoringCondition(**row)
            for row in await self._conditions.list_for_mission(mission.mission_id)
        ]

        evidence: list[Any] = list(mission.result.evidence_ids) if mission.result else []
        verification = {
            "required": mission.verification_gate.required,
            "decision": mission.verification_gate.decision,
            "is_satisfied": mission.verification_gate.is_satisfied,
            "verification_id": mission.result.verification_id if mission.result else None,
        }

        return MissionView(
            mission=mission,
            objective=objective,
            plan=plan,
            steps=steps,
            jobs=jobs,
            worker_runs=worker_runs,
            tool_calls=events,
            evidence=evidence,
            verification=verification,
            approvals=approvals,
            monitoring_conditions=conditions,
            timeline=self._build_timeline(events, conditions),
        )

    async def timeline(self, mission_id: str, *, scope_tenant: Optional[str] = None) -> list[dict[str, Any]]:
        """The mission's merged, time-ordered timeline (scope-enforced)."""
        view = await self.reconstruct(mission_id, scope_tenant=scope_tenant)
        return view.timeline

    async def _read_runtime(
        self, tenant: str, objective_id: str
    ) -> tuple[
        Optional[dict[str, Any]],
        Optional[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """Read the agent-runtime slices for one objective, degrading to empty.

        The runtime is reached through its own accessor rather than imported at
        module scope, so a runtime that is unavailable yields an empty
        composition instead of failing the whole view.
        """
        objective: Optional[dict[str, Any]] = None
        plan: Optional[dict[str, Any]] = None
        steps: list[dict[str, Any]] = []
        worker_runs: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        approvals: list[dict[str, Any]] = []
        if not objective_id:
            return objective, plan, steps, worker_runs, events, approvals
        try:
            from services.agent.runtime_repository import get_agent_runtime_repository

            repo = get_agent_runtime_repository()
            objective = await repo.get_objective(tenant, objective_id)
            plans = await repo.plans.find(tenant_id=tenant, objective_id=objective_id)
            plan = plans[0] if plans else None
            steps = await repo.steps.find(tenant_id=tenant, objective_id=objective_id)
            if not steps and plan:
                steps = list(plan.get("steps") or [])
            worker_runs = await repo.list_runs(tenant, objective_id=objective_id)
            events = await repo.events_for_tenant(tenant, objective_id=objective_id)
            approvals = await repo.review_batches_for_objective(tenant, objective_id)
        except Exception as exc:  # noqa: BLE001 - a missing plane degrades, never fails
            logger.warning(
                "kyber mission: agent-runtime composition unavailable "
                "(objective=%s tenant=%s error=%s)",
                objective_id, tenant, exc,
            )
        return objective, plan, steps, worker_runs, events, approvals

    async def _read_jobs(
        self, tenant: str, command_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Jobs this mission's commands correlate to, degrading to empty.

        A command carries its idempotency key onto the job it enqueues as the
        job's ``correlation_id``; a mission records that key in ``command_ids``.
        Reading by correlation keeps the composition to the jobs the mission
        actually raised rather than every job in the tenant.
        """
        if not command_ids:
            return []
        keys = set(command_ids)
        try:
            from repositories.jobs_repo import get_jobs_repository

            rows = await get_jobs_repository().list_jobs(tenant, limit=500)
        except Exception as exc:  # noqa: BLE001 - a missing plane degrades
            logger.warning("kyber mission: jobs composition unavailable (error=%s)", exc)
            return []
        return [row for row in rows if str(row.get("correlation_id") or "") in keys]

    @staticmethod
    def _build_timeline(
        events: list[dict[str, Any]], conditions: list[MonitoringCondition]
    ) -> list[dict[str, Any]]:
        """Merge agent events and monitoring checks into one ordered stream."""
        entries: list[dict[str, Any]] = []
        for event in events:
            entries.append(
                {
                    "at": event.get("created_at") or "",
                    "source": event.get("source") or "agent",
                    "type": event.get("event_type") or "event",
                    "ref": event.get("event_id") or "",
                }
            )
        for condition in conditions:
            if condition.last_checked_at:
                entries.append(
                    {
                        "at": condition.last_checked_at,
                        "source": "kyber.mission.monitor",
                        "type": f"condition.{condition.status}",
                        "ref": condition.condition_id,
                    }
                )
        entries.sort(key=lambda entry: str(entry.get("at") or ""))
        return entries


#: Process-wide singleton. Routes and the monitoring loop read through it so the
#: in-memory backend behaves like a database across the plane.
mission_service = MissionService()

__all__ = [
    "ALLOWED_FROM",
    "MissionService",
    "mission_service",
]
