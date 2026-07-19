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
    constructor(sdkVersion: string);
    /**
     * Build Tier 1 semantic context for an event.
     *
     * The canonical `sessionId` (owned by SessionManager) and top-level `eventId`
     * are passed in by the caller — the collector NEVER mints its own, so every
     * event carries a single agreeing session id and event id.
     */
    collect(sessionId: string, eventId: string): SemanticContext;
    /** Clean up */
    destroy(): void;
}
