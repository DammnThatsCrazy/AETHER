// =============================================================================
// Aether SDK — EVENT QUEUE (BATCH, FLUSH, RETRY, OFFLINE PERSISTENCE)
// Updated for multi-VM Web3 event types
// =============================================================================

import type { AetherEvent, RetryConfig, ConsentState } from '../types';
import { storage } from '../utils';

const QUEUE_STORAGE_KEY = 'event_queue';
const MAX_STORED_EVENTS = 1000;

interface QueueConfig {
  endpoint: string;
  apiKey: string;
  batchSize: number;
  flushInterval: number;
  maxQueueSize: number;
  retry: Required<RetryConfig>;
  headers: Record<string, string>;
  onError?: (error: Error, events: AetherEvent[]) => void;
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
 * Events not listed here are always allowed through.
 */
const CONSENT_MAP: Record<string, string> = {
  // Core analytics
  track: 'analytics', page: 'analytics', screen: 'analytics',
  heartbeat: 'analytics', error: 'analytics', performance: 'analytics',
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
  // Agent
  agent_task: 'agent', agent_decision: 'agent', a2h_interaction: 'agent',
  // x402
  x402_payment: 'commerce',
};

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
    this.queue.push(event);
    if (this.queue.length >= this.config.batchSize) this.flush();
    if (this.queue.length >= this.config.maxQueueSize) this.flush();
  }

  async flush(): Promise<void> {
    if (this.isFlushing || this.queue.length === 0 || this.isDestroyed) return;

    this.isFlushing = true;
    const batch = this.queue.splice(0, this.config.batchSize);
    const allowedEvents = this.filterByConsent(batch);

    if (allowedEvents.length === 0) {
      this.isFlushing = false;
      return;
    }

    try {
      await this.sendBatch(allowedEvents);
      this.persistQueue();
    } catch (error) {
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
      if (!purpose) return true; // Unknown event types are allowed through
      return (consent as unknown as Record<string, boolean>)[purpose] === true;
    });
  }

  private async sendBatch(events: AetherEvent[], retryCount = 0): Promise<void> {
    const payload = JSON.stringify({
      batch: events,
      sentAt: new Date().toISOString(),
      context: { library: { name: '@aether/sdk', version: '8.7.1' } },
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
    if (typeof navigator === 'undefined' || !navigator.sendBeacon) return false;
    const payload = JSON.stringify({
      batch: this.filterByConsent(events),
      sentAt: new Date().toISOString(),
      context: { library: { name: '@aether/sdk', version: '8.7.1' } },
    });
    const blob = new Blob([payload], { type: 'application/json' });
    // API key sent via query param (sendBeacon does not support custom headers)
    return navigator.sendBeacon(
      `${this.config.endpoint}/v1/batch?token=${encodeURIComponent(this.config.apiKey)}`,
      blob,
    );
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
        this.sendBeacon(this.queue); this.queue = [];
      }
    });
    window.addEventListener('pagehide', () => {
      if (this.queue.length > 0) { this.sendBeacon(this.queue); this.queue = []; }
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
