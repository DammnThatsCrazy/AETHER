import type { SourceClassification } from './source-classification';

/** A single touchpoint in a journey or campaign. */
export interface Touchpoint {
  readonly touchpoint_id: string;
  readonly type: TouchpointType;
  readonly channel: string;
  readonly campaign_id?: string;
  readonly journey_step_id?: string;
  readonly user_id?: string;
  readonly session_id?: string;
  readonly device_id?: string;
  readonly delivered_at: string;
  readonly interacted_at?: string;
  readonly status: TouchpointStatus;
  readonly properties?: Record<string, unknown>;
  readonly url?: string;
  readonly subject?: string;
  readonly personalized?: boolean;
  readonly source?: SourceClassification;
}

/** Touchpoint type categories. */
export type TouchpointType =
  | 'email'
  | 'push'
  | 'sms'
  | 'in-app'
  | 'ad'
  | 'social'
  | 'web'
  | 'display'
  | 'search'
  | 'referral'
  | 'api'
  | 'webhook'
  | 'custom';

/** Touchpoint status lifecycle. */
export type TouchpointStatus =
  | 'pending'
  | 'delivered'
  | 'opened'
  | 'clicked'
  | 'converted'
  | 'ignored'
  | 'failed';
