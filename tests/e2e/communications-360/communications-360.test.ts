/**
 * FPS-106 — Communications 360 (E2E)
 * Send communication events via batch, query communications 360, verify data.
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

describe.skipIf(!API_KEY)('FPS-106: Communications 360', () => {

  it('should POST communication events to batch endpoint', async () => {
    const events: EventEnvelope[] = [
      {
        tenant_id: 'aether-proof-tenant',
        workspace_id: 'proof-lab',
        platform_id: 'email',
        environment: 'staging',
        event_type: 'email_opened',
        sdk: { name: '@aether/email', version: '0.1.0-alpha.0' },
        identity: { anonymous_id: 'anon_comms_001' },
        timestamp: new Date().toISOString(),
        properties: {
          message_id: 'msg_e2e_open_001',
          campaign_id: 'camp_e2e_001',
          email: 'user@example.com',
          opened_at: new Date().toISOString(),
        },
      },
    ];

    const result = await httpPost<{ accepted: number; batch_id: string }>(
      '/v1/batch',
      { events },
    );
    expect(result.accepted).toBe(1);
  });

  it('should query communications 360 endpoint and return data', async () => {
    const comms = await httpGet<{
      communication_id: string;
      channel: string;
      type: string;
      surfaces: Array<{ source: string; event_count: number }>;
    }>('/v1/360/communications/msg_e2e_open_001');
    expect(comms.communication_id).toBe('msg_e2e_open_001');
    expect(comms.channel).toBe('email');
    expect(Array.isArray(comms.surfaces)).toBe(true);
  });

  it('should verify communications surfaces have expected sources', async () => {
    const comms = await httpGet<{
      communication_id: string;
      surfaces: Array<{ source: string }>;
    }>('/v1/360/communications/msg_e2e_open_001');
    const sources = comms.surfaces.map((s) => s.source);
    expect(sources.length).toBeGreaterThan(0);
  });
});
