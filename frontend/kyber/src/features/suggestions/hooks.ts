import { useCallback, useEffect, useState } from 'react';
import {
  approveSuggestion,
  fetchReviewQueue,
  fetchSuggestions,
  fetchSuggestionsSummary,
  rejectSuggestion,
  suppressSuggestion,
} from './api';

type AnyRecord = Record<string, any>;

export function useSuggestions(params?: AnyRecord) {
  const [data, setData] = useState<AnyRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fetchSuggestions(params)
      .then((res) => {
        if (!active) return;
        setData(((res as AnyRecord)?.items ?? []) as AnyRecord[]);
      })
      .catch((e) => active && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [params]);

  useEffect(() => refresh(), [refresh]);

  return { data, loading, error, refresh };
}

export function useSuggestionsSummary(tenantId?: string) {
  const [data, setData] = useState<AnyRecord>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fetchSuggestionsSummary(tenantId)
      .then((res) => {
        if (!active) return;
        setData((res as AnyRecord) ?? {});
      })
      .catch((e) => active && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [tenantId]);

  useEffect(() => load(), [load]);

  return { data, loading, error };
}

export function useReviewQueue(limit?: number) {
  const [data, setData] = useState<AnyRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fetchReviewQueue(limit)
      .then((res) => {
        if (!active) return;
        setData(((res as AnyRecord)?.items ?? []) as AnyRecord[]);
      })
      .catch((e) => active && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [limit]);

  useEffect(() => refresh(), [refresh]);

  return { data, loading, error, refresh };
}

export function useSuggestionActions() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const approve = useCallback(async (id: string, notes?: string): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      await approveSuggestion(id, notes);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  const reject = useCallback(async (id: string, reason: string, notes?: string): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      await rejectSuggestion(id, reason, notes);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  const suppress = useCallback(async (id: string, reason: string, hours?: number): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      await suppressSuggestion(id, reason, hours);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  return { approve, reject, suppress, loading, error };
}
