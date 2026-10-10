// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AutoDiscoveryModule } from '../src/modules/auto-discovery';

type Emitted = { event: string; props: Record<string, unknown> };

function createModule(config?: { navigationCorrelation?: boolean }) {
  const tracked: Emitted[] = [];
  const observed: Emitted[] = [];
  const module = new AutoDiscoveryModule(
    {
      onTrack: (event, props) => tracked.push({ event, props }),
      onObserve: (event, props) => observed.push({ event, props }),
    },
    config,
  );
  return { module, tracked, observed };
}

function click(el: Element, init: MouseEventInit = {}): void {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, ...init }));
}

let modules: AutoDiscoveryModule[] = [];

beforeEach(() => {
  document.body.innerHTML = '';
  sessionStorage.clear();
  window.history.replaceState({}, '', '/');
  // Cancel jsdom default navigation on anchor clicks (module listener is
  // capture-phase, so it always observes the click first).
  document.body.addEventListener('click', (e) => e.preventDefault());
});

afterEach(() => {
  modules.forEach((m) => m.destroy());
  modules = [];
  vi.useRealTimers();
});

function start(config?: { navigationCorrelation?: boolean }) {
  const created = createModule(config);
  created.module.start();
  modules.push(created.module);
  return created;
}

describe('interactive-ancestor resolution', () => {
  it('resolves nested SVG clicks to the owning button', () => {
    document.body.innerHTML =
      '<button aria-label="Open settings"><svg viewBox="0 0 10 10"><path d="M0 0h10"/></svg></button>';
    const { tracked } = start();

    click(document.querySelector('path')!);

    expect(tracked).toHaveLength(1);
    const props = tracked[0].props;
    expect(tracked[0].event).toBe('element_click');
    expect(props.tagName).toBe('button');
    expect(props.elementId).toBe('Open settings');
    expect(props.elementIdSource).toBe('accessible-name');
  });

  it('resolves nested spans inside [role=button] elements', () => {
    document.body.innerHTML =
      '<div role="button" id="cta-div"><span>Get started</span></div>';
    const { tracked } = start();

    click(document.querySelector('span')!);

    expect(tracked[0].props.tagName).toBe('div');
    expect(tracked[0].props.role).toBe('button');
    expect(tracked[0].props.elementId).toBe('cta-div');
  });

  it('prefers data-aether-id over element id and accessible name', () => {
    document.body.innerHTML =
      '<button data-aether-id="pricing-cta" id="btn-1" aria-label="See pricing">Pricing</button>';
    const { tracked } = start();

    click(document.querySelector('button')!);

    expect(tracked[0].props.elementId).toBe('pricing-cta');
    expect(tracked[0].props.elementIdSource).toBe('data-aether-id');
  });

  it('falls back id → accessible name → selector in order', () => {
    document.body.innerHTML = `
      <button id="with-id">A</button>
      <button aria-label="With label"></button>
      <button class="btn primary"></button>
    `;
    const { tracked } = start();
    const [withId, withLabel, bare] = Array.from(document.querySelectorAll('button'));

    click(withId);
    click(withLabel);
    click(bare);

    expect(tracked[0].props.elementIdSource).toBe('element-id');
    expect(tracked[0].props.elementId).toBe('with-id');
    expect(tracked[1].props.elementIdSource).toBe('accessible-name');
    expect(tracked[1].props.elementId).toBe('With label');
    expect(tracked[2].props.elementIdSource).toBe('selector');
    expect(String(tracked[2].props.elementId)).toContain('button.btn.primary');
  });

  it('privacy-reduces accessible names (digit runs, truncation)', () => {
    document.body.innerHTML =
      `<button aria-label="Account 1234567890 ${'x'.repeat(200)}"></button>`;
    const { tracked } = start();

    click(document.querySelector('button')!);

    const elementId = String(tracked[0].props.elementId);
    expect(elementId).toContain('****');
    expect(elementId).not.toContain('1234567890');
    expect(elementId.length).toBeLessThanOrEqual(80);
  });
});

describe('duplicate listener prevention', () => {
  it('start() is idempotent and destroy() removes the listener', () => {
    document.body.innerHTML = '<button id="once">Go</button>';
    const { module, tracked } = start();
    module.start(); // second start must not stack a second listener

    click(document.getElementById('once')!);
    expect(tracked).toHaveLength(1);

    module.destroy();
    click(document.getElementById('once')!);
    expect(tracked).toHaveLength(1);
  });
});

describe('navigation correlation', () => {
  it('emits navigation_intent for internal links and correlates arrival', () => {
    document.body.innerHTML =
      '<a href="/pricing?plan=pro" data-aether-id="nav-pricing">Pricing</a>';
    const { module, observed } = start();

    click(document.querySelector('a')!);

    const intent = observed.find((e) => e.event === 'navigation_intent')!;
    expect(intent).toBeDefined();
    expect(intent.props.destinationCategory).toBe('internal');
    expect(intent.props.destinationPath).toBe('/pricing');
    expect(intent.props.elementId).toBe('nav-pricing');
    expect(intent.props.newTab).toBe(false);
    expect(intent.props.download).toBe(false);
    const navigationId = intent.props.navigationId as string;
    expect(navigationId).toBeTruthy();

    // Simulated SPA route completion (index.ts calls recordArrival on route).
    window.history.pushState({}, '', '/pricing?plan=pro');
    module.recordArrival();

    const arrival = observed.find((e) => e.event === 'navigation_arrival')!;
    expect(arrival).toBeDefined();
    expect(arrival.props.navigationId).toBe(navigationId);
    expect(arrival.props.path).toBe('/pricing');

    // Consumed exactly once — a second arrival emits nothing new.
    module.recordArrival();
    expect(observed.filter((e) => e.event === 'navigation_arrival')).toHaveLength(1);
  });

  it('flags external destinations and new tabs, and does not persist them for arrival', () => {
    document.body.innerHTML =
      '<a href="https://external.example.com/docs?x=1" target="_blank">Docs</a>';
    const { module, observed } = start();

    click(document.querySelector('a')!);

    const intent = observed.find((e) => e.event === 'navigation_intent')!;
    expect(intent.props.destinationCategory).toBe('external');
    expect(intent.props.destinationDomain).toBe('external.example.com');
    expect(intent.props.destinationUrl).toBeUndefined();
    expect(intent.props.newTab).toBe(true);
    expect(sessionStorage.getItem('aether_nav_intent')).toBeNull();

    module.recordArrival();
    expect(observed.some((e) => e.event === 'navigation_arrival')).toBe(false);
  });

  it('flags downloads and does not persist them', () => {
    document.body.innerHTML = '<a href="/report.pdf" download>Report</a>';
    const { observed } = start();

    click(document.querySelector('a')!);

    const intent = observed.find((e) => e.event === 'navigation_intent')!;
    expect(intent.props.download).toBe(true);
    expect(sessionStorage.getItem('aether_nav_intent')).toBeNull();
  });

  it('expires unconsumed intents silently after the TTL', () => {
    document.body.innerHTML = '<a href="/late">Late</a>';
    const { module, observed } = start();
    click(document.querySelector('a')!);
    expect(sessionStorage.getItem('aether_nav_intent')).not.toBeNull();

    const stored = JSON.parse(sessionStorage.getItem('aether_nav_intent')!);
    stored.ts = Date.now() - 6 * 60 * 1000;
    sessionStorage.setItem('aether_nav_intent', JSON.stringify(stored));

    module.recordArrival();
    expect(observed.some((e) => e.event === 'navigation_arrival')).toBe(false);
    // Expired entry is still consumed (no stale state left behind).
    expect(sessionStorage.getItem('aether_nav_intent')).toBeNull();
  });

  it('sanitizes hrefs and navigation URLs (aether_ref never transmitted)', () => {
    window.history.replaceState({}, '', '/landing?aether_ref=page-token');
    document.body.innerHTML = '<a href="/next?aether_ref=link-token&keep=1">Next</a>';
    const { tracked, observed } = start();

    click(document.querySelector('a')!);

    const clickProps = tracked[0].props;
    expect(String(clickProps.href)).toContain('keep=1');
    expect(String(clickProps.href)).not.toContain('aether_ref');
    const intent = observed.find((e) => e.event === 'navigation_intent')!;
    expect(String(intent.props.sourceUrl)).not.toContain('aether_ref');
    expect(String(intent.props.destinationUrl)).not.toContain('aether_ref');
  });

  it('can be disabled via config while click tracking stays on', () => {
    document.body.innerHTML = '<a href="/somewhere">Go</a>';
    const { module, tracked, observed } = start({ navigationCorrelation: false });

    click(document.querySelector('a')!);

    expect(tracked).toHaveLength(1);
    expect(observed).toHaveLength(0);
    expect(sessionStorage.getItem('aether_nav_intent')).toBeNull();
    module.recordArrival();
    expect(observed).toHaveLength(0);
  });
});
