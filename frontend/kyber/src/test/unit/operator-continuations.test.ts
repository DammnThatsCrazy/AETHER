/**
 * KYBER operator continuation hooks — M5d real, flag-gated hooks.
 *
 * Proves the two halves of the flag contract (D8):
 *   · flag OFF — the list hook is disabled (no HTTP request can fire) and the
 *     create/handoff mutationFns resolve `{ skipped: true }` without touching the
 *     API — no dead surface, no traffic.
 *   · flag ON  — the list fetcher hits GET /v1/kyber/continuations/recent and the
 *     create/handoff mutationFns POST snake_case (D6) payloads to the operator
 *     continuation router.
 *
 * The hooks use React's `useCallback`, so each is exercised through `renderHook`
 * (a real render context) rather than as a bare function call.
 */
import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  isFeatureEnabled: vi.fn(),
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  recent: vi.fn(),
  create: vi.fn(),
  handoff: vi.fn(),
  get: vi.fn(),
  remove: vi.fn(),
}));

vi.mock('@kyber/lib/api/endpoints', () => ({
  api: {
    continuations: {
      recent: mocks.recent,
      list: vi.fn(),
      get: mocks.get,
      create: mocks.create,
      handoff: mocks.handoff,
      remove: mocks.remove,
    },
  },
}));

vi.mock('@kyber/lib/featureFlags', () => ({
  featureFlags: {},
  isFeatureEnabled: mocks.isFeatureEnabled,
}));

vi.mock('@aether/ui', () => ({
  useQuery: mocks.useQuery,
  useMutation: mocks.useMutation,
}));

function setFlag(value: boolean): void {
  mocks.isFeatureEnabled.mockReturnValue(value);
}

function stubUseQuery(continuations: unknown[] | null): void {
  mocks.useQuery.mockReturnValue({
    data: continuations === null ? null : { continuations },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
}

function stubUseMutation(): void {
  mocks.useMutation.mockReturnValue({
    mutate: vi.fn().mockResolvedValue(null),
    isLoading: false,
    error: null,
    data: null,
    reset: vi.fn(),
  });
}

describe('useOperatorContinuations', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubUseQuery([]);
    stubUseMutation();
  });

  it('is disabled (no request can fire) while the flag is off', async () => {
    setFlag(false);
    const { useOperatorContinuations } = await import(
      '@kyber/features/continuation/use-continuations'
    );
    const { result } = renderHook(() => useOperatorContinuations());
    const call = mocks.useQuery.mock.calls[0][0];
    expect(call.enabled).toBe(false);
    // Flag off ⇒ the empty list, never loading and never errored.
    expect(result.current.data).toEqual([]);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(mocks.recent).not.toHaveBeenCalled();
  });

  it('is enabled and returns the feed while the flag is on', async () => {
    setFlag(true);
    stubUseQuery([
      {
        id: 'cont_op_1',
        source_client: 'kyber-desktop',
        surface: 'investigations',
        summary: { title: 'whale outflow' },
        state_revision: 1,
        updated_at: '2026-08-07T00:00:00Z',
      },
    ]);
    const { useOperatorContinuations } = await import(
      '@kyber/features/continuation/use-continuations'
    );
    const { result } = renderHook(() => useOperatorContinuations());
    const call = mocks.useQuery.mock.calls[0][0];
    expect(call.enabled).toBe(true);
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data[0]?.summary.title).toBe('whale outflow');
  });

  it('fetches GET /v1/kyber/continuations/recent via the fetcher', async () => {
    setFlag(true);
    mocks.recent.mockResolvedValue({ continuations: [] });
    const { useOperatorContinuations } = await import(
      '@kyber/features/continuation/use-continuations'
    );
    renderHook(() => useOperatorContinuations());
    const call = mocks.useQuery.mock.calls[0][0];
    await call.fetcher();
    expect(mocks.recent).toHaveBeenCalledTimes(1);
  });
});

describe('useCreateOperatorContinuation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubUseQuery([]);
    stubUseMutation();
  });

  it('resolves { skipped: true } and fires no request while the flag is off', async () => {
    setFlag(false);
    const { useCreateOperatorContinuation } = await import(
      '@kyber/features/continuation/use-continuations'
    );
    renderHook(() => useCreateOperatorContinuation());
    const call = mocks.useMutation.mock.calls[0][0];
    const result = await call.mutationFn({
      source_command_id: 'cmd-1',
      objective: 'resume the investigation',
    });
    expect(result).toEqual({ skipped: true });
    expect(mocks.create).not.toHaveBeenCalled();
  });

  it('POSTs snake_case payload to /v1/kyber/continuations while the flag is on', async () => {
    setFlag(true);
    mocks.create.mockResolvedValue({
      id: 'cont_op_new',
      principal_id: 'op_1',
      source_client: 'kyber-desktop',
      surface: 'commands',
      summary: { title: 'resume the investigation' },
      state_revision: 0,
      updated_at: '2026-08-07T00:00:00Z',
    });
    const { useCreateOperatorContinuation } = await import(
      '@kyber/features/continuation/use-continuations'
    );
    renderHook(() => useCreateOperatorContinuation());
    const call = mocks.useMutation.mock.calls[0][0];
    const result = await call.mutationFn({
      source_command_id: 'cmd-1',
      objective: 'resume the investigation',
      title: 'Investigate the whale outflow',
    });
    expect(result.skipped).toBe(false);
    expect(mocks.create).toHaveBeenCalledWith({
      source_command_id: 'cmd-1',
      objective: 'resume the investigation',
      title: 'Investigate the whale outflow',
    });
  });
});

describe('useHandoffOperatorContinuation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    stubUseQuery([]);
    stubUseMutation();
  });

  it('resolves { skipped: true } and fires no request while the flag is off', async () => {
    setFlag(false);
    const { useHandoffOperatorContinuation } = await import(
      '@kyber/features/continuation/use-continuations'
    );
    renderHook(() => useHandoffOperatorContinuation());
    const call = mocks.useMutation.mock.calls[0][0];
    const result = await call.mutationFn({ continuation_id: 'cont_op_1' });
    expect(result).toEqual({ skipped: true });
    expect(mocks.handoff).not.toHaveBeenCalled();
  });

  it('POSTs /v1/kyber/continuations/{id}/handoff while the flag is on', async () => {
    setFlag(true);
    mocks.handoff.mockResolvedValue({
      token: 'dlt_abc',
      tenant_scope: 'aether',
      principal_id: 'op_1',
      created_at: '2026-08-07T00:00:00Z',
    });
    const { useHandoffOperatorContinuation } = await import(
      '@kyber/features/continuation/use-continuations'
    );
    renderHook(() => useHandoffOperatorContinuation());
    const call = mocks.useMutation.mock.calls[0][0];
    const result = await call.mutationFn({
      continuation_id: 'cont_op_1',
      reason: 'resume on phone',
    });
    expect(result.skipped).toBe(false);
    expect(mocks.handoff).toHaveBeenCalledWith('cont_op_1', { reason: 'resume on phone' });
  });
});
