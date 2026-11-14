import { useCallback, useEffect, useState } from 'react';
import { api } from '@kyber/lib/api';
import type { DiscoveredPatternDetail, DiscoveredPatternList } from '@kyber/lib/api/endpoints';

export type { DiscoveredPatternDetail, DiscoveredPatternList, DiscoveredPatternSummary } from '@kyber/lib/api/endpoints';

/** Analyst verdicts the backend accepts (`ReviewRequest.verdict`). */
export const PATTERN_VERDICTS = ['valid', 'malicious', 'benign', 'duplicate', 'unresolved'] as const;
export type PatternVerdict = (typeof PATTERN_VERDICTS)[number];

/** Statuses an operator can filter the queue by. Empty = the open review queue. */
export const PATTERN_STATUS_FILTERS = [
  '',
  'candidate',
  'confirmed_valid',
  'confirmed_malicious',
  'benign',
  'duplicate',
  'promoted',
  'deprecated',
] as const;

export const PATTERN_KINDS = [
  'sequence',
  'shared_attribute_cluster',
  'behavioral_cohort',
  'temporal_burst',
  'lockstep',
  'behavioral_outlier',
  'novel_motif',
  'schema_drift',
  'cross_domain',
] as const;

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function usePatternQueue(tenantId: string, status: string, kind: string) {
  const [data, setData] = useState<DiscoveredPatternList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    let active = true;
    if (!tenantId) {
      setData(null);
      return () => { active = false; };
    }
    setLoading(true);
    setError(null);
    api.admin.kyber.patternQueue(tenantId, { status: status || undefined, kind: kind || undefined, limit: 100 })
      .then((res) => { if (active) setData(res); })
      .catch((e) => active && setError(message(e)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [tenantId, status, kind]);

  useEffect(() => refresh(), [refresh]);
  return { data, loading, error, refresh };
}

export function usePatternDetail(tenantId: string, patternId: string | null) {
  const [data, setData] = useState<DiscoveredPatternDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    let active = true;
    if (!tenantId || !patternId) {
      setData(null);
      return () => { active = false; };
    }
    setLoading(true);
    setError(null);
    api.admin.kyber.patternDetail(tenantId, patternId)
      .then((res) => { if (active) setData(res); })
      .catch((e) => active && setError(message(e)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [tenantId, patternId]);

  useEffect(() => refresh(), [refresh]);
  return { data, loading, error, refresh, setData };
}

export function usePatternActions(tenantId: string) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wrap = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | null> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(message(e));
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  return {
    busy,
    error,
    run: () => wrap(() => api.admin.kyber.runPatternDiscovery(tenantId)),
    review: (patternId: string, verdict: PatternVerdict, reason: string, duplicateOf?: string) =>
      wrap(() => api.admin.kyber.reviewPattern(tenantId, patternId, {
        verdict, reason, ...(duplicateOf ? { duplicate_of: duplicateOf } : {}),
      })),
    promote: (patternId: string, reason: string) =>
      wrap(() => api.admin.kyber.promotePattern(tenantId, patternId, { reason })),
    deprecate: (patternId: string, reason: string) =>
      wrap(() => api.admin.kyber.deprecatePattern(tenantId, patternId, { reason })),
  };
}
