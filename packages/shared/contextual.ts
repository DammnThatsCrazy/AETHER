// =============================================================================
// Aether SDK — Contextual Profile Contracts
// Server-computed types for session, device, temporal, journey, attribution
// and loyalty data. Consumed by both Kyber (aggregated) and Aether (per-tenant).
// =============================================================================

import type { DeviceContext, CampaignContext } from './events';

// ── Platform ──────────────────────────────────────────────────────────────────

export type PlatformType =
  | 'web'
  | 'ios_app'
  | 'android_app'
  | 'react_native'
  | 'sdk'
  | 'api'
  | 'unknown';

// ── Geo ───────────────────────────────────────────────────────────────────────

export interface GeoContext {
  readonly country_code?: string;
  readonly region?: string;
  readonly city?: string;
  readonly timezone?: string;
  readonly latitude?: number;
  readonly longitude?: number;
  readonly is_vpn?: boolean;
  readonly is_proxy?: boolean;
  readonly is_tor?: boolean;
  readonly is_datacenter?: boolean;
}

// ── Sessions ──────────────────────────────────────────────────────────────────

/** Server-enriched session rollup — returned by GET /v1/profile/{id}/sessions */
export interface SessionSummary {
  readonly session_id: string;
  readonly user_id?: string;
  readonly device_id?: string;
  readonly platform: PlatformType;
  readonly device: DeviceContext;
  readonly geo?: GeoContext;
  readonly started_at: string;
  readonly ended_at?: string;
  readonly duration_ms?: number;
  readonly page_views: number;
  readonly event_count: number;
  readonly entry_url?: string;
  readonly exit_url?: string;
  readonly referrer?: string;
  readonly campaign?: CampaignContext;
}

/** Server-observed device — returned by GET /v1/profile/{id}/devices */
export interface DeviceSummary {
  readonly device_id: string;
  readonly type: DeviceContext['type'];
  readonly os?: string;
  readonly os_version?: string;
  readonly browser?: string;
  readonly browser_version?: string;
  readonly first_seen_at: string;
  readonly last_seen_at: string;
  readonly session_count: number;
  /** true = linked via login, false = probabilistic fingerprint match */
  readonly is_deterministic: boolean;
}

/** Platform attribution entry — returned by GET /v1/profile/{id}/platforms */
export interface PlatformSummary {
  readonly platform: PlatformType;
  readonly session_count: number;
  readonly event_count: number;
  readonly first_seen_at: string;
  readonly last_seen_at: string;
}

// ── Temporal & Frequency ──────────────────────────────────────────────────────

export interface HourBucket {
  readonly hour: number; // 0–23 UTC
  readonly event_count: number;
  readonly session_count: number;
  /** 0–1 relative weight within this user's own distribution */
  readonly relative_weight: number;
}

export interface DayBucket {
  readonly day: 0 | 1 | 2 | 3 | 4 | 5 | 6; // 0 = Sunday
  readonly event_count: number;
  readonly session_count: number;
  readonly relative_weight: number;
}

export interface TemporalPattern {
  readonly peak_hour: number; // 0–23
  readonly peak_day: 0 | 1 | 2 | 3 | 4 | 5 | 6;
  readonly hour_distribution: HourBucket[];
  readonly day_distribution: DayBucket[];
  readonly timezone?: string;
}

export type ChurnRisk = 'low' | 'medium' | 'high' | 'churned';

export interface FrequencyMetrics {
  readonly sessions_7d: number;
  readonly sessions_30d: number;
  readonly sessions_90d: number;
  readonly events_7d: number;
  readonly events_30d: number;
  readonly active_days_30d: number;
  readonly avg_session_duration_ms: number;
  readonly avg_events_per_session: number;
  /** Days elapsed since the most recent session */
  readonly recency_days: number;
  readonly first_seen_at: string;
  readonly last_seen_at: string;
  readonly is_new: boolean;
  readonly churn_risk: ChurnRisk;
}

// ── Journey & Funnel ──────────────────────────────────────────────────────────

export interface JourneyStep {
  readonly step_index: number;
  readonly step_name: string;
  readonly page?: string;
  readonly event_type: string;
  readonly channel?: string;
  readonly source?: string;
  readonly campaign_id?: string;
  readonly campaign_name?: string;
  readonly timestamp: string;
  readonly time_on_step_ms?: number;
  readonly completed: boolean;
  /** User left after this step but resumed later in the same journey */
  readonly is_drop_off: boolean;
  /** User left after this step and never returned to this journey */
  readonly is_abandonment: boolean;
  readonly exit_reason?: string;
}

export interface UserJourney {
  readonly journey_id: string;
  readonly user_id: string;
  readonly session_id?: string;
  readonly started_at: string;
  readonly completed_at?: string;
  readonly total_time_ms?: number;
  /** 0–1 fraction of steps completed */
  readonly completion_rate: number;
  readonly steps: JourneyStep[];
  readonly entry_channel?: string;
  readonly entry_campaign_id?: string;
  readonly converted: boolean;
  readonly conversion_value_usd?: number;
}

export interface FunnelStep {
  readonly step_name: string;
  readonly step_index: number;
  /** Unique users who reached this step */
  readonly entered: number;
  readonly completed: number;
  readonly dropped: number;
  readonly abandoned: number;
  /** dropped / entered */
  readonly drop_off_rate: number;
  /** abandoned / entered */
  readonly abandonment_rate: number;
  readonly avg_time_ms?: number;
}

export interface CampaignFunnel {
  readonly campaign_id: string;
  readonly campaign_name?: string;
  readonly channel?: string;
  readonly period_start: string;
  readonly period_end: string;
  readonly total_entered: number;
  readonly total_converted: number;
  readonly overall_conversion_rate: number;
  readonly steps: FunnelStep[];
}

// ── Behavioural "Why" ─────────────────────────────────────────────────────────

export type SignalFamily =
  | 'intent_residue'
  | 'wallet_friction'
  | 'identity_deltas'
  | 'continuity'
  | 'sequence_scars'
  | 'source_shadow';

export type SignalType =
  | 'SOURCE_SILENCE'
  | 'MISSING_EXPECTED_ACTION'
  | 'MISSING_EXPECTED_EDGE'
  | 'IDENTITY_CONTRADICTION'
  | 'RELATIONSHIP_CONTRADICTION'
  | 'TEMPORAL_CONTRADICTION'
  | 'GRAPH_CONTRADICTION'
  | 'MODEL_CONTRADICTION'
  | 'BROKEN_SEQUENCE';

export type SignalSeverity = 'critical' | 'high' | 'medium' | 'low' | 'info';

export interface BehavioralSignal {
  readonly signal_id: string;
  readonly signal_type: SignalType;
  readonly family?: SignalFamily;
  readonly severity: SignalSeverity;
  /** 0–1 — how confident the engine is in this signal */
  readonly confidence: number;
  readonly expected?: unknown;
  readonly observed?: unknown;
  /** Human-readable explanation of the anomaly */
  readonly explanation: string;
  readonly baseline_source?: string;
  readonly is_source_silence: boolean;
  readonly entity_id: string;
  readonly timestamp?: string;
  // Additional fields present in backend expectations/models.py
  readonly entity_type?: string;
  readonly source_tag?: string;
  readonly population_id?: string;
  readonly window_start?: string;
  readonly window_end?: string;
  readonly metadata?: Record<string, unknown>;
  readonly status?: string;
  readonly created_at?: string;
  readonly updated_at?: string;
  // Intelligence extension — signal sentiment, evidence, and staleness
  readonly sentiment?: 'positive' | 'caution' | 'negative' | 'informational';
  /** Event IDs or metric names that triggered this signal */
  readonly evidence_refs?: string[];
  /** ISO8601 — when this signal was last detected by the engine */
  readonly last_detected?: string;
  /** true when last_detected > 30 days ago; signal may no longer be relevant */
  readonly is_stale?: boolean;
}

export interface WhyExplanation {
  readonly entity_id: string;
  /** Ranked signals explaining anomalous behaviour, highest confidence first */
  readonly top_signals: BehavioralSignal[];
  readonly behavioral_context?: string;
  /** Campaign IDs that may have contributed to the behaviour pattern */
  readonly contributing_campaigns?: string[];
  /** Gaps between what was expected and what was observed */
  readonly expectation_gaps?: string[];
  readonly overall_confidence: number;
  readonly computed_at: string;
}

// ── Attribution "Where" ───────────────────────────────────────────────────────

export type AttributionModel =
  | 'multi_touch'
  | 'first_touch'
  | 'last_touch'
  | 'linear'
  | 'time_decay';

export interface AttributionCredit {
  readonly channel: string;
  readonly source: string;
  readonly campaign_id?: string;
  readonly campaign_name?: string;
  readonly model: AttributionModel;
  /** Fractional credit — all credits in a resolution sum to 1.0 */
  readonly weight: number;
  readonly event_type: string;
  readonly timestamp: string;
  readonly properties?: Record<string, unknown>;
}

export interface AttributionResolution {
  readonly user_id: string;
  readonly model_used: AttributionModel;
  readonly total_credit: number;
  readonly credits: AttributionCredit[];
  readonly resolved_at: string;
}

export interface Touchpoint {
  readonly touchpoint_id?: string;
  readonly channel: string;
  readonly source: string;
  readonly campaign?: string;
  readonly event_type: string;
  readonly timestamp: string;
  readonly properties?: Record<string, unknown>;
}

/** Response from GET /v1/attribution/journey/{user_id} */
export interface AttributionJourney {
  readonly user_id: string;
  readonly touchpoint_count: number;
  readonly touchpoints: Touchpoint[];
}

// ── Web3 Wallet Profile ───────────────────────────────────────────────────────

export type WalletType = 'eoa' | 'contract' | 'multisig' | 'smart_account' | 'unknown';

export interface TokenBalance {
  readonly contract_address?: string;
  readonly symbol: string;
  readonly name: string;
  readonly decimals: number;
  readonly raw_balance: string;
  readonly balance: number;
  readonly value_usd?: number;
  readonly token_type: 'native' | 'erc20' | 'erc721' | 'erc1155';
  readonly chain_id: string;
  readonly logo_url?: string;
  readonly price_usd?: number;
  readonly price_change_24h?: number;
}

export interface OnChainTransaction {
  readonly tx_hash: string;
  readonly chain_id: string;
  readonly block_number: number;
  readonly timestamp: string;
  readonly from_address: string;
  readonly to_address?: string;
  readonly value_eth?: number;
  readonly value_usd?: number;
  readonly gas_used?: number;
  readonly gas_price_gwei?: number;
  readonly method_name?: string;
  readonly protocol_name?: string;
  readonly transaction_type: 'transfer' | 'swap' | 'deposit' | 'withdraw' | 'stake' | 'unstake' | 'vote' | 'approve' | 'mint' | 'burn' | 'other';
  readonly success: boolean;
}

export interface ProtocolInteraction {
  readonly protocol_id: string;
  readonly protocol_name: string;
  readonly category: 'dex' | 'lending' | 'staking' | 'bridge' | 'nft' | 'governance' | 'yield' | 'other';
  readonly chain_id: string;
  readonly first_interaction_at: string;
  readonly last_interaction_at: string;
  readonly interaction_count: number;
  readonly volume_usd?: number;
  readonly current_position_usd?: number;
}

/** Web3 loyalty signals derived from on-chain activity. */
export interface Web3LoyaltySignals {
  readonly wallet_age_days: number;
  readonly total_chains_active: number;
  readonly unique_protocols_used: number;
  readonly is_defi_power_user: boolean;
  readonly governance_participation_rate?: number;
  readonly nft_collector_score?: number;
  /** 0–1 relative score within the user base */
  readonly web3_engagement_score: number;
}

/**
 * Full Web3 wallet profile — returned for each wallet in
 * GET /v1/profile/{userId}/wallets and GET /v1/intelligence/wallet/{addr}/profile.
 */
export interface Web3WalletProfile {
  readonly wallet_address: string;
  readonly chain_id?: string;
  readonly wallet_type: WalletType;
  readonly ens_name?: string;
  readonly labels?: string[];

  /** Token balances across all chains for this wallet. */
  readonly token_balances: TokenBalance[];
  readonly total_portfolio_usd?: number;

  /** Recent on-chain transaction history. */
  readonly recent_transactions: OnChainTransaction[];

  /** Protocol interactions — DEX, lending, staking, governance, etc. */
  readonly protocol_interactions: ProtocolInteraction[];

  /** Web3-specific loyalty and engagement signals. */
  readonly web3_loyalty: Web3LoyaltySignals;

  /** Risk assessment — flagged for mixer usage, exploits, sanctions, etc. */
  readonly risk_score?: number;
  readonly risk_flags?: string[];
  readonly is_sanctioned?: boolean;

  readonly first_transaction_at?: string;
  readonly last_transaction_at?: string;
  readonly total_transactions?: number;
  readonly computed_at: string;
}

// ── Loyalty ───────────────────────────────────────────────────────────────────

export type LoyaltyTier = 'none' | 'bronze' | 'silver' | 'gold' | 'platinum' | 'diamond';

export interface LoyaltyProfile {
  readonly user_id: string;
  readonly tier: LoyaltyTier;
  readonly points_balance: number;
  readonly lifetime_points: number;
  readonly rewards_earned: number;
  readonly rewards_claimed: number;
  readonly campaigns_participated: number;
  readonly campaigns_converted: number;
  readonly lifetime_value_usd?: number;
  readonly first_activity_at?: string;
  readonly last_activity_at?: string;
  readonly next_tier?: LoyaltyTier;
  readonly points_to_next_tier?: number;
}
