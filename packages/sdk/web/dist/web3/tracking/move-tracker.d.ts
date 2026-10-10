import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';
export declare class MoveTracker extends BaseVMTracker {
    constructor(callbacks: TrackerCallbacks);
    /** Process a SUI transaction — ship raw data */
    processTransaction(tx: {
        digest: string;
        [key: string]: unknown;
    }): void;
}
