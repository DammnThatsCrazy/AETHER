// =============================================================================
// Aether SDK — TRON (TVM) TRACKER (Tier 2 Thin Client)
// Ships raw transaction data to backend. No energy/bandwidth analytics.
// =============================================================================

import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';

export class TronTracker extends BaseVMTracker {
  constructor(callbacks: TrackerCallbacks) {
    super(callbacks);
  }

  /** Process a TRON transaction — ship raw data */
  processTransaction(tx: {
    txID: string;
    [key: string]: unknown;
  }): void {
    this.callbacks.onTransaction(tx.txID, {
      ...tx,
      vm: 'tvm',
    });
  }
}
