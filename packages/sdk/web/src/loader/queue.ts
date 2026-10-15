// =============================================================================
// Aether SDK — PRE-LOAD COMMAND QUEUE
//
// The loader is async: the SDK bundle is fetched after the script tag is parsed.
// Customer code that calls Aether.track() immediately after the snippet has to
// work anyway, so a stub global absorbs those calls and the loader replays them
// once the real SDK is live.
//
// The contract that matters: nothing a customer called before load may be lost
// or reordered, and a command that throws on replay must not break the page.
// =============================================================================

export type QueueCommand = 'track' | 'identify' | 'page' | 'ready';

/** A queued call: the command name and the arguments it was invoked with. */
export type QueueEntry = [QueueCommand, unknown[]];

export interface AetherStub {
  q: QueueEntry[];
  track(...args: unknown[]): void;
  identify(...args: unknown[]): void;
  page(...args: unknown[]): void;
  ready(fn: () => void): void;
}

/** Minimal shape of the live SDK surface the queue replays onto. */
export type ReplayTarget = Partial<
  Record<QueueCommand, (...args: unknown[]) => unknown>
>;

export interface DrainResult {
  /** Commands successfully replayed, in queue order. */
  drained: number;
  /** Commands that threw or had no matching SDK method. Never rethrown. */
  failures: Array<{ entry: QueueEntry; reason: string }>;
}

/**
 * Create the pre-load stub.
 *
 * Arguments are captured as a real array rather than the `arguments` object so
 * the queue survives serialization and is directly assertable in tests.
 */
export function createStub(): AetherStub {
  const stub: AetherStub = {
    q: [],
    track(...args: unknown[]) {
      stub.q.push(['track', args]);
    },
    identify(...args: unknown[]) {
      stub.q.push(['identify', args]);
    },
    page(...args: unknown[]) {
      stub.q.push(['page', args]);
    },
    ready(fn: () => void) {
      stub.q.push(['ready', [fn]]);
    },
  };
  return stub;
}

/**
 * Install the stub on a global object, idempotently.
 *
 * Idempotent on purpose: a page may include the snippet twice, or the SDK may
 * already have loaded. Overwriting an existing queue would silently discard
 * calls the customer already made.
 */
export function installStub(target: Record<string, unknown> = globalThis as unknown as Record<string, unknown>): AetherStub {
  const existing = target.Aether as (AetherStub & { __aetherLive?: boolean }) | undefined;

  // Already live (a real SDK, not a stub) — leave it alone.
  if (existing && existing.__aetherLive) return existing;

  // An existing stub: keep it, and keep whatever it has already queued.
  if (existing && Array.isArray(existing.q)) return existing;

  const stub = createStub();
  target.Aether = stub;
  return stub;
}

/**
 * Replay queued commands onto the live SDK, in order.
 *
 * Every failure is captured rather than thrown: a customer's malformed
 * identify() call must not take down their page, and the loader still reports
 * the failure through the returned result.
 */
export function drainQueue(sdk: ReplayTarget, entries: QueueEntry[]): DrainResult {
  const result: DrainResult = { drained: 0, failures: [] };

  for (const entry of entries) {
    const [command, args] = entry;
    const method = sdk[command];
    if (typeof method !== 'function') {
      result.failures.push({ entry, reason: `SDK has no ${command}() method` });
      continue;
    }
    try {
      method(...args);
      result.drained += 1;
    } catch (error) {
      result.failures.push({
        entry,
        reason: error instanceof Error ? error.message : String(error),
      });
    }
  }

  return result;
}
