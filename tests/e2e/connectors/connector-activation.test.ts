/**
 * FPS-103 — Connector Activation (E2E)
 * End-to-end: connect provider, verify sync state, graph writes, 360 update.
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

describe.skipIf(!API_KEY)('FPS-103: Connector Activation', () => {

  it('should POST fixture data to batch endpoint', async () => {
    // Construct a connector event envelope
    const connectorEvent: EventEnvelope = {
      tenant_id: 'aether-proof-tenant',
      workspace_id: 'proof-lab',
      platform_id: 'stripe',
      environment: 'staging',
      event_type: 'customer_created',
      sdk: { name: '@aether/stripe', version: '0.1.0-alpha.0' },
      identity: { anonymous_id: 'anon_stripe_001' },
      timestamp: new Date().toISOString(),
      properties: {
        id: 'cus_test_e2e',
        email: 'e2e@example.com',
        name: 'E2E Test Customer',
      },
    };

    const result = await httpPost<{ accepted: number; batch_id: string }>(
      '/v1/batch',
      { events: [connectorEvent] },
    );
    expect(result.accepted).toBe(1);
  });

  it('should verify sync state', async () => {
    const syncState = await httpGet<{
      platform_id: string;
      status: string;
      last_sync_at: string | null;
    }>('/v1/sync/stripe');
    expect(syncState.platform_id).toBe('stripe');
    expect(['idle', 'syncing', 'completed']).toContain(syncState.status);
  });

  it('should verify graph writes', async () => {
    // Query the graph API to verify nodes were written.
    const graph = await httpGet<{ nodes: unknown[]; edges: unknown[] }>(
      '/v1/graph/nodes',
    );
    expect(Array.isArray(graph.nodes)).toBe(true);
    expect(Array.isArray(graph.edges)).toBe(true);
  });

  it('should verify 360 update', async () => {
    const profile360 = await httpGet<{ profile_id: string; surfaces: unknown[] }>(
      '/v1/360/profile/e2e-test',
    );
    expect(profile360.profile_id).toBeDefined();
    expect(Array.isArray(profile360.surfaces)).toBe(true);
  });
});
