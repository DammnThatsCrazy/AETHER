// =============================================================================
// Aether SDK — Per-Entity-Class Profile Extensions
//
// Typed extensions on the shared EntityProfile base. Entity classes are
// domain-agnostic — Web2 and Web3 entities share unified types where possible.
//
// Entity class → extension type mapping:
//   human              → HumanProfileExtension
//   brand / business   → BrandProfile + CorporateStructure
//   governance_org     → GovernanceActivity (covers DAO + NGO + gov body)
//   exchange           → ExchangeProfile (covers DEX + CEX + stock exchange)
//   yield_platform     → YieldPlatformProfile (covers staking + savings)
//   marketplace        → MarketplaceProfile
//   media_entity       → MediaEntityProfile
//   protocol           → ProtocolMetrics (on-chain protocols)
//   agent              → AgentProfileExtension
// =============================================================================

import type { TimeWindow } from './asset-composition';

// ── Human Profile Extension ───────────────────────────────────────────────────

export interface HumanProfileExtension {
  /** Age range (e.g. "35–44") — never exact DOB */
  readonly age_range?: string;
  /** ISO 3166-1 alpha-2 country of primary residence */
  readonly country_of_residence?: string;
  readonly kyc_level?: 0 | 1 | 2 | 3;   // 0=none, 1=email, 2=phone+email, 3=ID verified
  readonly is_accredited_investor?: boolean;
}

// ── Protocol / Onchain Entity Extensions ─────────────────────────────────────

export type ProtocolFamilyLabel =
  | 'DEX' | 'Lending' | 'Bridge' | 'Staking' | 'Restaking'
  | 'Stablecoin' | 'Governance' | 'NFT_Marketplace' | 'Gaming'
  | 'Payments' | 'Prediction_Market' | 'RWA' | 'Yield_Aggregator'
  | 'Derivatives' | 'Insurance' | 'Oracle' | 'Infrastructure' | 'Other';

export interface ProtocolTVLSnapshot {
  readonly date: string;
  readonly tvl_usd: number;
}

export interface ProtocolMetrics {
  readonly entity_id: string;
  readonly window: TimeWindow;
  readonly protocol_family: ProtocolFamilyLabel;
  readonly tvl_usd: number;
  readonly tvl_history: ProtocolTVLSnapshot[];
  readonly volume_usd: number;
  readonly fee_revenue_usd: number;
  readonly unique_users: number;
  readonly transaction_count: number;
  /** Chains this protocol is deployed on */
  readonly chain_ids: string[];
  readonly computed_at: string;
}

export interface GovernanceProposalSummary {
  readonly proposal_id: string;
  readonly title: string;
  readonly state: 'active' | 'passed' | 'rejected' | 'cancelled' | 'pending';
  readonly votes_for: number;
  readonly votes_against: number;
  readonly votes_abstain: number;
  readonly quorum_met: boolean;
  readonly created_at: string;
  readonly end_at: string;
}

export interface GovernanceActivity {
  readonly entity_id: string;
  readonly window: TimeWindow;
  readonly proposal_count: number;
  readonly vote_count: number;
  readonly participation_rate: number;   // votes_cast / proposals_in_window
  readonly quorum_hit_rate: number;      // proposals that reached quorum / total
  readonly recent_proposals: GovernanceProposalSummary[];
  readonly computed_at: string;
}

export interface AuditRecord {
  readonly audit_id: string;
  readonly auditor_name: string;
  readonly audit_date: string;
  readonly severity_findings: Record<'critical' | 'high' | 'medium' | 'low' | 'informational', number>;
  readonly report_url?: string;
  readonly scope: string;
  readonly resolved: boolean;
}

// ── Brand / Business Profile Extension ───────────────────────────────────────

export interface CorporateRelationship {
  readonly entity_id: string;
  readonly entity_name: string;
  readonly relationship: 'parent' | 'subsidiary' | 'affiliate' | 'ubo' | 'partner' | 'investor';
  readonly ownership_pct?: number;
}

export interface CorporateStructure {
  readonly entity_id: string;
  readonly legal_name: string;
  readonly jurisdiction: string;         // ISO 3166-1 alpha-2
  readonly incorporation_date?: string;
  readonly business_type: 'llc' | 'corporation' | 'partnership' | 'foundation' | 'dao_legal_wrapper' | 'cooperative' | 'ngo' | 'other';
  readonly sector?: string;
  readonly employee_count_range?: string;    // e.g. "51–200"
  readonly revenue_range_usd?: string;       // e.g. "$1M–$10M"
  readonly relationships: CorporateRelationship[];
  readonly computed_at: string;
}

/** Brand/company intelligence — covers any registered business entity */
export interface BrandProfile {
  readonly entity_id: string;
  readonly window: TimeWindow;
  readonly corporate_structure?: CorporateStructure;
  /** Estimated customer count or MAU */
  readonly customer_count_estimate?: number;
  /** Primary product/service category */
  readonly primary_category?: string;
  /** Known social media presence across platforms */
  readonly social_platform_ids?: Record<string, string>;
  /** Funding rounds (for startups) */
  readonly funding_stage?: 'pre-seed' | 'seed' | 'series-a' | 'series-b' | 'series-c+' | 'public' | 'bootstrapped' | 'unknown';
  readonly total_funding_usd?: number;
  readonly computed_at: string;
}

// ── Marketplace Profile Extension ─────────────────────────────────────────────

export interface MarketplaceProfile {
  readonly entity_id: string;
  readonly window: TimeWindow;
  /** GMV = Gross Merchandise Value processed through the marketplace */
  readonly gmv_usd?: number;
  readonly active_sellers?: number;
  readonly active_buyers?: number;
  readonly product_category_count?: number;
  /** Primary marketplace type */
  readonly marketplace_type: 'ecommerce' | 'b2b' | 'gig' | 'real_estate' | 'financial' | 'nft' | 'other';
  readonly take_rate_pct?: number;          // platform commission %
  readonly avg_order_value_usd?: number;
  readonly computed_at: string;
}

// ── Media Entity / Influencer Profile Extension ───────────────────────────────

export interface ContentChannel {
  readonly platform: string;
  readonly channel_id?: string;
  readonly channel_name?: string;
  readonly subscriber_count?: number;
  readonly total_content_count?: number;
}

export interface MediaEntityProfile {
  readonly entity_id: string;
  readonly window: TimeWindow;
  /** Creator / brand / media outlet type */
  readonly media_type: 'creator' | 'influencer' | 'publisher' | 'podcast' | 'newsletter' | 'media_outlet' | 'agency' | 'other';
  readonly primary_content_category?: string;   // e.g. "finance", "gaming", "tech"
  readonly channels: ContentChannel[];
  /** Total cross-platform reach (deduplicated where possible) */
  readonly total_reach_estimate?: number;
  readonly avg_engagement_rate?: number;
  /** Revenue model */
  readonly monetization_types?: Array<'ads' | 'sponsorships' | 'subscriptions' | 'merchandise' | 'courses' | 'affiliate' | 'tips' | 'other'>;
  readonly computed_at: string;
}

// ── Exchange Profile Extension ─────────────────────────────────────────────────

export interface ExchangeProfile {
  readonly entity_id: string;
  readonly window: TimeWindow;
  /** Whether this is a decentralized (on-chain) or centralized exchange */
  readonly exchange_type: 'dex' | 'cex' | 'hybrid' | 'traditional_stock' | 'forex' | 'commodity' | 'other';
  readonly trading_volume_usd?: number;
  readonly open_interest_usd?: number;
  readonly unique_traders?: number;
  readonly listed_pairs_count?: number;
  readonly regulated?: boolean;
  readonly primary_jurisdictions?: string[];  // ISO 3166-1 alpha-2
  /** Chains (for DEX) or fiat corridors (for CEX/traditional) */
  readonly supported_chains_or_corridors?: string[];
  readonly computed_at: string;
}

// ── Yield Platform Profile Extension ──────────────────────────────────────────

export interface YieldPlatformProfile {
  readonly entity_id: string;
  readonly window: TimeWindow;
  /** Platform type spans staking protocols to savings accounts */
  readonly platform_type: 'staking' | 'restaking' | 'lending' | 'liquid_staking' | 'savings_account' | 'robo_advisor' | 'yield_aggregator' | 'other';
  readonly total_value_locked_usd?: number;
  readonly apy_range?: { min: number; max: number };
  readonly depositor_count?: number;
  readonly regulated?: boolean;
  /** For DeFi: on-chain chains; for TradFi: regulatory body names */
  readonly oversight_entities?: string[];
  readonly computed_at: string;
}

// ── Agent Profile Extension ──────────────────────────────────────────────────

export interface AgentCapability {
  readonly capability_id: string;
  readonly name: string;
  readonly description?: string;
}

export interface AgentProfileExtension {
  readonly agent_id: string;
  readonly operator_entity_id: string;
  readonly operator_kind: 'human' | 'brand' | 'organization' | 'business';
  readonly capability_set: AgentCapability[];
  readonly spending_limit_usd?: number;
  /** Scopes from the controlling delegation record */
  readonly delegation_scope: string[];
  readonly execution_count_total: number;
  readonly execution_success_rate: number;
  readonly avg_agent_confidence: number;
  readonly first_deployed_at: string;
  readonly last_active_at?: string;
}
