// Server SDK types — the consent vocabulary is the canonical, registry-generated
// contract re-exported from @aether/shared, so this SDK cannot drift from the
// registry again (a hand-written copy here shipped 9 of 12 purposes).

export type { ConsentPurpose } from '@aether/shared/consent';

export interface ServerConsentState {
  analytics: boolean;
  marketing: boolean;
  personalization: boolean;
  web3: boolean;
  agent: boolean;
  commerce: boolean;
  /** Always requires explicit opt-in — never granted by grantAll(). */
  credit: boolean;
  /** Always requires explicit opt-in — never granted by grantAll(). */
  location: boolean;
  /** Always requires explicit opt-in — gates agent trading orders, fills, positions, portfolio, and performance snapshots. */
  financial_activity: boolean;
  /** Always requires explicit opt-in — read-only stablecoin economic intelligence. */
  economic_observability: boolean;
  /** Always requires explicit opt-in — read-only cross-network interoperability intelligence. */
  cross_chain_observability: boolean;
  /** Always requires explicit opt-in — bot detection, fraud/abuse signals, platform security monitoring. */
  fraud_prevention: boolean;
}

/**
 * Per-batch ingestion health counters (Truth Kernel §2.8).
 *
 * `accepted` / `duplicate` / `rejected` are parsed from the backend
 * BatchResponse (packages/shared/ingestion-contract.ts). `dropped_by_consent`
 * and `queue_depth` are SDK-side truths surfaced alongside them: the server SDK
 * does not consent-drop locally (consent is sent as a hint), so
 * `dropped_by_consent` is 0 unless a future local gate drops events;
 * `queue_depth` reflects the in-process queue backlog after the batch is sent.
 */
export interface BatchHealth {
  accepted: number;
  duplicate: number;
  rejected: number;
  dropped_by_consent: number;
  queue_depth: number;
}

/**
 * Passed to `AetherServerConfig.onSpoolDrop` when the durable queue's
 * disk-space bound (`maxSpoolBytes`) rejects an event (Reliability Phase 2
 * §2, M5). Surfacing the drop is mandatory — events are never lost silently.
 */
export interface SpoolDropInfo {
  /** Absolute path of the spool file that hit its byte bound. */
  spoolPath: string;
  /** The configured `maxSpoolBytes` budget that was exceeded. */
  maxSpoolBytes: number;
  /** Live (not-yet-delivered) spool footprint, in bytes, at the drop. */
  liveBytes: number;
  /** Bytes the rejected event's spool record would have added. */
  attemptedBytes: number;
  /** Running count of events this client has dropped for this reason. */
  droppedTotal: number;
}

export interface ServerEvent {
  type: string;
  userId?: string;
  anonymousId?: string;
  sessionId?: string;
  properties?: Record<string, unknown>;
  context?: Record<string, unknown>;
  timestamp?: string;
  /**
   * Client-generated canonical event id — the backend idempotency key
   * (packages/shared/ingestion-contract.ts). Minted per event when omitted so
   * retries dedupe instead of duplicating. Named `id` to match the canonical
   * BaseEvent envelope the ingestion API validates.
   */
  id?: string;
}

export interface AetherServerConfig {
  writeKey: string;
  endpoint?: string;
  /** Consent state for server-side events. */
  consent?: Partial<ServerConsentState>;
  /**
   * Canonical envelope: emitting product identity stamped as
   * context.application on every event (distinct from the SDK library).
   */
  application?: {
    name?: string;
    version?: string;
    build?: string;
    environment?: string;
    namespace?: string;
  };
  /** Max events in memory before flushing. Default 100. */
  flushAt?: number;
  /** Flush interval in ms. Default 5000. */
  flushInterval?: number;
  /** Max queue size. Default 1000. */
  maxQueueSize?: number;
  /** User-Agent header value. */
  userAgent?: string;
  /**
   * Called after each successfully delivered batch with per-batch ingestion
   * health counters (Truth Kernel §2.8).
   */
  onBatchResult?: (health: BatchHealth) => void;

  // --- Durable event queue (Reliability Phase 2 §2, milestone M5) ---------
  //
  // Opt-in disk-backed durability. When enabled, queued events are mirrored
  // to a local append-only spool so a crash/restart between track() and a
  // confirmed send REPLAYS them on the next client init instead of losing
  // them. Delivered events are pruned from the spool; the spool's on-disk
  // footprint is hard-bounded by `maxSpoolBytes`.
  //
  // Selection: durability is on when EITHER `durable: true` OR `spoolPath`
  // is set (providing a spoolPath implies durable). It is OFF by default —
  // the in-memory queue is used — so existing consumers are unaffected.
  //
  // Intended default flip: once the durable path has soaked in production,
  // the default becomes "durable whenever a writable spool location is
  // available"; today it stays strictly opt-in to avoid surprising hosts
  // with unexpected disk writes or read-only-filesystem warnings. See the
  // note on AetherServerSDK's constructor in index.ts.

  /**
   * Enable the disk-backed durable queue. Defaults to false. When true
   * without a `spoolPath`, a stable per-writeKey file under the OS temp dir
   * is used (see AetherServerSDK's default spool path).
   */
  durable?: boolean;
  /**
   * Filesystem path for the durable spool file. Setting this implies
   * `durable: true`. Choose a location the process may write and that
   * survives restarts (a persistent volume for strongest durability).
   */
  spoolPath?: string;
  /**
   * Hard upper bound on the durable spool's live (not-yet-delivered)
   * footprint, in bytes. Once accepting an event would push the spool past
   * this bound, the event is REJECTED (never silently dropped): it is not
   * queued, `onSpoolDrop` fires, and — if no handler is set — the SDK warns.
   * Compaction keeps the physical file within a small constant factor of
   * this bound. Default 5 MiB. Ignored when durability is off.
   */
  maxSpoolBytes?: number;
  /**
   * Called when a durable event is rejected because the spool hit its
   * `maxSpoolBytes` bound, so hosts can meter/alert on backpressure instead
   * of losing events silently. No-op when durability is off.
   */
  onSpoolDrop?: (info: SpoolDropInfo) => void;
}
