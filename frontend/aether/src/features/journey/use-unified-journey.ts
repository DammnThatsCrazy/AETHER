import { useCallback, useEffect, useRef, useState } from 'react';

export type ActivityFamily = 'web2' | 'web3' | 'campaign' | 'commerce' | 'agent' | 'x402' | 'outcome';
export type ActivityStatus =
  | 'observed' | 'pending' | 'confirmed' | 'finalized'
  | 'failed' | 'reverted' | 'reorged' | 'adjusted'
  | 'deleted' | 'tombstoned' | 'consent_restricted';

export interface JourneyStep {
  step_id: string;
  step_position: number;
  activity_family: ActivityFamily;
  activity_type: string;
  activity_status: ActivityStatus;
  actor_type: string | null;
  transition_type: string | null;
  channel: string | null;
  source: string | null;
  domain: string | null;
  dapp_id: string | null;
  chain_id: string | null;
  wallet_id: string | null;
  agent_id: string | null;
  campaign_id: string | null;
  session_id: string | null;
  identity_confidence: number | null;
  identity_method: string | null;
  occurred_at: string;
  displayLabel: string;
  risk_score: number | null;
  risk_tier: string | null;
  fraud_status: string | null;
  fraud_disposition: string | null;
}

export interface JourneyMeta {
  journey_id: string;
  journey_version_id: string;
  step_count: number;
  compiler_version: string | null;
  quality_status: 'complete' | 'partial' | 'empty' | 'not_provisioned';
}

export interface UnifiedJourneyResult {
  steps: JourneyStep[];
  meta: JourneyMeta | null;
  hasMore: boolean;
  nextCursor: string | null;
  loading: boolean;
  error: string | null;
  loadMore: () => void;
}

interface Params {
  profileId: string;
  family?: ActivityFamily;
  after?: string;
  before?: string;
  limit?: number;
}

async function fetchJourneyPage(
  profileId: string,
  params: { family?: string; after?: string; before?: string; limit?: number; cursor?: string },
): Promise<{ steps: JourneyStep[]; meta: JourneyMeta | null; next_cursor: string | null; has_more: boolean }> {
  const qs = new URLSearchParams();
  if (params.family) qs.set('family', params.family);
  if (params.after) qs.set('after', params.after);
  if (params.before) qs.set('before', params.before);
  if (params.limit) qs.set('limit', String(params.limit));
  if (params.cursor) qs.set('cursor', params.cursor);
  const url = `/v1/profile/${encodeURIComponent(profileId)}/unified-journey?${qs.toString()}`;
  const res = await fetch(url, { credentials: 'include' });
  if (!res.ok) throw new Error(`Journey request failed: ${res.status}`);
  const body = await res.json();
  const data = body.data ?? body;
  return {
    steps: Array.isArray(data.steps) ? data.steps : [],
    meta: data.meta ?? null,
    next_cursor: data.pagination?.next_cursor ?? data.next_cursor ?? null,
    has_more: Boolean(data.pagination?.has_more ?? data.has_more),
  };
}

export function useUnifiedJourney(params: Params): UnifiedJourneyResult {
  const { profileId, family, after, before, limit = 50 } = params;
  const [steps, setSteps] = useState<JourneyStep[]>([]);
  const [meta, setMeta] = useState<JourneyMeta | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const cursorRef = useRef<string | null>(null);

  const load = useCallback(
    async (cursor: string | null, append: boolean) => {
      setLoading(true);
      setError(null);
      try {
        const pageParams: Parameters<typeof fetchJourneyPage>[1] = { limit };
        if (family) pageParams.family = family;
        if (after) pageParams.after = after;
        if (before) pageParams.before = before;
        if (cursor != null) pageParams.cursor = cursor;
        const page = await fetchJourneyPage(profileId, pageParams);
        setSteps(prev => append ? [...prev, ...page.steps] : page.steps);
        setMeta(page.meta);
        setHasMore(page.has_more);
        setNextCursor(page.next_cursor);
        cursorRef.current = page.next_cursor;
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [profileId, family, after, before, limit],
  );

  useEffect(() => {
    cursorRef.current = null;
    setSteps([]);
    setNextCursor(null);
    setHasMore(false);
    load(null, false);
  }, [load]);

  const loadMore = useCallback(() => {
    if (!hasMore || loading) return;
    load(cursorRef.current, true);
  }, [hasMore, loading, load]);

  return { steps, meta, hasMore, nextCursor, loading, error, loadMore };
}
