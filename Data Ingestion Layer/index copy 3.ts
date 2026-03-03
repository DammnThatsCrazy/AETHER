// =============================================================================
// AETHER BACKEND — CACHE CLIENT
// Redis-backed caching, real-time counters, deduplication, and pub/sub
// =============================================================================

import { createLogger } from '@aether/logger';

const logger = createLogger('aether.cache');

export interface CacheClient {
  get(key: string): Promise<string | null>;
  set(key: string, value: string, ttlSeconds?: number): Promise<void>;
  del(key: string): Promise<void>;
  incr(key: string, ttlSeconds?: number): Promise<number>;
  exists(key: string): Promise<boolean>;
  expire(key: string, ttlSeconds: number): Promise<void>;
  pipeline(): CachePipeline;
  publish(channel: string, message: string): Promise<void>;
  close(): Promise<void>;
}

export interface CachePipeline {
  set(key: string, value: string, ttlSeconds?: number): CachePipeline;
  incr(key: string): CachePipeline;
  expire(key: string, ttlSeconds: number): CachePipeline;
  exec(): Promise<void>;
}

// =============================================================================
// IN-MEMORY CACHE (dev / testing)
// =============================================================================

interface CacheEntry {
  value: string;
  expiresAt?: number;
}

export class InMemoryCache implements CacheClient {
  private store = new Map<string, CacheEntry>();
  private cleanupTimer: ReturnType<typeof setInterval>;

  constructor() {
    this.cleanupTimer = setInterval(() => this.evictExpired(), 10_000);
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

  async set(key: string, value: string, ttlSeconds?: number): Promise<void> {
    this.store.set(key, {
      value,
      expiresAt: ttlSeconds ? Date.now() + ttlSeconds * 1000 : undefined,
    });
  }

  async del(key: string): Promise<void> {
    this.store.delete(key);
  }

  async incr(key: string, ttlSeconds?: number): Promise<number> {
    const current = await this.get(key);
    const next = (current ? parseInt(current, 10) : 0) + 1;
    await this.set(key, String(next), ttlSeconds);
    return next;
  }

  async exists(key: string): Promise<boolean> {
    return (await this.get(key)) !== null;
  }

  async expire(key: string, ttlSeconds: number): Promise<void> {
    const entry = this.store.get(key);
    if (entry) entry.expiresAt = Date.now() + ttlSeconds * 1000;
  }

  pipeline(): CachePipeline {
    const ops: Array<() => Promise<void>> = [];
    const pipe: CachePipeline = {
      set: (key, value, ttl) => { ops.push(() => this.set(key, value, ttl)); return pipe; },
      incr: (key) => { ops.push(async () => { await this.incr(key); }); return pipe; },
      expire: (key, ttl) => { ops.push(() => this.expire(key, ttl)); return pipe; },
      exec: async () => { for (const op of ops) await op(); },
    };
    return pipe;
  }

  async publish(_channel: string, _message: string): Promise<void> {
    // No-op in memory
  }

  async close(): Promise<void> {
    clearInterval(this.cleanupTimer);
    this.store.clear();
  }

  private evictExpired(): void {
    const now = Date.now();
    for (const [key, entry] of this.store) {
      if (entry.expiresAt && now > entry.expiresAt) this.store.delete(key);
    }
  }
}

// =============================================================================
// DEDUPLICATION FILTER (uses cache backend)
// =============================================================================

export class DeduplicationFilter {
  constructor(
    private cache: CacheClient,
    private windowMs: number = 300_000,
    private prefix: string = 'dedup:',
  ) {}

  /** Returns true if event is a duplicate */
  async isDuplicate(eventId: string): Promise<boolean> {
    const key = `${this.prefix}${eventId}`;
    const exists = await this.cache.exists(key);
    if (exists) return true;
    await this.cache.set(key, '1', Math.ceil(this.windowMs / 1000));
    return false;
  }

  /** Batch check: returns set of duplicate event IDs */
  async filterDuplicates(eventIds: string[]): Promise<Set<string>> {
    const dupes = new Set<string>();
    const pipeline = this.cache.pipeline();

    for (const id of eventIds) {
      const key = `${this.prefix}${id}`;
      if (await this.cache.exists(key)) {
        dupes.add(id);
      } else {
        pipeline.set(key, '1', Math.ceil(this.windowMs / 1000));
      }
    }

    await pipeline.exec();
    return dupes;
  }
}

// =============================================================================
// REAL-TIME COUNTERS (for dashboard live metrics)
// =============================================================================

export class RealtimeCounters {
  constructor(
    private cache: CacheClient,
    private prefix: string = 'aether:rt:',
  ) {}

  async incrementEventCount(projectId: string, eventType: string): Promise<void> {
    const hour = new Date().toISOString().slice(0, 13);
    const key = `${this.prefix}events:${projectId}:${eventType}:${hour}`;
    await this.cache.incr(key, 7200); // 2h TTL
  }

  async incrementSessionCount(projectId: string): Promise<void> {
    const hour = new Date().toISOString().slice(0, 13);
    const key = `${this.prefix}sessions:${projectId}:${hour}`;
    await this.cache.incr(key, 7200);
  }

  async recordActiveUser(projectId: string, anonymousId: string): Promise<void> {
    const minute = new Date().toISOString().slice(0, 16);
    const key = `${this.prefix}active:${projectId}:${minute}`;
    await this.cache.set(`${key}:${anonymousId}`, '1', 120);
  }
}

export function createCache(redisUrl?: string): CacheClient {
  if (!redisUrl || redisUrl === 'memory') {
    logger.info('Using in-memory cache');
    return new InMemoryCache();
  }
  // In production: return new RedisCache(redisUrl);
  logger.info('Using in-memory cache (Redis client requires ioredis dependency)');
  return new InMemoryCache();
}
