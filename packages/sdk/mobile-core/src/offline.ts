/**
 * Read-only offline cache for the Aether mobile SDK.
 *
 * The cache stores READS only. An app fetches a bounded projection while online,
 * calls `put` to record the successful network result, and later serves `get` (with
 * a connectivity hint) when the network is unavailable. There is NO offline mutation
 * path — no queue, no offline write buffer, no pending-actions store. A user action
 * taken while offline is out of scope by design (plan M2 "no offline mutation"
 * invariant); actions must await connectivity.
 *
 * Platform-agnostic pure TypeScript (no react / react-native import): the host app
 * injects the string-backed storage ({ get / set / delete }) — SecureStore
 * (Keychain / Keystore) or AsyncStorage.
 */
import type { SecureStore } from './auth';

/** Derived state of a cached read. */
export type CacheState = 'fresh' | 'offline' | 'stale';

/** A stored cache entry. */
export interface CacheEntry<T> {
  data: T;
  /** Epoch ms at which the entry was written from a successful network read. */
  fetched_at: number;
  /** Entry TTL in ms. */
  ttl: number;
}

/**
 * String-backed storage the host app supplies. Structurally identical to
 * {@link SecureStore} — reused here rather than re-declared so there is no second
 * storage interface in the SDK.
 */
export type CacheStorage = SecureStore;

export interface OfflineCacheOptions {
  storage: CacheStorage;
  /** Default TTL (ms) applied when `put` does not override it. */
  defaultTtlMs: number;
  /** Key prefix isolating this cache's entries within the shared store. */
  namespace?: string;
}

export interface CachedRead<T> {
  data: T;
  state: CacheState;
}

export interface ReadOfflineOptions {
  /** Device connectivity hint. Defaults to `true`. */
  online?: boolean;
  /** Test seam: current epoch ms. Defaults to `Date.now()`. */
  now?: number;
}

export interface WriteOfflineOptions {
  /** Per-write TTL override (ms). Defaults to `defaultTtlMs`. */
  ttlMs?: number;
  /** Test seam: current epoch ms. Defaults to `Date.now()`. */
  now?: number;
}

/**
 * The read-only cache surface. By construction it exposes only `get` / `put` /
 * `clear` — there is deliberately no mutation-while-offline method.
 */
export interface OfflineCache<T> {
  get(key: string, opts?: ReadOfflineOptions): Promise<CachedRead<T> | null>;
  put(key: string, data: T, opts?: WriteOfflineOptions): Promise<void>;
  clear(): Promise<void>;
}

const DEFAULT_NAMESPACE = 'aether.cache';
const INDEX_MARKER = '#keys';

export function createOfflineCache<T>(options: OfflineCacheOptions): OfflineCache<T> {
  const storage = options.storage;
  const defaultTtlMs = options.defaultTtlMs;
  const namespace = options.namespace ?? DEFAULT_NAMESPACE;

  const entryKeyFor = (key: string): string => `${namespace}.${key}`;
  const indexKeyFor = (): string => `${namespace}${INDEX_MARKER}`;

  /** Best-effort: keep the key index in sync so `clear()` can drop only our entries. */
  async function addToIndex(key: string): Promise<void> {
    const raw = await storage.get(indexKeyFor());
    const keys = new Set<string>();
    if (raw !== null) {
      try {
        const parsed: unknown = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          for (const k of parsed) if (typeof k === 'string') keys.add(k);
        }
      } catch {
        // Corrupt index — replace it rather than block the write.
      }
    }
    keys.add(key);
    await storage.set(indexKeyFor(), JSON.stringify([...keys]));
  }

  return {
    async get(key, opts = {}): Promise<CachedRead<T> | null> {
      const raw = await storage.get(entryKeyFor(key));
      if (raw === null) return null;

      let entry: CacheEntry<T>;
      try {
        entry = JSON.parse(raw) as CacheEntry<T>;
      } catch {
        await storage.delete(entryKeyFor(key));
        return null;
      }
      if (
        typeof entry !== 'object' ||
        entry === null ||
        typeof entry.fetched_at !== 'number' ||
        typeof entry.ttl !== 'number'
      ) {
        await storage.delete(entryKeyFor(key));
        return null;
      }

      const now = opts.now ?? Date.now();
      const online = opts.online ?? true;
      const age = now - entry.fetched_at;

      let state: CacheState;
      if (age > entry.ttl) {
        state = 'stale';
      } else if (!online) {
        state = 'offline';
      } else {
        state = 'fresh';
      }
      return { data: entry.data, state };
    },

    async put(key, data, opts = {}): Promise<void> {
      const now = opts.now ?? Date.now();
      const ttl = opts.ttlMs ?? defaultTtlMs;
      const entry: CacheEntry<T> = { data, fetched_at: now, ttl };
      await storage.set(entryKeyFor(key), JSON.stringify(entry));
      await addToIndex(key);
    },

    async clear(): Promise<void> {
      const raw = await storage.get(indexKeyFor());
      if (raw === null) return;
      let keys: string[] = [];
      try {
        const parsed: unknown = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          keys = parsed.filter((k): k is string => typeof k === 'string');
        }
      } catch {
        // Corrupt index — nothing safe to enumerate; drop the index and move on.
      }
      for (const key of keys) {
        await storage.delete(entryKeyFor(key));
      }
      await storage.delete(indexKeyFor());
    },
  };
}
