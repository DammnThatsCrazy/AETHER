// =============================================================================
// Aether SDK — Location History Types
// =============================================================================

import type { TimeWindow } from './asset-composition';

export type LocationClassification =
  | 'primary'    // > 50% of sessions
  | 'secondary'  // 5–50% of sessions
  | 'rare'       // 1–5% of sessions
  | 'one_time';  // < 1% of sessions

export type ConnectionType =
  | 'broadband'
  | 'mobile'
  | 'datacenter'  // likely VPN or cloud provider
  | 'unknown';

export interface LocationHistory {
  readonly entity_id: string;
  readonly window: TimeWindow;
  readonly city: string;
  readonly region: string;
  readonly country: string;
  readonly country_code: string;
  readonly latitude?: number;
  readonly longitude?: number;
  readonly session_count: number;
  /** Fraction of total sessions from this location (0–1) */
  readonly session_pct: number;
  /** Dominant connection type observed from this location */
  readonly connection_type_dominant: ConnectionType;
  readonly classification: LocationClassification;
  /** ISO8601 — first session recorded from this location */
  readonly first_seen_at: string;
  /** ISO8601 — most recent session from this location */
  readonly last_seen_at: string;
  /**
   * true when this location became primary within the last 7 days.
   * Triggers a LOCATION_ANOMALY behavioral signal.
   */
  readonly is_new_primary?: boolean;
}
