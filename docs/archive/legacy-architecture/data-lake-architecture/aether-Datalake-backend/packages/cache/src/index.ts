export interface CacheClient {
  get(key: string): Promise<string | null>;
  set(key: string, value: string, ttlMs?: number): Promise<void>;
  del(key: string): Promise<void>;
  exists(key: string): Promise<boolean>;
  incr(key: string): Promise<number>;
}

export class InMemoryCache implements CacheClient {
  private store = new Map<string, { value: string; expiresAt?: number }>();
  private cleanupInterval: ReturnType<typeof setInterval>;

  constructor(cleanupIntervalMs: number = 60_000) {
    this.cleanupInterval = setInterval(() => this.cleanup(), cleanupIntervalMs);
  }

  async get(key: string): Promise<string | null> {
    const entry = this.store.get(key);
    if (!entry) return null;
    if (entry.expiresAt && Date.now() > entry.expiresAt) {
      this.store.delete(key);
      return null;
    }
    return entry.value;
  }

  async set(key: string, value: string, ttlMs?: number): Promise<void> {
    this.store.set(key, {
      value,
      expiresAt: ttlMs ? Date.now() + ttlMs : undefined,
    });
  }

  async del(key: string): Promise<void> {
    this.store.delete(key);
  }

  async exists(key: string): Promise<boolean> {
    const val = await this.get(key);
    return val !== null;
  }

  async incr(key: string): Promise<number> {
    const current = await this.get(key);
    const next = (parseInt(current ?? '0', 10) || 0) + 1;
    await this.set(key, String(next));
    return next;
  }

  /** Graceful shutdown — clears the cleanup timer */
  async close(): Promise<void> {
    clearInterval(this.cleanupInterval);
    this.store.clear();
  }

  destroy(): void {
    clearInterval(this.cleanupInterval);
  }

  private cleanup(): void {
    const now = Date.now();
    for (const [key, entry] of this.store) {
      if (entry.expiresAt && now > entry.expiresAt) {
        this.store.delete(key);
      }
    }
  }
}

export class DeduplicationFilter {
  private seen = new Map<string, number>();
  private windowMs: number;
  private cleanupInterval: ReturnType<typeof setInterval>;
  private cache: CacheClient | null;

  constructor(cacheOrWindowMs?: CacheClient | number, windowMs?: number) {
    // Support both (cache, windowMs) and (windowMs) constructor signatures
    if (typeof cacheOrWindowMs === 'number') {
      this.cache = null;
      this.windowMs = cacheOrWindowMs;
    } else {
      this.cache = cacheOrWindowMs ?? null;
      this.windowMs = windowMs ?? 300_000;
    }
    this.cleanupInterval = setInterval(() => this.cleanup(), this.windowMs);
  }

  isDuplicate(key: string): boolean {
    const now = Date.now();
    const existing = this.seen.get(key);
    if (existing && now - existing < this.windowMs) {
      return true;
    }
    this.seen.set(key, now);
    return false;
  }

  /**
   * Given a list of IDs, returns a Set of IDs that are duplicates
   * (already seen within the deduplication window).
   */
  async filterDuplicates(ids: string[]): Promise<Set<string>> {
    const duplicates = new Set<string>();
    for (const id of ids) {
      if (this.isDuplicate(id)) {
        duplicates.add(id);
      }
    }
    return duplicates;
  }

  destroy(): void {
    clearInterval(this.cleanupInterval);
  }

  private cleanup(): void {
    const now = Date.now();
    for (const [key, timestamp] of this.seen) {
      if (now - timestamp >= this.windowMs) {
        this.seen.delete(key);
      }
    }
  }
}

export class RealtimeCounters {
  private counters = new Map<string, { value: number; expiresAt: number }>();

  increment(key: string, ttlMs: number = 86400_000): number {
    const existing = this.counters.get(key);
    const now = Date.now();
    if (existing && now < existing.expiresAt) {
      existing.value++;
      return existing.value;
    }
    this.counters.set(key, { value: 1, expiresAt: now + ttlMs });
    return 1;
  }

  get(key: string): number {
    const entry = this.counters.get(key);
    if (!entry || Date.now() >= entry.expiresAt) return 0;
    return entry.value;
  }
}
