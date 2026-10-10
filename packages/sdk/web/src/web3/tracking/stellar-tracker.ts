import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';
export class StellarTracker extends BaseVMTracker {
  constructor(callbacks: TrackerCallbacks) { super(callbacks); }
  processTransaction(tx: { hash: string; [key: string]: unknown }): void {
    this.callbacks.onTransaction(tx.hash, { ...tx, vm: 'stellar' });
  }
}
