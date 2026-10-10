/**
 * Runtime for pages built from the design handoff (`design/designs/*.dc.html`).
 *
 * The handoff writes styles as inline CSS strings, hover states as
 * `style-hover`, and links as design file names (`Docs.dc.html?page=…`). The
 * pages keep those values verbatim so they stay pixel-faithful to the
 * designs; these helpers turn them into React styles, CSS classes and real
 * site URLs.
 */
import { useCallback, useEffect, useState, type CSSProperties } from 'react';
import { useSite } from '@site/site/site-context';
import type { SiteId } from '@site/site/site';
import { pilotOnly } from '@site/site/access';
import './base.css';

/* Styles ------------------------------------------------------------------ */

const styleCache = new Map<string, CSSProperties>();

function camel(prop: string): string {
  if (prop.startsWith('--')) return prop;
  const p = prop.startsWith('-ms-') ? prop.slice(1) : prop;
  return p.replace(/-([a-z])/g, (_, c: string) => c.toUpperCase());
}

/** `"font-size: 13px; color: #6b6a65"` → `{ fontSize: '13px', color: '#6b6a65' }`. */
export function css(input: string | null | undefined): CSSProperties {
  if (!input) return {};
  let text = input;
  const hit = styleCache.get(input);
  if (hit) return hit;
  const out: Record<string, string> = {};
  // Design asset paths inside url() resolve like <img src>.
  text = text.replace(/url\((['"]?)(\.\.\/assets\/[^'")]+)\1\)/g, (_m, q: string, p: string) => `url(${q}${asset(p)}${q})`);
  // Split on semicolons outside parentheses (url(), rgba() and data URIs).
  let depth = 0;
  let start = 0;
  const decls: string[] = [];
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (ch === '(') depth += 1;
    else if (ch === ')') depth = Math.max(0, depth - 1);
    else if (ch === ';' && depth === 0) {
      decls.push(text.slice(start, i));
      start = i + 1;
    }
  }
  decls.push(text.slice(start));
  for (const decl of decls) {
    const colon = decl.indexOf(':');
    if (colon < 0) continue;
    const prop = decl.slice(0, colon).trim();
    const value = decl.slice(colon + 1).trim();
    if (prop && value) out[camel(prop)] = value;
  }
  styleCache.set(input, out as CSSProperties);
  return out as CSSProperties;
}

/* Dynamic hover / focus classes -------------------------------------------- */

/**
 * Static `style-hover` values are compiled into the page CSS. Values computed
 * at render time (e.g. a selected tab) register here instead: the browser
 * gets the rule in a <style> element, and prerendering reads
 * `dynamicHoverCss()` after rendering a page and writes it into the HTML.
 */
const dynamicRules = new Map<string, string>();
let styleEl: HTMLStyleElement | null = null;

function hash(text: string): string {
  let h = 5381;
  for (let i = 0; i < text.length; i += 1) h = ((h << 5) + h + text.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}

function important(decls: string): string {
  return decls
    .split(';')
    .map((d) => d.trim())
    .filter(Boolean)
    .map((d) => `${d} !important`)
    .join('; ');
}

export function hoverClass(decls: string | null | undefined, kind: 'hover' | 'focus' = 'hover'): string {
  if (!decls) return '';
  const name = `${kind === 'hover' ? 'hd' : 'fd'}-${hash(decls)}`;
  if (!dynamicRules.has(name)) {
    const pseudo = kind === 'hover' ? ':hover' : ':focus-visible';
    const rule = `.${name}${pseudo} { ${important(decls)}; }`;
    dynamicRules.set(name, rule);
    if (typeof document !== 'undefined') {
      if (!styleEl) {
        styleEl = document.getElementById('dc-dynamic') as HTMLStyleElement | null;
        if (!styleEl) {
          styleEl = document.createElement('style');
          styleEl.id = 'dc-dynamic';
          document.head.appendChild(styleEl);
        }
      }
      if (!styleEl.textContent?.includes(`.${name}${pseudo}`)) styleEl.appendChild(document.createTextNode(rule));
    }
  }
  return name;
}

/** Rules registered while rendering; prerendering inlines them in <head>. */
export function dynamicHoverCss(): string {
  return [...dynamicRules.values()].join('\n');
}

/* State ------------------------------------------------------------------- */

type Patch<S> = Partial<S> | ((s: S) => Partial<S>);

/** Class-component `setState` semantics (shallow merge, updater functions). */
export function useDesignState<S extends object>(initial: S | (() => S)): [S, (patch: Patch<S>) => void] {
  const [state, set] = useState<S>(initial);
  const setState = useCallback((patch: Patch<S>) => {
    set((s) => ({ ...s, ...(typeof patch === 'function' ? patch(s) : patch) }));
  }, []);
  return [state, setState];
}

/* Assets ------------------------------------------------------------------- */

const OG = import.meta.glob('../assets/og/*.png', { eager: true, query: '?url', import: 'default' }) as Record<string, string>;

/**
 * Design asset paths → served URLs. Official marks and the reviewed provider
 * logos come from packages/ui/brand (the Vite public directory); preview images
 * are bundled from src/assets/og.
 */
export function asset(path: string | null | undefined): string {
  if (!path) return '';
  const m = /assets\/(.*)$/.exec(path);
  if (!m) return path;
  const rel = m[1] ?? '';
  if (rel.startsWith('brand/')) return `/providers/${rel.slice('brand/'.length)}`;
  if (rel.startsWith('og/')) return OG[`../assets/${rel}`] ?? `/${rel}`;
  return `/${rel}`;
}

/* Links -------------------------------------------------------------------- */

type Target = { site: SiteId | 'current'; path: string };

const FEATURE_PAGES = new Set(['graph', 'profiles', 'journeys', 'communications', 'value', 'risk']);
const TRUST_DETAILS = new Set(['privacy', 'governance', 'deployment']);

/** Resolve a design href (`Docs.dc.html?page=x#y`) to a site and path. */
export function designTarget(href: string, pilot: boolean): Target | null {
  const m = /^([^?#]*\.dc\.html)(\?[^#]*)?(#.*)?$/.exec(href);
  if (!m) return null;
  const file = decodeURIComponent(m[1] ?? '').replace(/^.*\//, '');
  const q = new URLSearchParams((m[2] ?? '').slice(1));
  const hash = m[3] ?? '';
  const aether = (path: string): Target => ({ site: 'aether', path: path + hash });
  const olympus = (path: string): Target => ({ site: 'olympus', path: path + hash });
  switch (file) {
    case 'Aether Home.dc.html':
      return aether('/');
    case 'Aether Platform.dc.html':
      return aether('/platform');
    case 'Aether Feature Page.dc.html': {
      const f = q.get('f') ?? '';
      return aether(FEATURE_PAGES.has(f) ? `/platform/${f}` : '/platform');
    }
    case 'Aether How It Works.dc.html':
      return aether('/how-it-works');
    case 'Aether Applications.dc.html':
      return aether('/applications');
    case 'Aether Customer Intelligence.dc.html':
      return aether('/applications/customer-intelligence');
    case 'Aether Lenses.dc.html':
      return aether('/platform/lenses');
    case 'Aether Agents.dc.html':
      return aether('/platform/agents');
    case 'Aether Connect.dc.html':
      return aether('/connect');
    case 'Aether Detail Page.dc.html': {
      const p = q.get('p') ?? 'connectors';
      return aether(TRUST_DETAILS.has(p) ? `/trust/${p}` : `/connect/${p}`);
    }
    case 'Aether Trust.dc.html':
      return aether('/trust');
    case 'Aether Security.dc.html':
      return aether('/security');
    case 'Aether Procurement.dc.html':
      return aether('/procurement');
    case 'Aether Pricing.dc.html':
      return aether('/pricing');
    case 'Aether Portal.dc.html': {
      const plan = q.get('plan');
      if (pilot) return aether(`/contact?type=pilot${plan ? `&plan=${plan}` : ''}`);
      if (q.get('mode') === 'signin') return aether('/app/signin');
      return aether(`/app/signup${plan ? `?plan=${plan}` : ''}`);
    }
    case 'Docs.dc.html': {
      const page = q.get('page');
      return aether(page ? `/docs/${page}` : '/docs');
    }
    case 'Glossary.dc.html':
      return aether('/docs/glossary');
    case 'Symbol Key.dc.html':
      return aether('/docs/symbol-key');
    case 'Status.dc.html':
      return aether('/status');
    case 'Contact.dc.html': {
      const brand = q.get('brand');
      q.delete('brand');
      const rest = q.toString();
      const path = `/contact${rest ? `?${rest}` : ''}${hash}`;
      return { site: brand === 'aether' || brand === 'olympus' ? brand : 'current', path };
    }
    case 'Legal.dc.html':
      return { site: 'current', path: `/legal/${q.get('doc') ?? 'privacy'}${hash}` };
    case 'Not Found.dc.html':
      return { site: 'current', path: '/' };
    case 'Olympus Home.dc.html':
      return olympus('/');
    case 'Olympus Technology.dc.html':
      return olympus('/technology');
    case 'Olympus Applications.dc.html':
      return olympus('/applications');
    case 'Olympus Company.dc.html':
      return olympus('/company');
    case 'Olympus Principles.dc.html':
      return olympus('/principles');
    case 'Olympus Research.dc.html':
      return olympus('/research');
    case 'Olympus Stories.dc.html':
      return olympus('/stories');
    default:
      return aether('/');
  }
}

/** `link(designHref)` → the URL this build should use (cross-site links are absolute). */
export function useLink(): (href: string | null | undefined) => string {
  const { site, href } = useSite();
  const pilot = pilotOnly();
  return useCallback(
    (raw: string | null | undefined) => {
      if (!raw) return '#';
      if (/^(https?:|mailto:|tel:|#)/.test(raw)) return raw;
      const t = designTarget(raw, pilot);
      if (!t) return raw;
      return href(t.site === 'current' ? site : t.site, t.path);
    },
    [site, href, pilot],
  );
}

/** Label for a sign-up call to action; pilot-only builds send it to the pilot form. */
export function portalLabel(label: string): string {
  return pilotOnly() ? 'Request a pilot' : label;
}

/* Motion ------------------------------------------------------------------- */

/** True when the visitor asked for reduced motion (false while prerendering). */
export function useReducedMotion(): boolean {
  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    if (typeof matchMedia === 'undefined') return;
    const mq = matchMedia('(prefers-reduced-motion: reduce)');
    setReduce(mq.matches);
    const on = () => setReduce(mq.matches);
    mq.addEventListener?.('change', on);
    return () => mq.removeEventListener?.('change', on);
  }, []);
  return reduce;
}
