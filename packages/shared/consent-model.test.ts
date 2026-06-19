import { describe, expect, it } from 'vitest';
import { CONSENT_PURPOSES, type ConsentPurpose } from './consent';
import { EVENT_CONSENT_PURPOSE } from './events';

// ---------------------------------------------------------------------------
// Canonical consent purpose list
// ---------------------------------------------------------------------------

const EXPECTED_PURPOSES: ConsentPurpose[] = [
  'analytics',
  'marketing',
  'web3',
  'agent',
  'commerce',
];

describe('consent-model', () => {
  it('exactly 5 canonical consent purposes exist', () => {
    expect(CONSENT_PURPOSES).toHaveLength(5);
  });

  it('CANONICAL_PURPOSES includes all 5 expected purposes', () => {
    for (const purpose of EXPECTED_PURPOSES) {
      expect(CONSENT_PURPOSES).toContain(purpose);
    }
  });

  it('no sixth purpose exists', () => {
    // Any purpose beyond the canonical five is a contract violation
    const purposeSet = new Set(CONSENT_PURPOSES);
    expect(purposeSet.size).toBe(5);
    const unexpected = [...purposeSet].filter((p) => !EXPECTED_PURPOSES.includes(p));
    expect(unexpected).toHaveLength(0);
  });

  it('each canonical purpose appears at least once in the event consent map', () => {
    const mappedPurposes = new Set(Object.values(EVENT_CONSENT_PURPOSE));
    for (const purpose of EXPECTED_PURPOSES) {
      expect(mappedPurposes).toContain(purpose);
    }
  });

  it('consent events are either mapped to analytics or excluded from gating', () => {
    // The consent event must never be silently dropped by the gating check.
    // It is either mapped to the always-allowed analytics purpose, or omitted
    // from the map (treated as unconditional pass-through).
    const consentPurpose = EVENT_CONSENT_PURPOSE['consent'];
    const isAllowed =
      consentPurpose === 'analytics' ||
      consentPurpose === null ||
      consentPurpose === undefined;
    expect(isAllowed).toBe(true);
  });

  it('analytics purpose gates core tracking events', () => {
    const analyticsGated: string[] = ['track', 'page', 'screen', 'heartbeat', 'error'];
    for (const eventType of analyticsGated) {
      expect(EVENT_CONSENT_PURPOSE[eventType as keyof typeof EVENT_CONSENT_PURPOSE]).toBe('analytics');
    }
  });

  it('commerce purpose gates payment and x402 events', () => {
    const commerceGated: string[] = [
      'payment_initiated', 'payment_completed', 'payment_failed',
      'x402_payment_submitted', 'x402_payment_settled',
    ];
    for (const eventType of commerceGated) {
      expect(EVENT_CONSENT_PURPOSE[eventType as keyof typeof EVENT_CONSENT_PURPOSE]).toBe('commerce');
    }
  });

  it('agent purpose gates agent lifecycle events', () => {
    const agentGated: string[] = ['agent_task', 'agent_decision', 'agent_registered'];
    for (const eventType of agentGated) {
      expect(EVENT_CONSENT_PURPOSE[eventType as keyof typeof EVENT_CONSENT_PURPOSE]).toBe('agent');
    }
  });

  it('web3 purpose gates wallet and transaction events', () => {
    const web3Gated: string[] = ['wallet', 'transaction', 'contract_action'];
    for (const eventType of web3Gated) {
      expect(EVENT_CONSENT_PURPOSE[eventType as keyof typeof EVENT_CONSENT_PURPOSE]).toBe('web3');
    }
  });
});
