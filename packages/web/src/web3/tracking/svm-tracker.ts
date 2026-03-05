// =============================================================================
// AETHER SDK — SOLANA (SVM) TRACKER (Tier 2 Thin Client)
// Ships raw transaction data to backend. No program detection, no analytics.
// =============================================================================

import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';

export class SVMTracker extends BaseVMTracker {
  constructor(callbacks: TrackerCallbacks) {
    super(callbacks);
  }

  /** Process a Solana transaction — ship raw data */
  processTransaction(tx: {
    signature: string;
    programIds?: string[];
    fee?: number;
    accountKeys?: string[];
    [key: string]: unknown;
  }): void {
    this.callbacks.onTransaction(tx.signature, {
      ...tx,
      vm: 'svm',
    });
  }
}
