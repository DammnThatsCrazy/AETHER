export interface FormAnalyticsCallbacks {
    onTrack: (event: string, properties: Record<string, unknown>) => void;
}
export interface FormAnalyticsConfig {
    autoDiscover?: boolean;
}
export declare class FormAnalyticsModule {
    private callbacks;
    private listeners;
    private observers;
    constructor(callbacks: FormAnalyticsCallbacks, config?: FormAnalyticsConfig);
    /** Attach listeners to a specific form */
    trackForm(form: HTMLFormElement | string): void;
    /** Clean up all listeners */
    destroy(): void;
    private startAutoDiscovery;
    private attachListeners;
    private isField;
}
