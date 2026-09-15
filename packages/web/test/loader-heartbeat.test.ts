import { describe, expect, it, vi } from 'vitest';

import {
  buildSignalEvent,
  createBeaconTransport,
  reportInstallSignal,
  type InstallSignalInput,
} from '../src/loader/heartbeat';

const FIXED = new Date('2026-09-14T12:00:00.000Z');

function input(overrides: Partial<InstallSignalInput> = {}): InstallSignalInput {
  return {
    signal: 'sdk_initialized',
    installMode: 'cdn_auto',
    loaderVersion: '0.1.0-alpha.0',
    sdkKey: 'pk_live_abc',
    siteId: 'site_1',
    endpoint: 'https://api.aether.io',
    now: () => FIXED,
    randomId: () => 'marker-1',
    ...overrides,
  };
}

describe('install signal', () => {
  describe('buildSignalEvent', () => {
    it('mints a self-contained session so a failed init is still verifiable', () => {
      // The whole point of the verifier: sdk_init_failed has no SDK session to
      // borrow, so the signal must carry its own correlated identity.
      const event = buildSignalEvent(input({ signal: 'sdk_init_failed', reason: 'boom' }));

      expect(event.sessionId).toBe('install_marker-1');
      expect(event.anonymousId).toBe('install_marker-1');
      expect(event.id).toBe('marker-1');
      expect(event.timestamp).toBe('2026-09-14T12:00:00.000Z');
      expect(event.properties).toEqual({
        installMode: 'cdn_auto',
        loaderVersion: '0.1.0-alpha.0',
        siteId: 'site_1',
        reason: 'boom',
      });
    });

    it('omits optional properties rather than sending nulls', () => {
      const event = buildSignalEvent(input({ signal: 'sdk_loaded' }));
      expect(event.properties).not.toHaveProperty('sdkVersion');
      expect(event.properties).not.toHaveProperty('reason');
      expect(event.properties).not.toHaveProperty('warnings');
    });

    it('carries warnings and sdkVersion when present', () => {
      const event = buildSignalEvent(
        input({ sdkVersion: '1.2.3', warnings: ['unknown data-debug "maybe"'] }),
      );
      expect(event.properties.sdkVersion).toBe('1.2.3');
      expect(event.properties.warnings).toEqual(['unknown data-debug "maybe"']);
    });

    it('names the loader as the library, since the SDK may never have loaded', () => {
      const event = buildSignalEvent(input({ signal: 'sdk_init_failed' }));
      expect(event.context.library).toEqual({ name: '@aether/sdk', version: '0.1.0-alpha.0' });
    });

    it('produces distinct markers by default', () => {
      const a = buildSignalEvent(input({ randomId: undefined }));
      const b = buildSignalEvent(input({ randomId: undefined }));
      expect(a.id).not.toBe(b.id);
    });
  });

  describe('reportInstallSignal', () => {
    it('posts the batch envelope to {endpoint}/v1/batch with bearer auth', () => {
      const calls: Array<[string, any, Record<string, string>]> = [];
      const ok = reportInstallSignal(input(), (url, body, headers) => {
        calls.push([url, JSON.parse(body), headers]);
      });

      expect(ok).toBe(true);
      const [url, body, headers] = calls[0];
      expect(url).toBe('https://api.aether.io/v1/batch');
      expect(headers.Authorization).toBe('Bearer pk_live_abc');
      expect(headers['X-Aether-SDK']).toBe('web');
      expect(headers['X-Aether-Site']).toBe('site_1');
      expect(body.sentAt).toBe('2026-09-14T12:00:00.000Z');
      expect(body.batch).toHaveLength(1);
      expect(body.context.library.name).toBe('@aether/sdk');
    });

    it('refuses to send without a key or endpoint', () => {
      const transport = vi.fn();
      expect(reportInstallSignal(input({ sdkKey: '' }), transport)).toBe(false);
      expect(reportInstallSignal(input({ endpoint: '' }), transport)).toBe(false);
      expect(transport).not.toHaveBeenCalled();
    });

    it('omits the site header when there is no site', () => {
      let headers: Record<string, string> = {};
      reportInstallSignal(input({ siteId: '' }), (_u, _b, h) => {
        headers = h;
      });
      expect(headers).not.toHaveProperty('X-Aether-Site');
    });

    it('swallows a throwing transport', () => {
      // A reporting failure must never become the customer's page error.
      const ok = reportInstallSignal(input(), () => {
        throw new Error('CSP blocked');
      });
      expect(ok).toBe(false);
    });
  });

  describe('createBeaconTransport', () => {
    it('uses fetch with keepalive so the signal survives page unload', () => {
      const fetchImpl = vi.fn(async () => ({}) as Response);
      createBeaconTransport(fetchImpl as never)('https://api.aether.io/v1/batch', '{}', {
        Authorization: 'Bearer k',
      });

      expect(fetchImpl).toHaveBeenCalledWith('https://api.aether.io/v1/batch', {
        method: 'POST',
        headers: { Authorization: 'Bearer k' },
        body: '{}',
        keepalive: true,
      });
    });

    it('never uses sendBeacon, which cannot carry the Authorization header', () => {
      // sendBeacon would force the publishable key into the URL, where proxy
      // and CDN logs would keep it. This is a deliberate, load-bearing choice.
      const source = createBeaconTransport.toString();
      expect(source).not.toContain('sendBeacon');
    });

    it('does not reject when the request fails', async () => {
      const fetchImpl = vi.fn(() => Promise.reject(new Error('offline')));
      expect(() =>
        createBeaconTransport(fetchImpl as never)('https://api.aether.io/v1/batch', '{}', {}),
      ).not.toThrow();
      await Promise.resolve();
    });

    it('does not reject on a synchronous throw from fetch itself', () => {
      const fetchImpl = vi.fn(() => {
        throw new Error('blocked by extension');
      });
      expect(() =>
        createBeaconTransport(fetchImpl as never)('https://api.aether.io/v1/batch', '{}', {}),
      ).not.toThrow();
    });

    it('is inert where fetch does not exist', () => {
      expect(() =>
        createBeaconTransport(undefined)('https://api.aether.io/v1/batch', '{}', {}),
      ).not.toThrow();
    });

    it('round-trips a real signal through fetch', () => {
      const fetchImpl = vi.fn(async () => ({}) as Response);
      reportInstallSignal(input(), createBeaconTransport(fetchImpl as never));

      const [, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
      const body = JSON.parse(init.body as string);
      expect(body.batch[0].type).toBe('sdk_initialized');
      expect(body.batch[0].properties.installMode).toBe('cdn_auto');
    });
  });
});
