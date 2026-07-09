// =============================================================================
// Aether SDK — Shared Event Envelope & Registry
// Canonical shapes every SDK emits and every ingestion validator accepts.
// See docs/source-of-truth/EVENT_REGISTRY.md and INGESTION_CONTRACT.md.
// =============================================================================

import type { ConsentState } from './consent';
import type { ActorKind, Provenance } from './provenance';

// @generated-start
// @generated — DO NOT EDIT. Source: packages/shared/contracts/event-registry.json
// Contract version: 8.12.0 — Run: python scripts/generate_contracts.py

/** The canonical event-type string union the backend validates. */
export type EventType =
  // core
  | 'track'
  | 'page'
  | 'screen'
  | 'heartbeat'
  | 'error'
  | 'performance'
  | 'experiment'
  // journey
  | 'journey_started'
  | 'journey_paused'
  | 'journey_resumed'
  | 'journey_continued'
  | 'journey_completed'
  | 'journey_abandoned'
  | 'journey_checkpoint'
  // identity
  | 'identify'
  // consent
  | 'consent'
  // commerce
  | 'conversion'
  | 'payment_initiated'
  | 'payment_completed'
  | 'payment_failed'
  | 'approval_requested'
  | 'approval_resolved'
  | 'entitlement_granted'
  | 'entitlement_revoked'
  | 'access_granted'
  | 'access_denied'
  // wallet
  | 'wallet'
  | 'transaction'
  | 'contract_action'
  // agent
  | 'agent_task'
  | 'agent_decision'
  | 'a2h_interaction'
  | 'agent_registered'
  | 'agent_updated'
  | 'agent_authorized'
  | 'agent_deauthorized'
  | 'agent_capability_granted'
  | 'agent_capability_revoked'
  | 'agent_task_created'
  | 'agent_task_decomposed'
  | 'agent_task_started'
  | 'agent_task_completed'
  | 'agent_task_failed'
  | 'agent_tool_called'
  | 'agent_resource_requested'
  | 'agent_delegated_task'
  | 'agent_subagent_spawned'
  | 'agent_policy_evaluated'
  | 'agent_handoff'
  | 'agent_escalated_to_human'
  | 'agent_outcome_recorded'
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
  | 'agent_strategy_observed'
  | 'agent_trade_intent_observed'
  | 'agent_trade_order_observed'
  | 'agent_trade_fill_observed'
  | 'agent_trade_rejection_observed'
  | 'agent_position_observed'
  | 'agent_portfolio_snapshot_observed'
  | 'agent_performance_snapshot_observed'
  | 'agent_disconnect_observed'
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
  | 'agent_evaluation_observed'
  | 'agent_cost_observed'
  | 'ai_invocation_observed'
  | 'agent_grounding_observed'
  | 'agent_guardrail_observed'
  | 'agent_human_override_observed'
  // reward
  | 'reward_action_queued'
  | 'reward_proof_generated'
  | 'reward_delivered'
  | 'reward_claim_submitted'
  // x402
  | 'x402_payment'
  | 'x402_resource_requested'
  | 'x402_payment_required'
  | 'x402_quote_received'
  | 'x402_authorization_requested'
  | 'x402_authorization_resolved'
  | 'x402_payment_intent_created'
  | 'x402_payment_submitted'
  | 'x402_payment_settled'
  | 'x402_payment_failed'
  | 'x402_payment_timeout'
  | 'x402_receipt_verified'
  | 'x402_access_granted'
  | 'x402_access_denied'
  | 'x402_refund_or_reversal'
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
  | 'x402_provider_observed'
  // exposure
  | 'content_impression'
  | 'recommendation_exposed'
  | 'offer_exposed'
  | 'feature_exposed'
  | 'search_result_exposed'
  | 'ad_exposed'
  | 'notification_presented'
  | 'decision_observed'
  // outcome
  | 'outcome_observed'
  | 'goal_achieved'
  | 'goal_failed'
  | 'recommendation_accepted'
  | 'recommendation_rejected'
  | 'feedback_submitted'
  | 'retention_observed'
  | 'churn_observed'
  | 'human_override_observed'
  // b2b
  | 'organization_observed'
  | 'workspace_created'
  | 'workspace_updated'
  | 'member_invited'
  | 'member_joined'
  | 'member_removed'
  | 'role_changed'
  | 'seat_assigned'
  | 'seat_released'
  | 'integration_connected'
  | 'integration_disconnected'
  | 'service_account_created'
  | 'service_account_revoked'
  | 'api_key_created'
  | 'api_key_revoked'
  | 'project_created'
  | 'project_archived'
  | 'workflow_started'
  | 'workflow_completed'
  | 'workflow_failed'
  // ecommerce
  | 'product_viewed'
  | 'cart_item_added'
  | 'cart_item_removed'
  | 'cart_updated'
  | 'coupon_applied'
  | 'checkout_started'
  | 'checkout_step_completed'
  | 'order_completed'
  | 'order_cancelled'
  | 'order_refunded'
  | 'chargeback_observed'
  | 'subscription_started'
  | 'trial_started'
  | 'trial_converted'
  | 'subscription_renewed'
  | 'subscription_upgrade_observed'
  | 'subscription_downgrade_observed'
  | 'subscription_cancelled'
  | 'invoice_issued'
  | 'invoice_paid'
  | 'invoice_failed'
  | 'dunning_started'
  | 'dunning_resolved'
  // friction
  | 'dead_click_observed'
  | 'rage_click_observed'
  | 'scroll_depth_observed'
  | 'form_started'
  | 'form_field_interaction'
  | 'form_validation_failed'
  | 'form_submitted'
  | 'form_abandoned'
  | 'search_reformulated'
  | 'retry_observed'
  | 'journey_stalled'
  | 'backtrack_observed'
  // server
  | 'api_request_observed'
  | 'webhook_delivery_observed'
  | 'connector_sync_started'
  | 'connector_sync_completed'
  | 'connector_sync_failed'
  | 'job_started'
  | 'job_completed'
  | 'job_failed'
  | 'rate_limit_observed'
  | 'dependency_failure_observed'
  | 'export_completed'
  // identity_lc
  | 'signup_started'
  | 'signup_completed'
  | 'login_succeeded'
  | 'login_failed'
  | 'logout_observed'
  | 'sso_observed'
  | 'mfa_challenge_observed'
  | 'identity_verified'
  | 'alias_link_requested'
  | 'alias_link_confirmed'
  | 'alias_revoked'
  | 'account_recovery_started'
  | 'account_recovery_completed'
  | 'device_registered'
  | 'device_revoked'
  // web3_lc
  | 'transaction_pending_observed'
  | 'transaction_confirmed_observed'
  | 'transaction_reverted_observed'
  | 'transaction_reorged_observed'
  | 'token_approval_observed'
  | 'allowance_changed_observed'
  | 'bridge_transfer_observed'
  | 'settlement_finality_observed'
  // comms
  | 'notification_delivered'
  | 'notification_opened'
  | 'notification_clicked'
  | 'email_delivered'
  | 'email_opened'
  | 'email_clicked'
  | 'email_bounced'
  | 'email_queued'
  | 'email_processed'
  | 'email_sent'
  | 'email_deferred'
  | 'email_dropped'
  | 'email_replied'
  | 'email_spam_complaint'
  | 'email_suppressed'
  | 'message_received_observed'
  | 'message_sent_observed'
  | 'message_replied_observed'
  | 'unsubscribe_observed'
  | 'support_case_created'
  | 'support_case_resolved'
  | 'support_case_escalated'
  | 'support_sla_breached'
  // credit
  | 'credit_signal_observed'
  | 'credit_account_observed'
  | 'credit_decision_observed'
  // location
  | 'location_observed'
  | 'geofence_transition_observed'
  // derivatives
  | 'trading_account_connected'
  | 'trading_account_disconnected'
  | 'trading_account_authorized'
  | 'trading_account_deauthorized'
  | 'trading_agent_enabled'
  | 'trading_agent_disabled'
  | 'trade_intent_created'
  | 'trade_approval_requested'
  | 'trade_approval_resolved'
  | 'risk_policy_updated'
  | 'human_trade_override_recorded'
  ;

export type EventFamily =
  | 'agent'
  | 'b2b'
  | 'commerce'
  | 'comms'
  | 'consent'
  | 'core'
  | 'credit'
  | 'derivatives'
  | 'ecommerce'
  | 'exposure'
  | 'friction'
  | 'identity'
  | 'identity_lc'
  | 'journey'
  | 'location'
  | 'outcome'
  | 'reward'
  | 'server'
  | 'wallet'
  | 'web3_lc'
  | 'x402'
  ;

/** Map from each event type to its family. */
export const EVENT_FAMILY: Record<EventType, EventFamily> = {
  track: 'core',
  page: 'core',
  screen: 'core',
  heartbeat: 'core',
  error: 'core',
  performance: 'core',
  experiment: 'core',
  journey_started: 'journey',
  journey_paused: 'journey',
  journey_resumed: 'journey',
  journey_continued: 'journey',
  journey_completed: 'journey',
  journey_abandoned: 'journey',
  journey_checkpoint: 'journey',
  identify: 'identity',
  consent: 'consent',
  conversion: 'commerce',
  payment_initiated: 'commerce',
  payment_completed: 'commerce',
  payment_failed: 'commerce',
  approval_requested: 'commerce',
  approval_resolved: 'commerce',
  entitlement_granted: 'commerce',
  entitlement_revoked: 'commerce',
  access_granted: 'commerce',
  access_denied: 'commerce',
  wallet: 'wallet',
  transaction: 'wallet',
  contract_action: 'wallet',
  agent_task: 'agent',
  agent_decision: 'agent',
  a2h_interaction: 'agent',
  agent_registered: 'agent',
  agent_updated: 'agent',
  agent_authorized: 'agent',
  agent_deauthorized: 'agent',
  agent_capability_granted: 'agent',
  agent_capability_revoked: 'agent',
  agent_task_created: 'agent',
  agent_task_decomposed: 'agent',
  agent_task_started: 'agent',
  agent_task_completed: 'agent',
  agent_task_failed: 'agent',
  agent_tool_called: 'agent',
  agent_resource_requested: 'agent',
  agent_delegated_task: 'agent',
  agent_subagent_spawned: 'agent',
  agent_policy_evaluated: 'agent',
  agent_handoff: 'agent',
  agent_escalated_to_human: 'agent',
  agent_outcome_recorded: 'agent',
  reward_action_queued: 'reward',
  reward_proof_generated: 'reward',
  reward_delivered: 'reward',
  reward_claim_submitted: 'reward',
  x402_payment: 'x402',
  x402_resource_requested: 'x402',
  x402_payment_required: 'x402',
  x402_quote_received: 'x402',
  x402_authorization_requested: 'x402',
  x402_authorization_resolved: 'x402',
  x402_payment_intent_created: 'x402',
  x402_payment_submitted: 'x402',
  x402_payment_settled: 'x402',
  x402_payment_failed: 'x402',
  x402_payment_timeout: 'x402',
  x402_receipt_verified: 'x402',
  x402_access_granted: 'x402',
  x402_access_denied: 'x402',
  x402_refund_or_reversal: 'x402',
  agentic_account_observed: 'agent',
  agentic_account_connected_observed: 'agent',
  agentic_account_disconnected_observed: 'agent',
  agent_budget_observed: 'agent',
  agent_budget_changed_observed: 'agent',
  agent_permission_observed: 'agent',
  agent_mcp_connection_observed: 'agent',
  agent_tool_observed: 'agent',
  agent_tool_invocation_observed: 'agent',
  agent_activity_observed: 'agent',
  agent_risk_signal_observed: 'agent',
  agent_notification_observed: 'agent',
  agent_strategy_observed: 'agent',
  agent_trade_intent_observed: 'agent',
  agent_trade_order_observed: 'agent',
  agent_trade_fill_observed: 'agent',
  agent_trade_rejection_observed: 'agent',
  agent_position_observed: 'agent',
  agent_portfolio_snapshot_observed: 'agent',
  agent_performance_snapshot_observed: 'agent',
  agent_disconnect_observed: 'agent',
  agent_inbox_observed: 'agent',
  agent_email_address_observed: 'agent',
  agent_thread_observed: 'agent',
  agent_message_received_observed: 'agent',
  agent_message_sent_observed: 'agent',
  agent_reply_observed: 'agent',
  agent_attachment_observed: 'agent',
  agent_attachment_parsed_observed: 'agent',
  agent_otp_detected_observed: 'agent',
  agent_invoice_detected_observed: 'agent',
  agent_receipt_detected_observed: 'agent',
  agent_calendar_intent_observed: 'agent',
  agent_support_route_observed: 'agent',
  agent_semantic_search_observed: 'agent',
  agent_data_extraction_observed: 'agent',
  x402_resource_request_observed: 'x402',
  x402_challenge_observed: 'x402',
  x402_payment_requirement_observed: 'x402',
  x402_signature_observed: 'x402',
  x402_verification_observed: 'x402',
  x402_settlement_observed: 'x402',
  x402_resource_access_observed: 'x402',
  x402_resource_access_denied_observed: 'x402',
  x402_failure_observed: 'x402',
  x402_replay_risk_observed: 'x402',
  x402_provider_observed: 'x402',
  content_impression: 'exposure',
  recommendation_exposed: 'exposure',
  offer_exposed: 'exposure',
  feature_exposed: 'exposure',
  search_result_exposed: 'exposure',
  ad_exposed: 'exposure',
  notification_presented: 'exposure',
  decision_observed: 'exposure',
  outcome_observed: 'outcome',
  goal_achieved: 'outcome',
  goal_failed: 'outcome',
  recommendation_accepted: 'outcome',
  recommendation_rejected: 'outcome',
  feedback_submitted: 'outcome',
  retention_observed: 'outcome',
  churn_observed: 'outcome',
  human_override_observed: 'outcome',
  organization_observed: 'b2b',
  workspace_created: 'b2b',
  workspace_updated: 'b2b',
  member_invited: 'b2b',
  member_joined: 'b2b',
  member_removed: 'b2b',
  role_changed: 'b2b',
  seat_assigned: 'b2b',
  seat_released: 'b2b',
  integration_connected: 'b2b',
  integration_disconnected: 'b2b',
  service_account_created: 'b2b',
  service_account_revoked: 'b2b',
  api_key_created: 'b2b',
  api_key_revoked: 'b2b',
  project_created: 'b2b',
  project_archived: 'b2b',
  workflow_started: 'b2b',
  workflow_completed: 'b2b',
  workflow_failed: 'b2b',
  product_viewed: 'ecommerce',
  cart_item_added: 'ecommerce',
  cart_item_removed: 'ecommerce',
  cart_updated: 'ecommerce',
  coupon_applied: 'ecommerce',
  checkout_started: 'ecommerce',
  checkout_step_completed: 'ecommerce',
  order_completed: 'ecommerce',
  order_cancelled: 'ecommerce',
  order_refunded: 'ecommerce',
  chargeback_observed: 'ecommerce',
  subscription_started: 'ecommerce',
  trial_started: 'ecommerce',
  trial_converted: 'ecommerce',
  subscription_renewed: 'ecommerce',
  subscription_upgrade_observed: 'ecommerce',
  subscription_downgrade_observed: 'ecommerce',
  subscription_cancelled: 'ecommerce',
  invoice_issued: 'ecommerce',
  invoice_paid: 'ecommerce',
  invoice_failed: 'ecommerce',
  dunning_started: 'ecommerce',
  dunning_resolved: 'ecommerce',
  dead_click_observed: 'friction',
  rage_click_observed: 'friction',
  scroll_depth_observed: 'friction',
  form_started: 'friction',
  form_field_interaction: 'friction',
  form_validation_failed: 'friction',
  form_submitted: 'friction',
  form_abandoned: 'friction',
  search_reformulated: 'friction',
  retry_observed: 'friction',
  journey_stalled: 'friction',
  backtrack_observed: 'friction',
  api_request_observed: 'server',
  webhook_delivery_observed: 'server',
  connector_sync_started: 'server',
  connector_sync_completed: 'server',
  connector_sync_failed: 'server',
  job_started: 'server',
  job_completed: 'server',
  job_failed: 'server',
  rate_limit_observed: 'server',
  dependency_failure_observed: 'server',
  export_completed: 'server',
  signup_started: 'identity_lc',
  signup_completed: 'identity_lc',
  login_succeeded: 'identity_lc',
  login_failed: 'identity_lc',
  logout_observed: 'identity_lc',
  sso_observed: 'identity_lc',
  mfa_challenge_observed: 'identity_lc',
  identity_verified: 'identity_lc',
  alias_link_requested: 'identity_lc',
  alias_link_confirmed: 'identity_lc',
  alias_revoked: 'identity_lc',
  account_recovery_started: 'identity_lc',
  account_recovery_completed: 'identity_lc',
  device_registered: 'identity_lc',
  device_revoked: 'identity_lc',
  agent_evaluation_observed: 'agent',
  agent_cost_observed: 'agent',
  ai_invocation_observed: 'agent',
  agent_grounding_observed: 'agent',
  agent_guardrail_observed: 'agent',
  agent_human_override_observed: 'agent',
  transaction_pending_observed: 'web3_lc',
  transaction_confirmed_observed: 'web3_lc',
  transaction_reverted_observed: 'web3_lc',
  transaction_reorged_observed: 'web3_lc',
  token_approval_observed: 'web3_lc',
  allowance_changed_observed: 'web3_lc',
  bridge_transfer_observed: 'web3_lc',
  settlement_finality_observed: 'web3_lc',
  notification_delivered: 'comms',
  notification_opened: 'comms',
  notification_clicked: 'comms',
  email_delivered: 'comms',
  email_opened: 'comms',
  email_clicked: 'comms',
  email_bounced: 'comms',
  email_queued: 'comms',
  email_processed: 'comms',
  email_sent: 'comms',
  email_deferred: 'comms',
  email_dropped: 'comms',
  email_replied: 'comms',
  email_spam_complaint: 'comms',
  email_suppressed: 'comms',
  message_received_observed: 'comms',
  message_sent_observed: 'comms',
  message_replied_observed: 'comms',
  unsubscribe_observed: 'comms',
  support_case_created: 'comms',
  support_case_resolved: 'comms',
  support_case_escalated: 'comms',
  support_sla_breached: 'comms',
  credit_signal_observed: 'credit',
  credit_account_observed: 'credit',
  credit_decision_observed: 'credit',
  location_observed: 'location',
  geofence_transition_observed: 'location',
  trading_account_connected: 'derivatives',
  trading_account_disconnected: 'derivatives',
  trading_account_authorized: 'derivatives',
  trading_account_deauthorized: 'derivatives',
  trading_agent_enabled: 'derivatives',
  trading_agent_disabled: 'derivatives',
  trade_intent_created: 'derivatives',
  trade_approval_requested: 'derivatives',
  trade_approval_resolved: 'derivatives',
  risk_policy_updated: 'derivatives',
  human_trade_override_recorded: 'derivatives',
};

/**
 * Primary required consent purpose for each event type.
 * Events with empty requiredPurposes (e.g. 'consent') are omitted — always allowed.
 */
export const EVENT_CONSENT_PURPOSE: Record<EventType, string> = {
  track: 'analytics',
  page: 'analytics',
  screen: 'analytics',
  heartbeat: 'analytics',
  error: 'analytics',
  performance: 'analytics',
  experiment: 'marketing',
  journey_started: 'analytics',
  journey_paused: 'analytics',
  journey_resumed: 'analytics',
  journey_continued: 'analytics',
  journey_completed: 'analytics',
  journey_abandoned: 'analytics',
  journey_checkpoint: 'analytics',
  identify: 'analytics',
  consent: 'analytics',
  conversion: 'marketing',
  payment_initiated: 'commerce',
  payment_completed: 'commerce',
  payment_failed: 'commerce',
  approval_requested: 'commerce',
  approval_resolved: 'commerce',
  entitlement_granted: 'commerce',
  entitlement_revoked: 'commerce',
  access_granted: 'commerce',
  access_denied: 'commerce',
  wallet: 'web3',
  transaction: 'web3',
  contract_action: 'web3',
  agent_task: 'agent',
  agent_decision: 'agent',
  a2h_interaction: 'agent',
  agent_registered: 'agent',
  agent_updated: 'agent',
  agent_authorized: 'agent',
  agent_deauthorized: 'agent',
  agent_capability_granted: 'agent',
  agent_capability_revoked: 'agent',
  agent_task_created: 'agent',
  agent_task_decomposed: 'agent',
  agent_task_started: 'agent',
  agent_task_completed: 'agent',
  agent_task_failed: 'agent',
  agent_tool_called: 'agent',
  agent_resource_requested: 'agent',
  agent_delegated_task: 'agent',
  agent_subagent_spawned: 'agent',
  agent_policy_evaluated: 'agent',
  agent_handoff: 'agent',
  agent_escalated_to_human: 'agent',
  agent_outcome_recorded: 'agent',
  reward_action_queued: 'commerce',
  reward_proof_generated: 'commerce',
  reward_delivered: 'commerce',
  reward_claim_submitted: 'commerce',
  x402_payment: 'commerce',
  x402_resource_requested: 'commerce',
  x402_payment_required: 'commerce',
  x402_quote_received: 'commerce',
  x402_authorization_requested: 'commerce',
  x402_authorization_resolved: 'commerce',
  x402_payment_intent_created: 'commerce',
  x402_payment_submitted: 'commerce',
  x402_payment_settled: 'commerce',
  x402_payment_failed: 'commerce',
  x402_payment_timeout: 'commerce',
  x402_receipt_verified: 'commerce',
  x402_access_granted: 'commerce',
  x402_access_denied: 'commerce',
  x402_refund_or_reversal: 'commerce',
  agentic_account_observed: 'agent',
  agentic_account_connected_observed: 'agent',
  agentic_account_disconnected_observed: 'agent',
  agent_budget_observed: 'agent',
  agent_budget_changed_observed: 'agent',
  agent_permission_observed: 'agent',
  agent_mcp_connection_observed: 'agent',
  agent_tool_observed: 'agent',
  agent_tool_invocation_observed: 'agent',
  agent_activity_observed: 'agent',
  agent_risk_signal_observed: 'agent',
  agent_notification_observed: 'agent',
  agent_strategy_observed: 'agent',
  agent_trade_intent_observed: 'agent',
  agent_trade_order_observed: 'financial_activity',
  agent_trade_fill_observed: 'financial_activity',
  agent_trade_rejection_observed: 'agent',
  agent_position_observed: 'financial_activity',
  agent_portfolio_snapshot_observed: 'financial_activity',
  agent_performance_snapshot_observed: 'financial_activity',
  agent_disconnect_observed: 'agent',
  agent_inbox_observed: 'agent',
  agent_email_address_observed: 'agent',
  agent_thread_observed: 'agent',
  agent_message_received_observed: 'agent',
  agent_message_sent_observed: 'agent',
  agent_reply_observed: 'agent',
  agent_attachment_observed: 'agent',
  agent_attachment_parsed_observed: 'agent',
  agent_otp_detected_observed: 'agent',
  agent_invoice_detected_observed: 'agent',
  agent_receipt_detected_observed: 'agent',
  agent_calendar_intent_observed: 'agent',
  agent_support_route_observed: 'agent',
  agent_semantic_search_observed: 'agent',
  agent_data_extraction_observed: 'agent',
  x402_resource_request_observed: 'commerce',
  x402_challenge_observed: 'commerce',
  x402_payment_requirement_observed: 'commerce',
  x402_signature_observed: 'commerce',
  x402_verification_observed: 'commerce',
  x402_settlement_observed: 'commerce',
  x402_resource_access_observed: 'commerce',
  x402_resource_access_denied_observed: 'commerce',
  x402_failure_observed: 'commerce',
  x402_replay_risk_observed: 'commerce',
  x402_provider_observed: 'commerce',
  content_impression: 'analytics',
  recommendation_exposed: 'analytics',
  offer_exposed: 'analytics',
  feature_exposed: 'analytics',
  search_result_exposed: 'analytics',
  ad_exposed: 'marketing',
  notification_presented: 'analytics',
  decision_observed: 'analytics',
  outcome_observed: 'analytics',
  goal_achieved: 'analytics',
  goal_failed: 'analytics',
  recommendation_accepted: 'analytics',
  recommendation_rejected: 'analytics',
  feedback_submitted: 'analytics',
  retention_observed: 'analytics',
  churn_observed: 'analytics',
  human_override_observed: 'analytics',
  organization_observed: 'analytics',
  workspace_created: 'analytics',
  workspace_updated: 'analytics',
  member_invited: 'analytics',
  member_joined: 'analytics',
  member_removed: 'analytics',
  role_changed: 'analytics',
  seat_assigned: 'analytics',
  seat_released: 'analytics',
  integration_connected: 'analytics',
  integration_disconnected: 'analytics',
  service_account_created: 'analytics',
  service_account_revoked: 'analytics',
  api_key_created: 'analytics',
  api_key_revoked: 'analytics',
  project_created: 'analytics',
  project_archived: 'analytics',
  workflow_started: 'analytics',
  workflow_completed: 'analytics',
  workflow_failed: 'analytics',
  product_viewed: 'commerce',
  cart_item_added: 'commerce',
  cart_item_removed: 'commerce',
  cart_updated: 'commerce',
  coupon_applied: 'commerce',
  checkout_started: 'commerce',
  checkout_step_completed: 'commerce',
  order_completed: 'commerce',
  order_cancelled: 'commerce',
  order_refunded: 'commerce',
  chargeback_observed: 'commerce',
  subscription_started: 'commerce',
  trial_started: 'commerce',
  trial_converted: 'commerce',
  subscription_renewed: 'commerce',
  subscription_upgrade_observed: 'commerce',
  subscription_downgrade_observed: 'commerce',
  subscription_cancelled: 'commerce',
  invoice_issued: 'commerce',
  invoice_paid: 'commerce',
  invoice_failed: 'commerce',
  dunning_started: 'commerce',
  dunning_resolved: 'commerce',
  dead_click_observed: 'analytics',
  rage_click_observed: 'analytics',
  scroll_depth_observed: 'analytics',
  form_started: 'analytics',
  form_field_interaction: 'analytics',
  form_validation_failed: 'analytics',
  form_submitted: 'analytics',
  form_abandoned: 'analytics',
  search_reformulated: 'analytics',
  retry_observed: 'analytics',
  journey_stalled: 'analytics',
  backtrack_observed: 'analytics',
  api_request_observed: 'analytics',
  webhook_delivery_observed: 'analytics',
  connector_sync_started: 'analytics',
  connector_sync_completed: 'analytics',
  connector_sync_failed: 'analytics',
  job_started: 'analytics',
  job_completed: 'analytics',
  job_failed: 'analytics',
  rate_limit_observed: 'analytics',
  dependency_failure_observed: 'analytics',
  export_completed: 'analytics',
  signup_started: 'analytics',
  signup_completed: 'analytics',
  login_succeeded: 'analytics',
  login_failed: 'analytics',
  logout_observed: 'analytics',
  sso_observed: 'analytics',
  mfa_challenge_observed: 'analytics',
  identity_verified: 'analytics',
  alias_link_requested: 'analytics',
  alias_link_confirmed: 'analytics',
  alias_revoked: 'analytics',
  account_recovery_started: 'analytics',
  account_recovery_completed: 'analytics',
  device_registered: 'analytics',
  device_revoked: 'analytics',
  agent_evaluation_observed: 'agent',
  agent_cost_observed: 'agent',
  ai_invocation_observed: 'agent',
  agent_grounding_observed: 'agent',
  agent_guardrail_observed: 'agent',
  agent_human_override_observed: 'agent',
  transaction_pending_observed: 'web3',
  transaction_confirmed_observed: 'web3',
  transaction_reverted_observed: 'web3',
  transaction_reorged_observed: 'web3',
  token_approval_observed: 'web3',
  allowance_changed_observed: 'web3',
  bridge_transfer_observed: 'web3',
  settlement_finality_observed: 'web3',
  notification_delivered: 'analytics',
  notification_opened: 'analytics',
  notification_clicked: 'analytics',
  email_delivered: 'marketing',
  email_opened: 'marketing',
  email_clicked: 'marketing',
  email_bounced: 'marketing',
  email_queued: 'marketing',
  email_processed: 'marketing',
  email_sent: 'marketing',
  email_deferred: 'marketing',
  email_dropped: 'marketing',
  email_replied: 'marketing',
  email_spam_complaint: 'marketing',
  email_suppressed: 'marketing',
  message_received_observed: 'analytics',
  message_sent_observed: 'analytics',
  message_replied_observed: 'analytics',
  unsubscribe_observed: 'marketing',
  support_case_created: 'analytics',
  support_case_resolved: 'analytics',
  support_case_escalated: 'analytics',
  support_sla_breached: 'analytics',
  credit_signal_observed: 'credit',
  credit_account_observed: 'credit',
  credit_decision_observed: 'credit',
  location_observed: 'location',
  geofence_transition_observed: 'location',
  trading_account_connected: 'financial_activity',
  trading_account_disconnected: 'financial_activity',
  trading_account_authorized: 'financial_activity',
  trading_account_deauthorized: 'financial_activity',
  trading_agent_enabled: 'financial_activity',
  trading_agent_disabled: 'financial_activity',
  trade_intent_created: 'financial_activity',
  trade_approval_requested: 'financial_activity',
  trade_approval_resolved: 'financial_activity',
  risk_policy_updated: 'financial_activity',
  human_trade_override_recorded: 'financial_activity',
};
// @generated-end

// ---------------------------------------------------------------------------
// Envelope
// ---------------------------------------------------------------------------

export interface PageContext {
  url: string;
  path: string;
  title: string;
  referrer: string;
  search?: string;
  hash?: string;
}

export interface DeviceContext {
  type: 'desktop' | 'mobile' | 'tablet';
  os?: string;
  osVersion?: string;
  browser?: string;
  browserVersion?: string;
  screenWidth?: number;
  screenHeight?: number;
  viewportWidth?: number;
  viewportHeight?: number;
  pixelRatio?: number;
  language?: string;
}

export interface CampaignContext {
  source?: string;
  medium?: string;
  campaign?: string;
  content?: string;
  term?: string;
  /** utm_id — highest-confidence UTM alias token. */
  utmId?: string;
  clickId?: string;
  referrerDomain?: string;
  referrerType?: 'direct' | 'organic' | 'paid' | 'social' | 'email' | 'referral' | 'unknown';
  /** Provider campaign ID (e.g. Google, Meta). Never treated as canonical Aether UUID. */
  externalCampaignId?: string;
  externalAccountId?: string;
  platform?: string;
  /** Aether canonical campaign UUID. Validated server-side before use. */
  canonicalCampaignId?: string;
}

export interface LibraryContext {
  name: string;
  version: string;
}

// ---------------------------------------------------------------------------
// Multi-actor journey v1 — optional event-completeness fields.
// All optional → existing SDKs keep working unchanged.
// ---------------------------------------------------------------------------

export type { ActorKind };

export interface ImpressionRecord {
  surface: string;          // e.g. 'home_feed', 'product_grid'
  itemId: string;
  position?: number;
  viewableMs?: number;
  viewportPct?: number;
  clicked?: boolean;
}

export interface IntentHint {
  predictedGoal: string;
  confidence: number;       // 0..1
}

export interface FrictionRecord {
  errorCode?: string;
  retryCount?: number;
  latencyMs?: number;
  [k: string]: string | number | undefined;
}

export interface EngagementRecord {
  depth?: number;
  dwellMs?: number;
  scrollPct?: number;
  [k: string]: number | undefined;
}

export interface DataQualityRecord {
  completeness?: number;    // 0..1
  freshness?: number;       // 0..1
  sourceTrust?: number;     // 0..1
  [k: string]: number | undefined;
}


// ---------------------------------------------------------------------------
// Cross-device journey continuity
// ---------------------------------------------------------------------------

export type JourneyLifecycleEventType =
  | 'journey_started'
  | 'journey_paused'
  | 'journey_resumed'
  | 'journey_continued'
  | 'journey_completed'
  | 'journey_abandoned'
  | 'journey_checkpoint';

export type JourneyStatus =
  | 'started'
  | 'paused'
  | 'resumed'
  | 'continued'
  | 'completed'
  | 'abandoned'
  | 'checkpoint';

export interface JourneyAttributionContext {
  source?: string;
  medium?: string;
  campaign?: string;
  content?: string;
  term?: string;
  clickId?: string;
  referrer?: string;
  deepLink?: string;
  [key: string]: unknown;
}

export interface JourneyPayload {
  journeyId?: string;
  journeyName?: string;
  journeyType?: string;
  stepId?: string;
  stepName?: string;
  previousStepId?: string;
  nextExpectedStepId?: string;
  journeyStatus?: JourneyStatus;
  pauseReason?: string;
  resumeReason?: string;
  completionReason?: string;
  abandonmentReason?: string;
  handoffFromSessionId?: string;
  handoffFromDeviceId?: string;
  handoffToDeviceId?: string;
  handoffLatencyMs?: number;
  confidence?: number;
  confidenceSignals?: string[];
  sourceSessionId?: string;
  sourceAnonymousId?: string;
  sourceUserId?: string;
  targetSessionId?: string;
  targetAnonymousId?: string;
  targetUserId?: string;
  campaignAttribution?: JourneyAttributionContext;
  referrerAttribution?: JourneyAttributionContext;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface JourneyLifecycleEvent extends BaseEvent {
  type: JourneyLifecycleEventType;
  properties: JourneyPayload;
}

export interface JourneyContext {
  journeyId?: string;
  journeyName?: string;
  journeyType?: string;
  currentStepId?: string;
  currentStepName?: string;
  status?: JourneyStatus;
  lastLifecycleEvent?: JourneyLifecycleEventType;
  confidence?: number;
  confidenceSignals?: string[];
}

export interface EventContext {
  library: LibraryContext;
  page?: PageContext;
  device?: DeviceContext;
  campaign?: CampaignContext;
  /** Full acquisition evidence envelope captured at landing; superset of CampaignContext. */
  acquisitionEvidence?: import('./acquisition-evidence').AcquisitionEvidence;
  fingerprint?: { id: string };
  ip?: string;
  locale?: string;
  timezone?: string;
  userAgent?: string;
  consent?: ConsentState;
  provenance?: Provenance;
  journey?: JourneyContext;
  /** Optional tenant/org binding for B2B + hybrid companies. */
  tenantId?: string;
  orgId?: string;

  // -- multi-actor journey v1 ------------------------------------------------
  /** Resolved or SDK-provided actor performing the event. */
  actorId?: string;
  actorKind?: ActorKind;
  /** When an actor acts on behalf of another (e.g. agent → human owner). */
  beneficiaryActorId?: string;

  /** Active delegation grant covering this action, if any. */
  delegationId?: string;
  delegationScope?: string[];

  /** Identity-stitching metadata. */
  identityConfidence?: number;          // 0..1
  identitySignals?: string[];           // e.g. ['login','wallet_match','cookie']

  /** Impressions seen but not necessarily clicked (exposure-aware attribution). */
  impressions?: ImpressionRecord[];

  // -- A6: reward enablement -------------------------------------------------
  /** Campaign this event is attributed to for reward eligibility evaluation. */
  rewardCampaignId?: string;
  /** Rule within the campaign matched for this event. */
  rewardRuleId?: string;
  /** Idempotency key for the reward eligibility decision. */
  rewardIdempotencyKey?: string;
  /** Wallet address of the reward recipient (EVM or other VM). */
  rewardWalletAddress?: string;
  /** Attribution result ID from the attribution service. */
  attributionResultId?: string;
  /** Fraud decision ID from the fraud service. */
  fraudDecisionId?: string;
  /** Consent snapshot ID at the time of event. */
  consentSnapshotId?: string;
}

/** The canonical event envelope every SDK emits. */
export interface BaseEvent {
  id: string;
  type: EventType;
  timestamp: string;
  sessionId: string;
  anonymousId: string;
  userId?: string;
  properties?: Record<string, unknown>;
  context: EventContext;
}

/** Ingestion batch envelope POSTed to /v1/batch. */
export interface BatchPayload {
  batch: BaseEvent[];
  sentAt: string;
  context?: { library: LibraryContext };
}
