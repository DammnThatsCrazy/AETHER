// PR2 — the server transport must send the canonical /v1/batch envelope
// ({ batch, sentAt, consents }), the API key in the Authorization header only,
// and never the legacy { events } shape or an API key in the query string.
import { afterEach, describe, expect, it, vi } from 'vitest';

import { sendBatch } from './transport';

describe('server transport — canonical /v1/batch envelope', () => {
  afterEach(() => vi.restoreAllMocks());

  it('sends { batch, sentAt, consents } — not { events }', async () => {
    let captured: any;
    const fetchMock = vi.fn(async (_url: string, init: any) => {
      captured = { url: _url, init, body: JSON.parse(init.body) };
      return { ok: true, status: 200, headers: { get: () => null } } as any;
    });
    (globalThis as any).fetch = fetchMock;

    const events = [{ id: 'e1', type: 'api_request_observed' }];
    const res = await sendBatch(
      { endpoint: 'https://api.test/v1/batch', writeKey: 'sk_test' },
      events,
      ['analytics'],
    );

    expect(res.ok).toBe(true);
    // Canonical envelope shape.
    expect(captured.body.batch).toEqual(events);
    expect(typeof captured.body.sentAt).toBe('string');
    expect(captured.body.consents).toEqual(['analytics']);
    // The retired legacy shape must be gone.
    expect(captured.body.events).toBeUndefined();
  });

  it('puts the write key in Authorization header, never the URL', async () => {
    let captured: any;
    (globalThis as any).fetch = vi.fn(async (url: string, init: any) => {
      captured = { url, init };
      return { ok: true, status: 200, headers: { get: () => null } } as any;
    });

    await sendBatch(
      { endpoint: 'https://api.test/v1/batch', writeKey: 'sk_secret' },
      [{ id: 'e1', type: 'job_started' }],
      [],
    );

    expect(captured.url).not.toContain('sk_secret');
    expect(captured.url).not.toContain('apiKey=');
    expect(captured.init.headers.Authorization).toBe('Bearer sk_secret');
  });
});
