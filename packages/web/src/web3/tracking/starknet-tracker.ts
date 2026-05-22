// =============================================================================
// Aether SDK — STARKNET TRACKER (Tier 2 Thin Client)
// Ships raw Starknet transaction data to backend.
// =============================================================================

import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';

export class StarknetTracker extends BaseVMTracker {
  constructor(callbacks: TrackerCallbacks) {
    super(callbacks);
  }

  processTransaction(tx: { transaction_hash: string; [key: string]: unknown }): void {
    this.callbacks.onTransaction(tx.transaction_hash, { ...tx, vm: 'starknet' });
  }
}
