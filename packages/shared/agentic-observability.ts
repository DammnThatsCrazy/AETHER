// =============================================================================
// Aether SDK — Agentic Observability Contracts
// Canonical types for observing external agentic activity.
//
// INVARIANT: AETHER observes. AETHER does not execute.
// execution_by_aether must always be false in all observation payloads.
// =============================================================================

// ---------------------------------------------------------------------------
// Provider / source types
// ---------------------------------------------------------------------------

export type AgenticObservationProvider =
  | 'robinhood'
  | 'agentmail'
  | 'x402'
  | 'mcp'
  | 'custom'
  | 'unknown';

export type AgenticActorType = 'human' | 'agent' | 'service' | 'organization';

export type AgenticAutonomyLevel =
  | 'manual'
  | 'assisted'
  | 'semi_autonomous'
  | 'autonomous_observed';

export type AgenticObjectType =
  | 'mcp_connection'
  | 'agentic_account'
  | 'inbox'
  | 'message'
  | 'attachment'
  | 'x402_interaction'
  | 'paid_resource'
  | 'trade_intent'
  | 'trade_order'
  | 'portfolio_snapshot'
  | 'budget'
  | 'tool'
  | 'resource';

export type AgenticActionStatus =
  | 'observed'
  | 'succeeded_observed'
  | 'failed_observed'
  | 'denied_observed'
  | 'unknown';

export type AgenticRiskLevel = 'low' | 'medium' | 'high' | 'critical';

export type AgenticEconomicRail =
  | 'x402'
  | 'brokerage'
  | 'card'
  | 'wallet'
  | 'internal'
  | 'unknown';

// ---------------------------------------------------------------------------
// Canonical observation envelope
// ---------------------------------------------------------------------------

/**
 * Canonical envelope for all agentic observability events.
 * Every field except event_id, tenant_id, observed_at, received_at,
 * source, actor, object, action, and provenance is optional.
 *
 * CRITICAL: economics.is_execution_by_aether must ALWAYS be false.
 * Any payload with is_execution_by_aether=true will be rejected by the
 * observability routes with HTTP 422.
 */
export type AgenticObservationEvent = {
  event_id: string;
  event_name: AgenticObservabilityEventType;
  tenant_id: string;
  observed_at: string;
  received_at: string;

  source: {
    provider: AgenticObservationProvider;
    provider_event_id?: string;
    integration_id?: string;
    webhook_id?: string;
    sdk_name?: string;
    sdk_version?: string;
  };

  actor: {
    actor_type: AgenticActorType;
    actor_id?: string;
    external_actor_id?: string;
  };

  agent?: {
    agent_id?: string;
    external_agent_id?: string;
    model?: string;
    framework?: string;
    autonomy_level?: AgenticAutonomyLevel;
  };

  object: {
    object_type: AgenticObjectType;
    object_id?: string;
    external_object_id?: string;
  };

  action: {
    name: string;
    status: AgenticActionStatus;
    intent?: string;
    outcome?: string;
  };

  economics?: {
    amount?: number;
    currency?: string;
    asset?: string;
    network?: string;
    rail?: AgenticEconomicRail;
    direction?: 'inbound' | 'outbound' | 'unknown';
    /** Always false. AETHER never originates economic actions. */
    is_execution_by_aether: false;
  };

  risk?: {
    risk_level?: AgenticRiskLevel;
    reason_codes?: string[];
    policy_flags?: string[];
    requires_review?: boolean;
  };

  provenance: {
    raw_event_hash: string;
    raw_payload_ref?: string;
    normalized_by: string;
    schema_version: string;
  };
};

// ---------------------------------------------------------------------------
// Agentic observability event type literals
// ---------------------------------------------------------------------------

/** All canonical event names for the agentic observability families. */
export type AgenticObservabilityEventType =
  // Agentic account / MCP
  | 'agentic_account_observed'
  | 'agentic_account_connected_observed'
  | 'agentic_account_disconnected_observed'
  | 'agent_budget_observed'
  | 'agent_budget_changed_observed'
  | 'agent_permission_observed'
  | 'agent_mcp_connection_observed'
  | 'agent_tool_observed'
  | 'agent_tool_invocation_observed'
  | 'agent_activity_observed'
  | 'agent_risk_signal_observed'
  | 'agent_notification_observed'
  // Robinhood-style trading observation
  | 'agent_strategy_observed'
  | 'agent_trade_intent_observed'
  | 'agent_trade_order_observed'
  | 'agent_trade_fill_observed'
  | 'agent_trade_rejection_observed'
  | 'agent_position_observed'
  | 'agent_portfolio_snapshot_observed'
  | 'agent_performance_snapshot_observed'
  | 'agent_disconnect_observed'
  // AgentMail-style communication observation
  | 'agent_inbox_observed'
  | 'agent_email_address_observed'
  | 'agent_thread_observed'
  | 'agent_message_received_observed'
  | 'agent_message_sent_observed'
  | 'agent_reply_observed'
  | 'agent_attachment_observed'
  | 'agent_attachment_parsed_observed'
  | 'agent_otp_detected_observed'
  | 'agent_invoice_detected_observed'
  | 'agent_receipt_detected_observed'
  | 'agent_calendar_intent_observed'
  | 'agent_support_route_observed'
  | 'agent_semantic_search_observed'
  | 'agent_data_extraction_observed'
  // x402 protocol observation
  | 'x402_resource_request_observed'
  | 'x402_challenge_observed'
  | 'x402_payment_requirement_observed'
  | 'x402_signature_observed'
  | 'x402_verification_observed'
  | 'x402_settlement_observed'
  | 'x402_resource_access_observed'
  | 'x402_resource_access_denied_observed'
  | 'x402_failure_observed'
  | 'x402_replay_risk_observed'
  | 'x402_provider_observed';

// ---------------------------------------------------------------------------
// x402 observation-specific types
// ---------------------------------------------------------------------------

export type X402InteractionObserved = {
  interaction_id: string;
  tenant_id: string;
  agent_id?: string;
  resource_url: string;
  provider: string;
  observed_at: string;
  execution_by_aether: false;
};

export type X402ChallengeObserved = {
  challenge_id: string;
  interaction_id: string;
  http_status: 402;
  amount_usd?: number;
  asset?: string;
  network?: string;
  recipient?: string;
  schema_version?: string;
  observed_at: string;
  tenant_id: string;
};

export type X402SettlementObserved = {
  settlement_id: string;
  interaction_id: string;
  tx_hash?: string;
  settled_at: string;
  /** Always true — settlement was executed by an external party, not AETHER */
  settlement_by_external: true;
  /** Always false — AETHER never executes settlement */
  execution_by_aether: false;
  tenant_id: string;
};

// ---------------------------------------------------------------------------
// Trade observation-specific types
// ---------------------------------------------------------------------------

export type TradeIntentObserved = {
  intent_id: string;
  brokerage_id: string;
  strategy_id?: string;
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  price_type: 'market' | 'limit' | 'stop';
  /** Always true — intent submitted to external broker, not AETHER */
  submitted_externally: true;
  /** Always false */
  execution_by_aether: false;
  tenant_id: string;
  observed_at: string;
};

export type TradeOrderObserved = {
  order_id: string;
  intent_id?: string;
  external_order_id?: string;
  status: 'pending' | 'filled' | 'partial' | 'rejected' | 'cancelled';
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  filled_qty?: number;
  avg_price?: number;
  /** Always true */
  executed_externally: true;
  /** Always false */
  execution_by_aether: false;
  tenant_id: string;
  observed_at: string;
};

// ---------------------------------------------------------------------------
// Agent communication observation types
// ---------------------------------------------------------------------------

export type AgentMessageObserved = {
  message_id: string;
  thread_id?: string;
  inbox_id?: string;
  direction: 'inbound' | 'outbound';
  from_address?: string;
  to_addresses?: string[];
  subject?: string;
  has_attachments: boolean;
  tenant_id: string;
  observed_at: string;
};

export type ExtractedEntityObserved = {
  entity_id: string;
  message_id?: string;
  attachment_id?: string;
  entity_type:
    | 'otp'
    | 'invoice'
    | 'receipt'
    | 'calendar_intent'
    | 'support_case'
    | 'payment_reference'
    | 'amount'
    | 'other';
  confidence?: number;
  tenant_id: string;
  observed_at: string;
};
