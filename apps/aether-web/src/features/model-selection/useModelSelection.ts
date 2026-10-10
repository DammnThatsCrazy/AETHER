import { useCallback, useEffect, useState } from 'react';
import type {
  ModelRegistryModel,
  TenantModelSelectionApi,
} from './types';
import { defaultModelSelectionApi } from './types';

export interface UseModelSelectionResult {
  models: ModelRegistryModel[];
  tenantDefaultModel: string | null;
  loading: boolean;
  error: Error | null;
  entitled: boolean;
  setDefault: (modelId: string) => Promise<void>;
}

/**
 * Tenant-scoped model selection.
 *
 * Server-authoritative: reads the model registry and the tenant default on
 * mount, and writes the tenant default through `setDefault`. This hook never
 * handles credentials or auth headers directly — all transport is owned by the
 * injected `TenantModelSelectionApi`, so the caller stays typed-only.
 *
 * Entitlement semantics (ADR-008 D4): a 403 (from either call) means the
 * tenant is NOT entitled to model selection. That is a distinct server-
 * authoritative state, not a load failure — `entitled` flips to false and no
 * `error` is surfaced. Any other failure surfaces `error` while leaving the
 * tenant entitled.
 */
export function useModelSelection(
  api: TenantModelSelectionApi = defaultModelSelectionApi,
): UseModelSelectionResult {
  const [models, setModels] = useState<ModelRegistryModel[]>([]);
  const [tenantDefaultModel, setTenantDefaultModel] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [entitled, setEntitled] = useState(true);

  useEffect(() => {
    let active = true;

    async function load(): Promise<void> {
      setLoading(true);
      try {
        const result = await api.getModels();
        if (!active) return;
        setModels(result.models);
        setTenantDefaultModel(result.tenantDefaultModel);
        setEntitled(true);
        setError(null);
      } catch (err) {
        if (!active) return;
        if (statusOf(err) === 403) {
          // Not entitled — server-authoritative boundary, not a load failure.
          setEntitled(false);
          setError(null);
        } else {
          setError(toError(err));
        }
      } finally {
        if (active) setLoading(false);
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, [api]);

  const setDefault = useCallback(
    async (modelId: string): Promise<void> => {
      const previous = tenantDefaultModel;
      setError(null);
      // Optimistic update; rolled back if the write fails.
      setTenantDefaultModel(modelId);
      try {
        await api.setTenantDefault(modelId);
      } catch (err) {
        setTenantDefaultModel(previous);
        if (statusOf(err) === 403) {
          setEntitled(false);
        } else {
          setError(toError(err));
        }
      }
    },
    [api, tenantDefaultModel],
  );

  return { models, tenantDefaultModel, loading, error, entitled, setDefault };
}

/** Reads a numeric HTTP status off a thrown error (e.g. RestClientError). */
function statusOf(err: unknown): number | null {
  if (typeof err === 'object' && err !== null && 'status' in err) {
    const status = (err as { status?: unknown }).status;
    if (typeof status === 'number') return status;
  }
  return null;
}

function toError(err: unknown): Error {
  if (err instanceof Error) return err;
  if (typeof err === 'object' && err !== null && 'message' in err) {
    const message = (err as { message?: unknown }).message;
    if (typeof message === 'string' && message.length > 0) return new Error(message);
  }
  return new Error(String(err));
}
