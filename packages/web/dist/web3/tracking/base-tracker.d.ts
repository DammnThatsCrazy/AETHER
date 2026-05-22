export interface TrackerCallbacks {
    onTransaction: (txHash: string, data: Record<string, unknown>) => void;
}
export declare abstract class BaseVMTracker {
    protected callbacks: TrackerCallbacks;
    constructor(callbacks: TrackerCallbacks);
    destroy(): void;
}
