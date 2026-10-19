"""Shared tenant-scoped source-to-canonical Agent identity resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class _EntityRepository(Protocol):
    async def find_by_id(self, entity_id: str) -> Any: ...


class _DeploymentRepository(Protocol):
    async def list_page(
        self, tenant_id: str, *, limit: int, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None, bool]: ...


class _IdentityBindingRepository(Protocol):
    async def find_for_source(
        self, tenant_id: str, source_namespace: str, source_agent_ref: str
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class CanonicalAgentIdentityRead:
    """Resolved identity rows and completeness for a bounded source-ID set."""

    rows: list[dict[str, Any]]
    scope_mismatch: bool = False
    truncated: bool = False


async def resolve_agent_identities(
    tenant_id: str,
    agent_ids: set[str] | list[str] | tuple[str, ...],
    *,
    deployments: _DeploymentRepository,
    identity_bindings: _IdentityBindingRepository,
    entities: _EntityRepository,
    limit: int,
) -> CanonicalAgentIdentityRead:
    """Resolve source IDs only through tenant-owned Agent entities or bindings.

    Source IDs are claims until the tenant deployment namespace, explicit
    binding, and canonical Agent entity all agree. A deployment page is read
    once for the whole requested set so callers can resolve entity-owned sets
    without issuing one tenant-wide scan per agent.
    """
    requested = {value.strip() for value in agent_ids if isinstance(value, str) and value.strip()}
    if not tenant_id or not requested:
        return CanonicalAgentIdentityRead(rows=[])

    identities: dict[tuple[str, str, str], dict[str, Any]] = {}
    direct_ids: set[str] = set()
    scope_mismatch = False

    for agent_id in requested:
        entity = await entities.find_by_id(agent_id)
        if (
            isinstance(entity, dict)
            and entity.get("tenant_id") == tenant_id
            and entity.get("entity_type") == "agent"
            and entity.get("entity_id") == agent_id
        ):
            direct_ids.add(agent_id)
            identities[("canonical_agent_entity", agent_id, agent_id)] = {
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "canonical_agent_entity_id": agent_id,
                "identity_evidence_id": agent_id,
                "identity_evidence_source": "entities",
                "identity_binding_authority": "canonical_agent_entity",
                "identity_bound_at": entity.get("created_at") or entity.get("updated_at"),
            }

    if requested == direct_ids:
        return CanonicalAgentIdentityRead(rows=list(identities.values()))

    raw_deployments, _, truncated = await deployments.list_page(tenant_id, limit=limit)
    if not isinstance(raw_deployments, list):
        raise TypeError("agent deployment source returned an invalid contract")
    if truncated:
        return CanonicalAgentIdentityRead(
            rows=list(identities.values()),
            scope_mismatch=scope_mismatch,
            truncated=True,
        )

    matching: dict[str, list[dict[str, Any]]] = {
        agent_id: [] for agent_id in requested - direct_ids
    }
    for row in raw_deployments:
        if not isinstance(row, dict):
            scope_mismatch = True
            continue
        if row.get("tenant_id") != tenant_id:
            scope_mismatch = True
            continue
        source_ref = row.get("agent_id")
        if isinstance(source_ref, str) and source_ref in matching:
            matching[source_ref].append(row)

    namespaces_by_source: dict[str, set[str]] = {}
    resolved_by_source: dict[str, dict[tuple[str, str, str], dict[str, Any]]] = {}
    for source_ref, source_deployments in matching.items():
        namespaces: set[str] = set()
        for deployment in source_deployments:
            namespace = deployment.get("agent_source_namespace")
            if not isinstance(namespace, str) or not namespace.strip():
                scope_mismatch = True
                continue
            namespace = namespace.strip().lower()
            namespaces.add(namespace)
            bindings = await identity_bindings.find_for_source(tenant_id, namespace, source_ref)
            if len(bindings) != 1:
                if len(bindings) > 1:
                    scope_mismatch = True
                continue
            binding = bindings[0]
            canonical_id = binding.get("canonical_agent_entity_id")
            if (
                binding.get("tenant_id") != tenant_id
                or binding.get("source_namespace") != namespace
                or binding.get("source_agent_ref") != source_ref
                or binding.get("status") != "active"
                or binding.get("binding_authority") != "tenant_admin_explicit"
                or not isinstance(canonical_id, str)
                or not canonical_id
            ):
                scope_mismatch = True
                continue
            canonical_entity = await entities.find_by_id(canonical_id)
            if (
                not isinstance(canonical_entity, dict)
                or canonical_entity.get("tenant_id") != tenant_id
                or canonical_entity.get("entity_type") != "agent"
                or canonical_entity.get("entity_id") != canonical_id
            ):
                scope_mismatch = True
                continue
            identity_key = (namespace, source_ref, canonical_id)
            resolved_by_source.setdefault(source_ref, {})[identity_key] = {
                "tenant_id": tenant_id,
                "agent_id": source_ref,
                "canonical_agent_entity_id": canonical_id,
                "identity_evidence_id": binding.get("id"),
                "identity_evidence_source": "agent_deployment_identity_bindings",
                "identity_binding_authority": "tenant_admin_explicit",
                "identity_bound_at": binding.get("bound_at"),
                "source_namespace": namespace,
            }
        namespaces_by_source[source_ref] = namespaces

    for source_ref, source_identities in resolved_by_source.items():
        expected_namespaces = namespaces_by_source.get(source_ref, set())
        resolved_namespaces = {key[0] for key in source_identities}
        canonical_ids = {key[2] for key in source_identities}
        if (
            not expected_namespaces
            or resolved_namespaces != expected_namespaces
            or len(canonical_ids) != 1
        ):
            scope_mismatch = True
            continue
        identities.update(source_identities)

    return CanonicalAgentIdentityRead(
        rows=list(identities.values()),
        scope_mismatch=scope_mismatch,
        truncated=False,
    )
