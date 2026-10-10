import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';
export declare class TonTracker extends BaseVMTracker {
    constructor(callbacks: TrackerCallbacks);
    processTransaction(tx: {
        transaction_id?: {
            hash?: string;
        };
        [key: string]: unknown;
    }): void;
}
