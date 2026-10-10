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
export type ReplayTarget = Partial<Record<QueueCommand, (...args: unknown[]) => unknown>>;
export interface DrainResult {
    /** Commands successfully replayed, in queue order. */
    drained: number;
    /** Commands that threw or had no matching SDK method. Never rethrown. */
    failures: Array<{
        entry: QueueEntry;
        reason: string;
    }>;
}
/**
 * Create the pre-load stub.
 *
 * Arguments are captured as a real array rather than the `arguments` object so
 * the queue survives serialization and is directly assertable in tests.
 */
export declare function createStub(): AetherStub;
/**
 * Install the stub on a global object, idempotently.
 *
 * Idempotent on purpose: a page may include the snippet twice, or the SDK may
 * already have loaded. Overwriting an existing queue would silently discard
 * calls the customer already made.
 */
export declare function installStub(target?: Record<string, unknown>): AetherStub;
/**
 * Replay queued commands onto the live SDK, in order.
 *
 * Every failure is captured rather than thrown: a customer's malformed
 * identify() call must not take down their page, and the loader still reports
 * the failure through the returned result.
 */
export declare function drainQueue(sdk: ReplayTarget, entries: QueueEntry[]): DrainResult;
