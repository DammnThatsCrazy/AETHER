import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';
export declare class BTCTracker extends BaseVMTracker {
    constructor(callbacks: TrackerCallbacks);
    /** Process a Bitcoin transaction — ship raw data */
    processTransaction(tx: {
        txid: string;
        fee?: number;
        size?: number;
        weight?: number;
        [key: string]: unknown;
    }): void;
}
