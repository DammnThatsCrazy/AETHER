#!/usr/bin/env python3
"""Validate universal financial-asset normalization invariants (TS + Python).

Release-blocking gate for the Universal Financial Normalization program
(WP2/WP3 registry + event-time valuation). Enforces, statically:

  - the canonical shared contract exists (packages/shared/financial-assets.ts)
    with the namespaced identity + deployment vocabulary, and value.ts carries
    the additive reporting/display seam (reporting_asset_id / reporting_amount,
    reporting_totals / value_lineage, CanonicalNativeValue + guards);
  - the backend mirrors exist (services/assets, services/valuation) and the
    canonical stablecoin read seam (services/stablecoin/canonical_identity.py)
    is present so the registry reuses it rather than re-deriving identity;
  - canonical ids are namespace-safe (``fiat:`` / ``crypto:`` / ``stablecoin:``
    / ``token:``; deployments ``deploy:``) — symbols are aliases, never identity
    — and legacy stablecoin ids are preserved as aliases, never rewritten;
  - money is Decimal / NUMERIC(38, 18), never binary float, in the canonical
    tables (financial migrations introduce no FLOAT/REAL money column) and the
    typed-repo ``as_decimal`` rejects float transit;
  - valuation snapshots are immutable (append-only with the supersede
    back-pointer/status carve-out), observations refuse in-place updates, and
    persisted rows are observation-only (execution_by_aether always False);
  - reporting_amount NULL means UNAVAILABLE — the canonical models never coerce
    an absent valuation to 0;
  - registry seeds are complete vs the x402 stablecoin universe (USDC/USDT,
    Base/Solana chains, native crypto:ETH) and the registry version is a
    deterministic sha256, never a wall-clock timestamp.

This is a static/contract gate — no services required.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "Backend Architecture" / "aether-backend"

FINANCIAL_TS = ROOT / "packages" / "shared" / "financial-assets.ts"
VALUE_TS = ROOT / "packages" / "shared" / "value.ts"
ASSETS_MODELS_PY = BACKEND / "services" / "assets" / "models.py"
ASSETS_SEEDS_PY = BACKEND / "services" / "assets" / "seeds.py"
ASSETS_REGISTRY_PY = BACKEND / "services" / "assets" / "registry.py"
VALUATION_MODELS_PY = BACKEND / "services" / "valuation" / "models.py"
VALUATION_SERVICE_PY = BACKEND / "services" / "valuation" / "service.py"
VALUATION_REPOS_PY = BACKEND / "services" / "valuation" / "repositories.py"
STABLECOIN_IDENTITY_PY = BACKEND / "services" / "stablecoin" / "canonical_identity.py"
TYPED_REPO_PY = BACKEND / "repositories" / "typed_repo.py"
FINANCIAL_MIGRATIONS = sorted(BACKEND.glob("alembic/versions/20260902_*.py"))

ERRORS: list[str] = []


def fail(msg: str) -> None:
    ERRORS.append(msg)


def _has(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def _require_file(path: Path) -> str | None:
    if not path.exists():
        fail(f"missing canonical surface {path.relative_to(ROOT)}")
        return None
    return path.read_text(encoding="utf-8")


def main() -> int:
    # 1. Canonical shared contract (TS) — namespaced identity + deployment vocab.
    fa = _require_file(FINANCIAL_TS)
    if fa is not None:
        for sym in (
            "AssetKind", "ChainReference", "FiatCurrencyMetadata", "CanonicalAsset",
            "AssetDeployment", "AssetAlias", "UnresolvedAssetReference",
            "AssetSupportCapability", "MarketPriceObservation", "ValuationSnapshot",
        ):
            if f"export interface {sym}" not in fa and f"export type {sym}" not in fa:
                fail(f"packages/shared/financial-assets.ts missing export {sym}")
        for token in ("fiat:", "crypto:", "stablecoin:", "token:", "deploy:"):
            if token not in fa:
                fail(
                    "packages/shared/financial-assets.ts must state the canonical "
                    f"identity namespace (missing literal {token!r})"
                )

    # 2. value.ts additive reporting/display seam (financial-normalization W4a).
    vt = _require_file(VALUE_TS)
    if vt is not None:
        for decl in (
            "canonical_asset_id",  # NativeValue canonical id (optional)
            "deployment_id",       # NativeValue deployment id (optional)
            "economic_role",       # NativeValue economic role (optional)
            "reporting_asset_id",  # USDValuation reporting asset id (optional)
            "reporting_amount",    # USDValuation reporting amount (optional)
            "reporting_totals",    # RollupResult reporting-asset-keyed totals
            "value_lineage",       # RollupResult opt-in provenance
        ):
            if decl not in vt:
                fail(f"packages/shared/value.ts missing additive field/decl {decl!r}")
        for sym in ("CanonicalNativeValue", "isCanonicalNativeValue", "assertCanonicalNative"):
            if f"export {('interface' if sym == 'CanonicalNativeValue' else 'function')} {sym}" not in vt:
                fail(f"packages/shared/value.ts missing export {sym}")

    # 3. Backend mirrors exist (services/assets + services/valuation).
    am = _require_file(ASSETS_MODELS_PY)
    if am is not None:
        for sym in ("CanonicalAsset", "AssetDeployment", "AssetAlias", "UnresolvedAssetReference"):
            if f"class {sym}" not in am:
                fail(f"services/assets/models.py missing class {sym}")
        # Namespace-safe identity is the enforced convention (symbols are aliases).
        if "fiat:<ISO>" not in am or "stablecoin:<SYMBOL>" not in am:
            fail(
                "services/assets/models.py must state the namespaced-id convention "
                "(fiat:<ISO>, crypto:<SYMBOL>, stablecoin:<SYMBOL>, token:<chain>:<contract>)"
            )

    vm = _require_file(VALUATION_MODELS_PY)
    if vm is not None:
        for sym in ("MarketPriceObservation", "ValuationSnapshot", "TenantValuePolicy", "CanonicalNativeValue"):
            if f"class {sym}" not in vm:
                fail(f"services/valuation/models.py missing class {sym}")
        # reporting_amount None = UNAVAILABLE, never coerced to 0.
        if "reporting_amount: Optional[Decimal]" not in vm:
            fail("services/valuation/models.py missing Optional reporting_amount (None = UNAVAILABLE)")
        for guard in ("_decimal_or_error", "_optional_decimal"):
            if guard not in vm:
                fail(f"services/valuation/models.py missing {guard} (Decimal-only amount validators)")

    # 4. Stablecoin canonical-identity read seam is reused (never re-derived).
    ci = _require_file(STABLECOIN_IDENTITY_PY)
    if ci is not None:
        for sym in ("StablecoinCanonicalIdentityResolver", "surface_on_read_row", "StablecoinUniversalIdentityRead"):
            if sym not in ci:
                fail(f"services/stablecoin/canonical_identity.py missing {sym}")

    # 5. Money is Decimal / NUMERIC(38, 18), never binary float, in canonical tables.
    tr = _require_file(TYPED_REPO_PY)
    if tr is not None:
        if "def as_decimal(" not in tr or "Rejects float outright" not in tr:
            fail("repositories/typed_repo.py as_decimal must reject float transit for canonical money")
    for mig in FINANCIAL_MIGRATIONS:
        body = _require_file(mig)
        if body is None:
            continue
        # Migrations that persist a money column must declare NUMERIC(38, 18).
        # (The registry trunk carries reference data only — its own docstring
        # states no monetary column — so only money-bearing migrations are
        # required to spell NUMERIC(38, 18).)
        if any(col in body for col in ("price ", "native_amount ", "reporting_amount ")):
            if "NUMERIC(38, 18)" not in body:
                fail(f"{mig.name} must declare money as NUMERIC(38, 18)")
        for float_col in ("FLOAT", "REAL", "DOUBLE PRECISION", "sa.Float(", "sa.REAL"):
            if float_col in body:
                fail(f"{mig.name} introduces a binary-float money column ({float_col!r}); money is NUMERIC(38, 18)")

    # 6. Seeds: namespace-safe canonical ids + legacy alias preservation + x402
    #    stablecoin universe completeness (USDC/USDT, Base/Solana, crypto:ETH).
    seeds = _require_file(ASSETS_SEEDS_PY)
    if seeds is not None:
        if "_NAMESPACED_PREFIXES" not in seeds:
            fail("services/assets/seeds.py missing the namespaced-prefix guard")
        for lit in ("fiat:{iso_code}", "stablecoin:{symbol}"):
            if f'f"{lit}"' not in seeds and f"f'{lit}'" not in seeds:
                fail(f"services/assets/seeds.py must build canonical ids namespaced (missing {lit})")
        # Legacy stablecoin ids are bridged as aliases, never rewritten.
        if "usdc" not in seeds.lower():
            fail("services/assets/seeds.py must preserve legacy stablecoin ids via aliases (usdc)")
        # The x402 stablecoin universe is seeded namespaced: USDC/USDT symbols
        # drive `stablecoin:<symbol>` asset rows (never hardcoded id literals).
        if "_STABLECOIN_NAMES" not in seeds or ("USDC" not in seeds or "USDT" not in seeds):
            fail("services/assets/seeds.py seed completeness vs x402: USDC/USDT stablecoin symbols missing")
        for seed_ref in ("crypto:ETH", "eip155:8453", "solana:mainnet"):
            if seed_ref not in seeds:
                fail(f"services/assets/seeds.py seed completeness vs x402: missing chain/native {seed_ref}")

    # 7. Valuation immutability + observe-only posture.
    repos = _require_file(VALUATION_REPOS_PY)
    if repos is not None:
        if "_IMMUTABILITY_CARVE_OUT" not in repos:
            fail("valuation repositories must restrict in-place snapshot updates to the carve-out columns")
        if "mark_superseded" not in repos:
            fail("valuation repositories missing mark_superseded (corrections APPEND, then flip status)")
    svc = _require_file(VALUATION_SERVICE_PY)
    if svc is not None:
        if "execution_by_aether" not in svc or '"execution_by_aether": False' not in svc:
            fail("valuation service must persist observation-only rows (execution_by_aether always False)")

    # 8. Registry version is a deterministic sha256, never a wall-clock timestamp.
    reg = _require_file(ASSETS_REGISTRY_PY)
    if reg is not None:
        if "sha256" not in reg or "wall-clock" not in reg.lower():
            fail(
                "registry_version must be a deterministic sha256 over canonical seed "
                "content, never a wall-clock timestamp"
            )

    return _report()


def _report() -> int:
    if ERRORS:
        print("universal financial-asset validation FAILED:")
        for e in ERRORS:
            print(f"  - {e}")
        print(
            "\nCanonical financial assets are namespaced, Decimal-only, immutable, "
            "and observation-only. See docs/source-of-truth/FINANCIAL_NORMALIZATION.md."
        )
        return 1
    print(
        "universal financial-asset validation OK "
        "(namespaced contract + Decimal money + immutable snapshots + observe-only)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
