import { BaseVMTracker, type TrackerCallbacks } from './base-tracker';
export declare class EVMTracker extends BaseVMTracker {
    constructor(callbacks: TrackerCallbacks);
    /** Classify a transaction by its input data (basic naming only) */
    classifyTransaction(input?: string): {
        name: string;
        type: string;
    };
    /** Process a transaction — ship raw data to backend */
    processTransaction(tx: {
        hash: string;
        from: string;
        to: string;
        value: string;
        gasUsed?: string;
        gasPrice?: string;
        input?: string;
        chainId: number;
    }): void;
    destroy(): void;
}
