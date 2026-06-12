import { useCallback, useEffect, useState } from 'react';
import { isLocalMocked } from '@kyber/lib/env';
import { facilitatorsApi } from '@kyber/lib/api/facilitators';
import type { Facilitator, StablecoinAsset } from '@kyber/lib/schemas/commerce';
import { fixtureFacilitators, fixtureAssets } from '@kyber/fixtures/commerce';

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
  readonly mode: 'mocked' | 'live';
  refresh(): Promise<void>;
  getHealth(facilitatorId: string): Promise<FacilitatorHealth>;
  register(body: { name: string; endpoint_url: string; mode: string; supported_assets: string[]; supported_chains: string[] }): Promise<Facilitator>;
}

export function useFacilitators(): UseFacilitatorsResult {
  const [facilitators, setFacilitators] = useState<Facilitator[]>([]);
  const [assets, setAssets] = useState<StablecoinAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mode: 'mocked' | 'live' = isLocalMocked() ? 'mocked' : 'live';

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (mode === 'mocked') {
        setFacilitators([...fixtureFacilitators]);
        setAssets([...fixtureAssets]);
      } else {
        const [facs, assts] = await Promise.all([facilitatorsApi.list(), facilitatorsApi.listAssets()]);
        setFacilitators(facs);
        setAssets(assts);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed to load facilitators');
    } finally {
      setLoading(false);
    }
  }, [mode]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const getHealth = useCallback(
    async (facilitatorId: string): Promise<FacilitatorHealth> => {
      if (mode === 'mocked') {
        const fac = fixtureFacilitators.find((f) => f.facilitator_id === facilitatorId) ?? fixtureFacilitators[0]!;
        const health: FacilitatorHealth = {
          facilitator_id: fac.facilitator_id,
          health_status: fac.health_status,
          avg_latency_ms: fac.avg_latency_ms,
          success_rate: fac.success_rate,
          last_checked: new Date().toISOString(),
        };
        return health;
      }
      return facilitatorsApi.getHealth(facilitatorId) as Promise<FacilitatorHealth>;
    },
    [mode]
  );

  const register = useCallback(
    async (body: { name: string; endpoint_url: string; mode: string; supported_assets: string[]; supported_chains: string[] }) => {
      if (mode === 'mocked') {
        const next: Facilitator = {
          facilitator_id: `fac_fx_new_${Date.now()}`,
          health_status: 'unknown',
          avg_latency_ms: 0,
          success_rate: 0,
          active: true,
          ...body,
        };
        setFacilitators((prev) => [...prev, next]);
        return next;
      }
      const result = await facilitatorsApi.register(body);
      await refresh();
      return result;
    },
    [mode, refresh]
  );

  return { facilitators, assets, loading, error, mode, refresh, getHealth, register };
}
