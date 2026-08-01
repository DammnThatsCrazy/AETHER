"""JSONB repositories for the Kyber Mission aggregate.

Two tables, created by ``alembic/versions/20260815_kyber_missions.py``:
``kyber_missions`` and ``kyber_monitoring_conditions``. Each row is the pydantic
contract's ``model_dump()`` stored in the ``data`` column, exactly as
:mod:`services.kyber.ops.command_repository` does for commands and
:mod:`services.kyber.ops.repository` does for exceptions.

Every lookup here is written against an expression the migration actually
indexes, so a read path never diverges from its own constraint:

* ``ux_kyber_missions_objective`` is unique on ``((data->>'objective_id'))`` —
  one live mission per objective — so :meth:`MissionRepository.find_by_objective`
  filters on that key and the service uses it to make ``open_mission`` idempotent
  rather than surface a constraint violation to an operator who retried.
* ``ix_kyber_missions_status`` covers ``(data->>'status')``, so listing is by
  status.
* ``ix_kyber_monitoring_due`` covers ``((data->>'status'), (data->>'next_check_at'))``,
  which is exactly what the monitoring sweep reads: the conditions that are both
  still active and due.

Backend selection is inherited from :class:`~repositories.repos.BaseRepository`:
asyncpg in staging/production, a shared in-memory dict per table when
``AETHER_ENV=local``, so nothing here needs a database to be exercised.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.temporal.instant import ensure_aware_utc

from .mission_contracts import MONITORING_ACTIVE_STATUSES, MissionStatus

#: Mission statuses that mean the mission has not reached a resting state. Used
#: when a caller asks for the ``open`` set rather than a single literal status.
OPEN_MISSION_STATUSES: tuple[str, ...] = (
    MissionStatus.DETECTED.value,
    MissionStatus.PROPOSED.value,
    MissionStatus.PLANNING.value,
    MissionStatus.QUEUED.value,
    MissionStatus.ACTIVE.value,
    MissionStatus.WAITING.value,
    MissionStatus.PAUSED.value,
    MissionStatus.BLOCKED.value,
    MissionStatus.VERIFYING.value,
    MissionStatus.AWAITING_REVIEW.value,
    MissionStatus.COMMITTING.value,
    MissionStatus.MONITORING.value,
    MissionStatus.EXTERNALLY_BLOCKED.value,
)


def _to_dt(value: Any) -> Optional[datetime]:
    """Coerce an ISO-8601 string / datetime / None to tz-aware UTC.

    Returns ``None`` when the value is missing or unparseable, so a condition
    with no ``next_check_at`` sorts as "never scheduled" rather than crashing
    the sweep.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return None
    return dt.astimezone(timezone.utc)


class MissionRepository(BaseRepository):
    """Store for ``kyber_missions``."""

    def __init__(self) -> None:
        super().__init__("kyber_missions")

    async def save_or_update(self, record: dict[str, Any]) -> dict[str, Any]:
        """Persist a mission whether or not it has been written before.

        Every lifecycle transition rewrites the whole row, and the service does
        not track whether a given mission has already been inserted. Choosing
        here — rather than making each caller remember — keeps a transition from
        silently becoming a no-op on an unsaved mission, the same choice
        :class:`~services.kyber.ops.command_repository.CommandRepository` makes.
        """
        payload = dict(record)
        payload.setdefault("tenant_id", payload.get("tenant_id") or "")
        mission_id = payload["mission_id"]
        if await self.find_by_id(mission_id) is None:
            return await self.insert(mission_id, payload)
        return await self.update(mission_id, payload)

    async def get(self, mission_id: str) -> Optional[dict[str, Any]]:
        """One mission by id, or ``None``."""
        if not mission_id:
            return None
        return await self.find_by_id(mission_id)

    async def find_by_objective(self, objective_id: str) -> Optional[dict[str, Any]]:
        """The single live mission for an objective, if one exists.

        Mirrors ``ux_kyber_missions_objective`` term for term. Returns the
        earliest row so a retry keeps landing on the same mission even in the
        pathological case where a historical duplicate predates the constraint.
        """
        if not objective_id:
            return None
        rows = await self.find_many({"objective_id": objective_id}, limit=50)
        if not rows:
            return None
        rows.sort(key=lambda row: str(row.get("created_at") or ""))
        return rows[0]

    async def list_by_status(
        self, status: Optional[str] = None, *, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Missions filtered by status.

        ``status="open"`` expands to :data:`OPEN_MISSION_STATUSES` — the whole
        unsettled set — rather than the literal value, because a mission that is
        verifying and one that is monitoring are both still someone's problem.
        """
        statuses: tuple[str, ...]
        if status is None:
            statuses = ()
        elif status == "open":
            statuses = OPEN_MISSION_STATUSES
        else:
            statuses = (status,)

        rows: list[dict[str, Any]] = []
        if not statuses:
            rows = await self.find_many(None, limit=limit)
        else:
            for value in statuses:
                rows.extend(await self.find_many({"status": value}, limit=limit))

        deduped: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(row.get("mission_id") or row.get("id") or "")
            if key:
                deduped[key] = row
        ordered = sorted(
            deduped.values(), key=lambda row: str(row.get("created_at") or ""), reverse=True
        )
        return ordered[:limit]

    async def list_for_tenant(
        self, tenant_id: str, *, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Every mission bound to one tenant, newest first."""
        if not tenant_id:
            return []
        rows = await self.find_many({"tenant_id": tenant_id}, limit=limit)
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return rows[:limit]


class MonitoringConditionRepository(BaseRepository):
    """Store for ``kyber_monitoring_conditions``."""

    def __init__(self) -> None:
        super().__init__("kyber_monitoring_conditions")

    async def save_or_update(self, record: dict[str, Any]) -> dict[str, Any]:
        """Persist a monitoring condition, insert-or-update by id."""
        payload = dict(record)
        payload.setdefault("tenant_id", payload.get("tenant_id") or "")
        condition_id = payload["condition_id"]
        if await self.find_by_id(condition_id) is None:
            return await self.insert(condition_id, payload)
        return await self.update(condition_id, payload)

    async def get(self, condition_id: str) -> Optional[dict[str, Any]]:
        if not condition_id:
            return None
        return await self.find_by_id(condition_id)

    async def list_for_mission(
        self, mission_id: str, *, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Every condition a mission scheduled, oldest first."""
        if not mission_id:
            return []
        rows = await self.find_many({"mission_id": mission_id}, limit=limit)
        rows.sort(key=lambda row: str(row.get("created_at") or ""))
        return rows

    async def list_by_status(
        self, status: str, *, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Conditions in one status."""
        if not status:
            return []
        return await self.find_many({"status": status}, limit=limit)

    async def list_due(
        self, now: Optional[datetime] = None, *, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Active conditions whose next check is due at ``now``.

        The composite index covers ``(status, next_check_at)`` but
        :meth:`BaseRepository.find_many` does only equality, so the
        ``next_check_at <= now`` half of the predicate is applied here rather
        than pushed down. A condition that has never been checked
        (``next_check_at`` is ``None``) is due immediately — the first sweep is
        what schedules it. ``escalated`` and ``resolved`` conditions are skipped:
        an escalated condition has already raised its signal and a second sweep
        must not raise a second one.
        """
        reference = ensure_aware_utc(now) if now is not None else datetime.now(timezone.utc)

        due: list[dict[str, Any]] = []
        for status in sorted(MONITORING_ACTIVE_STATUSES):
            for row in await self.find_many({"status": status}, limit=limit):
                next_dt = _to_dt(row.get("next_check_at"))
                if next_dt is None or next_dt <= reference:
                    due.append(row)
        due.sort(key=lambda row: str(row.get("next_check_at") or ""))
        return due[:limit]


#: Module-level singletons. Sharing one instance per table keeps the in-memory
#: backend behaving like a database across the service, the routes and the
#: monitoring loop.
mission_repository = MissionRepository()
monitoring_condition_repository = MonitoringConditionRepository()

__all__ = [
    "OPEN_MISSION_STATUSES",
    "MissionRepository",
    "MonitoringConditionRepository",
    "mission_repository",
    "monitoring_condition_repository",
]
