export interface FingerprintComponents {
    canvasHash: string;
    webglRenderer: string;
    webglVendor: string;
    audioHash: string;
    screenResolution: string;
    colorDepth: number;
    timezone: string;
    language: string;
    languages: string[];
    platform: string;
    hardwareConcurrency: number;
    deviceMemory: number;
    touchSupport: boolean;
    fontHash: string;
    cookieEnabled: boolean;
    doNotTrack: string | null;
    pixelRatio: number;
}
export declare class DeviceFingerprintCollector {
    private fingerprintId;
    private components;
    generate(): Promise<{
        fingerprintId: string;
        components: FingerprintComponents;
    }>;
    getFingerprintId(): string | null;
    getComponents(): FingerprintComponents | null;
    /**
     * Clear the in-memory fingerprint AND the cached storage. Called when
     * `personalization` consent is revoked so no further events can be stamped
     * with a device fingerprint until consent is granted again.
     */
    reset(): void;
    private collectCanvas;
    private collectWebGL;
    private collectAudio;
    private collectFonts;
    private sha256;
    private loadCached;
    private persistCache;
}
