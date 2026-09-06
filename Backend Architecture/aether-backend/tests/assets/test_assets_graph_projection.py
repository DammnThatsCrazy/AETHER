"""Universal asset registry → graph reference projector — DB-free tests.

Seeds the registry in-memory (typed repos fall back to shared stores), projects
the canonical rows onto a fresh in-memory GraphClient and asserts the GLOBAL
reference surface: every canonical asset / fiat currency / chain / deployment
row becomes one platform-scoped reference vertex, every deployment whose chain
row is present becomes one DEPLOYED_ON_CHAIN edge, re-projection is idempotent,
the surface classifies as RelationshipLayer.EXCLUDED (never H2H/H2A/A2H/A2A),
and nothing leaks into a consumer tenant. Present-but-no-op builders (issuer /
venue / bridge / price provider / alias) are asserted to project nothing, and
the seeder's default-OFF gate is asserted (no graph writes without opt-in).

Pure builders are DB-shaped-row functions; integration tests read repo rows back
exactly as the registry stored them (asset_id/iso_code/chain_id keys).
"""

from __future__ import annotations

import pytest

from repositories.typed_repo import reset_typed_in_memory_stores
from services.assets import seeds
from services.assets.graph_projector import (
    PLATFORM_TENANT,
    asset_vertex_id,
    build_all_from_registry,
    chain_vertex_id,
    deployment_vertex_id,
    fiat_vertex_id,
    project_alias_mutations,
    project_all_from_registry,
    project_asset_mutations,
    project_bridge_mutations,
    project_chain_mutations,
    project_deployment_mutations,
    project_fiat_mutations,
    project_issuer_mutations,
    project_price_provider_mutations,
    project_venue_mutations,
)
from services.assets.registry import UniversalAssetRegistry
from services.assets.seeder import UniversalAssetSeeder
from shared.graph.edge_properties import REQUIRED_EDGE_PROPERTIES
from shared.graph.economic_schema import get_edge_schema, get_vertex_schema
from shared.graph.graph import (
    EdgeType,
    GraphClient,
    Vertex,
    VertexType,
    _InMemoryGraphBackend,
)
from shared.graph.graph_contract import get_layer_for_edge
from shared.graph.relationship_layers import RelationshipLayer, classify_edge_type
from shared.graph.write_validator import GraphWriteValidator

# ── fixtures / helpers ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_typed_stores():
    reset_typed_in_memory_stores()
    yield
    reset_typed_in_memory_stores()


async def _seeded_registry() -> UniversalAssetRegistry:
    """A fully seeded registry (seed-only; projection is never auto-run)."""
    registry = UniversalAssetRegistry()
    await registry.seed_all()
    return registry


def _expected_vertex_counts() -> dict[str, int]:
    """Reference vertices the W2 canonical seed substantiates."""
    assets = (
        len(seeds.fiat_asset_rows())
        + len(seeds.native_asset_rows())
        + len(seeds.stablecoin_asset_rows())
    )
    return {
        VertexType.ASSET: assets,
        VertexType.FIAT_CURRENCY: len(seeds.fiat_currency_rows()),
        VertexType.CHAIN: len(seeds.chain_rows()),
        VertexType.ASSET_DEPLOYMENT: len(seeds.native_deployment_rows()) + len(seeds.stablecoin_deployment_rows()),
    }


async def _all_deposited_edges(graph: GraphClient) -> list:
    """Every DEPLOYED_ON_CHAIN edge reachable from a projected deployment."""
    edges: list = []
    for vertex in await graph.get_all_vertices(limit=10000):
        if vertex.vertex_type == VertexType.ASSET_DEPLOYMENT:
            edges.extend(await graph.get_edges(
                vertex.vertex_id,
                edge_type=EdgeType.DEPLOYED_ON_CHAIN,
                direction="out",
                include_revoked=True,
            ))
    return edges


# ── pure builders ─────────────────────────────────────────────────────────────

def test_project_asset_mutations_scheme_and_platform_tenant():
    row = {"asset_id": "stablecoin:USDC", "kind": "stablecoin", "symbol": "USDC",
           "name": "USD Coin", "issuer": "Circle", "display_decimals": 6, "status": "active"}
    vertices, edges = project_asset_mutations(row, registry_version="abc123")
    assert edges == []
    assert len(vertices) == 1
    vertex = vertices[0]
    assert vertex.vertex_id == asset_vertex_id("stablecoin:USDC") == "asset:stablecoin:USDC"
    assert vertex.vertex_type == VertexType.ASSET
    assert vertex.properties["tenant_id"] == PLATFORM_TENANT
    assert vertex.properties["canonical_asset_id"] == "stablecoin:USDC"
    assert vertex.properties["kind"] == "stablecoin"
    assert vertex.properties["registry_version"] == "abc123"
    assert vertex.properties["symbol"] == "USDC"
    assert vertex.properties["issuer"] == "Circle"


def test_project_asset_mutations_omits_none_props_and_versions():
    row = {"asset_id": "crypto:ETH", "kind": "crypto", "symbol": "ETH",
           "name": None, "issuer": None, "display_decimals": 18, "status": "active"}
    vertices, _ = project_asset_mutations(row)  # no registry_version stamp
    props = vertices[0].properties
    assert "registry_version" not in props
    assert "name" not in props and "issuer" not in props
    assert props["display_decimals"] == 18


def test_project_chain_mutations_id_and_props():
    row = {"chain_id": "eip155:8453", "name": "Base", "network": "mainnet",
           "status": "active", "vm": "evm", "native_currency": "crypto:ETH"}
    vertices, edges = project_chain_mutations(row)
    assert edges == [] and len(vertices) == 1
    vertex = vertices[0]
    assert vertex.vertex_id == chain_vertex_id("eip155:8453") == "chain:eip155:8453"
    assert vertex.vertex_type == VertexType.CHAIN
    assert vertex.properties["chain_id"] == "eip155:8453"
    assert vertex.properties["native_currency"] == "crypto:ETH"
    assert vertex.properties["tenant_id"] == PLATFORM_TENANT


def test_project_fiat_mutations_iso_vertex():
    row = {"iso_code": "USD", "numeric_code": "840", "minor_units": 2,
           "name": "US Dollar", "symbol": "$"}
    vertices, edges = project_fiat_mutations(row)
    assert edges == [] and len(vertices) == 1
    vertex = vertices[0]
    assert vertex.vertex_id == fiat_vertex_id("USD") == "fiat:USD"
    assert vertex.vertex_type == VertexType.FIAT_CURRENCY
    assert vertex.properties["iso_code"] == "USD"
    assert vertex.properties["numeric_code"] == "840"
    assert vertex.properties["canonical_asset_id"] == "fiat:USD"


def test_project_deployment_mutations_vertex_and_deposited_on_chain_edge():
    row = {"deployment_id": "deploy:stablecoin:USDC@eip155:8453:0xabc",
           "asset_id": "stablecoin:USDC", "chain_id": "eip155:8453",
           "contract_or_mint": "0xabc", "decimals": 6,
           "canonical_vs_bridged": "canonical", "deployment_status": "active",
           "token_standard": "erc20"}
    vertices, edges = project_deployment_mutations(row)
    assert len(vertices) == 1 and len(edges) == 1
    vertex = vertices[0]
    assert vertex.vertex_id == deployment_vertex_id(row["deployment_id"]) == row["deployment_id"]
    assert vertex.vertex_type == VertexType.ASSET_DEPLOYMENT
    assert vertex.properties["canonical_asset_id"] == "stablecoin:USDC"
    assert vertex.properties["chain_id"] == "eip155:8453"

    edge = edges[0]
    assert edge.edge_type == EdgeType.DEPLOYED_ON_CHAIN
    assert edge.from_vertex_id == row["deployment_id"]
    assert edge.to_vertex_id == "chain:eip155:8453"
    assert edge.properties["tenant_id"] == PLATFORM_TENANT
    assert edge.properties["actor_id"] == "universal_asset_seeder"
    assert edge.properties["actor_kind"] == "system"
    assert edge.properties["canonical_vs_bridged"] == "canonical"
    assert edge.properties["deployment_status"] == "active"


def test_deployment_edge_actor_kind_passes_strict_write_validator():
    # MEDIUM-4 regression: the graph's EDGE actor-kind vocabulary is
    # {human, agent, system} (edge_properties.VALID_ACTOR_KINDS), and
    # GraphClient.add_edge raises GraphWriteValidationError in Neptune mode for
    # an out-of-vocabulary actor_kind (e.g. "service"). A platform reference
    # seeder projects as a "system" actor, so the edge must pass the validator
    # under env="production" — never just lenient local/test logging.
    row = {"deployment_id": "deploy:stablecoin:USDC@eip155:8453:0xabc",
           "asset_id": "stablecoin:USDC", "chain_id": "eip155:8453",
           "contract_or_mint": "0xabc", "decimals": 6,
           "canonical_vs_bridged": "canonical", "deployment_status": "active",
           "token_standard": "erc20"}
    _vertices, edges = project_deployment_mutations(row)
    result = GraphWriteValidator().validate(edges[0], env="production")
    assert result.passed, result.violations
    assert edges[0].properties["actor_kind"] == "system"


def test_deployment_edge_carries_required_and_schema_properties():
    row = {"deployment_id": "deploy:crypto:SOL@solana:mainnet:EPjF",
           "asset_id": "crypto:SOL", "chain_id": "solana:mainnet",
           "contract_or_mint": "EPjF", "decimals": 9,
           "canonical_vs_bridged": "canonical", "deployment_status": "active",
           "token_standard": "native"}
    _vertices, edges = project_deployment_mutations(row)
    edge = edges[0]
    props = edge.properties
    assert REQUIRED_EDGE_PROPERTIES <= set(props)  # required edge property set present
    schema = get_edge_schema(EdgeType.DEPLOYED_ON_CHAIN)
    assert schema is not None and schema.creation_path == "assets.deployment_projection"
    for key in ("contract_or_mint", "decimals", "canonical_vs_bridged", "deployment_status"):
        assert key in props


def test_vertex_id_scheme_is_namespaced_and_collision_free():
    # Asset facet (asset:<canonical id>) and the fiat ISO facet (fiat:<iso>) for
    # the same USD currency are distinct vertex ids — no collision.
    assert asset_vertex_id("fiat:USD") != fiat_vertex_id("USD")
    assert asset_vertex_id("crypto:ETH") != chain_vertex_id("eip155:8453")
    deployment = "deploy:stablecoin:USDC@eip155:8453:0xabc"
    assert deployment_vertex_id(deployment) == deployment
    ids = {
        asset_vertex_id("fiat:USD"), asset_vertex_id("crypto:ETH"),
        fiat_vertex_id("USD"), chain_vertex_id("eip155:8453"), deployment,
    }
    assert len(ids) == 5


def test_asset_and_fiat_facets_are_separate_vertices_for_usd():
    fiat_vertices, _ = project_fiat_mutations(
        {"iso_code": "USD", "numeric_code": "840", "minor_units": 2,
         "name": "US Dollar", "symbol": "$"}
    )
    asset_vertices, _ = project_asset_mutations(
        {"asset_id": "fiat:USD", "kind": "fiat", "symbol": "USD",
         "name": "US Dollar", "display_decimals": 2, "status": "active"}
    )
    assert fiat_vertices[0].vertex_id == "fiat:USD"
    assert fiat_vertices[0].vertex_type == VertexType.FIAT_CURRENCY
    assert asset_vertices[0].vertex_id == "asset:fiat:USD"
    assert asset_vertices[0].vertex_type == VertexType.ASSET


def test_present_but_noop_projectors_project_nothing():
    # Issuer / venue / bridge / price-provider reference types are registered in
    # economic_schema but the W2 seed has no rows for them; alias rows have no
    # registered graph surface. All five builders must be present-but-no-op.
    assert project_issuer_mutations({"id": "circle"}) == ([], [])
    assert project_venue_mutations({"venue_id": "coinbase"}) == ([], [])
    assert project_bridge_mutations({"bridge_id": "wbtc"}) == ([], [])
    assert project_price_provider_mutations({"provider_id": "chainlink"}) == ([], [])
    alias_row = {"alias": "usdc", "target_asset_id": "stablecoin:USDC",
                 "target_deployment_id": None, "verification": "verified"}
    assert project_alias_mutations(alias_row) == ([], [])


# ── build_all_from_registry (pure whole-registry composition) ───────────────

@pytest.mark.asyncio
async def test_build_all_from_registry_projects_reference_surface():
    registry = await _seeded_registry()
    projection = await build_all_from_registry(registry)

    expected = _expected_vertex_counts()
    by_type: dict[str, int] = {}
    for vertex in projection.vertices:
        by_type[vertex.vertex_type] = by_type.get(vertex.vertex_type, 0) + 1
    assert by_type == expected
    assert projection.vertex_count == sum(expected.values()) == 46
    assert projection.edge_count == len(seeds.native_deployment_rows()) + len(seeds.stablecoin_deployment_rows()) == 7
    assert all(edge.edge_type == EdgeType.DEPLOYED_ON_CHAIN for edge in projection.edges)


@pytest.mark.asyncio
async def test_build_all_vertices_carry_registry_version_provenance():
    registry = await _seeded_registry()
    projection = await build_all_from_registry(registry)
    version = registry.current_registry_version()
    assert projection.registry_version == version
    for vertex in projection.vertices:
        assert vertex.properties["registry_version"] == version
        assert vertex.properties["tenant_id"] == PLATFORM_TENANT


@pytest.mark.asyncio
async def test_build_all_is_deterministic_across_runs():
    registry = await _seeded_registry()
    first = await build_all_from_registry(registry)
    second = await build_all_from_registry(registry)
    assert [v.vertex_id for v in first.vertices] == [v.vertex_id for v in second.vertices]
    assert [(e.from_vertex_id, e.edge_type, e.to_vertex_id) for e in first.edges] == [
        (e.from_vertex_id, e.edge_type, e.to_vertex_id) for e in second.edges
    ]


@pytest.mark.asyncio
async def test_build_all_only_projects_edges_to_projected_chains():
    registry = await _seeded_registry()
    projection = await build_all_from_registry(registry)
    chain_ids = {v.properties["chain_id"] for v in projection.vertices if v.vertex_type == VertexType.CHAIN}
    for edge in projection.edges:
        # Every DEPLOYED_ON_CHAIN target resolves to a projected Chain vertex.
        assert edge.to_vertex_id in {chain_vertex_id(c) for c in chain_ids}


@pytest.mark.asyncio
async def test_build_all_empty_registry_projects_nothing():
    projection = await build_all_from_registry(UniversalAssetRegistry())
    assert projection.vertex_count == 0 and projection.edge_count == 0


@pytest.mark.asyncio
async def test_projected_vertex_types_conform_to_reference_schema():
    registry = await _seeded_registry()
    projection = await build_all_from_registry(registry)
    for vertex in projection.vertices:
        schema = get_vertex_schema(vertex.vertex_type)
        assert schema is not None, vertex.vertex_type
        # Reference vertices are GLOBAL — never tenant-scoped, never actor-layer.
        assert schema.tenant_scoped is False
        assert schema.owner_service == "assets"
        assert schema.provenance_event.startswith("registry.")


# ── project_all_from_registry (persist seam, in-memory graph) ────────────────

@pytest.mark.asyncio
async def test_project_all_persists_global_reference_surface():
    registry = await _seeded_registry()
    graph = GraphClient()
    result = await project_all_from_registry(registry, graph=graph)

    assert result.status == "persisted"
    assert result.vertices_persisted == 46
    assert result.edges_persisted == 7

    vertices = await graph.get_all_vertices(limit=10000)
    assert len(vertices) == 46
    by_type: dict[str, int] = {}
    for vertex in vertices:
        by_type[vertex.vertex_type] = by_type.get(vertex.vertex_type, 0) + 1
    assert by_type == _expected_vertex_counts()

    assert len(await _all_deposited_edges(graph)) == 7


@pytest.mark.asyncio
async def test_project_all_is_idempotent_no_duplicate_edges():
    registry = await _seeded_registry()
    graph = GraphClient()
    first = await project_all_from_registry(registry, graph=graph)
    assert first.status == "persisted"

    second = await project_all_from_registry(registry, graph=graph)
    assert second.status == "up_to_date"
    assert second.vertices_persisted == 0 and second.edges_persisted == 0
    assert second.vertices_skipped == 46 and second.edges_skipped == 7

    # No duplicate edges, no duplicate vertices after the replay.
    assert len(await graph.get_all_vertices(limit=10000)) == 46
    edges = await _all_deposited_edges(graph)
    assert len(edges) == 7
    tuples = {(e.from_vertex_id, e.to_vertex_id) for e in edges}
    assert len(tuples) == 7  # one DEPLOYED_ON_CHAIN per deployment


@pytest.mark.asyncio
async def test_project_all_rewrites_changed_vertex_in_place_then_converges():
    # HIGH-1 regression: when a vertex's content changes (a registry edit), the
    # re-projection must rewrite EXACTLY that vertex in place (gateway
    # node_versioned → upsert_vertex) and then converge — it must not re-addV,
    # and it must not churn on every subsequent run.
    registry = await _seeded_registry()
    version = registry.current_registry_version()
    graph = GraphClient()
    first = await project_all_from_registry(registry, graph=graph, registry_version=version)
    assert first.vertices_persisted == 46 and first.edges_persisted == 7

    # Mutate one economic fact in place (identity unchanged).
    assert await registry.assets.update_by_key(
        {"asset_id": "stablecoin:USDC"}, {"display_decimals": 8},
    ) is True

    changed = await project_all_from_registry(registry, graph=graph, registry_version=version)
    assert changed.vertices_persisted == 1  # only the USDC asset vertex differs
    assert changed.vertices_skipped == 45
    assert changed.edges_persisted == 0 and changed.edges_skipped == 7

    stored = await graph.get_vertex(asset_vertex_id("stablecoin:USDC"))
    assert stored is not None
    assert stored.properties["display_decimals"] == 8
    assert len(await graph.get_all_vertices(limit=10000)) == 46  # no duplicates

    settled = await project_all_from_registry(registry, graph=graph, registry_version=version)
    assert settled.status == "up_to_date"
    assert settled.vertices_persisted == 0 and settled.vertices_skipped == 46


class _StringTypedNeptuneLikeBackend(_InMemoryGraphBackend):
    """Simulate the Neptune backend for the projector's idempotency contract.

    Faithful to graph.py's _NeptuneGraphBackend: every property is persisted as
    ``str(v)`` and read back as a string, and ``add_vertex`` is a PURE insert —
    re-adding an existing vertex id aborts (it must never be called on a vertex
    that already exists).
    """

    async def add_vertex(self, vertex: Vertex) -> str:
        if vertex.vertex_id in self._vertices:
            raise RuntimeError(
                f"duplicate addV on existing vertex id {vertex.vertex_id}"
            )
        self._vertices[vertex.vertex_id] = Vertex(
            vertex.vertex_type,
            vertex.vertex_id,
            properties={k: str(v) for k, v in (vertex.properties or {}).items()},
        )
        return vertex.vertex_id

    async def upsert_vertex(self, vertex: Vertex) -> str:
        incoming = {k: str(v) for k, v in (vertex.properties or {}).items()}
        existing = self._vertices.get(vertex.vertex_id)
        if existing is not None:
            existing.properties.update(incoming)
        else:
            self._vertices[vertex.vertex_id] = Vertex(
                vertex.vertex_type, vertex.vertex_id, properties=incoming,
            )
        return vertex.vertex_id


def _neptune_like_graph() -> GraphClient:
    graph = GraphClient()
    graph._backend = _StringTypedNeptuneLikeBackend()  # type: ignore[attr-defined]
    graph._connected = True  # type: ignore[attr-defined]
    graph._mode = "neptune"  # type: ignore[attr-defined]  # strict edge validation
    return graph


@pytest.mark.asyncio
async def test_project_all_idempotent_on_string_typed_storage_without_duplicate_addv():
    # HIGH-1 regression: Neptune reads every property back as a string, so a
    # Python-typed property comparison (int 6 != "6") previously reported every
    # int-bearing vertex as "not current" and re-issued node_created — which
    # aborts as a duplicate addV on Neptune. Re-projection on string-typed
    # storage must converge to up_to_date with zero duplicate-addV attempts.
    registry = await _seeded_registry()
    graph = _neptune_like_graph()
    first = await project_all_from_registry(registry, graph=graph)
    assert first.vertices_persisted == 46 and first.edges_persisted == 7

    second = await project_all_from_registry(registry, graph=graph)
    assert second.status == "up_to_date"
    assert second.vertices_persisted == 0 and second.vertices_skipped == 46
    assert second.edges_persisted == 0 and second.edges_skipped == 7
    assert len(await graph.get_all_vertices(limit=10000)) == 46


@pytest.mark.asyncio
async def test_project_all_rewrite_on_string_typed_storage_converges():
    # Combined HIGH-1 path: content change on string-typed storage is rewritten
    # via node_versioned (upsert, not addV) and then a later run is up_to_date.
    registry = await _seeded_registry()
    version = registry.current_registry_version()
    graph = _neptune_like_graph()
    await project_all_from_registry(registry, graph=graph, registry_version=version)
    await registry.assets.update_by_key(
        {"asset_id": "stablecoin:USDC"}, {"display_decimals": 8},
    )

    changed = await project_all_from_registry(registry, graph=graph, registry_version=version)
    assert changed.vertices_persisted == 1 and changed.vertices_skipped == 45
    stored = await graph.get_vertex(asset_vertex_id("stablecoin:USDC"))
    assert stored.properties["display_decimals"] == "8"

    settled = await project_all_from_registry(registry, graph=graph, registry_version=version)
    assert settled.status == "up_to_date" and settled.vertices_persisted == 0


@pytest.mark.asyncio
async def test_projected_rows_are_platform_scoped_never_consumer_tenant():
    registry = await _seeded_registry()
    graph = GraphClient()
    await project_all_from_registry(registry, graph=graph)

    platform = await graph.get_vertices_for_tenant(PLATFORM_TENANT)
    assert len(platform) == 46
    # No consumer tenant sees any reference row (reference layer is not
    # tenant-mutable and no reference write is tenant-scoped).
    assert await graph.get_vertices_for_tenant("tenant-alpha") == []
    assert await graph.get_vertices_for_tenant("tenant-beta") == []


@pytest.mark.asyncio
async def test_projected_edges_are_excluded_never_counted_in_actor_layers():
    registry = await _seeded_registry()
    projection = await build_all_from_registry(registry)
    for edge in projection.edges:
        assert classify_edge_type(edge.edge_type) == RelationshipLayer.EXCLUDED
        assert get_layer_for_edge(edge.edge_type) == RelationshipLayer.EXCLUDED
    # The projected vertex types are reference types — none is an actor-layer
    # subject vertex (ASSET/CHAIN/FiatCurrency/AssetDeployment).
    types = {v.vertex_type for v in projection.vertices}
    assert types == {
        VertexType.ASSET, VertexType.CHAIN,
        VertexType.FIAT_CURRENCY, VertexType.ASSET_DEPLOYMENT,
    }


@pytest.mark.asyncio
async def test_deposited_edges_connect_deployment_to_chain_vertices():
    registry = await _seeded_registry()
    graph = GraphClient()
    await project_all_from_registry(registry, graph=graph)

    edges = await _all_deposited_edges(graph)
    for edge in edges:
        deployment = await graph.get_vertex(edge.from_vertex_id)
        chain = await graph.get_vertex(edge.to_vertex_id)
        assert deployment is not None and deployment.vertex_type == VertexType.ASSET_DEPLOYMENT
        assert chain is not None and chain.vertex_type == VertexType.CHAIN
        assert edge.to_vertex_id == chain_vertex_id(deployment.properties["chain_id"])


@pytest.mark.asyncio
async def test_project_all_empty_registry_is_noop():
    result = await project_all_from_registry(UniversalAssetRegistry(), graph=GraphClient())
    assert result.status == "no_mutations"
    assert result.vertices_built == 0 and result.edges_built == 0
    assert result.vertices_persisted == 0 and result.edges_persisted == 0


@pytest.mark.asyncio
async def test_seeded_registry_does_not_auto_project_reference_edges():
    # Honest state: the W2 seed substantiates ONLY deployment→chain reference
    # edges. No reference edge type that needs a non-seeded subject row
    # (payment/settlement/instrument/issuer/valuation rows) is fabricated.
    registry = await _seeded_registry()
    projection = await build_all_from_registry(registry)
    produced = {edge.edge_type for edge in projection.edges}
    assert produced == {EdgeType.DEPLOYED_ON_CHAIN}


# ── seeder gate (default-OFF, opt-in projection) ─────────────────────────────

@pytest.mark.asyncio
async def test_seeder_default_off_projects_nothing():
    registry = UniversalAssetRegistry()
    seeder = UniversalAssetSeeder(registry=registry)  # no graph_enabled → settings default (False)
    summary = await seeder.seed_all()
    assert "graph_projection" not in summary
    assert await registry.get_meta() is None  # meta is written by the facade, not the seeder


@pytest.mark.asyncio
async def test_seeder_graph_enabled_projects_and_is_idempotent():
    registry = UniversalAssetRegistry()
    graph = GraphClient()
    summary = await UniversalAssetSeeder(
        registry=registry, graph_enabled=True, graph=graph,
    ).seed_all()

    projection = summary["graph_projection"]
    assert projection["status"] == "persisted"
    assert projection["vertices_persisted"] == 46
    assert projection["edges_persisted"] == 7
    assert projection["registry_version"] == registry.current_registry_version()
    assert len(await graph.get_all_vertices(limit=10000)) == 46

    # A re-seed through an opt-in seeder against the same registry is idempotent
    # (rows already exist; projection reports up-to-date, nothing re-written).
    replay = await UniversalAssetSeeder(
        registry=registry, graph_enabled=True, graph=graph,
    ).seed_all()
    assert replay["graph_projection"]["status"] == "up_to_date"
    assert replay["graph_projection"]["vertices_persisted"] == 0
    assert replay["graph_projection"]["edges_persisted"] == 0
    assert len(await _all_deposited_edges(graph)) == 7
