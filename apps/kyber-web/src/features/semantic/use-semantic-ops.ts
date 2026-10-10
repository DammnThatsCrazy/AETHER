import { useCallback, useEffect, useState } from 'react';
import { api } from '@kyber/lib/api';

export type SemanticFleetHealth = Awaited<ReturnType<typeof api.admin.kyber.semanticFleetHealth>>;
export type SemanticReviewQueue = Awaited<ReturnType<typeof api.admin.kyber.semanticReviewQueue>>;
export type SemanticReviewQueueItem = SemanticReviewQueue['items'][number];

/** Canonical Kyber semantic review queue taxonomy (route appends it as `queues`;
 *  used as the fallback until the first response arrives). */
export const SEMANTIC_QUEUE_TYPES = [
  'ambiguous_subject',
  'campaign_mapping',
  'graph_promotion_candidate',
] as const;

/** Fleet-health fields the backend currently HARDCODES (routes overwrite them
 *  with 0/0/false). The scorecard must label these "not yet instrumented"
 *  instead of rendering their values as live metrics. */
export const NOT_YET_INSTRUMENTED_FIELDS = [
  { key: 'queue_lag_seconds', label: 'Queue lag' },
  { key: 'graph_promotion_rate', label: 'Graph promotion rate' },
  { key: 'cross_tenant_contamination', label: 'Cross-tenant contamination' },
] as const;

export function useSemanticFleetHealth() {
  const [data, setData] = useState<SemanticFleetHealth | null>(null);
  const [fetchedAt, setFetchedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    let active = true;
    setLoading(true);
    setError(null);
    api.admin.kyber.semanticFleetHealth()
      .then((res) => {
        if (!active) return;
        setData(res);
        setFetchedAt(new Date().toISOString());
      })
      .catch((e) => active && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  useEffect(() => refresh(), [refresh]);

  return { data, fetchedAt, loading, error, refresh };
}

export function useSemanticReviewQueue(queueType?: string) {
  const [data, setData] = useState<SemanticReviewQueue | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    let active = true;
    setLoading(true);
    setError(null);
    api.admin.kyber.semanticReviewQueue(queueType)
      .then((res) => {
        if (!active) return;
        setData(res);
      })
      .catch((e) => active && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [queueType]);

  useEffect(() => refresh(), [refresh]);

  return { data, loading, error, refresh };
}
