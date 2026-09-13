"""Universal asset resolver — §8 resolution priority to canonical identity.

Given a value.ts-style native payload (packages/shared/value.ts NativeValue),
resolve it onto canonical registry identity WITHOUT guessing. Resolution follows
the financial-normalization §8 priority, each strategy demanding real registry
knowledge:

  1. chain + contract_or_mint  -> deployment row -> its asset  (AUTHORITATIVE:
     a payload naming a concrete deployment the registry does not know is never
     re-interpreted through its symbol — it is recorded unknown_contract)
  2. namespaced asset_id       -> registered asset (fiat:/crypto:/stablecoin:/token:)
  3. legacy canonical id       -> alias row -> canonical target (never rewritten)
  4. verified alias / symbol   -> exactly one active symbol match
  5. symbol + chain context    -> exactly one active candidate on that chain
  6. multiple candidates       -> collision_unresolvable (recorded, ambiguous_symbol)
  7. nothing verifiable        -> unresolved_recorded (reason from registry state)

When identity cannot be verified the reference is RECORDED on the tenant-scoped
registry_unresolved_asset_refs observational table (reason never guessed) and
the resolver returns an unresolved report — the original native payload is
preserved verbatim and never coerced. AETHER OBSERVES. AETHER DOES NOT EXECUTE.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from services.assets import seeds

if TYPE_CHECKING:
    from services.assets.registry import UniversalAssetRegistry

# Sentinel tenant for platform-scope resolutions without a caller tenant.
_PLATFORM_TENANT = "platform"

# Statuses that are a verified, actionable canonical resolution.
_RESOLVED_STATUSES = frozenset({
    "resolved_chain_contract", "resolved_namespaced_id",
    "resolved_legacy_alias", "resolved_symbol_verified",
    "resolved_symbol_context",
})


def _report(
    native: dict[str, Any],
    *,
    resolution_status: str,
    asset: Optional[dict] = None,
    deployment: Optional[dict] = None,
    registry_version: str,
    unresolved: Optional[dict] = None,
) -> dict[str, Any]:
    """Assemble one deterministic resolution report.

    ``native`` is echoed verbatim — canonicalization never rewrites the observed
    amount/currency/decimals. ``resolved_asset``/``resolved_deployment`` are the
    registry rows the resolution anchored on (contract shapes); top-level
    canonical_asset_id / deployment_id are populated from them for convenience.
    """
    canonical_asset_id = None
    if asset is not None:
        canonical_asset_id = asset.get("id") or asset.get("asset_id")
    deployment_id = None
    if deployment is not None:
        deployment_id = deployment.get("deployment_id")
    return {
        "native": dict(native),
        "resolution_status": resolution_status,
        "canonical_asset_id": canonical_asset_id,
        "canonical_symbol": (asset or {}).get("symbol") if asset else None,
        "canonical_decimals": (asset or {}).get("display_decimals"),
        "deployment_id": deployment_id,
        "resolved_asset": asset,
        "resolved_deployment": deployment,
        "verified": resolution_status in _RESOLVED_STATUSES,
        "unresolved": unresolved,
        "registry_version": registry_version,
    }


class UniversalAssetResolver:
    """§8 resolution over a UniversalAssetRegistry facade (injected)."""

    def __init__(
        self,
        registry: "UniversalAssetRegistry",
        *,
        tenant_id: Optional[str] = None,
    ) -> None:
        self.registry = registry
        self.tenant_id = tenant_id or _PLATFORM_TENANT
        self._version = registry.current_registry_version()

    # ── helpers ─────────────────────────────────────────────────────────────

    async def _chain_registered(self, chain_id: str) -> bool:
        return await self.registry.resolve_chain(chain_id) is not None

    async def _active_deployments_for(
        self, asset_id: str, chain_id: Optional[str],
    ) -> list[dict]:
        """Active deployments of an asset on a chain (empty when no chain)."""
        if not chain_id:
            return []
        rows = await self.registry.deployments.find_many(
            {"chain_id": chain_id, "asset_id": asset_id}, limit=10000,
        )
        return [r for r in rows if r.get("deployment_status") == "active"]

    async def _asset_view(self, asset_id: str) -> Optional[dict]:
        """Registry asset row with the contract ``id`` field (for reports)."""
        return await self.registry.get_asset(asset_id)

    @staticmethod
    def _symbol_token(native: dict[str, Any]) -> Optional[str]:
        """Preferred symbol token from a native payload (never guessed).

        asset_symbol is authoritative when present; otherwise the currency field
        (ISO fiat code or asset symbol, per value.ts). Uppercased for lookup.
        """
        raw = native.get("asset_symbol") or native.get("currency")
        if not raw:
            return None
        token = str(raw).strip().upper()
        return token or None

    async def _unresolved_report(
        self, native: dict[str, Any], *, reason: str,
    ) -> dict[str, Any]:
        """Record one unresolved sighting and return an unresolved report."""
        recorded = await self.registry.record_unresolved(
            raw_reference=self._raw_reference(native),
            reason=reason,
            tenant_id=self.tenant_id,
            evidence={"native": dict(native)},
        )
        return _report(
            native,
            resolution_status="unresolved_recorded",
            asset=None,
            deployment=None,
            registry_version=self._version,
            unresolved={"reason": reason, "recorded": recorded},
        )

    # ── §8 priority strategies ──────────────────────────────────────────────

    async def _resolve_chain_contract(self, native: dict[str, Any]) -> Optional[dict]:
        """§8.1 chain + contract_or_mint -> deployment -> asset.

        Authoritative when the payload names a deployment: if the registry does
        not know the (chain, contract) pair, symbol/alias fields must NOT
        re-interpret it (the caller asserted concrete on-chain identity). The
        caller returns None only when chain XOR contract is absent.
        """
        chain = native.get("chain")
        contract = native.get("contract_or_mint")
        if not chain or not contract:
            return None
        deployment = await self.registry.resolve_deployment(chain, contract)
        if deployment is not None:
            asset = await self._asset_view(deployment["asset_id"])
            return {
                "resolution_status": "resolved_chain_contract",
                "asset": asset,
                "deployment": deployment,
            }
        # Deployment unknown but a concrete deployment was asserted -> fail closed.
        if await self._chain_registered(chain):
            return {"unresolved": "unknown_contract"}
        return {"unresolved": "unknown_chain"}

    async def _resolve_namespaced_id(self, native: dict[str, Any]) -> Optional[dict]:
        """§8.2 a namespaced asset_id that is actually registered."""
        aid = native.get("canonical_asset_id") or native.get("asset_id")
        if not aid or not seeds.is_namespaced_asset_id(str(aid)):
            return None
        asset = await self._asset_view(str(aid))
        if asset is None:
            # Present but NOT registered — do not fall through to guesswork; the
            # caller asserted a canonical id the registry cannot verify.
            return {"unresolved": "no_registry_entry"}
        return {
            "resolution_status": "resolved_namespaced_id",
            "asset": asset,
            "deployment": None,
        }

    async def _resolve_legacy_alias(self, native: dict[str, Any]) -> Optional[dict]:
        """§8.3 a non-namespaced asset_id bridged by a legacy alias row."""
        aid = native.get("canonical_asset_id") or native.get("asset_id")
        if not aid or seeds.is_namespaced_asset_id(str(aid)):
            return None
        alias = await self.registry.resolve_alias(str(aid))
        if alias is None:
            return None
        target_asset_id = alias.get("target_asset_id")
        if not target_asset_id:
            return None
        asset = await self._asset_view(target_asset_id)
        deployment = None
        target_dep_id = alias.get("target_deployment_id")
        if target_dep_id:
            deployment = await self.registry.get_deployment(target_dep_id)
        return {
            "resolution_status": "resolved_legacy_alias",
            "asset": asset,
            "deployment": deployment,
        }

    async def _resolve_symbol(self, native: dict[str, Any]) -> Optional[dict]:
        """§8.4/8.5/8.6 symbol resolution (verified / context / collision)."""
        symbol = self._symbol_token(native)
        if not symbol:
            return None
        candidates = await self.registry.resolve_asset(symbol)
        active = [a for a in candidates if a.get("status") == "active"]
        chain = native.get("chain")

        # 8.4 — exactly one ACTIVE asset under the symbol -> verified.
        if len(active) == 1:
            asset = active[0]
            # Enrich deployment when a chain is given and the asset has exactly
            # one active deployment there (deterministic; never picked by rank).
            deployment = None
            if chain:
                deps = await self._active_deployments_for(asset["id"], chain)
                if len(deps) == 1:
                    deployment = deps[0]
            return {
                "resolution_status": "resolved_symbol_verified",
                "asset": asset,
                "deployment": deployment,
            }

        # 8.5 — symbol + chain context, exactly one active candidate on-chain.
        if len(active) > 1 and chain:
            narrowed = []
            for asset in active:
                deps = await self._active_deployments_for(asset["id"], chain)
                if len(deps) == 1:
                    narrowed.append((asset, deps[0]))
            if len(narrowed) == 1:
                asset, deployment = narrowed[0]
                return {
                    "resolution_status": "resolved_symbol_context",
                    "asset": asset,
                    "deployment": deployment,
                }
            return {"unresolved": "ambiguous_symbol"}  # 8.6 collision

        # 8.6 — multiple candidates, nothing to disambiguate -> collision.
        if len(active) > 1:
            return {"unresolved": "ambiguous_symbol"}

        # Zero active candidates: symbol genuinely unknown to the registry.
        return {"unresolved": "unknown_symbol"}

    # ── top-level resolution ────────────────────────────────────────────────

    async def resolve(self, native: dict[str, Any]) -> dict[str, Any]:
        """Run the §8 priority and return a deterministic resolution report.

        A strategy outcome is either a resolved anchor (status in
        ``_RESOLVED_STATUSES``) or an authoritative failure carrying an
        UNRESOLVED_REASONS member. The first non-None outcome wins; failures are
        recorded before returning so nothing is ever silently dropped.
        """
        strategy_order = [
            self._resolve_chain_contract,
            self._resolve_namespaced_id,
            self._resolve_legacy_alias,
            self._resolve_symbol,
        ]
        outcome: Optional[dict] = None
        for strategy in strategy_order:
            outcome = await strategy(native)
            if outcome is not None:
                break

        if outcome is None:
            # No resolvable signal at all (empty payload) -> record malformed.
            return await self._unresolved_report(native, reason="malformed_reference")

        status = outcome.get("resolution_status")
        if status in _RESOLVED_STATUSES:
            return _report(
                native,
                resolution_status=status,
                asset=outcome.get("asset"),
                deployment=outcome.get("deployment"),
                registry_version=self._version,
            )

        # An authoritative failure. Map a symbol collision to its own status;
        # everything else is a recorded unresolved reference.
        reason = outcome.get("unresolved") or "no_registry_entry"
        if reason == "ambiguous_symbol":
            recorded = await self.registry.record_unresolved(
                raw_reference=self._raw_reference(native),
                reason=reason,
                tenant_id=self.tenant_id,
                evidence={"native": dict(native)},
            )
            return _report(
                native,
                resolution_status="collision_unresolvable",
                asset=None,
                deployment=None,
                registry_version=self._version,
                unresolved={"reason": reason, "recorded": recorded},
            )
        return await self._unresolved_report(native, reason=reason)

    async def canonicalize(self, native: dict[str, Any]) -> dict[str, Any]:
        """Canonicalize one NativeValue payload (report wrapper of ``resolve``)."""
        return await self.resolve(native)

    # ── raw reference (observational row identity) ──────────────────────────

    @staticmethod
    def _raw_reference(native: dict[str, Any]) -> str:
        """Most specific identity string available for the observational row."""
        aid = native.get("canonical_asset_id") or native.get("asset_id")
        if aid:
            return str(aid)
        contract = native.get("contract_or_mint")
        chain = native.get("chain")
        if chain and contract:
            return f"{chain}:{contract}"
        symbol = native.get("asset_symbol") or native.get("currency")
        if symbol:
            return str(symbol)
        return "unknown"
