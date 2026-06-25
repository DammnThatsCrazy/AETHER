import { useEffect, useState } from 'react';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;

interface AttributionStudioData {
  runs: AnyRecord[];
  hasMore: boolean;
}

const EMPTY: AttributionStudioData = { runs: [], hasMore: false };

export function useAttributionStudio(params: { conversion_id?: string; model_type?: string; status?: string; limit?: number } = {}) {
  const [data, setData] = useState<AttributionStudioData>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    api.attributionRuns.list(params)
      .then((result: any) => {
        if (!active) return;
        const items = Array.isArray(result?.items) ? result.items : Array.isArray(result?.data) ? result.data : [];
        setData({ runs: items, hasMore: Boolean(result?.has_more) });
      })
      .catch((e) => active && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [params.conversion_id, params.model_type, params.status, params.limit]);

  return { data, loading, error };
}
