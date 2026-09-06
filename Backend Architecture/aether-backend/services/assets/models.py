"""Asset / chain registry contracts — Pydantic v2 mirror of packages/shared/financial-assets.ts.

Universal financial normalization (C1) registry trunk: chain references, fiat
currency reference data, canonical assets, deployments, aliases, unresolved
references and support-capability claims. Field names are snake_case exactly as
in the TypeScript contract; enum fields are Literal unions whose members match
the runtime arrays in financial-assets.ts byte-for-byte.

Frozenset ownership (future parity validator compares each TS union against
exactly one Python frozenset of identical snake_case strings):
  OWNED HERE:  ASSET_KINDS, CHAIN_STATUSES, RESOLUTION_STATUSES,
               ALIAS_VERIFICATION_STATUSES, UNRESOLVED_REASONS
  OWNED BY services/valuation/models.py (NOT duplicated here):
               ECONOMIC_ROLES, PRICE_STATUSES, VALUATION_BASIS,
               VALUATION_METHOD_EXTENDED

Stablecoin deployment-type members (canonical | bridged | wrapped | synthetic
| deprecated | counterfeit_suspected | unknown) are REUSED from
services/stablecoin/models.py — the same union the TS side reuses from
stablecoin-intelligence.ts; never redeclared in this module.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from services.stablecoin.models import StablecoinDeploymentType

# ── Frozensets (parity surface with financial-assets.ts runtime arrays) ──────

ASSET_KINDS = frozenset({"fiat", "crypto", "stablecoin", "token"})
CHAIN_STATUSES = frozenset({"active", "deprecated", "paused", "under_review"})
RESOLUTION_STATUSES = frozenset({
    "resolved_chain_contract", "resolved_namespaced_id", "resolved_legacy_alias",
    "resolved_symbol_verified", "resolved_symbol_context",
    "collision_unresolvable", "unresolved_recorded",
})
ALIAS_VERIFICATION_STATUSES = frozenset({
    "verified", "unverified", "contested", "retired",
})
UNRESOLVED_REASONS = frozenset({
    "unknown_symbol", "ambiguous_symbol", "unknown_chain", "unknown_contract",
    "no_registry_entry", "malformed_reference",
})

# ── Literal unions (mirror financial-assets.ts unions) ───────────────────────

AssetKind = Literal["fiat", "crypto", "stablecoin", "token"]
ChainStatus = Literal["active", "deprecated", "paused", "under_review"]
ResolutionStatus = Literal[
    "resolved_chain_contract", "resolved_namespaced_id", "resolved_legacy_alias",
    "resolved_symbol_verified", "resolved_symbol_context",
    "collision_unresolvable", "unresolved_recorded",
]
AliasVerificationStatus = Literal["verified", "unverified", "contested", "retired"]
UnresolvedReason = Literal[
    "unknown_symbol", "ambiguous_symbol", "unknown_chain", "unknown_contract",
    "no_registry_entry", "malformed_reference",
]

# A canonical asset id / deployment id are opaque strings in the registry;
# their naming convention (fiat:<ISO>, crypto:<SYMBOL>, stablecoin:<SYMBOL>,
# token:<chain>:<contract>, deploy:<asset_id>@<chain>:<contract>) is enforced by
# the resolution pipeline, not re-validated here.


# ── Registry models ──────────────────────────────────────────────────────────

class ChainReference(BaseModel):
    """A registered chain (CAIP-2 style chain_id, e.g. ``eip155:8453``)."""

    model_config = ConfigDict(extra="forbid")

    chain_id: str
    name: str
    network: Optional[str] = None  # mainnet / testnet / devnet (registry data)
    status: ChainStatus = "active"
    vm: str  # evm / svm / ...
    native_currency: str  # namespaced asset id, e.g. crypto:ETH
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    deprecated_at: Optional[str] = None


class FiatCurrencyMetadata(BaseModel):
    """ISO 4217 fiat reference data row (numeric_code keeps leading zeros)."""

    model_config = ConfigDict(extra="forbid")

    iso_code: str
    numeric_code: str = Field(pattern=r"^\d{3}$")
    minor_units: int = Field(ge=0, le=4)
    name: str
    symbol: str


class CanonicalAsset(BaseModel):
    """A canonical asset registry row. id is namespaced identity; symbol is an
    alias for display / legacy matching — never canonical identity."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: AssetKind
    symbol: str
    name: Optional[str] = None
    issuer: Optional[str] = None
    display_decimals: Optional[int] = Field(default=None, ge=0, le=36)
    status: ChainStatus = "active"


class AssetDeployment(BaseModel):
    """A concrete on-chain / mint deployment (``deploy:<asset_id>@<chain>:<contract>``)."""

    model_config = ConfigDict(extra="forbid")

    deployment_id: str
    asset_id: str
    chain_id: str
    contract_or_mint: str
    decimals: int = Field(ge=0, le=36)
    # Reuses the stablecoin deployment-type vocabulary (canonical/bridged/
    # wrapped/synthetic/deprecated/counterfeit_suspected/unknown).
    canonical_vs_bridged: StablecoinDeploymentType = "unknown"
    deployment_status: ChainStatus = "active"
    token_standard: Optional[str] = None  # erc20 / bep20 / native / ...
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    deprecated_at: Optional[str] = None


class AssetAlias(BaseModel):
    """Legacy id / symbol -> canonical target mapping. Legacy ids such as
    ``usdc`` are bridged by these rows, never rewritten in place."""

    model_config = ConfigDict(extra="forbid")

    alias: str
    target_asset_id: str
    target_deployment_id: Optional[str] = None
    verification: AliasVerificationStatus = "unverified"
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    note: Optional[str] = None


class UnresolvedAssetReference(BaseModel):
    """A raw reference that could not be resolved. Unknown is explicit and
    recorded — never silently guessed."""

    model_config = ConfigDict(extra="forbid")

    raw_reference: str
    tenant_id: Optional[str] = None
    reason: UnresolvedReason
    first_seen_at: str
    last_seen_at: str
    occurrence_count: Optional[int] = Field(default=None, ge=1)


class AssetSupportCapability(BaseModel):
    """Claim that an asset / deployment is usable as a given deployment nature.
    At least one of asset_id / deployment_id should identify the subject."""

    model_config = ConfigDict(extra="forbid")

    asset_id: Optional[str] = None
    deployment_id: Optional[str] = None
    capability: StablecoinDeploymentType
