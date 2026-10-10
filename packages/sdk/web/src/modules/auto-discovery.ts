// =============================================================================
// Aether SDK — AUTO-DISCOVERY MODULE (Tier 2 Thin Client)
// Minimal click tracker. Ships raw click data to backend.
// - Clicks resolve to the actual interactive control (nested SVG/span clicks
//   attach to the button/link that owns them).
// - Permitted navigation clicks emit canonical `navigation_intent` events,
//   correlated with `navigation_arrival` on the next page load / SPA route.
//   This proves internal button→page navigation only; it never claims
//   off-site acquisition proof (source classification is backend-owned).
// No rage click detection, no dead click detection, no scroll tracking.
// =============================================================================

import { generateId, sanitizeUrl } from '../utils';

export interface AutoDiscoveryCallbacks {
  onTrack: (event: string, properties: Record<string, unknown>) => void;
  /** Canonical registry event emitter (navigation_intent / navigation_arrival). */
  onObserve?: (type: string, properties: Record<string, unknown>) => void;
}

export interface AutoDiscoveryConfig {
  /** Emit navigation_intent/navigation_arrival correlation events (default on). */
  navigationCorrelation?: boolean;
}

/** Selector matching the interactive controls a click should resolve to. */
const INTERACTIVE_SELECTOR =
  'a, button, input[type="button"], input[type="submit"], [role="button"], [data-aether-track]';

const NAV_INTENT_STORAGE_KEY = 'aether_nav_intent';
/** Pending navigation intents expire silently after 5 minutes. */
const NAV_INTENT_TTL_MS = 5 * 60 * 1000;
const MAX_ACCESSIBLE_NAME_LENGTH = 80;

interface StoredNavigationIntent {
  navigationId: string;
  ts: number;
}

export class AutoDiscoveryModule {
  private callbacks: AutoDiscoveryCallbacks;
  private config: AutoDiscoveryConfig;
  private listeners: Array<[EventTarget, string, EventListener]> = [];
  private started = false;

  constructor(callbacks: AutoDiscoveryCallbacks, config: AutoDiscoveryConfig = {}) {
    this.callbacks = callbacks;
    this.config = config;
  }

  /** Start click tracking (idempotent — never stacks duplicate listeners) */
  start(): void {
    if (typeof document === 'undefined' || this.started) return;
    this.started = true;
    this.trackClicks();
  }

  /** Stop all tracking and clean up */
  destroy(): void {
    this.listeners.forEach(([target, event, handler]) => {
      target.removeEventListener(event, handler, { capture: true } as EventListenerOptions);
    });
    this.listeners = [];
    this.started = false;
  }

  /**
   * Consume a pending navigation intent and emit `navigation_arrival`.
   * Called on page load and after SPA route completion. Consumed exactly
   * once; expired intents are dropped silently.
   */
  recordArrival(): void {
    if (typeof window === 'undefined') return;
    if (this.config.navigationCorrelation === false) return;
    const intent = this.consumeStoredIntent();
    if (!intent) return;
    this.callbacks.onObserve?.('navigation_arrival', {
      navigationId: intent.navigationId,
      url: sanitizeUrl(window.location.href),
      path: window.location.pathname,
      latencyMs: Math.max(0, Date.now() - intent.ts),
      timestamp: Date.now(),
    });
  }

  private trackClicks(): void {
    const handler = (e: Event) => {
      const event = e as MouseEvent;
      const rawTarget = event.target as Element | null;
      if (!rawTarget) return;

      // Interactive-ancestor resolution: a click on a nested <svg>/<span>
      // resolves to the button/link that owns it.
      const control = (typeof rawTarget.closest === 'function'
        ? rawTarget.closest(INTERACTIVE_SELECTOR)
        : null) as HTMLElement | null;
      const element = control ?? (rawTarget as HTMLElement);
      if (!element.tagName) return;

      const identity = this.resolveIdentity(element);
      const anchor = element.closest?.('a') as HTMLAnchorElement | null;
      const href = anchor?.getAttribute('href') ? anchor.href : undefined;

      this.callbacks.onTrack('element_click', {
        elementId: identity.elementId,
        elementIdSource: identity.source,
        selector: this.getSelector(element),
        text: this.accessibleName(element),
        tagName: element.tagName.toLowerCase(),
        role: element.getAttribute?.('role') ?? undefined,
        href: href ? sanitizeUrl(href) : undefined,
        x: event.clientX,
        y: event.clientY,
        timestamp: Date.now(),
        pageUrl: window.location.pathname,
      });

      if (anchor && href) {
        this.emitNavigationIntent(event, anchor, element, identity.elementId);
      }
    };

    document.addEventListener('click', handler, { passive: true, capture: true });
    this.listeners.push([document, 'click', handler]);
  }

  /**
   * Element identity preference: data-aether-id → stable element id →
   * accessible name (aria-label / trimmed text, truncated, privacy-reduced)
   * → structural selector fallback.
   */
  private resolveIdentity(el: HTMLElement): { elementId: string; source: string } {
    const declared = el.getAttribute?.('data-aether-id');
    if (declared && declared.trim()) {
      return { elementId: declared.trim(), source: 'data-aether-id' };
    }
    if (el.id) return { elementId: el.id, source: 'element-id' };
    const name = this.accessibleName(el);
    if (name) return { elementId: name, source: 'accessible-name' };
    return { elementId: this.getSelector(el), source: 'selector' };
  }

  /** aria-label or trimmed text content, truncated and digit-reduced. */
  private accessibleName(el: HTMLElement): string | undefined {
    const label = el.getAttribute?.('aria-label');
    const raw = (label && label.trim()) || (el.textContent || '').trim();
    if (!raw) return undefined;
    // Privacy reduction: collapse whitespace and redact long digit runs
    // (account numbers, phone numbers) before the name leaves the page.
    return raw
      .replace(/\s+/g, ' ')
      .replace(/\d{4,}/g, '****')
      .slice(0, MAX_ACCESSIBLE_NAME_LENGTH);
  }

  private emitNavigationIntent(
    event: MouseEvent,
    anchor: HTMLAnchorElement,
    element: HTMLElement,
    elementId: string,
  ): void {
    if (this.config.navigationCorrelation === false) return;
    if (!this.callbacks.onObserve) return;

    let destination: URL;
    try {
      destination = new URL(anchor.href, window.location.href);
    } catch {
      return;
    }
    if (!/^https?:$/.test(destination.protocol)) return;

    const isExternal = destination.host !== window.location.host;
    const newTab =
      anchor.target === '_blank' || event.metaKey || event.ctrlKey || event.button === 1;
    const download = anchor.hasAttribute('download');
    const navigationId = generateId();

    this.callbacks.onObserve('navigation_intent', {
      navigationId,
      sourceUrl: sanitizeUrl(window.location.href),
      sourcePath: window.location.pathname,
      destinationCategory: isExternal ? 'external' : 'internal',
      destinationPath: destination.pathname,
      // Domain only for external destinations; full sanitized URL is internal-only.
      destinationDomain: isExternal ? destination.hostname : undefined,
      destinationUrl: isExternal ? undefined : sanitizeUrl(destination.toString()),
      elementId,
      elementRole: element.getAttribute?.('role') ?? element.tagName.toLowerCase(),
      newTab,
      download,
      timestamp: Date.now(),
    });

    // Persist for same-tab internal arrival correlation only. External
    // destinations, downloads, and new tabs cannot arrive back in this tab
    // and MUST NOT be claimed as proven navigation.
    if (!isExternal && !newTab && !download) {
      try {
        sessionStorage.setItem(
          NAV_INTENT_STORAGE_KEY,
          JSON.stringify({ navigationId, ts: Date.now() } satisfies StoredNavigationIntent),
        );
      } catch { /* sessionStorage unavailable */ }
    }
  }

  /** Read + delete the stored intent; expired entries are dropped silently. */
  private consumeStoredIntent(): StoredNavigationIntent | null {
    try {
      const raw = sessionStorage.getItem(NAV_INTENT_STORAGE_KEY);
      if (!raw) return null;
      sessionStorage.removeItem(NAV_INTENT_STORAGE_KEY);
      const parsed = JSON.parse(raw) as StoredNavigationIntent;
      if (!parsed?.navigationId || typeof parsed.ts !== 'number') return null;
      if (Date.now() - parsed.ts > NAV_INTENT_TTL_MS) return null;
      return parsed;
    } catch {
      return null;
    }
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
