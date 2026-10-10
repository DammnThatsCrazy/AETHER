import { describe, expect, it, vi } from 'vitest';

import { bootstrap, run } from '../src/loader/bootstrap';
import type { SignalTransport } from '../src/loader/heartbeat';

/** Records every signal handed to the transport, in order. */
function recordingTransport(): { sent: Array<{ url: string; body: any; headers: Record<string, string> }>; transport: SignalTransport } {
  const sent: Array<{ url: string; body: any; headers: Record<string, string> }> = [];
  return {
    sent,
    transport: (url, body, headers) => {
      sent.push({ url, body: JSON.parse(body), headers });
    },
  };
}

/** A stand-in for the loaded SDK bundle. */
function fakeSdk(overrides: Record<string, unknown> = {}) {
  return {
    init: vi.fn(),
    track: vi.fn(),
    identify: vi.fn(),
    page: vi.fn(),
    ...overrides,
  };
}

function fakeLoader(sdk: unknown, version = '1.2.3') {
  return {
    load: vi.fn(async () => sdk),
    getLoadedVersion: () => version,
  };
}

const SNIPPET = { 'data-key': 'pk_live_abc', 'data-site': 'site_1' };

describe('one-tag bootstrap', () => {
  it('installs, inits, and reports the install handshake', async () => {
    const sdk = fakeSdk();
    const loader = fakeLoader(sdk);
    const { sent, transport } = recordingTransport();
    const target: Record<string, unknown> = {};

    const result = await bootstrap({
      doc: { currentScript: { getAttribute: (n: string) => SNIPPET[n as never] ?? null } } as never,
      target,
      loader,
      transport,
    });

    expect(result.ok).toBe(true);
    expect(result.errors).toEqual([]);
    expect(result.sdkVersion).toBe('1.2.3');

    // The snippet's key and site reach the SDK as its apiKey and siteId.
    expect(sdk.init).toHaveBeenCalledWith(
      expect.objectContaining({
        apiKey: 'pk_live_abc',
        siteId: 'site_1',
        endpoint: 'https://api.aether.io',
      }),
    );

    // Loaded then initialized, in that order.
    expect(sent.map((s) => s.body.batch[0].type)).toEqual(['sdk_loaded', 'sdk_initialized']);

    // The live SDK replaces the stub on the global.
    expect(target.Aether).toBe(sdk);
  });

  it('captures calls made before the SDK exists and replays them in order', async () => {
    const sdk = fakeSdk();
    const { transport } = recordingTransport();
    const target: Record<string, unknown> = {};

    // The stub is installed synchronously; a slow loader must not lose calls.
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const loader = {
      load: vi.fn(async () => {
        await gate;
        return sdk;
      }),
      getLoadedVersion: () => '1.2.3',
    };

    const pending = bootstrap({
      doc: { currentScript: { getAttribute: (n: string) => SNIPPET[n as never] ?? null } } as never,
      target,
      loader,
      transport,
    });

    const stub = target.Aether as { track(...a: unknown[]): void; page(...a: unknown[]): void };
    stub.track('signup', { plan: 'pro' });
    stub.page('Pricing');

    release();
    const result = await pending;

    expect(sdk.track).toHaveBeenCalledWith('signup', { plan: 'pro' });
    expect(sdk.page).toHaveBeenCalledWith('Pricing');
    expect(result.drained).toEqual({ drained: 2, failures: [] });
    // The queue is emptied so a later drain cannot double-send.
    expect((target.Aether as never as { q: unknown[] }).q ?? []).toEqual([]);
  });

  it('reports sdk_init_failed instead of throwing when config is invalid', async () => {
    const loader = fakeLoader(fakeSdk());
    const { sent, transport } = recordingTransport();

    const result = await bootstrap({
      doc: { currentScript: { getAttribute: () => null } } as never,
      target: {},
      loader,
      transport,
    });

    expect(result.ok).toBe(false);
    expect(result.config).toBeNull();
    expect(result.errors).toEqual([
      'missing data-key (publishable SDK key)',
      'missing data-site (site id)',
    ]);
    // Nothing to report *to* without a key/endpoint, so no signal is sent —
    // and the loader is never asked to fetch a bundle.
    expect(sent).toEqual([]);
    expect(loader.load).not.toHaveBeenCalled();
  });

  it('reports sdk_init_failed when the bundle cannot be loaded', async () => {
    const { sent, transport } = recordingTransport();
    const loader = {
      load: vi.fn(async () => {
        throw new Error('HTTP 404: Not Found');
      }),
      getLoadedVersion: () => null,
    };

    const result = await bootstrap({
      doc: { currentScript: { getAttribute: (n: string) => SNIPPET[n as never] ?? null } } as never,
      target: {},
      loader,
      transport,
    });

    expect(result.ok).toBe(false);
    expect(result.errors).toEqual(['HTTP 404: Not Found']);
    // The failure is reported against the tenant's own key, so a broken install
    // is visible from the event stream rather than looking like no traffic.
    expect(sent.map((s) => s.body.batch[0].type)).toEqual(['sdk_init_failed']);
    expect(sent[0].headers.Authorization).toBe('Bearer pk_live_abc');
  });

  it('reports sdk_init_failed when the bundle exposes no init()', async () => {
    const { sent, transport } = recordingTransport();
    const loader = fakeLoader({ notAnSdk: true });

    const result = await bootstrap({
      doc: { currentScript: { getAttribute: (n: string) => SNIPPET[n as never] ?? null } } as never,
      target: {},
      loader,
      transport,
    });

    expect(result.ok).toBe(false);
    expect(result.errors[0]).toContain('does not expose init()');
    // Both signals, and that pairing is the point: the CDN served *something*
    // (so the URL resolves and the edge is up) but it was not an SDK. Reporting
    // only the failure would not distinguish this from a fetch that never
    // completed.
    expect(sent.map((s) => s.body.batch[0].type)).toEqual(['sdk_loaded', 'sdk_init_failed']);
  });

  it('sends every signal with the SDK batch wire contract', async () => {
    const sdk = fakeSdk();
    const { sent, transport } = recordingTransport();

    await bootstrap({
      doc: {
        currentScript: {
          getAttribute: (n: string) => ({ ...SNIPPET, 'data-site': 'site_9' }[n as never] ?? null),
        },
      } as never,
      target: {},
      loader: fakeLoader(sdk),
      transport,
    });

    const first = sent[0];
    expect(first.url).toBe('https://api.aether.io/v1/batch');
    expect(first.headers.Authorization).toBe('Bearer pk_live_abc');
    expect(first.headers['X-Aether-SDK']).toBe('web');
    expect(first.headers['X-Aether-Site']).toBe('site_9');
    expect(first.body.batch[0]).toMatchObject({
      type: 'sdk_loaded',
      sessionId: expect.any(String),
      anonymousId: expect.any(String),
      context: { library: { name: '@aether/sdk', version: expect.any(String) } },
    });
    expect(typeof first.body.sentAt).toBe('string');
  });

  it('surfaces snippet warnings without failing the install', async () => {
    const sdk = fakeSdk();
    const { transport } = recordingTransport();

    const result = await bootstrap({
      doc: {
        currentScript: {
          getAttribute: (n: string) =>
            ({ ...SNIPPET, 'data-autocapture': 'everything' }[n as never] ?? null),
        },
      } as never,
      target: {},
      loader: fakeLoader(sdk),
      transport,
    });

    expect(result.ok).toBe(true);
    expect(result.warnings).toEqual(['unknown data-autocapture "everything"; falling back to "safe"']);
    expect(sdk.init).toHaveBeenCalled();
  });

  it('does not boot twice when the snippet is included twice', async () => {
    const sdk = fakeSdk();
    const loader = fakeLoader(sdk);
    const { transport } = recordingTransport();
    const target: Record<string, unknown> = {};
    const doc = {
      currentScript: { getAttribute: (n: string) => SNIPPET[n as never] ?? null },
    } as never;

    await bootstrap({ doc, target, loader, transport });
    const second = run({ doc, target, loader, transport });

    // The second inclusion is a no-op, not a second fetch or a clobbered SDK.
    expect(second).toBeUndefined();
    expect(loader.load).toHaveBeenCalledTimes(1);
    expect(target.Aether).toBe(sdk);
  });

  it('finds the snippet when currentScript is unavailable', async () => {
    // An `async` script runs after the parser has moved on, and some bundlers
    // hoist the module — either way document.currentScript is null by then. The
    // install must still find its own tag rather than booting unconfigured.
    const sdk = fakeSdk();
    const { transport } = recordingTransport();
    const tag = {
      src: 'https://cdn.aether.network/v1.js',
      getAttribute: (n: string) => SNIPPET[n as never] ?? null,
    };
    const doc = {
      currentScript: null,
      getElementsByTagName: (name: string) => (name === 'script' ? [tag] : []),
    };

    const result = await bootstrap({
      doc: doc as never,
      target: {},
      loader: fakeLoader(sdk),
      transport,
    });

    expect(result.ok).toBe(true);
    expect(sdk.init).toHaveBeenCalledWith(expect.objectContaining({ apiKey: 'pk_live_abc' }));
  });

  it('ignores unrelated script tags when recovering the snippet', async () => {
    const sdk = fakeSdk();
    const { transport } = recordingTransport();
    const unrelated = ['https://example.com/analytics.js', 'https://cdn.aether.network/v2.js'];
    const doc = {
      currentScript: null,
      getElementsByTagName: () => unrelated.map((src) => ({ src, getAttribute: () => 'nope' })),
    };

    const result = await bootstrap({
      doc: doc as never,
      target: {},
      loader: fakeLoader(sdk),
      transport,
    });

    // v2.js is a different loader; matching it would hand this install to a
    // version it did not ask for.
    expect(result.ok).toBe(false);
    expect(result.errors).toContain('missing data-key (publishable SDK key)');
    expect(sdk.init).not.toHaveBeenCalled();
  });
});
