/**
 * FPS-101 — Tenant Activation (E2E)
 * End-to-end test: create tenant, register platform, generate SDK keys.
 * Skips if AETHER_API_URL/AETHER_API_KEY env vars are missing. Tenant creation
 * is a platform-operator action: it runs only with AETHER_OPERATOR_API_KEY, a key
 * for a tenant listed in PLATFORM_OPERATOR_TENANT_IDS.
 */
import { describe, it, expect } from 'vitest';

const API_URL = process.env.AETHER_API_URL || 'http://localhost:8000';
const API_KEY = process.env.AETHER_API_KEY;
const OPERATOR_API_KEY = process.env.AETHER_OPERATOR_API_KEY;

function headers(apiKey: string | undefined = API_KEY): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    'X-Aether-API-Key': apiKey!,
  };
}

function fetchJSON<T>(input: RequestInfo, init?: RequestInit, apiKey?: string): Promise<T> {
  return fetch(input, {
    ...init,
    headers: { ...headers(apiKey), ...init?.headers },
  }).then((res) => {
    if (res.status === 401 || res.status === 403) {
      throw new Error(`Auth failed: ${res.status} ${res.statusText}`);
    }
    if (res.status === 429) {
      throw new Error('Rate limited — 429');
    }
    if (res.status >= 500) {
      throw new Error(`Server error: ${res.status} ${res.statusText}`);
    }
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }
    return res.json() as Promise<T>;
  });
}

async function httpPost<T>(path: string, body: unknown, apiKey?: string): Promise<T> {
  return fetchJSON<T>(`${API_URL}${path}`, {
    method: 'POST',
    body: JSON.stringify(body),
  }, apiKey);
}

async function httpGet<T>(path: string, apiKey?: string): Promise<T> {
  return fetchJSON<T>(`${API_URL}${path}`, { method: 'GET' }, apiKey);
}

describe.skipIf(!API_KEY)('FPS-101: Tenant Activation', () => {

  it.skipIf(!OPERATOR_API_KEY)('should create a tenant as a platform operator', async () => {
    const body = {
      name: `e2e-test-${Date.now()}`,
      workspace: 'proof-e2e',
      platform: 'web',
    };
    const tenant = await httpPost<{ id: string; name: string; status: string }>(
      '/v1/admin/tenants',
      body,
      OPERATOR_API_KEY,
    );
    expect(tenant.id).toBeDefined();
    expect(tenant.name).toBe(body.name);
    expect(tenant.status).toBe('active');

    // GET the tenant to verify persistence
    const getTenant = await httpGet<{ id: string; name: string; status: string }>(
      `/v1/admin/tenants/${tenant.id}`,
      OPERATOR_API_KEY,
    );
    expect(getTenant.id).toBe(tenant.id);
    expect(getTenant.name).toBe(body.name);
  });

  it('should register SDK selection for platforms', async () => {
    const platforms = ['web', 'ios', 'android'];
    const result = await httpPost<{ selected: string[]; status: string }>(
      '/v1/activation/sdk-selection',
      { platforms },
    );
    expect(result.selected).toEqual(platforms);
    expect(result.status).toBe('configured');
  });

  it('should generate SDK keys', async () => {
    const result = await httpPost<{
      keys: Array<{ id: string; key: string; label: string }>;
      total: number;
    }>('/v1/activation/create-sdk-keys', {
      count: 2,
      label: 'e2e-test-keys',
    });
    expect(result.keys).toHaveLength(2);
    expect(result.total).toBe(2);
    for (const key of result.keys) {
      expect(key.id).toBeDefined();
      expect(key.key).toBeTruthy();
      expect(key.label).toBe('e2e-test-keys');
    }
  });

  it('should verify platform status', async () => {
    // Verify the platform endpoint returns the expected status.
    const status = await httpGet<{ platform: string; status: string }>(
      '/v1/activation/platform-status',
    );
    expect(status.platform).toBeDefined();
    expect(['active', 'configured', 'pending']).toContain(status.status);
  });
});
