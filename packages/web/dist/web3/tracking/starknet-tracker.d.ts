import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';
export declare class StarknetTracker extends BaseVMTracker {
    constructor(callbacks: TrackerCallbacks);
    processTransaction(tx: {
        transaction_hash: string;
        [key: string]: unknown;
    }): void;
}
