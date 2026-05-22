// =============================================================================
// Aether SDK — TON TRACKER (Tier 2 Thin Client)
// Ships raw TON transaction data to backend.
// =============================================================================

import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';

export class TonTracker extends BaseVMTracker {
  constructor(callbacks: TrackerCallbacks) {
    super(callbacks);
  }

  processTransaction(tx: { transaction_id?: { hash?: string }; [key: string]: unknown }): void {
    const txHash = tx.transaction_id?.hash ?? '';
    this.callbacks.onTransaction(txHash, { ...tx, vm: 'ton' });
  }
}
