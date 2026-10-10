import type { IdentityEvidence } from './identity-evidence';

/** A consolidated profile identity built from multiple identity evidence sources. */
export interface ProfileIdentity {
  readonly user_id: string;
  readonly email: string;
  readonly phone?: string;
  readonly name?: string;
  readonly identity_sources: readonly string[];
  readonly attributes: Record<string, unknown>;
  readonly lifetime_value?: number;
  readonly last_active?: string;
  readonly total_events?: number;
  readonly engagement_score?: number;
  readonly device_count?: number;
  readonly session_count?: number;
  readonly is_merged: boolean;
  readonly created_at: string;
  readonly updated_at: string;
  readonly evidence?: readonly IdentityEvidence[];
}
