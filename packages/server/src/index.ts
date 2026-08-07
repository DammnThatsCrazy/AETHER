// =============================================================================
// Aether Server SDK — Node.js server-side event observation client
// =============================================================================
//
// Security invariants:
//   - execution_by_aether is never set (Aether observes, never executes)
//   - explicit-opt-in purposes (credit, location, financial_activity,
//     economic_observability, cross_chain_observability, fraud_prevention)
//     are never granted by grantAll()
//   - sensitive fields are scrubbed before transmission (scrubSensitiveFields)
//   - no API keys, secrets, or sensitive payloads in event properties
//
// Usage:
//   const aether = new AetherServerSDK({ writeKey: '...', consent: { analytics: true } });
//   aether.track({ type: 'api_request_observed', properties: { ... } });
//   await aether.flush();

import os from 'node:os';
import { randomUUID } from 'node:crypto';

import { EVENT_FAMILY, CONTRACT_SCHEMA_VERSION } from '@aether/shared';
// Registry-generated purpose sets — hand-written copies here drifted to 9 of
// the registry's 12 purposes before being replaced with the canonical source.
import { CONSENT_PURPOSES as ALL_PURPOSES, EXPLICIT_OPT_IN_PURPOSES } from '@aether/shared/consent';
import type { EventType } from '@aether/shared';
import { EventQueue } from './queue';
import { sendBatch } from './transport';
import { scrubSensitiveFields } from './scrubber';
import { SdkHealthTracker } from './health';
import { makeServerClient } from './client';
import type { AetherServerConfig, ServerEvent, ServerConsentState, ConsentPurpose, BatchHealth } from './types';

/**
 * A server event's `type` must be a canonical registry event type
 * (packages/shared/events.ts EVENT_FAMILY). Unknown types are dropped before
 * transmission — the backend rejects them anyway, and Aether observes only
 * registry-governed events. Mirrors the web SDK's observe() canonical gate.
 */
function isCanonicalEventType(type: string): type is EventType {
  return Object.prototype.hasOwnProperty.call(EVENT_FAMILY, type);
}

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


const DEFAULT_ENDPOINT = 'https://ingest.aether.so/v1/batch';

export class AetherServerSDK {
  // application stays optional-valued: Required<> would strip its undefined,
  // but an unconfigured host has no product identity to fabricate.
  private readonly config: Required<Omit<AetherServerConfig, 'application'>> &
    Pick<AetherServerConfig, 'application'>;
  private consent: ServerConsentState;
  private readonly queue: EventQueue;
  private readonly health: SdkHealthTracker;
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  private flushing = false;
  private lastBatchHealth: BatchHealth | null = null;
  /** Monotonic per-process event index, stamped into context.sequence.event so
   *  the backend can detect gaps/reordering in this emitter's stream. */
  private eventSequence = 0;
  /** Per-process session/anonymous identity minted once. The canonical
   *  ingestion envelope requires non-empty sessionId and anonymousId; a caller
   *  may override either per event (event.sessionId / event.anonymousId). */
  private readonly sessionId = randomUUID();
  private readonly anonymousId = randomUUID();

  /** Typed helpers for common server observation patterns. */
  readonly observe: ReturnType<typeof makeServerClient>;

  constructor(config: AetherServerConfig) {
    this.config = {
      writeKey: config.writeKey,
      endpoint: config.endpoint ?? DEFAULT_ENDPOINT,
      consent: config.consent ?? {},
      application: config.application,
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
   * Grant all non-explicit-opt-in purposes. Explicit-opt-in purposes
   * (EXPLICIT_OPT_IN_PURPOSES from the registry) must each be granted
   * individually, e.g. grant(['credit']).
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
    if (!isCanonicalEventType(event.type)) {
      // Not a canonical registry event type — drop it rather than ship a type
      // the backend will reject. Aether observes only registry-governed events.
      if (typeof console !== 'undefined' && typeof console.warn === 'function') {
        console.warn(`[aether] track(): '${event.type}' is not a canonical event type — ignored`);
      }
      return;
    }
    const ts = event.timestamp ?? new Date().toISOString();
    const prepared = {
      ...event,
      // Canonical BaseEvent identity the ingestion API requires (id/sessionId/
      // anonymousId, all non-empty). id is minted per event so retries dedupe;
      // sessionId/anonymousId fall back to the per-process identity.
      // `||` (not `??`) so an empty-string id/sessionId/anonymousId is also
      // replaced — the backend BaseEvent requires all three to be non-empty.
      id: event.id || randomUUID(),
      sessionId: event.sessionId || this.sessionId,
      anonymousId: event.anonymousId || this.anonymousId,
      timestamp: ts,
      properties: event.properties ? scrubSensitiveFields(event.properties) : undefined,
      context: {
        // Surface identifies the emitting client so the backend can attribute
        // every event to its origin plane. Stamped for all server-SDK events.
        surface: 'server',
        // Envelope schema version this emitter conforms to (single source:
        // CONTRACT_SCHEMA_VERSION in @aether/shared).
        schemaVersion: CONTRACT_SCHEMA_VERSION,
        // Host OS identity in the canonical envelope shape.
        operatingSystem: { name: os.type(), version: os.release() },
        // Emitting product identity, when the host service declares it in config.
        application: this.config.application,
        // Monotonic ordering counter for gap/reorder detection at ingest.
        sequence: { event: this.eventSequence++ },
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
        if (result.ok && result.counters) {
          // Confirmed delivery: credit only what the backend reported, never a
          // fabricated "the whole batch landed".
          const counters = result.counters;
          this.health.recordDelivered(item.events.length);
          const health: BatchHealth = {
            accepted: counters.accepted,
            duplicate: counters.duplicate,
            rejected: counters.rejected,
            // Server SDK sends consent as a hint and does not drop locally.
            dropped_by_consent: 0,
            queue_depth: this.queue.size,
          };
          this.lastBatchHealth = health;
          this.config.onBatchResult(health);
        } else if (result.ok) {
          // 2xx but no parseable acceptance counters — delivery is unconfirmed,
          // so requeue rather than assume the batch landed. The minted event id
          // makes the retry idempotent (backend dedups → duplicate).
          this.queue.requeue(item);
          this.health.recordFailed(item.events.length);
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
    // Deny-by-default across the full registry vocabulary, then apply the
    // host's explicit grants.
    const state = Object.fromEntries(
      ALL_PURPOSES.map((p) => [p, false]),
    ) as unknown as ServerConsentState;
    return { ...state, ...partial };
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
