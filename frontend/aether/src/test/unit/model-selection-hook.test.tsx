import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type {
  ModelRegistryModel,
  TenantModelSelectionApi,
} from '@aether-app/features/model-selection/types';
import { useModelSelection } from '@aether-app/features/model-selection/useModelSelection';

const MODELS: ModelRegistryModel[] = [
  {
    modelId: 'anthropic/claude-sonnet-4',
    provider: 'anthropic',
    status: 'recommended',
    capabilities: ['text'],
    inputCostPerMTok: 3,
    outputCostPerMTok: 15,
  },
  {
    modelId: 'openai/gpt-4o',
    provider: 'openai',
    status: 'stable',
    capabilities: ['text', 'image'],
    inputCostPerMTok: 2.5,
    outputCostPerMTok: 10,
  },
];

const DEFAULT_MODEL = 'anthropic/claude-sonnet-4';

function createApi(overrides: Partial<TenantModelSelectionApi> = {}): TenantModelSelectionApi {
  return {
    getModels: vi.fn().mockResolvedValue({ models: MODELS, tenantDefaultModel: DEFAULT_MODEL }),
    setTenantDefault: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

/** An error shaped like the typed REST client error with an HTTP status. */
function httpError(status: number): Error {
  return Object.assign(new Error(`request failed with ${status}`), { status });
}

/** C13-F's defaultModelSelectionApi throws a plain `{ status, message }`. */
function serverError(status: number): { status: number; message: string } {
  return { status, message: `Failed to load models (HTTP ${status})` };
}

describe('useModelSelection (tenant-scoped model selection)', () => {
  it('loads the model registry and tenant default on mount', async () => {
    const api = createApi();
    const { result } = renderHook(() => useModelSelection(api));

    expect(result.current.loading).toBe(true);

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(api.getModels).toHaveBeenCalledTimes(1);
    expect(result.current.models).toEqual(MODELS);
    expect(result.current.tenantDefaultModel).toBe(DEFAULT_MODEL);
    expect(result.current.entitled).toBe(true);
    expect(result.current.error).toBeNull();
  }, 15_000);

  it('setDefault updates the tenant default optimistically and calls the api', async () => {
    const api = createApi();
    const { result } = renderHook(() => useModelSelection(api));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.setDefault('openai/gpt-4o');
    });

    expect(api.setTenantDefault).toHaveBeenCalledWith('openai/gpt-4o');
    expect(result.current.tenantDefaultModel).toBe('openai/gpt-4o');
    expect(result.current.error).toBeNull();
    expect(result.current.entitled).toBe(true);
  }, 15_000);

  it('setDefault rolls back and surfaces the error when the write fails', async () => {
    const api = createApi({
      setTenantDefault: vi.fn().mockRejectedValue(httpError(500)),
    });
    const { result } = renderHook(() => useModelSelection(api));
    await waitFor(() => expect(result.current.loading).toBe(false));

    // setDefault swallows the failure — it rolls back and surfaces via state.
    await act(async () => {
      await result.current.setDefault('openai/gpt-4o');
    });

    expect(api.setTenantDefault).toHaveBeenCalledWith('openai/gpt-4o');
    expect(result.current.tenantDefaultModel).toBe(DEFAULT_MODEL); // rolled back
    expect(result.current.error).not.toBeNull();
    expect(result.current.error?.message).toBe('request failed with 500');
    expect(result.current.entitled).toBe(true); // failure, not an entitlement boundary
  }, 15_000);

  it('treats a 403 on load as "not entitled" rather than a load failure', async () => {
    const api = createApi({
      getModels: vi.fn().mockRejectedValue(httpError(403)),
    });
    const { result } = renderHook(() => useModelSelection(api));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.entitled).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.models).toEqual([]);
  }, 15_000);

  it('treats a 403 on setDefault as an entitlement boundary and rolls back', async () => {
    const api = createApi({
      setTenantDefault: vi.fn().mockRejectedValue(httpError(403)),
    });
    const { result } = renderHook(() => useModelSelection(api));
    await waitFor(() => expect(result.current.loading).toBe(false));

    // setDefault swallows the failure — it rolls back and flips entitlement.
    await act(async () => {
      await result.current.setDefault('openai/gpt-4o');
    });

    expect(result.current.tenantDefaultModel).toBe(DEFAULT_MODEL); // rolled back
    expect(result.current.entitled).toBe(false);
    expect(result.current.error).toBeNull();
  }, 15_000);

  it('surfaces an arbitrary (non-403) load failure while staying entitled', async () => {
    const api = createApi({
      getModels: vi.fn().mockRejectedValue(new Error('registry unreachable')),
    });
    const { result } = renderHook(() => useModelSelection(api));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.entitled).toBe(true);
    expect(result.current.error?.message).toBe('registry unreachable');
    expect(result.current.models).toEqual([]);
  }, 15_000);

  it('detects a 403 from the default client plain-error shape', async () => {
    const api = createApi({
      getModels: vi.fn().mockRejectedValue(serverError(403)),
    });
    const { result } = renderHook(() => useModelSelection(api));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.entitled).toBe(false);
    expect(result.current.error).toBeNull();
  }, 15_000);

  it('surfaces a non-403 message from the default client plain-error shape', async () => {
    const api = createApi({
      setTenantDefault: vi.fn().mockRejectedValue(serverError(500)),
    });
    const { result } = renderHook(() => useModelSelection(api));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.setDefault('openai/gpt-4o');
    });

    expect(result.current.tenantDefaultModel).toBe(DEFAULT_MODEL); // rolled back
    expect(result.current.error?.message).toBe('Failed to load models (HTTP 500)');
    expect(result.current.entitled).toBe(true);
  }, 15_000);

  it('drives the loading flag through the mount lifecycle', async () => {
    let resolveLoad!: (value: { models: ModelRegistryModel[]; tenantDefaultModel: string | null }) => void;
    const pending = new Promise<{ models: ModelRegistryModel[]; tenantDefaultModel: string | null }>(
      resolve => {
        resolveLoad = resolve;
      },
    );
    const api = createApi({ getModels: vi.fn().mockReturnValue(pending) });

    const { result } = renderHook(() => useModelSelection(api));
    expect(result.current.loading).toBe(true);

    await act(async () => {
      resolveLoad({ models: MODELS, tenantDefaultModel: DEFAULT_MODEL });
      await pending;
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.models).toEqual(MODELS);
    expect(result.current.tenantDefaultModel).toBe(DEFAULT_MODEL);
  }, 15_000);
});
