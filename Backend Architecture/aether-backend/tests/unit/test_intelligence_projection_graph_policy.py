"""Graph-mutation policy tests for the intelligence projection plane (P0.5, group 9).

``graphMutationPolicy`` is per-projection generated metadata the runtime must
honour:

* ``read_only`` — the provider performs NO write. The registry exposes no write
  method, and a read_only provider's ``project()`` completes without invoking
  any mutation gateway.
* ``canonical_gateway_only`` — the provider routes every graph write through
  ``GraphMutationGateway.apply(MutationIntent)`` (the canonical choke point),
  never a direct client write.

The gateway is exercised in a real ``off`` mode and a real ``enforce`` mode
(validated ledger), mirroring ``tests/unit/graph_gateway/``.
"""

from __future__ import annotations

import dataclasses
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from config.settings import settings  # noqa: E402
from repositories.graph_mutation_ledger import (  # noqa: E402
    reset_graph_ledger_memory,
)
from shared.graph.graph import GraphClient, Vertex  # noqa: E402
from shared.graph.mutation_gateway import (  # noqa: E402
    GraphMutationGateway,
    get_mutation_gateway,
)
from shared.graph.mutation_intents import vertex_intent  # noqa: E402
from shared.intelligence_projections import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
    ProviderRegistry,
)


def _request(projection_id: str, *, kind: str = "entity", ident: str = "ent_1") -> ProjectionRequest:
    return ProjectionRequest(
        projectionId=projection_id,
        tenantId="tenant-a",
        subject=ProjectionSubject(kind=kind, id=ident),
    )


def _result(projection_id: str, request: ProjectionRequest, context: object, **overrides: object) -> ProjectionResult:
    values: dict[str, object] = {
        "projectionId": projection_id,
        "tenantId": request.tenantId,
        "contractVersion": INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        "sections": [],
        "claims": [],
        "dependencyState": context.dependencyState,  # type: ignore[attr-defined]
        "generatedAt": "2026-08-23T12:00:00Z",
        "degradedReasons": [],
    }
    values.update(overrides)
    return ProjectionResult(**values)


async def _graph() -> GraphClient:
    client = GraphClient()
    await client.connect()
    return client


@pytest.fixture()
def enforce_mode(monkeypatch) -> str:
    """Pin the gateway mode ladder to ``enforce`` for the duration of a test."""
    monkeypatch.setattr(
        settings,
        "temporal_observatory",
        dataclasses.replace(
            settings.temporal_observatory, mutation_gateway_mode="enforce"
        ),
    )
    return "enforce"


# ---------------------------------------------------------------------------
# graph_mutation_policy() reads the generated definition
# ---------------------------------------------------------------------------

def test_graph_mutation_policy_read_only() -> None:
    registry = ProviderRegistry()
    assert registry.graph_mutation_policy("profile360") == "read_only"
    assert registry.graph_mutation_policy("relationship360") == "read_only"


def test_graph_mutation_policy_canonical_gateway_only() -> None:
    registry = ProviderRegistry()
    # Real canonical_gateway_only ids from the generated registry.
    assert registry.graph_mutation_policy("campaign360") == "canonical_gateway_only"
    assert registry.graph_mutation_policy("connection360") == "canonical_gateway_only"


# ---------------------------------------------------------------------------
# read_only: the provider performs NO write; the registry has no write method
# ---------------------------------------------------------------------------

class _ReadOnlyProfileProvider:
    """profile360 (read_only) provider that only READS canonical truth."""

    projection_id = "profile360"
    contract_version = "1.0.0"

    def __init__(self, graph_client: GraphClient) -> None:
        self._graph = graph_client

    async def project(self, request: ProjectionRequest, context: object) -> ProjectionResult:
        # read_only: the provider never touches a mutation gateway and never
        # writes — it only reads the (canonical) graph.
        vertices = await self._graph.get_all_vertices()
        return _result(
            "profile360",
            request,
            context,
            sections=[
                ProjectionSection(
                    id="state",
                    state="available",
                    content={"vertexCount": len(vertices)},
                )
            ],
        )


@pytest.mark.asyncio
async def test_read_only_provider_performs_no_write() -> None:
    client = await _graph()
    # Seed exactly one vertex (the TEST writes; the provider must not).
    await client.add_vertex(
        Vertex(
            vertex_type="entity",
            vertex_id="seed_1",
            properties={"tenant_id": "tenant-a"},
        )
    )

    registry = ProviderRegistry()
    registry.register(_ReadOnlyProfileProvider(client))

    result = await registry.project("profile360", _request("profile360"))

    # The read completed and reported the seeded vertex.
    assert result.sections[0].content["vertexCount"] == 1
    assert result.degradedReasons == []
    # The provider performed NO write: the graph still holds exactly one vertex.
    assert len(await client.get_all_vertices()) == 1


def test_registry_exposes_no_write_method_on_read_only() -> None:
    registry = ProviderRegistry()
    registry.register(_NoopReadOnlyProvider())
    # The runtime exposes NO write API at all — a read_only projection has no
    # write path to reach through the registry.
    for name in ("apply", "apply_mutation", "mutate", "write", "project_mutation"):
        assert not hasattr(registry, name)


class _NoopReadOnlyProvider:
    projection_id = "profile360"
    contract_version = "1.0.0"

    async def project(self, request: ProjectionRequest, context: object) -> ProjectionResult:
        return _result("profile360", request, context)


# ---------------------------------------------------------------------------
# canonical_gateway_only: the provider routes its write through the gateway
# ---------------------------------------------------------------------------

class _CanonicalGatewayProvider:
    """campaign360 (canonical_gateway_only) provider that writes via the gateway."""

    projection_id = "campaign360"
    contract_version = "1.0.0"

    def __init__(self, gateway: GraphMutationGateway | None = None) -> None:
        # Real providers default to the module-level gateway; tests inject one.
        self._gateway = gateway or get_mutation_gateway()
        self.applied = 0

    async def project(self, request: ProjectionRequest, context: object) -> ProjectionResult:
        # canonical_gateway_only: EVERY write goes through
        # GraphMutationGateway.apply(MutationIntent) — never a direct client call.
        vertex = Vertex(
            vertex_type="campaign",
            vertex_id=f"campaign_{request.subject.id}",
            properties={
                "tenant_id": request.tenantId,
                "name": request.subject.id,
            },
        )
        intent = vertex_intent(
            vertex,
            operation="node_created",
            tenant_id=request.tenantId,
            actor_kind="system",
        )
        outcome = await self._gateway.apply(intent)
        self.applied += 1
        return _result(
            "campaign360",
            request,
            context,
            sections=[
                ProjectionSection(
                    id="state",
                    state="available",
                    content={
                        "mode": outcome.mode,
                        "applied": outcome.applied,
                    },
                )
            ],
        )


@pytest.mark.asyncio
async def test_canonical_gateway_only_write_routes_through_gateway_off_mode() -> None:
    client = await _graph()
    gateway = GraphMutationGateway(graph_client=client)  # default ladder: off
    provider = _CanonicalGatewayProvider(gateway)
    registry = ProviderRegistry()
    registry.register(provider)

    result = await registry.project(
        "campaign360", _request("campaign360", kind="campaign", ident="cmp_1")
    )

    # The provider invoked the gateway exactly once.
    assert provider.applied == 1
    # The write went through gateway.apply: the vertex is now projected.
    vertices = await client.get_all_vertices()
    assert [v.vertex_id for v in vertices] == ["campaign_cmp_1"]
    assert result.sections[0].content["mode"] == "off"
    assert result.sections[0].content["applied"] is True
    assert result.degradedReasons == []


@pytest.mark.asyncio
async def test_canonical_gateway_only_write_routes_through_gateway_enforce_mode(
    enforce_mode,
) -> None:
    reset_graph_ledger_memory()
    try:
        client = await _graph()
        gateway = GraphMutationGateway(graph_client=client)
        provider = _CanonicalGatewayProvider(gateway)
        registry = ProviderRegistry()
        registry.register(provider)

        result = await registry.project(
            "campaign360", _request("campaign360", kind="campaign", ident="cmp_2")
        )

        # The write went through the gateway's enforce pipeline (validated +
        # ledgered) and landed on the projected graph.
        assert provider.applied == 1
        assert result.sections[0].content["mode"] == "enforce"
        assert result.sections[0].content["applied"] is True
        vertices = await client.get_all_vertices()
        assert [v.vertex_id for v in vertices] == ["campaign_cmp_2"]
    finally:
        reset_graph_ledger_memory()
