"""Explicit tenant-owned bindings from external agent refs to Agent entities.

The external ``agent_id`` in a deployment is a source reference, never a
canonical identity. A tenant manager can create a backend-persisted binding
only after the API verifies the target is an Agent entity in that tenant.
Bindings are immutable and namespaced; conflicting attempts fail closed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from repositories.repos import BaseRepository
from shared.common.common import ConflictError
from shared.graph.edge_properties import build_edge_properties, make_edge_idempotency_key
from shared.graph.graph import Edge, EdgeType, Vertex, VertexType

_NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_locks: dict[str, asyncio.Lock] = {}


def _binding_id(tenant_id: str, source_namespace: str, source_agent_ref: str) -> str:
    material = json.dumps(
        [tenant_id, source_namespace, source_agent_ref],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "agent_identity_binding_" + hashlib.sha256(material.encode("utf-8")).hexdigest()


class AgentDeploymentIdentityBindingRepository(BaseRepository):
    """Immutable mapping authority scoped by tenant + namespace + source ref."""

    def __init__(self) -> None:
        super().__init__("agent_deployment_identity_bindings")

    async def bind(
        self,
        *,
        tenant_id: str,
        source_namespace: str,
        source_agent_ref: str,
        canonical_agent_entity_id: str,
        bound_by: str,
        source_deployment_id: str,
    ) -> dict[str, Any]:
        namespace = source_namespace.strip().lower()
        source_ref = source_agent_ref.strip()
        canonical_id = canonical_agent_entity_id.strip()
        if not tenant_id or not _NAMESPACE_RE.fullmatch(namespace):
            raise ValueError("valid tenant_id and source_namespace are required")
        if not source_ref or len(source_ref) > 256 or any(
            ord(char) < 32 or ord(char) == 127 for char in source_ref
        ):
            raise ValueError("source_agent_ref must be a bounded printable reference")
        if not canonical_id or not source_deployment_id:
            raise ValueError("canonical entity and source deployment are required")

        identity = [tenant_id, namespace, source_ref]
        lock_key = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
        lock = _locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            existing = await self.find_for_source(tenant_id, namespace, source_ref)
            if len(existing) > 1:
                raise ConflictError("Agent identity binding is ambiguous")
            if existing:
                current = existing[0]
                if current.get("canonical_agent_entity_id") != canonical_id:
                    raise ConflictError(
                        "Source agent reference is already bound to another canonical Agent"
                    )
                return current

            now = datetime.now(timezone.utc).isoformat()
            record_id = _binding_id(tenant_id, namespace, source_ref)
            record = {
                "id": record_id,
                "tenant_id": tenant_id,
                "source_namespace": namespace,
                "source_agent_ref": source_ref,
                "canonical_agent_entity_id": canonical_id,
                "source_deployment_id": source_deployment_id,
                "binding_authority": "tenant_admin_explicit",
                "bound_by": bound_by,
                "bound_at": now,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }

            pool = await self._ensure_pool()
            if pool is None:
                # Shared in-memory repository is used only in local/test mode.
                self._store[record_id] = record
            else:
                await self._ensure_table()
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        # Serialize distinct writers for the same identity key.
                        await conn.execute(
                            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                            f"agent_identity_binding:{lock_key}",
                        )
                        rows = await conn.fetch(
                            f"SELECT data FROM {self.table_name} "
                            "WHERE tenant_id = $1 "
                            "AND data->>'source_namespace' = $2 "
                            "AND data->>'source_agent_ref' = $3 LIMIT 2 FOR UPDATE",
                            tenant_id,
                            namespace,
                            source_ref,
                        )
                        if len(rows) > 1:
                            raise ConflictError("Agent identity binding is ambiguous")
                        if rows:
                            current = self._decode_row(rows[0]["data"])
                            if current.get("canonical_agent_entity_id") != canonical_id:
                                raise ConflictError(
                                    "Source agent reference is already bound to another canonical Agent"
                                )
                            return current
                        await conn.execute(
                            f"INSERT INTO {self.table_name} "
                            "(id, data, tenant_id, created_at, updated_at) "
                            "VALUES ($1, $2::jsonb, $3, NOW(), NOW()) "
                            "ON CONFLICT DO NOTHING",
                            record_id,
                            json.dumps(record, default=str),
                            tenant_id,
                        )
                        # A concurrent or migrated conflicting row is read back
                        # and validated below; it is never silently overwritten.

            persisted = await self.find_for_source(tenant_id, namespace, source_ref)
            if len(persisted) != 1:
                raise ConflictError("Agent identity binding could not be stored uniquely")
            current = persisted[0]
            if current.get("canonical_agent_entity_id") != canonical_id:
                raise ConflictError(
                    "Source agent reference is already bound to another canonical Agent"
                )
            return current

    async def find_for_source(
        self, tenant_id: str, source_namespace: str, source_agent_ref: str,
    ) -> list[dict[str, Any]]:
        """Return at most two matches so callers can fail closed on ambiguity."""
        return await self.find_many(
            filters={
                "tenant_id": tenant_id,
                "source_namespace": source_namespace,
                "source_agent_ref": source_agent_ref,
                "status": "active",
            },
            limit=2,
        )

    @staticmethod
    def _decode_row(value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except ValueError:
                return {}
            return decoded if isinstance(decoded, dict) else {}
        return value if isinstance(value, dict) else {}


def build_agent_deployment_identity_mutations(
    deployment: dict[str, Any], binding: dict[str, Any],
) -> list[Any]:
    """Project a verified stored binding as Agent → external deployment.

    The edge represents the tenant's explicit identity binding. It does not
    make the source runtime an execution authority or verify source-reported
    actions.
    """
    tenant_id = str(deployment.get("tenant_id") or "")
    deployment_id = str(deployment.get("id") or "")
    canonical_agent_id = str(binding.get("canonical_agent_entity_id") or "")
    namespace = str(binding.get("source_namespace") or "")
    source_ref = str(binding.get("source_agent_ref") or "")
    if not all((tenant_id, deployment_id, canonical_agent_id, namespace, source_ref)):
        return []
    if (
        binding.get("tenant_id") != tenant_id
        or deployment.get("agent_id") != source_ref
        or deployment.get("agent_source_namespace") != namespace
        or binding.get("binding_authority") != "tenant_admin_explicit"
        or binding.get("status") != "active"
    ):
        return []

    edge_type = EdgeType.AGENT_LINKED_TO_EXTERNAL_ACCOUNT
    return [
        Vertex(
            vertex_type=VertexType.EXTERNAL_AGENTIC_ACCOUNT,
            vertex_id=deployment_id,
            properties={
                "tenant_id": tenant_id,
                "kind": "agent_deployment",
                "agent_reference_authority": "tenant_deployment_registry",
            },
        ),
        Edge(
            edge_type=edge_type,
            from_vertex_id=canonical_agent_id,
            to_vertex_id=deployment_id,
            properties=build_edge_properties(
                tenant_id=tenant_id,
                edge_type=edge_type,
                from_vertex_id=canonical_agent_id,
                to_vertex_id=deployment_id,
                actor_kind="system",
                actor_id="agent_deployment_identity_binding",
                provenance="agent_deployment_identity_binding",
                provenance_class="direct",
                source_event_id=str(binding.get("id") or deployment_id),
                valid_from=str(binding.get("bound_at") or ""),
                confidence=1.0,
                idempotency_key=make_edge_idempotency_key(
                    tenant_id, edge_type, canonical_agent_id, deployment_id,
                    f"agent_binding:{namespace}:{source_ref}",
                ),
                binding_authority="tenant_admin_explicit",
                source_namespace=namespace,
                source_agent_ref=source_ref,
                canonical_agent_entity_id=canonical_agent_id,
            ),
        ),
    ]
