// =============================================================================
// Aether SDK — BASE VM TRACKER (Tier 2 Thin Client)
// Minimal base for all VM trackers — raw data emission only.
// =============================================================================

export interface TrackerCallbacks {
  onTransaction: (txHash: string, data: Record<string, unknown>) => void;
}

export abstract class BaseVMTracker {
  protected callbacks: TrackerCallbacks;

  constructor(callbacks: TrackerCallbacks) {
    this.callbacks = callbacks;
  }

  destroy(): void { /* base cleanup — override if needed */ }
}
