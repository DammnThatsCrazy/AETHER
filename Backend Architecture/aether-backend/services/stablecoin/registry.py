"""Stablecoin canonical asset + deployment registry.

Canonical identity is (asset, deployment) — symbols are aliases, never ids.
Seeds derive from the x402 verification constants (the platform's existing
source of verified stablecoin contract addresses) so the registry can never
drift from what x402 actually verifies on-chain.
"""

from __future__ import annotations

from typing import Any, Optional

from repositories.stablecoin_repos import StablecoinAssetRepo, StablecoinDeploymentRepo
from services.stablecoin.foundation import make_event, utc_now_iso
from services.stablecoin.models import StablecoinAssetCanonical, StablecoinDeployment
from services.x402.verification import _ASSET_CONTRACT, _ASSET_DECIMALS, _CHAIN_TO_NETWORK

# Registry events are platform-scope: the sentinel tenant for global rows.
_PLATFORM_TENANT = "platform"


class StablecoinRegistry:
    def __init__(
        self,
        asset_repo: Optional[StablecoinAssetRepo] = None,
        deployment_repo: Optional[StablecoinDeploymentRepo] = None,
    ) -> None:
        self.assets = asset_repo or StablecoinAssetRepo()
        self.deployments = deployment_repo or StablecoinDeploymentRepo()

    # ── registration ───────────────────────────────────────────────────────

    async def register_asset(self, asset: StablecoinAssetCanonical) -> dict[str, Any]:
        record = asset.model_dump(exclude={"global_reference"})
        record["first_seen_at"] = record.get("first_seen_at") or utc_now_iso()
        inserted = await self.assets.insert(record)
        events = []
        if inserted:
            events.append(make_event(
                "stablecoin_asset_registered", _PLATFORM_TENANT,
                {"canonical_asset_id": asset.canonical_asset_id, "symbol": asset.symbol},
            ))
        return {"inserted": inserted, "emitted_events": events}

    async def register_deployment(self, deployment: StablecoinDeployment) -> dict[str, Any]:
        record = deployment.model_dump(exclude={"global_reference"})
        record["first_seen_at"] = record.get("first_seen_at") or utc_now_iso()
        inserted = await self.deployments.insert(record)
        events = []
        if inserted:
            events.append(make_event(
                "stablecoin_deployment_registered", _PLATFORM_TENANT,
                {
                    "deployment_id": deployment.deployment_id,
                    "canonical_asset_id": deployment.canonical_asset_id,
                    "chain_id": deployment.chain_id,
                    "contract_or_mint": deployment.contract_or_mint,
                },
            ))
        return {"inserted": inserted, "emitted_events": events}

    async def seed_canonical_assets(self) -> dict[str, Any]:
        """Seed canonical assets/deployments from the x402 verified contracts."""
        emitted: list[dict] = []
        inserted_assets = 0
        inserted_deployments = 0

        symbols = {symbol for symbol, _chain in _ASSET_CONTRACT}
        for symbol in sorted(symbols):
            asset = StablecoinAssetCanonical(
                canonical_asset_id=symbol.lower(),
                symbol=symbol,
                name=f"{symbol} (canonical)",
                issuer_name="Circle" if symbol == "USDC" else None,
                backing_model="fiat_reserve" if symbol == "USDC" else "unknown",
                pegged_to="USD",
            )
            result = await self.register_asset(asset)
            inserted_assets += int(result["inserted"])
            emitted.extend(result["emitted_events"])

        for (symbol, chain_id), contract in sorted(_ASSET_CONTRACT.items()):
            network = _CHAIN_TO_NETWORK.get(chain_id, chain_id)
            deployment = StablecoinDeployment(
                deployment_id=f"{symbol.lower()}:{chain_id}",
                canonical_asset_id=symbol.lower(),
                chain_id=chain_id,
                network=network,
                token_standard="spl" if chain_id.startswith("solana:") else "erc20",
                contract_or_mint=contract,
                decimals=_ASSET_DECIMALS.get(symbol, 6),
                deployment_type="canonical",
                issuer_verified=True,
                testnet="sepolia" in network or "devnet" in network,
            )
            result = await self.register_deployment(deployment)
            inserted_deployments += int(result["inserted"])
            emitted.extend(result["emitted_events"])

        return {
            "inserted_assets": inserted_assets,
            "inserted_deployments": inserted_deployments,
            "emitted_events": emitted,
        }

    # ── resolution ─────────────────────────────────────────────────────────

    async def resolve_deployment(
        self, chain_id: str, contract_or_mint: str,
    ) -> Optional[dict]:
        """Resolve a deployment by chain + contract. EVM addresses compare
        case-insensitively (checksummed vs lowercase forms are one identity);
        Solana mints are case-sensitive base58."""
        rows = await self.deployments.find_many({"chain_id": chain_id}, limit=500)
        needle = contract_or_mint.lower() if contract_or_mint.startswith("0x") else contract_or_mint
        for row in rows:
            candidate = row.get("contract_or_mint") or ""
            if candidate.startswith("0x"):
                if candidate.lower() == needle:
                    return row
            elif candidate == needle:
                return row
        return None

    async def get_deployment(self, deployment_id: str) -> Optional[dict]:
        return await self.deployments.find_one({"deployment_id": deployment_id})
