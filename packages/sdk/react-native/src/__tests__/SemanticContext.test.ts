// RN JS-side semantic envelope — two contracts pinned here:
//
// 1. Canonical id reconciliation: the sessionId/eventId in the envelope are
//    NATIVE-OWNED and passed into collect() by the caller. The collector never
//    mints its own ids (same contract as the web SemanticContextCollector
//    after PR #475), so the JS envelope can never diverge from the session id
//    the native pipeline stamps on events.
// 2. Temporal provenance emission: the envelope carries the device timezone,
//    the UTC offset captured at collect (= event occurrence) time, and
//    explicit timeZoneSource/clockSource claims. Timestamps and lifecycle
//    events remain native-owned; this envelope is evidence only.
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('react-native', () => ({
  Platform: { OS: 'ios', Version: '17.0' },
  Dimensions: { get: vi.fn(() => ({ width: 390, height: 844 })) },
}));

import { RNSemanticContextCollector } from '../context/SemanticContext';

describe('RN semantic context — canonical id reconciliation', () => {
  afterEach(() => vi.restoreAllMocks());

  it('echoes the caller-provided canonical sessionId and eventId verbatim', () => {
    const envelope = new RNSemanticContextCollector().collect('sess-native-1', 'evt-42');
    expect(envelope.sessionId).toBe('sess-native-1');
    expect(envelope.eventId).toBe('evt-42');
  });

  it('never self-mints a session id — repeated collects agree with the passed id', () => {
    const collector = new RNSemanticContextCollector();
    const first = collector.collect('sess-native-1', 'evt-1');
    const second = collector.collect('sess-native-1', 'evt-2');
    expect(first.sessionId).toBe('sess-native-1');
    expect(second.sessionId).toBe('sess-native-1');
    expect(second.eventId).toBe('evt-2');
  });

  it('does not consult any RNG to produce ids', () => {
    const randomSpy = vi.spyOn(Math, 'random');
    new RNSemanticContextCollector().collect('sess-native-1', 'evt-1');
    expect(randomSpy).not.toHaveBeenCalled();
  });

  it('resetSession clears the screen trail without inventing a session id', () => {
    const collector = new RNSemanticContextCollector();
    collector.recordScreen('Home');
    collector.resetSession();
    const envelope = collector.collect('sess-native-2', 'evt-1');
    expect(envelope.sessionId).toBe('sess-native-2');
    expect(envelope.screenPath).toEqual([]);
  });
});

describe('RN semantic context — screen trail', () => {
  it('records screens in order and copies the trail into the envelope', () => {
    const collector = new RNSemanticContextCollector();
    collector.recordScreen('Home');
    collector.recordScreen('Cart');
    const envelope = collector.collect('sess-native-1', 'evt-1');
    expect(envelope.screenPath).toEqual(['Home', 'Cart']);
    // The envelope holds a copy — later recordings must not mutate it.
    collector.recordScreen('Checkout');
    expect(envelope.screenPath).toEqual(['Home', 'Cart']);
  });

  it('caps the trail at the 50 most recent screens', () => {
    const collector = new RNSemanticContextCollector();
    for (let i = 1; i <= 55; i++) collector.recordScreen(`Screen${i}`);
    const envelope = collector.collect('sess-native-1', 'evt-1');
    expect(envelope.screenPath).toHaveLength(50);
    expect(envelope.screenPath[0]).toBe('Screen6');
    expect(envelope.screenPath[49]).toBe('Screen55');
  });

  it('keeps the trail per collector instance — no shared module-level state', () => {
    const a = new RNSemanticContextCollector();
    const b = new RNSemanticContextCollector();
    a.recordScreen('OnlyInA');
    expect(a.collect('s', 'e').screenPath).toEqual(['OnlyInA']);
    expect(b.collect('s', 'e').screenPath).toEqual([]);
  });

  it('destroy clears the trail', () => {
    const collector = new RNSemanticContextCollector();
    collector.recordScreen('Home');
    collector.destroy();
    expect(collector.collect('s', 'e').screenPath).toEqual([]);
  });
});

describe('RN semantic context — temporal provenance', () => {
  afterEach(() => vi.restoreAllMocks());

  it('stamps timezone, utcOffsetMinutes, timeZoneSource and clockSource', () => {
    const envelope = new RNSemanticContextCollector().collect('sess-native-1', 'evt-1');
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
    const envelope = collector.collect('sess-native-1', 'evt-1');
    offsetSpy.mockRestore();
    expect(envelope.utcOffsetMinutes).toBe(330);
  });
});
