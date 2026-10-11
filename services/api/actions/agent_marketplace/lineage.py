"""Tenant-declared source lineage for external agent deployments.

This module does not fetch marketplace pages or verify their claims. It
preserves a bounded source reference and projects it as provenance through the
canonical graph mutation gateway. Runtime capabilities, authorization grants,
and economic outcomes remain separate evidence.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from shared.graph.edge_properties import build_edge_properties
from shared.graph.graph import Edge, EdgeType, Vertex, VertexType
from actions.agent_marketplace.models import AgentMarketplaceOrigin


def _tenant_scoped_id(kind: str, tenant_id: str, *parts: str) -> str:
    material = json.dumps([tenant_id, *parts], ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:40]
    return f"{kind}_{digest}"


def build_marketplace_origin_mutations(deployment: dict[str, Any]) -> list[Any]:
    """Build idempotent graph writes for a declared template origin.

    All source vertices are tenant-scoped. The graph records that the tenant
    declared this lineage; it does not canonicalize the template into an Agent
    or promote catalog labels into authority.
    """
    origin_data = deployment.get("marketplace_origin")
    if not origin_data:
        return []

    origin = AgentMarketplaceOrigin.model_validate(origin_data)
    tenant_id = str(deployment["tenant_id"])
    deployment_id = str(deployment["id"])
    observed_at = str(deployment.get("created_at") or deployment.get("updated_at") or "")
    marketplace_id = _tenant_scoped_id(
        "marketplace", tenant_id, origin.source_namespace
    )
    template_id = _tenant_scoped_id(
        "agent_template",
        tenant_id,
        origin.source_namespace,
        origin.template_ref,
        origin.template_version,
    )
    listing_id = _tenant_scoped_id(
        "agent_listing",
        tenant_id,
        origin.source_namespace,
        origin.listing_ref,
        origin.template_ref,
        origin.template_version,
    )

    # Keep the deployment as a tenant-scoped external node. `agent_id` is a
    # registry reference and may not yet resolve to a canonical Agent vertex;
    # do not create a graph edge that would imply that identity decision.
    mutations: list[Any] = [
        Vertex(
            vertex_type=VertexType.EXTERNAL_AGENTIC_ACCOUNT,
            vertex_id=deployment_id,
            properties={
                "tenant_id": tenant_id,
                "kind": "agent_deployment",
                "agent_reference_authority": "tenant_deployment_registry",
                "external_platform": deployment.get("external_platform"),
            },
        )
    ]
    mutations.extend([
        Vertex(
            vertex_type=VertexType.MARKETPLACE,
            vertex_id=marketplace_id,
            properties={
                "tenant_id": tenant_id,
                "kind": "agent_marketplace_source",
                "source_namespace": origin.source_namespace,
                "assertion": origin.assertion,
            },
        ),
        Vertex(
            vertex_type=VertexType.AGENT_TEMPLATE,
            vertex_id=template_id,
            properties={
                "tenant_id": tenant_id,
                "kind": "marketplace_agent_template_version",
                "source_namespace": origin.source_namespace,
                "template_ref": origin.template_ref,
                "template_version": origin.template_version,
                "catalog_capabilities": origin.catalog_capabilities,
                "assertion": origin.assertion,
            },
        ),
        Vertex(
            vertex_type=VertexType.AGENT_MARKETPLACE_LISTING,
            vertex_id=listing_id,
            properties={
                "tenant_id": tenant_id,
                "kind": "agent_marketplace_listing",
                "source_namespace": origin.source_namespace,
                "listing_ref": origin.listing_ref,
                "template_ref": origin.template_ref,
                "template_version": origin.template_version,
                "listing_url": str(origin.listing_url) if origin.listing_url else None,
                "category": origin.category,
                "assertion": origin.assertion,
            },
        ),
        Edge(
            edge_type=EdgeType.LISTED_ON,
            from_vertex_id=listing_id,
            to_vertex_id=marketplace_id,
            properties=build_edge_properties(
                tenant_id=tenant_id,
                edge_type=EdgeType.LISTED_ON,
                from_vertex_id=listing_id,
                to_vertex_id=marketplace_id,
                actor_kind="system",
                actor_id="agent_deployment_registry",
                provenance="agent_marketplace_lineage",
                valid_from=observed_at,
                confidence=1.0,
                source_event_id=deployment_id,
                assertion=origin.assertion,
            ),
        ),
        Edge(
            edge_type=EdgeType.LISTS_AGENT_TEMPLATE,
            from_vertex_id=listing_id,
            to_vertex_id=template_id,
            properties=build_edge_properties(
                tenant_id=tenant_id,
                edge_type=EdgeType.LISTS_AGENT_TEMPLATE,
                from_vertex_id=listing_id,
                to_vertex_id=template_id,
                actor_kind="system",
                actor_id="agent_deployment_registry",
                provenance="agent_marketplace_lineage",
                valid_from=observed_at,
                confidence=1.0,
                source_event_id=deployment_id,
                assertion=origin.assertion,
            ),
        ),
        Edge(
            edge_type=EdgeType.INSTANCE_OF,
            from_vertex_id=deployment_id,
            to_vertex_id=template_id,
            properties=build_edge_properties(
                tenant_id=tenant_id,
                edge_type=EdgeType.INSTANCE_OF,
                from_vertex_id=deployment_id,
                to_vertex_id=template_id,
                actor_kind="system",
                actor_id="agent_deployment_registry",
                provenance="agent_marketplace_lineage",
                valid_from=observed_at,
                confidence=1.0,
                source_event_id=deployment_id,
                assertion=origin.assertion,
            ),
        ),
    ])
    return mutations
