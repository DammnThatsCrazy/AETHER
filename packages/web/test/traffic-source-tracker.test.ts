// @vitest-environment jsdom

import { beforeEach, describe, expect, it } from 'vitest';

import { TrafficSourceTracker } from '../src/tracking/traffic-source-tracker';

describe('TrafficSourceTracker referral evidence', () => {
  beforeEach(() => {
    sessionStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  it('captures aether_ref as an opaque referralToken in the event payload', () => {
    window.history.replaceState(
      {},
      '',
      '/landing?utm_source=partner&aether_ref=opaque.v1-token_123',
    );

    const tracker = new TrafficSourceTracker();
    const detected = tracker.detect();

    expect(detected.utmSource).toBe('partner');
    expect(detected.referralToken).toBe('opaque.v1-token_123');
    expect(tracker.toEventPayload()).toMatchObject({
      referralToken: 'opaque.v1-token_123',
    });
  });

  it('retains the first referral token and landing page across SPA navigation', () => {
    window.history.replaceState({}, '', '/first?aether_ref=first-token');

    const first = new TrafficSourceTracker().detect();

    window.history.pushState({}, '', '/next?aether_ref=replacement-token');
    const afterNavigation = new TrafficSourceTracker().detect();

    expect(afterNavigation.referralToken).toBe('first-token');
    expect(afterNavigation.landingPage).toBe(first.landingPage);
    expect(afterNavigation.landingPage).toContain('/first?aether_ref=first-token');
  });
});
