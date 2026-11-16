// @vitest-environment jsdom
/**
 * Automation evidence: presence-only signals for actor classification.
 * See docs/architecture/AGENT-DETECTION-RELIABILITY.md.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  __resetAutomationProbeForTests,
  getAutomationSignals,
  getDeviceContext,
} from '../src/utils/index';

function setWebdriver(value: boolean | undefined): void {
  Object.defineProperty(window.navigator, 'webdriver', { value, configurable: true });
}

describe('automation signals', () => {
  beforeEach(() => __resetAutomationProbeForTests());
  afterEach(() => setWebdriver(undefined));

  it('reports the W3C webdriver flag', () => {
    setWebdriver(true);
    expect(getAutomationSignals().webdriver).toBe(true);
    setWebdriver(false);
    expect(getAutomationSignals().webdriver).toBe(false);
  });

  it('treats a missing webdriver property as false', () => {
    setWebdriver(undefined);
    expect(getAutomationSignals().webdriver).toBe(false);
  });

  it('ignores synthetic (untrusted) input events', () => {
    getAutomationSignals();
    window.dispatchEvent(new Event('pointerdown'));
    window.dispatchEvent(new Event('keydown'));
    expect(getAutomationSignals().trustedInputSeen).toBe(false);
  });

  it('is part of the device context and carries only booleans', () => {
    const device = getDeviceContext();
    expect(device.automation).toEqual({
      webdriver: expect.any(Boolean),
      trustedInputSeen: expect.any(Boolean),
    });
    expect(Object.keys(device.automation ?? {}).sort()).toEqual(['trustedInputSeen', 'webdriver']);
  });
});
