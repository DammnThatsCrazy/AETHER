// DurableEventQueue — an opt-in, disk-backed drop-in for EventQueue.
//
// Program: docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md, section 2
// ("A single /v1/batch ingestion owner + Node SDK durability"), milestones
// M4 (this standalone class) and M5 (its wiring into the SDK client).
//
// EventQueue (./queue.ts) is a bare in-process array: if the host process
// crashes or restarts between a caller's track() call and a successful
// transport send, every queued-but-unsent event is gone with no signal to
// the caller (track() already returned). DurableEventQueue closes that gap
// by mirroring every accepted event into an append-only local JSON-Lines
// spool file, so a crash between enqueue() and a confirmed send can be
// recovered by replaying the spool on the next process start.
//
// Wiring status: M5 wires this into AetherServerSDK (see ./index.ts) as an
// opt-in queue — the SDK selects it when `durable: true` or a `spoolPath`
// is configured, replays its spool on client init, and calls ack() from
// flush() on confirmed delivery so delivered entries are pruned instead of
// replaying forever. The class itself stays transport-agnostic: ack() is
// the confirmed-delivery hook the SDK now calls.
//
// Interface parity: enqueue / dequeueReady / requeue / size / drain behave
// identically to EventQueue (same inputs produce the same in-memory
// results and return values), so this class is a structural drop-in
// wherever EventQueue is used today. The one intentional behavioral
// addition beyond the side-channel persistence is the disk-space bound
// (see maxSpoolBytes below): a durable queue backed by a healthy spool
// refuses new events once persisting them would blow the configured disk
// budget, and surfaces every such rejection (never silent). ack() is an
// additive capability beyond the EventQueue interface.
//
// Bounded footprint (documented disk-space bound):
//   - In-memory / "ready to send" entries are bounded by `maxSize`, exactly
//     like EventQueue (default 1000).
//   - The durable (live, not-yet-acked) payload on disk is bounded by
//     `maxSpoolBytes` (default 5 MiB): once accepting an event would push
//     the live spool footprint past that budget, enqueue() REJECTS the
//     event (returns false), fires the `onSpoolFull` callback, and — only
//     if no callback is set — warns once. It is never dropped silently.
//     Retries (requeue) of already-accepted events are always honored; the
//     bound gates only new enqueues, so a burst can't grow the durable set
//     without limit. The physical file also carries transient dead lines
//     (acked/superseded records) between compactions; those are reclaimed
//     by compaction — the file is rewritten to contain only currently-live
//     entries once it exceeds `maxSpoolBytes` on disk, or after
//     `compactionIntervalOps` appended lines (default 200), via a temp-file
//     + rename so a crash mid-compaction never corrupts the spool. Net: the
//     physical file stays within a small constant factor of `maxSpoolBytes`
//     and the durable payload never exceeds it.
//
// Constrained filesystems: some host processes run with a read-only or
// otherwise constrained filesystem (design-doc risk). DurableEventQueue
// never throws from enqueue() (or any other public method) because of a
// disk failure. If the spool directory/file cannot be prepared, or any
// later write fails, the instance permanently marks itself degraded and
// continues operating exactly like an in-memory EventQueue from then on —
// it does not keep retrying a failing disk on every call, and it does not
// refuse to accept events because persistence is unavailable.
//
// Not supported (out of scope for M4): multiple processes sharing the same
// spool file concurrently. This class assumes single-writer, in-process
// use, matching how EventQueue itself is used today.

import fs from 'node:fs';
import path from 'node:path';

import type { EventQueue, QueuedEvent } from './queue';

/**
 * The subset of EventQueue's public surface DurableEventQueue promises to
 * behave identically to (see "Interface parity" above). Deriving this type
 * from EventQueue itself — rather than hand-duplicating the signatures —
 * means a future signature change to EventQueue's public methods fails this
 * file's typecheck instead of silently drifting out of parity.
 */
export type EventQueueLike = Pick<EventQueue, 'enqueue' | 'dequeueReady' | 'requeue' | 'size' | 'drain'>;

/**
 * Passed to `onSpoolFull` when the disk-space bound rejects an event. Carries
 * enough context for a host to meter/alert on durable-spool backpressure.
 */
export interface SpoolFullInfo {
  /** Absolute path of the spool file that is at its byte bound. */
  spoolPath: string;
  /** The configured `maxSpoolBytes` budget that was hit. */
  maxSpoolBytes: number;
  /** Live (not-yet-acked) spool footprint, in bytes, at the moment of the drop. */
  liveBytes: number;
  /** Bytes the rejected event's spool record would have added. */
  attemptedBytes: number;
}

export interface DurableQueueOptions {
  /**
   * Path to the append-only spool file. Required — this queue has no
   * implicit default location; a host opts into on-disk persistence by
   * choosing where it may write.
   */
  spoolPath: string;
  /** Bounds the in-memory "ready" queue. Same meaning as EventQueue's maxSize. Default 1000. */
  maxSize?: number;
  /** Same meaning as EventQueue's maxRetries. Default 5. */
  maxRetries?: number;
  /** Same meaning as EventQueue's baseRetryMs. Default 2000. */
  baseRetryMs?: number;
  /**
   * Disk-space bound: the hard upper limit on the live (not-yet-acked)
   * on-disk spool footprint, in bytes. Once accepting a new event would push
   * the live spool past this budget, enqueue() rejects it (returns false) and
   * fires `onSpoolFull` (never a silent drop). This is the durability
   * equivalent of `maxSize` for disk. It also drives compaction: the physical
   * file is rewritten to only-live entries whenever it grows past this many
   * bytes on disk, so accumulated dead (acked/superseded) lines are reclaimed
   * and the file stays within a small constant factor of this bound.
   * Default 5 MiB.
   */
  maxSpoolBytes?: number;
  /**
   * Called when the disk-space bound (`maxSpoolBytes`) rejects an event, so
   * the drop is surfaced rather than silent. When omitted, the queue instead
   * warns once via console.warn. Never throws out of enqueue() even if the
   * callback does.
   */
  onSpoolFull?: (info: SpoolFullInfo) => void;
  /**
   * Also compact after this many journal lines have been appended since the
   * last compaction, so a low-traffic-but-long-lived queue doesn't wait on
   * the byte threshold alone. Default 200.
   */
  compactionIntervalOps?: number;
}

type JournalLine =
  | { op: 'add' | 'requeue'; id: number; item: QueuedEvent }
  | { op: 'ack'; id: number };

const DEFAULT_MAX_SPOOL_BYTES = 5 * 1024 * 1024;
const DEFAULT_COMPACTION_INTERVAL_OPS = 200;

export class DurableEventQueue implements EventQueueLike {
  private readonly ready: QueuedEvent[] = [];
  private readonly maxSize: number;
  private readonly maxRetries: number;
  private readonly baseRetryMs: number;
  private readonly maxSpoolBytes: number;
  private readonly compactionIntervalOps: number;
  private readonly spoolPath: string;

  /** All accepted-but-not-yet-acked entries, keyed by spool id. Includes
   *  both ready-to-send and currently in-flight (dequeued, not yet
   *  acked/requeued) entries — compaction must preserve in-flight entries
   *  too, or a crash mid-send would lose them. */
  private readonly live = new Map<number, QueuedEvent>();
  /** Recovers an entry's spool id from the exact object handed back by
   *  dequeueReady(), without adding any field to the public QueuedEvent
   *  shape. */
  private readonly idOf = new WeakMap<QueuedEvent, number>();
  /** Entries recovered by replay() that don't fit in `ready` under maxSize
   *  (see replay() below). Still tracked in `live` — so they remain durable
   *  and are included in compaction — but withheld from `ready` until an
   *  ack/give-up frees room, so `size` (== ready.length) never exceeds the
   *  maxSize bound this queue promises callers, even right after replaying
   *  a spool that has more live entries than maxSize allows. */
  private readonly backlog: QueuedEvent[] = [];

  /** Running total of the live (not-yet-acked) on-disk footprint, in bytes.
   *  Kept in sync with `live` so the disk-space bound can be enforced in O(1)
   *  per enqueue; resynced authoritatively on replay and compaction. */
  private liveBytes = 0;
  private readonly onSpoolFullCb?: (info: SpoolFullInfo) => void;

  private nextId = 1;
  private opsSinceCompaction = 0;
  private spoolWritable = true;
  private warned = false;
  private spoolFullWarned = false;

  constructor(opts: DurableQueueOptions) {
    if (!opts || !opts.spoolPath) {
      throw new Error('DurableEventQueue requires a spoolPath (opt-in disk persistence needs an explicit location)');
    }
    this.spoolPath = opts.spoolPath;
    this.maxSize = opts.maxSize ?? 1000;
    this.maxRetries = opts.maxRetries ?? 5;
    this.baseRetryMs = opts.baseRetryMs ?? 2000;
    this.maxSpoolBytes = opts.maxSpoolBytes ?? DEFAULT_MAX_SPOOL_BYTES;
    this.compactionIntervalOps = opts.compactionIntervalOps ?? DEFAULT_COMPACTION_INTERVAL_OPS;
    this.onSpoolFullCb = opts.onSpoolFull;

    try {
      // The spool holds raw event payloads (potentially PII) — restrict the
      // directory to the owner (0o700) so other local users on a shared
      // host can't read buffered events off disk. `mode` here covers the
      // directory as created; hardenPermissions() below is a best-effort
      // top-up for platforms/umasks where the creating call's mode isn't
      // the final word.
      const dir = path.dirname(this.spoolPath);
      fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
      this.hardenPermissions(dir, 0o700);
    } catch (err) {
      // Directory cannot be prepared (read-only FS, permission denied,
      // a path component that isn't a directory, ...). Degrade to
      // in-memory-only for the lifetime of this instance rather than
      // throwing out of the constructor.
      this.spoolWritable = false;
      this.warnDegraded(err);
    }

    // Replay before accepting any new work: this constructor runs fully to
    // completion before the returned instance can be used, so "replay on
    // construction" and "replay before new work" are the same guarantee.
    this.replay();
  }

  /** Whether the on-disk spool is currently usable. False once any spool
   *  I/O has failed — from then on this instance behaves as an in-memory-
   *  only queue (same as EventQueue) but never throws. */
  get spoolHealthy(): boolean {
    return this.spoolWritable;
  }

  enqueue(item: Omit<QueuedEvent, 'attempt' | 'nextRetryAt'>): boolean {
    if (this.ready.length >= this.maxSize) return false;
    const record: QueuedEvent = { ...item, attempt: 0, nextRetryAt: 0 };
    const id = this.nextId;
    // Disk-space bound. Only meaningful while the spool is actually writable —
    // a degraded (in-memory-only) instance has no disk footprint to bound, so
    // it behaves exactly like EventQueue (bounded by maxSize alone). Because
    // `liveBytes` already reflects the compacted footprint, a rejection here
    // can't be resolved by compacting first — the live set itself won't fit.
    if (this.spoolWritable) {
      const addBytes = this.lineBytes(id, record);
      if (this.liveBytes + addBytes > this.maxSpoolBytes) {
        this.notifySpoolFull(addBytes);
        return false;
      }
    }
    this.nextId++;
    this.live.set(id, record);
    this.idOf.set(record, id);
    this.ready.push(record);
    this.liveBytes += this.lineBytes(id, record);
    this.appendLine({ op: 'add', id, item: record });
    return true;
  }

  dequeueReady(): QueuedEvent | undefined {
    const now = Date.now();
    const idx = this.ready.findIndex((item) => item.nextRetryAt <= now);
    if (idx === -1) return undefined;
    // Removed from the ready array but intentionally left in `live` / the
    // spool: it is now in-flight. If the process crashes before ack() or
    // requeue() is called on it, replay() will bring it back as pending —
    // an at-least-once guarantee (a possible duplicate send is preferable
    // to a silently dropped event).
    return this.ready.splice(idx, 1)[0];
  }

  requeue(item: QueuedEvent): void {
    const id = this.idOf.get(item);
    if (item.attempt >= this.maxRetries) {
      // Same as EventQueue: permanently give up after maxRetries. Unlike
      // EventQueue, that decision must also be reflected on disk, or the
      // spool would leak an entry for an event this queue will never send
      // again.
      if (id !== undefined) this.pruneSpoolEntry(id);
      return;
    }
    const jitter = Math.random() * 1000;
    const delay = this.baseRetryMs * Math.pow(2, item.attempt) + jitter;
    const next: QueuedEvent = { ...item, attempt: item.attempt + 1, nextRetryAt: Date.now() + delay };
    // Requeue is a retry of an already-accepted event, so it is NOT gated by
    // the disk-space bound — dropping an in-flight event to enforce the bound
    // would be worse than briefly exceeding it. `liveBytes` is still kept
    // exact so the bound stays honest for subsequent new enqueues.
    if (id !== undefined) {
      const prev = this.live.get(id);
      if (prev) this.liveBytes -= this.lineBytes(id, prev);
      this.live.set(id, next);
      this.idOf.set(next, id);
      this.liveBytes += this.lineBytes(id, next);
      this.appendLine({ op: 'requeue', id, item: next });
      this.ready.push(next);
    } else {
      // An item this instance never produced via dequeueReady (e.g.
      // hand-constructed by a caller). Spool it fresh rather than silently
      // accepting an unpersisted event back into the ready queue.
      const newId = this.nextId++;
      this.live.set(newId, next);
      this.idOf.set(next, newId);
      this.liveBytes += this.lineBytes(newId, next);
      this.appendLine({ op: 'add', id: newId, item: next });
      this.ready.push(next);
    }
  }

  /**
   * Confirm an item was durably delivered (or otherwise permanently
   * resolved) and prune it from the spool. Additive beyond EventQueue's
   * interface. M5 wires this into AetherServerSDK.flush(): it is called on
   * confirmed delivery (and on a terminal, non-retryable rejection) so a
   * delivered/rejected event is dropped from the spool instead of replaying
   * forever on the next startup. No-ops for an item this instance has no
   * record of.
   */
  ack(item: QueuedEvent): void {
    const id = this.idOf.get(item);
    if (id === undefined) return;
    this.idOf.delete(item);
    this.pruneSpoolEntry(id);
  }

  get size(): number {
    return this.ready.length;
  }

  drain(): void {
    // Mirrors EventQueue.drain(): discard everything currently ready to
    // send. Also prune those entries from the spool so they don't replay
    // on the next startup — drain() is an explicit "discard", not a crash.
    for (const item of this.ready) {
      const id = this.idOf.get(item);
      if (id !== undefined) {
        this.idOf.delete(item);
        this.live.delete(id);
      }
    }
    this.ready.length = 0;
    // The backlog (entries a replay held back to respect maxSize — see
    // `backlog` field doc) is conceptually part of the same queue, just
    // not yet visible via `size`. drain() means "discard everything
    // currently queued", so it must clear the backlog too, or those
    // entries would keep occupying `live`/the spool and reappear via
    // promoteFromBacklog() after a drain that was supposed to discard
    // them.
    for (const item of this.backlog) {
      const id = this.idOf.get(item);
      if (id !== undefined) {
        this.idOf.delete(item);
        this.live.delete(id);
      }
    }
    this.backlog.length = 0;
    this.compact();
  }

  // -- internals -------------------------------------------------------

  private replay(): void {
    let raw: string;
    try {
      raw = fs.readFileSync(this.spoolPath, 'utf8');
    } catch (err: unknown) {
      if ((err as NodeJS.ErrnoException)?.code === 'ENOENT') return; // no spool yet — nothing to replay
      // A real I/O failure reading an existing spool path (permission
      // denied, EISDIR because the path was clobbered by something else,
      // a corrupt/unreadable device, ...). Treat this exactly like any
      // other spool I/O failure: mark the spool unusable so every later
      // call degrades to in-memory-only instead of continuing to trust a
      // spool this instance already failed to read. Never throw.
      this.spoolWritable = false;
      this.warnDegraded(err);
      return;
    }

    const pending = new Map<number, QueuedEvent>();
    let maxId = 0;
    for (const rawLine of raw.split('\n')) {
      const line = rawLine.trim();
      if (!line) continue;
      let parsed: JournalLine;
      try {
        parsed = JSON.parse(line);
      } catch {
        // A crash can leave a torn last line — skip it, don't lose the rest
        // of the journal over one malformed record.
        continue;
      }
      if (!parsed || typeof parsed !== 'object' || typeof parsed.id !== 'number') continue;
      maxId = Math.max(maxId, parsed.id);
      if (parsed.op === 'ack') {
        pending.delete(parsed.id);
      } else if ((parsed.op === 'add' || parsed.op === 'requeue') && parsed.item) {
        pending.set(parsed.id, parsed.item);
      }
    }

    this.nextId = maxId + 1;
    // Preserve original spool order (ascending id) for replay.
    const ids = Array.from(pending.keys()).sort((a, b) => a - b);
    for (const id of ids) {
      const item = pending.get(id)!;
      this.live.set(id, item);
      this.idOf.set(item, id);
      // Every live entry — whether it was still "ready" or already
      // dequeued-and-in-flight at crash time — lands here undistinguished
      // (the journal has no "dequeued" op), so replay alone can otherwise
      // hand back more entries than maxSize ever allowed into `ready`
      // during normal operation. Respect the same bound enqueue()
      // enforces: push into `ready` only while there's room under
      // maxSize; anything beyond that stays tracked in `live` (still
      // durable, still included in compaction, never dropped) and sits in
      // `backlog` until an ack/give-up frees a slot (see
      // promoteFromBacklog()).
      if (this.ready.length < this.maxSize) {
        this.ready.push(item);
      } else {
        this.backlog.push(item);
      }
    }
    // Everything rehydrated above is now live on disk; seed the running total
    // so the disk-space bound is enforced correctly against a spool inherited
    // from a previous process.
    this.recomputeLiveBytes();
  }

  private appendLine(line: JournalLine): void {
    if (!this.spoolWritable) return;
    try {
      // `mode` only takes effect when this call creates the file (first
      // write to a fresh spool) — restrict it to the owner since spooled
      // lines are raw event payloads (potential PII). hardenPermissions()
      // below covers the file-already-exists case / umask edge cases.
      fs.appendFileSync(this.spoolPath, JSON.stringify(line) + '\n', { mode: 0o600 });
    } catch (err) {
      this.spoolWritable = false;
      this.warnDegraded(err);
      return;
    }
    this.hardenPermissions(this.spoolPath, 0o600);
    this.opsSinceCompaction++;
    if (this.opsSinceCompaction >= this.compactionIntervalOps || this.spoolFileTooLarge()) {
      this.compact();
    }
  }

  private pruneSpoolEntry(id: number): void {
    const prev = this.live.get(id);
    if (prev) this.liveBytes -= this.lineBytes(id, prev);
    this.live.delete(id);
    this.appendLine({ op: 'ack', id });
    this.promoteFromBacklog();
  }

  /** Move backlog entries (see `backlog` field doc) into `ready` as room
   *  frees up under maxSize, so entries recovered by a replay that
   *  exceeded maxSize still eventually get delivered instead of being
   *  stranded forever. */
  private promoteFromBacklog(): void {
    while (this.backlog.length > 0 && this.ready.length < this.maxSize) {
      this.ready.push(this.backlog.shift()!);
    }
  }

  private spoolFileTooLarge(): boolean {
    try {
      return fs.statSync(this.spoolPath).size > this.maxSpoolBytes;
    } catch {
      return false;
    }
  }

  private compact(): void {
    if (!this.spoolWritable) return;
    const tmpPath = `${this.spoolPath}.tmp-${process.pid}-${Date.now()}`;
    try {
      const lines: string[] = [];
      let bytes = 0;
      for (const [id, item] of this.live) {
        const line = JSON.stringify({ op: 'add', id, item } satisfies JournalLine);
        lines.push(line);
        bytes += Buffer.byteLength(line, 'utf8') + 1; // +1 for the '\n' terminator
      }
      fs.writeFileSync(tmpPath, lines.length ? lines.join('\n') + '\n' : '', { mode: 0o600 });
      fs.renameSync(tmpPath, this.spoolPath);
      this.hardenPermissions(this.spoolPath, 0o600);
      // The rewritten file contains exactly the live set — resync the running
      // total to the authoritative on-disk footprint.
      this.liveBytes = bytes;
      this.opsSinceCompaction = 0;
    } catch (err) {
      this.spoolWritable = false;
      this.warnDegraded(err);
      try { fs.unlinkSync(tmpPath); } catch { /* best-effort cleanup */ }
    }
  }

  /** Best-effort permission hardening on top of the `mode` already passed
   *  to the fs call that created `targetPath` (belt-and-suspenders against
   *  a permissive umask or a platform/filesystem that only partially
   *  honors creation-time mode). Never marks the queue degraded and never
   *  throws: chmod failing here (e.g. unsupported on Windows, or on a
   *  filesystem without POSIX permission bits) is not a durability
   *  failure, only a missed hardening opportunity. */
  private hardenPermissions(targetPath: string, mode: number): void {
    try {
      fs.chmodSync(targetPath, mode);
    } catch {
      // Best-effort only — see comment above.
    }
  }

  private warnDegraded(err: unknown): void {
    if (this.warned) return;
    this.warned = true;
    if (typeof console !== 'undefined' && typeof console.warn === 'function') {
      console.warn(
        `[aether] DurableEventQueue: spool at '${this.spoolPath}' is unusable (${String(
          (err as Error)?.message ?? err,
        )}) — continuing in-memory-only, events will not survive a process restart.`,
      );
    }
  }

  /** Serialized size (in bytes, including the '\n' terminator) of the spool
   *  line that persists this entry — the exact per-entry contribution
   *  compaction writes, so `liveBytes` tracks the compacted file size. */
  private lineBytes(id: number, item: QueuedEvent): number {
    return Buffer.byteLength(JSON.stringify({ op: 'add', id, item }), 'utf8') + 1;
  }

  private recomputeLiveBytes(): void {
    let bytes = 0;
    for (const [id, item] of this.live) bytes += this.lineBytes(id, item);
    this.liveBytes = bytes;
  }

  /** Surface a disk-space-bound rejection: never silent. Prefer the host's
   *  callback; fall back to a one-time console warning so a queue used
   *  without a callback still signals that it is shedding events. A throwing
   *  callback is isolated — enqueue() must not fail because of it. */
  private notifySpoolFull(attemptedBytes: number): void {
    const info: SpoolFullInfo = {
      spoolPath: this.spoolPath,
      maxSpoolBytes: this.maxSpoolBytes,
      liveBytes: this.liveBytes,
      attemptedBytes,
    };
    if (this.onSpoolFullCb) {
      try {
        this.onSpoolFullCb(info);
      } catch {
        /* a host callback must never break enqueue() */
      }
      return;
    }
    if (this.spoolFullWarned) return;
    this.spoolFullWarned = true;
    if (typeof console !== 'undefined' && typeof console.warn === 'function') {
      console.warn(
        `[aether] DurableEventQueue: spool at '${this.spoolPath}' reached its ${this.maxSpoolBytes}-byte bound ` +
          `(live=${this.liveBytes}) — rejecting new events until it drains. Set onSpoolFull to handle this.`,
      );
    }
  }
}
