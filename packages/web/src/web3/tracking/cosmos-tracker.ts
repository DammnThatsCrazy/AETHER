// =============================================================================
// AETHER SDK — COSMOS / SEI TRACKER (Tier 2 Thin Client)
// Ships raw transaction data to backend. No IBC detection, no analytics.
// =============================================================================

import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';

export class CosmosTracker extends BaseVMTracker {
  constructor(callbacks: TrackerCallbacks) {
    super(callbacks);
  }

  /** Process a Cosmos/SEI transaction — ship raw data */
  processTransaction(tx: {
    txhash: string;
    messages?: { '@type': string; [key: string]: unknown }[];
    [key: string]: unknown;
  }): void {
    this.callbacks.onTransaction(tx.txhash, {
      ...tx,
      vm: 'cosmos',
    });
  }
}
