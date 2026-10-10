import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';
export class HederaTracker extends BaseVMTracker {
  constructor(callbacks: TrackerCallbacks) { super(callbacks); }
  processTransaction(tx: { transactionId: string; [key: string]: unknown }): void {
    this.callbacks.onTransaction(tx.transactionId, { ...tx, vm: 'hedera' });
  }
}
