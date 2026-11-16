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
    // First-touch landing page is retained, but the sanitized URL never
    // carries aether_ref — the typed referralToken field is the only carrier.
    expect(afterNavigation.landingPage).toContain('/first');
    expect(afterNavigation.landingPage).not.toContain('aether_ref');
  });

  it('strips aether_ref and other sensitive params from the transmitted landing page', () => {
    window.history.replaceState(
      {},
      '',
      '/landing?utm_source=partner&aether_ref=secret-token&gclid=click-1#access_token=abc',
    );

    const detected = new TrafficSourceTracker().detect();

    expect(detected.referralToken).toBe('secret-token');
    expect(detected.clickIds).toMatchObject({ gclid: 'click-1' });
    expect(detected.landingPage).toContain('utm_source=partner');
    expect(detected.landingPage).not.toContain('aether_ref');
    expect(detected.landingPage).not.toContain('secret-token');
    expect(detected.landingPage).not.toContain('gclid');
    expect(detected.landingPage).not.toContain('access_token');
  });

  it('captures a signed ae click token as clickToken and strips it from the landing page', () => {
    const token = 'v1.eyJ0IjoidGVuYW50LWEifQ.abcdefghijklmnopqrstuvwxyz012345';
    window.history.replaceState({}, '', `/sale?utm_source=email&ae=${token}`);

    const tracker = new TrafficSourceTracker();
    const detected = tracker.detect();

    expect(detected.clickToken).toBe(token);
    expect(tracker.toEventPayload()).toMatchObject({ clickToken: token });
    expect(detected.landingPage).toContain('utm_source=email');
    expect(detected.landingPage).not.toContain(token);
    expect(detected.landingPage).not.toContain('ae=');
  });

  it('ignores a tenant-owned ae parameter that is not a signed token', () => {
    window.history.replaceState({}, '', '/checkout?ae=express');

    const detected = new TrafficSourceTracker().detect();

    expect(detected.clickToken).toBeNull();
    expect(detected.landingPage).toContain('ae=express');
  });
});
