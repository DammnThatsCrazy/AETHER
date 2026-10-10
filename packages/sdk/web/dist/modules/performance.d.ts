export interface PerformanceModuleConfig {
    onTrack: (event: string, props: Record<string, unknown>) => void;
    sampleRate?: number;
}
export declare class PerformanceModule {
    private config;
    private observers;
    private clsValue;
    private clsEntries;
    private sessionValue;
    private sessionEntries;
    private longTaskCount;
    private longTaskTotalMs;
    private memoryTimer;
    private navSent;
    constructor(config: PerformanceModuleConfig);
    start(): void;
    destroy(): void;
    private observeLCP;
    private observeCLS;
    private flushCLS;
    private observeINP;
    private observeFID;
    private observeFCP;
    private observeLongTasks;
    private captureNavigationTiming;
    private startMemorySampling;
    private emit;
    private observe;
}
