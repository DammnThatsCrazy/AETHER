export interface AutoDiscoveryCallbacks {
    onTrack: (event: string, properties: Record<string, unknown>) => void;
}
export declare class AutoDiscoveryModule {
    private callbacks;
    private listeners;
    constructor(callbacks: AutoDiscoveryCallbacks);
    /** Start click tracking */
    start(): void;
    /** Stop all tracking and clean up */
    destroy(): void;
    private trackClicks;
    private getSelector;
}
