// =============================================================================
// AETHER SDK — MOVE VM (SUI) TRACKER (Tier 2 Thin Client)
// Ships raw transaction data to backend. No protocol detection, no analytics.
// =============================================================================

import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';

export class MoveTracker extends BaseVMTracker {
  constructor(callbacks: TrackerCallbacks) {
    super(callbacks);
  }

  /** Process a SUI transaction — ship raw data */
  processTransaction(tx: {
    digest: string;
    [key: string]: unknown;
  }): void {
    this.callbacks.onTransaction(tx.digest, {
      ...tx,
      vm: 'movevm',
    });
  }
}
