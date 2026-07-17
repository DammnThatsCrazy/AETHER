// =============================================================================
// Aether Server SDK — Node.js server-side event observation client
// =============================================================================
//
// Security invariants:
//   - execution_by_aether is never set (Aether observes, never executes)
//   - credit and location consent require explicit opt-in; grantAll() excludes them
//   - sensitive fields are scrubbed before transmission (scrubSensitiveFields)
//   - no API keys, secrets, or sensitive payloads in event properties
//
// Usage:
//   const aether = new AetherServerSDK({ writeKey: '...', consent: { analytics: true } });
//   aether.track({ type: 'api_request_observed', properties: { ... } });
//   await aether.flush();

import { EventQueue } from './queue';
import { sendBatch } from './transport';
import { scrubSensitiveFields } from './scrubber';
import { SdkHealthTracker } from './health';
import { makeServerClient } from './client';
import type { AetherServerConfig, ServerEvent, ServerConsentState, ConsentPurpose, BatchHealth } from './types';

export { scrubSensitiveFields } from './scrubber';
export { makeServerClient } from './client';
export type { AetherServerConfig, ServerEvent, ServerConsentState, ConsentPurpose, BatchHealth } from './types';
export type { SdkHealthSnapshot } from './health';
export {
  buildAgentEvent,
  buildMCPObservation,
  buildToolInvocation,
  buildRiskSignal,
} from './agentic';
export type { AgentEventEnvelope } from './agentic';

const EXPLICIT_OPT_IN_PURPOSES: readonly ConsentPurpose[] = ['credit', 'location', 'financial_activity'];
const ALL_PURPOSES: readonly ConsentPurpose[] = [
  'analytics', 'marketing', 'personalization', 'web3', 'agent', 'commerce',
  'credit', 'location', 'financial_activity',
];
const DEFAULT_ENDPOINT = 'https://ingest.aether.so/v1/batch';

export class AetherServerSDK {
  private readonly config: Required<AetherServerConfig>;
  private consent: ServerConsentState;
  private readonly queue: EventQueue;
  private readonly health: SdkHealthTracker;
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  private flushing = false;
  private lastBatchHealth: BatchHealth | null = null;

  /** Typed helpers for common server observation patterns. */
  readonly observe: ReturnType<typeof makeServerClient>;

  constructor(config: AetherServerConfig) {
    this.config = {
      writeKey: config.writeKey,
      endpoint: config.endpoint ?? DEFAULT_ENDPOINT,
      consent: config.consent ?? {},
      flushAt: config.flushAt ?? 100,
      flushInterval: config.flushInterval ?? 5000,
      maxQueueSize: config.maxQueueSize ?? 1000,
      userAgent: config.userAgent ?? '@aether/server',
      onBatchResult: config.onBatchResult ?? (() => { /* no-op */ }),
    };
    this.consent = this.buildConsentState(config.consent ?? {});
    this.queue = new EventQueue({ maxSize: this.config.maxQueueSize });
    this.health = new SdkHealthTracker();
    this.observe = makeServerClient((event) => this.track(event));
    this.scheduleFlush();
  }

  /** Grant consent for specified purposes. */
  grant(purposes: ConsentPurpose[]): void {
    for (const p of purposes) {
      (this.consent as unknown as Record<string, boolean>)[p] = true;
    }
  }

  /**
   * Grant all non-explicit-opt-in purposes (excludes credit and location).
   * To grant credit or location, call grant(['credit']) or grant(['location']) explicitly.
   */
  grantAll(): void {
    this.grant(ALL_PURPOSES.filter((p) => !EXPLICIT_OPT_IN_PURPOSES.includes(p)));
  }

  /** Revoke consent for specified purposes. */
  revoke(purposes: ConsentPurpose[]): void {
    for (const p of purposes) {
      (this.consent as unknown as Record<string, boolean>)[p] = false;
    }
  }

  /** Get current consent state. */
  getConsent(): ServerConsentState {
    return { ...this.consent };
  }

  /** Queue a single event for batched delivery. */
  track(event: ServerEvent): void {
    const ts = event.timestamp ?? new Date().toISOString();
    const prepared = {
      ...event,
      timestamp: ts,
      properties: event.properties ? scrubSensitiveFields(event.properties) : undefined,
      context: {
        // Temporal provenance: server-side events are stamped by the server
        // clock in the server's zone context — never a fabricated device
        // offset. Caller-supplied context (e.g. relayed device evidence) wins.
        timeZoneSource: 'server',
        clockSource: 'server',
        ...event.context,
      },
    };
    const enqueued = this.queue.enqueue({
      writeKey: this.config.writeKey,
      events: [prepared],
    });
    if (enqueued) {
      this.health.recordQueued(1);
    }
    if (this.queue.size >= this.config.flushAt) {
      void this.flush();
    }
  }

  /** Flush all queued events immediately. */
  async flush(): Promise<void> {
    if (this.flushing) return;
    this.flushing = true;
    try {
      const grantedConsents = Object.entries(this.consent)
        .filter(([, v]) => v === true)
        .map(([k]) => k);

      let item = this.queue.dequeueReady();
      while (item) {
        const result = await sendBatch(
          {
            endpoint: this.config.endpoint,
            writeKey: this.config.writeKey,
            userAgent: this.config.userAgent,
          },
          item.events,
          grantedConsents,
        );
        if (result.ok) {
          this.health.recordDelivered(item.events.length);
          const health: BatchHealth = {
            accepted: result.counters?.accepted ?? item.events.length,
            duplicate: result.counters?.duplicate ?? 0,
            rejected: result.counters?.rejected ?? 0,
            // Server SDK sends consent as a hint and does not drop locally.
            dropped_by_consent: 0,
            queue_depth: this.queue.size,
          };
          this.lastBatchHealth = health;
          this.config.onBatchResult(health);
        } else if (result.status >= 500 || result.status === 429 || result.status === 0) {
          this.queue.requeue(item);
          this.health.recordFailed(item.events.length);
        } else {
          this.health.recordFailed(item.events.length);
        }
        item = this.queue.dequeueReady();
      }
    } catch (err) {
      this.health.recordFlushError(String(err));
    } finally {
      this.flushing = false;
    }
  }

  /** Get SDK health snapshot. */
  healthSnapshot() {
    return this.health.snapshot();
  }

  /**
   * Per-batch ingestion health from the most recently delivered batch
   * (Truth Kernel §2.8), or null if no batch has been delivered yet.
   */
  lastBatchResult(): BatchHealth | null {
    return this.lastBatchHealth;
  }

  /** Flush remaining events and stop the flush timer. */
  async shutdown(): Promise<void> {
    if (this.flushTimer !== null) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }
    await this.flush();
  }

  private buildConsentState(partial: Partial<ServerConsentState>): ServerConsentState {
    return {
      analytics: false,
      marketing: false,
      personalization: false,
      web3: false,
      agent: false,
      commerce: false,
      credit: false,
      location: false,
      financial_activity: false,
      ...partial,
    };
  }

  private scheduleFlush(): void {
    this.flushTimer = setTimeout(async () => {
      await this.flush();
      this.scheduleFlush();
    }, this.config.flushInterval);
    if (this.flushTimer.unref) this.flushTimer.unref();
  }
}

// External Agent Telemetry Plane V1 — re-exported after the class definition
// because agent-telemetry extends AetherServerSDK from this module.
export { AgentTelemetryClient, validateAgentDeploymentContext } from './agent-telemetry';
export type { AgentTelemetryConfig } from './agent-telemetry';
export type { AgentDeploymentContext } from '@aether/shared';
