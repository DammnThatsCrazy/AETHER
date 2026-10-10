export declare const EVENT_CONSENT_PURPOSE: Readonly<Record<string, string>>;
/** Every canonical event type the backend registry recognises. */
export declare const CANONICAL_EVENT_TYPES: ReadonlySet<string>;
/** True if `type` is a canonical registry event type. */
export declare function isCanonicalEventType(type: string): boolean;
