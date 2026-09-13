"""Universal asset registry seeder — idempotent seed of canonical reference data.

Consumes the pure builders in ``seeds.py`` and writes them through the registry
facade's register_* methods in dependency order:

  fiat -> chains (+ each chain's native crypto asset/deployment) ->
          stablecoins (x402 verified) -> legacy aliases

Every register is an upsert on canonical identity (typed repo
INSERT .. ON CONFLICT .. DO NOTHING), so seeding is idempotent: re-running
produces byte-identical registry state and the same deterministic
``registry_version``. No seed row is ever a guess — stablecoin contracts and
decimals come from x402 verification constants, chain metadata from committed
chain meta, fiat from the ISO reference seed. No function here fabricates
content (e.g. never derives a deployment for a chain the x402 map does not
verify).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from services.assets import seeds

if TYPE_CHECKING:
    from shared.graph.graph import GraphClient
    from services.assets.registry import UniversalAssetRegistry


class UniversalAssetSeeder:
    """Seed the canonical registry through a UniversalAssetRegistry facade.

    Optionally projects the freshly seeded canonical rows onto the graph's
    GLOBAL reference layer when graph projection is enabled. Projection is
    default-OFF: callers must pass ``graph_enabled=True`` or set
    ``AETHER_ASSETS_GRAPH_ENABLED`` (settings.assets.graph_enabled); nothing is
    projected unless one of the two opts in.
    """

    def __init__(
        self,
        registry: Optional["UniversalAssetRegistry"] = None,
        *,
        graph_enabled: Optional[bool] = None,
        graph: Optional["GraphClient"] = None,
    ) -> None:
        if registry is None:
            from services.assets.registry import UniversalAssetRegistry

            registry = UniversalAssetRegistry()
        self.registry = registry
        # graph_enabled=None → fall back to settings.assets.graph_enabled (env
        # AETHER_ASSETS_GRAPH_ENABLED, default False). The injectable bool lets
        # tests toggle projection without mutating the frozen settings object.
        self._graph_enabled = graph_enabled
        self._graph = graph

    # ── phases ──────────────────────────────────────────────────────────────

    async def seed_fiat(self) -> dict[str, Any]:
        """ISO 4217 currencies; each register_fiat also registers its fiat asset."""
        inserted = 0
        for row in seeds.fiat_currency_rows():
            result = await self.registry.register_fiat(row)
            if result["fiat_inserted"]:
                inserted += 1
        return {"domain": "fiat", "fiat_inserted": inserted, "fiat_total": len(seeds.fiat_currency_rows())}

    async def seed_chains(self) -> dict[str, Any]:
        """Chains (from the x402 network map) and their native crypto assets."""
        chain_inserted = 0
        for row in seeds.chain_rows():
            result = await self.registry.register_chain(row)
            if result["inserted"]:
                chain_inserted += 1
        asset_inserted = 0
        for row in seeds.native_asset_rows():
            result = await self.registry.register_asset(row)
            if result["inserted"]:
                asset_inserted += 1
        deployment_inserted = 0
        for row in seeds.native_deployment_rows():
            result = await self.registry.register_deployment(row)
            if result["inserted"]:
                deployment_inserted += 1
        return {
            "domain": "chains",
            "chain_inserted": chain_inserted,
            "chain_total": len(seeds.chain_rows()),
            "native_asset_inserted": asset_inserted,
            "native_deployment_inserted": deployment_inserted,
        }

    async def seed_stablecoins_from_x402(self) -> dict[str, Any]:
        """Stablecoin assets/deployments exactly where x402 verification says so."""
        asset_inserted = 0
        for row in seeds.stablecoin_asset_rows():
            result = await self.registry.register_asset(row)
            if result["inserted"]:
                asset_inserted += 1
        deployment_inserted = 0
        for row in seeds.stablecoin_deployment_rows():
            result = await self.registry.register_deployment(row)
            if result["inserted"]:
                deployment_inserted += 1
        return {
            "domain": "stablecoins",
            "stablecoin_asset_inserted": asset_inserted,
            "stablecoin_deployment_inserted": deployment_inserted,
        }

    async def seed_aliases(self) -> dict[str, Any]:
        """Legacy stablecoin-domain ids and native symbols, bridged via aliases."""
        inserted = 0
        for row in seeds.alias_rows():
            result = await self.registry.register_alias(row)
            if result["inserted"]:
                inserted += 1
        return {"domain": "aliases", "alias_inserted": inserted, "alias_total": len(seeds.alias_rows())}

    # ── full seed ───────────────────────────────────────────────────────────

    async def seed_all(self) -> dict[str, Any]:
        """Run every phase in dependency order and return a full summary.

        The returned summary carries the seed_count_snapshot totals plus the
        per-phase inserted counts (informational). The facade writes the
        deterministic registry_version meta row from this result.

        When graph projection is enabled (see __init__/settings.assets.
        graph_enabled), the freshly seeded canonical rows are also projected
        onto the graph's GLOBAL reference layer and the summary carries a
        ``graph_projection`` block. Default-OFF: no graph writes unless the
        caller or env opts in.
        """
        phases = [
            await self.seed_fiat(),
            await self.seed_chains(),
            await self.seed_stablecoins_from_x402(),
            await self.seed_aliases(),
        ]
        summary: dict[str, Any] = dict(seeds.seed_count_snapshot())
        summary["inserted"] = {
            phase.pop("domain"): phase for phase in phases
        }
        projection = await self._maybe_project_graph()
        if projection is not None:
            summary["graph_projection"] = projection
        return summary

    # ── optional graph projection ───────────────────────────────────────────

    async def _maybe_project_graph(self) -> Optional[dict[str, Any]]:
        """Run the registry → graph reference projector when enabled.

        Resolves the graph_enabled flag (constructor injection wins, otherwise
        settings.assets.graph_enabled) and delegates the actual projection to
        services/assets/graph_projector.py. Returns None when disabled so the
        seed summary is unchanged unless projection actually ran.
        """
        enabled = self._graph_enabled
        if enabled is None:
            from config.settings import settings

            enabled = bool(settings.assets.graph_enabled)
        if not enabled:
            return None
        from services.assets.graph_projector import project_all_from_registry

        result = await project_all_from_registry(self.registry, graph=self._graph)
        return {
            "status": result.status,
            "vertices_built": result.vertices_built,
            "vertices_persisted": result.vertices_persisted,
            "vertices_skipped": result.vertices_skipped,
            "edges_built": result.edges_built,
            "edges_persisted": result.edges_persisted,
            "edges_skipped": result.edges_skipped,
            "registry_version": result.registry_version,
        }
