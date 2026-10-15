import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';
export declare class AlgorandTracker extends BaseVMTracker {
    constructor(callbacks: TrackerCallbacks);
    processTransaction(tx: {
        id: string;
        [key: string]: unknown;
    }): void;
}
