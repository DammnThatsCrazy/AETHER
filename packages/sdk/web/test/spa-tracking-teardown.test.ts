// @vitest-environment jsdom
/**
 * destroy() removes the SPA route hooks setupSPATracking() installed, so a
 * destroy()/init() cycle (the React provider restarting for a new key or site)
 * records one page view per navigation instead of one per init.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import aether from '../src/index';

const CONFIG = {
  apiKey: 'pk_test',
  endpoint: 'https://api.test',
  modules: { autoDiscovery: false, performance: false, ecommerce: false, commerceDetection: false },
};

function capturePageViews() {
  const pages: unknown[] = [];
  (globalThis as any).fetch = vi.fn(async (_url: string, init?: any) => {
    try {
      const parsed = JSON.parse(init?.body ?? '{}');
      if (Array.isArray(parsed.batch)) pages.push(...parsed.batch.filter((e: any) => e.type === 'page'));
    } catch { /* manifest / heartbeat calls */ }
    return { ok: true, status: 200, json: async () => ({ accepted: 1, duplicates: 0, rejected: 0 }), text: async () => '{}' } as any;
  });
  return pages;
}

async function navigate(path: string) {
  window.history.pushState({}, '', path);
  await new Promise((r) => setTimeout(r, 5)); // onRoute is deferred with setTimeout(0)
}

describe('SPA route tracking across destroy()/init()', () => {
  let originalPush: History['pushState'];

  beforeEach(() => {
    localStorage.clear();
    window.history.replaceState({}, '', '/');
    originalPush = window.history.pushState;
  });

  afterEach(() => {
    try { aether.destroy(); } catch { /* ignore */ }
    vi.restoreAllMocks();
  });

  it('restores the history methods it wrapped', () => {
    aether.init(CONFIG);
    expect(window.history.pushState).not.toBe(originalPush);
    aether.destroy();
    expect(window.history.pushState).toBe(originalPush);
  });

  it('records one page view per navigation after a restart', async () => {
    const pages = capturePageViews();
    aether.init(CONFIG);
    aether.destroy();
    aether.init(CONFIG);
    aether.consent.grant(['analytics']); // page views are consent-gated
    await aether.flush();
    pages.length = 0;

    await navigate('/pricing');
    await aether.flush();

    expect(pages).toHaveLength(1);
  });
});
