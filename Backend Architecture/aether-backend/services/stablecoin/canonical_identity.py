"""Stablecoin → universal canonical-identity seam (read side, additive).

The stablecoin canonical module (this package) predates the universal asset
registry: its reference rows key canonical assets by ``symbol.lower()`` (e.g.
``usdc``) and deployments by ``{symbol.lower()}:{chain_id}`` (e.g.
``usdc:eip155:8453``). Under universal financial normalization those spellings
are LEGACY ids — the universal registry bridges them, never rewrites them,
through alias rows:

    "usdc"             -> stablecoin:USDC
    "usdc:eip155:8453" -> stablecoin:USDC + deploy:stablecoin:USDC@eip155:8453:...

This module is the seam that lets the stablecoin domain READ through the
universal registry where it is meaningful — ADDITIVELY. It never invents an id
the universal registry cannot verify, never rewrites a legacy id, and never
touches storage. Given a legacy stablecoin id / symbol / deployment, it returns
a read model carrying ``canonical_asset_id`` / ``canonical_deployment_id`` as
Optional fields populated only when the universal registry verifies a target;
an unknown reference stays unresolved (both fields None), never guessed.

The seam is intentionally NOT wired into the module's write / persist /
graph_mutations paths — it is a read-side projection only. Resolver instances
default to fresh registry facades (in-memory typed stores under
AETHER_ENV=local) so the full path is DB-free and matches how the module's
routes already construct their registries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from services.assets.registry import UniversalAssetRegistry
    from services.stablecoin.registry import StablecoinRegistry

# Namespaced universal references that are echoed (verified) rather than
# resolved through aliases. ``deploy:`` deployment ids are NOT namespaced asset
# ids (the seeds helper covers fiat:/crypto:/stablecoin:/token: only).
_UNIVERSAL_PREFIXES = ("fiat:", "crypto:", "stablecoin:", "token:", "deploy:")

# Resolution methods the seam reports (informational provenance).
_ASSET_ALIAS = "asset_alias"
_DEPLOYMENT_ALIAS = "deployment_alias"
_DOMAIN_DEPLOYMENT_VERIFIED = "domain_deployment_verified"
_ASSET_CHAIN_VERIFIED = "asset_chain_verified"
_SYMBOL_VERIFIED = "symbol_verified"
_NAMESPACED_VERIFIED = "namespaced_verified"
_UNRESOLVED = "unresolved"


class StablecoinUniversalIdentityRead(BaseModel):
    """Read model produced by the canonical-identity seam.

    ``reference`` preserves the caller's original spelling verbatim — the seam
    never rewrites a legacy id. ``canonical_asset_id`` and
    ``canonical_deployment_id`` are Optional and populated only when the
    universal registry verifies a target row; unknown references keep both
    None (never a guessed id). ``resolved`` is True exactly when at least one
    canonical id was verified.
    """

    model_config = ConfigDict(extra="forbid")

    reference: str
    resolved: bool = False
    canonical_asset_id: Optional[str] = None
    canonical_deployment_id: Optional[str] = None
    resolution_method: Optional[str] = None
    registry_version: Optional[str] = None


def _identity(
    *,
    reference: str,
    canonical_asset_id: Optional[str],
    canonical_deployment_id: Optional[str],
    resolution_method: Optional[str],
    registry_version: Optional[str],
) -> StablecoinUniversalIdentityRead:
    return StablecoinUniversalIdentityRead(
        reference=reference,
        resolved=canonical_asset_id is not None or canonical_deployment_id is not None,
        canonical_asset_id=canonical_asset_id,
        canonical_deployment_id=canonical_deployment_id,
        resolution_method=resolution_method,
        registry_version=registry_version,
    )


def _unresolved(reference: str, registry_version: Optional[str]) -> StablecoinUniversalIdentityRead:
    return _identity(
        reference=reference,
        canonical_asset_id=None,
        canonical_deployment_id=None,
        resolution_method=_UNRESOLVED,
        registry_version=registry_version,
    )


class StablecoinCanonicalIdentityResolver:
    """Maps stablecoin legacy ids / symbols / deployments to universal identity.

    Resolution demands real universal-registry knowledge at every step (alias
    rows, registered asset/deployment rows, exactly-one candidate symbol
    matches). Nothing is guessed, and an unknown reference yields an unresolved
    read (canonical ids None) with the original spelling preserved.
    """

    def __init__(
        self,
        universal_registry: Optional["UniversalAssetRegistry"] = None,
        stablecoin_registry: Optional["StablecoinRegistry"] = None,
    ) -> None:
        # Facades are defaulted to fresh instances here. services.assets.registry
        # imports only shared contracts (not this package's services), so pulling
        # it in creates no import cycle. Under AETHER_ENV=local both registries
        # fall back to the shared in-memory typed stores (DB-free).
        if universal_registry is None:
            from services.assets.registry import UniversalAssetRegistry

            universal_registry = UniversalAssetRegistry()
        if stablecoin_registry is None:
            from services.stablecoin.registry import StablecoinRegistry

            stablecoin_registry = StablecoinRegistry()
        self.universal = universal_registry
        self.stablecoin = stablecoin_registry

    # ── top-level resolution ──────────────────────────────────────────────

    async def resolve(self, reference: str) -> StablecoinUniversalIdentityRead:
        """Resolve one legacy stablecoin reference onto universal identity.

        ``reference`` may be a legacy asset id / symbol (``"usdc"``, ``"USDC"``),
        a legacy deployment id (``"usdc:eip155:8453"``), or an already-universal
        namespaced id (``"stablecoin:USDC"``, ``"deploy:stablecoin:USDC@..."`` —
        verified against the registry and echoed when known).
        """
        ref = str(reference or "").strip()
        if not ref:
            return _unresolved(ref, self.universal.current_registry_version())

        if ref.startswith(_UNIVERSAL_PREFIXES):
            return await self._resolve_universal(ref)

        if ":" in ref:
            return await self._resolve_coloned(ref) or _unresolved(
                ref, self.universal.current_registry_version()
            )
        return await self._resolve_bare(ref) or _unresolved(
            ref, self.universal.current_registry_version()
        )

    # ── resolution strategies ─────────────────────────────────────────────

    async def _resolve_universal(self, ref: str) -> StablecoinUniversalIdentityRead:
        """An already-namespaced id: verify it exists, echo it, else unresolved."""
        version = self.universal.current_registry_version()
        if ref.startswith("deploy:"):
            deployment = await self.universal.get_deployment(ref)
            if deployment is None:
                return _unresolved(ref, version)
            asset = await self.universal.get_asset(deployment.get("asset_id") or "")
            return _identity(
                reference=ref,
                canonical_asset_id=(asset or {}).get("id") if asset else None,
                canonical_deployment_id=deployment["deployment_id"],
                resolution_method=_NAMESPACED_VERIFIED,
                registry_version=version,
            )
        asset = await self.universal.get_asset(ref)
        if asset is None:
            return _unresolved(ref, version)
        return _identity(
            reference=ref,
            canonical_asset_id=asset["id"],
            canonical_deployment_id=None,
            resolution_method=_NAMESPACED_VERIFIED,
            registry_version=version,
        )

    async def _resolve_coloned(self, ref: str) -> Optional[StablecoinUniversalIdentityRead]:
        """A coloned reference — a legacy deployment id (alias or chain-scoped).

        Priority: legacy-deployment alias row (``usdc:eip155:8453``), then the
        module's own deployment registry (chain + contract verified against the
        universal registry), then a symbol+chain context narrowing that only
        succeeds when the registry holds exactly one active deployment for the
        asset on that chain. Unknown chain/contract is never re-interpreted.
        """
        version = self.universal.current_registry_version()

        # 1) Legacy deployment alias row (the seeded, verified bridge).
        alias = await self.universal.resolve_alias(ref)
        if alias is not None and alias.get("target_asset_id"):
            asset = await self.universal.get_asset(alias["target_asset_id"])
            if asset is not None:
                deployment_id = alias.get("target_deployment_id")
                deployment = (
                    await self.universal.get_deployment(deployment_id)
                    if deployment_id
                    else None
                )
                # An alias naming a deployment the registry does not hold is
                # never trusted — unresolved rather than a guessed deployment.
                if deployment_id and deployment is None:
                    return _unresolved(ref, version)
                return _identity(
                    reference=ref,
                    canonical_asset_id=asset["id"],
                    canonical_deployment_id=deployment_id if deployment is not None else None,
                    resolution_method=(
                        _DEPLOYMENT_ALIAS if deployment is not None else _ASSET_ALIAS
                    ),
                    registry_version=version,
                )

        # 2) Module deployment registry: resolve chain+contract upstream.
        domain_deployment = await self.stablecoin.get_deployment(ref)
        if domain_deployment is not None:
            chain = domain_deployment.get("chain_id")
            contract = domain_deployment.get("contract_or_mint")
            if chain and contract:
                deployment = await self.universal.resolve_deployment(chain, contract)
                if deployment is not None:
                    asset = await self.universal.get_asset(deployment.get("asset_id") or "")
                    return _identity(
                        reference=ref,
                        canonical_asset_id=(asset or {}).get("id") if asset else None,
                        canonical_deployment_id=deployment["deployment_id"],
                        resolution_method=_DOMAIN_DEPLOYMENT_VERIFIED,
                        registry_version=version,
                    )

        # 3) symbol:chain narrowing — exactly one active universal deployment.
        symbol, _, chain = ref.partition(":")
        if symbol and chain:
            alias = await self.universal.resolve_alias(symbol)
            target = (alias or {}).get("target_asset_id")
            if target:
                candidates = await self.universal.deployments.find_many(
                    {"asset_id": target, "chain_id": chain, "deployment_status": "active"},
                    limit=1000,
                )
                if len(candidates) == 1:
                    asset = await self.universal.get_asset(target)
                    return _identity(
                        reference=ref,
                        canonical_asset_id=(asset or {}).get("id") if asset else None,
                        canonical_deployment_id=candidates[0]["deployment_id"],
                        resolution_method=_ASSET_CHAIN_VERIFIED,
                        registry_version=version,
                    )
        return None

    async def _resolve_bare(self, ref: str) -> Optional[StablecoinUniversalIdentityRead]:
        """A bare legacy asset id / symbol (no colon)."""
        version = self.universal.current_registry_version()

        alias = await self.universal.resolve_alias(ref)  # case-insensitive
        if alias is not None and alias.get("target_asset_id"):
            asset = await self.universal.get_asset(alias["target_asset_id"])
            if asset is not None:
                deployment_id = alias.get("target_deployment_id")
                deployment = (
                    await self.universal.get_deployment(deployment_id)
                    if deployment_id
                    else None
                )
                if deployment_id and deployment is None:
                    return _unresolved(ref, version)
                return _identity(
                    reference=ref,
                    canonical_asset_id=asset["id"],
                    canonical_deployment_id=deployment_id if deployment is not None else None,
                    resolution_method=(
                        _DEPLOYMENT_ALIAS if deployment is not None else _ASSET_ALIAS
                    ),
                    registry_version=version,
                )

        # Bare symbol: exactly one ACTIVE canonical asset wins; collisions and
        # zero matches are unresolved (mirrors the universal resolver's §8.4).
        candidates = await self.universal.resolve_asset(ref)
        active = [a for a in candidates if a.get("status") == "active"]
        if len(active) == 1:
            return _identity(
                reference=ref,
                canonical_asset_id=active[0]["id"],
                canonical_deployment_id=None,
                resolution_method=_SYMBOL_VERIFIED,
                registry_version=version,
            )
        return None

    # ── read-row surface (objective 2) ────────────────────────────────────

    async def resolve_read_row(self, row: dict[str, Any]) -> StablecoinUniversalIdentityRead:
        """Resolve one module read row (observation / deployment / asset row).

        The row's own identity signal is preferred: deployment_id first, then
        canonical_asset_id (the module's legacy spelling), then chain+contract.
        Rows carrying no stablecoin identity signal resolve unresolved (their
        legacy spelling — if any — is preserved on ``reference``).
        """
        deployment_id = row.get("deployment_id")
        if deployment_id:
            return await self.resolve(str(deployment_id))
        asset_id = row.get("canonical_asset_id")
        if asset_id:
            return await self.resolve(str(asset_id))
        chain = row.get("chain_id")
        contract = row.get("contract_or_mint")
        if chain and contract:
            deployment = await self.universal.resolve_deployment(str(chain), str(contract))
            if deployment is not None:
                version = self.universal.current_registry_version()
                asset = await self.universal.get_asset(deployment.get("asset_id") or "")
                return _identity(
                    reference=f"{chain}:{contract}",
                    canonical_asset_id=(asset or {}).get("id") if asset else None,
                    canonical_deployment_id=deployment["deployment_id"],
                    resolution_method=_DOMAIN_DEPLOYMENT_VERIFIED,
                    registry_version=version,
                )
        return _unresolved(
            str(deployment_id or asset_id or f"{chain}:{contract}" if (chain and contract) else ""),
            self.universal.current_registry_version(),
        )


def surface_on_read_row(
    row: dict[str, Any],
    identity: Optional[StablecoinUniversalIdentityRead],
) -> dict[str, Any]:
    """Return a shallow copy of a module read row augmented with canonical ids.

    Additive-only: ``canonical_asset_id`` / ``canonical_deployment_id`` are
    attached when resolvable AND the source row does not already define that key
    with a non-None value. Pre-convergence rows that already carry the legacy
    spelling under ``canonical_asset_id`` keep it untouched — the seam never
    rewrites a legacy id; callers that need the universal asset id read it off
    ``identity.canonical_asset_id`` directly.
    """
    out = dict(row)
    if identity is None:
        return out
    if (
        identity.canonical_asset_id is not None
        and (out.get("canonical_asset_id") is None)
    ):
        out["canonical_asset_id"] = identity.canonical_asset_id
    if (
        identity.canonical_deployment_id is not None
        and (out.get("canonical_deployment_id") is None)
    ):
        out["canonical_deployment_id"] = identity.canonical_deployment_id
    return out


async def resolve_canonical_identity(
    reference: str,
    *,
    universal_registry: Optional["UniversalAssetRegistry"] = None,
    stablecoin_registry: Optional["StablecoinRegistry"] = None,
) -> StablecoinUniversalIdentityRead:
    """Module-level convenience: resolve one reference through the seam."""
    resolver = StablecoinCanonicalIdentityResolver(
        universal_registry=universal_registry,
        stablecoin_registry=stablecoin_registry,
    )
    return await resolver.resolve(reference)
