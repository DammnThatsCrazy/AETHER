import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';
export class AlgorandTracker extends BaseVMTracker {
  constructor(callbacks: TrackerCallbacks) { super(callbacks); }
  processTransaction(tx: { id: string; [key: string]: unknown }): void {
    this.callbacks.onTransaction(tx.id, { ...tx, vm: 'algorand' });
  }
}
