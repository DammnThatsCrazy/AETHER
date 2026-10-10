import { useEffect, useState } from 'react';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;

interface ConversionExplorerData {
  conversions: AnyRecord[];
  hasMore: boolean;
}

const EMPTY: ConversionExplorerData = { conversions: [], hasMore: false };

export function useConversionExplorer(params: { profile_id?: string; campaign_id?: string; cluster_id?: string; attribution_run_id?: string; channel?: string; conversion_type?: string; status?: string; limit?: number } = {}) {
  const [data, setData] = useState<ConversionExplorerData>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    api.conversions.list(params)
      .then((result: any) => {
        if (!active) return;
        const items = Array.isArray(result?.items) ? result.items : Array.isArray(result?.data) ? result.data : [];
        setData({ conversions: items, hasMore: Boolean(result?.has_more) });
      })
      .catch((e) => active && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [params.profile_id, params.campaign_id, params.cluster_id, params.attribution_run_id, params.channel, params.conversion_type, params.status, params.limit]);

  return { data, loading, error };
}
