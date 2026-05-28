// =============================================================================
// Aether SDK — Graph & Relationship Contracts
// Covers every actor-to-actor interaction class: H2H, H2A, A2H, A2A.
// Models entities, relationships, delegation chains, financial flows,
// and the "collective tissue" that connects clusters of entities.
// =============================================================================

import type {
  SessionSummary, DeviceSummary, PlatformSummary,
  FrequencyMetrics, TemporalPattern, BehavioralSignal, WhyExplanation,
  LoyaltyProfile, UserJourney, AttributionResolution,
} from './contextual';

// ── Actor taxonomy ────────────────────────────────────────────────────────────

/** High-level actor class — drives interaction-class labels. */
export type ActorClass = 'H' | 'A' | 'S'; // Human | Agent | System

/**
 * Granular entity kinds within the graph.
 *
 * Unified across Web2 and Web3 — the graph does not distinguish
 * by domain. Functional categories cover both:
 *   governance_org = DAO or NGO or government body
 *   exchange       = DEX or CEX or stock exchange
 *   yield_platform = staking protocol or savings account
 *   brand          = startup or enterprise or product
 *   marketplace    = DeFi app or Shopify or Amazon Seller
 *   media_entity   = influencer or publisher or media outlet
 */
export type GraphNodeKind =
  | 'human'             // natural person
  | 'agent'             // AI / autonomous agent
  | 'organization'      // generic legal entity / company (use specific kinds below when known)
  | 'device'            // physical or virtual device
  | 'wallet'            // blockchain wallet address
  | 'session'           // browser/app session node
  | 'contract'          // smart contract
  | 'protocol'          // DeFi / Web3 protocol
  | 'bot'               // scripted, non-AI bot
  // ── Unified entity categories (Web2 + Web3) ──────────────────────────
  | 'governance_org'    // DAO, NGO, cooperative, government body, trade association
  | 'exchange'          // DEX, CEX, stock exchange, forex platform
  | 'yield_platform'    // staking protocol, savings account, yield aggregator, robo-advisor
  | 'brand'             // company, product brand, SaaS, startup
  | 'marketplace'       // e-commerce platform, app store, gig platform
  | 'media_entity'      // publisher, content creator, influencer, media outlet
  // ── Legacy aliases (kept for backward compatibility) ──────────────────
  | 'dao'               // → governance_org
  | 'dex'               // → exchange
  | 'staking_platform'  // → yield_platform
  | 'business'          // → brand
  | 'unknown';

/**
 * Interaction class label for any directed edge.
 * Derived from the actor classes of source and target:
 *   H2H — person ↔ person  (referrals, commerce, trust)
 *   H2A — person → agent   (delegation, hiring, configuration)
 *   A2H — agent → person   (notifications, purchases on behalf, reports)
 *   A2A — agent ↔ agent    (sub-delegation, pipelines, A2A payments)
 *   H2S / A2S               — actor → system (write events, config changes)
 */
export type InteractionClass = 'H2H' | 'H2A' | 'A2H' | 'A2A' | 'H2S' | 'A2S';

// ── Relationship types ────────────────────────────────────────────────────────

export type RelationType =
  // Ownership / control
  | 'owns'                   // H owns A (agent or wallet)
  | 'managed_by'             // A managed_by H (H supervises A)
  | 'operates_for'           // A operates on behalf of H
  // Delegation
  | 'delegates_to'           // H→A or H→H — grants scoped authority
  | 'delegates_vote_to'      // governance vote delegation
  // Commerce
  | 'buys_from'              // purchase flow (Web2 or Web3)
  | 'sells_to'               // reverse purchase
  | 'subscribes_to'          // recurring access / subscription
  | 'hires'                  // H or org hires an A (agent marketplace)
  // Financial flows
  | 'transfers_to'           // token or fiat transfer
  | 'provides_liquidity_to'  // AMM / pool contribution
  | 'borrows_from'           // lending / credit
  // Social / trust
  | 'refers'                 // referral attribution
  | 'follows'                // social graph link
  | 'partners_with'          // B2B / co-marketing
  // Identity links (may be inferred)
  | 'shares_device'          // probabilistic — same device fingerprint
  | 'shares_wallet'          // same wallet address across contexts
  | 'same_person'            // resolved identity merge
  | 'co_located'             // same IP / network segment
  // Human → Onchain Entity
  | 'trades_on'              // swap events on DEX / protocol
  | 'governs'                // DAO governance vote cast
  | 'stakes_in'              // staking / restaking deposit
  | 'deploys_contract'       // wallet is tx_from on contract creation
  | 'uses_bridge'            // bridge cross-chain event
  // Human → Business
  | 'employee_of'            // HR / LinkedIn / manual
  | 'founder_of'             // incorporation filing or self-reported
  | 'customer_of'            // Stripe payment or subscription record
  | 'investor_in'            // token purchase from project wallet / Crunchbase
  | 'contractor_for'         // delegation record with time-bounded scope
  // Human/Business → Agent
  | 'owns_agent'             // entity directly owns/controls an agent
  | 'deploys_agent'          // first deployment transaction
  | 'authorizes_agent'       // delegation record with agent scope
  | 'agent_acts_on_behalf_of' // inverse: agent → human/business
  // Human → Human
  | 'co_invests_with'        // shared LP or co-investment in same vehicle
  | 'shared_wallet_cluster'  // identity cluster match
  | 'social_follows'         // any social platform follow
  | 'same_bundle'            // wallet bundle via identity resolution
  // Entity → Channel / Platform (Web2-native)
  | 'listed_on'              // product or brand listed on marketplace/exchange
  | 'distributes_via'        // content/product distributed through a channel
  | 'content_on'             // entity has channel/page on platform
  | 'competes_with'          // competitive relationship between brands/entities
  | 'reviews'                // entity reviews / rates another entity
  | 'sells_on'               // brand sells through marketplace
  | 'operates_channel'       // brand operates media channel or social page
  // Org → People (Web2 employment / org chart)
  | 'employs'                // org → human (employment relationship)
  | 'advises';               // advisor relationship

// ── Relationship edge ─────────────────────────────────────────────────────────

export interface RelationshipEdge {
  readonly edge_id: string;
  readonly from_entity_id: string;
  readonly from_kind: GraphNodeKind;
  readonly to_entity_id: string;
  readonly to_kind: GraphNodeKind;
  readonly relation_type: RelationType;
  readonly interaction_class: InteractionClass;
  /** Relationship strength 0–1 */
  readonly weight: number;
  /** System confidence 0–1 — lower for inferred / probabilistic links */
  readonly confidence: number;
  readonly is_inferred: boolean;
  readonly started_at?: string;
  readonly ended_at?: string;
  /** Cumulative USD value of flows on this edge */
  readonly volume_usd?: number;
  readonly event_count?: number;
  readonly properties?: Record<string, unknown>;
}

// ── Delegation ────────────────────────────────────────────────────────────────

export interface DelegationRecord {
  readonly delegation_id: string;
  readonly grantor_entity_id: string;
  readonly grantor_kind?: GraphNodeKind;
  readonly grantee_entity_id: string;
  readonly grantee_kind?: GraphNodeKind;
  readonly scope: string[];
  readonly starts_at: string;
  readonly ends_at?: string;
  readonly is_active: boolean;
  readonly max_amount_usd?: number;
}

/** A chain of delegations e.g. H → A1 → A2 — exposes the full trust path. */
export interface DelegationChain {
  readonly chain_id: string;
  readonly root_grantor_id: string;
  readonly ultimate_grantee_id: string;
  /** Number of hops (depth 1 = direct grant, depth 2 = via one intermediary, …) */
  readonly depth: number;
  readonly links: DelegationRecord[];
  /** Intersection of all scopes along the chain */
  readonly effective_scope: string[];
}

// ── Identifier set ────────────────────────────────────────────────────────────

export interface IdentifierSet {
  readonly wallets: string[];
  readonly emails: string[];
  readonly devices: string[];
  readonly sessions: string[];
  readonly social_handles: string[];
  readonly customer_ids: string[];
}

// ── Flow summary ──────────────────────────────────────────────────────────────

export interface FlowSummary {
  readonly total_inflow_usd?: number;
  readonly total_outflow_usd?: number;
  readonly net_flow_usd?: number;
  readonly transaction_count: number;
  readonly dominant_direction?: 'inbound' | 'outbound' | 'bilateral';
  readonly top_assets?: string[];
  readonly flow_edges: RelationshipEdge[];
}

// ── Entity profile (any graph node) ──────────────────────────────────────────

/**
 * Unified profile for any graph entity — human, agent, org, wallet, etc.
 * Returned by GET /v1/profile/{id}/summary and profile360 full surface.
 * All behavioural, temporal, loyalty and graph dimensions are co-located
 * here so the UI never needs to stitch multiple responses manually.
 */
export interface EntityProfile {
  readonly entity_id: string;
  readonly kind: GraphNodeKind;
  readonly actor_class?: ActorClass;
  readonly display_name?: string;
  readonly created_at?: string;

  // ── Identity ──
  readonly identifiers: IdentifierSet;

  // ── Context (session / device / platform) ──
  readonly recent_sessions?: SessionSummary[];
  readonly devices?: DeviceSummary[];
  readonly platforms?: PlatformSummary[];

  // ── Temporal & frequency ──
  readonly frequency?: FrequencyMetrics;
  readonly temporal?: TemporalPattern;

  // ── Behaviour & "Why" ──
  readonly behavioral_signals?: BehavioralSignal[];
  readonly why_explanation?: WhyExplanation;

  // ── Loyalty & journeys ──
  readonly loyalty?: LoyaltyProfile;
  readonly journeys?: UserJourney[];

  // ── Attribution "Where" ──
  readonly attribution?: AttributionResolution;

  // ── Intelligence scores ──
  readonly trust_score?: number;
  readonly risk_score?: number;
  readonly anomaly_score?: number;

  // ── Graph relationships ──
  readonly outbound_edges: RelationshipEdge[];
  readonly inbound_edges: RelationshipEdge[];

  // ── Delegation ──
  readonly delegations_granted: DelegationRecord[];
  readonly delegations_received: DelegationRecord[];

  readonly computed_at: string;
}

// ── Cluster ───────────────────────────────────────────────────────────────────

export interface ClusterMember {
  readonly entity_id: string;
  readonly kind: GraphNodeKind;
  readonly actor_class?: ActorClass;
  readonly display_name?: string;
  /** How strongly this member is bound to the cluster 0–1 */
  readonly membership_confidence: number;
  readonly link_types: RelationType[];
  readonly trust_score?: number;
  readonly risk_score?: number;
}

/**
 * A cluster of entities connected by shared identifiers, behaviours, or flows.
 * Returned by GET /v1/intelligence/entity/{id}/cluster
 * and GET /v1/resolution/cluster/{id}.
 */
export interface EntityCluster {
  readonly cluster_id: string;
  readonly members: ClusterMember[];
  readonly cluster_size: number;

  // ── Shared tissue — what links these entities together ──
  readonly shared_identifiers: IdentifierSet;
  readonly shared_devices: string[];
  readonly shared_ips: string[];
  readonly shared_campaigns: string[];
  /** Pairwise behavioural similarity score 0–1 */
  readonly behavioral_similarity: number;

  // ── Aggregate intelligence ──
  readonly aggregate_trust_score?: number;
  readonly aggregate_risk_score?: number;
  readonly dominant_actor_class?: ActorClass;

  // ── Formation ──
  /** Signal names that caused the cluster to form (e.g. 'shared_wallet', 'same_ip') */
  readonly formation_signals: string[];
  readonly confidence: number;
  readonly computed_at: string;
}

// ── Collective tissue ─────────────────────────────────────────────────────────

/**
 * The shared tissue between an arbitrary set of entity IDs.
 * Surfaces what connects a group: shared identifiers, campaign touch,
 * behavioural patterns, delegation chains, and net financial flows.
 */
export interface CollectiveTissue {
  readonly entity_ids: string[];
  readonly shared_identifiers: IdentifierSet;
  readonly shared_campaigns: string[];
  readonly shared_behavioral_patterns: string[];
  readonly interaction_edges: RelationshipEdge[];
  readonly delegation_chains: DelegationChain[];
  readonly flow_summary: FlowSummary;
  readonly computed_at: string;
}

// ── Graph snapshot ────────────────────────────────────────────────────────────

export interface GraphEntityNode {
  readonly entity_id: string;
  readonly kind: GraphNodeKind;
  readonly actor_class?: ActorClass;
  readonly display_name?: string;
  readonly trust_score?: number;
  readonly risk_score?: number;
  readonly cluster_id?: string;
  readonly inbound_count: number;
  readonly outbound_count: number;
}

/**
 * Full graph snapshot rooted at an entity or cluster.
 * Returned by GET /v1/entities/{id}/graph and profile360 graph surface.
 */
export interface EntityGraph {
  readonly root_entity_id?: string;
  readonly cluster_id?: string;
  readonly nodes: GraphEntityNode[];
  readonly edges: RelationshipEdge[];
  readonly clusters: EntityCluster[];
  readonly computed_at: string;
}

// ── Relationship summary (per-entity view) ────────────────────────────────────

export interface RelationshipSummary {
  readonly entity_id: string;
  readonly total_edges: number;
  readonly by_interaction_class: Record<InteractionClass, number>;
  readonly by_relation_type: Partial<Record<RelationType, number>>;
  readonly key_counterparties: Array<{
    readonly entity_id: string;
    readonly kind: GraphNodeKind;
    readonly relation_type: RelationType;
    readonly weight: number;
  }>;
  readonly delegation_depth: number;
  readonly computed_at: string;
}
