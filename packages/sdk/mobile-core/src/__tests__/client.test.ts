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

  it('reads the operator client-sync feed with no query params', async () => {
    const { client, calls } = stubClient(() => ({
      status: 200,
      body: { data: { events: [], cursor: 'op:9', has_more: false, reset: true } },
    }));
    const feed = await client.operatorClientSync();
    expect(feed.cursor).toBe('op:9');
    expect(feed.reset).toBe(true);
    expect(calls[0].url).toBe('https://api.aether.test/v1/kyber/client-sync');
    expect(calls[0].init.method ?? 'GET').toBe('GET');
    expect(calls[0].init.headers.authorization).toBe('Bearer tok-123');
  });

  it('emits only the set operator client-sync query params', async () => {
    const { client, calls } = stubClient(() => ({
      status: 200,
      body: { data: { events: [], cursor: 'op:1', has_more: false, reset: false } },
    }));
    await client.operatorClientSync({ cursor: '0:0' });
    expect(calls[0].url).toBe('https://api.aether.test/v1/kyber/client-sync?cursor=0%3A0');

    await client.operatorClientSync({ cursor: '0:0', limit: 50 });
    expect(calls[1].url).toBe('https://api.aether.test/v1/kyber/client-sync?cursor=0%3A0&limit=50');

    await client.operatorClientSync({ limit: 50 });
    expect(calls[2].url).toBe('https://api.aether.test/v1/kyber/client-sync?limit=50');
  });

  it('unwraps the ClientSyncResponse envelope from the operator feed', async () => {
    const { client, calls } = stubClient(() => ({
      status: 200,
      body: {
        data: {
          events: [
            {
              seq: 1,
              tenant_id: 'op-1',
              principal_id: 'op-1',
              change_type: 'command_receipt_changed',
              resource_kind: 'command_receipt',
              resource_id: 'cmd_1',
              payload: {},
              emitted_at: '2026-08-01T00:00:00Z',
            },
          ],
          cursor: 'op:2',
          has_more: true,
          reset: false,
        },
      },
    }));
    const feed = await client.operatorClientSync({ cursor: 'op:1' });
    expect(feed.events).toHaveLength(1);
    expect(feed.events[0].change_type).toBe('command_receipt_changed');
    expect(feed.events[0].resource_id).toBe('cmd_1');
    expect(feed.has_more).toBe(true);
    expect(calls[0].url).toBe('https://api.aether.test/v1/kyber/client-sync?cursor=op%3A1');
  });

  it('surfaces a 404 from the flag-gated operator client-sync router as MobileApiError', async () => {
    const { client } = stubClient(() => ({ status: 404, body: { detail: 'not found' } }));
    try {
      await client.operatorClientSync();
      throw new Error('expected operatorClientSync to reject');
    } catch (err) {
      expect(err).toBeInstanceOf(MobileApiError);
      expect((err as MobileApiError).status).toBe(404);
    }
  });

  it('throws MobileApiError on a non-2xx response', async () => {
    const { client } = stubClient(() => ({ status: 409, body: { error: 'conflict' } }));
    await expect(client.getContinuation('c1')).rejects.toBeInstanceOf(MobileApiError);
  });

  it('lists recent operator continuations via the /v1/kyber/continuations router', async () => {
    const { client, calls } = stubClient(() => ({
      status: 200,
      body: {
        data: {
          continuations: [
            {
              version: '1',
              id: 'cont_op_1',
              principal_id: 'operator-1',
              app_kind: 'kyber',
              source_client: 'desktop',
              surface: 'investigation',
              resource_references: [],
              canonical_context: {},
              summary: { title: 'Resume the settlement incident', subtitle: 'kyber' },
              state_revision: 1,
              sensitivity: 'standard',
              updated_at: '2026-08-01T00:00:00Z',
            },
          ],
        },
      },
    }));
    const list = await client.operatorRecentContinuations();
    expect(list).toHaveLength(1);
    expect(list[0].id).toBe('cont_op_1');
    expect(list[0].summary.title).toBe('Resume the settlement incident');
    expect(calls[0].url).toBe('https://api.aether.test/v1/kyber/continuations/recent');
  });

  it('reads one operator continuation by id', async () => {
    const { client, calls } = stubClient(() => ({
      status: 200,
      body: {
        data: {
          version: '1',
          id: 'cont_op_7',
          principal_id: 'operator-1',
          app_kind: 'kyber',
          source_client: 'desktop',
          surface: 'incident',
          resource_references: [],
          canonical_context: {},
          summary: { title: 'Investigate the webhook storm' },
          state_revision: 2,
          sensitivity: 'restricted',
          updated_at: '2026-08-02T00:00:00Z',
        },
      },
    }));
    const continuation = await client.operatorGetContinuation('cont_op_7');
    expect(continuation.id).toBe('cont_op_7');
    expect(calls[0].url).toBe('https://api.aether.test/v1/kyber/continuations/cont_op_7');
  });

  it('surfaces a 404 from the flag-gated operator router as MobileApiError', async () => {
    const { client } = stubClient(() => ({ status: 404, body: { detail: 'not found' } }));
    try {
      await client.operatorRecentContinuations();
      throw new Error('expected operatorRecentContinuations to reject');
    } catch (err) {
      expect(err).toBeInstanceOf(MobileApiError);
      expect((err as MobileApiError).status).toBe(404);
    }
  });
});
