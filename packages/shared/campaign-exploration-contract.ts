// =============================================================================
// Aether SDK — Campaign 360 Exploration Contract
//
// Canonical types for the Campaign 360 drill-down surface.
// Both Kyber (operator) and Aether (tenant) bind to these types.
// Backend shapes responses at GET /v1/campaigns/{id}/overview and sub-routes.
// =============================================================================

import type { RelationshipLayer } from './graph-contract';

// ── Population funnel ─────────────────────────────────────────────────────────

/**
 * Population funnel stages — always monotonically decreasing:
 * observed >= resolved >= engaged >= converted >= attributed
 * 'incremental' is additionality-only (requires holdout/control)
 */
export type PopulationType =
  | 'observed'
  | 'resolved'
  | 'engaged'
  | 'converted'
  | 'attributed'
  | 'incremental';

// ── Time range ────────────────────────────────────────────────────────────────

export interface CampaignTimeRange {
  start: string; // ISO date string
  end: string;   // ISO date string
  tz?: string;   // IANA tz name, default UTC
}

// ── Exploration filter ────────────────────────────────────────────────────────

export interface CampaignExplorationFilter {
  campaign_id: string;
  time_range?: CampaignTimeRange;
  population?: PopulationType;
  attribution_model?: string;
  attribution_run_id?: string;
  channel?: string;
  cluster_id?: string;
  entity_type?: string;
  consent_state?: 'granted' | 'denied' | 'unknown';
  limit?: number;
  cursor?: string;
}

// ── Overview ──────────────────────────────────────────────────────────────────

export interface CampaignDataQuality {
  connector_freshness: 'fresh' | 'stale' | 'missing';
  attribution_run_freshness: 'fresh' | 'stale' | 'missing';
  projection_lag_hours: number | null;
  reconciliation_status: 'ok' | 'warn' | 'error';
  completeness_pct: number | null;
}

export interface CampaignOverviewResponse {
  campaign_id: string;
  campaign_name: string;
  status: string;
  channel: string;
  period: CampaignTimeRange;

  // Spend
  spend_usd: number;
  impressions: number;
  clicks: number;
  cpm: number | null;
  cpc: number | null;
  ctr: number | null;

  // Population funnel counts
  observed_count: number;
  resolved_count: number;
  engaged_count: number;
  converted_count: number;
  attributed_count: number;

  // Conversion & revenue
  conversion_count: number;
  fractional_attributed_conversions: number;
  gross_attributed_revenue: number;
  net_attributed_revenue: number;
  roas: number | null;

  // Identity quality
  identity_resolution_rate: number | null;
  data_quality: CampaignDataQuality;

  // Attribution context
  attribution_model: string;
  attribution_run_id: string | null;
  total_credit_weight: number;
  touchpoint_count: number;
}

// ── Population row ────────────────────────────────────────────────────────────

export interface CampaignPopulationRow {
  entity_id: string;
  entity_type: string;
  cluster_id: string | null;
  touchpoint_count: number;
  conversion_count: number;
  attributed_revenue: number;
  attribution_credit: number;
  identity_confidence: number | null;
  last_activity_at: string | null;
  channels: string[];
}

export interface CampaignPopulationResponse {
  campaign_id: string;
  population: PopulationType;
  items: CampaignPopulationRow[];
  pagination: {
    limit: number;
    next_cursor: string | null;
    has_more: boolean;
    total_count: number | null;
  };
}

// ── Cluster row ───────────────────────────────────────────────────────────────

export interface CampaignClusterRow {
  cluster_id: string;
  member_count: number;
  entity_type_counts: Record<string, number>;
  touchpoint_count: number;
  conversion_count: number;
  attributed_gross_revenue: number;
  attributed_net_revenue: number;
  top_channels: string[];
  identity_confidence: number | null;
}

export interface CampaignClustersResponse {
  campaign_id: string;
  items: CampaignClusterRow[];
  pagination: {
    limit: number;
    next_cursor: string | null;
    has_more: boolean;
  };
}

// ── Entity row ────────────────────────────────────────────────────────────────

export interface CampaignEntityRow {
  canonical_id: string;
  entity_type: string;
  cluster_id: string | null;
  display_name: string | null;
  touchpoint_count: number;
  conversion_count: number;
  attributed_revenue: number;
  last_activity_at: string | null;
}

export interface CampaignEntitiesResponse {
  campaign_id: string;
  items: CampaignEntityRow[];
  pagination: {
    limit: number;
    next_cursor: string | null;
    has_more: boolean;
  };
}

// ── Journey row ───────────────────────────────────────────────────────────────

export interface CampaignJourneyRow {
  journey_id: string;
  profile_id: string | null;
  cluster_id: string | null;
  stage_count: number;
  campaign_touchpoint_count: number;
  converted: boolean;
  gross_revenue: number;
  started_at: string | null;
  completed_at: string | null;
}

export interface CampaignJourneysResponse {
  campaign_id: string;
  items: CampaignJourneyRow[];
  pagination: {
    limit: number;
    next_cursor: string | null;
    has_more: boolean;
  };
}

// ── Conversion row ────────────────────────────────────────────────────────────

export interface CampaignConversionRow {
  conversion_id: string;
  profile_id: string | null;
  cluster_id: string | null;
  conversion_type: string;
  status: string;
  gross_value: number;
  net_value: number;
  occurred_at: string;
  attribution_credit: number | null;
  attributed_model: string | null;
}

export interface CampaignConversionsResponse {
  campaign_id: string;
  items: CampaignConversionRow[];
  pagination: {
    limit: number;
    next_cursor: string | null;
    has_more: boolean;
  };
}

// ── Touchpoint row ────────────────────────────────────────────────────────────

export interface CampaignTouchpointRow {
  touchpoint_id: string;
  channel: string;
  source: string;
  user_id: string | null;
  session_id: string | null;
  event_type: string;
  is_conversion: boolean;
  revenue_usd: number;
  occurred_at: string;
}

export interface CampaignTouchpointsResponse {
  campaign_id: string;
  items: CampaignTouchpointRow[];
  pagination: {
    limit: number;
    next_cursor: string | null;
    has_more: boolean;
  };
}

// ── Graph request & response ──────────────────────────────────────────────────

export interface CampaignGraphRequest {
  anchor: string; // campaign_id
  population?: PopulationType;
  time_range?: CampaignTimeRange;
  relationship_layers?: RelationshipLayer[];
  depth?: number; // max 3
  max_nodes?: number; // max 500
  max_edges?: number; // max 1500
  filters?: {
    entity_types?: string[];
    channels?: string[];
    cluster_id?: string;
    min_attribution_credit?: number;
  };
  continuation_token?: string;
}

export interface CampaignGraphNode {
  id: string;
  type: string; // VertexType value
  label: string;
  properties: Record<string, unknown>;
}

export interface CampaignGraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  layer: RelationshipLayer;
  weight?: number;
  properties?: Record<string, unknown>;
}

export interface CampaignGraphResponse {
  campaign_id: string;
  nodes: CampaignGraphNode[];
  edges: CampaignGraphEdge[];
  node_count: number;
  edge_count: number;
  truncated: boolean;
  truncation_reason: string | null;
  continuation_token: string | null;
  depth_reached: number;
  query_budget: {
    max_nodes: number;
    max_edges: number;
    max_depth: number;
    elapsed_ms: number;
  };
}

// ── Evidence envelope ─────────────────────────────────────────────────────────

export interface EvidenceEnvelope {
  tenant_id: string;
  canonical_id: string;
  source_record_ids: string[];
  attribution_run_id: string | null;
  model_name: string | null;
  model_version: string | null;
  computed_at: string | null;
  confidence: number | null; // 0–1
  consent_status: 'granted' | 'denied' | 'unknown';
  data_quality: {
    completeness: number | null; // 0–1
    freshness_hours: number | null;
    source_count: number;
  };
  provenance: Array<{
    source: string;
    record_id: string;
    ingested_at: string | null;
  }>;
}
