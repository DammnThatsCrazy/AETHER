"""Universal asset registry — canonical seed reference data and builders.

Pure-data mirror of packages/shared/financial-assets.ts (FIAT_REFERENCE_SEED)
plus the deterministic seed rows the registry seeder writes:

  - fiat currencies / fiat:* canonical assets  (16 ISO 4217 rows)
  - chains                                   (from services/x402 _CHAIN_TO_NETWORK)
  - crypto native assets + native deployments (chain native_currency rows)
  - stablecoin assets/deployments             (from x402 _ASSET_CONTRACT /
                                              _ASSET_DECIMALS — the platform's
                                              verified source, so the registry
                                              can never drift from what x402
                                              verifies on-chain)
  - legacy aliases                           (bridging the stablecoin domain's
                                              today-identifiers WITHOUT rewriting
                                              them: "usdc", "usdc:eip155:8453")

Every builder is a pure function of committed constants — the seeder and the
deterministic ``registry_version`` share these builders, so identical seed
content always hashes to one version (never a wall-clock timestamp). No
function here touches a database.

Record shapes are the Pydantic contract shapes from services/assets/models.py:
CanonicalAsset rows keyed ``id`` (not the DB column ``asset_id``); other rows
keyed exactly as their contracts. The facade maps ``id`` <-> ``asset_id`` at
the repository boundary.
"""

from __future__ import annotations

import hashlib
from typing import Any

from services.x402.verification import _ASSET_CONTRACT, _ASSET_DECIMALS, _CHAIN_TO_NETWORK

# ── Helpers ──────────────────────────────────────────────────────────────────

# Namespace prefixes a canonical asset id may carry (mirror ASSET_KINDS).
_NAMESPACED_PREFIXES = ("fiat:", "crypto:", "stablecoin:", "token:")


def normalize_contract_or_mint(value: str) -> str:
    """Canonical registry spelling for contract_or_mint.

    EVM addresses compare case-insensitively (checksummed vs lowercase forms
    are one identity) so they are stored lowercased — this guarantees the
    UNIQUE (chain_id, contract_or_mint) deployment guard holds regardless of
    the case a seed/observer supplied. Solana mints (base58, case-sensitive)
    are returned verbatim. Mirrors StablecoinRegistry.resolve_deployment.
    """
    if value and value.startswith("0x"):
        return value.lower()
    return value


def is_evm_contract_or_mint(value: str) -> bool:
    return bool(value) and value.startswith("0x")


def is_namespaced_asset_id(value: str) -> bool:
    """Syntactic check for a canonical namespaced asset id (no registry read).

    Accepts ``fiat:USD``, ``crypto:ETH``, ``stablecoin:USDC`` and
    ``token:<chain>:<contract>`` (the token chain segment may itself contain a
    colon, e.g. ``token:eip155:8453:0x...``). Mirrors the TS
    ``isNamespacedAssetId`` helper; existence is verified against the registry.
    """
    if not isinstance(value, str) or not value:
        return False
    colon = value.find(":")
    if colon <= 0:
        return False
    ns = value[:colon]
    rest = value[colon + 1:]
    if ns not in {"fiat", "crypto", "stablecoin", "token"}:
        return False
    if not rest:
        return False
    if ns == "token":
        # token:<chain>:<contract> requires a second colon inside rest.
        inner = rest.find(":")
        return inner > 0 and not rest.endswith(":")
    return True


def asset_deployment_id(asset_id: str, chain_id: str, contract_or_mint: str) -> str:
    """Canonical deployment id: ``deploy:<asset_id>@<chain>:<contract>``."""
    return f"deploy:{asset_id}@{chain_id}:{contract_or_mint}"


def fiat_asset_id(iso_code: str) -> str:
    return f"fiat:{iso_code}"


# ── ISO 4217 reference seed (mirror of FIAT_REFERENCE_SEED in
#    packages/shared/financial-assets.ts) ─────────────────────────────────────

FIAT_CURRENCIES: tuple[dict[str, Any], ...] = (
    {"iso_code": "USD", "numeric_code": "840", "minor_units": 2, "name": "US Dollar", "symbol": "$"},
    {"iso_code": "EUR", "numeric_code": "978", "minor_units": 2, "name": "Euro", "symbol": "€"},
    {"iso_code": "GBP", "numeric_code": "826", "minor_units": 2, "name": "British Pound", "symbol": "£"},
    {"iso_code": "JPY", "numeric_code": "392", "minor_units": 0, "name": "Japanese Yen", "symbol": "¥"},
    {"iso_code": "CNY", "numeric_code": "156", "minor_units": 2, "name": "Chinese Yuan", "symbol": "¥"},
    {"iso_code": "AUD", "numeric_code": "036", "minor_units": 2, "name": "Australian Dollar", "symbol": "A$"},
    {"iso_code": "CAD", "numeric_code": "124", "minor_units": 2, "name": "Canadian Dollar", "symbol": "C$"},
    {"iso_code": "CHF", "numeric_code": "756", "minor_units": 2, "name": "Swiss Franc", "symbol": "CHF"},
    {"iso_code": "HKD", "numeric_code": "344", "minor_units": 2, "name": "Hong Kong Dollar", "symbol": "HK$"},
    {"iso_code": "SGD", "numeric_code": "702", "minor_units": 2, "name": "Singapore Dollar", "symbol": "S$"},
    {"iso_code": "SEK", "numeric_code": "752", "minor_units": 2, "name": "Swedish Krona", "symbol": "kr"},
    {"iso_code": "NOK", "numeric_code": "578", "minor_units": 2, "name": "Norwegian Krone", "symbol": "kr"},
    {"iso_code": "NZD", "numeric_code": "554", "minor_units": 2, "name": "New Zealand Dollar", "symbol": "NZ$"},
    {"iso_code": "KRW", "numeric_code": "410", "minor_units": 0, "name": "South Korean Won", "symbol": "₩"},
    {"iso_code": "MXN", "numeric_code": "484", "minor_units": 2, "name": "Mexican Peso", "symbol": "Mex$"},
    {"iso_code": "INR", "numeric_code": "356", "minor_units": 2, "name": "Indian Rupee", "symbol": "₹"},
)


def fiat_currency_rows() -> list[dict[str, Any]]:
    """ISO 4217 metadata rows (registry_fiat_currencies payloads)."""
    return [dict(row) for row in FIAT_CURRENCIES]


def fiat_asset_rows() -> list[dict[str, Any]]:
    """CanonicalAsset rows for every seeded fiat currency (fiat:<ISO>)."""
    rows: list[dict[str, Any]] = []
    for cur in FIAT_CURRENCIES:
        iso = cur["iso_code"]
        rows.append({
            "id": fiat_asset_id(iso),
            "kind": "fiat",
            "symbol": iso,
            "name": cur["name"],
            "issuer": None,
            "display_decimals": cur["minor_units"],
            "status": "active",
        })
    return rows


# ── Chain reference seed (x402 _CHAIN_TO_NETWORK chains, enriched metadata) ─

# Chain_id -> (name, public-network, vm, native_currency asset id). Native
# currency names are the registry's canonical crypto asset ids (crypto:ETH /
# crypto:SOL) and are seeded alongside the chain so native_currency resolves.
_CHAIN_META: dict[str, tuple[str, str, str, str]] = {
    "eip155:8453":    ("Base",       "mainnet", "evm", "crypto:ETH"),
    "eip155:84532":   ("Base",       "testnet", "evm", "crypto:ETH"),
    "solana:mainnet": ("Solana",     "mainnet", "svm", "crypto:SOL"),
    "solana:devnet":  ("Solana",     "devnet",  "svm", "crypto:SOL"),
}


def chain_rows() -> list[dict[str, Any]]:
    """ChainReference rows seeded from the x402 network map.

    Only chains with committed metadata are seeded — chain metadata is never
    guessed. Every chain present in _CHAIN_TO_NETWORK today is covered.
    """
    rows: list[dict[str, Any]] = []
    for chain_id in _CHAIN_TO_NETWORK:
        meta = _CHAIN_META.get(chain_id)
        if meta is None:
            continue
        name, network, vm, native_currency = meta
        rows.append({
            "chain_id": chain_id,
            "name": name,
            "network": network,
            "status": "active",
            "vm": vm,
            "native_currency": native_currency,
        })
    return rows


def _chain_native_asset_rows() -> list[dict[str, Any]]:
    """CanonicalAsset rows for the crypto native currencies referenced above."""
    display: dict[str, int] = {"crypto:ETH": 18, "crypto:SOL": 9}
    names: dict[str, str] = {
        "crypto:ETH": "Ether",
        "crypto:SOL": "Solana",
    }
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for chain in chain_rows():
        native_id = chain["native_currency"]
        if native_id in seen:
            continue
        seen.add(native_id)
        symbol = native_id.split(":", 1)[1]
        rows.append({
            "id": native_id,
            "kind": "crypto",
            "symbol": symbol,
            "name": names.get(native_id, symbol),
            "issuer": None,
            "display_decimals": display.get(native_id),
            "status": "active",
        })
    return rows


def native_asset_rows() -> list[dict[str, Any]]:
    return _chain_native_asset_rows()


def native_deployment_rows() -> list[dict[str, Any]]:
    """AssetDeployment rows for each chain's native currency.

    A native currency deploys as the chain's native sentinel
    (``contract_or_mint="native"``, token_standard ``native``) — one row per
    chain the currency is native on.
    """
    rows: list[dict[str, Any]] = []
    for chain in chain_rows():
        native_id = chain["native_currency"]
        symbol = native_id.split(":", 1)[1]
        decimals = 18 if symbol == "ETH" else (9 if symbol == "SOL" else 0)
        chain_id = chain["chain_id"]
        rows.append({
            "deployment_id": asset_deployment_id(native_id, chain_id, "native"),
            "asset_id": native_id,
            "chain_id": chain_id,
            "contract_or_mint": "native",
            "decimals": decimals,
            "canonical_vs_bridged": "canonical",
            "deployment_status": "active",
            "token_standard": "native",
        })
    return rows


# ── Stablecoin seed (x402 verified contracts — mirror of the stablecoin
#    domain's seed_canonical_assets; deployment ids use the UNIVERSAL id
#    scheme, and legacy stablecoin-domain ids are bridged via alias rows) ─────

_STABLECOIN_NAMES: dict[str, str] = {
    "USDC": "USD Coin",
    "USDT": "Tether USD",
}
_STABLECOIN_ISSUERS: dict[str, str] = {
    "USDC": "Circle Internet Financial",
    "USDT": "Tether",
}


def _stablecoin_symbols() -> list[str]:
    return sorted({symbol for symbol, _chain in _ASSET_CONTRACT})


def stablecoin_asset_rows() -> list[dict[str, Any]]:
    """CanonicalAsset rows for every stablecoin symbol x402 verifies."""
    rows: list[dict[str, Any]] = []
    for symbol in _stablecoin_symbols():
        decimals = _ASSET_DECIMALS.get(symbol)
        if decimals is None:
            # Unknown decimal precision is never defaulted — mirror x402's
            # AssetDecimalsError stance (an unknown asset is a hard error).
            raise ValueError(
                f"decimals for stablecoin {symbol!r} are not declared in x402 "
                "_ASSET_DECIMALS; refusing to seed with a guess"
            )
        rows.append({
            "id": f"stablecoin:{symbol}",
            "kind": "stablecoin",
            "symbol": symbol,
            "name": _STABLECOIN_NAMES.get(symbol, f"{symbol} Stablecoin"),
            "issuer": _STABLECOIN_ISSUERS.get(symbol),
            "display_decimals": decimals,
            "status": "active",
        })
    return rows


def stablecoin_deployment_rows() -> list[dict[str, Any]]:
    """AssetDeployment rows for every (symbol, chain) x402 verifies.

    canonical_vs_bridged mirrors the stablecoin domain's own seeder, which
    marks every x402 deployment ``canonical`` (issuer-verified contract
    addresses). EVM contract_or_mint is stored lowercased.
    """
    rows: list[dict[str, Any]] = []
    for (symbol, chain_id), contract in sorted(_ASSET_CONTRACT.items()):
        decimals = _ASSET_DECIMALS.get(symbol)
        if decimals is None:
            raise ValueError(
                f"decimals for stablecoin {symbol!r} are not declared in x402 "
                "_ASSET_DECIMALS; refusing to seed with a guess"
            )
        asset_id = f"stablecoin:{symbol}"
        contract_key = normalize_contract_or_mint(contract)
        rows.append({
            "deployment_id": asset_deployment_id(asset_id, chain_id, contract_key),
            "asset_id": asset_id,
            "chain_id": chain_id,
            "contract_or_mint": contract_key,
            "decimals": decimals,
            "canonical_vs_bridged": "canonical",
            "deployment_status": "active",
            "token_standard": "spl" if chain_id.startswith("solana:") else "erc20",
        })
    return rows


def stablecoin_alias_rows() -> list[dict[str, Any]]:
    """AssetAlias rows bridging the stablecoin domain's today-identifiers.

    The stablecoin domain (services/stablecoin) keys its canonical assets by
    lowercased symbol (``usdc``) and its deployments by
    ``{symbol.lower()}:{chain_id}`` (``usdc:eip155:8453``). Those identifiers
    are bridged — never rewritten — to universal ids:
      - ``usdc``                     -> stablecoin:USDC
      - ``usdc:<chain_id>``          -> stablecoin:USDC + the universal deployment
    """
    rows: list[dict[str, Any]] = []
    for symbol in _stablecoin_symbols():
        asset_id = f"stablecoin:{symbol}"
        rows.append({
            "alias": symbol.lower(),
            "target_asset_id": asset_id,
            "target_deployment_id": None,
            "verification": "verified",
            "note": "legacy stablecoin-domain canonical asset id (symbol.lower())",
        })
    for (symbol, chain_id), contract in sorted(_ASSET_CONTRACT.items()):
        asset_id = f"stablecoin:{symbol}"
        contract_key = normalize_contract_or_mint(contract)
        deployment_id = asset_deployment_id(asset_id, chain_id, contract_key)
        rows.append({
            "alias": f"{symbol.lower()}:{chain_id}",
            "target_asset_id": asset_id,
            "target_deployment_id": deployment_id,
            "verification": "verified",
            "note": "legacy stablecoin-domain deployment id",
        })
    return rows


# Native symbol aliases: a bare ``ETH`` / ``SOL`` in a payload is an alias for
# the canonical crypto native asset (AssetAlias documents bare-symbol aliases).
def native_alias_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for asset in native_asset_rows():
        symbol = asset["symbol"]
        rows.append({
            "alias": symbol,
            "target_asset_id": asset["id"],
            "target_deployment_id": None,
            "verification": "verified",
            "note": "canonical crypto native symbol alias",
        })
    return rows


def alias_rows() -> list[dict[str, Any]]:
    return stablecoin_alias_rows() + native_alias_rows()


# ── Deterministic registry_version (never wall-clock) ────────────────────────

def _deployment_rows() -> list[dict[str, Any]]:
    return native_deployment_rows() + stablecoin_deployment_rows()


def seed_content_keys() -> list[str]:
    """Sorted canonical keys the deterministic registry_version hashes.

    Keys enumerate exactly the rows seed_all writes: one key per asset id,
    chain id, deployment id and alias mapping. Sorting makes the digest stable
    regardless of iteration order.
    """
    keys: list[str] = []
    for asset in fiat_asset_rows() + native_asset_rows() + stablecoin_asset_rows():
        keys.append(asset["id"])
    for chain in chain_rows():
        keys.append(f"chain:{chain['chain_id']}")
    for deployment in _deployment_rows():
        keys.append(deployment["deployment_id"])
    for alias in alias_rows():
        tail = alias["target_deployment_id"] or alias["target_asset_id"]
        keys.append(f"alias:{alias['alias']}->{tail}")
    return sorted(set(keys))


def registry_version() -> str:
    """Deterministic sha256 over the sorted seed content keys."""
    basis = "\n".join(seed_content_keys())
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def seed_count_snapshot() -> dict[str, int]:
    """Row counts the meta ledger records after a full seed."""
    deployments = _deployment_rows()
    return {
        "asset_count": len(fiat_asset_rows() + native_asset_rows() + stablecoin_asset_rows()),
        "chain_count": len(chain_rows()),
        "deployment_count": len(deployments),
        "fiat_count": len(fiat_currency_rows()),
        "alias_count": len(alias_rows()),
    }


# Re-export for callers that only need a stable version digest.
current_registry_version = registry_version
