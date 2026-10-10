import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';
export declare class SVMTracker extends BaseVMTracker {
    constructor(callbacks: TrackerCallbacks);
    /** Process a Solana transaction — ship raw data */
    processTransaction(tx: {
        signature: string;
        programIds?: string[];
        fee?: number;
        accountKeys?: string[];
        [key: string]: unknown;
    }): void;
}
