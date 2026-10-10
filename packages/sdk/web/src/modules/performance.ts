// =============================================================================
// Aether SDK — Performance Module
// Captures Web Vitals (LCP, CLS, INP, TTFB, FCP), Long Tasks, Navigation
// Timing, and memory. All metrics gated by analytics consent.
// Uses PerformanceObserver where available; falls back gracefully.
// =============================================================================

export interface PerformanceModuleConfig {
  onTrack: (event: string, props: Record<string, unknown>) => void;
  sampleRate?: number; // 0–1, default 1.0 (100%)
}

interface VitalEntry {
  name: string;
  value: number;
  rating: 'good' | 'needs-improvement' | 'poor';
  navigationType?: string;
}

// Thresholds per Google Web Vitals spec
const THRESHOLDS = {
  LCP:  { good: 2500, poor: 4000 },
  CLS:  { good: 0.1,  poor: 0.25 },
  INP:  { good: 200,  poor: 500  },
  FID:  { good: 100,  poor: 300  },
  FCP:  { good: 1800, poor: 3000 },
  TTFB: { good: 800,  poor: 1800 },
};

function rate(metric: keyof typeof THRESHOLDS, value: number): 'good' | 'needs-improvement' | 'poor' {
  const t = THRESHOLDS[metric];
  if (value <= t.good) return 'good';
  if (value <= t.poor) return 'needs-improvement';
  return 'poor';
}

export class PerformanceModule {
  private config: PerformanceModuleConfig;
  private observers: PerformanceObserver[] = [];
  private clsValue = 0;
  private clsEntries: PerformanceEntry[] = [];
  private sessionValue = 0;
  private sessionEntries: PerformanceEntry[] = [];
  private longTaskCount = 0;
  private longTaskTotalMs = 0;
  private memoryTimer: ReturnType<typeof setInterval> | null = null;
  private navSent = false;

  constructor(config: PerformanceModuleConfig) {
    this.config = config;
  }

  start(): void {
    if (typeof window === 'undefined' || typeof PerformanceObserver === 'undefined') return;
    if (Math.random() > (this.config.sampleRate ?? 1.0)) return;

    this.observeLCP();
    this.observeCLS();
    this.observeINP();
    this.observeFID();
    this.observeFCP();
    this.observeLongTasks();
    this.captureNavigationTiming();
    this.startMemorySampling();

    // Flush CLS on page hide
    const onHide = () => {
      this.flushCLS();
      document.removeEventListener('visibilitychange', onHide);
    };
    document.addEventListener('visibilitychange', onHide);
  }

  destroy(): void {
    this.observers.forEach((o) => { try { o.disconnect(); } catch { /* */ } });
    this.observers = [];
    if (this.memoryTimer !== null) {
      clearInterval(this.memoryTimer);
      this.memoryTimer = null;
    }
  }

  // ---------------------------------------------------------------------------
  // LCP — Largest Contentful Paint
  // ---------------------------------------------------------------------------
  private observeLCP(): void {
    this.observe('largest-contentful-paint', (list) => {
      const entries = list.getEntries();
      const last = entries[entries.length - 1] as PerformanceEntry & { startTime: number; size: number; element?: Element };
      if (!last) return;
      const value = last.startTime;
      this.emit({ name: 'LCP', value, rating: rate('LCP', value) });
    });
  }

  // ---------------------------------------------------------------------------
  // CLS — Cumulative Layout Shift (session-windowed, reported on page hide)
  // ---------------------------------------------------------------------------
  private observeCLS(): void {
    this.observe('layout-shift', (list) => {
      for (const entry of list.getEntries()) {
        const e = entry as PerformanceEntry & { hadRecentInput: boolean; value: number };
        if (e.hadRecentInput) continue;

        const firstEntry = this.sessionEntries[0];
        const lastEntry = this.sessionEntries[this.sessionEntries.length - 1];
        const gap = firstEntry ? (entry.startTime - (lastEntry as any).startTime) : 0;
        const interval = firstEntry ? (entry.startTime - (firstEntry as any).startTime) : 0;

        if (this.sessionEntries.length && (gap > 1000 || interval > 5000)) {
          if (this.sessionValue > this.clsValue) {
            this.clsValue = this.sessionValue;
            this.clsEntries = [...this.sessionEntries];
          }
          this.sessionValue = 0;
          this.sessionEntries = [];
        }

        this.sessionValue += e.value;
        this.sessionEntries.push(entry);
      }
    });
  }

  private flushCLS(): void {
    if (document.visibilityState !== 'hidden') return;
    if (this.sessionValue > this.clsValue) {
      this.clsValue = this.sessionValue;
    }
    this.emit({ name: 'CLS', value: this.clsValue, rating: rate('CLS', this.clsValue) });
  }

  // ---------------------------------------------------------------------------
  // INP — Interaction to Next Paint (replaces FID in Core Web Vitals 2024)
  // ---------------------------------------------------------------------------
  private observeINP(): void {
    let maxDuration = 0;
    this.observe('event', (list) => {
      for (const entry of list.getEntries()) {
        const e = entry as PerformanceEntry & { processingStart: number; processingEnd: number; duration: number };
        if (e.duration > maxDuration) {
          maxDuration = e.duration;
          this.emit({ name: 'INP', value: maxDuration, rating: rate('INP', maxDuration) });
        }
      }
    }, { durationThreshold: 40 });
  }

  // ---------------------------------------------------------------------------
  // FID — First Input Delay (legacy, iOS/older browsers)
  // ---------------------------------------------------------------------------
  private observeFID(): void {
    this.observe('first-input', (list) => {
      const entry = list.getEntries()[0] as (PerformanceEntry & { processingStart: number; startTime: number }) | undefined;
      if (!entry) return;
      const value = entry.processingStart - entry.startTime;
      this.emit({ name: 'FID', value, rating: rate('FID', value) });
    });
  }

  // ---------------------------------------------------------------------------
  // FCP — First Contentful Paint
  // ---------------------------------------------------------------------------
  private observeFCP(): void {
    this.observe('paint', (list) => {
      for (const entry of list.getEntries()) {
        if (entry.name === 'first-contentful-paint') {
          this.emit({ name: 'FCP', value: entry.startTime, rating: rate('FCP', entry.startTime) });
        }
      }
    });
  }

  // ---------------------------------------------------------------------------
  // Long Tasks
  // ---------------------------------------------------------------------------
  private observeLongTasks(): void {
    this.observe('longtask', (list) => {
      for (const entry of list.getEntries()) {
        this.longTaskCount++;
        this.longTaskTotalMs += entry.duration;
        this.emit({
          name: 'long_task',
          value: entry.duration,
          rating: entry.duration > 100 ? 'poor' : 'needs-improvement',
        });
      }
    });
  }

  // ---------------------------------------------------------------------------
  // Navigation Timing (TTFB + full page load breakdown)
  // ---------------------------------------------------------------------------
  private captureNavigationTiming(): void {
    const send = () => {
      if (this.navSent) return;
      const entries = performance.getEntriesByType('navigation') as PerformanceNavigationTiming[];
      if (!entries.length) return;
      const nav = entries[0]!;
      this.navSent = true;

      const ttfb = nav.responseStart - nav.requestStart;
      this.emit({ name: 'TTFB', value: ttfb, rating: rate('TTFB', ttfb) });

      this.config.onTrack('performance', {
        metric: 'navigation_timing',
        dnsLookup:        nav.domainLookupEnd   - nav.domainLookupStart,
        tcpConnect:       nav.connectEnd         - nav.connectStart,
        tlsNegotiation:   nav.secureConnectionStart > 0 ? nav.connectEnd - nav.secureConnectionStart : 0,
        ttfb,
        responseDownload: nav.responseEnd        - nav.responseStart,
        domInteractive:   nav.domInteractive     - nav.startTime,
        domComplete:      nav.domComplete        - nav.startTime,
        loadComplete:     nav.loadEventEnd       - nav.startTime,
        transferSize:     nav.transferSize,
        encodedBodySize:  nav.encodedBodySize,
        decodedBodySize:  nav.decodedBodySize,
        navigationType:   nav.type,
        protocol:         nav.nextHopProtocol,
      });
    };

    if (document.readyState === 'complete') {
      send();
    } else {
      window.addEventListener('load', () => setTimeout(send, 0), { once: true });
    }
  }

  // ---------------------------------------------------------------------------
  // Memory (sampled every 30s where available)
  // ---------------------------------------------------------------------------
  private startMemorySampling(): void {
    const mem = (performance as any).memory;
    if (!mem) return;

    const sample = () => {
      this.config.onTrack('performance', {
        metric: 'memory',
        usedJSHeapSize:  mem.usedJSHeapSize,
        totalJSHeapSize: mem.totalJSHeapSize,
        jsHeapSizeLimit: mem.jsHeapSizeLimit,
        usedMB: Math.round(mem.usedJSHeapSize / 1048576),
      });
    };

    sample();
    this.memoryTimer = setInterval(sample, 30000);
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------
  private emit(vital: VitalEntry): void {
    this.config.onTrack('performance', {
      metric: vital.name,
      value:  vital.value,
      rating: vital.rating,
      navigationType: vital.navigationType,
    });
  }

  private observe(
    type: string,
    callback: (list: PerformanceObserverEntryList) => void,
    options?: Record<string, unknown>,
  ): void {
    try {
      const po = new PerformanceObserver(callback);
      po.observe({ type, buffered: true, ...options } as PerformanceObserverInit);
      this.observers.push(po);
    } catch {
      // Entry type not supported in this browser — skip silently
    }
  }
}
