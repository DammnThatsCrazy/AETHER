import type { SourceClassification } from './source-classification';

/** Input parameters for a lens query. */
export interface LensInput {
  readonly workspace_id: string;
  readonly lens_name: string;
  readonly lens_type?: LensType;
  readonly lens_scope?: LensScope;
  readonly event_types?: readonly string[];
  readonly time_window?: {
    readonly start: string;
    readonly end: string;
  };
  readonly filters?: Record<string, unknown>;
  readonly group_by?: readonly string[];
  readonly aggregations?: readonly LensAggregation[];
  readonly sort?: readonly LensSort[];
  readonly limit?: number;
  readonly offset?: number;
  readonly include_distribution?: boolean;
  readonly percentiles?: readonly number[];
  readonly source?: SourceClassification;
}

/** Lens type categories. */
export type LensType =
  | 'acquisition'
  | 'retention'
  | 'engagement'
  | 'conversion'
  | 'revenue'
  | 'behavior'
  | 'cohort'
  | 'funnel'
  | 'journey'
  | 'custom';

/** Lens scope — the level of aggregation. */
export type LensScope =
  | 'user'
  | 'session'
  | 'event'
  | 'campaign'
  | 'workspace'
  | 'tenant'
  | 'device'
  | 'custom';

/** A single aggregation specification. */
export interface LensAggregation {
  readonly metric: string;
  readonly field: string;
  readonly operation: LensOperation;
  readonly alias?: string;
}

/** Lens aggregation operations. */
export type LensOperation =
  | 'sum'
  | 'count'
  | 'avg'
  | 'min'
  | 'max'
  | 'distinct'
  | 'percentile'
  | 'stddev'
  | 'variance';

/** Lens sort configuration. */
export interface LensSort {
  readonly field: string;
  readonly direction: 'asc' | 'desc';
}
