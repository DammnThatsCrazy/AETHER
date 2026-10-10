import { useState, useEffect } from 'react';
import { api } from '@aether-app/lib/api/endpoints';

// ── Types ──────────────────────────────────────────────────────────────────────

export interface ClusterRecord {
  cluster_id: string;
  cluster_type: string;
  label: string;
  tenant_id: string;
  member_count: number;
  formation_reason: string | null;
  confidence: number;
  lifecycle_state: string;
  created_at: string;
  updated_at: string | null;
  risk_score: number | null;
  properties: Record<string, unknown>;
}

export interface ClusterMember {
  entity_id: string;
  entity_type: string;
  label: string;
  membership_confidence: number;
  joined_at: string | null;
  properties: Record<string, unknown>;
}

export interface ClusterTimelineEvent {
  event_id: string;
  event_type: string;
  timestamp: string;
  description: string;
  metadata: Record<string, unknown>;
}

export interface ClusterEconomicSummary {
  cluster_id: string;
  total_revenue: number;
  total_spend: number;
  ltv_estimate: number;
  transaction_count: number;
  currency: string;
  value_tier: string;
  member_economic_summaries: Array<{ entity_id: string; revenue: number; spend: number }>;
}

export interface ClusterCampaignSummary {
  cluster_id: string;
  attributed_campaigns: Array<{ campaign_id: string; attributed_revenue: number }>;
  total_attributed_revenue: number;
  top_acquisition_channel: string | null;
  conversion_rate: number | null;
}

export interface ClusterRiskSummary {
  cluster_id: string;
  aggregate_risk_score: number;
  risk_tier: string;
  fraud_network_id: string | null;
  fraud_network_type: string | null;
  alert_count: number;
  evidence_refs: string[];
  high_risk_members: string[];
}

export interface ClusterGeographySummary {
  cluster_id: string;
  country_distribution: Record<string, number>;
  region_distribution: Record<string, number>;
  primary_country: string | null;
  geo_concentration_score: number;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function asRecord(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' ? (v as Record<string, unknown>) : {};
}

function extractData<T>(resp: unknown): T {
  const r = asRecord(resp);
  return (r.data ?? resp) as T;
}

// ── Hook ───────────────────────────────────────────────────────────────────────

export function useCluster360(clusterId: string | null) {
  const [cluster, setCluster] = useState<ClusterRecord | null>(null);
  const [members, setMembers] = useState<ClusterMember[]>([]);
  const [timeline, setTimeline] = useState<ClusterTimelineEvent[]>([]);
  const [economic, setEconomic] = useState<ClusterEconomicSummary | null>(null);
  const [campaigns, setCampaigns] = useState<ClusterCampaignSummary | null>(null);
  const [risk, setRisk] = useState<ClusterRiskSummary | null>(null);
  const [geography, setGeography] = useState<ClusterGeographySummary | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!clusterId) return;
    const id = clusterId;
    let cancelled = false;
    setIsLoading(true);
    setError(null);

    async function load() {
      const tenantId = await _resolveTenantId();
      const params = { tenant_id: tenantId };
      const [clusterResp, membersResp, timelineResp, economicResp, campaignsResp, riskResp, geoResp] =
        await Promise.allSettled([
          api.clusters.get(id, params),
          api.clusters.members(id, { ...params, limit: 200 }),
          api.clusters.timeline(id, params),
          api.clusters.economic(id, params),
          api.clusters.campaigns(id, params),
          api.clusters.risk(id, params),
          api.clusters.geography(id, params),
        ]);

      if (cancelled) return;

      if (clusterResp.status === 'fulfilled') setCluster(extractData<ClusterRecord>(clusterResp.value));
      if (membersResp.status === 'fulfilled') {
        const d = extractData<{ members: ClusterMember[] }>(membersResp.value);
        setMembers(d.members ?? []);
      }
      if (timelineResp.status === 'fulfilled') {
        const d = extractData<{ events: ClusterTimelineEvent[] }>(timelineResp.value);
        setTimeline(d.events ?? []);
      }
      if (economicResp.status === 'fulfilled') setEconomic(extractData<ClusterEconomicSummary>(economicResp.value));
      if (campaignsResp.status === 'fulfilled') setCampaigns(extractData<ClusterCampaignSummary>(campaignsResp.value));
      if (riskResp.status === 'fulfilled') setRisk(extractData<ClusterRiskSummary>(riskResp.value));
      if (geoResp.status === 'fulfilled') setGeography(extractData<ClusterGeographySummary>(geoResp.value));
    }

    load()
      .catch(err => { if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load cluster'); })
      .finally(() => { if (!cancelled) setIsLoading(false); });

    return () => { cancelled = true; };
  }, [clusterId]);

  return { cluster, members, timeline, economic, campaigns, risk, geography, isLoading, error };
}

// ── Tenant ID resolution ───────────────────────────────────────────────────────

async function _resolveTenantId(): Promise<string> {
  try {
    const meData = await api.me.profile();
    const r = asRecord(meData);
    return String(r.tenant_id ?? r.tenantId ?? '');
  } catch {
    return '';
  }
}
