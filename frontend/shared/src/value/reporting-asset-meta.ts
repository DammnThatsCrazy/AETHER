// =============================================================================
// Canonical reporting-asset metadata resolver (additive Wave-3 display layer).
//
// Maps a canonical, NAMESPACED asset id to the display metadata
// (`symbol` / `minor_units` / `code`) a value render needs, using the canonical
// registry data in `packages/shared/financial-assets.ts` — never a hardcoded
// frontend copy. Because the id is namespaced, the suffix is an ALIAS (symbol),
// never canonical identity; a bare / non-namespaced id is rejected (returns
// null) so the display layer never guesses a symbol or decimals from an
// uncanonicalized string.
//
//   - `fiat:<ISO>`           -> FiatCurrencyMetadata row from FIAT_REFERENCE_SEED
//                               (symbol + minor_units) when the ISO is seeded;
//                               otherwise symbol/minor_units are null and the ISO
//                               code itself is the label (never a guessed glyph).
//   - `crypto:<SYMBOL>`      -> the symbol segment is the display code (e.g. ETH);
//                               decimals are not seeded for non-fiat, so
//                               minor_units is null (stored precision preserved).
//   - `stablecoin:<SYMBOL>`  -> as crypto.
//   - `token:<chain>:<addr>` -> no human symbol in the id; code is the full
//                               canonical id and decimals are null.
//
// Runtime registry VALUES are imported from the `@aether/shared` leaf module
// (not the barrel) following the repo convention for CJS value imports (see
// frontend/shared/src/exploration/registry.ts).
// =============================================================================

import {
  FIAT_REFERENCE_SEED,
  isNamespacedAssetId,
  type FiatCurrencyMetadata,
} from '@aether/shared/financial-assets';
import type { AssetDisplayMeta } from './reporting-value';

const FIAT_BY_ISO = new Map<string, FiatCurrencyMetadata>(
  FIAT_REFERENCE_SEED.map((row) => [row.iso_code, row]),
);

function fiatMeta(iso: string, assetId: string): AssetDisplayMeta {
  const row = FIAT_BY_ISO.get(iso);
  if (row) {
    return {
      assetId,
      code: row.iso_code,
      symbol: row.symbol,
      minorUnits: row.minor_units,
    };
  }
  // Seeded symbols are display hints, not identity. An unseeded ISO code is
  // rendered verbatim (no invented glyph, no invented decimal convention).
  return { assetId, code: iso, symbol: null, minorUnits: null };
}

function symbolSuffixMeta(assetId: string, ns: string, body: string): AssetDisplayMeta {
  const suffix = body.split(':')[0] ?? body;
  return {
    assetId,
    // `crypto:ETH` / `stablecoin:USDC`: the id's symbol segment is the display
    // code. This is the id's own alias, not a guess.
    code: ns === 'token' ? assetId : suffix,
    symbol: null,
    // Non-fiat display decimals are registry/deployment data (not seeded in
    // financial-assets.ts); unknown => preserve the stored amount precision.
    minorUnits: null,
  };
}

/**
 * Resolve display metadata (symbol + display decimals + code) for a canonical
 * namespaced asset id. Returns null for null/empty or NON-namespaced (bare
 * symbol / malformed) ids — the display layer must reject those rather than
 * guess.
 */
export function resolveCanonicalAssetDisplayMeta(
  assetId: string | null | undefined,
): AssetDisplayMeta | null {
  if (assetId === null || assetId === undefined || assetId.trim() === '') {
    return null;
  }
  const id = assetId.trim();
  if (!isNamespacedAssetId(id)) {
    return null;
  }
  const colon = id.indexOf(':');
  const ns = id.slice(0, colon);
  const body = id.slice(colon + 1);

  if (ns === 'fiat') {
    return fiatMeta(body, id);
  }
  return symbolSuffixMeta(id, ns, body);
}

/** Alias matching the reporting display vocabulary. */
export function resolveReportingAssetMeta(
  assetId: string | null | undefined,
): AssetDisplayMeta | null {
  return resolveCanonicalAssetDisplayMeta(assetId);
}
