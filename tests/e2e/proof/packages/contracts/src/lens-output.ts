import type { LensInput } from './lens-input';
import type { SourceClassification } from './source-classification';

/** Output result from a lens computation. */
export interface LensOutput {
  readonly workspace_id: string;
  readonly lens_name: string;
  readonly lens_type?: string;
  readonly metrics: Record<string, unknown>;
  readonly top_events?: readonly LensTopEvent[];
  readonly segments?: readonly LensSegment[];
  readonly distribution?: Record<string, readonly LensDistributionBucket[]>;
  readonly time_series?: readonly LensTimeSeriesPoint[];
  readonly computed_at: string;
  readonly computation_time_ms?: number;
  readonly total_records?: number;
  readonly is_partial?: boolean;
  readonly warnings?: readonly string[];
  readonly source?: SourceClassification;
  readonly rows?: readonly LensResultRow[];
}

/** A single result row from a lens query. */
export interface LensResultRow {
  readonly group_key: Record<string, unknown>;
  readonly metrics: Record<string, unknown>;
  readonly row_count: number;
  readonly rank?: number;
}

/** Top event types ranked by frequency. */
export interface LensTopEvent {
  readonly event_type: string;
  readonly count: number;
  readonly percentage?: number;
}

/** A user segment produced by a lens. */
export interface LensSegment {
  readonly segment_id: string;
  readonly name?: string;
  readonly user_count: number;
  readonly percentage?: number;
  readonly rank?: number;
  readonly key_properties?: Record<string, unknown>;
  readonly description?: string;
  readonly metrics?: {
    readonly total_value?: number;
    readonly conversion_count?: number;
    readonly average_value?: number;
  };
}

/** Distribution bucket. */
export interface LensDistributionBucket {
  readonly bucket: string;
  readonly count: number;
  readonly percentage?: number;
}

/** Time series data point. */
export interface LensTimeSeriesPoint {
  readonly timestamp: string;
  readonly value: number;
}
