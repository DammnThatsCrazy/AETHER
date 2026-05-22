import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';
export declare class TronTracker extends BaseVMTracker {
    constructor(callbacks: TrackerCallbacks);
    /** Process a TRON transaction — ship raw data */
    processTransaction(tx: {
        txID: string;
        [key: string]: unknown;
    }): void;
}
