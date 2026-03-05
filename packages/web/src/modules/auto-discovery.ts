// =============================================================================
// AETHER SDK — AUTO-DISCOVERY MODULE (Tier 2 Thin Client)
// Minimal click tracker. Ships raw click data to backend.
// No rage click detection, no dead click detection, no scroll tracking.
// =============================================================================

export interface AutoDiscoveryCallbacks {
  onTrack: (event: string, properties: Record<string, unknown>) => void;
}

export class AutoDiscoveryModule {
  private callbacks: AutoDiscoveryCallbacks;
  private listeners: Array<[EventTarget, string, EventListener]> = [];

  constructor(callbacks: AutoDiscoveryCallbacks) {
    this.callbacks = callbacks;
  }

  /** Start click tracking */
  start(): void {
    if (typeof document === 'undefined') return;
    this.trackClicks();
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
      const event = e as MouseEvent;
      const target = event.target as HTMLElement;
      if (!target) return;

      this.callbacks.onTrack('element_click', {
        selector: this.getSelector(target),
        text: (target.textContent || '').trim().slice(0, 100) || undefined,
        tagName: target.tagName.toLowerCase(),
        href: (target as HTMLAnchorElement).href || undefined,
        x: event.clientX,
        y: event.clientY,
        timestamp: Date.now(),
        pageUrl: window.location.pathname,
      });
    };

    document.addEventListener('click', handler, { passive: true, capture: true });
    this.listeners.push([document, 'click', handler]);
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
