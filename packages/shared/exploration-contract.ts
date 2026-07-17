/**
 * Unified Exploration Fabric contract (v1).
 *
 * One context-preserving query/filter/presentation state shared by every
 * analytical surface. `ExplorationContextV1` COMPOSES the canonical
 * `FilterGroup` from graph-contract.ts (never a second filter language), and
 * every response reports per-filter applicability — a silent filter drop is
 * structurally impossible. Python twin: `shared/exploration/models.py`
 * (parity-tested by `tests/contracts/test_exploration_contract_parity.py`).
 */

import type { DimensionEnvelope, DimensionState } from './dimension-state';
import type { FilterGroup, RelationshipLayer } from './graph-contract';
import type { TemporalAuthority, TemporalRange } from './temporal';

export const explorationContractVersion = '1' as const;

/** How a requested filter was handled by a surface — never silently dropped. */
export const filterDispositions = [
  'applied',        // used exactly as requested
  'translated',     // mapped to an equivalent surface-native filter
  'unsupported',    // the surface cannot apply it (reported, not ignored)
  'suppressed',     // policy/consent/cohort-minimum withheld it
  'not_applicable', // meaningless for this surface/entity kind
] as const;

export type FilterDisposition = typeof filterDispositions[number];

/** Presentation surfaces a context can render into. */
export const explorationViews = [
  'graph',
  'table',
  'map',
  'timeline',
  'flow',
  'comparison',
] as const;

export type ExplorationView = typeof explorationViews[number];

/** Temporal interpretation modes for exploration queries. */
export const explorationTemporalModes = [
  'window',
  'as_of',
  'compare',
  'relative',
] as const;

export type ExplorationTemporalMode = typeof explorationTemporalModes[number];

/** Which timestamp semantics a temporal selection applies to. */
export const explorationTemporalFields = [
  'occurred_at',
  'observed_at',
  'ingested_at',
  'valid_time',
  'computed_at',
] as const;

export type ExplorationTemporalField = typeof explorationTemporalFields[number];

/** A typed reference to any first-class object (entity, cluster, campaign…). */
export interface ExplorationAnchor {
  kind: string;
  id: string;
}

export interface TemporalSelection {
  mode: ExplorationTemporalMode;
  field: ExplorationTemporalField;
  range?: TemporalRange | null;
  as_of?: string | null;
  compare_to?: string | null;
  timezone: string;
  authority?: TemporalAuthority | null;
}

export interface GraphConstraints {
  layers?: RelationshipLayer[];
  edge_types?: string[];
  direction?: 'in' | 'out' | 'both';
  depth?: number;
  traversal_mode?: 'shortest' | 'strongest' | 'k_shortest';
  k?: number;
}

export interface ExplorationSort {
  field: string;
  direction: 'asc' | 'desc';
}

export interface PresentationSpec {
  view: ExplorationView;
  group_by?: string[];
  sort?: ExplorationSort[];
  columns?: string[];
  page_size?: number;
}

export interface SelectionSet {
  focused?: ExplorationAnchor | null;
  selected?: ExplorationAnchor[];
}

export interface TruthRequirements {
  minimum_confidence?: number | null;
  allowed_dimension_states?: DimensionState[];
  include_evidence?: boolean;
  include_provenance?: boolean;
}

/** The versioned, shareable exploration state. URL/state codecs carry ONLY
 * registry field names and opaque ids — never raw PII. */
export interface ExplorationContextV1 {
  version: '1';
  scope: { tenant_id: string; surface: string };
  anchors?: ExplorationAnchor[];
  population?: FilterGroup | null;
  temporal: TemporalSelection;
  graph?: GraphConstraints | null;
  dimensions?: string[];
  overlays?: string[];
  presentation?: PresentationSpec | null;
  selection?: SelectionSet | null;
  truth?: TruthRequirements | null;
}

export interface FilterApplicabilityEntry {
  field: string;
  disposition: FilterDisposition;
  reason?: string | null;
  translated_to?: string | null;
}

/** One entry per requested filter/constraint — completeness is the contract. */
export interface ApplicabilityReport {
  entries: FilterApplicabilityEntry[];
}

export interface ExplorationCompleteness {
  complete: boolean;
  sampled: boolean;
  truncated: boolean;
  truncation_reason?: string | null;
  coverage_percent?: number | null;
}

export interface ExplorationTruth {
  overall_state: DimensionState;
  dimensions: DimensionEnvelope[];
  freshness_watermark?: string | null;
}

export interface ExplorationExecution {
  duration_ms: number;
  cache_status: 'hit' | 'miss' | 'bypass';
  adapters: string[];
}

export interface ExplorationPagination {
  cursor?: string | null;
  has_more: boolean;
  total_estimate?: number | null;
}

/** The canonical envelope every exploration result returns. */
export interface ExplorationResultEnvelope<T> {
  contract_version: string;
  query_id: string;
  normalized_context: ExplorationContextV1;
  data: T;
  pagination?: ExplorationPagination | null;
  completeness: ExplorationCompleteness;
  truth: ExplorationTruth;
  applicability: ApplicabilityReport;
  execution: ExplorationExecution;
  warnings: string[];
}

/** A context-preserving navigation edge to another surface. */
export interface ContextLink {
  to: string;
  context: ExplorationContextV1;
  focus?: ExplorationAnchor | null;
}
