// =============================================================================
// Aether SDK — NEAR PROTOCOL TRACKER (Tier 2 Thin Client)
// Ships raw transaction data to backend. No action detection, no analytics.
// =============================================================================

import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';

export class NEARTracker extends BaseVMTracker {
  constructor(callbacks: TrackerCallbacks) {
    super(callbacks);
  }

  /** Process a NEAR transaction — ship raw data */
  processTransaction(tx: {
    hash: string;
    receiverId?: string;
    actions?: { kind: string; args?: Record<string, unknown> }[];
    [key: string]: unknown;
  }): void {
    this.callbacks.onTransaction(tx.hash, {
      ...tx,
      vm: 'near',
    });
  }
}
