import { useCallback, useEffect, useState } from 'react';
import { api } from '@kyber/lib/api';
import type { PatternCurationAction, PatternKind, PatternVerdict } from '@aether/shared';
import type { DiscoveredPatternDetail, DiscoveredPatternList, PatternSubgraph, PatternWhatsNew } from '@kyber/lib/api/endpoints';

export type {
  DiscoveredPatternDetail, DiscoveredPatternList, DiscoveredPatternSummary, PatternSubgraph, PatternWhatsNew,
} from '@kyber/lib/api/endpoints';

/** Typed against the shared contract (packages/shared/pattern-discovery.ts), whose
 *  parity with the backend is asserted by tests/unit/test_pattern_discovery_contract_parity.py;
 *  a value outside the shared vocabulary fails the typecheck. */
export type { PatternCurationAction, PatternKind, PatternVerdict } from '@aether/shared';

export const PATTERN_VERDICTS = ['valid', 'malicious', 'benign', 'duplicate', 'unresolved'] as const satisfies readonly PatternVerdict[];

export const PATTERN_KINDS = [
  'sequence',
  'shared_attribute_cluster',
  'behavioral_cohort',
  'temporal_burst',
  'lockstep',
  'behavioral_outlier',
  'novel_motif',
  'schema_drift',
  'segment_shift',
  'agent_spawn_anomaly',
  'agent_tool_signature',
  'agent_interaction_cluster',
  'traffic_anomaly',
  'cross_domain',
] as const satisfies readonly PatternKind[];

/** Statuses an operator can filter by. Empty = the surfaced feed (what tenants see by default). */
export const PATTERN_STATUS_FILTERS = [
  '',
  'surfaced',
  'candidate',
  'hidden',
  'confirmed_valid',
  'confirmed_malicious',
  'benign',
  'duplicate',
  'unresolved',
  'promoted',
  'deprecated',
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

/** Loads one value for (tenant, key) with a manual refresh; nothing loads without a tenant / key. */
function useLoader<T>(tenantId: string, key: string | null, load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(() => {
    let active = true;
    if (!tenantId || key === null) {
      setData(null);
      return () => { active = false; };
    }
    setLoading(true);
    setError(null);
    load()
      .then((res) => { if (active) setData(res); })
      .catch((e) => active && setError(message(e)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [tenantId, key]);
  useEffect(() => refresh(), [refresh]);
  return { data, loading, error, refresh };
}

/** New / changed / retired patterns since this operator last looked at the tenant's feed. */
export function usePatternWhatsNew(tenantId: string) {
  return useLoader<PatternWhatsNew>(tenantId, 'feed', () => api.admin.kyber.patternWhatsNew(tenantId, 'feed'));
}

export function usePatternGraph(tenantId: string, patternId: string | null) {
  return useLoader<PatternSubgraph>(tenantId, patternId, () => api.admin.kyber.patternGraph(tenantId, patternId ?? ''));
}

export function usePatternCuration(tenantId: string) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const curate = useCallback(async (patternId: string, action: PatternCurationAction, title?: string): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      await api.admin.kyber.curatePattern(tenantId, patternId, title !== undefined ? { action, title } : { action });
      return true;
    } catch (e) {
      setError(message(e));
      return false;
    } finally {
      setBusy(false);
    }
  }, [tenantId]);
  const markSeen = useCallback(async (): Promise<boolean> => {
    try {
      await api.admin.kyber.markPatternsSeen(tenantId, 'feed');
      return true;
    } catch (e) {
      setError(message(e));
      return false;
    }
  }, [tenantId]);
  return { curate, markSeen, busy, error };
}
