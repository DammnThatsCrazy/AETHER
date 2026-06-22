// =============================================================================
// Aether SDK — SDK Health Agent (React Native)
//
// Emits periodic fleet heartbeats to /v1/diagnostics/sdk/heartbeat so installed
// mobile SDKs show up in the tenant's SDK fleet view, and fetches the remote
// config manifest on startup. Heartbeats are fire-and-forget and never block
// the app. Mirrors packages/web SDKHealthAgent behavior for parity.
// =============================================================================

import { Platform } from 'react-native';

const SDK_VERSION = '8.10.0';
const DEFAULT_HEARTBEAT_INTERVAL_MS = 60_000;
const SDK_ID_KEY = 'aether_sdk_instance_id';

export interface RNHealthAgentConfig {
  endpoint: string;
  apiKey: string;
  appVersion?: string;
  /** Heartbeat interval in ms (default 60 000). */
  heartbeatIntervalMs?: number;
}

function uuid(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

/** Optional AsyncStorage — resolved lazily so it's not a hard dependency. */
type AsyncStorageLike = {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
};

function resolveAsyncStorage(): AsyncStorageLike | null {
  try {
    // Resolve the module name indirectly: Metro statically follows *literal*
    // require() strings at bundle time and would hard-fail apps that have not
    // installed this optional peer dependency. A computed specifier is opaque
    // to that static analysis, so the require stays a soft runtime lookup.
    const moduleName = ['@react-native-async-storage', 'async-storage'].join('/');
    const dynamicRequire = require as unknown as (id: string) => Record<string, unknown>;
    const mod = dynamicRequire(moduleName);
    return (mod.default ?? mod) as unknown as AsyncStorageLike;
  } catch {
    return null;
  }
}

export class RNHealthAgent {
  private readonly config: Required<RNHealthAgentConfig>;
  private timer: ReturnType<typeof setInterval> | null = null;
  private sdkId: string;
  private storage: AsyncStorageLike | null;

  constructor(config: RNHealthAgentConfig) {
    this.config = {
      appVersion: '',
      heartbeatIntervalMs: DEFAULT_HEARTBEAT_INTERVAL_MS,
      ...config,
    };
    this.storage = resolveAsyncStorage();
    // Start with an ephemeral id; replaced by the persisted one once loaded.
    this.sdkId = `${this.platform()}_${uuid()}`;
  }

  private platform(): string {
    return Platform.OS === 'ios' || Platform.OS === 'android' ? Platform.OS : 'react-native';
  }

  /** Load (or create + persist) a stable per-install SDK id. */
  private async loadSdkId(): Promise<void> {
    if (!this.storage) return; // keep ephemeral id
    try {
      const existing = await this.storage.getItem(SDK_ID_KEY);
      if (existing) {
        this.sdkId = existing;
      } else {
        await this.storage.setItem(SDK_ID_KEY, this.sdkId);
      }
    } catch {
      // storage unavailable — keep ephemeral id
    }
  }

  /** Begin emitting heartbeats. Sends one immediately after id resolution. */
  start(): void {
    void this.loadSdkId().then(() => {
      void this.sendHeartbeat();
    });
    void this.fetchManifest();
    this.timer = setInterval(() => { void this.sendHeartbeat(); }, this.config.heartbeatIntervalMs);
  }

  /** Stop emitting heartbeats. */
  stop(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  private async sendHeartbeat(): Promise<void> {
    try {
      await fetch(`${this.config.endpoint}/v1/diagnostics/sdk/heartbeat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.config.apiKey}`,
          'X-Aether-SDK': this.platform(),
          'X-Aether-SDK-Version': SDK_VERSION,
        },
        body: JSON.stringify({
          sdk_id: this.sdkId,
          sdk_version: SDK_VERSION,
          platform: this.platform(),
          app_version: this.config.appVersion,
        }),
      });
    } catch {
      // Non-fatal — fleet visibility is best-effort.
    }
  }

  private async fetchManifest(): Promise<void> {
    try {
      const url = `${this.config.endpoint}/v1/config/sdk/manifest?sdk_id=${encodeURIComponent(this.sdkId)}&sdk_version=${SDK_VERSION}`;
      await fetch(url, {
        headers: {
          'Authorization': `Bearer ${this.config.apiKey}`,
          'X-Aether-SDK': this.platform(),
        },
      });
    } catch {
      // Non-fatal.
    }
  }
}
