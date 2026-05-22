import type { DeviceContext } from '../types';
export interface SemanticContext {
    eventId: string;
    timestamp: string;
    sdkVersion: string;
    platform: 'web';
    device: {
        type: DeviceContext['type'];
        os: string;
        language: string;
        online: boolean;
        viewportWidth: number;
        viewportHeight: number;
    };
    pageUrl: string;
    referrer: string;
    sessionId: string;
}
export declare class SemanticContextCollector {
    private sdkVersion;
    private sessionId;
    constructor(sdkVersion: string);
    /** Build Tier 1 semantic context for an event */
    collect(): SemanticContext;
    /** Clean up */
    destroy(): void;
}
