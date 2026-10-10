// Bounded in-process event queue with exponential-backoff retry and jitter.

export interface QueuedEvent {
  writeKey: string;
  events: unknown[];
  attempt: number;
  nextRetryAt: number;
}

interface QueueOptions {
  maxSize?: number;
  maxRetries?: number;
  baseRetryMs?: number;
}

export class EventQueue {
  private readonly queue: QueuedEvent[] = [];
  private readonly maxSize: number;
  private readonly maxRetries: number;
  private readonly baseRetryMs: number;

  constructor(opts: QueueOptions = {}) {
    this.maxSize = opts.maxSize ?? 1000;
    this.maxRetries = opts.maxRetries ?? 5;
    this.baseRetryMs = opts.baseRetryMs ?? 2000;
  }

  enqueue(item: Omit<QueuedEvent, 'attempt' | 'nextRetryAt'>): boolean {
    if (this.queue.length >= this.maxSize) return false;
    this.queue.push({ ...item, attempt: 0, nextRetryAt: 0 });
    return true;
  }

  dequeueReady(): QueuedEvent | undefined {
    const now = Date.now();
    const idx = this.queue.findIndex((item) => item.nextRetryAt <= now);
    if (idx === -1) return undefined;
    return this.queue.splice(idx, 1)[0];
  }

  requeue(item: QueuedEvent): void {
    if (item.attempt >= this.maxRetries) return;
    const jitter = Math.random() * 1000;
    const delay = this.baseRetryMs * Math.pow(2, item.attempt) + jitter;
    this.queue.push({ ...item, attempt: item.attempt + 1, nextRetryAt: Date.now() + delay });
  }

  get size(): number {
    return this.queue.length;
  }

  drain(): void {
    this.queue.length = 0;
  }
}
