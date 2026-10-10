import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';
export declare class AptosTracker extends BaseVMTracker {
    constructor(callbacks: TrackerCallbacks);
    processTransaction(tx: {
        hash: string;
        [key: string]: unknown;
    }): void;
}
