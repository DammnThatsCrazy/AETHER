import { useCallback, useEffect, useState } from 'react';
import { isLocalMocked } from '@kyber/lib/env';
import { resourcesApi } from '@kyber/lib/api/resources';
import type { ProtectedResource, ResourceClass } from '@kyber/lib/schemas/commerce';
import { fixtureResourceList } from '@kyber/fixtures/resources';

export interface UseResourcesResult {
  readonly resources: readonly ProtectedResource[];
  readonly loading: boolean;
  readonly error: string | null;
  readonly mode: 'mocked' | 'live';
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
  const mode: 'mocked' | 'live' = isLocalMocked() ? 'mocked' : 'live';

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (mode === 'mocked') {
        setResources([...fixtureResourceList]);
      } else {
        const items = await resourcesApi.list();
        setResources(items);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed to load resources');
    } finally {
      setLoading(false);
    }
  }, [mode]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const get = useCallback(
    async (resourceId: string): Promise<ProtectedResource> => {
      if (mode === 'mocked') {
        return fixtureResourceList.find((r) => r.resource_id === resourceId) ?? fixtureResourceList[0]!;
      }
      return resourcesApi.get(resourceId);
    },
    [mode]
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
      if (mode === 'mocked') {
        const base = fixtureResourceList[0]!;
        const next: ProtectedResource = {
          ...base,
          resource_id: `res_fx_new_${Date.now()}`,
          tenant_id: 'tenant_kyber_mock',
          approval_required: true,
          entitlement_ttl_seconds: 900,
          active: true,
          registered_at: new Date().toISOString(),
          ...body,
          description: body.description ?? base.description,
        };
        setResources((prev) => [...prev, next]);
        return next;
      }
      const result = await resourcesApi.register(body);
      await refresh();
      return result;
    },
    [mode, refresh]
  );

  const update = useCallback(
    async (resourceId: string, body: Partial<{ price_usd: number; active: boolean; approval_required: boolean; entitlement_ttl_seconds: number }>) => {
      if (mode === 'mocked') {
        const base = fixtureResourceList.find((r) => r.resource_id === resourceId) ?? fixtureResourceList[0]!;
        const next: ProtectedResource = { ...base, ...body };
        setResources((prev) => prev.map((r) => (r.resource_id === resourceId ? next : r)));
        return next;
      }
      const result = await resourcesApi.update(resourceId, body);
      await refresh();
      return result;
    },
    [mode, refresh]
  );

  return { resources, loading, error, mode, refresh, get, register, update };
}
