/**
 * Propagation & Diffusion lens contract (TypeScript mirror).
 *
 * Canonical JSON Schema: packages/shared/contracts/propagation-run.schema.json
 * Python mirror: services/api/intelligence/propagation/contracts.py
 *
 * Unknown metrics are null, never 0. There is no collapsed influence or
 * contagion score. claim_type 'causally_supported' is reserved and is never
 * emitted by the propagation computation.
 */

export const propagationSchemaVersion = 'propagation.run.v1' as const;
export const propagationAlgorithm = 'aether.propagation.exposure_adoption' as const;

export const exposureChannels = ['social', 'onchain', 'in_app', 'relationship'] as const;
export type ExposureChannel = typeof exposureChannels[number];

export const propagationClaimTypes = ['observed', 'inferred', 'causally_supported'] as const;
export type PropagationClaimType = typeof propagationClaimTypes[number];

export const episodeClassifications = ['organic', 'viral', 'coordinated', 'insufficient_data'] as const;
export type EpisodeClassification = typeof episodeClassifications[number];

export interface PropagationQuery {
  tenant_id: string;
  window_start: string;
  window_end: string;
  instrument_keys: string[];
  channels: ExposureChannel[];
  exposure_window_seconds: number;
  max_hops: number;
  lockstep_window_seconds: number;
  lockstep_min_entities: number;
  viral_lift_threshold: number;
  min_exposed_for_baseline: number;
  as_of: string | null;
}

export interface AdoptionEvent {
  tenant_id: string;
  subject_id: string;
  instrument_key: string;
  side: string;
  adopted_at: string;
  venue: string;
  account_ref: string;
  canonical_market_id: string;
  evidence_refs: string[];
}

export interface PropagationHop {
  from_subject: string;
  to_subject: string;
  exposure_id: string;
  channel: ExposureChannel;
  predicate: string;
  lag_seconds: number;
  evidence_refs: string[];
}

export interface InfluenceAssessment {
  decision: string;
  propagation_certified: boolean;
  available_component_ids: string[];
  reason_codes: string[];
  algorithm: string;
  version: string;
}

export interface PropagationPath {
  path_id: string;
  seed_subject: string;
  target_subject: string;
  hops: PropagationHop[];
  depth: number;
  certified_depth: number;
  claim_type: 'observed';
  influence: InfluenceAssessment | null;
}

export interface EpisodeMetrics {
  adopters: number;
  exposed_adopters: number;
  independent_adopters: number;
  propagation_radius: number | null;
  certified_radius: number | null;
  max_breadth: number | null;
  velocity_per_hour: number | null;
  median_lag_seconds: number | null;
  repeated_exposure_adopters: number;
  channels: Partial<Record<ExposureChannel, number>>;
  unknown_reasons: string[];
}

export interface BaselineComparison {
  population: number;
  exposed: number;
  exposed_adopters: number;
  unexposed: number;
  unexposed_adopters: number;
  exposed_rate: number | null;
  unexposed_rate: number | null;
  lift: number | null;
  reason_codes: string[];
}

export interface CoordinationSignal {
  lockstep_groups: string[][];
  shared_funding_pairs: [string, string][];
  reason_codes: string[];
}

export interface DiffusionEpisode {
  episode_id: string;
  tenant_id: string;
  instrument_key: string;
  side: string;
  seed_subject: string;
  started_at: string;
  ended_at: string;
  classification: EpisodeClassification;
  claim_type: 'observed' | 'inferred';
  classification_reasons: string[];
  metrics: EpisodeMetrics;
  baseline: BaselineComparison;
  coordination: CoordinationSignal;
  paths: PropagationPath[];
  adopters: AdoptionEvent[];
}

export interface PropagationRun {
  run_id: string;
  tenant_id: string;
  query: PropagationQuery;
  computed_at: string;
  episodes: DiffusionEpisode[];
  input_digest: string;
  limitations: string[];
  algorithm: typeof propagationAlgorithm;
  algorithm_version: string;
  schema_version: typeof propagationSchemaVersion;
  execution_by_aether: false;
}
