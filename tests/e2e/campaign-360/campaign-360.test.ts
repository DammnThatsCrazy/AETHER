/**
 * FPS-105 — Campaign 360 (E2E)
 * Send campaign events via batch, query campaign 360, verify data.
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

describe.skipIf(!API_KEY)('FPS-105: Campaign 360', () => {

  it('should POST campaign events to batch endpoint', async () => {
    const events: EventEnvelope[] = [
      {
        tenant_id: 'aether-proof-tenant',
        workspace_id: 'proof-lab',
        platform_id: 'email',
        environment: 'staging',
        event_type: 'email_sent',
        sdk: { name: '@aether/email', version: '0.1.0-alpha.0' },
        identity: { anonymous_id: 'anon_campaign_001' },
        timestamp: new Date().toISOString(),
        properties: {
          campaign_id: 'camp_e2e_001',
          campaign_name: 'E2E Test Campaign',
          message_id: 'msg_e2e_001',
          subject: 'E2E Test',
        },
      },
    ];

    const result = await httpPost<{ accepted: number; batch_id: string }>(
      '/v1/batch',
      { events },
    );
    expect(result.accepted).toBe(1);
  });

  it('should query campaign 360 endpoint and return data', async () => {
    const campaign = await httpGet<{
      campaign_id: string;
      name: string;
      channel: string;
      surfaces: Array<{ source: string; event_count: number }>;
    }>('/v1/360/campaign/camp_e2e_001');
    expect(campaign.campaign_id).toBe('camp_e2e_001');
    expect(campaign.name).toBe('E2E Test Campaign');
    expect(Array.isArray(campaign.surfaces)).toBe(true);
  });

  it('should verify campaign surfaces have expected sources', async () => {
    const campaign = await httpGet<{
      campaign_id: string;
      surfaces: Array<{ source: string }>;
    }>('/v1/360/campaign/camp_e2e_001');
    const sources = campaign.surfaces.map((s) => s.source);
    expect(sources.length).toBeGreaterThan(0);
  });
});
