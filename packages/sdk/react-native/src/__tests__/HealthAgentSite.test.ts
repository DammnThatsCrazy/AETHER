import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('react-native', () => ({
  NativeModules: {},
  NativeEventEmitter: class {},
  Platform: { OS: 'ios' },
}));

import { RNHealthAgent } from '../modules/HealthAgent';

// A native app ships a site-bound publishable key, and the backend refuses a
// publishable key on a request that declares no site. The heartbeat is one of
// the native SDK posts that key may reach, so it must declare the site.
describe('RNHealthAgent site declaration', () => {
  const fetchMock = vi.fn(async () => ({ ok: true }));

  beforeEach(() => {
    fetchMock.mockClear();
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function firstHeartbeatHeaders(config: ConstructorParameters<typeof RNHealthAgent>[0]) {
    const agent = new RNHealthAgent({ heartbeatIntervalMs: 60_000, ...config });
    agent.start();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    agent.stop();
    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    return init.headers as Record<string, string>;
  }

  it('sends X-Aether-Site when a site id is configured', async () => {
    const headers = await firstHeartbeatHeaders({
      endpoint: 'https://api.example.test',
      apiKey: 'pk_live_x',
      siteId: 'site_app',
    });
    expect(headers['X-Aether-Site']).toBe('site_app');
    expect(headers['Authorization']).toBe('Bearer pk_live_x');
  });

  it('omits the header without a site id', async () => {
    const headers = await firstHeartbeatHeaders({
      endpoint: 'https://api.example.test',
      apiKey: 'ak_secret',
    });
    expect(headers).not.toHaveProperty('X-Aether-Site');
  });
});
