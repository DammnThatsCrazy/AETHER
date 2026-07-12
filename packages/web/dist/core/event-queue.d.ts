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
     * (packages/shared/ingestion-contract.ts). Falls back to treating the whole
     * batch as accepted if the body is absent or unparseable, so health reporting
     * never blocks a successful (2xx) delivery.
     */
    private parseIngestCounters;
    private sendBeacon;
    private startFlushTimer;
    private setupLifecycleHandlers;
    private persistQueue;
    private restoreQueue;
    private sleep;
}
