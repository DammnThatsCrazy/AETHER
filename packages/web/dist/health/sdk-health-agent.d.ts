import type { EventQueue } from '../core/event-queue';
export interface SDKHealthAgentConfig {
    /** Aether backend base URL, e.g. https://api.aether.xyz */
    endpoint: string;
    /** Tenant API key */
    apiKey: string;
    /** Stable UUID generated once per SDK installation (persisted in localStorage) */
    sdkId: string;
    /** App version string */
    appVersion?: string;
    /** Runtime platform label */
    platform?: 'web' | 'ios' | 'android' | 'react-native' | 'node' | 'other';
    /** Heartbeat emission interval in ms (default 60 000) */
    heartbeatIntervalMs?: number;
    /** Manifest refresh interval in ms (default 300 000) */
    manifestRefreshMs?: number;
    /** Config version string (from last fetched manifest) */
    configVersion?: string;
    /** Rollout cohort label */
    rolloutCohort?: string;
    /** Secret for HMAC signing (must match SDK_CONFIG_SECRET on backend) */
    signingSecret?: string;
}
export interface SDKHeartbeatPayload {
    sdk_id: string;
    sdk_version: string;
    platform: string;
    app_version: string;
    queue_depth: number;
    retry_count: number;
    dropped_events: number;
    endpoint_latency_ms: number;
    ingestion_success_rate: number;
    schema_hash: string;
    auth_valid: boolean;
    consent_valid: boolean;
    wallet_connected: boolean;
    config_version: string;
    rollout_cohort: string;
}
export interface SDKManifest {
    manifest_version: string;
    min_sdk_version: string;
    schema_version: string;
    rollout_percentage: number;
    features: Record<string, boolean>;
    endpoints: Record<string, string>;
    flags: Record<string, unknown>;
    published_at: string;
    signature: string;
}
export type ManifestUpdateCallback = (manifest: SDKManifest) => void;
export declare class SDKHealthAgent {
    private readonly config;
    private readonly eventQueue;
    private metrics;
    private heartbeatTimer;
    private manifestTimer;
    private currentManifest;
    private manifestCallbacks;
    private isRunning;
    constructor(config: SDKHealthAgentConfig, eventQueue: EventQueue);
    /** Start the health agent — emits first heartbeat immediately. */
    start(): void;
    /** Stop the health agent and clear all timers. */
    stop(): void;
    /** Register a callback to be invoked when the manifest is updated. */
    onManifestUpdate(callback: ManifestUpdateCallback): void;
    /** Record a dropped event (called by EventQueue on consent filter / error). */
    recordDroppedEvent(): void;
    /** Record a successful event dispatch. */
    recordAttempt(latencyMs: number, success: boolean): void;
    sendHeartbeat(): Promise<void>;
    fetchManifest(): Promise<SDKManifest | null>;
    /** Return the currently cached manifest (null if not yet fetched). */
    getManifest(): SDKManifest | null;
    private buildHeartbeatPayload;
    private computeSchemaHash;
    private verifyManifestSignature;
    private hexToBytes;
    private sleep;
}
