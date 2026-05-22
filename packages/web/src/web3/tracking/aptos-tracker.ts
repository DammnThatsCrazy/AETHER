// =============================================================================
// Aether SDK — APTOS TRACKER (Tier 2 Thin Client)
// Ships raw Aptos transaction data to backend.
// =============================================================================

import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';

export class AptosTracker extends BaseVMTracker {
  constructor(callbacks: TrackerCallbacks) {
    super(callbacks);
  }

  processTransaction(tx: { hash: string; [key: string]: unknown }): void {
    this.callbacks.onTransaction(tx.hash, { ...tx, vm: 'aptos' });
  }
}
