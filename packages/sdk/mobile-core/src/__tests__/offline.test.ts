import { describe, expect, it } from 'vitest';

import { createOfflineCache, type CacheStorage } from '../offline';

interface Payload {
  items: number[];
}

function memoryStore(): CacheStorage & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    get: async (k) => data.get(k) ?? null,
    set: async (k, v) => {
      data.set(k, v);
    },
    delete: async (k) => {
      data.delete(k);
    },
  };
}

const T0 = 1_752_000_000_000; // fixed epoch for deterministic tests
const TTL = 60_000; // 1 minute

function makeCache() {
  const store = memoryStore();
  const cache = createOfflineCache<Payload>({ storage: store, defaultTtlMs: TTL });
  return { cache, store };
}

describe('createOfflineCache', () => {
  it('returns fresh data for a recent read while online', async () => {
    const { cache } = makeCache();
    await cache.put('today', { items: [1, 2, 3] }, { now: T0 });
    const read = await cache.get('today', { now: T0 + 10_000 });
    expect(read).toEqual({ data: { items: [1, 2, 3] }, state: 'fresh' });
  });

  it('marks an unexpired read as offline when connectivity is lost', async () => {
    const { cache } = makeCache();
    await cache.put('today', { items: [1] }, { now: T0 });
    const read = await cache.get('today', { now: T0 + 10_000, online: false });
    expect(read?.state).toBe('offline');
    expect(read?.data).toEqual({ items: [1] });
  });

  it('marks an expired entry stale regardless of connectivity', async () => {
    const { cache } = makeCache();
    await cache.put('today', { items: [1] }, { now: T0 });
    const offline = await cache.get('today', { now: T0 + TTL + 1, online: false });
    const online = await cache.get('today', { now: T0 + TTL + 1 });
    expect(offline?.state).toBe('stale');
    expect(online?.state).toBe('stale');
  });

  it('is still fresh exactly at the TTL boundary', async () => {
    const { cache } = makeCache();
    await cache.put('today', { items: [1] }, { now: T0 });
    const read = await cache.get('today', { now: T0 + TTL });
    expect(read?.state).toBe('fresh');
  });

  it('returns null on a miss', async () => {
    const { cache } = makeCache();
    expect(await cache.get('nope', { now: T0 })).toBeNull();
  });

  it('drops corrupt entries and treats them as misses', async () => {
    const { cache, store } = makeCache();
    await cache.put('today', { items: [1] }, { now: T0 });
    store.data.set('aether.cache.today', '{not json');
    expect(await cache.get('today', { now: T0 })).toBeNull();
    expect(store.data.has('aether.cache.today')).toBe(false);
  });

  it('the latest put wins', async () => {
    const { cache } = makeCache();
    await cache.put('today', { items: [1] }, { now: T0 });
    await cache.put('today', { items: [2, 2] }, { now: T0 + 5_000 });
    const read = await cache.get('today', { now: T0 + 10_000 });
    expect(read?.data).toEqual({ items: [2, 2] });
    expect(read?.state).toBe('fresh');
  });

  it('honours a per-write TTL override', async () => {
    const { cache } = makeCache();
    await cache.put('today', { items: [1] }, { now: T0, ttlMs: 5_000 });
    expect((await cache.get('today', { now: T0 + 5_001 }))?.state).toBe('stale');
  });

  it('clear removes every cached entry', async () => {
    const { cache, store } = makeCache();
    await cache.put('today', { items: [1] }, { now: T0 });
    await cache.put('alerts', { items: [2] }, { now: T0 });
    expect(store.data.size).toBeGreaterThan(0);
    await cache.clear();
    expect(await cache.get('today', { now: T0 })).toBeNull();
    expect(await cache.get('alerts', { now: T0 })).toBeNull();
  });

  it('clear is scoped to its own namespace', async () => {
    const store = memoryStore();
    const a = createOfflineCache<Payload>({ storage: store, defaultTtlMs: TTL, namespace: 'a' });
    const b = createOfflineCache<Payload>({ storage: store, defaultTtlMs: TTL, namespace: 'b' });
    await a.put('today', { items: [1] }, { now: T0 });
    await b.put('today', { items: [2] }, { now: T0 });
    await a.clear();
    expect(await a.get('today', { now: T0 })).toBeNull();
    expect(await b.get('today', { now: T0 })).toEqual({ data: { items: [2] }, state: 'fresh' });
  });

  it('exposes no offline mutation / queue path (read-only invariant)', async () => {
    const { cache } = makeCache();
    expect(Object.keys(cache).sort()).toEqual(['clear', 'get', 'put']);
    expect('enqueueOfflineWrite' in cache).toBe(false);
    expect('mutate' in cache).toBe(false);
    expect('flushQueue' in cache).toBe(false);
  });
});
