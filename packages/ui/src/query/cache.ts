type Subscriber = () => void;

interface CacheEntry<T> {
  readonly data: T;
  readonly fetchedAt: number;
}

class QueryCache {
  private readonly entries = new Map<string, CacheEntry<unknown>>();
  private readonly inFlight = new Map<string, Promise<unknown>>();
  private readonly subscribers = new Map<string, Set<Subscriber>>();

  get<T>(key: string): CacheEntry<T> | null {
    const entry = this.entries.get(key);
    return entry !== undefined ? (entry as CacheEntry<T>) : null;
  }

  set<T>(key: string, data: T): void {
    this.entries.set(key, { data, fetchedAt: Date.now() });
    this.notify(key);
  }

  isStale(key: string, staleTimeMs: number): boolean {
    const entry = this.entries.get(key);
    if (entry === undefined) return true;
    return Date.now() - entry.fetchedAt > staleTimeMs;
  }

  getInFlight<T>(key: string): Promise<T> | null {
    const p = this.inFlight.get(key);
    return p !== undefined ? (p as Promise<T>) : null;
  }

  setInFlight<T>(key: string, promise: Promise<T>): void {
    this.inFlight.set(key, promise as Promise<unknown>);
    void promise.finally(() => this.inFlight.delete(key));
  }

  invalidate(key: string): void {
    this.entries.delete(key);
    this.notify(key);
  }

  invalidatePrefix(prefix: string): void {
    for (const key of this.entries.keys()) {
      if (key.startsWith(prefix)) {
        this.entries.delete(key);
        this.notify(key);
      }
    }
  }

  subscribe(key: string, fn: Subscriber): () => void {
    let set = this.subscribers.get(key);
    if (set === undefined) {
      set = new Set<Subscriber>();
      this.subscribers.set(key, set);
    }
    set.add(fn);
    return () => this.subscribers.get(key)?.delete(fn);
  }

  private notify(key: string): void {
    this.subscribers.get(key)?.forEach(fn => fn());
  }
}

export const queryCache = new QueryCache();
