import { describe, expect, it } from 'vitest';

import {
  createStub,
  drainQueue,
  installStub,
  type QueueEntry,
} from '../src/loader/queue';

describe('pre-load command queue', () => {
  describe('createStub', () => {
    it('captures calls in order as real arrays', () => {
      const stub = createStub();
      stub.track('signup', { plan: 'pro' });
      stub.identify('u1', { email: 'a@b.c' });
      stub.page('Pricing');

      expect(stub.q).toEqual<QueueEntry[]>([
        ['track', ['signup', { plan: 'pro' }]],
        ['identify', ['u1', { email: 'a@b.c' }]],
        ['page', ['Pricing']],
      ]);
    });

    it('captures a ready() callback so it can be replayed', () => {
      const stub = createStub();
      const fn = () => {};
      stub.ready(fn);
      expect(stub.q).toEqual<QueueEntry[]>([['ready', [fn]]]);
    });

    it('records zero-argument calls without losing the entry', () => {
      const stub = createStub();
      stub.page();
      expect(stub.q).toEqual<QueueEntry[]>([['page', []]]);
    });
  });

  describe('installStub', () => {
    it('installs a stub on the target', () => {
      const target: Record<string, unknown> = {};
      const stub = installStub(target);
      expect(target.Aether).toBe(stub);
      expect(stub.q).toEqual([]);
    });

    it('is idempotent and preserves an existing queue', () => {
      const target: Record<string, unknown> = {};
      const first = installStub(target);
      first.track('early');

      const second = installStub(target);

      // A duplicated snippet must not discard calls the customer already made.
      expect(second).toBe(first);
      expect(second.q).toEqual<QueueEntry[]>([['track', ['early']]]);
    });

    it('leaves a live SDK alone', () => {
      const target: Record<string, unknown> = {};
      const live = { init: () => {}, __aetherLive: true, q: [] };
      target.Aether = live;

      expect(installStub(target)).toBe(live);
      expect(target.Aether).toBe(live);
    });

    it('replaces a non-stub, non-live global', () => {
      const target: Record<string, unknown> = { Aether: { somethingElse: true } };
      const stub = installStub(target);
      expect(target.Aether).toBe(stub);
    });
  });

  describe('drainQueue', () => {
    it('replays in queue order and reports the count', () => {
      const seen: string[] = [];
      const sdk = {
        track: (name: unknown) => seen.push(`track:${name}`),
        identify: (id: unknown) => seen.push(`identify:${id}`),
      };

      const result = drainQueue(sdk, [
        ['track', ['a']],
        ['identify', ['u1']],
        ['track', ['b']],
      ]);

      expect(seen).toEqual(['track:a', 'identify:u1', 'track:b']);
      expect(result.drained).toBe(3);
      expect(result.failures).toEqual([]);
    });

    it('captures a throwing command instead of breaking the page', () => {
      const sdk = {
        track: (name: unknown) => {
          if (name === 'boom') throw new Error('bad payload');
        },
        identify: () => {},
      };

      const result = drainQueue(sdk, [
        ['track', ['ok']],
        ['track', ['boom']],
        ['identify', ['u1']],
      ]);

      // The later commands still run — one bad call must not strand the rest.
      expect(result.drained).toBe(2);
      expect(result.failures).toHaveLength(1);
      expect(result.failures[0].entry).toEqual(['track', ['boom']]);
      expect(result.failures[0].reason).toBe('bad payload');
    });

    it('reports a command the SDK does not implement', () => {
      const result = drainQueue({ track: () => {} }, [['page', ['/x']]]);
      expect(result.drained).toBe(0);
      expect(result.failures[0].reason).toContain('no page() method');
    });

    it('stringifies a non-Error throw', () => {
      const sdk = {
        track: () => {
          throw 'plain string';
        },
      };
      const result = drainQueue(sdk, [['track', []]]);
      expect(result.failures[0].reason).toBe('plain string');
    });

    it('handles an empty queue', () => {
      expect(drainQueue({ track: () => {} }, [])).toEqual({ drained: 0, failures: [] });
    });
  });
});
