// =============================================================================
// Aether SDK — Canonical Profile360 Contract
//
// THE shared contract for any entity lookup by ID.  Both Kyber (kyber_internal)
// and Aether (end_user) bind to these types.  The backend shapes this response
// at GET /v1/profile360/{entity_type}/{entity_id} and its sub-resource routes.
//
// Given any ID you can request any combination of sub-resources and get back
// a strongly-typed payload with predictable field names.
// =============================================================================

import type {
  SessionSummary, DeviceSummary, PlatformSummary,
  FrequencyMetrics, TemporalPattern,
  BehavioralSignal, WhyExplanation,
  AttributionResolution, AttributionJourney,
  Web3WalletProfile, LoyaltyProfile,
  UserJourney, CampaignFunnel,
} from './contextual';

import type { IntelligenceProfile, WalletRiskProfile } from './intelligence';
import type { UnifiedFinancialProfile } from './financials';
import type {
  RelationshipEdge, DelegationRecord, EntityGraph,
  EntityCluster, RelationshipSummary, GraphNodeKind,
} from './graph-relationships';
import type { Provenance } from './provenance';

// ── Surface & visibility ──────────────────────────────────────────────────────

/** Which product surface is requesting the profile. */
export type Profile360Surface = 'kyber_internal' | 'end_user';

/**
 * Data visibility level — kyber_internal returns unredacted data.
 * end_user returns data the tenant is permitted to expose to their users.
 */
export type Profile360Visibility = 'internal_full' | 'redacted';

// ── Entity type registry ──────────────────────────────────────────────────────

/**
 * Every entity type that supports Profile360 lookup.
 * Pass as the {entity_type} path segment in the API route.
 */
export type Profile360EntityType =
  // People & orgs
  | 'human' | 'user' | 'agent' | 'bot' | 'organization' | 'tenant'
  // Infrastructure
  | 'wallet' | 'device' | 'session' | 'contract' | 'protocol'
  // Activities
  | 'journey' | 'delegation' | 'transaction' | 'payment'
  | 'reward' | 'campaign' | 'execution_trace';

// ── Identity block ────────────────────────────────────────────────────────────

/**
 * Core identity fields present for any entity regardless of type.
 * Always included in Profile360Response.
 */
export interface Profile360Identity {
  readonly entity_id: string;
  readonly entity_type: Profile360EntityType;
  readonly display_label: string;
  readonly kind: GraphNodeKind;
  readonly trust_score: number;          // 0–1
  readonly risk_score: number;           // 0–1
  readonly anomaly_score: number;        // 0–1
  readonly tags?: string[];
  readonly identifiers?: Array<{
    readonly type: string;               // email | wallet | device | session | social | customer_id
    readonly value: string;
    readonly confidence?: number;        // 0–1
  }>;
  readonly created_at?: string;
  readonly updated_at?: string;
}

// ── Sub-resource map ──────────────────────────────────────────────────────────

/**
 * Every field here is independently fetchable via its own GET route.
 * The profile360 full surface returns all populated fields in one call.
 * Individual routes return only that field.
 *
 * Route → field mapping:
 *   GET /v1/profile/{id}/sessions         → sessions
 *   GET /v1/profile/{id}/devices          → devices
 *   GET /v1/profile/{id}/platforms        → platforms
 *   GET /v1/profile/{id}/journeys         → journeys
 *   GET /v1/profile/{id}/wallets          → wallets
 *   GET /v1/profile/{id}/financials       → financials
 *   GET /v1/profile/{id}/intelligence     → intelligence
 *   GET /v1/profile/{id}/rewards          → loyalty
 *   GET /v1/behavioral/entity/{id}        → behavioral
 *   GET /v1/expectations/entity/{id}/explain → why
 *   GET /v1/attribution/journey/{id}      → attribution_journey
 *   GET /v1/profile/{id}/relationships    → relationships, relationship_summary
 *   GET /v1/delegations?grantor={id}      → delegations_granted
 *   GET /v1/delegations?grantee={id}      → delegations_received
 *   GET /v1/entities/{id}/graph           → graph
 *   GET /v1/intelligence/entity/{id}/cluster → cluster
 *   GET /v1/profile/{id}/intelligence     → intelligence
 *   GET /v1/intelligence/wallet/{addr}/risk → wallet_risk (per wallet)
 *   GET /v1/profile/{id}/provenance       → provenance
 *   GET /v1/profile/{id}/timeline         → timeline (events[])
 */
export interface Profile360SubResources {
  // Sessions, devices, platforms
  readonly sessions?: SessionSummary[];
  readonly devices?: DeviceSummary[];
  readonly platforms?: PlatformSummary[];
  readonly frequency?: FrequencyMetrics;
  readonly temporal?: TemporalPattern;

  // Journeys and funnels
  readonly journeys?: UserJourney[];
  readonly campaign_funnels?: CampaignFunnel[];

  // Web3 wallets (one entry per linked wallet address)
  readonly wallets?: Web3WalletProfile[];
  readonly wallet_risk?: WalletRiskProfile[];

  // Financial (Web2 + Web3 unified)
  readonly financials?: UnifiedFinancialProfile;

  // Intelligence and risk
  readonly intelligence?: IntelligenceProfile;

  // Loyalty and rewards
  readonly loyalty?: LoyaltyProfile;

  // Behavioural "Why"
  readonly behavioral?: BehavioralSignal[];
  readonly why?: WhyExplanation;

  // Attribution "Where"
  readonly attribution?: AttributionResolution;
  readonly attribution_journey?: AttributionJourney;

  // Graph relationships
  readonly relationships?: RelationshipEdge[];
  readonly relationship_summary?: RelationshipSummary;
  readonly delegations_granted?: DelegationRecord[];
  readonly delegations_received?: DelegationRecord[];
  readonly graph?: EntityGraph;
  readonly cluster?: EntityCluster;

  // Provenance and audit
  readonly provenance?: Provenance;
}

// ── Canonical response ────────────────────────────────────────────────────────

/**
 * The canonical Profile360 response.
 * Used by both Kyber and Aether to type the result of any profile lookup.
 *
 * GET /v1/profile360/{entity_type}/{entity_id}
 * GET /v1/profile/{user_id}                    (legacy, same shape)
 */
export interface Profile360Response {
  readonly entity_id: string;
  readonly entity_type: Profile360EntityType;
  readonly tenant_id: string;
  readonly surface: Profile360Surface;
  readonly visibility?: Profile360Visibility;
  readonly identity: Profile360Identity;
  readonly sub_resources: Profile360SubResources;
  /** Raw backend payload — available in kyber_internal surface only */
  readonly raw?: Record<string, unknown>;
  readonly computed_at: string;
}

// ── Sub-resource endpoint response wrappers ───────────────────────────────────
// These type the direct JSON responses from individual sub-resource routes,
// each of which wraps its payload in { status, data, timestamp }.

export interface SessionsResponse {
  readonly user_id: string;
  readonly sessions: SessionSummary[];
  readonly count: number;
}

export interface DevicesResponse {
  readonly user_id: string;
  readonly devices: DeviceSummary[];
  readonly count: number;
}

export interface JourneysResponse {
  readonly user_id: string;
  readonly journeys: UserJourney[];
  readonly count: number;
}

export interface WalletsResponse {
  readonly user_id: string;
  readonly wallets: Web3WalletProfile[];
  readonly count: number;
}

export interface RelationshipsResponse {
  readonly entity_id: string;
  readonly outbound: RelationshipEdge[];
  readonly inbound: RelationshipEdge[];
  readonly total: number;
  /** Aggregate breakdown by interaction class / relation type — same route as relationships */
  readonly relationship_summary?: RelationshipSummary;
}

export interface DelegationsResponse {
  readonly entity_id: string;
  readonly granted: DelegationRecord[];
  readonly received: DelegationRecord[];
}

export interface TimelineResponse {
  readonly user_id: string;
  readonly events: unknown[];
  readonly count: number;
}

export interface LakeResponse {
  readonly user_id: string;
  readonly domain: string;
  readonly records: unknown[];
  readonly count: number;
}
