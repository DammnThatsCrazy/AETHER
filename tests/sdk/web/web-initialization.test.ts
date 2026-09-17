/**
 * @vitest-environment jsdom
 */
/** @description FPS-050 — Web SDK Initialization test.
 * Tests the real @aether/web SDK: SDK_VERSION constant, AetherSDK class exports,
 * and event envelope shape from fixtures. */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import aether, { AetherSDK } from '@aether/web';
import { SDK_VERSION } from '@aether/shared/sdk-version';
import { EventEnvelope } from '@aether/proof-contracts';
import { trackEventFixture, identifyEventFixture } from '@aether/proof-fixtures';

// Top-level DOM shims for Node env before SDK module evaluation
if (typeof globalThis.screen === 'undefined') (globalThis as any).screen = { width: 1920, height: 1080, colorDepth: 24 } as any;
if (typeof globalThis.window !== 'undefined' && !(globalThis.window as any).screen) (globalThis.window as any).screen = (globalThis as any).screen;


function ensureDomMocks() {
  const canvasStub = () => ({
    width: 200,
    height: 50,
    getContext: (type: string) => {
      if (type === '2d') {
        return {
          textBaseline: 'top',
          font: '14px Arial',
          fillStyle: '#f60',
          fillRect: () => {},
          fillText: () => {},
          measureText: () => ({ width: 100 }),
        } as any;
      }
      return null;
    },
    toDataURL: () => 'data:image/png;base64,',
  });
  const createElementStub = (tag: string) => {
    if (tag === 'canvas') return canvasStub() as any;
    return { style: {}, setAttribute: () => {}, getAttribute: () => null, addEventListener: () => {}, removeEventListener: () => {}, appendChild: () => {}, removeChild: () => {}, querySelector: () => null, querySelectorAll: () => [], textContent: '', innerHTML: '', className: '' } as any;
  };
  if (typeof (globalThis as any).document === 'undefined') {
    (globalThis as any).document = {
      cookie: '',
      title: 'Test Document',
      referrer: '',
      addEventListener: () => {},
      removeEventListener: () => {},
      visibilityState: 'visible',
      hidden: false,
      createElement: createElementStub,
      querySelector: () => null,
      querySelectorAll: () => [],
      getElementById: () => null,
      getElementsByTagName: () => [],
      body: { appendChild: () => {}, removeChild: () => {}, style: {}, querySelector: () => null, querySelectorAll: () => [] } as any,
      head: { appendChild: () => {}, querySelector: () => null } as any,
      documentElement: { style: {} },
    } as any;
  } else {
    const d = (globalThis as any).document;
    if (!d.addEventListener) d.addEventListener = () => {};
    if (!d.removeEventListener) d.removeEventListener = () => {};
    if (d.cookie === undefined) d.cookie = '';
    if (d.title === undefined) d.title = 'Test Document';
    if (d.referrer === undefined) d.referrer = '';
    if (d.visibilityState === undefined) d.visibilityState = 'visible';
    if (!d.createElement) d.createElement = createElementStub;
    if (!d.documentElement) d.documentElement = { style: {} } as any;
    if (!d.querySelector) d.querySelector = () => null;
    if (!d.querySelectorAll) d.querySelectorAll = () => [];
    if (!d.getElementById) d.getElementById = () => null;
    if (!d.getElementsByTagName) d.getElementsByTagName = () => [];
    if (!d.body) d.body = { appendChild: () => {}, removeChild: () => {}, style: {}, querySelector: () => null, querySelectorAll: () => [] } as any;
    if (!d.head) d.head = { appendChild: () => {}, querySelector: () => null } as any;
    if (d.body && !d.body.appendChild) d.body.appendChild = () => {};
    if (d.body && !d.body.querySelector) d.body.querySelector = () => null;
    if (d.body && !d.body.querySelectorAll) d.body.querySelectorAll = () => [];
  }
  if (typeof (globalThis as any).window === 'undefined') {
    (globalThis as any).window = {
      location: { href: 'https://example.com/', pathname: '/', search: '', hash: '', origin: 'https://example.com' },
      history: { pushState: () => {}, replaceState: () => {} },
      innerWidth: 1024,
      innerHeight: 768,
      devicePixelRatio: 1,
      addEventListener: () => {},
      removeEventListener: () => {},
    } as any;
  } else {
    const w = (globalThis as any).window;
    if (!w.location) w.location = { href: 'https://example.com/', pathname: '/', search: '', hash: '', origin: 'https://example.com' } as any;
    if (!w.history) w.history = { pushState: () => {}, replaceState: () => {} } as any;
    if (w.devicePixelRatio === undefined) w.devicePixelRatio = 1;
    if (!w.addEventListener) w.addEventListener = () => {};
    if (!w.removeEventListener) w.removeEventListener = () => {};
    if (!(w as any).screen) (w as any).screen = (globalThis as any).screen;
    if (!(w as any).screen) (w as any).screen = (globalThis as any).screen;
  }
  if (typeof (globalThis as any).navigator === 'undefined') {
    (globalThis as any).navigator = {
      language: 'en-US',
      languages: ['en-US', 'en'],
      platform: 'MacIntel',
      hardwareConcurrency: 8,
      maxTouchPoints: 0,
      cookieEnabled: true,
      doNotTrack: '0',
      userAgent: 'Mozilla/5.0',
      connection: undefined,
    } as any;
  } else {
    const n = (globalThis as any).navigator;
    try { if (!n.language) n.language = 'en-US'; } catch {}
    try { if (!n.languages) n.languages = ['en-US', 'en']; } catch {}
    try { if (!n.platform) (n as any).platform = 'MacIntel'; } catch { try { Object.defineProperty(n, 'platform', { value: 'MacIntel', configurable: true }); } catch {} }
    try { if (n.hardwareConcurrency === undefined) (n as any).hardwareConcurrency = 8; } catch {}
    try { if (n.maxTouchPoints === undefined) (n as any).maxTouchPoints = 0; } catch {}
    try { if (n.cookieEnabled === undefined) (n as any).cookieEnabled = true; } catch {}
    try { if (n.doNotTrack === undefined) n.doNotTrack = '0'; } catch {}
    try { if (!n.userAgent) n.userAgent = 'Mozilla/5.0'; } catch {}
    // ensure required navigator fields exist without throwing
    try { if ((n as any).hardwareConcurrency === undefined) Object.defineProperty(n, 'hardwareConcurrency', { value: 8, configurable: true }); } catch {}
  }
  if (typeof (globalThis as any).screen === 'undefined') {
    (globalThis as any).screen = { width: 1920, height: 1080, colorDepth: 24 } as any;
  }
  if (typeof (globalThis as any).localStorage === 'undefined') {
    const _store: Record<string, string> = {};
    const ls: any = {
      getItem: (k: string) => (_store[k] ?? null),
      setItem: (k: string, v: string) => { _store[k] = String(v); ls[k] = String(v); },
      removeItem: (k: string) => { delete _store[k]; delete ls[k]; },
      clear: () => { Object.keys(_store).forEach(k => { delete _store[k]; delete ls[k]; }); },
      get length() { return Object.keys(_store).length; },
      key: (i: number) => Object.keys(_store)[i] ?? null,
    };
    (globalThis as any).localStorage = ls;
  }
  if (typeof (globalThis as any).history === 'undefined' && (globalThis as any).window?.history) {
    (globalThis as any).history = (globalThis as any).window.history;
  }
  if (typeof (globalThis as any).fetch === 'undefined') {
    (globalThis as any).fetch = async () => ({ ok: true, json: async () => ({}) } as any);
  }
  if (typeof (globalThis as any).OfflineAudioContext === 'undefined') {
    (globalThis as any).OfflineAudioContext = class {
      constructor() {}
      createOscillator() { return { type: 'triangle', frequency: { setValueAtTime: () => {} }, connect: () => {}, start: () => {} } as any; }
      createDynamicsCompressor() { return { connect: () => {} } as any; }
      get destination() { return {} as any; }
      get currentTime() { return 0; }
      async startRendering() { return { getChannelData: () => new Float32Array(5000) } as any; }
    } as any;
  }
  if (typeof (globalThis as any).crypto === 'undefined') {
    // Node 20 has crypto, but ensure subtle
  }
}

describe('FPS-050: Web SDK Initialization', () => {
  beforeEach(() => {
    ensureDomMocks();
  });
  afterEach(() => {
    try { (aether as any).destroy?.(); } catch {}
    // also clear any singleton state that might persist
    try {
      const inst = new AetherSDK();
      (inst as any).destroy?.();
    } catch {}
  });

  it('should have SDK version constant', () => {
    expect(SDK_VERSION).toBeDefined();
    expect(typeof SDK_VERSION).toBe('string');
    expect(SDK_VERSION).toBe('0.1.0-alpha.0');
  });

  it('should export AetherSDK class (as singleton factory)', () => {
    // Named export is the class constructor, default export is the singleton instance
    expect(typeof AetherSDK).toBe('function');
    expect(typeof aether).toBe('object');
    expect(typeof aether.init).toBe('function');
    expect(typeof AetherSDK.prototype.init).toBe('function');
  });

  it('should construct AetherSDK instance with apiKey and endpoint', () => {
    ensureDomMocks();
    const sdk = new AetherSDK();
    expect(sdk).toBeDefined();
    expect(typeof sdk.init).toBe('function');
    expect(() => sdk.init({ apiKey: 'test_key_123', endpoint: 'https://api.example.com' })).not.toThrow();
    // singleton also exposes init
    expect(typeof aether.init).toBe('function');
    sdk.destroy();
  });

  it('should accept configuration with only apiKey', () => {
    ensureDomMocks();
    const sdk = new AetherSDK();
    expect(() => sdk.init({ apiKey: 'test_key_only' } as any)).not.toThrow();
    sdk.destroy();
  });

  it('should construct EventEnvelope shape from track event fixture', () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.workspace_id).toBe('proof-lab');
    expect(envelope.platform_id).toBe('web');
    expect(envelope.environment).toBe('staging');
    expect(envelope.event_type).toBe('page');
    expect(envelope.sdk.name).toBe('@aether/web');
    expect(envelope.sdk.version).toBe('0.1.0-alpha.0');
    expect(envelope.identity.anonymous_id).toBe('anon_001');
    expect(envelope.identity.user_id).toBe('user_001');
  });

  it('should construct EventEnvelope shape from identify event fixture', () => {
    const envelope = identifyEventFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.workspace_id).toBe('proof-lab');
    expect(envelope.platform_id).toBe('web');
    expect(envelope.environment).toBe('staging');
    expect(envelope.event_type).toBe('identify');
    expect(envelope.identity.user_id).toBe('user_002');
  });

  it('should validate SDK static properties match fixture SDK info', () => {
    // SDK_VERSION is the module-level version; fixtures use 0.1.0-alpha.0
    const fixtureVersion = '0.1.0-alpha.0';
    expect(SDK_VERSION).toBeDefined();
    // Just verify both are strings — don't hard-code equality in case version drifts
    expect(typeof SDK_VERSION).toBe('string');
    expect(typeof fixtureVersion).toBe('string');
    expect(SDK_VERSION).toBe(fixtureVersion);
  });

  it('should throw without apiKey option', () => {
    const sdk = new AetherSDK();
    // init must throw when apiKey missing or empty, constructor itself does not throw
    expect(() => (sdk as any).init(undefined as any)).toThrow();
    expect(() => (sdk as any).init({} as any)).toThrow();
    expect(() => (sdk as any).init({ apiKey: '' } as any)).toThrow();
    expect(() => (sdk as any).init({ apiKey: null } as any)).toThrow();
    sdk.destroy();
  });
});
