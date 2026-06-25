import { useEffect, useState, useCallback } from 'react';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, unknown>;

interface UseQueryState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

function useQuery<T>(
  fetcher: () => Promise<T>,
  deps: unknown[],
): UseQueryState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fetcher()
      .then(result => { if (active) setData(result as T); })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const refetch = useCallback(() => setTick(t => t + 1), []);
  return { data, loading, error, refetch };
}

// ── Overview ──────────────────────────────────────────────────────────────────

export interface Campaign360OverviewParams {
  campaignId: string;
  time_start?: string;
  time_end?: string;
  tz?: string;
  attribution_model?: string;
  attribution_run_id?: string;
}

export function useCampaign360Overview(params: Campaign360OverviewParams) {
  return useQuery<AnyRecord>(
    () => api.campaigns.overview(params.campaignId, {
      time_start: params.time_start,
      time_end: params.time_end,
      tz: params.tz,
      attribution_model: params.attribution_model,
      attribution_run_id: params.attribution_run_id,
    }) as Promise<AnyRecord>,
    [params.campaignId, params.time_start, params.time_end, params.attribution_model, params.attribution_run_id],
  );
}

// ── Population ────────────────────────────────────────────────────────────────

export interface Campaign360PopulationParams {
  campaignId: string;
  population?: string;
  channel?: string;
  cluster_id?: string;
  time_start?: string;
  time_end?: string;
  limit?: number;
  cursor?: string;
}

export function useCampaign360Population(params: Campaign360PopulationParams) {
  return useQuery<AnyRecord>(
    () => api.campaigns.population(params.campaignId, {
      population: params.population,
      channel: params.channel,
      cluster_id: params.cluster_id,
      time_start: params.time_start,
      time_end: params.time_end,
      limit: params.limit,
      cursor: params.cursor,
    }) as Promise<AnyRecord>,
    [params.campaignId, params.population, params.channel, params.cluster_id, params.time_start, params.time_end, params.cursor],
  );
}

// ── Clusters ──────────────────────────────────────────────────────────────────

export interface Campaign360ClustersParams {
  campaignId: string;
  attribution_run_id?: string;
  time_start?: string;
  time_end?: string;
  limit?: number;
  cursor?: string;
}

export function useCampaign360Clusters(params: Campaign360ClustersParams) {
  return useQuery<AnyRecord>(
    () => api.campaigns.clusters(params.campaignId, {
      attribution_run_id: params.attribution_run_id,
      time_start: params.time_start,
      time_end: params.time_end,
      limit: params.limit,
      cursor: params.cursor,
    }) as Promise<AnyRecord>,
    [params.campaignId, params.attribution_run_id, params.time_start, params.time_end, params.cursor],
  );
}

// ── Entities ──────────────────────────────────────────────────────────────────

export interface Campaign360EntitiesParams {
  campaignId: string;
  entity_type?: string;
  time_start?: string;
  time_end?: string;
  limit?: number;
  cursor?: string;
}

export function useCampaign360Entities(params: Campaign360EntitiesParams) {
  return useQuery<AnyRecord>(
    () => api.campaigns.entities(params.campaignId, {
      entity_type: params.entity_type,
      time_start: params.time_start,
      time_end: params.time_end,
      limit: params.limit,
      cursor: params.cursor,
    }) as Promise<AnyRecord>,
    [params.campaignId, params.entity_type, params.time_start, params.time_end, params.cursor],
  );
}

// ── Journeys ──────────────────────────────────────────────────────────────────

export interface Campaign360JourneysParams {
  campaignId: string;
  time_start?: string;
  time_end?: string;
  limit?: number;
  cursor?: string;
}

export function useCampaign360Journeys(params: Campaign360JourneysParams) {
  return useQuery<AnyRecord>(
    () => api.campaigns.journeys(params.campaignId, {
      time_start: params.time_start,
      time_end: params.time_end,
      limit: params.limit,
      cursor: params.cursor,
    }) as Promise<AnyRecord>,
    [params.campaignId, params.time_start, params.time_end, params.cursor],
  );
}

// ── Conversions ───────────────────────────────────────────────────────────────

export interface Campaign360ConversionsParams {
  campaignId: string;
  cluster_id?: string;
  conversion_type?: string;
  status?: string;
  attribution_run_id?: string;
  channel?: string;
  after?: string;
  before?: string;
  include_unattributed?: boolean;
  limit?: number;
  cursor?: string;
}

export function useCampaign360Conversions(params: Campaign360ConversionsParams) {
  return useQuery<AnyRecord>(
    () => api.campaigns.conversions(params.campaignId, {
      cluster_id: params.cluster_id,
      conversion_type: params.conversion_type,
      status: params.status,
      attribution_run_id: params.attribution_run_id,
      channel: params.channel,
      after: params.after,
      before: params.before,
      include_unattributed: params.include_unattributed,
      limit: params.limit,
      cursor: params.cursor,
    }) as Promise<AnyRecord>,
    [params.campaignId, params.cluster_id, params.conversion_type, params.status, params.attribution_run_id, params.channel, params.after, params.before, params.cursor],
  );
}

// ── Graph ─────────────────────────────────────────────────────────────────────

export interface Campaign360GraphParams {
  campaignId: string;
  population?: string;
  time_range?: { start: string; end: string };
  depth?: number;
  max_nodes?: number;
  max_edges?: number;
  filters?: Record<string, unknown>;
}

export function useCampaign360Graph(params: Campaign360GraphParams) {
  return useQuery<AnyRecord>(
    () => api.campaigns.graph(params.campaignId, {
      population: params.population,
      time_range: params.time_range,
      depth: params.depth,
      max_nodes: params.max_nodes,
      max_edges: params.max_edges,
      filters: params.filters,
    }) as Promise<AnyRecord>,
    [params.campaignId, params.population, params.depth, params.max_nodes],
  );
}
