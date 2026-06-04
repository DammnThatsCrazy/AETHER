import { describe, expect, it } from 'vitest';
import { EVENT_CONSENT_PURPOSE, EVENT_FAMILY, type JourneyPayload } from './events';

const journeyTypes = [
  'journey_started',
  'journey_paused',
  'journey_resumed',
  'journey_continued',
  'journey_completed',
  'journey_abandoned',
  'journey_checkpoint',
] as const;

describe('journey lifecycle event contracts', () => {
  it('registers every journey lifecycle event as analytics-gated journey family', () => {
    for (const eventType of journeyTypes) {
      expect(EVENT_FAMILY[eventType]).toBe('journey');
      expect(EVENT_CONSENT_PURPOSE[eventType]).toBe('analytics');
    }
  });

  it('supports handoff confidence payload fields', () => {
    const payload: JourneyPayload = {
      journeyId: 'jrn_1',
      journeyType: 'checkout',
      handoffFromSessionId: 'desktop-session',
      handoffToDeviceId: 'iphone-device',
      confidence: 0.97,
      confidenceSignals: ['user_id_match', 'email_hash_match'],
    };
    expect(payload.confidenceSignals).toContain('email_hash_match');
  });
});
