import type { InstallMode } from './auto-init';
/** Canonical event types emitted at each install milestone. */
export type InstallSignal = 'sdk_loaded' | 'sdk_initialized' | 'sdk_init_failed';
export interface InstallSignalInput {
    signal: InstallSignal;
    installMode: InstallMode;
    /** Version of the loader bundle that is running, from its own build. */
    loaderVersion: string;
    /** Resolved SDK bundle version, once known. */
    sdkVersion?: string | null;
    /** Publishable SDK key from the snippet — same credential the SDK uses. */
    sdkKey: string;
    siteId: string;
    endpoint: string;
    /** Human-readable cause, for the failure signal. */
    reason?: string;
    /** Non-fatal snippet problems worth surfacing to the site owner. */
    warnings?: string[];
    /** Injected for deterministic tests. */
    now?: () => Date;
    /** Injected for deterministic tests. */
    randomId?: () => string;
}
/**
 * Sends one already-serialized signal. Swappable so tests never touch the
 * network, and so a caller can route signals through their own transport.
 */
export type SignalTransport = (url: string, body: string, headers: Record<string, string>) => void;
/** The canonical envelope fields the batch endpoint requires. */
export interface InstallSignalEvent {
    id: string;
    type: InstallSignal;
    timestamp: string;
    sessionId: string;
    anonymousId: string;
    properties: Record<string, unknown>;
    context: {
        library: {
            name: string;
            version: string;
        };
        surface: string;
        schemaVersion: string;
        sequence: {
            event: number;
        };
    };
}
/**
 * Build the canonical event for a signal.
 *
 * `sessionId`/`anonymousId` are minted here rather than reused from the SDK:
 * for `sdk_init_failed` there is no SDK session to read, and a verifier that
 * only worked on the happy path would be useless for the case it exists for.
 */
export declare function buildSignalEvent(input: InstallSignalInput): InstallSignalEvent;
/**
 * POST transport matching the SDK's own batch contract.
 *
 * Uses fetch with `keepalive` rather than `navigator.sendBeacon`: sendBeacon
 * cannot carry an Authorization header, which would force the publishable key
 * into the URL — visible in proxy logs, CDN logs and referrer headers.
 */
export declare function createBeaconTransport(fetchImpl?: typeof fetch | undefined): SignalTransport;
/**
 * Emit one install signal. Returns whether it was handed to the transport;
 * never throws, because a reporting failure must not break the page.
 */
export declare function reportInstallSignal(input: InstallSignalInput, transport?: SignalTransport): boolean;
