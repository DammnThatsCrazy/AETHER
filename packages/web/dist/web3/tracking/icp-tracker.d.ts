import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';
export declare class ICPTracker extends BaseVMTracker {
    constructor(callbacks: TrackerCallbacks);
    processTransaction(tx: {
        blockIndex: string;
        [key: string]: unknown;
    }): void;
}
