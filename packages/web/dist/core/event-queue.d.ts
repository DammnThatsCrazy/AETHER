import type { AetherEvent, RetryConfig, ConsentState } from '../types';
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
    private sendBeacon;
    private startFlushTimer;
    private setupLifecycleHandlers;
    private persistQueue;
    private restoreQueue;
    private sleep;
}
export {};
