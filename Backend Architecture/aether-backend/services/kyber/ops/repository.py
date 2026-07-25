"""JSONB repositories for the Kyber exception and incident tables.

Three tables, created by ``alembic/versions/20260810_kyber_graph_ops.py``:
``kyber_exceptions``, ``kyber_incidents`` and ``kyber_incident_signals``. Each
row is the pydantic contract's ``model_dump()`` stored in the ``data`` column,
with the handful of typed columns the migration indexes (``status``, ``bucket``,
``priority_score``, ``dedupe_key``, …) mirrored into that same payload so the
JSONB expression indexes and the in-memory fallback agree on where a field
lives.

The one piece of behaviour that belongs here rather than in the service is
:meth:`ExceptionRepository.find_open_by_dedupe_key`. The migration declares a
*partial* unique index — one open exception per ``dedupe_key``, for status in
``open``/``acknowledged``/``in_progress`` — and that index is what collapses an
alert storm into a single actionable item. ``BaseRepository.find_many`` only
does equality, so "open" has to be expanded into the same status set the index
uses; keeping that set next to the lookup is what stops the service and the
index from disagreeing about which rows are eligible for compression.

Backend selection is inherited: asyncpg in staging/production, a shared
in-memory dict per table when ``AETHER_ENV=local``, so nothing here needs a
database to be exercised.
"""
from __future__ import annotations

from typing import Any, Optional

from repositories.repos import BaseRepository

#: Statuses the partial unique index treats as "an exception that is still
#: live". Compression targets exactly these, so a resolved or suppressed
#: exception with the same ``dedupe_key`` starts a new row instead of
#: reviving a closed one.
OPEN_EXCEPTION_STATUSES: tuple[str, ...] = ("open", "acknowledged", "in_progress")

#: Incident statuses that are still someone's problem.
OPEN_INCIDENT_STATUSES: tuple[str, ...] = (
    "detected", "investigating", "identified", "mitigating", "monitoring",
)


def _first_tenant(record: dict[str, Any]) -> str:
    """Tenant for the indexed column, or ``""`` for fleet-wide rows.

    The contracts carry ``affected_tenants`` (a list) rather than a single
    tenant because one exception can span several. The column exists for the
    per-tenant index the migration creates, so it takes the first entry and
    leaves multi-tenant reach to be read from the payload.
    """
    tenants = record.get("affected_tenants") or []
    if isinstance(tenants, list) and tenants:
        first = tenants[0]
        if isinstance(first, str):
            return first
    tenant_id = record.get("tenant_id")
    return tenant_id if isinstance(tenant_id, str) else ""


class ExceptionRepository(BaseRepository):
    """Store for ``kyber_exceptions``."""

    def __init__(self) -> None:
        super().__init__("kyber_exceptions")

    async def save(self, record: dict[str, Any]) -> dict[str, Any]:
        """Insert one exception payload, stamping the indexed tenant column."""
        payload = dict(record)
        payload.setdefault("tenant_id", _first_tenant(payload))
        return await self.insert(payload["exception_id"], payload)

    async def find_open_by_dedupe_key(self, dedupe_key: str) -> Optional[dict[str, Any]]:
        """The single live exception for ``dedupe_key``, if there is one.

        Mirrors the partial unique index: only ``open``/``acknowledged``/
        ``in_progress`` rows are candidates. Returns the earliest-seen match so
        repeated compression keeps landing on the same row even in the
        pathological case where a historical duplicate exists.
        """
        if not dedupe_key:
            return None
        matches: list[dict[str, Any]] = []
        for status in OPEN_EXCEPTION_STATUSES:
            matches.extend(
                await self.find_many({"dedupe_key": dedupe_key, "status": status}, limit=50)
            )
        if not matches:
            return None
        matches.sort(key=lambda row: str(row.get("first_seen_at") or row.get("created_at") or ""))
        return matches[0]

    async def list_by_status(
        self,
        status: Optional[str] = None,
        *,
        bucket: Optional[str] = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Exceptions filtered by status and/or bucket.

        ``status="open"`` means the whole live set the index guards, not the
        literal ``open`` value — an acknowledged exception is still in the
        queue, it just already has an owner.
        """
        statuses: tuple[str, ...]
        if status is None:
            statuses = ()
        elif status == "open":
            statuses = OPEN_EXCEPTION_STATUSES
        else:
            statuses = (status,)

        rows: list[dict[str, Any]] = []
        if not statuses:
            filters = {"bucket": bucket} if bucket else None
            rows = await self.find_many(filters, limit=limit)
        else:
            for value in statuses:
                filters = {"status": value}
                if bucket:
                    filters["bucket"] = bucket
                rows.extend(await self.find_many(filters, limit=limit))
        deduped: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(row.get("exception_id") or row.get("id") or "")
            if key:
                deduped[key] = row
        return list(deduped.values())[:limit]

    async def list_for_incident(self, incident_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        """Every exception attached to one incident."""
        return await self.find_many({"incident_id": incident_id}, limit=limit)


class IncidentRepository(BaseRepository):
    """Store for ``kyber_incidents``."""

    def __init__(self) -> None:
        super().__init__("kyber_incidents")

    async def save(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = dict(record)
        payload.setdefault("tenant_id", _first_tenant(payload))
        return await self.insert(payload["incident_id"], payload)

    async def list_by_status(
        self,
        status: Optional[str] = None,
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Incidents by status; ``status="open"`` expands to the live set."""
        if status is None:
            return await self.find_many(None, limit=limit)
        statuses = OPEN_INCIDENT_STATUSES if status == "open" else (status,)
        rows: list[dict[str, Any]] = []
        for value in statuses:
            rows.extend(await self.find_many({"status": value}, limit=limit))
        deduped: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(row.get("incident_id") or row.get("id") or "")
            if key:
                deduped[key] = row
        return list(deduped.values())[:limit]

    async def list_open(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """Every incident that has not been resolved or closed."""
        return await self.list_by_status("open", limit=limit)


class IncidentSignalRepository(BaseRepository):
    """Store for ``kyber_incident_signals``."""

    def __init__(self) -> None:
        super().__init__("kyber_incident_signals")

    async def save(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = dict(record)
        payload.setdefault("tenant_id", payload.get("tenant_id") or "")
        return await self.insert(payload["signal_id"], payload)

    async def list_for_incident(self, incident_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        """Signals attributed to one incident, oldest observation first."""
        rows = await self.find_many({"incident_id": incident_id}, limit=limit)
        rows.sort(key=lambda row: str(row.get("observed_at") or ""))
        return rows

    async def list_unattached(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """Signals that no incident has claimed yet.

        ``incident_id`` is ``None`` on these rows, and ``find_many`` cannot
        express "IS NULL" (the SQL branch casts every filter value with
        ``str()``), so the predicate is applied here instead of pushed down.
        """
        rows = await self.find_many(None, limit=limit)
        unattached = [row for row in rows if not row.get("incident_id")]
        unattached.sort(key=lambda row: str(row.get("observed_at") or ""))
        return unattached[:limit]

    async def list_by_signature(self, error_signature: str, *, limit: int = 500) -> list[dict[str, Any]]:
        """Signals sharing an exact error signature."""
        if not error_signature:
            return []
        return await self.find_many({"error_signature": error_signature}, limit=limit)


#: Module-level singletons. Sharing one instance per table keeps the in-memory
#: backend behaving like a database across the service and the routes.
exception_repository = ExceptionRepository()
incident_repository = IncidentRepository()
incident_signal_repository = IncidentSignalRepository()

__all__ = [
    "OPEN_EXCEPTION_STATUSES",
    "OPEN_INCIDENT_STATUSES",
    "ExceptionRepository",
    "IncidentRepository",
    "IncidentSignalRepository",
    "exception_repository",
    "incident_repository",
    "incident_signal_repository",
]
