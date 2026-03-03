// =============================================================================
// AETHER BACKEND — AUTHENTICATION & API KEY MANAGEMENT
// Validates API keys, resolves projects, enforces rate limits
// =============================================================================

import { createHash } from 'node:crypto';
import type { ApiKeyRecord, RateLimitConfig } from '@aether/common';

// =============================================================================
// API KEY VALIDATOR
// =============================================================================

export class ApiKeyValidator {
  private keyCache = new Map<string, { record: ApiKeyRecord; cachedAt: number }>();
  private readonly cacheTtlMs: number;
  private store: ApiKeyStore;

  constructor(store: ApiKeyStore, cacheTtlMs: number = 300_000) {
    this.store = store;
    this.cacheTtlMs = cacheTtlMs;
  }

  /** Validate an API key and return the associated project record */
  async validate(apiKey: string): Promise<ApiKeyRecord | null> {
    if (!apiKey || apiKey.length < 20) return null;

    // Check cache
    const cached = this.keyCache.get(apiKey);
    if (cached && Date.now() - cached.cachedAt < this.cacheTtlMs) {
      return cached.record.isActive ? cached.record : null;
    }

    // Look up from store
    const keyHash = this.hashKey(apiKey);
    const record = await this.store.findByHash(keyHash);
    if (!record) return null;

    // Cache the result
    this.keyCache.set(apiKey, { record, cachedAt: Date.now() });

    return record.isActive ? record : null;
  }

  /** Extract API key from Authorization header or query parameter */
  static extractKey(
    authHeader?: string,
    queryKey?: string,
  ): string | null {
    if (authHeader) {
      if (authHeader.startsWith('Bearer ')) return authHeader.slice(7);
      return authHeader;
    }
    return queryKey ?? null;
  }

  /** Clear the key cache */
  clearCache(): void {
    this.keyCache.clear();
  }

  private hashKey(key: string): string {
    return createHash('sha256').update(key).digest('hex');
  }
}

// =============================================================================
// API KEY STORE INTERFACE
// =============================================================================

export interface ApiKeyStore {
  findByHash(keyHash: string): Promise<ApiKeyRecord | null>;
  findByProjectId(projectId: string): Promise<ApiKeyRecord[]>;
}

/** In-memory store for development/testing */
export class InMemoryApiKeyStore implements ApiKeyStore {
  private records = new Map<string, ApiKeyRecord>();

  addKey(record: ApiKeyRecord): void {
    this.records.set(record.keyHash, record);
  }

  async findByHash(keyHash: string): Promise<ApiKeyRecord | null> {
    return this.records.get(keyHash) ?? null;
  }

  async findByProjectId(projectId: string): Promise<ApiKeyRecord[]> {
    return Array.from(this.records.values()).filter(r => r.projectId === projectId);
  }
}

// =============================================================================
// SLIDING WINDOW RATE LIMITER
// =============================================================================

interface RateLimitEntry {
  count: number;
  windowStart: number;
}

export class RateLimiter {
  private windows = new Map<string, RateLimitEntry>();
  private cleanupInterval: ReturnType<typeof setInterval>;

  constructor(private windowMs: number = 60_000) {
    this.cleanupInterval = setInterval(() => this.cleanup(), windowMs * 2);
  }

  /** Check if a request is allowed. Returns remaining quota or -1 if exceeded. */
  check(key: string, limits: RateLimitConfig): { allowed: boolean; remaining: number; resetMs: number } {
    const now = Date.now();
    const entry = this.windows.get(key);

    if (!entry || now - entry.windowStart >= this.windowMs) {
      this.windows.set(key, { count: 1, windowStart: now });
      return {
        allowed: true,
        remaining: limits.eventsPerMinute - 1,
        resetMs: this.windowMs,
      };
    }

    entry.count++;
    const remaining = limits.eventsPerMinute - entry.count;
    const resetMs = this.windowMs - (now - entry.windowStart);

    return {
      allowed: remaining >= 0,
      remaining: Math.max(0, remaining),
      resetMs,
    };
  }

  /** Record events consumed (for batch accounting) */
  consume(key: string, count: number): void {
    const entry = this.windows.get(key);
    if (entry) {
      entry.count += count - 1; // -1 because check() already incremented by 1
    }
  }

  destroy(): void {
    clearInterval(this.cleanupInterval);
  }

  private cleanup(): void {
    const now = Date.now();
    for (const [key, entry] of this.windows) {
      if (now - entry.windowStart >= this.windowMs * 2) {
        this.windows.delete(key);
      }
    }
  }
}
