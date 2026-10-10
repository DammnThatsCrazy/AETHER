import type { PlatformType } from '@aether/shared/contextual';
import type { Provenance } from '@aether/shared/provenance';

/** Platform the data originated from — aligned with @aether/shared PlatformType. */
export type SourcePlatform = PlatformType;

/** Classification of the data payload type. */
export type SourceDataType =
  | 'event'
  | 'identity'
  | 'conversion'
  | 'campaign'
  | 'communication'
  | 'commerce'
  | 'graph'
  | 'lens'
  | '360'
  | 'finance'
  | 'support'
  | 'agent'
  | 'value';

/** Source classification metadata attached to data payloads. */
export interface SourceClassification {
  readonly platform: SourcePlatform;
  readonly data_type: SourceDataType;
  readonly platform_id?: string;
  readonly sdk?: string;
  readonly environment?: 'development' | 'staging' | 'production';
  readonly metadata?: Record<string, unknown>;
  readonly connector?: string;
  readonly provenance?: Provenance;
}

/** Data source kind for provenance tracking. */
export type DataSource =
  | 'sdk'
  | 'connector'
  | 'backend'
  | 'inferred'
  | 'import'
  | 'manual';

/** Provenance origin — where the data originally came from. */
export interface ProvenanceOrigin {
  readonly source: DataSource;
  readonly source_id?: string;
  readonly collected_at?: string;
  readonly original_format?: string;
  readonly transformed: boolean;
  readonly transformation_notes?: string;
}
