"""Universal asset registry facade — canonical assets, chains, deployments.

Generalizes the stablecoin domain's StablecoinRegistry to the universal
registry trunk (financial-normalization WP2/WP3): register_asset /
register_chain / register_fiat / register_deployment / register_alias,
deterministic seeding, chain+contract resolution and canonicalization of
value.ts-style native payloads through the UniversalAssetResolver.

Registry rows are authoritative global reference data — no tenant_id, no
execution_by_aether. The only tenant-scoped write is the observational
``record_unresolved`` (registry_unresolved_asset_refs): unknown references are
recorded explicitly, never silently guessed. AETHER OBSERVES. AETHER DOES NOT
EXECUTE.

Constructor injection mirrors StablecoinRegistry; every register method is an
idempotent upsert on canonical identity (typed repo INSERT .. ON CONFLICT ..
DO NOTHING) and returns dicts.
"""

from __future__ import annotations

from typing import Any, Optional, Union

from repositories.registry_repos import (
    RegistryAliasRepo,
    RegistryAssetRepo,
    RegistryCapabilityRepo,
    RegistryChainRepo,
    RegistryDeploymentRepo,
    RegistryFiatCurrencyRepo,
    RegistryMetaRepo,
    RegistryUnresolvedAssetRepo,
)
from services.assets import seeds
from services.assets.models import (
    AssetAlias,
    AssetDeployment,
    AssetSupportCapability,
    CanonicalAsset,
    ChainReference,
    FiatCurrencyMetadata,
)
from services.x402.verification import _CHAIN_TO_NETWORK

# Sentinel tenant for platform-scope global actions (mirrors the stablecoin
# registry's _PLATFORM_TENANT convention for non-tenant-scoped records).
_PLATFORM_TENANT = "platform"

# Single-row registry_meta identity.
_META_SINGLETON = "registry"


class UniversalAssetRegistry:
    def __init__(
        self,
        asset_repo: Optional[RegistryAssetRepo] = None,
        chain_repo: Optional[RegistryChainRepo] = None,
        fiat_repo: Optional[RegistryFiatCurrencyRepo] = None,
        deployment_repo: Optional[RegistryDeploymentRepo] = None,
        alias_repo: Optional[RegistryAliasRepo] = None,
        capability_repo: Optional[RegistryCapabilityRepo] = None,
        unresolved_repo: Optional[RegistryUnresolvedAssetRepo] = None,
        meta_repo: Optional[RegistryMetaRepo] = None,
    ) -> None:
        self.assets = asset_repo or RegistryAssetRepo()
        self.chains = chain_repo or RegistryChainRepo()
        self.fiats = fiat_repo or RegistryFiatCurrencyRepo()
        self.deployments = deployment_repo or RegistryDeploymentRepo()
        self.aliases = alias_repo or RegistryAliasRepo()
        self.capabilities = capability_repo or RegistryCapabilityRepo()
        self.unresolved = unresolved_repo or RegistryUnresolvedAssetRepo()
        self.meta = meta_repo or RegistryMetaRepo()

    # ── row <-> contract shape helpers ──────────────────────────────────────

    @staticmethod
    def _asset_to_contract(row: Optional[dict]) -> Optional[dict]:
        """Rename the DB column ``asset_id`` back to the contract field ``id``."""
        if row is None:
            return None
        out = dict(row)
        if "asset_id" in out:
            out["id"] = out.pop("asset_id")
        return out

    @staticmethod
    def _asset_record(asset: Union[CanonicalAsset, dict]) -> dict:
        """Validate a CanonicalAsset payload and produce a registry_assets row."""
        model = (
            asset if isinstance(asset, CanonicalAsset)
            else CanonicalAsset.model_validate(asset)
        )
        dump = model.model_dump(exclude_none=True)
        asset_id = dump.pop("id")
        return {"asset_id": asset_id, **dump}

    # ── registration (idempotent upsert on canonical identity) ─────────────

    async def register_asset(self, asset: Union[CanonicalAsset, dict]) -> dict[str, Any]:
        record = self._asset_record(asset)
        inserted = await self.assets.insert(record)
        return {
            "inserted": inserted,
            "asset_id": record["asset_id"],
            "symbol": record.get("symbol"),
            "kind": record.get("kind"),
        }

    async def register_chain(self, chain: Union[ChainReference, dict]) -> dict[str, Any]:
        model = (
            chain if isinstance(chain, ChainReference)
            else ChainReference.model_validate(chain)
        )
        record = model.model_dump(exclude_none=True)
        inserted = await self.chains.insert(record)
        return {
            "inserted": inserted,
            "chain_id": record["chain_id"],
            "name": record.get("name"),
        }

    async def register_fiat(self, fiat: Union[FiatCurrencyMetadata, dict]) -> dict[str, Any]:
        """Register an ISO 4217 fiat currency AND its ``fiat:<ISO>`` asset.

        A fiat currency is a canonical asset (fiat:USD) plus reference metadata
        (numeric_code / minor_units). Keeping the two halves together guarantees
        the fiat:* registry never points at an unregistered asset.
        """
        model = (
            fiat if isinstance(fiat, FiatCurrencyMetadata)
            else FiatCurrencyMetadata.model_validate(fiat)
        )
        record = model.model_dump()
        iso = record["iso_code"]
        asset_result = await self.register_asset(CanonicalAsset(
            id=seeds.fiat_asset_id(iso),
            kind="fiat",
            symbol=iso,
            name=record.get("name"),
            display_decimals=record.get("minor_units"),
            status="active",
        ))
        inserted = await self.fiats.insert(record)
        return {
            "inserted": inserted or asset_result["inserted"],
            "fiat_inserted": inserted,
            "asset_inserted": asset_result["inserted"],
            "iso_code": iso,
        }

    async def register_deployment(self, deployment: Union[AssetDeployment, dict]) -> dict[str, Any]:
        """Register one concrete on-chain / mint deployment.

        EVM contract_or_mint is normalized to lowercase and the deployment_id is
        always recomputed from (asset_id, chain_id, normalized contract) so the
        universal id scheme and the UNIQUE (chain_id, contract_or_mint) guard
        are consistent no matter the case a caller supplied.
        """
        model = (
            deployment if isinstance(deployment, AssetDeployment)
            else AssetDeployment.model_validate(deployment)
        )
        record = model.model_dump(exclude_none=True)
        contract = seeds.normalize_contract_or_mint(record["contract_or_mint"])
        record["contract_or_mint"] = contract
        record["deployment_id"] = seeds.asset_deployment_id(
            record["asset_id"], record["chain_id"], contract,
        )
        inserted = await self.deployments.insert(record)
        return {
            "inserted": inserted,
            "deployment_id": record["deployment_id"],
            "asset_id": record["asset_id"],
            "chain_id": record["chain_id"],
            "contract_or_mint": contract,
        }

    async def register_alias(self, alias: Union[AssetAlias, dict]) -> dict[str, Any]:
        """Register a legacy id / symbol alias -> canonical target.

        Alias text is stored lowercase so alias resolution is case-insensitive
        and the PK never splits one spelling across two rows.
        """
        model = (
            alias if isinstance(alias, AssetAlias)
            else AssetAlias.model_validate(alias)
        )
        record = model.model_dump(exclude_none=True)
        record["alias"] = record["alias"].lower()
        record.setdefault("verification", "unverified")
        inserted = await self.aliases.insert(record)
        return {
            "inserted": inserted,
            "alias": record["alias"],
            "target_asset_id": record["target_asset_id"],
            "target_deployment_id": record.get("target_deployment_id"),
        }

    async def register_capability(
        self,
        capability: Union[AssetSupportCapability, dict],
    ) -> dict[str, Any]:
        model = (
            capability if isinstance(capability, AssetSupportCapability)
            else AssetSupportCapability.model_validate(capability)
        )
        record = model.model_dump(exclude_none=True)
        capability_id = RegistryCapabilityRepo.capability_key(
            capability=record["capability"],
            asset_id=record.get("asset_id"),
            deployment_id=record.get("deployment_id"),
        )
        record["capability_id"] = capability_id
        inserted = await self.capabilities.insert(record)
        return {
            "inserted": inserted,
            "capability_id": capability_id,
            "capability": record["capability"],
        }

    # ── reference reads / resolution ────────────────────────────────────────

    async def get_asset(self, asset_id: str) -> Optional[dict]:
        row = await self.assets.find_one({"asset_id": asset_id})
        return self._asset_to_contract(row)

    async def resolve_asset(self, symbol: str) -> list[dict]:
        """Return every canonical asset whose symbol matches (case-insensitive).

        May return multiple candidates — a bare symbol never canonically
        identifies one asset; the resolver decides collisions explicitly.
        """
        if not symbol:
            return []
        needle = symbol.lower()
        rows = await self.assets.find_many(limit=10000)
        return [
            self._asset_to_contract(row)
            for row in rows
            if str(row.get("symbol") or "").lower() == needle
        ]

    async def get_chain(self, chain_id: str) -> Optional[dict]:
        return await self.chains.find_one({"chain_id": chain_id})

    async def resolve_chain(self, chain_id: str) -> Optional[dict]:
        return await self.chains.find_one({"chain_id": chain_id})

    async def get_deployment(self, deployment_id: str) -> Optional[dict]:
        return await self.deployments.find_one({"deployment_id": deployment_id})

    async def resolve_deployment(
        self, chain_id: str, contract_or_mint: str,
    ) -> Optional[dict]:
        """Resolve a deployment by chain + contract.

        EVM addresses compare case-insensitively (checksummed vs lowercase forms
        are one identity); Solana mints are case-sensitive base58. Mirrors
        StablecoinRegistry.resolve_deployment.
        """
        rows = await self.deployments.find_many({"chain_id": chain_id}, limit=10000)
        needle = contract_or_mint.lower() if contract_or_mint.startswith("0x") else contract_or_mint
        for row in rows:
            candidate = row.get("contract_or_mint") or ""
            if candidate.startswith("0x"):
                if candidate.lower() == needle:
                    return row
            elif candidate == needle:
                return row
        return None

    async def resolve_alias(self, alias: str) -> Optional[dict]:
        """Resolve a (case-insensitive) alias row to its canonical target."""
        if not alias:
            return None
        return await self.aliases.find_one({"alias": alias.lower()})

    async def record_unresolved(
        self,
        raw_reference: str,
        reason: str,
        *,
        tenant_id: Optional[str] = None,
        evidence: Optional[dict] = None,
        seen_at: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record one unresolved raw reference sighting (tenant-scoped).

        Unknown is explicit and recorded — never guessed. Tenant-less sightings
        are attributed to the platform sentinel so the observational table's
        NOT NULL tenant_id holds. Re-seen references bump occurrence_count.
        """
        tenant = tenant_id or _PLATFORM_TENANT
        return await self.unresolved.record_unresolved(
            tenant_id=tenant,
            raw_reference=raw_reference,
            reason=reason,
            evidence=evidence,
            seen_at=seen_at,
        )

    # ── deterministic registry versioning ───────────────────────────────────

    @staticmethod
    def current_registry_version() -> str:
        """Deterministic sha256 over the sorted canonical seed content.

        Never a wall-clock timestamp: identical registry seed states always
        hash to one version (financial-normalization §6/§10). Valuations and
        graph projections cite this version as their registry provenance.
        """
        return seeds.registry_version()

    async def get_meta(self) -> Optional[dict]:
        return await self.meta.find_one({"meta_id": _META_SINGLETON})

    async def _store_meta(self, counts: dict[str, int]) -> dict[str, Any]:
        version = self.current_registry_version()
        record = {
            "meta_id": _META_SINGLETON,
            "registry_version": version,
            "algorithm": "sha256",
            "asset_count": counts.get("asset_count", 0),
            "chain_count": counts.get("chain_count", 0),
            "deployment_count": counts.get("deployment_count", 0),
            "fiat_count": counts.get("fiat_count", 0),
            "alias_count": counts.get("alias_count", 0),
        }
        await self.meta.insert(record)
        return {"meta_id": _META_SINGLETON, "registry_version": version}

    # ── seeding / canonicalization ──────────────────────────────────────────

    async def seed_all(self) -> dict[str, Any]:
        """Seed fiat -> chains (+native crypto) -> stablecoins + legacy aliases.

        Idempotent: every register is an upsert on canonical identity, so
        re-running reproduces identical registry state and the same
        deterministic registry_version. The version ledger row is written from
        the deterministic digest, never from a wall-clock timestamp.
        """
        from services.assets.seeder import UniversalAssetSeeder

        seeder = UniversalAssetSeeder(registry=self)
        summary = await seeder.seed_all()
        meta = await self._store_meta(summary)
        summary["registry_version"] = meta["registry_version"]
        return summary

    async def canonicalize(
        self, native: dict, *, tenant_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Map a value.ts-style native payload onto canonical identity.

        Resolution follows the registry resolver priority (resolver.py); the
        original native payload is preserved verbatim — canonicalization never
        rewrites the observed amount/currency. When identity cannot be resolved
        the reference is recorded unresolved and the source stays valid with
        canonical_asset_id absent (never guessed).
        """
        from services.assets.resolver import UniversalAssetResolver

        resolver = UniversalAssetResolver(registry=self, tenant_id=tenant_id)
        return await resolver.canonicalize(native)

    @staticmethod
    def supported_chains() -> list[str]:
        """Chain ids x402 currently verifies on (seed surface, informational)."""
        return sorted(_CHAIN_TO_NETWORK)
