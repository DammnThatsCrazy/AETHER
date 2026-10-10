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
    /**
     * Build the metadata-only payload for a field interaction.
     *
     * PRIVACY INVARIANT: typed form values, selections, and defaults are NEVER
     * read — only structural metadata (name/type/action) leaves the page. The
     * final scrub is defense-in-depth so no future edit can accidentally ship
     * a value-shaped key.
     */
    private fieldPayload;
    private attachListeners;
    private isField;
}
