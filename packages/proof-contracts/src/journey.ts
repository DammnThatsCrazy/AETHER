import type { SourceClassification } from './source-classification';
import type { Touchpoint } from './touchpoint';
import type { Conversion } from './conversion';

/** A user journey composed of ordered steps and touchpoints. */
export interface Journey {
  readonly journey_id: string;
  readonly name: string;
  readonly description?: string;
  readonly journey_type: string;
  readonly status: JourneyStatus;
  readonly steps: readonly JourneyStep[];
  readonly touchpoints?: readonly Touchpoint[];
  readonly source?: SourceClassification;
  readonly created_at: string;
  readonly updated_at?: string;
  readonly started_at?: string;
  readonly completed_at?: string;
  readonly conversions?: readonly ConversionReference[];
  readonly entered_count?: number;
  readonly completed_count?: number;
}

/** Journey status lifecycle. */
export type JourneyStatus =
  | 'draft'
  | 'active'
  | 'paused'
  | 'completed'
  | 'archived'
  | 'abandoned';

/** A single step within a journey. */
export interface JourneyStep {
  readonly step_id: string;
  readonly name: string;
  readonly description?: string;
  readonly order: number;
  readonly expected_touchpoint_type?: string;
  readonly expected_channel?: string;
  readonly required?: boolean;
  readonly entry_conditions?: Record<string, unknown>;
  readonly completion_conditions?: Record<string, unknown>;
  readonly timeout_ms?: number;
  readonly actions?: readonly string[];
}

/** A reference to a conversion event linked to a journey. */
export interface ConversionReference {
  readonly conversion_id: string;
  readonly event_type: string;
  readonly value?: number;
  readonly currency?: string;
  readonly timestamp: string;
}

/** A journey record — the canonical persisted form. */
export interface JourneyRecord extends Journey {
  readonly id: string;
  readonly workspace_id: string;
  readonly tenant_id: string;
  readonly created_by?: string;
  readonly updated_by?: string;
}

/** Journey lifecycle event types. */
export type JourneyLifecycleEventType =
  | 'journey_started'
  | 'journey_paused'
  | 'journey_resumed'
  | 'journey_continued'
  | 'journey_completed'
  | 'journey_abandoned'
  | 'journey_checkpoint';

/** Journey lifecycle event payload. */
export interface JourneyLifecycleEvent {
  readonly type: JourneyLifecycleEventType;
  readonly journey_id: string;
  readonly user_id: string;
  readonly session_id?: string;
  readonly step_id?: string;
  readonly timestamp: string;
  readonly reason?: string;
  readonly metadata?: Record<string, unknown>;
}
