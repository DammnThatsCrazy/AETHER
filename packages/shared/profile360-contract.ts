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
import type { UnifiedEconomicBreakdown } from './economic-metrics';
import type { TierProfile } from './tier';
import type { AssetComposition } from './asset-composition';
import type { PNLSummary } from './pnl';
import type { TradingProfile } from './trading-profile';
import type { LocationHistory } from './location-history';
import type { CalendarHeatmap } from './temporal-intelligence';
import type { SocialProfile } from './social-intelligence';
import type {
  JourneyEconomics, DevicePerformance, ConversionFunnel, TimeToConversion,
} from './journey-economics';
import type { RetargetRecommendation } from './recommendations';
import type { Web2Profile } from './web2-profile';
import type {
  ProtocolMetrics, GovernanceActivity, AuditRecord, CorporateStructure,
  BrandProfile, MarketplaceProfile, MediaEntityProfile,
  ExchangeProfile, YieldPlatformProfile,
} from './entity-extensions';

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
 *
 * Entity types are domain-agnostic — the same type covers Web2 and Web3
 * equivalents. Use unified kinds where possible; legacy onchain kinds
 * are preserved for backward compatibility.
 */
export type Profile360EntityType =
  // ── People & agents ──────────────────────────────────────────────────
  | 'human' | 'user' | 'agent' | 'bot' | 'organization' | 'tenant'
  // ── Unified entity categories (Web2 + Web3) ──────────────────────────
  | 'governance_org'    // DAO, NGO, cooperative, government body
  | 'brand'             // company, product brand, SaaS, startup
  | 'marketplace'       // e-commerce platform, app store, gig platform
  | 'media_entity'      // publisher, creator, influencer, media outlet
  | 'exchange'          // DEX, CEX, stock exchange, forex platform
  | 'yield_platform'    // staking protocol, savings account, robo-advisor
  // ── Legacy onchain aliases (backward compat) ─────────────────────────
  | 'dao' | 'dex' | 'staking_platform'
  // ── Business / legal (legacy alias → brand) ───────────────────────────
  | 'business'
  // ── Infrastructure ───────────────────────────────────────────────────
  | 'wallet' | 'device' | 'session' | 'contract' | 'protocol'
  // ── Activities ───────────────────────────────────────────────────────
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

  // Economic intelligence (unified decomposable breakdown)
  //   GET /v1/profile/{id}/economic → economic
  readonly economic?: UnifiedEconomicBreakdown;

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

  // ── Tier & financial intelligence (Human, window-aware) ──────────────────
  /** Entity tier (Whale / Shark / Dolphin / Fish / Shrimp) + percentile rank */
  readonly tier?: TierProfile;
  /** On-chain portfolio composition by asset category */
  readonly asset_composition?: AssetComposition;
  /** Realized + unrealized PNL and TVL delta */
  readonly pnl?: PNLSummary;
  /** Trading behavior: pairs, gas strategy, slippage, protocol loyalty */
  readonly trading_profile?: TradingProfile;

  // ── Geo & temporal intelligence ──────────────────────────────────────────
  /** City-level location history with 30/60/90/lifetime window */
  readonly location_history?: LocationHistory[];
  /** 24×7 activity heatmap + streak data */
  readonly temporal_heatmap?: CalendarHeatmap;

  // ── Social & Web2 ────────────────────────────────────────────────────────
  /** Cross-platform social profile aggregation */
  readonly social_intelligence?: SocialProfile;
  /** TradFi portfolio, bank accounts, credit signal, income estimate */
  readonly web2?: Web2Profile;

  // ── Journey economics & funnel ───────────────────────────────────────────
  /** Per-journey ROAS, CPA, LTV, and retarget score */
  readonly journey_economics?: JourneyEconomics[];
  /** Conversion rate and average value per device type */
  readonly device_performance?: DevicePerformance;
  /** Stage-by-stage conversion funnel (Impression → Liquidity) */
  readonly funnel?: ConversionFunnel;
  /** Median time between each funnel stage */
  readonly time_to_convert?: TimeToConversion;

  // ── Retargeting ──────────────────────────────────────────────────────────
  /** Analyst-review recommendations for re-engaging abandoned journeys */
  readonly retarget_recommendations?: RetargetRecommendation[];

  // ── Protocol / Onchain entity extensions ─────────────────────────────────
  /** TVL history, volume, fee revenue per time window */
  readonly protocol_metrics?: ProtocolMetrics;
  /** Governance proposals, votes, participation rate (DAO, NGO, gov body) */
  readonly governance_activity?: GovernanceActivity;
  /** Security audit history */
  readonly audit_records?: AuditRecord[];

  // ── Unified entity class extensions (Web2 + Web3) ─────────────────────────
  /** Brand/company intelligence — covers any registered business entity */
  readonly brand_profile?: BrandProfile;
  /** Corporate structure: parent/subsidiary tree, UBO, jurisdiction, sector */
  readonly corporate_structure?: CorporateStructure;
  /** Marketplace: GMV, sellers, buyers, take rate */
  readonly marketplace_profile?: MarketplaceProfile;
  /** Media entity / creator / influencer profile */
  readonly media_entity_profile?: MediaEntityProfile;
  /** Exchange profile: trading volume, pairs, regulation (DEX or CEX or stock exchange) */
  readonly exchange_profile?: ExchangeProfile;
  /** Yield platform: TVL, APY, depositors (staking or savings or robo-advisor) */
  readonly yield_platform_profile?: YieldPlatformProfile;

  // ── Silver-backed dimensions (v8.10.0+) ────────────────────────────────────
  /** Content and recommendation exposure facts from silver_exposure_facts */
  readonly exposures?: ExposuresResponse;
  /** Revenue and subscription facts from silver_revenue_facts */
  readonly silver_revenue?: SilverRevenueResponse;
  /** UX friction observations from silver_friction_facts */
  readonly silver_friction?: SilverFrictionResponse;
  /** B2B account activity facts from silver_account_activity_facts */
  readonly accounts?: SilverAccountsResponse;
  /** Notification/email/message delivery facts from silver_comms_facts */
  readonly communications?: SilverCommunicationsResponse;
  /** Integration and server operation facts from silver_server_operation_facts */
  readonly integrations?: SilverIntegrationsResponse;
  /** Data quality and schema completeness from silver_data_quality_facts */
  readonly data_quality?: DataQualityResponse;
}

// ── Canonical response ────────────────────────────────────────────────────────

/**
 * The canonical Profile360 response.
 * Used by both Kyber and Aether to type the result of any profile lookup.
 *
 * GET /v1/profile360/{entity_type}/{entity_id}
 *
 * Backend shape (composer.get_profile360_surface):
 *   entity, tenant_id, surface, visibility, sections, timeline, graph, raw, alignment_audit
 *
 * `identity` and `sub_resources` are conceptual groupings documented in Profile360Identity
 * and Profile360SubResources — the backend surfaces their contents via `entity` and `sections`.
 */
export interface Profile360Response {
  /** Entity identity block — id, type, name, trust/risk/anomaly scores, tags, metadata. */
  readonly entity: Record<string, unknown>;
  readonly tenant_id: string;
  readonly surface: Profile360Surface;
  readonly visibility?: Profile360Visibility;
  /**
   * Keyed sections returned for the requested surface.
   * kyber_internal: identity | system | financial | analytics | debug
   * Each section: { id, title, data }
   */
  readonly sections?: Record<string, { readonly id: string; readonly title: string; readonly data: Record<string, unknown> }>;
  readonly timeline?: unknown[];
  readonly graph?: EntityGraph;
  /** Raw backend payload — available in kyber_internal surface only */
  readonly raw?: Record<string, unknown>;
  readonly alignment_audit?: Record<string, unknown>;
  readonly computed_at?: string;
  /** @deprecated Access entity identity via entity.id / entity.type instead */
  readonly entity_id?: string;
  /** @deprecated Access entity identity via entity.type instead */
  readonly entity_type?: Profile360EntityType;
  /** @deprecated Sub-resource data is in sections; fetch individual routes for typed arrays */
  readonly identity?: Profile360Identity;
  /** @deprecated Sub-resource data is in sections; fetch individual routes for typed arrays */
  readonly sub_resources?: Profile360SubResources;
}

// ── Sub-resource wire envelope ────────────────────────────────────────────────

/**
 * Actual JSON shape returned by every profile sub-resource endpoint:
 *   GET /v1/profile/{id}/sessions|devices|wallets|journeys|relationships|financials
 *
 * The backend aggregator wraps items in this envelope. Access items via `.items`,
 * not the old `.sessions` / `.devices` / `.wallets` field names.
 */
export interface SubResourceEnvelope {
  readonly entity_id: string;
  readonly tenant_id?: string;
  /** Discriminator — "sessions" | "devices" | "wallets" | "journeys" | "relationships" | "financials" */
  readonly kind: string;
  /** The array of enriched items for this sub-resource. */
  readonly items: unknown[];
  readonly summary?: Record<string, unknown>;
  readonly pagination?: {
    readonly total?: number;
    readonly limit?: number;
    readonly offset?: number;
    readonly has_more?: boolean;
  };
  readonly computed_at?: string;
  readonly provenance?: Provenance;
}

/** Sub-resource endpoint response shapes — wire format uses SubResourceEnvelope. */
export type SessionsResponse = SubResourceEnvelope;
export type DevicesResponse = SubResourceEnvelope;
export type JourneysResponse = SubResourceEnvelope;
export type WalletsResponse = SubResourceEnvelope;

export interface RelationshipsResponse {
  readonly entity_id: string;
  readonly outbound: RelationshipEdge[];
  readonly inbound: RelationshipEdge[];
  readonly total: number;
  /** Aggregate breakdown by interaction class / relation type — same route as relationships */
  readonly relationship_summary?: RelationshipSummary;
}

/**
 * Response shape from GET /v1/delegations (list endpoint, with optional
 * grantor= or grantee= filter).  Backend returns a flat list + count.
 * Use delegations_granted / delegations_received (in Profile360SubResources)
 * for the per-profile split that comes from the profile-scoped route.
 */
export interface DelegationsResponse {
  readonly delegations: DelegationRecord[];
  readonly count: number;
}

/**
 * Per-profile delegation split — returned by profile-scoped delegation routes.
 * Separate from DelegationsResponse (list) because the shapes differ.
 */
export interface ProfileDelegationsResponse {
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

// ── Silver-backed sub-resource types (v8.10.0+) ──────────────────────────────

/** Wire format returned by all Silver-backed /v1/profile/{id}/<dim> endpoints. */
export interface SilverFactsEnvelope {
  readonly entity_id: string;
  readonly items: unknown[];
  readonly count: number;
  readonly source: 'silver';
  readonly source_status: 'available' | 'empty';
}

export type ExposuresResponse = SilverFactsEnvelope;
export type SilverRevenueResponse = SilverFactsEnvelope;
export type SilverFrictionResponse = SilverFactsEnvelope;
export type SilverAccountsResponse = SilverFactsEnvelope;
export type SilverCommunicationsResponse = SilverFactsEnvelope;
export type SilverIntegrationsResponse = SilverFactsEnvelope;
export type DataQualityResponse = SilverFactsEnvelope;
