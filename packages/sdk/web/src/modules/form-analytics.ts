// =============================================================================
// Aether SDK — FORM ANALYTICS MODULE (Tier 2 Thin Client)
// Ships raw field-level events to backend. No abandonment detection,
// no hesitation analysis, no field-level analytics.
// =============================================================================

export interface FormAnalyticsCallbacks {
  onTrack: (event: string, properties: Record<string, unknown>) => void;
}

export interface FormAnalyticsConfig {
  autoDiscover?: boolean;
}

export class FormAnalyticsModule {
  private callbacks: FormAnalyticsCallbacks;
  private listeners: Array<[EventTarget, string, EventListener]> = [];
  private observers: MutationObserver[] = [];

  constructor(callbacks: FormAnalyticsCallbacks, config: FormAnalyticsConfig = {}) {
    this.callbacks = callbacks;
    if (typeof window !== 'undefined' && config.autoDiscover !== false) {
      this.startAutoDiscovery();
    }
  }

  /** Attach listeners to a specific form */
  trackForm(form: HTMLFormElement | string): void {
    const element = typeof form === 'string'
      ? document.querySelector<HTMLFormElement>(form)
      : form;
    if (!element || element.tagName !== 'FORM') return;

    const formId = element.id || element.getAttribute('name') || 'unknown';
    this.attachListeners(element, formId);
  }

  /** Clean up all listeners */
  destroy(): void {
    this.listeners.forEach(([target, event, handler]) => {
      target.removeEventListener(event, handler);
    });
    this.observers.forEach((o) => o.disconnect());
    this.listeners = [];
    this.observers = [];
  }

  private startAutoDiscovery(): void {
    document.querySelectorAll<HTMLFormElement>('form').forEach((form) => {
      this.trackForm(form);
    });

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of Array.from(mutation.addedNodes)) {
          if (node instanceof HTMLFormElement) this.trackForm(node);
          if (node instanceof HTMLElement) {
            node.querySelectorAll<HTMLFormElement>('form').forEach((f) => this.trackForm(f));
          }
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    this.observers.push(observer);
  }

  /**
   * Build the metadata-only payload for a field interaction.
   *
   * PRIVACY INVARIANT: typed form values, selections, and defaults are NEVER
   * read — only structural metadata (name/type/action) leaves the page. The
   * final scrub is defense-in-depth so no future edit can accidentally ship
   * a value-shaped key.
   */
  private fieldPayload(
    input: HTMLInputElement,
    action: 'focus' | 'blur' | 'change',
    formId: string,
  ): Record<string, unknown> {
    const payload: Record<string, unknown> = {
      fieldName: input.name || input.id || 'unknown',
      fieldType: input.type || input.tagName.toLowerCase(),
      action,
      timestamp: Date.now(),
      formId,
    };
    for (const key of ['value', 'checked', 'defaultValue', 'files', 'selectionStart', 'selectionEnd']) {
      delete payload[key];
    }
    return payload;
  }

  private attachListeners(form: HTMLFormElement, formId: string): void {
    const focusHandler = (e: Event) => {
      const target = e.target as HTMLElement;
      if (!this.isField(target)) return;
      this.callbacks.onTrack(
        'form_field',
        this.fieldPayload(target as HTMLInputElement, 'focus', formId),
      );
    };

    const blurHandler = (e: Event) => {
      const target = e.target as HTMLElement;
      if (!this.isField(target)) return;
      this.callbacks.onTrack(
        'form_field',
        this.fieldPayload(target as HTMLInputElement, 'blur', formId),
      );
    };

    const inputHandler = (e: Event) => {
      const target = e.target as HTMLElement;
      if (!this.isField(target)) return;
      this.callbacks.onTrack(
        'form_field',
        this.fieldPayload(target as HTMLInputElement, 'change', formId),
      );
    };

    form.addEventListener('focusin', focusHandler, { passive: true });
    form.addEventListener('focusout', blurHandler, { passive: true });
    form.addEventListener('input', inputHandler, { passive: true });

    this.listeners.push(
      [form, 'focusin', focusHandler],
      [form, 'focusout', blurHandler],
      [form, 'input', inputHandler],
    );
  }

  private isField(el: HTMLElement): boolean {
    return ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
  }
}
