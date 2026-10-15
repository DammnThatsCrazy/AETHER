export interface HeatmapCallbacks {
    onTrack: (event: string, properties: Record<string, unknown>) => void;
}
export interface HeatmapConfig {
    clicks?: boolean;
    movement?: boolean;
    scroll?: boolean;
}
export declare class HeatmapModule {
    private callbacks;
    private config;
    private listeners;
    constructor(callbacks: HeatmapCallbacks, config?: HeatmapConfig);
    /** Start all configured heatmap tracking */
    start(): void;
    /** Stop all tracking and clean up */
    destroy(): void;
    private trackClicks;
    private trackMovement;
    private trackScroll;
    private getSelector;
}
