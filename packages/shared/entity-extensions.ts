// =============================================================================
// Aether SDK — Per-Entity-Class Profile Extensions
// Typed extensions on the shared EntityProfile base. Each entity class
// (Human, OnchainEntity, Business, Agent) gets a typed extension struct.
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

// ── Onchain Entity Extensions (DAO / Protocol / DEX) ─────────────────────────

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

// ── Business Profile Extension ───────────────────────────────────────────────

export interface CorporateRelationship {
  readonly entity_id: string;
  readonly entity_name: string;
  readonly relationship: 'parent' | 'subsidiary' | 'affiliate' | 'ubo' | 'partner';
  readonly ownership_pct?: number;
}

export interface CorporateStructure {
  readonly entity_id: string;
  readonly legal_name: string;
  readonly jurisdiction: string;         // ISO 3166-1 alpha-2
  readonly incorporation_date?: string;
  readonly business_type: 'llc' | 'corporation' | 'partnership' | 'foundation' | 'dao_legal_wrapper' | 'other';
  readonly sector?: string;
  readonly employee_count_range?: string;    // e.g. "51–200"
  readonly revenue_range_usd?: string;       // e.g. "$1M–$10M"
  readonly relationships: CorporateRelationship[];
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
  readonly operator_kind: 'human' | 'business' | 'organization';
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
