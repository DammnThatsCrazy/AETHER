// M4 (docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md §2) — DurableEventQueue
// must be a structural drop-in for EventQueue while additionally surviving a
// process crash between enqueue() and a confirmed send.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { DurableEventQueue } from './durable-queue';
import type { SpoolFullInfo } from './durable-queue';

let tmpDir: string;

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aether-durable-queue-'));
});

afterEach(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

function spoolPath(name = 'spool.jsonl'): string {
  return path.join(tmpDir, name);
}

describe('DurableEventQueue — interface parity with EventQueue', () => {
  it('enqueue/dequeueReady/size behave like EventQueue for a single item', () => {
    const q = new DurableEventQueue({ spoolPath: spoolPath() });
    expect(q.size).toBe(0);
    const ok = q.enqueue({ writeKey: 'wk_1', events: [{ id: 'e1' }] });
    expect(ok).toBe(true);
    expect(q.size).toBe(1);

    const item = q.dequeueReady();
    expect(item).toBeDefined();
    expect(item!.writeKey).toBe('wk_1');
    expect(item!.events).toEqual([{ id: 'e1' }]);
    expect(item!.attempt).toBe(0);
    expect(q.size).toBe(0);
  });

  it('respects maxSize, same as EventQueue', () => {
    const q = new DurableEventQueue({ spoolPath: spoolPath(), maxSize: 2 });
    expect(q.enqueue({ writeKey: 'wk', events: [1] })).toBe(true);
    expect(q.enqueue({ writeKey: 'wk', events: [2] })).toBe(true);
    expect(q.enqueue({ writeKey: 'wk', events: [3] })).toBe(false);
    expect(q.size).toBe(2);
  });

  it('requeue applies exponential backoff before an item is ready again', () => {
    const q = new DurableEventQueue({ spoolPath: spoolPath(), maxRetries: 3, baseRetryMs: 10_000 });
    q.enqueue({ writeKey: 'wk', events: [1] });
    const item = q.dequeueReady()!;
    q.requeue(item); // attempt 0 -> 1 (0 < maxRetries(3)), nextRetryAt pushed well into the future
    expect(q.size).toBe(1);

    // Not yet ready (nextRetryAt in the future).
    expect(q.dequeueReady()).toBeUndefined();
  });

  it('drain clears the in-memory queue, same as EventQueue', () => {
    const q = new DurableEventQueue({ spoolPath: spoolPath() });
    q.enqueue({ writeKey: 'wk', events: [1] });
    q.enqueue({ writeKey: 'wk', events: [2] });
    expect(q.size).toBe(2);
    q.drain();
    expect(q.size).toBe(0);
  });
});

describe('DurableEventQueue — durability', () => {
  it('persists enqueued events to the spool file on disk', () => {
    const p = spoolPath();
    const q = new DurableEventQueue({ spoolPath: p });
    q.enqueue({ writeKey: 'wk_persist', events: [{ id: 'e1' }] });

    expect(fs.existsSync(p)).toBe(true);
    const lines = fs.readFileSync(p, 'utf8').trim().split('\n');
    expect(lines.length).toBe(1);
    const record = JSON.parse(lines[0]);
    expect(record.op).toBe('add');
    expect(record.item.writeKey).toBe('wk_persist');
    expect(record.item.events).toEqual([{ id: 'e1' }]);
  });

  it('a new instance over the same spool file replays un-sent entries', () => {
    const p = spoolPath();
    const q1 = new DurableEventQueue({ spoolPath: p });
    q1.enqueue({ writeKey: 'wk_a', events: [{ id: 'e1' }] });
    q1.enqueue({ writeKey: 'wk_a', events: [{ id: 'e2' }] });
    // Simulate a crash: q1 is simply abandoned without ever confirming
    // (no ack, no successful send) — nothing drains it cleanly.
    expect(q1.size).toBe(2);

    const q2 = new DurableEventQueue({ spoolPath: p });
    expect(q2.size).toBe(2);
    const replayed = [q2.dequeueReady()!, q2.dequeueReady()!].map((i) => i.events[0]);
    expect(replayed).toEqual([{ id: 'e1' }, { id: 'e2' }]);
  });

  it('replays an entry that was in-flight (dequeued but never acked) at crash time', () => {
    const p = spoolPath();
    const q1 = new DurableEventQueue({ spoolPath: p });
    q1.enqueue({ writeKey: 'wk_inflight', events: [{ id: 'e1' }] });
    const inFlight = q1.dequeueReady();
    expect(inFlight).toBeDefined();
    // q1 "crashes" here — mid-send, before ack() or requeue() is called.

    const q2 = new DurableEventQueue({ spoolPath: p });
    expect(q2.size).toBe(1);
    expect(q2.dequeueReady()!.events).toEqual([{ id: 'e1' }]);
  });

  it('confirmed-sent entries are pruned and do not replay', () => {
    const p = spoolPath();
    const q1 = new DurableEventQueue({ spoolPath: p });
    q1.enqueue({ writeKey: 'wk_a', events: [{ id: 'keep' }] });
    const toSend = q1.enqueue({ writeKey: 'wk_a', events: [{ id: 'sent' }] });
    expect(toSend).toBe(true);

    // Drain both, "send" the second, ack only that one.
    const first = q1.dequeueReady()!;
    const second = q1.dequeueReady()!;
    expect([first.events[0], second.events[0]]).toEqual([{ id: 'keep' }, { id: 'sent' }]);
    q1.ack(second);
    // `first` remains un-acked (still in-flight / not yet confirmed).

    const q2 = new DurableEventQueue({ spoolPath: p });
    expect(q2.size).toBe(1);
    expect(q2.dequeueReady()!.events).toEqual([{ id: 'keep' }]);
  });

  it('compacts the on-disk journal once acked entries no longer need to be retained', () => {
    const p = spoolPath();
    const q = new DurableEventQueue({ spoolPath: p, compactionIntervalOps: 2 });
    q.enqueue({ writeKey: 'wk', events: [{ id: 'e1' }] });
    const item = q.dequeueReady()!;
    q.ack(item); // second appended line ('ack') hits compactionIntervalOps=2 -> triggers compact()

    const raw = fs.readFileSync(p, 'utf8').trim();
    // After compaction, the acked entry must not appear anywhere in the
    // rewritten file — not as a lingering 'add' line, not as anything else.
    expect(raw.includes('"id":1')).toBe(false);
    expect(raw).toBe('');
  });

  it('requeue giving up after maxRetries prunes the spool entry too', () => {
    const p = spoolPath();
    const q1 = new DurableEventQueue({ spoolPath: p, maxRetries: 0 });
    q1.enqueue({ writeKey: 'wk', events: [{ id: 'give-up' }] });
    const item = q1.dequeueReady()!;
    q1.requeue(item); // attempt(0) >= maxRetries(0) -> permanently dropped
    expect(q1.size).toBe(0);

    const q2 = new DurableEventQueue({ spoolPath: p });
    expect(q2.size).toBe(0);
  });

  it('drain() discards spooled entries so they do not replay later', () => {
    const p = spoolPath();
    const q1 = new DurableEventQueue({ spoolPath: p });
    q1.enqueue({ writeKey: 'wk', events: [{ id: 'e1' }] });
    q1.drain();

    const q2 = new DurableEventQueue({ spoolPath: p });
    expect(q2.size).toBe(0);
  });

  it('respects maxSize after a replay whose live entries would otherwise exceed it', () => {
    const p = spoolPath();
    const q1 = new DurableEventQueue({ spoolPath: p, maxSize: 2 });

    // Fill to maxSize, then dequeue both (in-flight, still "live" but no
    // longer counted in `ready.length`) so two more can be legitimately
    // enqueued on top — exactly like EventQueue would allow, since neither
    // queue counts in-flight items against maxSize during live operation.
    q1.enqueue({ writeKey: 'wk', events: [{ id: 'e1' }] });
    q1.enqueue({ writeKey: 'wk', events: [{ id: 'e2' }] });
    // Both dequeued (in-flight): still "live" on disk, but no longer
    // counted in `ready.length` — mirrors real send-in-progress usage.
    q1.dequeueReady();
    q1.dequeueReady();
    expect(q1.size).toBe(0);

    expect(q1.enqueue({ writeKey: 'wk', events: [{ id: 'e3' }] })).toBe(true);
    expect(q1.enqueue({ writeKey: 'wk', events: [{ id: 'e4' }] })).toBe(true);
    expect(q1.size).toBe(2);
    // A 5th item is correctly rejected — `ready` is at maxSize.
    expect(q1.enqueue({ writeKey: 'wk', events: [{ id: 'e5' }] })).toBe(false);

    // "Crash": q1 is abandoned with 4 live (unacked) spool entries — e1/e2
    // in-flight, e3/e4 ready — against a maxSize of 2.

    const q2 = new DurableEventQueue({ spoolPath: p, maxSize: 2 });
    // The bound must hold even right after replay: never more than maxSize
    // entries surface via size() at once, even though 4 live entries exist
    // on disk.
    expect(q2.size).toBe(2);

    // Nothing is lost: repeatedly dequeuing + acking to free room
    // eventually surfaces all 4 originally-live entries, and size() never
    // exceeds maxSize along the way.
    const delivered: string[] = [];
    let guard = 0;
    while (delivered.length < 4 && guard < 20) {
      guard++;
      const item = q2.dequeueReady();
      if (!item) break;
      delivered.push((item.events[0] as { id: string }).id);
      q2.ack(item);
      expect(q2.size).toBeLessThanOrEqual(2);
    }
    expect(delivered.sort()).toEqual(['e1', 'e2', 'e3', 'e4']);

    // Once everything has been acked, a fresh instance replays nothing.
    const q3 = new DurableEventQueue({ spoolPath: p, maxSize: 2 });
    expect(q3.size).toBe(0);
  });
});

describe('DurableEventQueue — disk-space bound (maxSpoolBytes)', () => {
  it('rejects new events once the live spool would exceed maxSpoolBytes, surfacing every drop', () => {
    const p = spoolPath();
    const drops: SpoolFullInfo[] = [];
    // ~150 bytes/entry; a 400-byte budget fits a couple, then rejects.
    const q = new DurableEventQueue({ spoolPath: p, maxSpoolBytes: 400, onSpoolFull: (i) => drops.push(i) });

    let accepted = 0;
    let rejected = 0;
    for (let n = 0; n < 50; n++) {
      const ok = q.enqueue({ writeKey: 'wk', events: [{ id: `e${n}`, blob: 'x'.repeat(50) }] });
      if (ok) accepted++;
      else rejected++;
    }

    expect(accepted).toBeGreaterThan(0);
    expect(rejected).toBeGreaterThan(0);
    expect(accepted + rejected).toBe(50);
    // Every rejection is surfaced — none silent.
    expect(drops.length).toBe(rejected);
    expect(drops[0].maxSpoolBytes).toBe(400);
    expect(drops[0].spoolPath).toBe(p);
    expect(drops[0].attemptedBytes).toBeGreaterThan(0);
    expect(drops[0].liveBytes).toBeLessThanOrEqual(400);
    // The queue only holds what it accepted.
    expect(q.size).toBe(accepted);
  });

  it('rejects (and surfaces) a single event that is larger than the whole budget', () => {
    const p = spoolPath();
    const drops: SpoolFullInfo[] = [];
    const q = new DurableEventQueue({ spoolPath: p, maxSpoolBytes: 40, onSpoolFull: (i) => drops.push(i) });

    const ok = q.enqueue({ writeKey: 'wk', events: [{ id: 'too-big', blob: 'y'.repeat(200) }] });
    expect(ok).toBe(false);
    expect(q.size).toBe(0);
    expect(drops).toHaveLength(1);
    expect(drops[0].attemptedBytes).toBeGreaterThan(drops[0].maxSpoolBytes);
  });

  it('frees room again once entries are delivered (acked) below the bound', () => {
    const p = spoolPath();
    const drops: SpoolFullInfo[] = [];
    const q = new DurableEventQueue({ spoolPath: p, maxSpoolBytes: 400, onSpoolFull: (i) => drops.push(i) });

    // Fill until the bound rejects.
    while (q.enqueue({ writeKey: 'wk', events: [{ id: 'x', blob: 'y'.repeat(50) }] })) { /* fill */ }
    expect(drops.length).toBeGreaterThan(0);
    const dropsWhenFull = drops.length;

    // Deliver+ack one entry -> its bytes are reclaimed.
    const item = q.dequeueReady()!;
    q.ack(item);

    // A fresh event now fits again, without a new drop.
    expect(q.enqueue({ writeKey: 'wk', events: [{ id: 'after-ack', blob: 'y'.repeat(50) }] })).toBe(true);
    expect(drops.length).toBe(dropsWhenFull);
  });

  it('does NOT enforce the byte bound when the spool is degraded (in-memory-only)', () => {
    // Unwritable spool path -> degraded; the byte bound is a disk concept and
    // must not start rejecting an in-memory-only queue.
    const blocker = path.join(tmpDir, 'not-a-directory');
    fs.writeFileSync(blocker, 'x');
    const p = path.join(blocker, 'nested', 'spool.jsonl');
    const drops: SpoolFullInfo[] = [];
    const q = new DurableEventQueue({ spoolPath: p, maxSpoolBytes: 10, onSpoolFull: (i) => drops.push(i) });

    expect(q.spoolHealthy).toBe(false);
    for (let n = 0; n < 5; n++) {
      expect(q.enqueue({ writeKey: 'wk', events: [{ id: `e${n}`, blob: 'z'.repeat(50) }] })).toBe(true);
    }
    expect(q.size).toBe(5);
    expect(drops).toHaveLength(0);
  });

  it('keeps the physical spool file within a small constant factor of the bound under churn', () => {
    const p = spoolPath();
    const q = new DurableEventQueue({ spoolPath: p, maxSpoolBytes: 2000, compactionIntervalOps: 100 });

    // Steady add -> deliver -> ack churn: the live set stays tiny, but add/ack
    // lines accumulate. Compaction (byte- and ops-triggered) must reclaim them.
    for (let n = 0; n < 500; n++) {
      if (q.enqueue({ writeKey: 'wk', events: [{ id: `e${n}`, blob: 'q'.repeat(30) }] })) {
        const item = q.dequeueReady();
        if (item) q.ack(item);
      }
    }

    const fileBytes = fs.statSync(p).size;
    expect(fileBytes).toBeLessThanOrEqual(2000 * 3);
  });
});

describe('DurableEventQueue — constrained filesystem', () => {
  it('an unwritable spool path degrades to in-memory without throwing from the constructor or enqueue()', () => {
    // `blocker` is a plain file. Using it as a path *segment* (a parent
    // directory) makes mkdir(..., {recursive:true}) fail with ENOTDIR —
    // a structural failure that reproduces "unwritable spool path" without
    // relying on chmod/uid tricks that don't reliably block a root-run
    // test process.
    const blocker = path.join(tmpDir, 'not-a-directory');
    fs.writeFileSync(blocker, 'x');
    const unwritablePath = path.join(blocker, 'nested', 'spool.jsonl');

    let q!: DurableEventQueue;
    expect(() => {
      q = new DurableEventQueue({ spoolPath: unwritablePath });
    }).not.toThrow();

    expect(q.spoolHealthy).toBe(false);

    expect(() => q.enqueue({ writeKey: 'wk', events: [{ id: 'e1' }] })).not.toThrow();
    expect(q.size).toBe(1);

    const item = q.dequeueReady();
    expect(item).toBeDefined();
    expect(item!.events).toEqual([{ id: 'e1' }]);

    // No spool file was ever created on the blocked path.
    expect(fs.existsSync(unwritablePath)).toBe(false);

    // ack()/requeue() on a degraded instance must also stay silent, never throw.
    expect(() => q.ack(item!)).not.toThrow();
    expect(() => q.requeue(item!)).not.toThrow();
  });

  it('throws only for the programmer error of omitting spoolPath (not a runtime FS failure)', () => {
    expect(() => new DurableEventQueue({} as never)).toThrow(/spoolPath/);
  });

  it('a non-ENOENT replay read failure marks the queue degraded without throwing', () => {
    const p = spoolPath();
    // A directory at the exact spool path makes fs.readFileSync(p) fail
    // with EISDIR, not ENOENT — a genuine I/O failure distinct from
    // "no spool yet" (which is expected and must NOT degrade the queue).
    fs.mkdirSync(p);

    let q!: DurableEventQueue;
    expect(() => {
      q = new DurableEventQueue({ spoolPath: p });
    }).not.toThrow();

    // The queue must consistently mark itself unhealthy on this failure —
    // not just skip replay silently — so it stops trusting a spool it
    // already failed to read from.
    expect(q.spoolHealthy).toBe(false);

    // Still degrades to in-memory-only rather than throwing from any
    // public method.
    expect(() => q.enqueue({ writeKey: 'wk', events: [{ id: 'e1' }] })).not.toThrow();
    expect(q.size).toBe(1);
    // No write was attempted against the (still-a-directory) spool path.
    expect(fs.readdirSync(p)).toEqual([]);
  });
});

describe('DurableEventQueue — spool file/dir permissions', () => {
  // chmod/mode bits are POSIX-specific; skip on platforms (e.g. Windows)
  // where fs mode bits aren't meaningfully enforced.
  const itPosix = process.platform === 'win32' ? it.skip : it;

  itPosix('creates the spool directory with mode 0700 and the spool file with mode 0600', () => {
    const nestedDir = path.join(tmpDir, 'nested', 'spool-dir');
    const p = path.join(nestedDir, 'spool.jsonl');
    const q = new DurableEventQueue({ spoolPath: p });
    q.enqueue({ writeKey: 'wk', events: [{ id: 'e1' }] });

    expect(q.spoolHealthy).toBe(true);

    const dirMode = fs.statSync(nestedDir).mode & 0o777;
    expect(dirMode).toBe(0o700);

    const fileMode = fs.statSync(p).mode & 0o777;
    expect(fileMode).toBe(0o600);
  });

  itPosix('the spool file stays mode 0600 after compaction rewrites it', () => {
    const p = spoolPath();
    const q = new DurableEventQueue({ spoolPath: p, compactionIntervalOps: 2 });
    q.enqueue({ writeKey: 'wk', events: [{ id: 'e1' }] });
    const item = q.dequeueReady()!;
    q.ack(item); // triggers compact() at compactionIntervalOps=2

    const fileMode = fs.statSync(p).mode & 0o777;
    expect(fileMode).toBe(0o600);
  });
});
