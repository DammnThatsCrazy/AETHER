import { describe, expect, it } from 'vitest';
import { resolveCanonicalAssetDisplayMeta } from './reporting-asset-meta';

// Resolver tests run against the CANONICAL `@aether/shared/financial-assets`
// registry data (FIAT_REFERENCE_SEED + isNamespacedAssetId). They require the
// @aether/shared built module, which the local partial install does not provide;
// they run in the full CI install.

describe('resolveCanonicalAssetDisplayMeta', () => {
  it('resolves seeded fiat metadata (symbol + minor_units)', () => {
    expect(resolveCanonicalAssetDisplayMeta('fiat:USD')).toEqual({
      assetId: 'fiat:USD',
      code: 'USD',
      symbol: '$',
      minorUnits: 2,
    });
    expect(resolveCanonicalAssetDisplayMeta('fiat:EUR')).toMatchObject({ code: 'EUR', minorUnits: 2 });
    expect(resolveCanonicalAssetDisplayMeta('fiat:JPY')).toMatchObject({ code: 'JPY', minorUnits: 0 });
  });

  it('renders an unseeded fiat code verbatim (no invented glyph/decimals)', () => {
    expect(resolveCanonicalAssetDisplayMeta('fiat:THB')).toEqual({
      assetId: 'fiat:THB',
      code: 'THB',
      symbol: null,
      minorUnits: null,
    });
  });

  it('uses the id symbol segment as the code for crypto/stablecoin (decimals unknown)', () => {
    expect(resolveCanonicalAssetDisplayMeta('crypto:ETH')).toMatchObject({
      assetId: 'crypto:ETH',
      code: 'ETH',
      symbol: null,
      minorUnits: null,
    });
    expect(resolveCanonicalAssetDisplayMeta('stablecoin:USDC')).toMatchObject({
      code: 'USDC',
      symbol: null,
    });
  });

  it('falls back to the full canonical id for token assets (no symbol to guess)', () => {
    const token = 'token:eip155:8453:0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913';
    expect(resolveCanonicalAssetDisplayMeta(token)).toEqual({
      assetId: token,
      code: token,
      symbol: null,
      minorUnits: null,
    });
  });

  it('rejects bare / non-namespaced / malformed ids', () => {
    expect(resolveCanonicalAssetDisplayMeta('USD')).toBeNull(); // bare symbol
    expect(resolveCanonicalAssetDisplayMeta('token:0xabc')).toBeNull(); // no chain
    expect(resolveCanonicalAssetDisplayMeta('usd')).toBeNull();
    expect(resolveCanonicalAssetDisplayMeta('')).toBeNull();
    expect(resolveCanonicalAssetDisplayMeta(null)).toBeNull();
    expect(resolveCanonicalAssetDisplayMeta(undefined)).toBeNull();
  });
});
