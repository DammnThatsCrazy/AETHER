// =============================================================================
// AETHER SDK — FEATURE FLAGS MODULE (Tier 2 Thin Client)
// Cache-only layer: fetches flags from backend, caches in memory + localStorage.
// No local evaluation, no override logic, no stale-while-revalidate complexity.
// =============================================================================

import { storage } from '../utils';

export interface FeatureFlagCallbacks {
  onTrack: (event: string, properties: Record<string, unknown>) => void;
}

export interface FeatureFlagConfig {
  endpoint: string;
  apiKey: string;
  refreshIntervalMs?: number;
}

interface FlagEntry {
  key: string;
  enabled: boolean;
  value?: unknown;
}

const CACHE_KEY = 'feature_flags';
const CACHE_TTL_KEY = 'feature_flags_ttl';
const DEFAULT_TTL_MS = 300_000; // 5 minutes

export class FeatureFlagModule {
  private callbacks: FeatureFlagCallbacks;
  private config: FeatureFlagConfig | null = null;
  private flags: Map<string, FlagEntry> = new Map();
  private refreshTimer: ReturnType<typeof setInterval> | null = null;

  constructor(callbacks: FeatureFlagCallbacks) {
    this.callbacks = callbacks;
  }

  /** Initialize: load cache, fetch from backend, start refresh timer */
  async init(config: FeatureFlagConfig): Promise<void> {
    this.config = config;
    this.loadCache();
    await this.refresh().catch(() => { /* use cache */ });

    const interval = config.refreshIntervalMs ?? DEFAULT_TTL_MS;
    this.refreshTimer = setInterval(() => {
      this.refresh().catch(() => { /* silent */ });
    }, interval);
  }

  /** Check if a flag is enabled */
  isEnabled(key: string): boolean {
    return this.flags.get(key)?.enabled ?? false;
  }

  /** Get a typed flag value with a default fallback */
  getValue<T>(key: string, defaultValue: T): T {
    const flag = this.flags.get(key);
    if (flag?.value !== undefined && flag.value !== null) {
      return flag.value as T;
    }
    return defaultValue;
  }

  /** Force-refresh flags from backend */
  async refresh(): Promise<void> {
    if (!this.config) return;
    const response = await fetch(`${this.config.endpoint}/v1/config`, {
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${this.config.apiKey}`,
        'Content-Type': 'application/json',
      },
    });
    if (!response.ok) throw new Error(`Flag fetch failed: ${response.status}`);

    const data = await response.json() as { flags?: FlagEntry[] };
    this.flags.clear();
    for (const flag of data.flags ?? []) {
      this.flags.set(flag.key, flag);
    }
    this.persistCache();
  }

  /** Stop refresh timer and clean up */
  destroy(): void {
    if (this.refreshTimer !== null) {
      clearInterval(this.refreshTimer);
      this.refreshTimer = null;
    }
    this.flags.clear();
  }

  private loadCache(): void {
    const ttl = storage.get<number>(CACHE_TTL_KEY);
    if (ttl && ttl < Date.now()) {
      storage.remove(CACHE_KEY);
      storage.remove(CACHE_TTL_KEY);
      return;
    }
    const cached = storage.get<FlagEntry[]>(CACHE_KEY);
    if (Array.isArray(cached)) {
      for (const flag of cached) {
        this.flags.set(flag.key, flag);
      }
    }
  }

  private persistCache(): void {
    const flags: FlagEntry[] = [];
    this.flags.forEach((f) => flags.push(f));
    storage.set(CACHE_KEY, flags);
    storage.set(CACHE_TTL_KEY, Date.now() + DEFAULT_TTL_MS);
  }
}
