import type { Journey } from './journey';

/** A time-bounded episode of user activity within a journey or session. */
export interface Episode {
  readonly episode_id: string;
  readonly journey_id?: string;
  readonly session_id?: string;
  readonly user_id?: string;
  readonly device_id?: string;
  readonly start_time: string;
  readonly end_time?: string;
  readonly duration_ms?: number;
  readonly episode_type: EpisodeType;
  readonly sequence_number: number;
  readonly events?: readonly EpisodeEvent[];
  readonly converted?: boolean;
  readonly outcome?: string;
  readonly entry_point?: string;
  readonly context?: {
    readonly locale?: string;
    readonly timezone?: string;
    readonly country?: string;
    readonly region?: string;
    readonly city?: string;
  };
}

/** Type of episode. */
export type EpisodeType =
  | 'session'
  | 'journey'
  | 'onboarding'
  | 'purchase'
  | 'exploration'
  | 'support'
  | 'conversion'
  | 'churn_risk'
  | 'reengagement'
  | 'custom';

/** An event that occurred within an episode. */
export interface EpisodeEvent {
  readonly event_id: string;
  readonly event_type: string;
  readonly timestamp: string;
  readonly properties?: Record<string, unknown>;
}
