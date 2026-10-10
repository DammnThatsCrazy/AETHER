import { useCallback, useEffect, useState } from 'react';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;

export interface SourceReclassificationParams {
  start_date: string;
  end_date: string;
  dry_run: boolean;
  limit: number;
  request_id: string;
}

export function useMeasurementOps() {
  const [overview, setOverview] = useState<AnyRecord>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sourceClassificationHealth, setSourceClassificationHealth] = useState<AnyRecord>({});
  const [sourceClassificationLoading, setSourceClassificationLoading] = useState(true);
  const [sourceClassificationError, setSourceClassificationError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    api.measurement.kyberOverview()
      .then((result: any) => { if (active) setOverview((result as AnyRecord) ?? {}); })
      .catch((e) => active && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  const refreshSourceClassificationHealth = useCallback(async () => {
    setSourceClassificationLoading(true);
    setSourceClassificationError(null);
    try {
      const result = await api.measurement.sourceClassificationHealth();
      setSourceClassificationHealth((result as AnyRecord) ?? {});
    } catch (e) {
      setSourceClassificationError(e instanceof Error ? e.message : String(e));
    } finally {
      setSourceClassificationLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshSourceClassificationHealth();
  }, [refreshSourceClassificationHealth]);

  const restartConnector = (id: string) => api.measurement.restartConnector(id);
  const backfillConnector = (id: string, params: Record<string, string>) => api.measurement.backfillConnector(id, params);
  const recomputeConversion = (id: string) => api.measurement.recomputeConversion(id);
  const recomputeAll = (tenantId: string) => api.measurement.recomputeAll(tenantId);
  const reclassifySources = async (params: SourceReclassificationParams) => {
    const result = await api.measurement.reclassifySources(params);
    await refreshSourceClassificationHealth();
    return result;
  };

  return {
    overview,
    loading,
    error,
    restartConnector,
    backfillConnector,
    recomputeConversion,
    recomputeAll,
    sourceClassificationHealth,
    sourceClassificationLoading,
    sourceClassificationError,
    refreshSourceClassificationHealth,
    reclassifySources,
  };
}
