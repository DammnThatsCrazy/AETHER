// =============================================================================
// Aether SDK — HEATMAP MODULE (Tier 2 Thin Client)
// Ships raw coordinate events to backend. No grid building, no aggregation.
// =============================================================================

import { throttle } from '../utils';

export interface HeatmapCallbacks {
  onTrack: (event: string, properties: Record<string, unknown>) => void;
}

export interface HeatmapConfig {
  clicks?: boolean;
  movement?: boolean;
  scroll?: boolean;
}

export class HeatmapModule {
  private callbacks: HeatmapCallbacks;
  private config: Required<HeatmapConfig>;
  private listeners: Array<[EventTarget, string, EventListener]> = [];

  constructor(callbacks: HeatmapCallbacks, config: HeatmapConfig = {}) {
    this.callbacks = callbacks;
    this.config = {
      clicks: config.clicks ?? true,
      movement: config.movement ?? true,
      scroll: config.scroll ?? true,
    };
  }

  /** Start all configured heatmap tracking */
  start(): void {
    if (typeof window === 'undefined') return;
    if (this.config.clicks) this.trackClicks();
    if (this.config.movement) this.trackMovement();
    if (this.config.scroll) this.trackScroll();
  }

  /** Stop all tracking and clean up */
  destroy(): void {
    this.listeners.forEach(([target, event, handler]) => {
      target.removeEventListener(event, handler);
    });
    this.listeners = [];
  }

  private trackClicks(): void {
    const handler = (e: Event) => {
      const me = e as MouseEvent;
      const target = me.target as HTMLElement;
      this.callbacks.onTrack('heatmap_click', {
        x: me.clientX, y: me.clientY, timestamp: Date.now(),
        selector: this.getSelector(target),
        pageUrl: window.location.pathname,
        viewportWidth: window.innerWidth,
        viewportHeight: window.innerHeight,
      });
    };
    document.addEventListener('click', handler, { passive: true, capture: true });
    this.listeners.push([document, 'click', handler]);
  }

  private trackMovement(): void {
    const handler = throttle((e: unknown) => {
      const me = e as MouseEvent;
      this.callbacks.onTrack('heatmap_move', {
        x: me.clientX, y: me.clientY, timestamp: Date.now(),
        pageUrl: window.location.pathname,
        viewportWidth: window.innerWidth,
        viewportHeight: window.innerHeight,
      });
    }, 100);
    document.addEventListener('mousemove', handler as EventListener, { passive: true });
    this.listeners.push([document, 'mousemove', handler as EventListener]);
  }

  private trackScroll(): void {
    const handler = throttle(() => {
      this.callbacks.onTrack('heatmap_scroll', {
        x: 0, y: window.scrollY, timestamp: Date.now(),
        pageUrl: window.location.pathname,
        viewportWidth: window.innerWidth,
        viewportHeight: window.innerHeight,
      });
    }, 100);
    window.addEventListener('scroll', handler as EventListener, { passive: true });
    this.listeners.push([window, 'scroll', handler as EventListener]);
  }

  private getSelector(el: HTMLElement, maxDepth = 3): string {
    const parts: string[] = [];
    let current: HTMLElement | null = el;
    let depth = 0;
    while (current && depth < maxDepth) {
      let selector = current.tagName.toLowerCase();
      if (current.id) { parts.unshift(`#${current.id}`); break; }
      if (current.className && typeof current.className === 'string') {
        const classes = current.className.trim().split(/\s+/).slice(0, 2).join('.');
        if (classes) selector += `.${classes}`;
      }
      parts.unshift(selector);
      current = current.parentElement;
      depth++;
    }
    return parts.join(' > ');
  }
}
