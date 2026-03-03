// =============================================================================
// AETHER SDK — PERFORMANCE MODULE
// Core Web Vitals (LCP, FID, CLS), resource timing, JS error tracking
// =============================================================================

export interface PerformanceCallbacks {
  onPerformance: (metrics: Record<string, unknown>) => void;
  onError: (error: Record<string, unknown>) => void;
}

export class PerformanceModule {
  private callbacks: PerformanceCallbacks;
  private observers: PerformanceObserver[] = [];
  private cls = 0;

  constructor(callbacks: PerformanceCallbacks) {
    this.callbacks = callbacks;
  }

  /** Start tracking performance metrics */
  start(config: { webVitals?: boolean; errors?: boolean; resources?: boolean } = {}): void {
    if (typeof window === 'undefined') return;
    if (config.webVitals !== false) this.trackWebVitals();
    if (config.errors !== false) this.trackErrors();
    if (config.resources === true) this.trackResourceTiming();
  }

  destroy(): void {
    this.observers.forEach((o) => o.disconnect());
    this.observers = [];
  }

  // ===========================================================================
  // CORE WEB VITALS
  // ===========================================================================

  private trackWebVitals(): void {
    // LCP (Largest Contentful Paint)
    try {
      const lcpObserver = new PerformanceObserver((list) => {
        const entries = list.getEntries();
        const last = entries[entries.length - 1];
        if (last) {
          this.callbacks.onPerformance({
            metric: 'lcp',
            value: Math.round(last.startTime),
            rating: last.startTime <= 2500 ? 'good' : last.startTime <= 4000 ? 'needs-improvement' : 'poor',
          });
        }
      });
      lcpObserver.observe({ type: 'largest-contentful-paint', buffered: true });
      this.observers.push(lcpObserver);
    } catch { /* PerformanceObserver not supported */ }

    // FID (First Input Delay)
    try {
      const fidObserver = new PerformanceObserver((list) => {
        const entry = list.getEntries()[0] as PerformanceEventTiming;
        if (entry) {
          const fid = entry.processingStart - entry.startTime;
          this.callbacks.onPerformance({
            metric: 'fid',
            value: Math.round(fid),
            rating: fid <= 100 ? 'good' : fid <= 300 ? 'needs-improvement' : 'poor',
          });
        }
      });
      fidObserver.observe({ type: 'first-input', buffered: true });
      this.observers.push(fidObserver);
    } catch { /* Not supported */ }

    // CLS (Cumulative Layout Shift)
    try {
      const clsObserver = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (!(entry as LayoutShiftEntry).hadRecentInput) {
            this.cls += (entry as LayoutShiftEntry).value;
          }
        }
      });
      clsObserver.observe({ type: 'layout-shift', buffered: true });
      this.observers.push(clsObserver);

      // Report CLS on page hide
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') {
          this.callbacks.onPerformance({
            metric: 'cls',
            value: Math.round(this.cls * 1000) / 1000,
            rating: this.cls <= 0.1 ? 'good' : this.cls <= 0.25 ? 'needs-improvement' : 'poor',
          });
        }
      });
    } catch { /* Not supported */ }

    // Navigation timing (TTFB, FCP, DOM Ready, Load)
    if (typeof performance !== 'undefined') {
      window.addEventListener('load', () => {
        setTimeout(() => {
          const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming;
          if (nav) {
            this.callbacks.onPerformance({
              metric: 'navigation',
              ttfb: Math.round(nav.responseStart - nav.requestStart),
              domReady: Math.round(nav.domContentLoadedEventEnd - nav.fetchStart),
              loadComplete: Math.round(nav.loadEventEnd - nav.fetchStart),
              transferSize: nav.transferSize,
              domInteractive: Math.round(nav.domInteractive - nav.fetchStart),
            });
          }

          // FCP
          const fcp = performance.getEntriesByName('first-contentful-paint')[0];
          if (fcp) {
            this.callbacks.onPerformance({
              metric: 'fcp',
              value: Math.round(fcp.startTime),
              rating: fcp.startTime <= 1800 ? 'good' : fcp.startTime <= 3000 ? 'needs-improvement' : 'poor',
            });
          }
        }, 0);
      });
    }
  }

  // ===========================================================================
  // ERROR TRACKING
  // ===========================================================================

  private trackErrors(): void {
    // Uncaught exceptions
    window.addEventListener('error', (e: ErrorEvent) => {
      this.callbacks.onError({
        type: 'uncaught_exception',
        message: e.message,
        filename: e.filename,
        lineno: e.lineno,
        colno: e.colno,
        stack: e.error?.stack,
      });
    });

    // Unhandled promise rejections
    window.addEventListener('unhandledrejection', (e: PromiseRejectionEvent) => {
      this.callbacks.onError({
        type: 'unhandled_rejection',
        message: String(e.reason),
        stack: e.reason?.stack,
      });
    });
  }

  // ===========================================================================
  // RESOURCE TIMING
  // ===========================================================================

  private trackResourceTiming(): void {
    try {
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          const resource = entry as PerformanceResourceTiming;
          // Only track slow resources (>1s)
          if (resource.duration > 1000) {
            this.callbacks.onPerformance({
              metric: 'slow_resource',
              name: resource.name.slice(0, 200),
              initiatorType: resource.initiatorType,
              duration: Math.round(resource.duration),
              transferSize: resource.transferSize,
            });
          }
        }
      });
      observer.observe({ type: 'resource', buffered: false });
      this.observers.push(observer);
    } catch { /* Not supported */ }
  }
}

// Type augmentation for Layout Shift entries
interface LayoutShiftEntry extends PerformanceEntry {
  value: number;
  hadRecentInput: boolean;
}

interface PerformanceEventTiming extends PerformanceEntry {
  processingStart: number;
}
