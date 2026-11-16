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

  it('does not resume a journey redeemed for the previous install', async () => {
    let respond!: (body: unknown) => void;
    (globalThis as any).fetch = vi.fn((url: string) => {
      if (String(url).endsWith('/sdk/journey-handoff/redeem')) {
        return new Promise((resolve) => {
          respond = (body) => resolve({ ok: true, status: 200, json: async () => body } as any);
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: null, accepted: 0, duplicates: 0, rejected: 0 }), text: async () => '{}' } as any);
    });

    aether.init(CONFIG('pk_old'));
    const redeemed = aether.redeemJourneyHandoff('tok_old');
    aether.destroy();
    aether.init(CONFIG('pk_new'));
    respond({ data: { link_basis: 'explicit_handoff', journey_id: 'journey_old', handoff_id: 'h1' } });

    expect(await redeemed).toBeNull();
    expect(aether.getCurrentJourney()?.journeyId).not.toBe('journey_old');
  });

  it('does not resolve the previous install\'s identity under the new key', async () => {
    const resolveCalls: { key: string; body: any }[] = [];
    (globalThis as any).fetch = vi.fn(async (url: string, init?: any) => {
      if (String(url).endsWith('/sdk/identity/resolve')) {
        resolveCalls.push({ key: init?.headers?.['x-api-key'], body: JSON.parse(init.body) });
      }
      return { ok: true, status: 200, json: async () => ({ resolved: false, data: null, accepted: 0, duplicates: 0, rejected: 0 }), text: async () => '{}' } as any;
    });

    aether.init(CONFIG('pk_old'));
    aether.hydrateIdentity({ userId: 'old-user', traits: {} } as any);
    // The email hash / resolve continuation is async; restart before it runs.
    aether.destroy();
    aether.init(CONFIG('pk_new'));
    await new Promise((r) => setTimeout(r, 10));

    expect(resolveCalls.filter((c) => c.key === 'pk_new' && c.body.user_id === 'old-user')).toHaveLength(0);
  });

  it('resolves the same email again for the replacement install', async () => {
    // Which keys received the email hash (init() also resolves, but without one).
    const emailHashKeys: string[] = [];
    (globalThis as any).fetch = vi.fn(async (url: string, init?: any) => {
      if (String(url).endsWith('/sdk/identity/resolve') && JSON.parse(init.body).email_hash) {
        emailHashKeys.push(init?.headers?.['x-api-key']);
      }
      return { ok: true, status: 200, json: async () => ({ resolved: false, data: null, accepted: 0, duplicates: 0, rejected: 0 }), text: async () => '{}' } as any;
    });
    const settle = () => new Promise((r) => setTimeout(r, 20));
    // jsdom's TextEncoder and Node's WebCrypto come from different realms, so the
    // real digest fails there; a stable hash arms the de-dupe the way a browser would.
    vi.spyOn(aether as any, '_hashEmail').mockResolvedValue('a'.repeat(64));

    aether.init(CONFIG('pk_old'));
    aether.hydrateIdentity({ email: 'person@example.com' } as any);
    await settle();
    aether.destroy();
    aether.init(CONFIG('pk_new'));
    aether.hydrateIdentity({ email: 'person@example.com' } as any);
    await settle();

    expect(emailHashKeys).toEqual(['pk_old', 'pk_new']);
  });
});
