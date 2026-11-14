type Subscriber = () => void;

interface CacheEntry<T> {
  readonly data: T;
  readonly fetchedAt: number;
}

class QueryCache {
  private readonly entries = new Map<string, CacheEntry<unknown>>();
  private readonly inFlight = new Map<string, Promise<unknown>>();
  private readonly subscribers = new Map<string, Set<Subscriber>>();
  private generationValue = 0;

  /**
   * Bumped by clear(). A fetch records the generation it started in, and set()
   * drops a result from an older generation, so a response for the previous
   * signed-in identity can never repopulate the cache after a switch.
   */
  get generation(): number {
    return this.generationValue;
  }

  get<T>(key: string): CacheEntry<T> | null {
    const entry = this.entries.get(key);
    return entry !== undefined ? (entry as CacheEntry<T>) : null;
  }

  set<T>(key: string, data: T, generation?: number): void {
    if (generation !== undefined && generation !== this.generationValue) return;
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
    // Observing both outcomes avoids the orphan rejected promise created by
    // `finally()`, while still removing the in-flight entry deterministically.
    // Only remove this promise's own entry: after clear(), a replacement
    // request may already be registered under the same key.
    const release = () => {
      if (this.inFlight.get(key) === promise) this.inFlight.delete(key);
    };
    void promise.then(release, release);
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

  /**
   * Forget every cached result and in-flight request. The cache is
   * module-global and keys are not tenant-scoped, so it must be cleared
   * whenever the signed-in identity changes; otherwise a tenant switch
   * without a reload shows the previous tenant's data. Subscribed hooks are
   * notified so mounted views refetch under the new identity.
   */
  clear(): void {
    this.generationValue += 1;
    this.entries.clear();
    this.inFlight.clear();
    for (const key of this.subscribers.keys()) this.notify(key);
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
