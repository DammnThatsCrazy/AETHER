// =============================================================================
// AETHER SDK — BITCOIN TRACKER (Tier 2 Thin Client)
// Ships raw transaction data to backend. No UTXO tracking, no fee analytics.
// =============================================================================

import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';

export class BTCTracker extends BaseVMTracker {
  constructor(callbacks: TrackerCallbacks) {
    super(callbacks);
  }

  /** Process a Bitcoin transaction — ship raw data */
  processTransaction(tx: {
    txid: string;
    fee?: number;
    size?: number;
    weight?: number;
    [key: string]: unknown;
  }): void {
    this.callbacks.onTransaction(tx.txid, {
      ...tx,
      vm: 'bitcoin',
    });
  }
}
