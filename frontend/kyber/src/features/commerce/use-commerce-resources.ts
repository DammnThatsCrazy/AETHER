import { useCallback, useEffect, useState } from 'react';
import { commerceApi } from '@kyber/lib/api/commerce';
import type { Facilitator, ProtectedResource, StablecoinAsset } from '@kyber/lib/schemas/commerce';

export interface UseCommerceResourcesResult {
  readonly resources: readonly ProtectedResource[];
  readonly facilitators: readonly Facilitator[];
  readonly assets: readonly StablecoinAsset[];
  readonly loading: boolean;
  readonly error: string | null;
  refresh(): Promise<void>;
}

export function useCommerceResources(): UseCommerceResourcesResult {
  const [resources, setResources] = useState<ProtectedResource[]>([]);
  const [facilitators, setFacilitators] = useState<Facilitator[]>([]);
  const [assets, setAssets] = useState<StablecoinAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [r, f, a] = await Promise.all([
        commerceApi.listResources(),
        commerceApi.listFacilitators(),
        commerceApi.listAssets(),
      ]);
      setResources(r);
      setFacilitators(f);
      setAssets(a);
    } catch (e) {
      setResources([]);
      setFacilitators([]);
      setAssets([]);
      setError(e instanceof Error ? e.message : 'failed to load commerce resources');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { resources, facilitators, assets, loading, error, refresh };
}
