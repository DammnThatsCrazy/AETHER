"""Append-only persistence for the IRRL authority.

The repository uses the platform's shared asyncpg pool in staging/production
and its explicitly local-only in-memory backend in local development/tests.
Unlike ``BaseRepository.insert``, an existing id is never overwritten: replay
of the same payload is a no-op and a conflicting payload raises.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from repositories.repos import BaseRepository, get_pool


class ImmutableRightsRecordError(ValueError):
    """Raised when an append-only IRRL record is reused with different data."""


_TABLES = {
    "policy": "irrl_policy_sets",
    "envelope": "irrl_artifact_rights_envelopes",
    "decision": "irrl_rights_decisions",
    "derivation": "irrl_derivation_edges",
    "impact": "irrl_impact_graphs",
    "revocation": "irrl_revocations",
    "source_grant": "irrl_source_grants",
}


def _canonical(value: Any) -> str:
    if isinstance(value, dict):
        # BaseRepository adds local persistence metadata to the JSON document;
        # those fields are not part of the immutable IRRL contract.
        value = {
            key: item for key, item in value.items()
            if key not in {"id", "created_at", "updated_at"} and not key.startswith("_")
        }
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class RightsLedgerRepository:
    """Durable append-only IRRL record store."""

    def __init__(self) -> None:
        self._repos = {key: BaseRepository(table) for key, table in _TABLES.items()}

    async def _append(self, kind: str, record_id: str, data: dict[str, Any]) -> bool:
        repo = self._repos[kind]
        existing = await repo.find_by_id(record_id)
        if existing is not None:
            if _canonical(existing) != _canonical(data):
                raise ImmutableRightsRecordError(
                    f"immutable IRRL record conflict: {_TABLES[kind]}/{record_id}"
                )
            return False

        pool = await get_pool()
        if pool is None:
            await repo.insert(record_id, dict(data))
            return True

        await repo._ensure_table()  # migration owns the same additive JSONB shape
        tenant_id = data.get("tenant_id")
        payload = json.dumps(data, default=str)
        result = await pool.execute(
            f"""INSERT INTO {_TABLES[kind]} (id, data, tenant_id)
                VALUES ($1, $2::jsonb, $3)
                ON CONFLICT (id) DO NOTHING""",
            record_id,
            payload,
            tenant_id,
        )
        if str(result).endswith("0"):
            existing = await repo.find_by_id(record_id)
            if existing is not None and _canonical(existing) != _canonical(data):
                raise ImmutableRightsRecordError(
                    f"immutable IRRL record conflict: {_TABLES[kind]}/{record_id}"
                )
            return False
        return True

    async def _get(self, kind: str, record_id: str) -> Optional[dict[str, Any]]:
        return await self._repos[kind].find_by_id(record_id)

    async def _list(self, kind: str, tenant_id: Optional[str] = None, limit: int = 1000) -> list[dict[str, Any]]:
        filters = {"tenant_id": tenant_id} if tenant_id is not None else None
        return await self._repos[kind].find_many(filters=filters, limit=limit, sort_by="created_at", sort_order="asc")

    async def append_policy(self, value: dict[str, Any]) -> bool:
        return await self._append("policy", value["policy_set_id"], value)

    async def get_policy(self, record_id: str) -> Optional[dict[str, Any]]:
        return await self._get("policy", record_id)

    async def list_policies(self, tenant_id: Optional[str] = None) -> list[dict[str, Any]]:
        return await self._list("policy", tenant_id)

    async def append_envelope(self, value: dict[str, Any]) -> bool:
        return await self._append("envelope", value["envelope_id"], value)

    async def get_envelope(self, record_id: str) -> Optional[dict[str, Any]]:
        return await self._get("envelope", record_id)

    async def list_envelopes(self, tenant_id: Optional[str] = None) -> list[dict[str, Any]]:
        return await self._list("envelope", tenant_id)

    async def append_decision(self, value: dict[str, Any]) -> bool:
        return await self._append("decision", value["decision_id"], value)

    async def get_decision(self, record_id: str) -> Optional[dict[str, Any]]:
        return await self._get("decision", record_id)

    async def list_decisions(self, tenant_id: Optional[str] = None) -> list[dict[str, Any]]:
        return await self._list("decision", tenant_id)

    async def append_derivation(self, value: dict[str, Any]) -> bool:
        return await self._append("derivation", value["edge_id"], value)

    async def list_derivations(self, limit: int = 10000) -> list[dict[str, Any]]:
        return await self._list("derivation", limit=limit)

    async def append_impact(self, value: dict[str, Any]) -> bool:
        return await self._append("impact", value["impact_graph_id"], value)

    async def get_impact(self, record_id: str) -> Optional[dict[str, Any]]:
        return await self._get("impact", record_id)

    async def list_impacts(self, tenant_id: Optional[str] = None) -> list[dict[str, Any]]:
        return await self._list("impact", tenant_id)

    async def append_revocation(self, value: dict[str, Any]) -> bool:
        return await self._append("revocation", value["revocation_id"], value)

    async def list_revocations(self, tenant_id: Optional[str] = None) -> list[dict[str, Any]]:
        return await self._list("revocation", tenant_id)

    async def append_source_grant(self, value: dict[str, Any]) -> bool:
        return await self._append("source_grant", value["data_rights_grant_id"], value)

    async def get_source_grant(self, record_id: str) -> Optional[dict[str, Any]]:
        return await self._get("source_grant", record_id)

    async def get_latest_source_grant(self, record_id: str) -> Optional[dict[str, Any]]:
        """Resolve an append-only grant revision by its stable public id."""
        rows = await self.list_source_grants()
        revisions = [
            row for row in rows
            if row.get("data_rights_grant_id") == record_id
            or row.get("id") == record_id
        ]
        if not revisions:
            return None
        return max(revisions, key=lambda row: int(row.get("grant_version", 1)))

    async def list_source_grants(self, tenant_id: Optional[str] = None) -> list[dict[str, Any]]:
        return await self._list("source_grant", tenant_id)


__all__ = ["ImmutableRightsRecordError", "RightsLedgerRepository"]
