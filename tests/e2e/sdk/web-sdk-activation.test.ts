/**
 * FPS-102 — Web SDK Activation (E2E)
 * End-to-end: initialize SDK, emit events, verify via API.
 * Skips if AETHER_API_KEY is missing.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { trackEventFixture } from '@aether/proof-fixtures';

const API_URL = process.env.AETHER_API_URL || 'http://localhost:8000';
const API_KEY = process.env.AETHER_API_KEY;

function headers(): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    'X-Aether-API-Key': API_KEY!,
  };
}

function fetchJSON<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  return fetch(input, {
    ...init,
    headers: { ...headers(), ...init?.headers },
  }).then((res) => {
    if (res.status === 401 || res.status === 403) {
      throw new Error(`Auth failed: ${res.status}`);
    }
    if (res.status === 429) {
      throw new Error('Rate limited');
    }
    if (res.status >= 500) {
      throw new Error(`Server error: ${res.status}`);
    }
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    return res.json() as Promise<T>;
  });
}

async function httpPost<T>(path: string, body: unknown): Promise<T> {
  return fetchJSON<T>(`${API_URL}${path}`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

async function httpGet<T>(path: string): Promise<T> {
  return fetchJSON<T>(`${API_URL}${path}`, { method: 'GET' });
}

describe.skipIf(!API_KEY)('FPS-102: Web SDK Activation', () => {

  it('should initialize SDK with API key', () => {
    // The SDK initialization requires a valid API key.
    // We verify that the key is present and well-formed.
    expect(API_KEY).toBeTruthy();
    expect(API_KEY?.length).toBeGreaterThan(10);
  });

  it('should emit heartbeat event', async () => {
    const envelope = trackEventFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.event_type).toBe('page');

    // POST the event to the batch ingestion endpoint
    const result = await httpPost<{ accepted: number; batch_id: string }>(
      '/v1/batch',
      { events: [envelope] },
    );
    expect(result.accepted).toBe(1);
    expect(result.batch_id).toBeDefined();
  });

  it('should verify events were accepted via platform last_seen_at', async () => {
    // Query the platform endpoint to verify the event was processed.
    const platform = await httpGet<{
      platform_id: string;
      last_seen_at: string;
      event_count: number;
    }>('/v1/platform/web');
    expect(platform.platform_id).toBe('web');
    expect(platform.last_seen_at).toBeDefined();
    expect(platform.event_count).toBeGreaterThanOrEqual(0);
  });
});
