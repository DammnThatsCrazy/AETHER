import type { AetherEvent, RetryConfig, ConsentState, BatchHealth } from '../types';
export type { BatchHealth } from '../types';
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
    /**
     * Called after each processed batch with per-batch health counters
     * (accepted / duplicate / rejected / dropped_by_consent / queue_depth).
     */
    onBatchResult?: (health: BatchHealth) => void;
}
export declare class EventQueue {
    private queue;
    private config;
    private flushTimer;
    private isFlushing;
    private isDestroyed;
    private consent;
    constructor(config: Omit<Partial<QueueConfig>, 'retry'> & Pick<QueueConfig, 'endpoint' | 'apiKey'> & {
        retry?: RetryConfig;
    });
    setConsent(consent: ConsentState): void;
    enqueue(event: AetherEvent): void;
    flush(): Promise<void>;
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
