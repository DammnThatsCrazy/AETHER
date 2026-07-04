// =============================================================================
// Aether SDK — Shared Entity Model
// Canonical entities the SDK may reference. Mirrors backend VertexType enum
// in Backend Architecture/aether-backend/shared/graph/graph.py.
// See docs/source-of-truth/ENTITY_MODEL.md.
//
// Design principle: entity kinds are domain-agnostic. The same kind covers
// Web2 and Web3 equivalents — we are intelligence graph infrastructure, not
// a domain-specific analytics platform.
// =============================================================================

/**
 * Every canonical entity ref is { kind, id } — SDKs never construct full nodes.
 *
 * Unified kind mapping (Web2 ↔ Web3 equivalents share a kind):
 *   governance_org  → DAO, NGO, cooperative, government body, trade association
 *   exchange        → DEX, CEX, stock exchange, forex platform, crypto exchange
 *   yield_platform  → staking protocol, savings account, yield aggregator, robo-advisor
 *   brand           → registered company, product brand, SaaS business, LLC, startup
 *   marketplace     → e-commerce platform, app store, gig platform, online market
 *   media_entity    → publisher, content creator, influencer account, media outlet
 */
export type EntityKind =
  // Core (always present)
  | 'tenant'
  | 'org'
  | 'user'
  | 'session'
  | 'device'
  | 'application'
  // Access plane
  | 'resource'
  | 'approval'
  | 'entitlement'
  // Commerce plane
  | 'payment'
  | 'invoice'
  | 'subscription'
  | 'plan'
  // ── Unified entity categories (Web2 + Web3, domain-agnostic) ──────────
  | 'governance_org'    // DAO, NGO, cooperative, government body, trade association
  | 'exchange'          // DEX, CEX, stock exchange, forex platform
  | 'yield_platform'    // staking protocol, savings account, yield aggregator, robo-advisor
  | 'brand'             // company, product brand, SaaS business, startup, LLC
  | 'marketplace'       // e-commerce platform, app store, online market, gig platform
  | 'media_entity'      // publisher, content creator, influencer, media outlet
  // ── Blockchain-specific (additive) ────────────────────────────────────
  | 'wallet'
  | 'contract'
  | 'chain'
  | 'token'
  | 'protocol'
  // ── Agent plane ────────────────────────────────────────────────────────
  | 'agent'
  | 'service'
  // ── Economic graph layer ───────────────────────────────────────────────
  | 'payment_intent'
  | 'settlement_event'
  | 'economic_resource'
  | 'facilitator'
  | 'agent_economic_identity'
  | 'agent_profile360'
  // ── Intelligence & computed nodes ──────────────────────────────────────
  | 'tier_group'
  | 'retarget_recommendation'
  | 'ad_campaign'
  | 'social_profile'
  | 'credit_profile'
  | 'plaid_account'
  | 'tradfi_position'
  // ── Derivatives Intelligence bounded-domain references (PR1 foundation) ──
  | 'trading_venue'
  | 'venue_deployment'
  | 'derivative_instrument'
  | 'derivative_market'
  | 'market_index'
  | 'trading_account'
  | 'trading_subaccount'
  | 'trading_vault'
  | 'derivatives_order'
  | 'derivatives_fill'
  | 'derivatives_position'
  | 'position_epoch'
  | 'collateral_account'
  | 'margin_snapshot'
  | 'funding_payment'
  | 'trading_fee'
  | 'liquidation_event'
  | 'price_observation'
  | 'risk_policy'
  | 'trading_strategy'
  | 'strategy_version'
  | 'execution_decision'
  | 'reconciliation_variance'
  | 'connector_checkpoint'
  | 'venue_credential_reference'
  // ── Legacy aliases (kept for backward compatibility) ───────────────────
  | 'dao'               // → governance_org
  | 'dex'               // → exchange
  | 'staking_platform'  // → yield_platform
  | 'business';         // → brand

/** Lightweight reference emitted in event properties. */
export interface EntityRef {
  kind: EntityKind;
  id: string;
  /** Optional human label (SDK may leave blank; backend enriches). */
  label?: string;
}
