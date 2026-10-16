import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BrandMark, resolveBrandMark } from '@aether-app/components/brand-mark';

describe('resolveBrandMark', () => {
  it('resolves connector families, display names and SDK platforms', () => {
    expect(resolveBrandMark('shopify')).toMatch(/shopify/);
    expect(resolveBrandMark('google_ads')).toMatch(/googleads/);
    expect(resolveBrandMark('Google Analytics')).toMatch(/googleanalytics/);
    expect(resolveBrandMark('facebook_ads')).toMatch(/meta/);
    expect(resolveBrandMark('react-native')).toMatch(/react/);
    expect(resolveBrandMark('ios')).toMatch(/apple/);
  });

  it('returns null for unknown families', () => {
    expect(resolveBrandMark('definitely-not-a-provider')).toBeNull();
    expect(resolveBrandMark('')).toBeNull();
  });
});

describe('BrandMark', () => {
  it('renders the mark image when known, and a lettermark otherwise', () => {
    const known = render(<BrandMark token="stripe" />);
    expect(known.container.querySelector('img')).not.toBeNull();
    const unknown = render(<BrandMark token="zz-unknown" label="Zeta" />);
    expect(unknown.container.querySelector('img')).toBeNull();
    expect(unknown.container.textContent).toBe('Z');
  });
});
