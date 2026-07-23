import { describe, expect, it } from 'vitest';

import {
  ACQUISITION_EVIDENCE_SCHEMA_VERSION,
  evidenceFromSearchParams,
} from './acquisition-evidence';

describe('acquisition evidence', () => {
  it('captures an opaque aether_ref token in schema version 3', () => {
    const evidence = evidenceFromSearchParams(new URLSearchParams(
      'utm_source=partner&aether_ref=opaque.v1-token_123',
    ));

    expect(ACQUISITION_EVIDENCE_SCHEMA_VERSION).toBe(3);
    expect(evidence.schemaVersion).toBe(3);
    expect(evidence.utmSource).toBe('partner');
    expect(evidence.referralToken).toBe('opaque.v1-token_123');
  });

  it('remains backward-compatible when aether_ref is absent', () => {
    const evidence = evidenceFromSearchParams(new URLSearchParams('utm_campaign=summer'));

    expect(evidence.utmCampaign).toBe('summer');
    expect(evidence.referralToken).toBeUndefined();
  });
});
