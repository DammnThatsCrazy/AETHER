import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';
export declare class HederaTracker extends BaseVMTracker {
    constructor(callbacks: TrackerCallbacks);
    processTransaction(tx: {
        transactionId: string;
        [key: string]: unknown;
    }): void;
}
