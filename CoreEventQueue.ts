// =============================================================================
// AETHER SDK — EVENT QUEUE (BATCH, FLUSH, RETRY, OFFLINE PERSISTENCE)
// =============================================================================

import type { AetherEvent, RetryConfig, ConsentState } from './WebSDKTypes(CoreTypeDefinitions)';
import { storage } from './SDKUtilityFunctions';

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

export class EventQueue {
  private queue: AetherEvent[] = [];
  private config: QueueConfig;
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private isFlushing = false;
  private isDestroyed = false;
  private consent: ConsentState | null = null;

  constructor(config: Partial<QueueConfig> & Pick<QueueConfig, 'endpoint' | 'apiKey'>) {
    this.config = {
      batchSize: 10,
      flushInterval: 5000,
      maxQueueSize: 100,
      retry: { ...DEFAULT_RETRY, ...config.retry },
      headers: {},
      ...config,
    };
    this.restoreQueue();
    this.startFlushTimer();
    this.setupLifecycleHandlers();
  }

  /** Set current consent state — events are filtered at flush time */
  setConsent(consent: ConsentState): void {
    this.consent = consent;
  }

  /** Add an event to the queue */
  enqueue(event: AetherEvent): void {
    if (this.isDestroyed) return;

    this.queue.push(event);

    // Auto-flush when queue reaches batch size
    if (this.queue.length >= this.config.batchSize) {
      this.flush();
    }

    // Hard flush when queue hits max
    if (this.queue.length >= this.config.maxQueueSize) {
      this.flush();
    }
  }

  /** Flush all queued events to the server */
  async flush(): Promise<void> {
    if (this.isFlushing || this.queue.length === 0 || this.isDestroyed) return;

    this.isFlushing = true;
    const batch = this.queue.splice(0, this.config.batchSize);

    // Filter events based on consent
    const allowedEvents = this.filterByConsent(batch);

    if (allowedEvents.length === 0) {
      this.isFlushing = false;
      return;
    }

    try {
      await this.sendBatch(allowedEvents);
      this.persistQueue();
    } catch (error) {
      // Put events back at the front of the queue for retry
      this.queue.unshift(...allowedEvents);
      this.persistQueue();
      this.config.onError?.(error as Error, allowedEvents);
    } finally {
      this.isFlushing = false;

      // Continue flushing if there are more events
      if (this.queue.length >= this.config.batchSize) {
        this.flush();
      }
    }
  }

  /** Get current queue size */
  get size(): number {
    return this.queue.length;
  }

  /** Destroy the queue and clean up */
  destroy(): void {
    this.isDestroyed = true;
    if (this.flushTimer) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }
    // Attempt final flush
    if (this.queue.length > 0) {
      this.sendBeacon(this.queue);
    }
    this.queue = [];
  }

  // ===========================================================================
  // PRIVATE METHODS
  // ===========================================================================

  private filterByConsent(events: AetherEvent[]): AetherEvent[] {
    if (!this.consent) return events; // No consent state = allow all (pre-consent)

    return events.filter((event) => {
      // Consent events always pass through
      if (event.type === 'consent') return true;

      // Analytics consent covers behavioral tracking
      if (['track', 'page', 'screen', 'performance', 'heartbeat', 'error'].includes(event.type)) {
        return this.consent!.analytics;
      }

      // Marketing consent covers campaign/conversion
      if (['conversion', 'experiment'].includes(event.type)) {
        return this.consent!.marketing;
      }

      // Web3 consent covers wallet/transaction
      if (['wallet', 'transaction'].includes(event.type)) {
        return this.consent!.web3;
      }

      // Identity events require analytics consent
      if (event.type === 'identify') {
        return this.consent!.analytics;
      }

      return true;
    });
  }

  private async sendBatch(events: AetherEvent[], retryCount = 0): Promise<void> {
    const payload = JSON.stringify({
      batch: events,
      sentAt: new Date().toISOString(),
      context: {
        library: { name: '@aether/sdk', version: '8.7.0' },
      },
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
        const retryAfter = parseInt(response.headers.get('Retry-After') || '5', 10);
        await this.sleep(retryAfter * 1000);
        return this.sendBatch(events, retryCount + 1);
      }

      throw new Error(`Aether API error: ${response.status} ${response.statusText}`);
    }
  }

  /** Fallback: use Navigator.sendBeacon for unload events */
  private sendBeacon(events: AetherEvent[]): boolean {
    if (typeof navigator === 'undefined' || !navigator.sendBeacon) return false;

    const payload = JSON.stringify({
      batch: this.filterByConsent(events),
      sentAt: new Date().toISOString(),
      context: { library: { name: '@aether/sdk', version: '__SDK_VERSION__' } },
    });

    const blob = new Blob([payload], { type: 'application/json' });
    return navigator.sendBeacon(`${this.config.endpoint}/v1/batch?key=${this.config.apiKey}`, blob);
  }

  private startFlushTimer(): void {
    this.flushTimer = setInterval(() => {
      if (this.queue.length > 0) {
        this.flush();
      }
    }, this.config.flushInterval);
  }

  private setupLifecycleHandlers(): void {
    if (typeof window === 'undefined') return;

    // Flush on page hide (tab switch, minimize, navigate away)
    window.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden' && this.queue.length > 0) {
        this.sendBeacon(this.queue);
        this.queue = [];
      }
    });

    // Flush on page unload
    window.addEventListener('pagehide', () => {
      if (this.queue.length > 0) {
        this.sendBeacon(this.queue);
        this.queue = [];
      }
    });

    // Handle online/offline
    window.addEventListener('online', () => {
      if (this.queue.length > 0) this.flush();
    });
  }

  private persistQueue(): void {
    const toStore = this.queue.slice(0, MAX_STORED_EVENTS);
    storage.set(QUEUE_STORAGE_KEY, toStore);
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
