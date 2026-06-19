// =============================================================================
// Aether SDK — EVENT QUEUE (BATCH, FLUSH, RETRY, OFFLINE PERSISTENCE)
// Updated for multi-VM Web3 event types
// =============================================================================

import type { AetherEvent, RetryConfig, ConsentState } from '../types';
import { storage } from '../utils';

const QUEUE_STORAGE_KEY = 'event_queue';
const MAX_STORED_EVENTS = 1000;
const SDK_VERSION = '8.9.0'; // synchronized by scripts/bump-sdk-version.sh and scripts/validate_sdk_release_alignment.py

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
  agent_trade_order_observed: 'agent', agent_trade_fill_observed: 'agent',
  agent_trade_rejection_observed: 'agent', agent_position_observed: 'agent',
  agent_portfolio_snapshot_observed: 'agent', agent_performance_snapshot_observed: 'agent',
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
  x402_resource_request_observed: 'agent', x402_challenge_observed: 'agent',
  x402_payment_requirement_observed: 'agent', x402_signature_observed: 'agent',
  x402_verification_observed: 'agent', x402_settlement_observed: 'agent',
  x402_resource_access_observed: 'agent', x402_resource_access_denied_observed: 'agent',
  x402_failure_observed: 'agent', x402_replay_risk_observed: 'agent',
  x402_provider_observed: 'agent',
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
