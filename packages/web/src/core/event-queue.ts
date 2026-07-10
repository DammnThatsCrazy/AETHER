// =============================================================================
// Aether SDK — EVENT QUEUE (BATCH, FLUSH, RETRY, OFFLINE PERSISTENCE)
// Updated for multi-VM Web3 event types
// =============================================================================

import type { AetherEvent, RetryConfig, ConsentState } from '../types';
import { storage } from '../utils';

const QUEUE_STORAGE_KEY = 'event_queue';
const MAX_STORED_EVENTS = 1000;
const SDK_VERSION = '8.12.0'; // synchronized by scripts/bump-sdk-version.sh and scripts/validate_sdk_release_alignment.py

interface QueueConfig {
  endpoint: string;
  apiKey: string;
  batchSize: number;
  flushInterval: number;
  maxQueueSize: number;
  retry: Required<RetryConfig>;
  headers: Record<string, string>;
  onError?: (error: Error, events: AetherEvent[]) => void;
  /** Called after each batch send attempt with round-trip latency and success. */
  onAttempt?: (latencyMs: number, success: boolean) => void;
}

const DEFAULT_RETRY: Required<RetryConfig> = {
  maxRetries: 3,
  baseDelay: 1000,
  maxDelay: 30000,
  backoffMultiplier: 2,
};

/**
 * Maps every canonical event type to its required consent purpose.
 * MUST stay in sync with packages/shared/events.ts EVENT_CONSENT_PURPOSE.
 * Events not listed here are rejected; custom application signals must be
 * wrapped as canonical `track` with `properties.event`.
 */
const SENSITIVE_KEYS = new Set([
  'privatekey', 'private_key', 'seedphrase', 'seed_phrase', 'mnemonic',
  'secret', 'secretkey', 'secret_key', 'password', 'pin',
  'cardnumber', 'card_number', 'pan', 'cvv', 'cvc', 'cvv2',
  'paymenttoken', 'payment_token', 'authcode', 'auth_code',
]);

const CONSENT_MAP: Record<string, string> = {
  // Core analytics
  track: 'analytics', page: 'analytics', screen: 'analytics',
  heartbeat: 'analytics', error: 'analytics', performance: 'analytics',
  journey_started: 'analytics', journey_paused: 'analytics', journey_resumed: 'analytics',
  journey_continued: 'analytics', journey_completed: 'analytics', journey_abandoned: 'analytics',
  journey_checkpoint: 'analytics',
  identify: 'analytics',
  // Marketing
  experiment: 'marketing', conversion: 'marketing',
  // Commerce / access (Web2 + Web3 unified)
  payment_initiated: 'commerce', payment_completed: 'commerce', payment_failed: 'commerce',
  approval_requested: 'commerce', approval_resolved: 'commerce',
  entitlement_granted: 'commerce', entitlement_revoked: 'commerce',
  access_granted: 'commerce', access_denied: 'commerce',
  // Wallet / on-chain
  wallet: 'web3', transaction: 'web3', contract_action: 'web3',
  // Agent (legacy)
  agent_task: 'agent', agent_decision: 'agent', a2h_interaction: 'agent',
  // Agent lifecycle
  agent_registered: 'agent', agent_updated: 'agent',
  agent_authorized: 'agent', agent_deauthorized: 'agent',
  agent_capability_granted: 'agent', agent_capability_revoked: 'agent',
  agent_task_created: 'agent', agent_task_decomposed: 'agent',
  agent_task_started: 'agent', agent_task_completed: 'agent', agent_task_failed: 'agent',
  agent_tool_called: 'agent', agent_resource_requested: 'agent',
  agent_delegated_task: 'agent', agent_subagent_spawned: 'agent',
  agent_policy_evaluated: 'agent', agent_handoff: 'agent',
  agent_escalated_to_human: 'agent', agent_outcome_recorded: 'agent',
  // x402 (legacy)
  x402_payment: 'commerce',
  // x402 lifecycle
  x402_resource_requested: 'commerce', x402_payment_required: 'commerce',
  x402_quote_received: 'commerce', x402_authorization_requested: 'commerce',
  x402_authorization_resolved: 'commerce', x402_payment_intent_created: 'commerce',
  x402_payment_submitted: 'commerce', x402_payment_settled: 'commerce',
  x402_payment_failed: 'commerce', x402_payment_timeout: 'commerce',
  x402_receipt_verified: 'commerce', x402_access_granted: 'commerce',
  x402_access_denied: 'commerce', x402_refund_or_reversal: 'commerce',
  // reward enablement (A6)
  reward_action_queued: 'commerce', reward_proof_generated: 'commerce',
  reward_delivered: 'commerce', reward_claim_submitted: 'commerce',
  // Agentic observability — account / MCP / tool
  agentic_account_observed: 'agent', agentic_account_connected_observed: 'agent',
  agentic_account_disconnected_observed: 'agent', agent_budget_observed: 'agent',
  agent_budget_changed_observed: 'agent', agent_permission_observed: 'agent',
  agent_mcp_connection_observed: 'agent', agent_tool_observed: 'agent',
  agent_tool_invocation_observed: 'agent', agent_activity_observed: 'agent',
  agent_risk_signal_observed: 'agent', agent_notification_observed: 'agent',
  // Agentic observability — Robinhood-style trading observation
  agent_strategy_observed: 'agent', agent_trade_intent_observed: 'agent',
  agent_trade_order_observed: 'financial_activity', agent_trade_fill_observed: 'financial_activity',
  agent_trade_rejection_observed: 'agent', agent_position_observed: 'financial_activity',
  agent_portfolio_snapshot_observed: 'financial_activity', agent_performance_snapshot_observed: 'financial_activity',
  agent_disconnect_observed: 'agent',
  // Agentic observability — AgentMail-style communication observation
  agent_inbox_observed: 'agent', agent_email_address_observed: 'agent',
  agent_thread_observed: 'agent', agent_message_received_observed: 'agent',
  agent_message_sent_observed: 'agent', agent_reply_observed: 'agent',
  agent_attachment_observed: 'agent', agent_attachment_parsed_observed: 'agent',
  agent_otp_detected_observed: 'agent', agent_invoice_detected_observed: 'agent',
  agent_receipt_detected_observed: 'agent', agent_calendar_intent_observed: 'agent',
  agent_support_route_observed: 'agent', agent_semantic_search_observed: 'agent',
  agent_data_extraction_observed: 'agent',
  // x402 protocol observation family
  x402_resource_request_observed: 'commerce', x402_challenge_observed: 'commerce',
  x402_payment_requirement_observed: 'commerce', x402_signature_observed: 'commerce',
  x402_verification_observed: 'commerce', x402_settlement_observed: 'commerce',
  x402_resource_access_observed: 'commerce', x402_resource_access_denied_observed: 'commerce',
  x402_failure_observed: 'commerce', x402_replay_risk_observed: 'commerce',
  x402_provider_observed: 'commerce',
  // Exposure family
  content_impression: 'analytics', recommendation_exposed: 'analytics',
  offer_exposed: 'analytics', feature_exposed: 'analytics',
  search_result_exposed: 'analytics', ad_exposed: 'marketing',
  notification_presented: 'analytics', decision_observed: 'analytics',
  // Outcome family
  outcome_observed: 'analytics', goal_achieved: 'analytics', goal_failed: 'analytics',
  recommendation_accepted: 'analytics', recommendation_rejected: 'analytics',
  feedback_submitted: 'analytics', retention_observed: 'analytics',
  churn_observed: 'analytics', human_override_observed: 'analytics',
  // B2B family
  organization_observed: 'analytics', workspace_created: 'analytics', workspace_updated: 'analytics',
  member_invited: 'analytics', member_joined: 'analytics', member_removed: 'analytics',
  role_changed: 'analytics', seat_assigned: 'analytics', seat_released: 'analytics',
  integration_connected: 'analytics', integration_disconnected: 'analytics',
  service_account_created: 'analytics', service_account_revoked: 'analytics',
  api_key_created: 'analytics', api_key_revoked: 'analytics',
  project_created: 'analytics', project_archived: 'analytics',
  workflow_started: 'analytics', workflow_completed: 'analytics', workflow_failed: 'analytics',
  // Ecommerce extended family
  product_viewed: 'commerce', cart_item_added: 'commerce', cart_item_removed: 'commerce',
  cart_updated: 'commerce', coupon_applied: 'commerce',
  checkout_started: 'commerce', checkout_step_completed: 'commerce',
  order_completed: 'commerce', order_cancelled: 'commerce', order_refunded: 'commerce',
  chargeback_observed: 'commerce',
  subscription_started: 'commerce', trial_started: 'commerce', trial_converted: 'commerce',
  subscription_renewed: 'commerce', subscription_upgrade_observed: 'commerce',
  subscription_downgrade_observed: 'commerce', subscription_cancelled: 'commerce',
  invoice_issued: 'commerce', invoice_paid: 'commerce', invoice_failed: 'commerce',
  dunning_started: 'commerce', dunning_resolved: 'commerce',
  // Friction family
  dead_click_observed: 'analytics', rage_click_observed: 'analytics',
  scroll_depth_observed: 'analytics', form_started: 'analytics',
  form_field_interaction: 'analytics', form_validation_failed: 'analytics',
  form_submitted: 'analytics', form_abandoned: 'analytics',
  search_reformulated: 'analytics', retry_observed: 'analytics',
  journey_stalled: 'analytics', backtrack_observed: 'analytics',
  // Server observation family
  api_request_observed: 'analytics', webhook_delivery_observed: 'analytics',
  connector_sync_started: 'analytics', connector_sync_completed: 'analytics',
  connector_sync_failed: 'analytics', job_started: 'analytics',
  job_completed: 'analytics', job_failed: 'analytics',
  rate_limit_observed: 'analytics', dependency_failure_observed: 'analytics',
  export_completed: 'analytics',
  // Identity lifecycle family
  signup_started: 'analytics', signup_completed: 'analytics',
  login_succeeded: 'analytics', login_failed: 'analytics',
  logout_observed: 'analytics', sso_observed: 'analytics',
  mfa_challenge_observed: 'analytics', identity_verified: 'analytics',
  alias_link_requested: 'analytics', alias_link_confirmed: 'analytics',
  alias_revoked: 'analytics', account_recovery_started: 'analytics',
  account_recovery_completed: 'analytics', device_registered: 'analytics',
  device_revoked: 'analytics',
  // Agent evaluation family
  agent_evaluation_observed: 'agent', agent_cost_observed: 'agent',
  agent_grounding_observed: 'agent', agent_guardrail_observed: 'agent',
  agent_human_override_observed: 'agent', ai_invocation_observed: 'agent',
  // Web3 lifecycle extensions
  transaction_pending_observed: 'web3', transaction_confirmed_observed: 'web3',
  transaction_reverted_observed: 'web3', transaction_reorged_observed: 'web3',
  token_approval_observed: 'web3', allowance_changed_observed: 'web3',
  bridge_transfer_observed: 'web3', settlement_finality_observed: 'web3',
  // Comms family
  notification_delivered: 'analytics', notification_opened: 'analytics',
  notification_clicked: 'analytics',
  email_delivered: 'marketing', email_opened: 'marketing',
  email_clicked: 'marketing', email_bounced: 'marketing',
  email_queued: 'marketing', email_processed: 'marketing',
  email_sent: 'marketing', email_deferred: 'marketing',
  email_dropped: 'marketing', email_replied: 'marketing',
  email_spam_complaint: 'marketing', email_suppressed: 'marketing',
  message_replied_observed: 'analytics', unsubscribe_observed: 'marketing',
  support_case_created: 'analytics', support_case_resolved: 'analytics',
  support_case_escalated: 'analytics', support_sla_breached: 'analytics',
  // Credit family (explicit opt-in)
  credit_signal_observed: 'credit', credit_account_observed: 'credit',
  credit_decision_observed: 'credit',
  // Location family (explicit opt-in)
  location_observed: 'location', geofence_transition_observed: 'location',
  // Derivatives family (explicit financial_activity opt-in)
  trading_account_connected: 'financial_activity', trading_account_disconnected: 'financial_activity',
  trading_account_authorized: 'financial_activity', trading_account_deauthorized: 'financial_activity',
  trading_agent_enabled: 'financial_activity', trading_agent_disabled: 'financial_activity',
  trade_intent_created: 'financial_activity', trade_approval_requested: 'financial_activity',
  trade_approval_resolved: 'financial_activity', risk_policy_updated: 'financial_activity',
  human_trade_override_recorded: 'financial_activity',
  // Stablecoin intelligence family (explicit opt-in)
  stablecoin_transfer_observed: 'economic_observability', stablecoin_payment_observed: 'economic_observability',
  stablecoin_mint_observed: 'economic_observability', stablecoin_burn_observed: 'economic_observability',
  stablecoin_bridge_outbound_observed: 'economic_observability', stablecoin_bridge_inbound_observed: 'economic_observability',
  stablecoin_swap_observed: 'economic_observability', stablecoin_x402_settlement_observed: 'economic_observability',
  stablecoin_treasury_movement_observed: 'economic_observability', stablecoin_payout_observed: 'economic_observability',
  stablecoin_venue_deposit_observed: 'economic_observability', stablecoin_venue_withdrawal_observed: 'economic_observability',
  stablecoin_balance_snapshot_observed: 'economic_observability', stablecoin_supply_snapshot_observed: 'economic_observability',
  stablecoin_holder_concentration_observed: 'economic_observability', stablecoin_valuation_observed: 'economic_observability',
  stablecoin_depeg_detected: 'economic_observability', stablecoin_depeg_resolved: 'economic_observability',
  stablecoin_finality_confirmed: 'economic_observability', stablecoin_reorg_detected: 'economic_observability',
  stablecoin_observation_corrected: 'economic_observability', stablecoin_reconciliation_run_completed: 'economic_observability',
  stablecoin_reconciliation_variance_detected: 'economic_observability', stablecoin_reconciliation_variance_resolved: 'economic_observability',
  stablecoin_asset_registered: 'economic_observability', stablecoin_deployment_registered: 'economic_observability',
  stablecoin_support_asserted: 'economic_observability', stablecoin_support_revoked: 'economic_observability',
  stablecoin_flow_aggregate_materialized: 'economic_observability', stablecoin_checkpoint_advanced: 'economic_observability',
  // Derivatives intelligence family (explicit opt-in)
  derivatives_venue_registered: 'financial_activity', derivatives_venue_deployment_registered: 'financial_activity',
  derivatives_instrument_registered: 'financial_activity', derivatives_market_registered: 'financial_activity',
  derivatives_strategy_registered: 'financial_activity', derivatives_strategy_version_registered: 'financial_activity',
  derivatives_risk_policy_registered: 'financial_activity', derivatives_account_linked: 'financial_activity',
  derivatives_account_link_revoked: 'financial_activity', derivatives_balance_snapshot_observed: 'financial_activity',
  derivatives_collateral_change_observed: 'financial_activity', derivatives_margin_snapshot_observed: 'financial_activity',
  derivatives_order_observed: 'financial_activity', derivatives_order_updated_observed: 'financial_activity',
  derivatives_order_cancelled_observed: 'financial_activity', derivatives_order_rejected_observed: 'financial_activity',
  derivatives_order_expired_observed: 'financial_activity', derivatives_fill_observed: 'financial_activity',
  derivatives_fill_corrected: 'financial_activity', derivatives_position_opened_observed: 'financial_activity',
  derivatives_position_increased_observed: 'financial_activity', derivatives_position_reduced_observed: 'financial_activity',
  derivatives_position_closed_observed: 'financial_activity', derivatives_position_liquidated_observed: 'financial_activity',
  derivatives_position_adl_observed: 'financial_activity', derivatives_position_settled_observed: 'financial_activity',
  derivatives_position_corrected: 'financial_activity', derivatives_funding_payment_observed: 'financial_activity',
  derivatives_fee_observed: 'financial_activity', derivatives_pnl_snapshot_materialized: 'financial_activity',
  derivatives_exposure_snapshot_materialized: 'financial_activity', derivatives_price_observation_recorded: 'financial_activity',
  derivatives_market_status_changed: 'financial_activity', derivatives_stream_gap_detected: 'financial_activity',
  derivatives_stream_gap_recovered: 'financial_activity', derivatives_stream_checkpoint_advanced: 'financial_activity',
  derivatives_adapter_conformance_run: 'financial_activity', derivatives_reconciliation_run_completed: 'financial_activity',
  derivatives_reconciliation_variance_detected: 'financial_activity', derivatives_reconciliation_variance_resolved: 'financial_activity',
  derivatives_risk_threshold_breached: 'financial_activity',
  // Interoperability intelligence family (explicit opt-in)
  interop_provider_registered: 'cross_chain_observability', interop_gateway_registered: 'cross_chain_observability',
  interop_path_registered: 'cross_chain_observability', interop_application_registered: 'cross_chain_observability',
  interop_verification_actor_registered: 'cross_chain_observability', interop_message_discovered: 'cross_chain_observability',
  interop_message_sent_observed: 'cross_chain_observability', interop_message_source_confirmed: 'cross_chain_observability',
  interop_message_verification_observed: 'cross_chain_observability', interop_message_verified: 'cross_chain_observability',
  interop_message_delivery_attempt_observed: 'cross_chain_observability', interop_message_delivered: 'cross_chain_observability',
  interop_message_executed_observed: 'cross_chain_observability', interop_message_settled: 'cross_chain_observability',
  interop_message_failed: 'cross_chain_observability', interop_message_timeout: 'cross_chain_observability',
  interop_message_expired: 'cross_chain_observability', interop_message_cancelled: 'cross_chain_observability',
  interop_message_refunded_observed: 'cross_chain_observability', interop_message_recovered: 'cross_chain_observability',
  interop_message_reorged: 'cross_chain_observability', interop_message_corrected: 'cross_chain_observability',
  interop_message_correlated: 'cross_chain_observability', interop_intent_observed: 'cross_chain_observability',
  interop_intent_fulfilled_observed: 'cross_chain_observability', interop_asset_leg_locked_observed: 'cross_chain_observability',
  interop_asset_leg_burned_observed: 'cross_chain_observability', interop_asset_leg_minted_observed: 'cross_chain_observability',
  interop_asset_leg_released_observed: 'cross_chain_observability', interop_fee_observed: 'cross_chain_observability',
  interop_security_policy_snapshot_recorded: 'cross_chain_observability', interop_security_policy_changed: 'cross_chain_observability',
  interop_verification_quorum_observed: 'cross_chain_observability', interop_provider_checkpoint_advanced: 'cross_chain_observability',
  interop_stream_gap_detected: 'cross_chain_observability', interop_stream_gap_recovered: 'cross_chain_observability',
  interop_reconciliation_run_completed: 'cross_chain_observability', interop_reconciliation_variance_detected: 'cross_chain_observability',
  interop_reconciliation_variance_resolved: 'cross_chain_observability',
};

function scrubSensitiveFields(props: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(props)) {
    out[k] = SENSITIVE_KEYS.has(k.toLowerCase()) ? '[REDACTED]' : v;
  }
  return out;
}

export class EventQueue {
  private queue: AetherEvent[] = [];
  private config: QueueConfig;
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private isFlushing = false;
  private isDestroyed = false;
  private consent: ConsentState | null = null;

  constructor(config: Omit<Partial<QueueConfig>, 'retry'> & Pick<QueueConfig, 'endpoint' | 'apiKey'> & { retry?: RetryConfig }) {
    this.config = {
      batchSize: config.batchSize ?? 10,
      flushInterval: config.flushInterval ?? 5000,
      maxQueueSize: config.maxQueueSize ?? 100,
      retry: { ...DEFAULT_RETRY, ...config.retry },
      headers: config.headers ?? {},
      endpoint: config.endpoint,
      apiKey: config.apiKey,
      onError: config.onError,
      onAttempt: config.onAttempt,
    };
    this.restoreQueue();
    this.startFlushTimer();
    this.setupLifecycleHandlers();
  }

  setConsent(consent: ConsentState): void {
    this.consent = consent;
  }

  enqueue(event: AetherEvent): void {
    if (this.isDestroyed) return;
    const safe: AetherEvent = event.properties
      ? ({ ...event, properties: scrubSensitiveFields(event.properties) } as AetherEvent)
      : event;
    this.queue.push(safe);
    if (this.queue.length >= this.config.batchSize) this.flush();
    if (this.queue.length >= this.config.maxQueueSize) this.flush();
  }

  async flush(): Promise<void> {
    if (this.isFlushing || this.queue.length === 0 || this.isDestroyed) return;

    this.isFlushing = true;
    const batch = this.queue.splice(0, this.config.batchSize);
    const allowedEvents = this.filterByConsent(batch);

    // Consent filtering is intentional, not an ingestion failure — it must not
    // count against health metrics, so it is deliberately not reported as a drop.
    if (allowedEvents.length === 0) {
      this.isFlushing = false;
      return;
    }

    const start = Date.now();
    try {
      await this.sendBatch(allowedEvents);
      this.config.onAttempt?.(Date.now() - start, true);
      this.persistQueue();
    } catch (error) {
      this.config.onAttempt?.(Date.now() - start, false);
      this.queue.unshift(...allowedEvents);
      this.persistQueue();
      this.config.onError?.(error as Error, allowedEvents);
    } finally {
      this.isFlushing = false;
      if (this.queue.length >= this.config.batchSize) this.flush();
    }
  }

  get size(): number {
    return this.queue.length;
  }

  destroy(): void {
    this.isDestroyed = true;
    if (this.flushTimer) { clearInterval(this.flushTimer); this.flushTimer = null; }
    if (this.queue.length > 0) this.sendBeacon(this.queue);
    this.queue = [];
  }

  // ===========================================================================
  // PRIVATE
  // ===========================================================================

  private filterByConsent(events: AetherEvent[]): AetherEvent[] {
    if (!this.consent) return events;
    const consent = this.consent;

    return events.filter((event) => {
      if ((event.type as string) === 'consent') return true;
      const purpose = CONSENT_MAP[event.type];
      if (!purpose) return false;
      return (consent as unknown as Record<string, boolean>)[purpose] === true;
    });
  }

  private async sendBatch(events: AetherEvent[], retryCount = 0): Promise<void> {
    const payload = JSON.stringify({
      batch: events,
      sentAt: new Date().toISOString(),
      context: { library: { name: '@aether/sdk', version: SDK_VERSION } },
    });

    const response = await fetch(`${this.config.endpoint}/v1/batch`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.config.apiKey}`,
        'X-Aether-SDK': 'web',
        ...this.config.headers,
      },
      body: payload,
      keepalive: true,
    });

    if (!response.ok) {
      if (response.status >= 500 && retryCount < this.config.retry.maxRetries) {
        const delay = Math.min(
          this.config.retry.baseDelay * Math.pow(this.config.retry.backoffMultiplier, retryCount),
          this.config.retry.maxDelay
        );
        await this.sleep(delay);
        return this.sendBatch(events, retryCount + 1);
      }

      if (response.status === 429) {
        if (retryCount >= this.config.retry.maxRetries) {
          throw new Error('Rate limited: max retries exceeded');
        }
        const retryAfter = parseInt(response.headers.get('Retry-After') || '5', 10);
        await this.sleep(retryAfter * 1000);
        return this.sendBatch(events, retryCount + 1);
      }

      throw new Error(`Aether API error: ${response.status} ${response.statusText}`);
    }
  }

  private sendBeacon(events: AetherEvent[]): boolean {
    // Use fetch with keepalive:true instead of sendBeacon.
    // sendBeacon does not support Authorization headers, which would force
    // the API key into the URL query string — visible in proxy logs and referrer
    // headers. fetch+keepalive is supported in all modern browsers and behaves
    // identically for page-unload scenarios.
    const allowed = this.filterByConsent(events);
    if (allowed.length === 0) return true;
    const payload = JSON.stringify({
      batch: allowed,
      sentAt: new Date().toISOString(),
      context: { library: { name: '@aether/sdk', version: SDK_VERSION } },
    });
    try {
      fetch(`${this.config.endpoint}/v1/batch`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.config.apiKey}`,
          'X-Aether-SDK': 'web',
          ...this.config.headers,
        },
        body: payload,
        keepalive: true,
      }).catch(() => {
        // Unload flush is best-effort; silently drop if fetch fails.
        // The queue was already cleared by the caller — retries happen
        // via the persistent queue on next page load.
      });
      return true;
    } catch {
      return false;
    }
  }

  private startFlushTimer(): void {
    this.flushTimer = setInterval(() => {
      if (this.queue.length > 0) this.flush();
    }, this.config.flushInterval);
  }

  private setupLifecycleHandlers(): void {
    if (typeof window === 'undefined') return;
    window.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden' && this.queue.length > 0) {
        const sent = this.sendBeacon(this.queue);
        if (sent) this.queue = [];
        // If beacon rejected, leave queue intact — periodic flush will retry
      }
    });
    window.addEventListener('pagehide', () => {
      if (this.queue.length > 0) {
        const sent = this.sendBeacon(this.queue);
        if (sent) this.queue = [];
      }
    });
    window.addEventListener('online', () => {
      if (this.queue.length > 0) this.flush();
    });
  }

  private persistQueue(): void {
    storage.set(QUEUE_STORAGE_KEY, this.queue.slice(0, MAX_STORED_EVENTS));
  }

  private restoreQueue(): void {
    const stored = storage.get<AetherEvent[]>(QUEUE_STORAGE_KEY);
    if (stored && Array.isArray(stored)) {
      this.queue = [...stored, ...this.queue];
      storage.remove(QUEUE_STORAGE_KEY);
    }
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}
