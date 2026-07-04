"""Foundation helpers for agentic observability route correctness.

These helpers keep PR-1 semantics explicit until the durable graph outbox lands:
accepted observations are persisted even when graph projection fails, and API
responses report built/persisted mutation counts truthfully.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, Request, status

from services.ingestion.generated_registry import CANONICAL_EVENT_TYPES
from shared.graph.graph import Edge, Vertex
from shared.logger.logger import get_logger

logger = get_logger("aether.agentic_observability.foundation")

CANONICAL_GRAPH_TENANT_PROPERTY = "tenantId"


@dataclass
class GraphProjectionResult:
    graph_mutations_built: int = 0
    graph_mutations_persisted: int = 0
    graph_projection_status: str = "not_applicable"
    graph_projection_errors: list[str] = field(default_factory=list)


def active_tenant_id(request: Request) -> str:
    tenant = getattr(request.state, "tenant", None)
    if not tenant:
        raise HTTPException(status_code=401, detail="Missing tenant context")
    return tenant.tenant_id


def require_permission(request: Request, perm: str) -> None:
    tenant = getattr(request.state, "tenant", None)
    if not tenant:
        raise HTTPException(status_code=401, detail="Missing tenant context")
    if hasattr(tenant, "require_permission"):
        try:
            tenant.require_permission(perm)
            return
        except Exception as e:  # permission adapters expose typed and untyped failures
            raise HTTPException(status_code=403, detail=str(e)) from e
    if hasattr(tenant, "has_permission") and not tenant.has_permission(perm):
        raise HTTPException(status_code=403, detail=f"Permission denied: {perm}")


def validate_payload_tenant(payload: Any, tenant_id: str) -> None:
    data = payload if isinstance(payload, dict) else payload.model_dump()
    claimed = data.get("tenant_id") or data.get("tenantId")
    if claimed and claimed != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="tenant_id mismatch: authenticated tenant context is authoritative",
        )


def validate_event_name(event_name: str) -> None:
    if event_name not in CANONICAL_EVENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown event_name {event_name!r}; use a canonical event registry value",
        )


def check_no_execution(payload: Any) -> None:
    data = payload if isinstance(payload, dict) else payload.model_dump()
    if data.get("execution_by_aether") is True:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="execution_by_aether must be false. AETHER observes; it does not execute external actions.",
        )
    economics = data.get("economics")
    if isinstance(economics, dict) and economics.get("is_execution_by_aether") is True:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="economics.is_execution_by_aether must be false. AETHER observes; it does not execute external actions.",
        )


def normalize_graph_tenant_properties(mutations: list[Any], tenant_id: str) -> list[Any]:
    for mutation in mutations:
        props = getattr(mutation, "properties", None)
        if isinstance(props, dict):
            props[CANONICAL_GRAPH_TENANT_PROPERTY] = tenant_id
            props.setdefault("tenant_id", tenant_id)  # legacy readers until graph contract migration completes
            if props.get("tenant_id") != tenant_id or props.get("tenantId") != tenant_id:
                raise HTTPException(status_code=500, detail="Graph mutation tenant normalization failed")
    return mutations


async def persist_mutations(mutations: list[Any], *, tenant_id: str, trace_id: str | None = None) -> GraphProjectionResult:
    mutations = normalize_graph_tenant_properties(mutations, tenant_id)
    result = GraphProjectionResult(graph_mutations_built=len(mutations))
    if not mutations:
        return result
    try:
        from dependencies.providers import get_graph
        graph = get_graph()
        for mutation in mutations:
            if isinstance(mutation, Vertex):
                await graph.add_vertex(mutation)
                result.graph_mutations_persisted += 1
            elif isinstance(mutation, Edge):
                await graph.add_edge(mutation)
                result.graph_mutations_persisted += 1
        result.graph_projection_status = "persisted" if result.graph_mutations_persisted == len(mutations) else "partial"
    except Exception as exc:
        result.graph_projection_status = "failed"
        result.graph_projection_errors.append(type(exc).__name__)
        logger.warning(
            "agentic graph projection failed",
            extra={"tenant_id": tenant_id, "trace_id": trace_id, "error": str(exc), "built": len(mutations)},
        )
    return result
