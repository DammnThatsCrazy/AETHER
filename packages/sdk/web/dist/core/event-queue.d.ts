import type { AetherEvent, RetryConfig, ConsentState, BatchHealth } from '../types';
export type { BatchHealth } from '../types';
export type DroppedEventReason = 'consent_denied' | 'schema_invalid' | 'queue_full' | 'offline_expired' | 'retry_exhausted' | 'manifest_blocked' | 'unsupported_sdk_version' | 'payload_too_large' | 'auth_failed' | 'shutdown_unflushed';
interface DroppedEventCounts {
    consent_denied: number;
    schema_invalid: number;
    queue_full: number;
    offline_expired: number;
    retry_exhausted: number;
    manifest_blocked: number;
    unsupported_sdk_version: number;
    payload_too_large: number;
    auth_failed: number;
    shutdown_unflushed: number;
}
interface QueueConfig {
    endpoint: string;
    apiKey: string;
    /**
     * Site this install is bound to. Sent as `X-Aether-Site` on every batch —
     * including the unload path — because the backend refuses a publishable
     * credential that declares no site. Present whenever the config came from
     * the snippet (see types.ts AetherConfig.siteId).
     */
    siteId?: string;
    batchSize: number;
    flushInterval: number;
    maxQueueSize: number;
    retry: Required<RetryConfig>;
    headers: Record<string, string>;
    onError?: (error: Error, events: AetherEvent[]) => void;
    /** Called after each batch send attempt with round-trip latency and success. */
    onAttempt?: (latencyMs: number, success: boolean) => void;
    /**
     * Called after each processed batch with per-batch health counters
     * (accepted / duplicate / rejected / dropped_by_consent / queue_depth).
     */
    onBatchResult?: (health: BatchHealth) => void;
}
export declare class EventQueue {
    private queue;
    /** localStorage key for this install's persisted queue (see installStorageKey). */
    private readonly storageKey;
    private config;
    private flushTimer;
    private isFlushing;
    private isDestroyed;
    private consent;
    private droppedCounts;
    private lastFlushStatus;
    /** Epoch ms until which sending is paused after a 401/403; 0 = not paused. */
    private authPausedUntil;
    /** Current auth pause length; doubles per consecutive rejection up to the cap. */
    private authPauseMs;
    /** onError fires once per auth incident, not once per retry. */
    private authErrorReported;
    constructor(config: Omit<Partial<QueueConfig>, 'retry'> & Pick<QueueConfig, 'endpoint' | 'apiKey'> & {
        retry?: RetryConfig;
    });
    setConsent(consent: ConsentState): void;
    enqueue(event: AetherEvent): void;
    /**
     * Hold the queue to `maxQueueSize` by evicting the oldest evictable events
     * (consent and identify are protected). Each eviction is a real drop and is
     * counted as `queue_full`. If every queued event is protected, the oldest is
     * evicted anyway so the bound always holds.
     */
    private enforceCap;
    /** True while sending is paused after the API rejected the credential. */
    isAuthPaused(): boolean;
    /**
     * Public API: get diagnostics including dropped-event counts by reason.
     */
    getDiagnostics(): {
        droppedEvents: DroppedEventCounts;
        queueDepth: number;
        lastFlushStatus: 'pending' | 'flushing' | 'success' | 'failed' | 'no_events';
        authPaused: boolean;
    };
    /**
     * Public API: get current queue depth.
     */
    getQueueDepth(): number;
    /**
     * Public API: get last flush status.
     */
    getLastFlushStatus(): 'pending' | 'flushing' | 'success' | 'failed' | 'no_events';
    /**
     * Public API: flush the queue immediately.
     */
    flush(): Promise<void>;
    private clearAuthPause;
    get size(): number;
    destroy(): void;
    private filterByConsent;
    private sendBatch;
    /**
     * Parse per-batch acceptance counters from the /v1/batch response body.
     * The backend BatchResponse uses `accepted` / `duplicates` / `rejected`
     * (packages/shared/ingestion-contract.ts). Returns `undefined` when the
     * body is absent, non-JSON, or carries none of those keys — an ambiguous
     * 2xx. Callers MUST NOT treat `undefined` as success: a 2xx only confirms
     * the request was received, not that every event landed, and crediting the
     * whole batch on an ambiguous body would silently hide real drops. See
     * `AmbiguousDeliveryError` for how the caller (`sendBatch`) handles this.
     */
    private parseIngestCounters;
    private sendBeacon;
    private startFlushTimer;
    private setupLifecycleHandlers;
    private persistQueue;
    private restoreQueue;
    private sleep;
}
