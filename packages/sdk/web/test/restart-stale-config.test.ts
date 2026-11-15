// @vitest-environment jsdom
/**
 * A /v1/config response that arrives after destroy() belongs to the previous
 * install and must not load its funnel definitions into the replacement
 * instance (the React provider restarts the SDK when the key or site changes).
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import aether from '../src/index';
import { FunnelModule } from '../src/modules/funnels';

const CONFIG = (apiKey: string) => ({
  apiKey,
  endpoint: 'https://api.test',
  modules: { autoDiscovery: false, performance: false, funnels: true },
});

describe('restart and late /v1/config responses', () => {
  afterEach(() => {
    try { aether.destroy(); } catch { /* ignore */ }
    vi.restoreAllMocks();
  });

  it('ignores the previous install\'s funnel definitions', async () => {
    const pending: Record<string, (body: unknown) => void> = {};
    (globalThis as any).fetch = vi.fn((url: string, init?: any) => {
      if (String(url).endsWith('/v1/config')) {
        const key = String(init?.headers?.Authorization ?? '');
        return new Promise((resolve) => {
          pending[key] = (body) => resolve({ ok: true, status: 200, json: async () => body } as any);
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: null, accepted: 0, duplicates: 0, rejected: 0 }), text: async () => '{}' } as any);
    });
    const load = vi.spyOn(FunnelModule.prototype, 'loadDefinitions');

    aether.init(CONFIG('pk_old'));   // /v1/config for the old install is in flight
    aether.destroy();
    aether.init(CONFIG('pk_new'));

    pending['Bearer pk_new']({ funnelDefinitions: [{ id: 'new', name: 'new', steps: [] }] });
    await new Promise((r) => setTimeout(r, 0));
    pending['Bearer pk_old']({ funnelDefinitions: [{ id: 'old', name: 'old', steps: [] }] });
    await new Promise((r) => setTimeout(r, 0));

    expect(load).toHaveBeenCalledTimes(1);
    expect(load.mock.calls[0][0][0].id).toBe('new');
  });
});
