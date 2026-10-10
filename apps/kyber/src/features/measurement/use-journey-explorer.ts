import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, any>;

interface JourneyExplorerData {
  journeys: AnyRecord[];
  hasMore: boolean;
}

interface JourneyStepsData {
  steps: AnyRecord[];
  hasMore: boolean;
  nextCursor: string | null;
  meta: AnyRecord | null;
}

interface TransitionsData {
  transitions: Record<string, number>;
  families: Record<string, number>;
  total_steps: number;
  has_web3: boolean;
  has_agent: boolean;
  has_x402: boolean;
}

const EMPTY_LIST: JourneyExplorerData = { journeys: [], hasMore: false };
const EMPTY_STEPS: JourneyStepsData = { steps: [], hasMore: false, nextCursor: null, meta: null };

export function useJourneyExplorer(params: { profile_id?: string; campaign_id?: string; limit?: number } = {}) {
  const [data, setData] = useState<JourneyExplorerData>(EMPTY_LIST);
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

export function useJourneySteps(
  journeyId: string | null,
  params: { family?: string; status?: string; wallet_id?: string; chain_id?: string; campaign_id?: string; limit?: number } = {},
) {
  const [data, setData] = useState<JourneyStepsData>(EMPTY_STEPS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cursorRef = useRef<string | null>(null);

  const load = useCallback(async (cursor: string | null, append: boolean) => {
    if (!journeyId) return;
    setLoading(true);
    setError(null);
    try {
      const result: any = await api.journeysMeasurement.steps(journeyId, { ...params, ...(cursor != null ? { cursor } : {}) });
      const items: AnyRecord[] = Array.isArray(result?.data) ? result.data : [];
      const nextCursor = result?.pagination?.next_cursor ?? null;
      const hasMore = Boolean(result?.pagination?.has_more);
      const meta = result?.meta ?? null;
      cursorRef.current = nextCursor;
      setData(prev => ({
        steps: append ? [...prev.steps, ...items] : items,
        hasMore,
        nextCursor,
        meta,
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [journeyId, params.family, params.status, params.wallet_id, params.chain_id, params.campaign_id, params.limit]);

  useEffect(() => {
    cursorRef.current = null;
    setData(EMPTY_STEPS);
    if (journeyId) load(null, false);
  }, [load, journeyId]);

  const loadMore = useCallback(() => {
    if (!data.hasMore || loading) return;
    load(cursorRef.current, true);
  }, [data.hasMore, loading, load]);

  return { data, loading, error, loadMore };
}

export function useJourneyTransitions(journeyId: string | null) {
  const [data, setData] = useState<TransitionsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!journeyId) return;
    let active = true;
    setLoading(true);
    api.journeysMeasurement.transitions(journeyId)
      .then((result: any) => {
        if (!active) return;
        setData((result?.data ?? result) as TransitionsData);
      })
      .catch((e: Error) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [journeyId]);

  return { data, loading, error };
}

export function useJourneyExplain(journeyId: string | null) {
  const [data, setData] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!journeyId) return;
    let active = true;
    setLoading(true);
    api.journeysMeasurement.explain(journeyId)
      .then((result: any) => {
        if (!active) return;
        setData((result?.data ?? result) as AnyRecord);
      })
      .catch((e: Error) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [journeyId]);

  return { data, loading, error };
}

interface JourneyHealthData {
  summary: {
    total_journeys: number;
    avg_steps_per_journey: number;
    quality_breakdown: Record<string, number>;
    compiler_versions: Record<string, number>;
  };
  failed_or_partial: AnyRecord[];
  web3_finality_backlog: number | null;
  rebuild_queue_depth: number | null;
}

const EMPTY_HEALTH: JourneyHealthData = {
  summary: { total_journeys: 0, avg_steps_per_journey: 0, quality_breakdown: {}, compiler_versions: {} },
  failed_or_partial: [],
  web3_finality_backlog: null,
  rebuild_queue_depth: null,
};

export function useJourneyHealth() {
  const [data, setData] = useState<JourneyHealthData>(EMPTY_HEALTH);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    let active = true;
    setLoading(true);
    api.journeysMeasurement.health()
      .then((result: any) => {
        if (!active) return;
        const d = result?.data ?? result;
        setData(d as JourneyHealthData);
      })
      .catch((e: Error) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    return refresh();
  }, [refresh]);

  return { data, loading, error, refresh };
}
