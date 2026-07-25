"""JSONB repositories for the governed command plane.

Three tables, created by ``alembic/versions/20260810_kyber_graph_ops.py``:
``kyber_command_requests``, ``kyber_command_executions`` and
``kyber_command_verifications``. Each row is the pydantic contract's
``model_dump()`` stored in the ``data`` column, exactly as
:mod:`services.kyber.ops.repository` does for exceptions and incidents.

Every lookup here is written against an expression the migration actually
indexes, because a read path that ignores its own constraint is a constraint
that only fires on the write:

* ``ux_kyber_command_idempotency`` is unique on
  ``((data->>'command_type'), (data->>'idempotency_key'))``, so
  :meth:`CommandRepository.find_by_idempotency` filters on those two keys and
  nothing else. The database refuses the second insert; this lookup is what lets
  the service return the *first* command instead of surfacing a constraint
  violation to an operator who simply retried a request.
* ``ix_kyber_commands_status`` covers ``(status, created_at)`` and
  ``ix_kyber_command_requests_status`` covers ``data->>'status'``, so listing is
  by status.
* ``ix_kyber_command_executions_command`` and
  ``ix_kyber_command_verifications_command`` cover ``data->>'command_id'``, so
  both child tables are read by their parent command and never by a scan.

Backend selection is inherited from :class:`~repositories.repos.BaseRepository`:
asyncpg in staging/production, a shared in-memory dict per table when
``AETHER_ENV=local``, so nothing here needs a database to be exercised.
"""
from __future__ import annotations

from typing import Any, Optional

from repositories.repos import BaseRepository

#: Command statuses that mean the command has not reached a resting state.
#: ``executed_unverified`` is deliberately in this set: a command whose
#: postconditions were never confirmed is still someone's problem.
OPEN_COMMAND_STATUSES: tuple[str, ...] = (
    "requested",
    "awaiting_approval",
    "approved",
    "dry_run_complete",
    "executing",
    "executed_unverified",
)


def _first_tenant(record: dict[str, Any]) -> str:
    """Tenant for the indexed column, or ``""`` for fleet-wide commands.

    A command carries ``tenant_ids`` (a list) because one command can name
    several. The typed column exists for the per-tenant index the migration
    creates, so it takes the first entry; multi-tenant reach is read from the
    payload.
    """
    tenants = record.get("tenant_ids") or []
    if isinstance(tenants, list) and tenants:
        first = tenants[0]
        if isinstance(first, str):
            return first
    tenant_id = record.get("tenant_id")
    return tenant_id if isinstance(tenant_id, str) else ""


class CommandRepository(BaseRepository):
    """Store for ``kyber_command_requests``."""

    def __init__(self) -> None:
        super().__init__("kyber_command_requests")

    async def save(self, record: dict[str, Any]) -> dict[str, Any]:
        """Insert one command payload, stamping the indexed tenant column."""
        payload = dict(record)
        payload.setdefault("tenant_id", _first_tenant(payload))
        return await self.insert(payload["command_id"], payload)

    async def save_or_update(self, record: dict[str, Any]) -> dict[str, Any]:
        """Persist a command whether or not it has been written before.

        Every lifecycle transition rewrites the whole row, and the service does
        not track whether a given command has already been inserted. Choosing
        here — rather than making each caller remember — is what keeps a
        transition from silently becoming a no-op on an unsaved command.
        """
        payload = dict(record)
        payload.setdefault("tenant_id", _first_tenant(payload))
        command_id = payload["command_id"]
        if await self.find_by_id(command_id) is None:
            return await self.insert(command_id, payload)
        return await self.update(command_id, payload)

    async def find_by_idempotency(
        self, command_type: str, idempotency_key: str
    ) -> Optional[dict[str, Any]]:
        """The command already recorded for this key, if there is one.

        Mirrors ``ux_kyber_command_idempotency`` term for term. Returns the
        earliest row so a repeated request keeps landing on the same command
        even in the pathological case where the constraint was absent when a
        historical duplicate was written.
        """
        if not command_type or not idempotency_key:
            return None
        rows = await self.find_many(
            {"command_type": command_type, "idempotency_key": idempotency_key}, limit=50
        )
        if not rows:
            return None
        rows.sort(key=lambda row: str(row.get("created_at") or ""))
        return rows[0]

    async def list_by_status(
        self,
        status: Optional[str] = None,
        *,
        command_type: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Commands filtered by status and/or type.

        ``status="open"`` means the whole unsettled set
        (:data:`OPEN_COMMAND_STATUSES`), not the literal value — an approved
        command that nobody executed and an executed command nobody verified are
        both still open questions.
        """
        statuses: tuple[str, ...]
        if status is None:
            statuses = ()
        elif status == "open":
            statuses = OPEN_COMMAND_STATUSES
        else:
            statuses = (status,)

        rows: list[dict[str, Any]] = []
        if not statuses:
            filters = {"command_type": command_type} if command_type else None
            rows = await self.find_many(filters, limit=limit)
        else:
            for value in statuses:
                filters = {"status": value}
                if command_type:
                    filters["command_type"] = command_type
                rows.extend(await self.find_many(filters, limit=limit))

        deduped: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(row.get("command_id") or row.get("id") or "")
            if key:
                deduped[key] = row
        ordered = sorted(
            deduped.values(), key=lambda row: str(row.get("created_at") or ""), reverse=True
        )
        return ordered[:limit]

    async def list_for_incident(
        self, incident_id: str, *, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Every command raised against one incident."""
        if not incident_id:
            return []
        return await self.find_many({"incident_id": incident_id}, limit=limit)


class CommandExecutionRepository(BaseRepository):
    """Store for ``kyber_command_executions``."""

    def __init__(self) -> None:
        super().__init__("kyber_command_executions")

    async def save(self, record: dict[str, Any], *, tenant_id: str = "") -> dict[str, Any]:
        """Insert one execution attempt.

        The tenant is passed in rather than derived: an execution row carries no
        tenant of its own, and inventing one from the handler result would put a
        value in the indexed column that no read path could rely on.
        """
        payload = dict(record)
        payload.setdefault("tenant_id", tenant_id)
        return await self.insert(payload["execution_id"], payload)

    async def list_for_command(
        self, command_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Every attempt made for one command, oldest first."""
        if not command_id:
            return []
        rows = await self.find_many({"command_id": command_id}, limit=limit)
        rows.sort(key=lambda row: str(row.get("started_at") or ""))
        return rows

    async def latest_for_command(self, command_id: str) -> Optional[dict[str, Any]]:
        """The most recent attempt, or ``None`` when the command never ran."""
        rows = await self.list_for_command(command_id)
        return rows[-1] if rows else None

    async def attempt_count(self, command_id: str) -> int:
        """How many times this command has been dispatched.

        The service reads this before dispatching so a second execute call
        cannot quietly become a second side effect.
        """
        return len(await self.list_for_command(command_id))


class CommandVerificationRepository(BaseRepository):
    """Store for ``kyber_command_verifications``."""

    def __init__(self) -> None:
        super().__init__("kyber_command_verifications")

    async def save(self, record: dict[str, Any], *, tenant_id: str = "") -> dict[str, Any]:
        """Insert one verification result."""
        payload = dict(record)
        payload.setdefault("tenant_id", tenant_id)
        return await self.insert(payload["verification_id"], payload)

    async def list_for_command(
        self, command_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Every verification run for one command, oldest first."""
        if not command_id:
            return []
        rows = await self.find_many({"command_id": command_id}, limit=limit)
        rows.sort(key=lambda row: str(row.get("started_at") or ""))
        return rows

    async def latest_for_command(self, command_id: str) -> Optional[dict[str, Any]]:
        """The most recent verification, or ``None`` when none has run.

        ``None`` is the correct answer for a command that reached
        ``executed_unverified`` and stopped there, and callers must render it as
        "not verified" rather than as an absent field.
        """
        rows = await self.list_for_command(command_id)
        return rows[-1] if rows else None


#: Module-level singletons. Sharing one instance per table keeps the in-memory
#: backend behaving like a database across the service and the routes.
command_repository = CommandRepository()
command_execution_repository = CommandExecutionRepository()
command_verification_repository = CommandVerificationRepository()

__all__ = [
    "OPEN_COMMAND_STATUSES",
    "CommandExecutionRepository",
    "CommandRepository",
    "CommandVerificationRepository",
    "command_execution_repository",
    "command_repository",
    "command_verification_repository",
]
