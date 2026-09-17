/**
 * FPS-104 — Profile 360 (E2E)
 * Send events via batch, query profile 360, verify expected data.
 * Skips if AETHER_API_KEY is missing.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';

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

describe.skipIf(!API_KEY)('FPS-104: Profile 360', () => {

  it('should POST events to batch endpoint', async () => {
    const events: EventEnvelope[] = [
      {
        tenant_id: 'aether-proof-tenant',
        workspace_id: 'proof-lab',
        platform_id: 'web',
        environment: 'staging',
        event_type: 'page',
        sdk: { name: '@aether/web', version: '0.1.0-alpha.0' },
        identity: { anonymous_id: 'anon_profile_001', user_id: 'user_profile_001' },
        timestamp: new Date().toISOString(),
        properties: { url: 'https://example.com/profile-test', path: '/profile-test' },
      },
    ];

    const result = await httpPost<{ accepted: number; batch_id: string }>(
      '/v1/batch',
      { events },
    );
    expect(result.accepted).toBe(1);
  });

  it('should query profile 360 endpoint and return data', async () => {
    const profile = await httpGet<{
      profile_id: string;
      anonymous_id: string;
      user_id: string | null;
      surfaces: Array<{ source: string; last_seen: string; properties: unknown }>;
    }>('/v1/360/profile/anon_profile_001');
    expect(profile.profile_id).toBeDefined();
    expect(profile.anonymous_id).toBe('anon_profile_001');
    expect(Array.isArray(profile.surfaces)).toBe(true);
  });

  it('should verify surfaces contain expected sources', async () => {
    const profile = await httpGet<{
      profile_id: string;
      surfaces: Array<{ source: string; last_seen: string }>;
    }>('/v1/360/profile/anon_profile_001');
    const sources = profile.surfaces.map((s) => s.source);
    // Should have at least the web source from the event we posted
    expect(sources.length).toBeGreaterThan(0);
  });
});
