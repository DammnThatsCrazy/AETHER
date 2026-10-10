import { describe, expect, it } from 'vitest';

import { KYBER_NAV_ITEMS } from './sidebar';

function item(path: string) {
  const result = KYBER_NAV_ITEMS.find(candidate => candidate.path === path);
  if (!result) throw new Error(`Expected navigation item for ${path}`);
  return result;
}

describe('Kyber sidebar semantic navigation', () => {
  it('maps every production destination to the central navigation taxonomy rather than a raw glyph', () => {
    expect(KYBER_NAV_ITEMS.length).toBeGreaterThanOrEqual(40);
    expect(KYBER_NAV_ITEMS.every(candidate => !('glyph' in candidate))).toBe(true);
    expect(KYBER_NAV_ITEMS.every(candidate => candidate.destination.startsWith('kyber-'))).toBe(true);

    expect(item('/mission').destination).toBe('kyber-mission');
    expect(item('/kyber-graph').destination).toBe('kyber-graph');
    expect(item('/connectors').destination).toBe('kyber-connectors');
    expect(item('/payment-rails').destination).toBe('kyber-payment-rails');
    expect(item('/lab').destination).toBe('kyber-lab');
  });

  it('preserves the existing backend capability requirements and frontend-only flags', () => {
    expect(item('/connectors').requirement).toEqual({ flag: 'connectors_enabled' });
    expect(item('/payment-rails').requirement).toEqual({ domain: 'payments' });
    expect(item('/payment-rails').envFlag).toBe('enablePaymentRails');
    expect(item('/ai-efficiency').requirement).toEqual({ domain: 'economic' });
    expect(item('/ai-efficiency').envFlag).toBe('enableAiEfficiency');
    expect(item('/agent-telemetry').envFlag).toBe('enableExternalAgentTelemetry');
    expect(KYBER_NAV_ITEMS.find(candidate => candidate.path === '/suggestions')).toBeUndefined();
    expect(item('/intelligence/suggestions').requirement).toEqual({ flag: 'suggestions_enabled' });
    expect(item('/kyber-graph').requirement).toBeUndefined();
    expect(item('/tenant-mirror').requirement).toBeUndefined();
  });
});
