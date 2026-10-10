import { afterEach, describe, expect, expectTypeOf, it, vi } from 'vitest';
import {
  defaultModelRuntimeAdminApi,
  type EntitlementsResponse,
  type HealthResponse,
  type ModelRuntimeAdminApi,
  type RegistryResponse,
  type TracesResponse,
  type UsageResponse,
} from '../../features/model-runtime/types';
import * as modelRuntime from '../../features/model-runtime/index';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('model-runtime admin types (ADR-008 D8/D9)', () => {
  it('defaultModelRuntimeAdminApi exposes all five admin methods', () => {
    const methods = [
      'fetchRegistry',
      'fetchHealth',
      'fetchEntitlements',
      'fetchUsage',
      'fetchTraces',
    ] as const;
    for (const method of methods) {
      expect(typeof defaultModelRuntimeAdminApi[method]).toBe('function');
    }
    expectTypeOf(defaultModelRuntimeAdminApi).toEqualTypeOf<ModelRuntimeAdminApi>();
  });

  it('index barrel exports the five page components, types, and default api', () => {
    for (const page of [
      'ModelRegistryPage',
      'ModelRuntimeHealthPage',
      'EntitlementsPage',
      'UsagePage',
      'TracesPage',
    ] as const) {
      expect(modelRuntime[page]).toBeDefined();
    }
    expect(modelRuntime.defaultModelRuntimeAdminApi).toBe(defaultModelRuntimeAdminApi);

    // Types are erased at runtime; pin them at the type level through the barrel.
    // A namespace member reference in type position resolves the type-only
    // re-exports (the value namespace has no trace of them); if the barrel ever
    // drops a name, the reference below is a compile error.
    expectTypeOf<modelRuntime.RegistryResponse>().toEqualTypeOf<RegistryResponse>();
    expectTypeOf<modelRuntime.HealthResponse>().toEqualTypeOf<HealthResponse>();
    expectTypeOf<modelRuntime.EntitlementsResponse>().toEqualTypeOf<EntitlementsResponse>();
    expectTypeOf<modelRuntime.UsageResponse>().toEqualTypeOf<UsageResponse>();
    expectTypeOf<modelRuntime.TracesResponse>().toEqualTypeOf<TracesResponse>();
    expectTypeOf<RegistryResponse>().toEqualTypeOf<RegistryResponse>();
    expectTypeOf<HealthResponse>().toEqualTypeOf<HealthResponse>();
    expectTypeOf<EntitlementsResponse>().toEqualTypeOf<EntitlementsResponse>();
    expectTypeOf<UsageResponse>().toEqualTypeOf<UsageResponse>();
    expectTypeOf<TracesResponse>().toEqualTypeOf<TracesResponse>();
  });

  it('fetchRegistry parses a resolved Response', async () => {
    const payload: RegistryResponse = {
      models: [
        {
          modelId: 'claude-sonnet-5',
          provider: 'anthropic',
          status: 'recommended',
          capabilities: ['tool_use', 'structured_outputs'],
          inputCostPerMTok: 3,
          outputCostPerMTok: 15,
        },
      ],
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(payload), { status: 200 })),
    );

    await expect(defaultModelRuntimeAdminApi.fetchRegistry()).resolves.toEqual(payload);
  });

  it('fetchRegistry rejects with { status: 403 } on a 403', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('Forbidden', { status: 403, statusText: 'Forbidden' })),
    );

    await expect(defaultModelRuntimeAdminApi.fetchRegistry()).rejects.toMatchObject({
      status: 403,
    });
  });

  it('carries the HttpOnly session cookie (credentials: include) on all five admin calls', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{}', { status: 200 })),
    );

    await defaultModelRuntimeAdminApi.fetchRegistry();
    await defaultModelRuntimeAdminApi.fetchHealth();
    await defaultModelRuntimeAdminApi.fetchEntitlements();
    await defaultModelRuntimeAdminApi.fetchUsage();
    await defaultModelRuntimeAdminApi.fetchTraces();

    const calls = vi.mocked(fetch).mock.calls;
    expect(calls).toHaveLength(5);
    for (const [url, init] of calls) {
      expect(String(url)).toMatch(/\/v1\/model-runtime\/(registry|health|entitlements|usage|traces)$/);
      expect(init).toEqual(expect.objectContaining({ credentials: 'include' }));
    }
  });
});
