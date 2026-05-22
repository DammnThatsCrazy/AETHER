import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';
export declare class NEARTracker extends BaseVMTracker {
    constructor(callbacks: TrackerCallbacks);
    /** Process a NEAR transaction — ship raw data */
    processTransaction(tx: {
        hash: string;
        receiverId?: string;
        actions?: {
            kind: string;
            args?: Record<string, unknown>;
        }[];
        [key: string]: unknown;
    }): void;
}
