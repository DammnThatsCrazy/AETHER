"""The monitoring sweep — the recurring half of a live mission.

A mission that has done its work is not finished the moment it completes: the
state it produced can regress. Monitoring conditions are the checks a mission
schedules against the world, and this service is the loop that wakes on the ones
that are due, compares what the mission asserted against what is live now, and —
when a divergence persists past its escalation threshold — raises one operator
signal.

The escalation path is deliberately :func:`report_operational_signal`, not a
transition on the underlying objective. The agent runtime's
``transition_objective`` supports only pause/resume/cancel; there is no reopen,
so a completed objective whose monitoring later fails cannot be silently revived.
Raising a signal is the honest alternative: the regression becomes a ranked
exception (and a correlated incident) an operator reads, rather than a mission
that quietly rewrites its own history. The mission root itself is moved to
``monitoring`` to record that it is now under active watch.

Two properties matter and both are structural:

**Idempotent per tick, and across ticks.** Within a sweep each due condition is
processed once. Across sweeps, a condition that escalates leaves the active set
(:data:`~services.kyber.ops.mission_contracts.MONITORING_ACTIVE_STATUSES`), so
:meth:`MonitoringConditionRepository.list_due` never returns it again and the
next tick cannot raise a second signal for the same failure. The dedupe key
(`mission:{mission}:{condition}`) is the belt to that suspenders: even a
re-raise compresses onto the one exception rather than storming the queue.

**A verifier that cannot read the world does not pass.** Evaluation compares the
condition's ``expected_state`` against live state read at sweep time; there is no
default that asserts agreement, mirroring the verification plane's refusal to
return ``passed`` on missing information.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics

from .contracts import IncidentSignal
from .exceptions import report_operational_signal
from .mission_contracts import Mission, MissionStatus, MonitoringCondition
from .mission_repository import (
    MissionRepository,
    MonitoringConditionRepository,
    mission_repository,
    monitoring_condition_repository,
)

logger = get_logger("aether.kyber.ops.monitoring")

#: Default checks-before-escalation when a condition's policy names none.
_DEFAULT_THRESHOLD = 3
#: Default seconds until the next check when a condition names no window.
_DEFAULT_WINDOW_SECONDS = 60


class MonitoringService:
    """Evaluate due monitoring conditions and escalate persistent divergence."""

    def __init__(
        self,
        conditions: Optional[MonitoringConditionRepository] = None,
        missions: Optional[MissionRepository] = None,
    ) -> None:
        self._conditions = conditions or monitoring_condition_repository
        self._missions = missions or mission_repository

    async def check_due(self, now: Optional[datetime] = None) -> dict[str, Any]:
        """Evaluate every condition due at ``now`` and escalate as needed.

        Args:
            now: The sweep instant. Computed internally as the current UTC time
                when ``None`` so the platform monitoring loop can call
                ``check_due()`` with no arguments.

        Returns:
            A small summary — how many conditions were checked, how many failed
            and how many escalated on this tick — for the caller's telemetry.
        """
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        stamp = reference.isoformat()

        due = await self._conditions.list_due(reference)
        checked = failed = escalated = skipped = 0

        for row in due:
            condition = MonitoringCondition(**row)
            mission_row = await self._missions.get(condition.mission_id)
            if mission_row is None:
                # An orphaned condition — the mission it watched is gone. Nothing
                # to evaluate; leave it for reconciliation rather than escalate.
                skipped += 1
                continue
            mission = Mission(**mission_row)
            checked += 1

            passing = self._evaluate(condition, mission)
            condition.last_checked_at = stamp
            condition.next_check_at = (
                reference + timedelta(seconds=self._window_seconds(condition.window))
            ).isoformat()
            condition.updated_at = stamp

            if passing:
                condition.status = "passing"
                condition.failure_count = 0
            else:
                failed += 1
                condition.failure_count += 1
                threshold = self._threshold(condition.escalation_policy)
                if condition.status != "escalated" and condition.failure_count >= threshold:
                    await self._escalate(condition, mission)
                    condition.status = "escalated"
                    escalated += 1
                else:
                    condition.status = "failing"

            await self._conditions.save_or_update(condition.model_dump(mode="json"))

        metrics.increment(
            "kyber_mission_monitor_ticks_total",
            labels={"escalated": str(escalated), "failed": str(failed)},
        )
        return {
            "checked": checked,
            "failed": failed,
            "escalated": escalated,
            "skipped": skipped,
            "generated_at": stamp,
        }

    # ── Evaluation ───────────────────────────────────────────────────────────

    @staticmethod
    def _evaluate(condition: MonitoringCondition, mission: Mission) -> bool:
        """Whether the mission's live state still matches the condition.

        The mission status is the live signal for a status condition; any other
        ``condition_type`` is read from the mission's metadata under that key.
        Equality is the passing case — a state that cannot be read (absent
        metadata) compares unequal and therefore fails, never silently passes.
        """
        expected = condition.expected_state
        ctype = condition.condition_type
        if ctype in ("mission_status", "status"):
            observed: Any = mission.status.value
        else:
            observed = mission.metadata.get(ctype)
        return observed == expected

    async def _escalate(self, condition: MonitoringCondition, mission: Mission) -> None:
        """Raise one operator signal and put the mission under monitoring.

        The signal — not an objective transition — is the escalation path,
        because a completed objective has no reopen. The mission root is set to
        ``monitoring`` directly (not through :meth:`MissionService.transition`)
        precisely because this is a system escalation rather than an operator
        move: it must always record that the mission is now watched, even from a
        state the operator lifecycle map would not permit that move from.
        """
        policy = condition.escalation_policy or {}
        severity = str(policy.get("severity") or "high")
        signal = IncidentSignal(
            source="kyber.mission.monitor",
            signal_type=condition.condition_type,
            tenant_id=mission.tenant_id or None,
            feature=policy.get("feature"),
            payload={
                "mission_id": mission.mission_id,
                "condition_id": condition.condition_id,
                "condition_type": condition.condition_type,
                "expected_state": condition.expected_state,
                "failure_count": condition.failure_count,
                "objective_id": mission.objective_id,
            },
        )
        await report_operational_signal(
            signal,
            title=(
                f"Mission monitoring failed: {condition.condition_type} on "
                f"mission {mission.mission_id}"
            ),
            dedupe_key=f"mission:{mission.mission_id}:{condition.condition_id}",
            severity=severity,  # type: ignore[arg-type]
            probable_cause=(
                f"Expected {condition.expected_state!r} but the live state diverged "
                f"for {condition.failure_count} consecutive checks"
            ),
            recommended_action=policy.get("recommended_action"),
            data_integrity_exposure=bool(policy.get("data_integrity_exposure", False)),
            correlate=True,
        )

        if mission.status != MissionStatus.MONITORING:
            mission.status = MissionStatus.MONITORING
            mission.updated_at = datetime.now(timezone.utc).isoformat()
            await self._missions.save_or_update(mission.model_dump(mode="json"))

        logger.warning(
            "kyber mission monitor escalated mission=%s condition=%s type=%s failures=%d",
            mission.mission_id, condition.condition_id,
            condition.condition_type, condition.failure_count,
        )

    # ── Policy helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _threshold(policy: dict[str, Any]) -> int:
        """Consecutive failures a condition tolerates before it escalates."""
        raw = (policy or {}).get("max_failures", (policy or {}).get("threshold"))
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return _DEFAULT_THRESHOLD
        return value if value >= 1 else _DEFAULT_THRESHOLD

    @staticmethod
    def _window_seconds(window: Any) -> int:
        """Seconds until a condition's next check, from a flexible ``window``.

        Accepts a bare number of seconds, a mapping of
        ``seconds``/``minutes``/``hours``, or a numeric string; anything
        unrecognised falls back to a safe default so a malformed window slows the
        cadence rather than crashing the sweep.
        """
        if isinstance(window, bool):
            return _DEFAULT_WINDOW_SECONDS
        if isinstance(window, (int, float)):
            return int(window) if window > 0 else _DEFAULT_WINDOW_SECONDS
        if isinstance(window, dict):
            total = (
                int(window.get("seconds", 0) or 0)
                + int(window.get("minutes", 0) or 0) * 60
                + int(window.get("hours", 0) or 0) * 3600
            )
            return total if total > 0 else _DEFAULT_WINDOW_SECONDS
        if isinstance(window, str):
            try:
                value = int(float(window))
            except (TypeError, ValueError):
                return _DEFAULT_WINDOW_SECONDS
            return value if value > 0 else _DEFAULT_WINDOW_SECONDS
        return _DEFAULT_WINDOW_SECONDS


#: Process-wide singleton. The main-app monitoring loop constructs its own
#: instance; this one is shared by routes and tests.
monitoring_service = MonitoringService()

__all__ = [
    "MonitoringService",
    "monitoring_service",
]
