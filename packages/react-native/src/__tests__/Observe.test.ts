// Truth Kernel §2.6 / §2.8 — the RN bridge must expose a canonical observe()
// entry point, native queue-depth awareness, and per-batch health delivered via
// the AetherBatchResult native event. Also pins the semantic-envelope wiring:
// events are natively emitted and natively session-stamped, so the JS Tier 1
// envelope is exposed via collectSemanticContext(sessionId, eventId) around
// caller-held canonical ids — never around a JS-minted session id.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const { nativeMethods, listeners } = vi.hoisted(() => ({
  nativeMethods: {
    initialize: vi.fn(),
    track: vi.fn(),
    observe: vi.fn(),
    screenView: vi.fn(),
    reset: vi.fn(),
    getQueueDepth: vi.fn(async () => 7),
  },
  listeners: {} as Record<string, (payload: unknown) => void>,
}));

vi.mock('react-native', () => ({
  NativeModules: { AetherNative: nativeMethods },
  NativeEventEmitter: class {
    addListener = vi.fn((event: string, cb: (payload: unknown) => void) => {
      listeners[event] = cb;
      return { remove: vi.fn(() => { delete listeners[event]; }) };
    });
  },
  Platform: { OS: 'ios', Version: '17.0' },
  Dimensions: { get: vi.fn(() => ({ width: 390, height: 844 })) },
}));

import Aether from '../bridge';

describe('Aether RN bridge — observe() parity (§2.6)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('observe delegates the canonical type and properties to native', () => {
    Aether.observe('order_completed', { orderId: 'O-1' });
    expect(nativeMethods.observe).toHaveBeenCalledWith('order_completed', { orderId: 'O-1' });
  });

  it('observe passes empty properties when none provided', () => {
    Aether.observe('page_viewed');
    expect(nativeMethods.observe).toHaveBeenCalledWith('page_viewed', {});
  });

  it('queueDepth resolves the native queue depth', async () => {
    await expect(Aether.queueDepth()).resolves.toBe(7);
    expect(nativeMethods.getQueueDepth).toHaveBeenCalled();
  });

  it('queueDepth returns 0 when native throws', async () => {
    nativeMethods.getQueueDepth.mockRejectedValueOnce(new Error('unavailable'));
    await expect(Aether.queueDepth()).resolves.toBe(0);
  });
});

describe('Aether RN bridge — batch health (§2.8)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    for (const k of Object.keys(listeners)) delete listeners[k];
  });

  it('onBatchResult subscribes to AetherBatchResult and forwards health', () => {
    const cb = vi.fn();
    const unsub = Aether.onBatchResult(cb);
    expect(typeof unsub).toBe('function');
    expect(listeners['AetherBatchResult']).toBeTypeOf('function');

    const health = { accepted: 3, duplicate: 1, rejected: 0, dropped_by_consent: 2, queue_depth: 4 };
    listeners['AetherBatchResult'](health);
    expect(cb).toHaveBeenCalledWith(health);

    unsub();
    expect(listeners['AetherBatchResult']).toBeUndefined();
  });
});

describe('Aether RN bridge — semantic envelope wiring', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Clears the module-singleton JS screen trail between tests (and exercises
    // the reset() → resetSession() reconciliation below).
    Aether.reset();
  });

  it('collectSemanticContext builds the envelope around caller-held canonical ids', () => {
    const envelope = Aether.collectSemanticContext('sess-native-1', 'evt-9');
    expect(envelope.sessionId).toBe('sess-native-1');
    expect(envelope.eventId).toBe('evt-9');
    expect(envelope.sdk).toEqual({ name: 'aether-react-native', version: '8.12.0' });
    expect(envelope.platform).toBe('ios');
  });

  it('never stamps a JS-minted session id — the envelope always echoes the passed id', () => {
    const first = Aether.collectSemanticContext('sess-native-1', 'evt-1');
    const second = Aether.collectSemanticContext('sess-native-1', 'evt-2');
    expect(first.sessionId).toBe('sess-native-1');
    expect(second.sessionId).toBe('sess-native-1');
  });

  it('screenView records the JS screen trail shipped in the envelope', () => {
    Aether.screenView('Home');
    Aether.screenView('Cart', { source: 'push' });
    expect(nativeMethods.screenView).toHaveBeenCalledWith('Home', {});
    expect(nativeMethods.screenView).toHaveBeenCalledWith('Cart', { source: 'push' });
    const envelope = Aether.collectSemanticContext('sess-native-1', 'evt-1');
    expect(envelope.screenPath).toEqual(['Home', 'Cart']);
  });

  it('reset() clears the JS screen trail at the native session boundary', () => {
    Aether.screenView('Home');
    Aether.reset();
    expect(nativeMethods.reset).toHaveBeenCalled();
    // Native reset() re-minted the native session; the next envelope must not
    // carry the previous session's trail.
    const envelope = Aether.collectSemanticContext('sess-native-2', 'evt-1');
    expect(envelope.screenPath).toEqual([]);
  });
});

describe('Aether RN bridge — capability matrix', () => {
  it('advertises observe / batchHealth / manifestSignatureVerification', () => {
    expect(Aether.capabilities.observe).toBe(true);
    expect(Aether.capabilities.batchHealth).toBe(true);
    expect(Aether.capabilities.manifestSignatureVerification).toBe(true);
  });
});
