export interface FunnelDefinition {
    id: string;
    name: string;
    steps: {
        id: string;
        name: string;
        event?: string;
        page?: string;
    }[];
}
export interface FunnelCallbacks {
    onTrack: (event: string, properties: Record<string, unknown>) => void;
}
export declare class FunnelModule {
    private callbacks;
    private funnels;
    constructor(callbacks: FunnelCallbacks, config?: {
        definitions?: FunnelDefinition[];
    });
    /** Load funnel definitions from backend config */
    loadDefinitions(definitions: FunnelDefinition[]): void;
    /** Tag an event with matching funnel metadata and ship to backend */
    tagEvent(eventName: string, properties?: Record<string, unknown>): void;
    /** Clean up */
    destroy(): void;
}
