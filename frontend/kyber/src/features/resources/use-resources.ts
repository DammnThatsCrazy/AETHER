import { useCallback, useEffect, useState } from 'react';
import { resourcesApi } from '@kyber/lib/api/resources';
import type { ProtectedResource, ResourceClass } from '@kyber/lib/schemas/commerce';

export interface UseResourcesResult {
  readonly resources: readonly ProtectedResource[];
  readonly loading: boolean;
  readonly error: string | null;
  refresh(): Promise<void>;
  get(resourceId: string): Promise<ProtectedResource>;
  register(body: {
    name: string;
    resource_class: ResourceClass;
    path_pattern: string;
    owner_service: string;
    description?: string;
    price_usd: number;
    accepted_assets: string[];
    accepted_chains: string[];
    approval_required?: boolean;
    entitlement_ttl_seconds?: number;
  }): Promise<ProtectedResource>;
  update(resourceId: string, body: Partial<{ price_usd: number; active: boolean; approval_required: boolean; entitlement_ttl_seconds: number }>): Promise<ProtectedResource>;
}

export function useResources(): UseResourcesResult {
  const [resources, setResources] = useState<ProtectedResource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const items = await resourcesApi.list();
      setResources(items);
    } catch (e) {
      setResources([]);
      setError(e instanceof Error ? e.message : 'failed to load resources');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const get = useCallback(
    async (resourceId: string): Promise<ProtectedResource> => resourcesApi.get(resourceId),
    []
  );

  const register = useCallback(
    async (body: {
      name: string;
      resource_class: ResourceClass;
      path_pattern: string;
      owner_service: string;
      description?: string;
      price_usd: number;
      accepted_assets: string[];
      accepted_chains: string[];
      approval_required?: boolean;
      entitlement_ttl_seconds?: number;
    }) => {
      setError(null);
      try {
        const result = await resourcesApi.register(body);
        await refresh();
        return result;
      } catch (e) {
        setError(e instanceof Error ? e.message : 'failed to register resource');
        throw e;
      }
    },
    [refresh]
  );

  const update = useCallback(
    async (resourceId: string, body: Partial<{ price_usd: number; active: boolean; approval_required: boolean; entitlement_ttl_seconds: number }>) => {
      setError(null);
      try {
        const result = await resourcesApi.update(resourceId, body);
        await refresh();
        return result;
      } catch (e) {
        setError(e instanceof Error ? e.message : 'failed to update resource');
        throw e;
      }
    },
    [refresh]
  );

  return { resources, loading, error, refresh, get, register, update };
}
