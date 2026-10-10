export type AutocaptureMode = 'off' | 'safe' | 'custom';
export type ConsentMode = 'none' | 'callback' | 'deferred' | 'required';
export type ReleaseChannel = 'managed_stable' | 'security_auto' | 'compatible_auto' | 'patch_auto' | 'pinned';
/** How the SDK got onto the page. Reported to the fleet for drift analysis. */
export type InstallMode = 'cdn_auto' | 'cdn_loader' | 'npm';
export interface AutoInitConfig {
    sdkKey: string;
    siteId: string;
    endpoint: string;
    autocapture: AutocaptureMode;
    consentMode: ConsentMode;
    debug: boolean;
    releaseChannel: ReleaseChannel;
}
export declare const DEFAULT_AUTO_INIT: Omit<AutoInitConfig, 'sdkKey' | 'siteId'>;
/** data-* attribute name -> config field. */
declare const ATTRIBUTE_MAP: {
    readonly 'data-key': "sdkKey";
    readonly 'data-site': "siteId";
    readonly 'data-endpoint': "endpoint";
    readonly 'data-autocapture': "autocapture";
    readonly 'data-consent': "consentMode";
    readonly 'data-debug': "debug";
    readonly 'data-channel': "releaseChannel";
};
export type RawAttributes = Partial<Record<keyof typeof ATTRIBUTE_MAP, string>>;
export interface ResolveOptions {
    /** Overrides merged over the defaults; wins over attributes when set. */
    overrides?: Partial<AutoInitConfig>;
    /** Where the config came from, recorded for fleet attribution. */
    installMode?: InstallMode;
}
export interface ResolveResult {
    config: AutoInitConfig | null;
    installMode: InstallMode;
    /** Fatal problems. A non-empty list means `config` is null. */
    errors: string[];
    /** Non-fatal problems worth surfacing in debug mode. */
    warnings: string[];
}
/**
 * Read data-* attributes from a <script> element.
 *
 * Accepts a plain record as well so the contract is testable without a DOM.
 */
export declare function readScriptAttributes(script: HTMLScriptElement | Record<string, string | undefined>): RawAttributes;
/**
 * Normalize an ingest endpoint.
 *
 * Trailing slashes are stripped so path joins cannot produce `//v1/batch`.
 * Plain http is rejected outside localhost: publishing keys over cleartext
 * would leak the key to anyone on the path.
 */
export declare function normalizeEndpoint(endpoint: string): {
    endpoint: string | null;
    error: string | null;
};
/**
 * Build a validated config from snippet attributes.
 *
 * Returns errors rather than throwing: a misconfigured snippet must not break
 * the customer's page. The loader decides what to do with the errors.
 */
export declare function resolveConfig(attrs: RawAttributes, options?: ResolveOptions): ResolveResult;
/**
 * Locate the script tag that loaded the loader.
 *
 * document.currentScript is null inside async callbacks, so fall back to
 * matching on the loader filename.
 */
export declare function findLoaderScript(doc?: Document | undefined): HTMLScriptElement | null;
export {};
