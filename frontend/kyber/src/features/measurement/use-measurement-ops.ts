import { useEffect, useState } from 'react';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;

export function useMeasurementOps() {
  const [overview, setOverview] = useState<AnyRecord>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    api.measurement.kyberOverview()
      .then((result: any) => { if (active) setOverview((result as AnyRecord) ?? {}); })
      .catch((e) => active && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  const restartConnector = (id: string) => api.measurement.restartConnector(id);
  const backfillConnector = (id: string, params: Record<string, string>) => api.measurement.backfillConnector(id, params);
  const recomputeConversion = (id: string) => api.measurement.recomputeConversion(id);
  const recomputeAll = (tenantId: string) => api.measurement.recomputeAll(tenantId);

  return { overview, loading, error, restartConnector, backfillConnector, recomputeConversion, recomputeAll };
}
