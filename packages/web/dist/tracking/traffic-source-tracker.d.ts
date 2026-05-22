export interface TrafficSourceData {
    referrer: string;
    referrerDomain: string;
    utmSource?: string | null;
    utmMedium?: string | null;
    utmCampaign?: string | null;
    utmTerm?: string | null;
    utmContent?: string | null;
    clickIds: Record<string, string>;
    landingPage: string;
}
export declare class TrafficSourceTracker {
    private data;
    constructor();
    /** Detect traffic source on page load and return raw data */
    detect(): TrafficSourceData;
    /** Get the detected source data for event payload */
    toEventPayload(): Record<string, unknown>;
}
