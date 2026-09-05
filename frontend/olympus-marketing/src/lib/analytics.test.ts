import { describe, expect, it } from 'vitest';
import { resolveAnalytics } from '@olympus-marketing/lib/analytics';

describe('resolveAnalytics', () => {
  it('keeps the explicit off provider inert even when a property id is present', () => {
    expect(resolveAnalytics({ provider: 'off', propertyId: 'G-1234567890' })).toEqual({
      enabled: false,
      provider: 'off',
      propertyId: 'G-1234567890',
    });
  });

  it('normalizes an empty property id against a valid provider to disabled', () => {
    expect(resolveAnalytics({ provider: 'ga4', propertyId: '' })).toEqual({
      enabled: false,
      provider: 'ga4',
      propertyId: '',
    });
    expect(resolveAnalytics({ provider: 'plausible', propertyId: '' })).toEqual({
      enabled: false,
      provider: 'plausible',
      propertyId: '',
    });
  });

  it('treats a missing property id exactly like an empty one', () => {
    expect(resolveAnalytics({ provider: 'ga4', propertyId: undefined })).toEqual({
      enabled: false,
      provider: 'ga4',
      propertyId: '',
    });
  });

  it('treats whitespace-only property ids as empty', () => {
    expect(resolveAnalytics({ provider: 'ga4', propertyId: '   ' })).toEqual({
      enabled: false,
      provider: 'ga4',
      propertyId: '',
    });
  });

  it('enables ga4 only when the property id is non-empty', () => {
    expect(resolveAnalytics({ provider: 'ga4', propertyId: 'G-1234567890' })).toEqual({
      enabled: true,
      provider: 'ga4',
      propertyId: 'G-1234567890',
    });
  });

  it('enables plausible only when the property id is non-empty', () => {
    expect(resolveAnalytics({ provider: 'plausible', propertyId: 'olympuslabs.com' })).toEqual({
      enabled: true,
      provider: 'plausible',
      propertyId: 'olympuslabs.com',
    });
  });

  it('trims surrounding whitespace from a property id before enabling', () => {
    expect(resolveAnalytics({ provider: 'plausible', propertyId: '  olympuslabs.com  ' })).toEqual({
      enabled: true,
      provider: 'plausible',
      propertyId: 'olympuslabs.com',
    });
  });

  it('normalizes any unknown provider string to off and disabled', () => {
    expect(resolveAnalytics({ provider: 'segment', propertyId: 'anything' })).toEqual({
      enabled: false,
      provider: 'off',
      propertyId: 'anything',
    });
  });

  it('never throws and stays disabled when raw config is missing entirely', () => {
    expect(resolveAnalytics({})).toEqual({ enabled: false, provider: 'off', propertyId: '' });
  });
});
