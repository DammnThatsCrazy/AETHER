import type { DeviceContext, CampaignContext, PageContext } from '../types';
/** Generate a UUID v4 */
export declare function generateId(): string;
/** Get current ISO timestamp */
export declare function now(): string;
/** SHA-256 hash (async, uses SubtleCrypto where available) */
export declare function sha256(input: string): Promise<string>;
/** Anonymize an IP address (zero last octet for IPv4, last 80 bits for IPv6) */
export declare function anonymizeIP(ip: string): string;
/** Detect device context from browser environment */
export declare function getDeviceContext(): DeviceContext;
/** Configure URL sanitization from AetherConfig (privacy-safe default: on). */
export declare function configureUrlSanitization(options?: {
    enabled?: boolean;
    additionalParams?: string[];
}): void;
/** Strip a query string (leading '?' optional) of sensitive parameters. */
export declare function sanitizeSearch(search: string): string;
/**
 * Strip fragments and sensitive query params (aether_ref, aether_cid, click
 * IDs, token params) from a URL before it is transmitted anywhere.
 * Relative URLs are resolved against the current page origin when available.
 */
export declare function sanitizeUrl(url: string | undefined | null): string;
/** Get current page context (URLs sanitized before transmission) */
export declare function getPageContext(): PageContext;
/** Extract campaign/UTM parameters from URL */
export declare function getCampaignContext(): CampaignContext;
export declare const storage: {
    get<T>(key: string): T | null;
    set(key: string, value: unknown): void;
    remove(key: string): void;
    clear(): void;
};
export declare const cookies: {
    get(name: string): string | null;
    set(name: string, value: string, days?: number, domain?: string): void;
    remove(name: string, domain?: string): void;
};
export declare function maskSensitiveData(value: string, additionalPatterns?: RegExp[]): string;
/** Check if a form field is likely sensitive */
export declare function isSensitiveField(el: HTMLInputElement | HTMLTextAreaElement): boolean;
export declare function throttle<T extends (...args: unknown[]) => void>(fn: T, ms: number): T;
export declare function debounce<T extends (...args: unknown[]) => void>(fn: T, ms: number): T;
