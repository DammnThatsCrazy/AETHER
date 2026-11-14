import { describe, expect, it, vi } from 'vitest';
import { queryCache } from './cache';

describe('queryCache.clear', () => {
  it('drops every entry and in-flight request and notifies subscribers', () => {
    queryCache.set('tenant-a:comms', ['a-campaign']);
    queryCache.setInFlight('tenant-a:health', new Promise(() => {}));
    const subscriber = vi.fn();
    const unsubscribe = queryCache.subscribe('tenant-a:comms', subscriber);

    queryCache.clear();

    expect(queryCache.get('tenant-a:comms')).toBeNull();
    expect(queryCache.getInFlight('tenant-a:health')).toBeNull();
    expect(subscriber).toHaveBeenCalled();
    unsubscribe();
  });

  it('ignores a result fetched under the previous identity', () => {
    const generation = queryCache.generation;
    queryCache.clear();
    queryCache.set('comms:index', ['previous-tenant-data'], generation);
    expect(queryCache.get('comms:index')).toBeNull();

    queryCache.set('comms:index', ['current-tenant-data'], queryCache.generation);
    expect(queryCache.get('comms:index')?.data).toEqual(['current-tenant-data']);
  });

  it('a pre-clear request settling does not remove its replacement in-flight entry', async () => {
    // Codex review on DammnThatsCrazy/AETHER#868.
    let resolveOld: (v: string) => void = () => {};
    const old = new Promise<string>((r) => { resolveOld = r; });
    queryCache.setInFlight('k:inflight', old);
    queryCache.clear();
    const replacement = new Promise<string>(() => {});
    queryCache.setInFlight('k:inflight', replacement);
    resolveOld('stale');
    await old;
    await Promise.resolve();
    expect(queryCache.getInFlight('k:inflight')).toBe(replacement);
  });
});

