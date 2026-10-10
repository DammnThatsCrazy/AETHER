// M5 (docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md §2) — the Node SDK
// client must wire in DurableEventQueue as an OPT-IN durable queue, with:
//   - correct selection (in-memory by default vs durable when opted in),
//   - startup replay of spooled-but-unsent events on client init,
//   - a documented, enforced disk-space bound (maxSpoolBytes) whose drops are
//     surfaced (onSpoolDrop) and never silent,
//   - ack-on-delivery so delivered/terminally-rejected events are pruned from
//     the spool instead of replaying forever.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AetherServerSDK } from './index';
import type { SpoolDropInfo } from './index';
import { __resetSpoolOwnershipForTests } from './durable-queue';

let tmpDir: string;

/** A benign default fetch so any stray flush during a selection-only test is a
 *  harmless 200. Tests that assert on delivery override this. */
function benignFetch() {
  return vi.fn(async () => ({
    ok: true,
    status: 200,
    headers: { get: () => null },
    json: async () => ({ accepted: 1, duplicates: 0, rejected: 0 }),
  }));
}

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aether-durable-sdk-'));
  (globalThis as unknown as { fetch: unknown }).fetch = benignFetch();
});

afterEach(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
  vi.restoreAllMocks();
});

describe('AetherServerSDK — durable queue selection', () => {
  it('is in-memory by default and never writes to disk (opt-in durability)', async () => {
    const sdk = new AetherServerSDK({
      writeKey: 'sk',
      endpoint: 'http://localhost',
      consent: { analytics: true },
    });
    expect(sdk.isDurable()).toBe(false);
    expect(sdk.spoolHealthy()).toBeNull();

    sdk.track({ type: 'api_request_observed', properties: { path: '/x' } });
    expect(sdk.queueDepth()).toBe(1);
    // Nothing was persisted anywhere under the temp dir.
    expect(fs.readdirSync(tmpDir)).toEqual([]);
    await sdk.shutdown();
  });

  it('selects the durable queue when a spoolPath is provided (implies durable)', async () => {
    const p = path.join(tmpDir, 'explicit-spool.jsonl');
    const sdk = new AetherServerSDK({ writeKey: 'sk', endpoint: 'http://localhost', spoolPath: p });
    expect(sdk.isDurable()).toBe(true);
    expect(sdk.spoolHealthy()).toBe(true);
    await sdk.shutdown();
  });

  it('selects the durable queue when durable:true, using a default spool path', async () => {
    // Unique write key -> unique default spool file -> no cross-run state.
    const sdk = new AetherServerSDK({
      writeKey: `sk-${Math.random().toString(36).slice(2)}`,
      endpoint: 'http://localhost',
      durable: true,
    });
    expect(sdk.isDurable()).toBe(true);
    expect(sdk.spoolHealthy()).toBe(true);
    await sdk.shutdown();
  });

  it('reports a degraded spool via spoolHealthy() but still accepts events', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => { /* silence degrade warning */ });
    // Using a plain file as a path segment forces ENOTDIR when the queue tries
    // to create the spool directory.
    const blocker = path.join(tmpDir, 'not-a-directory');
    fs.writeFileSync(blocker, 'x');
    const p = path.join(blocker, 'nested', 'spool.jsonl');

    const sdk = new AetherServerSDK({
      writeKey: 'sk',
      endpoint: 'http://localhost',
      spoolPath: p,
      consent: { analytics: true },
    });
    expect(sdk.isDurable()).toBe(true);
    expect(sdk.spoolHealthy()).toBe(false);

    sdk.track({ type: 'api_request_observed', properties: { path: '/x' } });
    expect(sdk.queueDepth()).toBe(1);
    await sdk.shutdown();
    warn.mockRestore();
  });
});

describe('AetherServerSDK — startup replay', () => {
  it('spools tracked events and replays them into a fresh client on startup', async () => {
    const p = path.join(tmpDir, 'replay-spool.jsonl');

    // Client 1: track two events, then "crash" (abandon) with them unsent.
    const sdk1 = new AetherServerSDK({
      writeKey: 'sk',
      endpoint: 'http://localhost',
      spoolPath: p,
      consent: { analytics: true },
      flushInterval: 1_000_000, // keep the periodic timer from firing mid-test
    });
    sdk1.track({ type: 'api_request_observed', properties: { path: '/a' } });
    sdk1.track({ type: 'api_request_observed', properties: { path: '/b' } });
    expect(sdk1.isDurable()).toBe(true);
    expect(sdk1.queueDepth()).toBe(2);
    expect(fs.existsSync(p)).toBe(true);
    // sdk1 is deliberately abandoned here: no shutdown(), no flush(). Simulate
    // the process holding it dying — its in-process spool ownership (N9) vanishes
    // while the on-disk spool survives — so the "restarted" sdk2 can reclaim the
    // same spool and replay the two unsent events.
    __resetSpoolOwnershipForTests();

    // Client 2 over the same spool: its constructor replays the spool AND kicks
    // off a startup flush. Wait deterministically until both events are sent.
    const captured: Array<{ batch: Array<{ properties?: { path?: string } }> }> = [];
    let seenBoth: () => void = () => { /* set below */ };
    const bothDelivered = new Promise<void>((resolve) => { seenBoth = resolve; });
    (globalThis as unknown as { fetch: unknown }).fetch = vi.fn(async (_url: string, init: { body: string }) => {
      captured.push(JSON.parse(init.body));
      if (captured.length >= 2) seenBoth();
      return { ok: true, status: 200, headers: { get: () => null }, json: async () => ({ accepted: 1, duplicates: 0, rejected: 0 }) };
    });

    const sdk2 = new AetherServerSDK({
      writeKey: 'sk',
      endpoint: 'http://localhost',
      spoolPath: p,
      consent: { analytics: true },
      flushInterval: 1_000_000,
    });
    await bothDelivered; // startup replay delivered both spooled events
    await sdk2.shutdown();

    const paths = captured
      .flatMap((b) => b.batch.map((e) => e.properties?.path))
      .sort();
    expect(paths).toEqual(['/a', '/b']);

    // Client 3: both were acked on delivery, so the spool replays nothing.
    const sdk3 = new AetherServerSDK({
      writeKey: 'sk',
      endpoint: 'http://localhost',
      spoolPath: p,
      flushInterval: 1_000_000,
    });
    expect(sdk3.queueDepth()).toBe(0);
    await sdk3.shutdown();
  });

  it('prunes a terminally-rejected (4xx) event so it is not replayed forever', async () => {
    const p = path.join(tmpDir, 'poison-spool.jsonl');
    (globalThis as unknown as { fetch: unknown }).fetch = vi.fn(async () => ({
      ok: false,
      status: 400,
      headers: { get: () => null },
    }));

    const sdk1 = new AetherServerSDK({
      writeKey: 'sk',
      endpoint: 'http://localhost',
      spoolPath: p,
      consent: { analytics: true },
      flushInterval: 1_000_000,
    });
    sdk1.track({ type: 'api_request_observed', properties: { path: '/poison' } });
    await sdk1.flush(); // 400 is terminal -> acked/pruned, not requeued
    expect(sdk1.queueDepth()).toBe(0);
    await sdk1.shutdown();

    const sdk2 = new AetherServerSDK({
      writeKey: 'sk',
      endpoint: 'http://localhost',
      spoolPath: p,
      flushInterval: 1_000_000,
    });
    expect(sdk2.queueDepth()).toBe(0);
    await sdk2.shutdown();
  });
});

describe('AetherServerSDK — disk-space bound (maxSpoolBytes)', () => {
  it('rejects events past maxSpoolBytes and surfaces every drop via onSpoolDrop', async () => {
    const p = path.join(tmpDir, 'bounded-spool.jsonl');
    const drops: SpoolDropInfo[] = [];

    const sdk = new AetherServerSDK({
      writeKey: 'sk',
      endpoint: 'http://localhost',
      spoolPath: p,
      consent: { analytics: true },
      maxSpoolBytes: 3000,
      onSpoolDrop: (i) => drops.push(i),
      // No auto-flush: keep everything queued so the bound is what limits us.
      flushAt: 1_000_000,
      flushInterval: 1_000_000,
    });

    const TOTAL = 100;
    for (let n = 0; n < TOTAL; n++) {
      sdk.track({ type: 'api_request_observed', properties: { path: '/x', blob: 'y'.repeat(40) } });
    }

    // Every tracked event either queued or dropped — nothing vanished silently.
    expect(sdk.queueDepth()).toBeGreaterThan(0);
    expect(drops.length).toBeGreaterThan(0);
    expect(sdk.queueDepth() + drops.length).toBe(TOTAL);
    expect(sdk.droppedBySpoolBound()).toBe(drops.length);

    // Drop info is populated and monotonic.
    expect(drops[0].maxSpoolBytes).toBe(3000);
    expect(drops[0].spoolPath).toBe(p);
    expect(drops[0].attemptedBytes).toBeGreaterThan(0);
    expect(drops[0].droppedTotal).toBe(1);
    expect(drops[drops.length - 1].droppedTotal).toBe(drops.length);

    await sdk.shutdown();
  });

  it('warns (never silent) when the spool is full and no onSpoolDrop is set', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => { /* capture */ });
    const p = path.join(tmpDir, 'warn-spool.jsonl');
    const sdk = new AetherServerSDK({
      writeKey: 'sk',
      endpoint: 'http://localhost',
      spoolPath: p,
      consent: { analytics: true },
      maxSpoolBytes: 500,
      flushAt: 1_000_000,
      flushInterval: 1_000_000,
    });

    for (let n = 0; n < 50; n++) {
      sdk.track({ type: 'api_request_observed', properties: { path: '/x', blob: 'z'.repeat(40) } });
    }

    expect(sdk.droppedBySpoolBound()).toBeGreaterThan(0);
    // Surfaced via a warning at least once (canonical-type warnings are absent
    // because every event here uses a canonical type).
    const spoolWarns = warn.mock.calls.filter((c) => String(c[0]).includes('durable spool full'));
    expect(spoolWarns.length).toBeGreaterThan(0);

    await sdk.shutdown();
    warn.mockRestore();
  });
});
