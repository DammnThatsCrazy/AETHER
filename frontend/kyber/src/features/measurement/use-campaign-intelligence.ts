import { useEffect, useState } from 'react';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;

interface CampaignIntelligenceData {
  spend: AnyRecord[];
  reconciliation: AnyRecord;
}

const EMPTY: CampaignIntelligenceData = { spend: [], reconciliation: {} };

export function useCampaignIntelligence(params: { campaign_id?: string; period_start?: string; period_end?: string } = {}) {
  const [data, setData] = useState<CampaignIntelligenceData>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const now = new Date();
  const start = params.period_start ?? new Date(now.getTime() - 30 * 86400000).toISOString().split('T')[0];
  const end = params.period_end ?? now.toISOString().split('T')[0];

  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([
      api.spend.list({ campaign_id: params.campaign_id }),
      api.spend.reconciliation({ campaign_id: params.campaign_id, period_start: start, period_end: end }),
    ])
      .then(([spendResult, recon]: [any, any]) => {
        if (!active) return;
        const items = Array.isArray(spendResult?.items) ? spendResult.items : Array.isArray(spendResult?.data) ? spendResult.data : [];
        setData({ spend: items, reconciliation: (recon as AnyRecord) ?? {} });
      })
      .catch((e) => active && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [params.campaign_id, start, end]);

  return { data, loading, error };
}
