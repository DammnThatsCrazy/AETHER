import type { ConsentPurpose } from '@aether/shared/consent';

/** Resolution level for identity resolution. */
export type IdentityResolutionLevel =
  | 'none'
  | 'low'
  | 'medium'
  | 'high'
  | 'deterministic';

/** Evidence collected about a resolved identity from one or more identity sources. */
export interface IdentityEvidence {
  readonly evidence_id: string;
  readonly type: IdentityEvidenceType;
  readonly source: string;
  readonly user_id: string;
  readonly anonymous_id?: string;
  readonly match_score?: number;
  readonly confidence?: number;
  readonly raw_payload?: Record<string, unknown>;
  readonly created_at: string;
  readonly email?: string;
  readonly phone?: string;
  readonly verified?: boolean;
  readonly first_seen?: string;
  readonly last_seen?: string;
  readonly attributes?: Record<string, unknown>;
  readonly channel?: string;
}

/** Type of identity evidence. */
export type IdentityEvidenceType =
  | 'email'
  | 'phone'
  | 'wallet'
  | 'device'
  | 'cookie'
  | 'oauth'
  | 'sso'
  | 'ldap'
  | 'custom';

/** Collection of identity evidence from multiple sources for a single user. */
export interface IdentityEvidenceBundle {
  readonly user_id: string;
  readonly evidence: readonly IdentityEvidence[];
  readonly merged_at: string;
  readonly resolution_strategy?: string;
  readonly merged_confidence?: number;
}

/** A resolved identity record — the canonical output of identity resolution. */
export interface IdentityRecord {
  readonly user_id: string;
  readonly anonymous_id: string;
  readonly identities: readonly IdentityRecordIdentity[];
  readonly resolution_level: IdentityResolutionLevel;
  readonly confidence: number;
  readonly merged_at?: string;
  readonly resolved_at: string;
  readonly evidence: readonly IdentityEvidence[];
  readonly consent_purposes?: readonly ConsentPurpose[];
}

/** A single identity within a resolved identity record. */
export interface IdentityRecordIdentity {
  readonly id: string;
  readonly type: IdentityEvidenceType;
  readonly identifier: string;
  readonly source: string;
  readonly verified: boolean;
  readonly first_seen: string;
  readonly last_seen: string;
  readonly confidence: number;
}
