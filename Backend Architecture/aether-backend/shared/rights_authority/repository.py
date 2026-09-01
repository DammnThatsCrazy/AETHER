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
    "evidence_manifest": "irrl_evidence_manifests",
    "remediation_step": "irrl_remediation_steps",
    "remediation_receipt": "irrl_remediation_receipts",
    "audit_outbox": "irrl_rights_audit_outbox",
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
        value = {**value, "policy_revision": int(value.get("policy_revision", 1))}
        return await self._append("policy", value["policy_set_id"], value)

    async def get_policy(self, record_id: str) -> Optional[dict[str, Any]]:
        rows = await self._list("policy")
        revisions = [
            row for row in rows
            if row.get("policy_set_id") == record_id or row.get("id") == record_id
        ]
        if not revisions:
            return None
        return max(revisions, key=lambda row: int(row.get("policy_revision", 1)))

    async def list_policies(self, tenant_id: Optional[str] = None) -> list[dict[str, Any]]:
        rows = await self._list("policy", tenant_id)
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            policy_id = row.get("policy_set_id") or row.get("id")
            if not policy_id:
                continue
            if int(row.get("policy_revision", 1)) >= int(latest.get(policy_id, {}).get("policy_revision", 0)):
                latest[policy_id] = row
        return list(latest.values())

    async def append_policy_revision(self, value: dict[str, Any]) -> bool:
        """Append an immutable state revision while retaining the public id."""
        policy_id = value["policy_set_id"]
        revision = int(value.get("policy_revision", 1))
        return await self._append("policy", f"{policy_id}:v{revision}", {
            **value, "policy_revision": revision,
        })

    async def append_envelope(self, value: dict[str, Any]) -> bool:
        return await self._append("envelope", value["envelope_id"], value)

    async def get_envelope(self, record_id: str) -> Optional[dict[str, Any]]:
        return await self._get("envelope", record_id)

    async def list_envelopes(self, tenant_id: Optional[str] = None) -> list[dict[str, Any]]:
        return await self._list("envelope", tenant_id)

    async def append_decision(self, value: dict[str, Any]) -> bool:
        request_id = value.get("request_id")
        if request_id:
            existing = await self.get_decision_by_request_id(str(request_id))
            if existing is not None and _canonical(existing) != _canonical(value):
                raise ImmutableRightsRecordError(
                    f"immutable IRRL request conflict: {request_id}"
                )
        return await self._append("decision", value["decision_id"], value)

    async def append_decision_with_audit_outbox(
        self, decision: dict[str, Any], audit_event: dict[str, Any]
    ) -> bool:
        """Atomically append a decision and its durable audit projection.

        PostgreSQL uses one transaction. The local backend is intentionally
        sequential but deterministic; it is not an authority backend.
        """
        pool = await get_pool()
        outbox = {
            "outbox_id": f"raob_{decision['decision_id']}",
            "tenant_id": decision.get("tenant_id"),
            "decision_id": decision["decision_id"],
            "status": "pending",
            "event": audit_event,
        }
        if pool is None:
            inserted = await self.append_decision(decision)
            await self._append("audit_outbox", outbox["outbox_id"], outbox)
            return inserted

        decision_repo = self._repos["decision"]
        outbox_repo = self._repos["audit_outbox"]
        await decision_repo._ensure_table()
        await outbox_repo._ensure_table()
        async with pool.acquire() as connection:
            async with connection.transaction():
                decision_result = await connection.execute(
                    """INSERT INTO irrl_rights_decisions (id, data, tenant_id)
                    VALUES ($1, $2::jsonb, $3) ON CONFLICT (id) DO NOTHING""",
                    decision["decision_id"], json.dumps(decision, default=str),
                    decision.get("tenant_id"),
                )
                await connection.execute(
                    """INSERT INTO irrl_rights_audit_outbox (id, data, tenant_id)
                    VALUES ($1, $2::jsonb, $3) ON CONFLICT (id) DO NOTHING""",
                    outbox["outbox_id"], json.dumps(outbox, default=str),
                    outbox.get("tenant_id"),
                )
        return not str(decision_result).endswith("0")

    async def get_decision(self, record_id: str) -> Optional[dict[str, Any]]:
        return await self._get("decision", record_id)

    async def get_decision_by_request_id(self, request_id: str) -> Optional[dict[str, Any]]:
        """Return the immutable decision already assigned to a request id.

        PostgreSQL enforces this with ``uq_irrl_decisions_request``. The local
        backend mirrors the same idempotency rule so a retry cannot create a
        second authorization receipt.
        """
        if not request_id:
            return None
        for row in await self._list("decision"):
            if row.get("request_id") == request_id:
                return row
        return None

    async def list_decisions(self, tenant_id: Optional[str] = None) -> list[dict[str, Any]]:
        return await self._list("decision", tenant_id)

    async def list_audit_outbox(self, tenant_id: Optional[str] = None) -> list[dict[str, Any]]:
        return await self._list("audit_outbox", tenant_id)

    async def update_audit_outbox(self, outbox_id: str, **changes: Any) -> dict[str, Any]:
        """Advance delivery state for the mutable delivery envelope.

        The decision and audit event remain append-only; only the outbox's
        operational delivery metadata is mutable so retries can be observed.
        """
        return await self._repos["audit_outbox"].update(outbox_id, changes)

    async def append_derivation(self, value: dict[str, Any]) -> bool:
        return await self._append("derivation", value["edge_id"], value)

    async def list_derivations(self, limit: int = 10000) -> list[dict[str, Any]]:
        return await self._list("derivation", limit=limit)

    async def append_impact(self, value: dict[str, Any]) -> bool:
        value = {**value, "impact_revision": int(value.get("impact_revision", 1))}
        return await self._append("impact", value["impact_graph_id"], value)

    async def get_impact(self, record_id: str) -> Optional[dict[str, Any]]:
        rows = await self._list("impact")
        revisions = [
            row for row in rows
            if row.get("impact_graph_id") == record_id or row.get("id") == record_id
        ]
        if not revisions:
            return None
        return max(revisions, key=lambda row: int(row.get("impact_revision", 1)))

    async def list_impacts(self, tenant_id: Optional[str] = None) -> list[dict[str, Any]]:
        rows = await self._list("impact", tenant_id)
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            impact_id = row.get("impact_graph_id") or row.get("id")
            if not impact_id:
                continue
            if int(row.get("impact_revision", 1)) >= int(latest.get(impact_id, {}).get("impact_revision", 0)):
                latest[impact_id] = row
        return list(latest.values())

    async def append_impact_revision(self, value: dict[str, Any]) -> bool:
        impact_id = value["impact_graph_id"]
        revision = int(value.get("impact_revision", 1))
        return await self._append("impact", f"{impact_id}:v{revision}", {
            **value, "impact_revision": revision,
        })

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

    async def append_evidence_manifest(self, value: dict[str, Any]) -> bool:
        return await self._append("evidence_manifest", value["manifest_id"], value)

    async def get_evidence_manifest(self, record_id: str) -> Optional[dict[str, Any]]:
        return await self._get("evidence_manifest", record_id)

    async def list_evidence_manifests(self, tenant_id: Optional[str] = None) -> list[dict[str, Any]]:
        return await self._list("evidence_manifest", tenant_id)

    async def append_remediation_step(self, value: dict[str, Any]) -> bool:
        return await self._append("remediation_step", value["step_id"], value)

    async def list_remediation_steps(self, impact_graph_id: Optional[str] = None) -> list[dict[str, Any]]:
        rows = await self._list("remediation_step")
        if impact_graph_id is not None:
            rows = [row for row in rows if row.get("impact_graph_id") == impact_graph_id]
        return rows

    async def append_remediation_receipt(self, value: dict[str, Any]) -> bool:
        return await self._append("remediation_receipt", value["receipt_id"], value)

    async def list_remediation_receipts(self, impact_graph_id: Optional[str] = None) -> list[dict[str, Any]]:
        rows = await self._list("remediation_receipt")
        if impact_graph_id is not None:
            rows = [row for row in rows if row.get("impact_graph_id") == impact_graph_id]
        return rows


__all__ = ["ImmutableRightsRecordError", "RightsLedgerRepository"]
