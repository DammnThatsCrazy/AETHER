"""Universal asset registry → graph reference projector (financial-normalization
WP3, lane C3-GRAPH-PROJECTOR).

Turns canonical rows in the universal asset registry (services/assets) into
GLOBAL reference vertices/edges on the graph's non-actor reference layer —
mirroring the stablecoin-domain projection precedent in
``services/stablecoin/graph_mutations.py``. Reference vertices/edges live on
RelationshipLayer.EXCLUDED (never H2H/H2A/A2H/A2A) and carry the platform
tenant ("platform"): tenant-owned records reference them by id, but the
reference layer itself is not tenant-mutable.

Scope — project only what registry rows substantiate:

  Projected today (the W2 canonical seed has rows for these):
    - Asset vertices          ← registry_assets rows of every kind (fiat /
                                crypto / stablecoin / token). The economic
                                schema's Asset entry explicitly names fiat as a
                                canonical asset kind, so a fiat currency has an
                                ``asset:fiat:USD`` Asset vertex (the canonical
                                asset facet) in addition to its ISO reference
                                facet below.
    - FiatCurrency vertices   ← registry_fiat_currencies (ISO-4217 metadata)
    - Chain vertices          ← registry_chains
    - AssetDeployment vertices + DEPLOYED_ON_CHAIN edges ←
                                registry_asset_deployments

  Present-but-no-op today (registered in economic_schema but the W2 seed has no
  issuer / venue / bridge / price-provider rows, and alias rows have no
  registered graph surface): project_issuer_mutations / project_venue_mutations /
  project_bridge_mutations / project_price_provider_mutations /
  project_alias_mutations. They return empty and document why — they are kept so
  the projector surface is complete as those registries gain rows.

Determinism / idempotency:
  - Vertex ids are deterministic functions of canonical registry ids
    (``asset:<asset_id>``, ``chain:<chain_id>``, ``fiat:<iso_code>``, and the
    deployment_id verbatim for AssetDeployment vertices).
  - Re-running against the same registry is idempotent: vertices whose type +
    properties already exist are not rewritten, and a DEPLOYED_ON_CHAIN edge is
    only written when no edge already connects that (deployment, chain) pair —
    so re-projection never duplicates and never churns ``created_at``.
  - Vertices carry the deterministic ``registry_version`` provenance so a seed
    change rewrites exactly the affected reference vertices. A content change is
    projected as ``node_versioned`` (the gateway's upsert path) — never a
    second ``addV`` on an existing vertex id — and the idempotency comparison is
    storage-spelling neutral (string-normalised), so an int 6 in a build is
    recognised as already-present against a Neptune ``"6"`` read-back.

Projection is NOT live by default: the seeder only invokes
:func:`project_all_from_registry` when the caller (or
``settings.assets.graph_enabled`` / ``AETHER_ASSETS_GRAPH_ENABLED``) opts in.
This module only writes GLOBAL reference rows — it never originates, settles,
or touches a tenant-scoped record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from shared.graph.edge_properties import build_edge_properties
from shared.graph.graph import (
    TENANT_PROPERTY,
    Edge,
    EdgeType,
    Vertex,
    VertexType,
    get_graph_client,
)

# The platform tenant is the canonical home of GLOBAL reference rows (mirrors
# stablecoin graph_mutations' platform-tenant precedent and the registry's own
# _PLATFORM_TENANT sentinel). "platform" is never a consumer tenant.
PLATFORM_TENANT = "platform"

# Provenance/actor metadata stamped on every projected reference write.
_PROVENANCE = "universal_asset_registry"
_ACTOR_ID = "universal_asset_seeder"
_TENANT_ID_SPELLING = "tenant_id"  # legacy reader spelling; see graph.py TENANT_PROPERTY

# How many rows a repo read may return at most. Registry sizes are reference
# scale (tens to low thousands); a hard cap keeps the projector bounded.
_READ_LIMIT = 10_000


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Vertex-id scheme ──────────────────────────────────────────────────────────
# Vertex ids are deterministic functions of canonical registry identity so a
# re-projection lands on the exact same vertex. The prefix namespaces each
# vertex type: asset:<canonical asset id>, chain:<chain id>, fiat:<iso code>,
# and AssetDeployment uses the deployment_id verbatim (deploy:<asset>@<chain>:
# <contract>), which is already globally unique. AssetDeployment ids never
# collide with the stablecoin domain's ``stablecoin_deployment:`` ids.

def asset_vertex_id(asset_id: str) -> str:
    """Global Asset vertex id for a canonical asset registry id (fiat/crypto/
    stablecoin/token)."""
    return f"asset:{asset_id}"


def chain_vertex_id(chain_id: str) -> str:
    """Global Chain vertex id for a CAIP-2 chain id (chain:<chain_id>).

    Reuses the stablecoin domain's chain vertex namespace so both projectors
    converge on ONE Chain vertex per chain id (last-writer-wins on the shared
    global vertex, never a duplicate chain).
    """
    return f"chain:{chain_id}"


def fiat_vertex_id(iso_code: str) -> str:
    """Global FiatCurrency vertex id for an ISO-4217 code (fiat:<iso_code>)."""
    return f"fiat:{iso_code}"


def deployment_vertex_id(deployment_id: str) -> str:
    """Global AssetDeployment vertex id — the deployment_id verbatim.

    Registry deployment ids already namespace by asset+chain+contract
    (``deploy:<asset_id>@<chain>:<contract>``), so they are globally unique and
    are used as the graph vertex id without an extra prefix.
    """
    return deployment_id


def _drop_none(props: dict[str, Any]) -> dict[str, Any]:
    """Registry columns we do not know may be absent/None; omit them from the
    projected vertex rather than storing an explicit null property."""
    return {k: v for k, v in props.items() if v is not None}


def _stamp_registry_version(props: dict[str, Any], registry_version: str) -> dict[str, Any]:
    if registry_version:
        props["registry_version"] = registry_version
    return props


# ── Pure builders (registry DB-shaped row → (vertices, edges)) ───────────────

def project_asset_mutations(
    asset_row: dict[str, Any],
    *,
    registry_version: str = "",
) -> tuple[list[Vertex], list[Edge]]:
    """One canonical ASSET vertex for a registry_assets row.

    Every canonical asset kind (fiat/crypto/stablecoin/token) is projected as a
    VertexType.ASSET node whose properties carry the kind, symbol, display
    decimals and status so queries can distinguish fiat assets from crypto
    assets. Fiat currencies additionally project a FiatCurrency reference vertex
    (project_fiat_mutations) from their ISO metadata row — two registry tables
    (registry_assets vs registry_fiat_currencies) map to two reference facets.
    """
    props: dict[str, Any] = {
        "tenant_id": PLATFORM_TENANT,
        "canonical_asset_id": asset_row["asset_id"],
        "kind": asset_row.get("kind"),
        "symbol": asset_row.get("symbol"),
        "name": asset_row.get("name"),
        "issuer": asset_row.get("issuer"),
        "display_decimals": asset_row.get("display_decimals"),
        "status": asset_row.get("status"),
    }
    vertex = Vertex(
        vertex_type=VertexType.ASSET,
        vertex_id=asset_vertex_id(asset_row["asset_id"]),
        properties=_stamp_registry_version(_drop_none(props), registry_version),
    )
    return [vertex], []


def project_chain_mutations(
    chain_row: dict[str, Any],
    *,
    registry_version: str = "",
) -> tuple[list[Vertex], list[Edge]]:
    """One global CHAIN vertex for a registry_chains row (chain:<chain_id>)."""
    props: dict[str, Any] = {
        "tenant_id": PLATFORM_TENANT,
        "chain_id": chain_row["chain_id"],
        "name": chain_row.get("name"),
        "network": chain_row.get("network"),
        "status": chain_row.get("status"),
        "vm": chain_row.get("vm"),
        "native_currency": chain_row.get("native_currency"),
    }
    vertex = Vertex(
        vertex_type=VertexType.CHAIN,
        vertex_id=chain_vertex_id(chain_row["chain_id"]),
        properties=_stamp_registry_version(_drop_none(props), registry_version),
    )
    return [vertex], []


def project_fiat_mutations(
    fiat_row: dict[str, Any],
    *,
    registry_version: str = "",
) -> tuple[list[Vertex], list[Edge]]:
    """One global FIAT_CURRENCY vertex for a registry_fiat_currencies row.

    The vertex id is ``fiat:<iso_code>`` (the canonical registry asset id for
    that currency). The associated fiat canonical asset also projects as an
    ASSET vertex (``asset:fiat:<iso_code>``) from its registry_assets row — see
    project_asset_mutations.
    """
    iso = fiat_row["iso_code"]
    props: dict[str, Any] = {
        "tenant_id": PLATFORM_TENANT,
        "iso_code": iso,
        "numeric_code": fiat_row.get("numeric_code"),
        "minor_units": fiat_row.get("minor_units"),
        "name": fiat_row.get("name"),
        "symbol": fiat_row.get("symbol"),
        "canonical_asset_id": f"fiat:{iso}",
    }
    vertex = Vertex(
        vertex_type=VertexType.FIAT_CURRENCY,
        vertex_id=fiat_vertex_id(iso),
        properties=_stamp_registry_version(_drop_none(props), registry_version),
    )
    return [vertex], []


def project_deployment_mutations(
    deployment_row: dict[str, Any],
    *,
    registry_version: str = "",
) -> tuple[list[Vertex], list[Edge]]:
    """One AssetDeployment vertex + its DEPLOYED_ON_CHAIN edge to the chain.

    The AssetDeployment vertex id is the registry deployment_id verbatim. The
    DEPLOYED_ON_CHAIN edge targets the global Chain vertex
    ``chain:<chain_id>``, which is projected separately by
    project_chain_mutations — the edge is only emitted when the chain row is
    actually projected (see build_all_from_registry). Reference topology:
    non-actor, RelationshipLayer.EXCLUDED.
    """
    deployment_id = deployment_row["deployment_id"]
    chain_id = deployment_row["chain_id"]
    props: dict[str, Any] = {
        "tenant_id": PLATFORM_TENANT,
        "canonical_asset_id": deployment_row["asset_id"],
        "chain_id": chain_id,
        "contract_or_mint": deployment_row.get("contract_or_mint"),
        "decimals": deployment_row.get("decimals"),
        "canonical_vs_bridged": deployment_row.get("canonical_vs_bridged"),
        "deployment_status": deployment_row.get("deployment_status"),
        "token_standard": deployment_row.get("token_standard"),
    }
    vertex = Vertex(
        vertex_type=VertexType.ASSET_DEPLOYMENT,
        vertex_id=deployment_vertex_id(deployment_id),
        properties=_stamp_registry_version(_drop_none(props), registry_version),
    )
    to_vertex = chain_vertex_id(chain_id)
    edge = Edge(
        edge_type=EdgeType.DEPLOYED_ON_CHAIN,
        from_vertex_id=deployment_id,
        to_vertex_id=to_vertex,
        properties=build_edge_properties(
            tenant_id=PLATFORM_TENANT,
            edge_type=EdgeType.DEPLOYED_ON_CHAIN,
            from_vertex_id=deployment_id,
            to_vertex_id=to_vertex,
            # The graph's EDGE actor-kind vocabulary is {human, agent, system}
            # (edge_properties.VALID_ACTOR_KINDS), enforced by
            # GraphWriteValidator on the Neptune write path. A platform
            # reference-seeder is a "system" actor on the edge; the richer
            # ledger spelling ("service") travels on the intent, never on the
            # edge properties.
            actor_kind="system",
            actor_id=_ACTOR_ID,
            provenance=_PROVENANCE,
            valid_from=_utc_now_iso(),
            contract_or_mint=str(deployment_row.get("contract_or_mint") or ""),
            decimals=str(deployment_row.get("decimals") or ""),
            canonical_vs_bridged=str(deployment_row.get("canonical_vs_bridged") or ""),
            deployment_status=str(deployment_row.get("deployment_status") or ""),
        ),
    )
    return [vertex], [edge]


# ── Present-but-no-op builders (no W2 registry rows substantiate them) ───────

def project_issuer_mutations(
    issuer_row: dict[str, Any],
    *,
    registry_version: str = "",
) -> tuple[list[Vertex], list[Edge]]:
    """No-op today: the registry has no issuer reference rows.

    VertexType.ISSUER is registered in economic_schema (owner_service="assets",
    provenance "registry.issuer.seeded"), but no registry table/repo seeds an
    issuer row in the W2 canonical seed, so nothing here is substantiated.
    Keep this builder present so the ISSUED_BY / issuer surface can be projected
    the moment an issuer registry exists — never project a fabricated issuer.
    """
    del issuer_row, registry_version  # present-but-no-op; nothing to build
    return [], []


def project_venue_mutations(
    venue_row: dict[str, Any],
    *,
    registry_version: str = "",
) -> tuple[list[Vertex], list[Edge]]:
    """No-op today: the registry has no trading/listing venue reference rows."""
    del venue_row, registry_version
    return [], []


def project_bridge_mutations(
    bridge_row: dict[str, Any],
    *,
    registry_version: str = "",
) -> tuple[list[Vertex], list[Edge]]:
    """No-op today: the registry has no bridge operator/router reference rows."""
    del bridge_row, registry_version
    return [], []


def project_price_provider_mutations(
    price_provider_row: dict[str, Any],
    *,
    registry_version: str = "",
) -> tuple[list[Vertex], list[Edge]]:
    """No-op today: no price-provider registry rows exist.

    VertexType.PRICE_PROVIDER is owned by services/valuation in economic_schema,
    so the assets domain deliberately never invents price-provider rows.
    """
    del price_provider_row, registry_version
    return [], []


def project_alias_mutations(
    alias_row: dict[str, Any],
    *,
    registry_version: str = "",
) -> tuple[list[Vertex], list[Edge]]:
    """No-op today: alias rows are resolution-only.

    registry_asset_aliases bridge legacy ids ("usdc", "usdc:eip155:8453") to
    canonical registry targets and are consumed by the resolver at read time.
    economic_schema registers no Alias reference vertex or alias→asset edge, so
    there is no graph surface for an alias row to project onto (schema gap —
    the FINANCIAL_NORMALIZATION.md §9 "alias → asset" note is not yet a
    registered edge). Keep this present-but-no-op rather than fabricating one.
    """
    del alias_row, registry_version
    return [], []


# ── Whole-registry build (pure composition, no graph writes) ────────────────

@dataclass
class RegistryReferenceProjection:
    """The full set of reference vertices/edges a registry state substantiates."""

    vertices: list[Vertex]
    edges: list[Edge]
    registry_version: str

    @property
    def vertex_count(self) -> int:
        return len(self.vertices)

    @property
    def edge_count(self) -> int:
        return len(self.edges)


async def _read_sorted(repo: Any, key: str) -> list[dict[str, Any]]:
    """Read every row of a registry repo and sort by its canonical key.

    Sorting in Python (rather than trusting repo order) keeps the projection
    deterministic regardless of insertion order or backend ordering.
    """
    rows = await repo.find_many(limit=_READ_LIMIT)
    return sorted(rows, key=lambda r: str(r.get(key) or ""))


async def _resolve_registry_version(
    registry: Any,
    registry_version: Optional[str],
) -> str:
    """The deterministic registry_version to stamp as provenance.

    Prefers an explicit argument, then the persisted meta ledger, then the
    current deterministic digest of the seeded content. Never wall-clock.
    """
    if registry_version:
        return registry_version
    meta = await registry.get_meta()
    if meta and meta.get("registry_version"):
        return str(meta["registry_version"])
    return str(registry.current_registry_version())


async def build_all_from_registry(
    registry: Any,
    *,
    registry_version: Optional[str] = None,
) -> RegistryReferenceProjection:
    """Build every reference vertex/edge the current registry state substantiates.

    Pure composition over the registry repos (no graph writes, no tenant
    scoping): asset/chain/fiat/deployment rows project their reference vertices,
    and each deployment whose chain row is present projects its
    DEPLOYED_ON_CHAIN edge. Registry rows whose reference type has no seeded
    content (issuer/venue/bridge/price-provider/alias) are deliberately not
    projected. ``registry`` is a UniversalAssetRegistry facade.
    """
    version = await _resolve_registry_version(registry, registry_version)

    asset_rows = await _read_sorted(registry.assets, "asset_id")
    chain_rows = await _read_sorted(registry.chains, "chain_id")
    fiat_rows = await _read_sorted(registry.fiats, "iso_code")
    deployment_rows = await _read_sorted(registry.deployments, "deployment_id")
    # Alias rows are read to keep build_all complete, but project_alias_mutations
    # is a documented no-op (no registered alias graph surface).
    await _read_sorted(registry.aliases, "alias")

    chain_ids = {row["chain_id"] for row in chain_rows}

    vertices: list[Vertex] = []
    edges: list[Edge] = []

    for row in asset_rows:
        v, _e = project_asset_mutations(row, registry_version=version)
        vertices.extend(v)
    for row in chain_rows:
        v, _e = project_chain_mutations(row, registry_version=version)
        vertices.extend(v)
    for row in fiat_rows:
        v, _e = project_fiat_mutations(row, registry_version=version)
        vertices.extend(v)
    for row in deployment_rows:
        v, e = project_deployment_mutations(row, registry_version=version)
        vertices.extend(v)
        # Only emit DEPLOYED_ON_CHAIN when the chain's own reference row was
        # projected (the W2 seed always registers chains before deployments).
        if row.get("chain_id") in chain_ids:
            edges.extend(e)

    # Deterministic ordering for the write pass and for digest reproducibility.
    vertices.sort(key=lambda vertex: vertex.vertex_id)
    edges.sort(key=lambda edge: (edge.from_vertex_id, edge.edge_type, edge.to_vertex_id))
    return RegistryReferenceProjection(
        vertices=vertices, edges=edges, registry_version=version,
    )


# ── Persist seam (graph write house path) ───────────────────────────────────

@dataclass
class AssetGraphProjectionResult:
    """What a projection run wrote (vs. what it skipped as already current)."""

    status: str = "no_mutations"
    vertices_built: int = 0
    vertices_persisted: int = 0
    vertices_skipped: int = 0
    edges_built: int = 0
    edges_persisted: int = 0
    edges_skipped: int = 0
    registry_version: str = ""


def _normalize_platform_tenant(mutations: list[Any]) -> None:
    """Stamp both tenant spellings onto every mutation's properties.

    The graph carries ``tenantId`` (canonical, used by Neptune tenant reads and
    vertex producers) and ``tenant_id`` (legacy, used by edge producers). Global
    reference rows are platform-scoped, so both spellings point at
    PLATFORM_TENANT — otherwise get_vertices_for_tenant("platform") would miss
    them on the Neptune path.
    """
    for mutation in mutations:
        props = getattr(mutation, "properties", None)
        if isinstance(props, dict):
            props[TENANT_PROPERTY] = PLATFORM_TENANT
            props.setdefault(_TENANT_ID_SPELLING, PLATFORM_TENANT)


_CANONICAL_TENANT_PROPERTIES = frozenset({TENANT_PROPERTY, _TENANT_ID_SPELLING})


def _content_view(properties: Optional[dict[str, Any]]) -> dict[str, str]:
    """Storage-neutral property view for idempotency comparison.

    The Neptune backend persists every property as ``str(v)`` and reads it back
    as a string, while the in-memory backend keeps the Python value verbatim
    (so an int 6 in a build is stored as ``6`` locally but ``"6"`` on Neptune).
    Comparing raw dicts therefore reports identical content as different on the
    Neptune path and re-projection would never converge. This canonicalises both
    sides the same way the mutation gateway's digest does — values stringified,
    the two tenant-key spellings folded to one — so ``int 6`` equals ``"6"``.
    """
    view: dict[str, str] = {}
    for key, value in (properties or {}).items():
        if value is None:
            continue
        if key in _CANONICAL_TENANT_PROPERTIES:
            view[TENANT_PROPERTY] = str(value)
            continue
        view[str(key)] = str(value)
    return view


def _vertex_content_equal(existing: Vertex, desired: Vertex) -> bool:
    """True when ``existing`` already holds exactly the content ``desired`` wants.

    The desired projection is authoritative for the keys it manages: every
    ``desired`` property must be present with an equal (string-normalised) value
    on the stored vertex. Extra stored keys — e.g. a tenant-key spelling or
    property left by an earlier projection of the same shared global vertex id —
    do not defeat idempotency, so a re-run against an unchanged registry
    converges instead of churning ``created_at``.
    """
    if existing.vertex_type != desired.vertex_type:
        return False
    stored = _content_view(existing.properties)
    wanted = _content_view(desired.properties)
    return all(stored.get(key) == value for key, value in wanted.items())


async def _vertex_write_operation(graph_client: Any, vertex: Vertex) -> tuple[str, bool]:
    """Decide how to persist one reference vertex.

    Returns ``(operation, exists)``:
      - vertex id absent      → (``node_created``, False)  → gateway add_vertex
      - present but different → (``node_versioned``, True) → gateway upsert_vertex
      - present + identical   → caller skips (handled by the persist loop).

    The split matters on Neptune: ``add_vertex`` is a pure ``addV`` insert and
    re-adding an existing vertex id aborts, so a content change (e.g. a seed
    change bumping ``registry_version``) must be routed to ``node_versioned``,
    which the gateway projects through ``upsert_vertex`` — an in-place property
    rewrite on both backends. A brand-new vertex is a genuine ``node_created``.
    """
    existing = await graph_client.get_vertex(vertex.vertex_id)
    if existing is None:
        return "node_created", False
    if _vertex_content_equal(existing, vertex):
        return "node_created", True  # identical → persist loop skips
    return "node_versioned", True


async def _edge_already_present(graph_client: Any, edge: Edge) -> bool:
    """True when a DEPLOYED_ON_CHAIN edge already connects these endpoints.

    In-memory backends append edges (unlike vertex sets which dedupe by id), so
    idempotency for edges is decided on the (from, edge_type, to) tuple rather
    than on properties — the first projection's valid_from is kept.
    """
    existing = await graph_client.get_edges(
        edge.from_vertex_id,
        edge_type=edge.edge_type,
        direction="out",
        include_revoked=True,
    )
    return any(stored.to_vertex_id == edge.to_vertex_id for stored in existing)


async def project_all_from_registry(
    registry: Any,
    *,
    graph: Optional[Any] = None,
    registry_version: Optional[str] = None,
) -> AssetGraphProjectionResult:
    """Project the whole registry onto the graph (GLOBAL reference rows only).

    Builds the reference surface (build_all_from_registry) and persists it
    through the canonical GraphMutationGateway (off mode → the existing
    add_vertex/add_edge path). Idempotent: vertices already holding identical
    content (compared storage-spelling neutral) and already-present
    (deployment, chain) DEPLOYED_ON_CHAIN edges are skipped, so re-projection
    against the same registry reproduces the same graph state without
    duplicates. A vertex whose content changed (e.g. a seed change bumped its
    ``registry_version``) is rewritten in place via ``node_versioned`` (gateway
    upsert_vertex) — never a duplicate ``addV`` on the existing id.

    ``graph`` may be injected (tests); otherwise the process-wide GraphClient is
    used. This function never originates/settles and never touches a consumer
    tenant — every write is a platform-scoped global reference row.
    """
    from shared.graph.mutation_gateway import GraphMutationGateway
    from shared.graph.mutation_intents import edge_intent, vertex_intent

    projection = await build_all_from_registry(registry, registry_version=registry_version)
    version = projection.registry_version
    graph_client = graph or get_graph_client()

    result = AssetGraphProjectionResult(
        status="no_mutations",
        vertices_built=projection.vertex_count,
        edges_built=projection.edge_count,
        registry_version=version,
    )
    if not projection.vertices and not projection.edges:
        return result

    _normalize_platform_tenant([*projection.vertices, *projection.edges])
    gateway = GraphMutationGateway(graph_client=graph_client)

    vertices_persisted = 0
    vertices_skipped = 0
    for vertex in projection.vertices:
        operation, exists = await _vertex_write_operation(graph_client, vertex)
        if exists and operation == "node_created":
            # Existing vertex with identical content → nothing to rewrite.
            vertices_skipped += 1
            continue
        await gateway.apply(vertex_intent(
            vertex,
            operation=operation,
            tenant_id=PLATFORM_TENANT,
            actor_kind="service",
            actor_id=_ACTOR_ID,
        ))
        vertices_persisted += 1

    edges_persisted = 0
    edges_skipped = 0
    for edge in projection.edges:
        if await _edge_already_present(graph_client, edge):
            edges_skipped += 1
            continue
        await gateway.apply(edge_intent(
            edge,
            operation="edge_created",
            tenant_id=PLATFORM_TENANT,
        ))
        edges_persisted += 1

    result.vertices_persisted = vertices_persisted
    result.vertices_skipped = vertices_skipped
    result.edges_persisted = edges_persisted
    result.edges_skipped = edges_skipped
    result.status = (
        "persisted"
        if (vertices_persisted or edges_persisted)
        else "up_to_date"
    )
    return result


__all__ = [
    "PLATFORM_TENANT",
    "AssetGraphProjectionResult",
    "RegistryReferenceProjection",
    "asset_vertex_id",
    "build_all_from_registry",
    "chain_vertex_id",
    "deployment_vertex_id",
    "fiat_vertex_id",
    "project_alias_mutations",
    "project_all_from_registry",
    "project_asset_mutations",
    "project_bridge_mutations",
    "project_chain_mutations",
    "project_deployment_mutations",
    "project_fiat_mutations",
    "project_issuer_mutations",
    "project_price_provider_mutations",
    "project_venue_mutations",
]
