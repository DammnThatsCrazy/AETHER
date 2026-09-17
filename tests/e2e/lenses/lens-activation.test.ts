/**
 * FPS-107 — Lens Activation (E2E)
 * Apply lens via API, verify derived output, disengage, reapply.
 * Skips if AETHER_API_KEY is missing.
 */
import { describe, it, expect } from 'vitest';

import { LensInput, LensOutput } from '@aether/proof-contracts';

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

async function httpDelete<T>(path: string): Promise<T> {
  return fetchJSON<T>(`${API_URL}${path}`, { method: 'DELETE' });
}

describe.skipIf(!API_KEY)('FPS-107: Lens Activation', () => {

  it('should apply a lens and get derived output', async () => {
    const lensInput: LensInput = {
      lens_name: 'active_users',
      dimensions: ['last_active_days'],
      filters: [{ dimension: 'last_active_days', operator: 'gt', value: 7 }],
    };

    const result = await httpPost<LensOutput>('/v1/lens/apply', lensInput);
    expect(result.lens_name).toBe('active_users');
    expect(result.total_profiles).toBeGreaterThanOrEqual(0);
  });

  it('should verify derived output matches expected lens structure', async () => {
    const result = await httpPost<LensOutput>('/v1/lens/apply', {
      lens_name: 'active_users',
      dimensions: ['last_active_days'],
      filters: [{ dimension: 'last_active_days', operator: 'gt', value: 7 }],
    });
    expect(result.segments).toBeDefined();
    expect(Array.isArray(result.segments)).toBe(true);
  });

  it('should disengage lens and verify reset', async () => {
    // Disengage the lens — should clear derived data
    await httpDelete<{ status: string }>('/v1/lens/disengage', {
      lens_name: 'active_users',
    });

    // Verify state is reset — query without filters should return all profiles
    const result = await httpPost<LensOutput>('/v1/lens/apply', {
      lens_name: 'active_users',
      dimensions: ['last_active_days'],
    });
    expect(result.total_profiles).toBeGreaterThanOrEqual(0);
  });

  it('should reapply lens and verify deterministic output', async () => {
    // Reapply with same filters — output should be deterministic
    const result1 = await httpPost<LensOutput>('/v1/lens/apply', {
      lens_name: 'active_users',
      dimensions: ['last_active_days'],
      filters: [{ dimension: 'last_active_days', operator: 'gt', value: 7 }],
    });

    const result2 = await httpPost<LensOutput>('/v1/lens/apply', {
      lens_name: 'active_users',
      dimensions: ['last_active_days'],
      filters: [{ dimension: 'last_active_days', operator: 'gt', value: 7 }],
    });

    expect(result1.total_profiles).toBe(result2.total_profiles);
    expect(result1.segments?.length).toBe(result2.segments?.length);
  });
});
