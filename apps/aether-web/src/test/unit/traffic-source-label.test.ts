// Canonical traffic-source presentation: labels come from the generated
// registry (@aether/shared/traffic-source), the honest fallback is
// "Direct / Unknown", and evidence tooltips only surface fields that exist.
import { describe, it, expect } from 'vitest';
import {
  sourceClassLabel,
  humanizeRegistryValue,
  touchpointEvidenceSummary,
} from '@aether-app/lib/traffic-source';

describe('sourceClassLabel', () => {
  it('renders canonical registry labels', () => {
    expect(sourceClassLabel('organic_search')).toBe('Organic Search');
    expect(sourceClassLabel('ai_referral')).toBe('AI Referral');
    expect(sourceClassLabel('owned_referral')).toBe('Verified Source');
  });

  it('renders direct_unknown as "Direct / Unknown", never a typed-URL claim', () => {
    expect(sourceClassLabel('direct_unknown')).toBe('Direct / Unknown');
    expect(sourceClassLabel('direct_unknown')).not.toMatch(/typed/i);
  });

  it('normalizes the legacy "direct" alias to the honest label', () => {
    expect(sourceClassLabel('direct')).toBe('Direct / Unknown');
  });

  it('falls back to the raw value for unknown future classes and dash for empty', () => {
    expect(sourceClassLabel('some_future_class')).toBe('some_future_class');
    expect(sourceClassLabel(null)).toBe('—');
    expect(sourceClassLabel(undefined)).toBe('—');
    expect(sourceClassLabel('')).toBe('—');
  });
});

describe('humanizeRegistryValue', () => {
  it('humanizes snake_case registry values and dashes empties', () => {
    expect(humanizeRegistryValue('ios_universal_link')).toBe('ios universal link');
    expect(humanizeRegistryValue('server_observed')).toBe('server observed');
    expect(humanizeRegistryValue(undefined)).toBe('—');
  });
});

describe('touchpointEvidenceSummary', () => {
  it('includes only present optional evidence fields', () => {
    expect(
      touchpointEvidenceSummary({
        entry_method: 'ios_universal_link',
        proof_level: 'server_observed',
        verification_level: 'verified',
      }),
    ).toBe('Entry: ios universal link · Proof: server observed · Verification: verified');
  });

  it('surfaces conflicts when present and stays empty for bare rows', () => {
    expect(
      touchpointEvidenceSummary({
        proof_level: 'declared',
        classification_conflicts: ['utm_source disagrees with referrer'],
      }),
    ).toBe('Proof: declared · Conflicts: utm_source disagrees with referrer');
    expect(touchpointEvidenceSummary({})).toBe('');
  });
});
