// Temporal provenance emission — the RN JS-side semantic envelope carries the
// device timezone, the UTC offset captured at collect (= event occurrence)
// time, and explicit timeZoneSource/clockSource claims. Timestamps and
// lifecycle events remain native-owned; this envelope is evidence only.
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('react-native', () => ({
  Platform: { OS: 'ios', Version: '17.0' },
  Dimensions: { get: vi.fn(() => ({ width: 390, height: 844 })) },
}));

import { RNSemanticContextCollector } from '../context/SemanticContext';

describe('RN semantic context — temporal provenance', () => {
  afterEach(() => vi.restoreAllMocks());

  it('stamps timezone, utcOffsetMinutes, timeZoneSource and clockSource', () => {
    const envelope = new RNSemanticContextCollector().collect();
    expect(envelope.timezone).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
    // `+ 0` normalizes -0 → 0 (a UTC test env yields -0; JSON serializes it as 0).
    expect(envelope.utcOffsetMinutes + 0).toBe(-new Date().getTimezoneOffset() + 0);
    expect(typeof envelope.utcOffsetMinutes).toBe('number');
    expect(envelope.timeZoneSource).toBe('device');
    expect(envelope.clockSource).toBe('device');
  });

  it('captures the offset at collect time, not module load', () => {
    const collector = new RNSemanticContextCollector();
    const offsetSpy = vi.spyOn(Date.prototype, 'getTimezoneOffset').mockReturnValue(-330);
    const envelope = collector.collect();
    offsetSpy.mockRestore();
    expect(envelope.utcOffsetMinutes).toBe(330);
  });
});
