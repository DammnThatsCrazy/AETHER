import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  clearSessionCsrfToken,
  readCsrfToken,
  setSessionCsrfToken,
  withCsrfCriticalSection,
} from './session-transport';

type ChannelListener = (event: { readonly data: unknown }) => void;

class FakeBroadcastChannel {
  static readonly instances = new Set<FakeBroadcastChannel>();
  readonly listeners = new Set<ChannelListener>();

  constructor(readonly name: string) {
    FakeBroadcastChannel.instances.add(this);
  }

  addEventListener(_type: string, listener: ChannelListener): void {
    this.listeners.add(listener);
  }

  postMessage(data: unknown): void {
    for (const peer of FakeBroadcastChannel.instances) {
      if (peer === this || peer.name !== this.name) continue;
      for (const listener of peer.listeners) {
        queueMicrotask(() => listener({ data }));
      }
    }
  }

  close(): void {
    FakeBroadcastChannel.instances.delete(this);
  }
}

afterEach(() => {
  clearSessionCsrfToken();
  FakeBroadcastChannel.instances.clear();
  Reflect.deleteProperty(navigator, 'locks');
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('Kyber CSRF session transport', () => {
  it('adopts a newer token from another browser tab without persisting the value', async () => {
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    setSessionCsrfToken('initial-token');

    const peer = new FakeBroadcastChannel('aether:kyber:csrf:v1');
    const revisionKey = 'aether:kyber:csrf:v1:revision';
    const nextRevision = Number(localStorage.getItem(revisionKey)) + 1;
    peer.postMessage({
      type: 'token',
      revision: nextRevision,
      token: 'fresh-token',
    });
    await new Promise<void>((resolve) => queueMicrotask(resolve));

    expect(readCsrfToken()).toBe('fresh-token');
    expect(localStorage.getItem(revisionKey)).not.toContain('fresh-token');
  });

  it('uses the browser lock for the shared CSRF critical section', async () => {
    let lockDepth = 0;
    const request = vi.fn(
      async (_name: string, _options: unknown, task: () => Promise<string>) => {
        lockDepth += 1;
        try {
          return await task();
        } finally {
          lockDepth -= 1;
        }
      },
    );
    Object.defineProperty(navigator, 'locks', {
      configurable: true,
      value: { request },
    });

    let observedDepth = 0;
    const result = await withCsrfCriticalSection(async () => {
      observedDepth = lockDepth;
      return 'complete';
    });

    expect(result).toBe('complete');
    expect(observedDepth).toBe(1);
    expect(request).toHaveBeenCalledWith(
      'aether:kyber:csrf:v1',
      { mode: 'exclusive' },
      expect.any(Function),
    );
  });
});
