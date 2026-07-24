import { useCallback, useEffect, useState } from 'react';
import { facilitatorsApi } from '@kyber/lib/api/facilitators';
import type { Facilitator, StablecoinAsset } from '@kyber/lib/schemas/commerce';

export interface FacilitatorHealth {
  facilitator_id: string;
  health_status: string;
  avg_latency_ms: number;
  success_rate: number;
  last_checked?: string | null;
  error?: string | null;
}

export interface UseFacilitatorsResult {
  readonly facilitators: readonly Facilitator[];
  readonly assets: readonly StablecoinAsset[];
  readonly loading: boolean;
  readonly error: string | null;
  refresh(): Promise<void>;
  getHealth(facilitatorId: string): Promise<FacilitatorHealth>;
  register(body: { name: string; endpoint_url: string; mode: string; supported_assets: string[]; supported_chains: string[] }): Promise<Facilitator>;
}

export function useFacilitators(): UseFacilitatorsResult {
  const [facilitators, setFacilitators] = useState<Facilitator[]>([]);
  const [assets, setAssets] = useState<StablecoinAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [facs, assts] = await Promise.all([facilitatorsApi.list(), facilitatorsApi.listAssets()]);
      setFacilitators(facs);
      setAssets(assts);
    } catch (e) {
      setFacilitators([]);
      setAssets([]);
      setError(e instanceof Error ? e.message : 'failed to load facilitators');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const getHealth = useCallback(
    async (facilitatorId: string): Promise<FacilitatorHealth> =>
      facilitatorsApi.getHealth(facilitatorId) as Promise<FacilitatorHealth>,
    []
  );

  const register = useCallback(
    async (body: { name: string; endpoint_url: string; mode: string; supported_assets: string[]; supported_chains: string[] }) => {
      setError(null);
      try {
        const result = await facilitatorsApi.register(body);
        await refresh();
        return result;
      } catch (e) {
        setError(e instanceof Error ? e.message : 'failed to register facilitator');
        throw e;
      }
    },
    [refresh]
  );

  return { facilitators, assets, loading, error, refresh, getHealth, register };
}
