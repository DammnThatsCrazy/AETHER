/** Normalization status for an event. */
export type NormalizationStatus =
  | 'pending'
  | 'processing'
  | 'normalized'
  | 'failed'
  | 'skipped'
  | 'duplicated';

/** A normalization error. */
export interface NormalizationError {
  readonly code: string;
  readonly message: string;
  readonly field?: string;
  readonly original_value?: string;
  readonly expected_type?: string;
  readonly timestamp: string;
}

/** A normalized event record. */
export interface NormalizationRecord {
  readonly id: string;
  readonly event_id: string;
  readonly workspace_id: string;
  readonly tenant_id: string;
  readonly original_event_type: string;
  readonly normalized_event_type: string;
  readonly status: NormalizationStatus;
  readonly normalized_at?: string;
  readonly errors: readonly NormalizationError[];
  readonly original_payload?: Record<string, unknown>;
  readonly normalized_payload?: Record<string, unknown>;
  readonly platform: string;
  readonly platform_id?: string;
  readonly created_at: string;
  readonly updated_at?: string;
}
