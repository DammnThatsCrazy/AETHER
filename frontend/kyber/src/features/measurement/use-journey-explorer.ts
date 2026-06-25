import { useEffect, useState } from 'react';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;

interface JourneyExplorerData {
  journeys: AnyRecord[];
  hasMore: boolean;
}

const EMPTY: JourneyExplorerData = { journeys: [], hasMore: false };

export function useJourneyExplorer(params: { profile_id?: string; campaign_id?: string; limit?: number } = {}) {
  const [data, setData] = useState<JourneyExplorerData>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    api.journeysMeasurement.list(params)
      .then((result: any) => {
        if (!active) return;
        const items = Array.isArray(result?.items) ? result.items : Array.isArray(result?.data) ? result.data : [];
        setData({ journeys: items, hasMore: Boolean(result?.has_more) });
      })
      .catch((e) => active && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [params.profile_id, params.campaign_id, params.limit]);

  return { data, loading, error };
}
