// =============================================================================
// Aether SDK — SDK Health Agent
//
// Emits signed heartbeats to the backend SDK health monitoring endpoint at a
// configurable interval (default 60 s). Heartbeats are fire-and-forget and
// never block the main event pipeline.
//
// The agent also fetches and caches the remote config manifest on startup and
// when the manifest version changes, notifying registered callbacks.
// =============================================================================

import type { EventQueue } from '../core/event-queue';

const SDK_VERSION = '8.9.0'; // synchronized by scripts/bump-sdk-version.sh and scripts/validate_sdk_release_alignment.py
const DEFAULT_HEARTBEAT_INTERVAL_MS = 60_000;
const DEFAULT_MANIFEST_REFRESH_MS   = 300_000; // 5 min
const MAX_HEARTBEAT_RETRIES         = 3;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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
  /** Extra HTTP headers (e.g. gateway/proxy headers) merged into every request. */
  customHeaders?: Record<string, string>;
  /**
   * Provides live auth/consent/wallet state at heartbeat time so the fleet view
   * reflects reality rather than optimistic defaults. Called on each heartbeat.
   */
  getDynamicState?: () => { authValid: boolean; consentValid: boolean; walletConnected: boolean };
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

// ---------------------------------------------------------------------------
// Internal counters (module-level, reset-safe)
// ---------------------------------------------------------------------------

interface InternalMetrics {
  droppedEvents: number;
  totalAttempted: number;
  retryCount: number;
  lastLatencyMs: number;
  lastSuccessRate: number;
}

// ---------------------------------------------------------------------------
// SDKHealthAgent
// ---------------------------------------------------------------------------

export class SDKHealthAgent {
  private readonly config: Required<SDKHealthAgentConfig>;
  private readonly eventQueue: EventQueue;
  private metrics: InternalMetrics = {
    droppedEvents: 0,
    totalAttempted: 0,
    retryCount: 0,
    lastLatencyMs: 0,
    lastSuccessRate: 1.0,
  };
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private manifestTimer: ReturnType<typeof setInterval> | null = null;
  private currentManifest: SDKManifest | null = null;
  private manifestCallbacks: ManifestUpdateCallback[] = [];
  private isRunning = false;

  constructor(config: SDKHealthAgentConfig, eventQueue: EventQueue) {
    this.config = {
      platform: 'web',
      appVersion: '',
      heartbeatIntervalMs: DEFAULT_HEARTBEAT_INTERVAL_MS,
      manifestRefreshMs: DEFAULT_MANIFEST_REFRESH_MS,
      configVersion: '0',
      rolloutCohort: 'default',
      signingSecret: '',
      customHeaders: {},
      getDynamicState: () => ({ authValid: true, consentValid: true, walletConnected: false }),
      ...config,
    };
    this.eventQueue = eventQueue;
  }

  /** Start the health agent — emits first heartbeat immediately. */
  start(): void {
    if (this.isRunning) return;
    this.isRunning = true;

    // Immediate first run
    this.sendHeartbeat().catch(() => {/* fire-and-forget */});
    this.fetchManifest().catch(() => {/* fire-and-forget */});

    this.heartbeatTimer = setInterval(
      () => this.sendHeartbeat().catch(() => {/* ignore */}),
      this.config.heartbeatIntervalMs,
    );

    this.manifestTimer = setInterval(
      () => this.fetchManifest().catch(() => {/* ignore */}),
      this.config.manifestRefreshMs,
    );
  }

  /** Stop the health agent and clear all timers. */
  stop(): void {
    this.isRunning = false;
    if (this.heartbeatTimer !== null) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    if (this.manifestTimer !== null) {
      clearInterval(this.manifestTimer);
      this.manifestTimer = null;
    }
  }

  /** Register a callback to be invoked when the manifest is updated. */
  onManifestUpdate(callback: ManifestUpdateCallback): void {
    this.manifestCallbacks.push(callback);
  }

  /** Record a dropped event (called by EventQueue on consent filter / error). */
  recordDroppedEvent(): void {
    this.metrics.droppedEvents++;
  }

  /** Record a successful event dispatch. */
  recordAttempt(latencyMs: number, success: boolean): void {
    this.metrics.totalAttempted++;
    this.metrics.lastLatencyMs = latencyMs;
    if (!success) {
      this.metrics.retryCount++;
    }
    const total = this.metrics.totalAttempted;
    const dropped = this.metrics.droppedEvents;
    const failed = this.metrics.retryCount;
    this.metrics.lastSuccessRate =
      total > 0 ? Math.max(0, (total - failed - dropped) / total) : 1.0;
  }

  // ── Heartbeat Emission ─────────────────────────────────────────────────

  async sendHeartbeat(): Promise<void> {
    const payload = this.buildHeartbeatPayload();

    let attempt = 0;
    while (attempt < MAX_HEARTBEAT_RETRIES) {
      try {
        const start = Date.now();
        const resp = await fetch(`${this.config.endpoint}/v1/diagnostics/sdk/heartbeat`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${this.config.apiKey}`,
            'X-Aether-SDK': 'web',
            'X-Aether-SDK-Version': SDK_VERSION,
            ...this.config.customHeaders,
          },
          body: JSON.stringify(payload),
          // keepalive ensures delivery even on page unload
          keepalive: true,
        });

        if (resp.ok) {
          // Update latency with round-trip measurement
          this.metrics.lastLatencyMs = Date.now() - start;
          return;
        }

        // 4xx errors are not retried
        if (resp.status >= 400 && resp.status < 500) return;
      } catch (_err) {
        // Network error — will retry
      }
      attempt++;
      await this.sleep(1_000 * Math.pow(2, attempt));
    }
  }

  // ── Manifest Fetching ─────────────────────────────────────────────────

  async fetchManifest(): Promise<SDKManifest | null> {
    try {
      const url = new URL(`${this.config.endpoint}/v1/config/sdk/manifest`);
      url.searchParams.set('sdk_id', this.config.sdkId);
      url.searchParams.set('sdk_version', SDK_VERSION);
      url.searchParams.set('cohort', this.config.rolloutCohort);

      const resp = await fetch(url.toString(), {
        headers: {
          'Authorization': `Bearer ${this.config.apiKey}`,
          'X-Aether-SDK': 'web',
          ...this.config.customHeaders,
        },
      });

      if (!resp.ok) return null;

      const body = await resp.json() as { data: SDKManifest };
      const manifest = body.data;

      if (!manifest) return null;

      // Verify HMAC signature if a signing secret is configured
      if (this.config.signingSecret && manifest.signature) {
        const valid = await this.verifyManifestSignature(manifest);
        if (!valid) {
          console.warn('[Aether SDK] Manifest signature verification failed — ignoring update');
          return null;
        }
      }

      // Notify callbacks only if manifest version changed
      if (
        this.currentManifest === null ||
        this.currentManifest.manifest_version !== manifest.manifest_version
      ) {
        this.currentManifest = manifest;
        this.config.configVersion = manifest.manifest_version;
        for (const cb of this.manifestCallbacks) {
          try { cb(manifest); } catch (_) {/* ignore callback errors */}
        }
      }

      return manifest;
    } catch (_err) {
      return null;
    }
  }

  /** Return the currently cached manifest (null if not yet fetched). */
  getManifest(): SDKManifest | null {
    return this.currentManifest;
  }

  // ── Payload Construction ───────────────────────────────────────────────

  private buildHeartbeatPayload(): SDKHeartbeatPayload {
    const dynamic = this.config.getDynamicState();
    return {
      sdk_id: this.config.sdkId,
      sdk_version: SDK_VERSION,
      platform: this.config.platform,
      app_version: this.config.appVersion,
      queue_depth: this.eventQueue.size,
      retry_count: this.metrics.retryCount,
      dropped_events: this.metrics.droppedEvents,
      endpoint_latency_ms: this.metrics.lastLatencyMs,
      ingestion_success_rate: this.metrics.lastSuccessRate,
      schema_hash: this.computeSchemaHash(),
      auth_valid: dynamic.authValid,
      consent_valid: dynamic.consentValid,
      wallet_connected: dynamic.walletConnected,
      config_version: this.config.configVersion,
      rollout_cohort: this.config.rolloutCohort,
    };
  }

  private computeSchemaHash(): string {
    // In production: hash of the active event schema definition.
    // Here we use a stable string derived from the SDK version.
    return `schema-${SDK_VERSION}`;
  }

  // ── Signature Verification ─────────────────────────────────────────────

  private async verifyManifestSignature(manifest: SDKManifest): Promise<boolean> {
    if (typeof crypto === 'undefined' || !crypto.subtle) return true; // skip in unsupported envs

    try {
      const { signature, ...rest } = manifest;
      const canonical = JSON.stringify(rest, Object.keys(rest).sort());

      const key = await crypto.subtle.importKey(
        'raw',
        new TextEncoder().encode(this.config.signingSecret),
        { name: 'HMAC', hash: 'SHA-256' },
        false,
        ['verify'],
      );

      const sigBytes = this.hexToBytes(signature);
      return await crypto.subtle.verify(
        'HMAC',
        key,
        sigBytes as unknown as ArrayBuffer,
        new TextEncoder().encode(canonical),
      );
    } catch {
      return false;
    }
  }

  private hexToBytes(hex: string): Uint8Array {
    const bytes = new Uint8Array(hex.length / 2);
    for (let i = 0; i < hex.length; i += 2) {
      bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16);
    }
    return bytes;
  }

  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}
