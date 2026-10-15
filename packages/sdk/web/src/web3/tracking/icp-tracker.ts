import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';
export class ICPTracker extends BaseVMTracker {
  constructor(callbacks: TrackerCallbacks) { super(callbacks); }
  processTransaction(tx: { blockIndex: string; [key: string]: unknown }): void {
    this.callbacks.onTransaction(tx.blockIndex, { ...tx, vm: 'icp' });
  }
}
