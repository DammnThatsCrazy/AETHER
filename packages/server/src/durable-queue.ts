// DurableEventQueue — an opt-in, disk-backed drop-in for EventQueue.
//
// Program: docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md, section 2
// ("A single /v1/batch ingestion owner + Node SDK durability"), milestone M4.
//
// EventQueue (./queue.ts) is a bare in-process array: if the host process
// crashes or restarts between a caller's track() call and a successful
// transport send, every queued-but-unsent event is gone with no signal to
// the caller (track() already returned). DurableEventQueue closes that gap
// by mirroring every accepted event into an append-only local JSON-Lines
// spool file, so a crash between enqueue() and a confirmed send can be
// recovered by replaying the spool on the next process start.
//
// Status: this is ONLY the M4 increment — the standalone class. Wiring it
// into AetherServerSDK as an opt-in/default queue implementation (M5, per
// the program doc) is NOT part of this change; index.ts's track()/flush()
// are untouched. ack() below is the hook a future M5 change would call
// from flush() on confirmed delivery — nothing calls it yet in this repo.
//
// Interface parity: enqueue / dequeueReady / requeue / size / drain behave
// identically to EventQueue (same inputs produce the same in-memory
// results and return values), so this class is a structural drop-in
// wherever EventQueue is used today. The only behavioral difference is the
// side-channel: accepted events are also durably persisted, and ack() is
// available as an additive capability beyond the EventQueue interface.
//
// Bounded footprint:
//   - In-memory / "ready to send" entries are bounded by `maxSize`, exactly
//     like EventQueue (default 1000).
//   - The on-disk journal can otherwise grow unboundedly as entries are
//     added, requeued, and acked (each is an appended line) — it is kept
//     bounded by compaction: once the journal exceeds `maxSpoolBytes`
//     (default 5 MiB) or `compactionIntervalOps` appended lines (default
//     200) since the last compaction, the file is rewritten to contain only
//     currently-live (not yet acked) entries, via a temp-file + rename so a
//     crash mid-compaction never corrupts the spool.
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
type EventQueueLike = Pick<EventQueue, 'enqueue' | 'dequeueReady' | 'requeue' | 'size' | 'drain'>;

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
   * Compact (rewrite to only live entries) once the spool file exceeds this
   * many bytes. Bounds disk footprint independent of maxSize, since acked/
   * superseded journal lines accumulate between compactions. Default 5 MiB.
   */
  maxSpoolBytes?: number;
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

  private nextId = 1;
  private opsSinceCompaction = 0;
  private spoolWritable = true;
  private warned = false;

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
    const id = this.nextId++;
    this.live.set(id, record);
    this.idOf.set(record, id);
    this.ready.push(record);
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
    if (id !== undefined) {
      this.live.set(id, next);
      this.idOf.set(next, id);
      this.appendLine({ op: 'requeue', id, item: next });
      this.ready.push(next);
    } else {
      // An item this instance never produced via dequeueReady (e.g.
      // hand-constructed by a caller). Spool it fresh rather than silently
      // accepting an unpersisted event back into the ready queue.
      const newId = this.nextId++;
      this.live.set(newId, next);
      this.idOf.set(next, newId);
      this.appendLine({ op: 'add', id: newId, item: next });
      this.ready.push(next);
    }
  }

  /**
   * Confirm an item was durably delivered (or otherwise permanently
   * resolved) and prune it from the spool. Additive beyond EventQueue's
   * interface — nothing in this repo calls it yet (that wiring is the
   * program doc's M5, not this change); it exists so a future caller can
   * mark successful sends without this queue growing its spool forever.
   * No-ops for an item this instance has no record of.
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
      for (const [id, item] of this.live) {
        lines.push(JSON.stringify({ op: 'add', id, item } satisfies JournalLine));
      }
      fs.writeFileSync(tmpPath, lines.length ? lines.join('\n') + '\n' : '', { mode: 0o600 });
      fs.renameSync(tmpPath, this.spoolPath);
      this.hardenPermissions(this.spoolPath, 0o600);
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
}
