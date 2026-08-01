import { describe, expect, it } from 'vitest';

import { AetherMobileClient, MobileApiError } from '../index';
import type { FetchLike, FetchRequestInit } from '../index';

interface RecordedCall {
  url: string;
  init: FetchRequestInit;
}

function stubClient(
  responder: (call: RecordedCall) => { status: number; body: unknown },
  token: string | null = 'tok-123',
) {
  const calls: RecordedCall[] = [];
  const fetch: FetchLike = async (url, init) => {
    const call = { url, init };
    calls.push(call);
    const { status, body } = responder(call);
    return {
      status,
      json: async () => body,
      text: async () => JSON.stringify(body),
    };
  };
  const client = new AetherMobileClient(
    { apiBaseUrl: 'https://api.aether.test/', appKind: 'aether', environment: 'production' },
    { fetch, auth: { getAccessToken: async () => token } },
  );
  return { client, calls };
}

describe('AetherMobileClient', () => {
  it('registers an installation, unwrapping the APIResponse envelope', async () => {
    const { client, calls } = stubClient(() => ({
      status: 200,
      body: {
        data: {
          installation: {
            id: 'inst_1',
            principal_id: 'user-1',
            app_kind: 'aether',
            platform: 'ios',
            bundle_id: 'com.aether.app',
            environment: 'production',
            trust_state: 'registered',
            created_at: '2026-01-01T00:00:00Z',
          },
          subscription: null,
        },
      },
    }));
    const result = await client.registerInstallation({
      platform: 'ios',
      bundle_id: 'com.aether.app',
      environment: 'production',
    });
    expect(result.installation.id).toBe('inst_1');
    expect(result.subscription).toBeNull();
    // base URL trailing slash is normalized; the mobile path is correct.
    expect(calls[0].url).toBe('https://api.aether.test/v1/mobile/installations');
    expect(calls[0].init.headers.authorization).toBe('Bearer tok-123');
  });

  it('omits the Authorization header when unauthenticated', async () => {
    const { client, calls } = stubClient(() => ({ status: 200, body: { data: { installations: [] } } }), null);
    await client.listInstallations();
    expect(calls[0].init.headers.authorization).toBeUndefined();
  });

  it('resolves a deep link', async () => {
    const { client, calls } = stubClient(() => ({
      status: 200,
      body: { data: { resolved: false, reason: 'unresolvable' } },
    }));
    const res = await client.resolveDeepLink('inst_1', 'cont_1');
    expect(res.resolved).toBe(false);
    expect(res.reason).toBe('unresolvable');
    expect(calls[0].url).toBe('https://api.aether.test/v1/mobile/deep-links/resolve');
    expect(JSON.parse(calls[0].init.body ?? '{}')).toEqual({
      installation_id: 'inst_1',
      continuation_id: 'cont_1',
    });
  });

  it('reads the client-sync feed with a cursor', async () => {
    const { client, calls } = stubClient(() => ({
      status: 200,
      body: { data: { events: [], cursor: '10:5', has_more: false, reset: false } },
    }));
    const feed = await client.clientSync('0:0');
    expect(feed.cursor).toBe('10:5');
    expect(calls[0].url).toBe('https://api.aether.test/v1/client-sync?cursor=0%3A0');
  });

  it('throws MobileApiError on a non-2xx response', async () => {
    const { client } = stubClient(() => ({ status: 409, body: { error: 'conflict' } }));
    await expect(client.getContinuation('c1')).rejects.toBeInstanceOf(MobileApiError);
  });
});
