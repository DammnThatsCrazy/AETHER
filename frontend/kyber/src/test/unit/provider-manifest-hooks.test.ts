/**
 * KYBER provider-connections — hooks over the manifest contract.
 *
 * Exercises the real hooks through mocked @aether/ui query primitives and a
 * mocked endpoints module. Proves:
 *   · useProviderCatalog surfaces manifest data from useQuery and delegates
 *     refresh to refetch.
 *   · useProviderConnections stays DISABLED (no fetch can fire) until a tenant
 *     id is named — routing to the page is not a grant.
 *   · useCertifyProvider POSTs the identity key to the certify endpoint, parses
 *     the report through the zod schema, and invalidates the catalog + overview
 *     caches.
 */
import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  providers: vi.fn(),
  overview: vi.fn(),
  health: vi.fn(),
  tenant: vi.fn(),
  certify: vi.fn(),
}));

vi.mock('@aether/ui', () => ({
  useQuery: mocks.useQuery,
  useMutation: mocks.useMutation,
}));

vi.mock('@kyber/lib/api/endpoints', () => ({
  api: {
    admin: {
      kyber: {
        providerConnections: {
          providers: mocks.providers,
          overview: mocks.overview,
          health: mocks.health,
          tenant: mocks.tenant,
          certify: mocks.certify,
        },
      },
    },
  },
}));

import {
  useCertifyProvider,
  useProviderCatalog,
  useProviderConnections,
} from '@kyber/features/provider-connections';

const VALID_ENTRY = {
  identity: 'payments.stripe.payouts',
  display_name: 'Stripe Payouts',
  category: 'payments',
  readiness: { level: 4, state: 'sandbox_validated' },
  availability: {
    environments: { local: true, integration: true, staging: false, production: false },
  },
  authentication: { type: 'oauth2' },
  capabilities: { auth: true, account: true, pull: true, webhook: false, report: false, stream: false, reconciliation: false },
  certification_state: 'certified',
};

function stubUseQuery(overrides: Partial<ReturnType<typeof mocks.useQuery>> = {}): void {
  mocks.useQuery.mockReturnValue({
    data: { providers: [VALID_ENTRY], issues: [] },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  });
}

describe('useProviderCatalog', () => {
  beforeEach(() => stubUseQuery());

  it('surfaces the manifest catalog from useQuery', () => {
    const { result } = renderHook(() => useProviderCatalog());
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.data).toEqual({ providers: [VALID_ENTRY], issues: [] });
  });

  it('delegates refresh to the underlying refetch', () => {
    const refetch = vi.fn();
    stubUseQuery({ refetch });
    const { result } = renderHook(() => useProviderCatalog());
    result.current.refresh();
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});

describe('useProviderConnections', () => {
  beforeEach(() => stubUseQuery());

  it('passes enabled:false until a tenant id is named', () => {
    renderHook(() => useProviderConnections(null));
    const lastCall = mocks.useQuery.mock.calls.at(-1)?.[0] as { enabled?: boolean };
    expect(lastCall.enabled).toBe(false);
  });

  it('enables the fetch when a tenant id is present', () => {
    renderHook(() => useProviderConnections('tenant-1'));
    const lastCall = mocks.useQuery.mock.calls.at(-1)?.[0] as { enabled?: boolean };
    expect(lastCall.enabled).toBe(true);
  });
});

describe('useCertifyProvider', () => {
  beforeEach(() => {
    // FAITHFUL to production @aether/ui useMutation: it swallows errors, sets
    // the error state, and resolves null — it never rejects. The mock invokes
    // the real mutationFn so the endpoint call and zod report parse are both
    // exercised end-to-end, then mirrors production's catch behavior. The
    // getters keep error/data live so the hook's delegated state reflects the
    // current outcome.
    mocks.useMutation.mockImplementation(
      (options: { mutationFn: (input: string) => Promise<unknown> }) => {
        let error: string | null = null;
        let data: unknown = null;
        const mutate = vi.fn(async (input: string) => {
          error = null;
          try {
            data = await options.mutationFn(input);
            return data;
          } catch (err) {
            error = err instanceof Error ? err.message : 'Mutation failed';
            return null;
          }
        });
        return {
          mutate,
          isLoading: false,
          get error() {
            return error;
          },
          get data() {
            return data;
          },
          reset: vi.fn(() => {
            error = null;
            data = null;
          }),
        };
      },
    );
  });

  it('calls the certify endpoint with the identity key and invalidates caches', async () => {
    mocks.certify.mockResolvedValue({
      identity: 'payments.stripe.payouts',
      passed: true,
      checks: [{ name: 'manifest_honest', passed: true }],
      generated_at: '2026-08-08T00:00:00Z',
    });
    const { result } = renderHook(() => useCertifyProvider());

    const report = await result.current.certify('payments.stripe.payouts');

    expect(mocks.certify).toHaveBeenCalledWith('payments.stripe.payouts');
    expect(report).not.toBeNull();
    expect(report?.passed).toBe(true);
    expect(report?.checks).toHaveLength(1);

    const options = mocks.useMutation.mock.calls[0]?.[0] as { invalidateKeys?: readonly string[] };
    expect(options.invalidateKeys).toEqual([
      'kyber-provider-connections:catalog',
      'kyber-provider-connections:overview',
    ]);
  });

  it('surfaces a malformed certify report as error state, not a rejection', async () => {
    // Production useMutation swallows the mutationFn error: it sets error state
    // and resolves null. A test asserting a rejection would pin behavior the
    // production hook cannot exhibit. Assert the real contract instead.
    mocks.certify.mockResolvedValue({ identity: 'x' });
    const { result } = renderHook(() => useCertifyProvider());

    const report = await result.current.certify('x');

    expect(report).toBeNull();
    const mutationResult = mocks.useMutation.mock.results.at(-1)?.value as {
      error: string | null;
      data: unknown;
    };
    expect(mutationResult.data).toBeNull();
    expect(mutationResult.error).not.toBeNull();
    // The zod message is surfaced verbatim as the error string — here the
    // malformed report is missing the required ``passed`` boolean.
    expect(mutationResult.error).toContain('passed');
  });
});
