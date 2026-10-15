// Canonical acquisition attribution over the RN bridge:
// - Aether.attribution delegates to the exact cross-platform native method
//   names (getFirstTouchAttribution / getLatestTouchAttribution / handleURL /
//   resolveDeferredHandoff).
// - Native JSON strings parse into the shared AcquisitionEvidence shape.
// - Everything stays null-safe when the native module is absent or throws —
//   deferred attribution is deterministic-only, so "no match" is a null, not
//   an error, and the install stays Direct / Unknown server-side.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const { nativeMethods } = vi.hoisted(() => ({
  nativeMethods: {
    initialize: vi.fn(),
    track: vi.fn(),
    observe: vi.fn(),
    getFirstTouchAttribution: vi.fn(async (): Promise<unknown> => null),
    getLatestTouchAttribution: vi.fn(async (): Promise<unknown> => null),
    handleURL: vi.fn(),
    handleQrScanResult: vi.fn(),
    handleNfcUri: vi.fn(),
    resolveDeferredHandoff: vi.fn(async (): Promise<unknown> => null),
  },
}));

vi.mock('react-native', () => ({
  NativeModules: { AetherNative: nativeMethods },
  NativeEventEmitter: class {
    addListener = vi.fn(() => ({ remove: vi.fn() }));
  },
  Platform: { OS: 'ios', Version: '17.0' },
  Dimensions: { get: vi.fn(() => ({ width: 390, height: 844 })) },
}));

import Aether from '../bridge';
import { createTrackedPressHandler, emitTrackedPress } from '../components/tracked-press';

const firstTouchJSON = JSON.stringify({
  schemaVersion: 3,
  entryMethod: 'ios_universal_link',
  destinationDomain: 'app.example.com',
  utmSource: 'newsletter',
  firstTouch: true,
});

describe('Aether.attribution — native delegation', () => {
  beforeEach(() => vi.clearAllMocks());

  it('getFirstTouch parses the native JSON string into AcquisitionEvidence', async () => {
    nativeMethods.getFirstTouchAttribution.mockResolvedValueOnce(firstTouchJSON);
    const evidence = await Aether.attribution.getFirstTouch();
    expect(nativeMethods.getFirstTouchAttribution).toHaveBeenCalledTimes(1);
    expect(evidence).toEqual({
      schemaVersion: 3,
      entryMethod: 'ios_universal_link',
      destinationDomain: 'app.example.com',
      utmSource: 'newsletter',
      firstTouch: true,
    });
  });

  it('getLatestTouch passes through an already-decoded native object', async () => {
    nativeMethods.getLatestTouchAttribution.mockResolvedValueOnce({
      schemaVersion: 3,
      entryMethod: 'ios_custom_url',
      firstTouch: false,
    });
    const evidence = await Aether.attribution.getLatestTouch();
    expect(evidence?.entryMethod).toBe('ios_custom_url');
    expect(evidence?.firstTouch).toBe(false);
  });

  it('getFirstTouch returns null for native null and for malformed JSON', async () => {
    nativeMethods.getFirstTouchAttribution.mockResolvedValueOnce(null);
    await expect(Aether.attribution.getFirstTouch()).resolves.toBeNull();
    nativeMethods.getFirstTouchAttribution.mockResolvedValueOnce('{not json');
    await expect(Aether.attribution.getFirstTouch()).resolves.toBeNull();
  });

  it('handleURL delegates the raw URL to the native parser', () => {
    Aether.attribution.handleURL('https://app.example.com/promo?utm_source=x');
    expect(nativeMethods.handleURL).toHaveBeenCalledWith(
      'https://app.example.com/promo?utm_source=x',
    );
  });

  it('handleQrScanResult delegates the host-decoded QR URL to the native parser', () => {
    Aether.attribution.handleQrScanResult('https://app.example.com/qr?utm_source=poster');
    expect(nativeMethods.handleQrScanResult).toHaveBeenCalledWith(
      'https://app.example.com/qr?utm_source=poster',
    );
  });

  it('handleNfcUri delegates the host-decoded NFC URI to the native parser', () => {
    Aether.attribution.handleNfcUri('https://app.example.com/nfc?aether_ref=abc');
    expect(nativeMethods.handleNfcUri).toHaveBeenCalledWith(
      'https://app.example.com/nfc?aether_ref=abc',
    );
  });

  it('resolveDeferredHandoff resolves evidence on a server match', async () => {
    nativeMethods.resolveDeferredHandoff.mockResolvedValueOnce(firstTouchJSON);
    const evidence = await Aether.attribution.resolveDeferredHandoff('HANDOFF-123');
    expect(nativeMethods.resolveDeferredHandoff).toHaveBeenCalledWith('HANDOFF-123');
    expect(evidence?.destinationDomain).toBe('app.example.com');
  });

  it('resolveDeferredHandoff resolves null when the handoff is unmatched', async () => {
    nativeMethods.resolveDeferredHandoff.mockResolvedValueOnce(null);
    await expect(Aether.attribution.resolveDeferredHandoff('nope')).resolves.toBeNull();
  });

  it('resolveDeferredHandoff resolves null (never throws) on native rejection', async () => {
    nativeMethods.resolveDeferredHandoff.mockRejectedValueOnce(new Error('offline'));
    await expect(Aether.attribution.resolveDeferredHandoff('HANDOFF-123')).resolves.toBeNull();
  });
});

describe('Aether.attribution — null-safety without a linked native module', () => {
  it('all methods are safe when the native methods are absent', async () => {
    const savedFirst = nativeMethods.getFirstTouchAttribution;
    const savedLatest = nativeMethods.getLatestTouchAttribution;
    const savedHandle = nativeMethods.handleURL;
    const savedQr = nativeMethods.handleQrScanResult;
    const savedNfc = nativeMethods.handleNfcUri;
    const savedResolve = nativeMethods.resolveDeferredHandoff;
    // Simulate an app running with an older native SDK that predates the
    // attribution methods (optional-chained natively, so undefined, not throw).
    delete (nativeMethods as Record<string, unknown>).getFirstTouchAttribution;
    delete (nativeMethods as Record<string, unknown>).getLatestTouchAttribution;
    delete (nativeMethods as Record<string, unknown>).handleURL;
    delete (nativeMethods as Record<string, unknown>).handleQrScanResult;
    delete (nativeMethods as Record<string, unknown>).handleNfcUri;
    delete (nativeMethods as Record<string, unknown>).resolveDeferredHandoff;
    try {
      await expect(Aether.attribution.getFirstTouch()).resolves.toBeNull();
      await expect(Aether.attribution.getLatestTouch()).resolves.toBeNull();
      expect(() => Aether.attribution.handleURL('myapp://landing')).not.toThrow();
      expect(() => Aether.attribution.handleQrScanResult('myapp://qr')).not.toThrow();
      expect(() => Aether.attribution.handleNfcUri('myapp://nfc')).not.toThrow();
      await expect(Aether.attribution.resolveDeferredHandoff('id')).resolves.toBeNull();
    } finally {
      nativeMethods.getFirstTouchAttribution = savedFirst;
      nativeMethods.getLatestTouchAttribution = savedLatest;
      nativeMethods.handleURL = savedHandle;
      nativeMethods.handleQrScanResult = savedQr;
      nativeMethods.handleNfcUri = savedNfc;
      nativeMethods.resolveDeferredHandoff = savedResolve;
    }
  });
});

describe('Tracked press interaction (AetherPressable core)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('emits ui_interaction_observed with the stable controlId and no text capture', () => {
    emitTrackedPress('checkout.confirm');
    expect(nativeMethods.observe).toHaveBeenCalledWith('ui_interaction_observed', {
      controlId: 'checkout.confirm',
      controlType: 'pressable',
      action: 'press',
    });
    const props = nativeMethods.observe.mock.calls[0][1] as Record<string, unknown>;
    expect(Object.keys(props).sort()).toEqual(['action', 'controlId', 'controlType']);
  });

  it('handler emits first, then delegates the press event to onPress', () => {
    const order: string[] = [];
    nativeMethods.observe.mockImplementationOnce(() => order.push('emit'));
    const onPress = vi.fn(() => order.push('onPress'));
    const handler = createTrackedPressHandler<{ kind: string }>('cta.primary', onPress, {
      screen: 'Home',
    });

    handler({ kind: 'press-event' });

    expect(order).toEqual(['emit', 'onPress']);
    expect(onPress).toHaveBeenCalledWith({ kind: 'press-event' });
    expect(nativeMethods.observe).toHaveBeenCalledWith('ui_interaction_observed', {
      controlId: 'cta.primary',
      controlType: 'pressable',
      action: 'press',
      screen: 'Home',
    });
  });

  it('handler keeps the controlId stable across repeated presses', () => {
    const handler = createTrackedPressHandler('cta.primary');
    handler(undefined);
    handler(undefined);
    const ids = nativeMethods.observe.mock.calls.map(
      call => (call[1] as Record<string, unknown>).controlId,
    );
    expect(ids).toEqual(['cta.primary', 'cta.primary']);
  });

  it('handler is null-safe without an onPress and without a native module', () => {
    const handler = createTrackedPressHandler('cta.secondary', null);
    expect(() => handler(undefined)).not.toThrow();
  });
});
