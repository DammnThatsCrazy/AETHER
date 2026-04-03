// =============================================================================
// AETHER SDK — AUTO-DISCOVERY MODULE
// Automatic tracking of clicks, forms, scroll depth, rage clicks, dead clicks
// =============================================================================

import { throttle, isSensitiveField, maskSensitiveData } from './SDKUtilityFunctions';

export interface AutoDiscoveryCallbacks {
  onTrack: (event: string, properties: Record<string, unknown>) => void;
}

interface ClickRecord {
  x: number;
  y: number;
  time: number;
}

export class AutoDiscoveryModule {
  private callbacks: AutoDiscoveryCallbacks;
  private clickHistory: ClickRecord[] = [];
  private maxScrollDepth = 0;
  private scrollMilestones = new Set<number>();
  private observers: MutationObserver[] = [];
  private listeners: Array<[EventTarget, string, EventListener]> = [];
  private maskSensitive: boolean;
  private piiPatterns: RegExp[];

  constructor(
    callbacks: AutoDiscoveryCallbacks,
    options: { maskSensitive?: boolean; piiPatterns?: RegExp[] } = {}
  ) {
    this.callbacks = callbacks;
    this.maskSensitive = options.maskSensitive ?? true;
    this.piiPatterns = options.piiPatterns ?? [];
  }

  /** Start all auto-discovery listeners */
  start(config: {
    clicks?: boolean;
    forms?: boolean;
    scrollDepth?: boolean;
    rageClicks?: boolean;
    deadClicks?: boolean;
  }): void {
    if (config.clicks !== false) this.trackClicks();
    if (config.forms !== false) this.trackForms();
    if (config.scrollDepth !== false) this.trackScrollDepth();
    if (config.rageClicks !== false) this.trackRageClicks();
    if (config.deadClicks !== false) this.trackDeadClicks();
  }

  /** Stop all auto-discovery and clean up */
  destroy(): void {
    this.listeners.forEach(([target, event, handler]) => {
      target.removeEventListener(event, handler);
    });
    this.observers.forEach((o) => o.disconnect());
    this.listeners = [];
    this.observers = [];
  }

  // ===========================================================================
  // CLICK TRACKING
  // ===========================================================================

  private trackClicks(): void {
    const handler = (e: Event) => {
      const event = e as MouseEvent;
      const target = event.target as HTMLElement;
      if (!target) return;

      const props = this.getElementProperties(target);
      this.callbacks.onTrack('click', {
        ...props,
        x: event.clientX,
        y: event.clientY,
        pageX: event.pageX,
        pageY: event.pageY,
      });

      // Record for rage/dead click detection
      this.clickHistory.push({
        x: event.clientX,
        y: event.clientY,
        time: Date.now(),
      });

      // Keep only last 20 clicks
      if (this.clickHistory.length > 20) {
        this.clickHistory.shift();
      }
    };

    document.addEventListener('click', handler, { passive: true, capture: true });
    this.listeners.push([document, 'click', handler]);
  }

  // ===========================================================================
  // FORM TRACKING
  // ===========================================================================

  private trackForms(): void {
    // Track form focus (form start)
    const focusHandler = (e: Event) => {
      const target = e.target as HTMLElement;
      if (!this.isFormElement(target)) return;

      const form = (target as HTMLInputElement).form;
      this.callbacks.onTrack('form_focus', {
        formId: form?.id || null,
        formAction: form?.action || null,
        fieldName: this.maskSensitive && isSensitiveField(target as HTMLInputElement)
          ? '[sensitive]'
          : (target as HTMLInputElement).name || (target as HTMLInputElement).id,
        fieldType: (target as HTMLInputElement).type,
      });
    };

    // Track form submission
    const submitHandler = (e: Event) => {
      const form = e.target as HTMLFormElement;
      if (!form || form.tagName !== 'FORM') return;

      const fields = Array.from(form.elements) as HTMLInputElement[];
      const filledFields = fields.filter(
        (f) => f.value && f.type !== 'hidden' && f.type !== 'submit'
      ).length;
      const totalFields = fields.filter(
        (f) => f.type !== 'hidden' && f.type !== 'submit'
      ).length;

      this.callbacks.onTrack('form_submit', {
        formId: form.id || null,
        formAction: form.action || null,
        formMethod: form.method,
        filledFields,
        totalFields,
        completionRate: totalFields > 0 ? filledFields / totalFields : 0,
      });
    };

    // Track form abandonment (blur from form without submit)
    const blurHandler = (e: Event) => {
      const target = e.target as HTMLElement;
      if (!this.isFormElement(target)) return;

      const input = target as HTMLInputElement;
      if (this.maskSensitive && isSensitiveField(input)) return;

      this.callbacks.onTrack('form_field_blur', {
        formId: input.form?.id || null,
        fieldName: input.name || input.id,
        fieldType: input.type,
        hasValue: !!input.value,
      });
    };

    document.addEventListener('focusin', focusHandler, { passive: true });
    document.addEventListener('submit', submitHandler, { passive: true });
    document.addEventListener('focusout', blurHandler, { passive: true });

    this.listeners.push(
      [document, 'focusin', focusHandler],
      [document, 'submit', submitHandler],
      [document, 'focusout', blurHandler]
    );
  }

  // ===========================================================================
  // SCROLL DEPTH TRACKING
  // ===========================================================================

  private trackScrollDepth(): void {
    const milestones = [25, 50, 75, 90, 100];

    const handler = throttle(() => {
      const scrollTop = window.scrollY || document.documentElement.scrollTop;
      const docHeight = Math.max(
        document.body.scrollHeight,
        document.documentElement.scrollHeight
      );
      const viewportHeight = window.innerHeight;
      const scrollable = docHeight - viewportHeight;

      if (scrollable <= 0) return;

      const depth = Math.min(Math.round((scrollTop / scrollable) * 100), 100);

      if (depth > this.maxScrollDepth) {
        this.maxScrollDepth = depth;
      }

      // Fire milestone events
      for (const milestone of milestones) {
        if (depth >= milestone && !this.scrollMilestones.has(milestone)) {
          this.scrollMilestones.add(milestone);
          this.callbacks.onTrack('scroll_depth', {
            depth: milestone,
            maxDepth: this.maxScrollDepth,
            url: window.location.href,
          });
        }
      }
    }, 250);

    window.addEventListener('scroll', handler, { passive: true });
    this.listeners.push([window, 'scroll', handler as EventListener]);
  }

  // ===========================================================================
  // RAGE CLICK DETECTION
  // ===========================================================================

  private trackRageClicks(): void {
    const RAGE_THRESHOLD = 3; // clicks
    const RAGE_WINDOW = 1000; // ms
    const RAGE_RADIUS = 100; // pixels

    const handler = (e: Event) => {
      const event = e as MouseEvent;
      const currentTime = Date.now();
      const recentClicks = this.clickHistory.filter(
        (c) =>
          currentTime - c.time < RAGE_WINDOW &&
          Math.abs(c.x - event.clientX) < RAGE_RADIUS &&
          Math.abs(c.y - event.clientY) < RAGE_RADIUS
      );

      if (recentClicks.length >= RAGE_THRESHOLD) {
        const target = event.target as HTMLElement;
        this.callbacks.onTrack('rage_click', {
          clickCount: recentClicks.length,
          ...this.getElementProperties(target),
          x: event.clientX,
          y: event.clientY,
        });
      }
    };

    document.addEventListener('click', handler, { passive: true });
    this.listeners.push([document, 'click', handler]);
  }

  // ===========================================================================
  // DEAD CLICK DETECTION
  // ===========================================================================

  private trackDeadClicks(): void {
    const DEAD_CLICK_TIMEOUT = 1000; // ms — no DOM change within this window

    const handler = (e: Event) => {
      const event = e as MouseEvent;
      const target = event.target as HTMLElement;
      if (!target) return;

      // Only track clicks on seemingly interactive elements
      const isInteractive =
        target.tagName === 'A' ||
        target.tagName === 'BUTTON' ||
        target.closest('a, button, [role="button"], [onclick]');

      if (!isInteractive) return;

      // Watch for DOM mutations after the click
      let domChanged = false;
      const observer = new MutationObserver(() => {
        domChanged = true;
      });
      observer.observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true,
      });

      setTimeout(() => {
        observer.disconnect();
        if (!domChanged) {
          this.callbacks.onTrack('dead_click', {
            ...this.getElementProperties(target),
            x: event.clientX,
            y: event.clientY,
          });
        }
      }, DEAD_CLICK_TIMEOUT);
    };

    document.addEventListener('click', handler, { passive: true });
    this.listeners.push([document, 'click', handler]);
  }

  // ===========================================================================
  // HELPERS
  // ===========================================================================

  private getElementProperties(el: HTMLElement): Record<string, unknown> {
    const rect = el.getBoundingClientRect();
    return {
      tagName: el.tagName.toLowerCase(),
      id: el.id || undefined,
      className: el.className
        ? (typeof el.className === 'string' ? el.className.slice(0, 200) : undefined)
        : undefined,
      text: (el.textContent || '').trim().slice(0, 100) || undefined,
      href: (el as HTMLAnchorElement).href || undefined,
      type: (el as HTMLInputElement).type || undefined,
      name: (el as HTMLInputElement).name || undefined,
      role: el.getAttribute('role') || undefined,
      ariaLabel: el.getAttribute('aria-label') || undefined,
      dataTestId: el.getAttribute('data-testid') || undefined,
      boundingRect: {
        top: Math.round(rect.top),
        left: Math.round(rect.left),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
      selector: this.getSelector(el),
    };
  }

  private getSelector(el: HTMLElement, maxDepth = 3): string {
    const parts: string[] = [];
    let current: HTMLElement | null = el;
    let depth = 0;

    while (current && depth < maxDepth) {
      let selector = current.tagName.toLowerCase();
      if (current.id) {
        selector = `#${current.id}`;
        parts.unshift(selector);
        break;
      }
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

  private isFormElement(el: HTMLElement): boolean {
    return ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
  }
}
