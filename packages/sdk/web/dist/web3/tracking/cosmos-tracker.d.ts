import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';
export declare class CosmosTracker extends BaseVMTracker {
    constructor(callbacks: TrackerCallbacks);
    /** Process a Cosmos/SEI transaction — ship raw data */
    processTransaction(tx: {
        txhash: string;
        messages?: {
            '@type': string;
            [key: string]: unknown;
        }[];
        [key: string]: unknown;
    }): void;
}
