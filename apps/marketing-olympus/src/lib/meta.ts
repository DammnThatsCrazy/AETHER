import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { OLYMPUS_SITE_URL } from '@olympus-marketing/lib/env';

export interface PageMeta {
  readonly title: string;
  readonly description?: string;
  readonly robots?: 'index,follow' | 'noindex,nofollow';
  readonly canonical?: string;
}

const META_DATA_KEY = 'data-olympus-meta';
const SITE_NAME = 'Olympus Labs';

/** Every managed head slot this hook can own, keyed by its stable identity. */
const SLOT_KEYS = [
  'description',
  'canonical',
  'robots',
  'og:title',
  'og:description',
  'og:url',
  'og:type',
  'og:site_name',
  'twitter:card',
  'twitter:title',
  'twitter:description',
] as const;

function defaultCanonical(pathname: string): string {
  // pathname always begins with "/"; "/" keeps the origin's trailing slash.
  return `${OLYMPUS_SITE_URL}${pathname === '/' ? '/' : pathname}`;
}

function ownedSelector(key: string): string {
  return `[${META_DATA_KEY}="${key}"]`;
}

function removeOwned(key: string): void {
  document.head.querySelector(ownedSelector(key))?.remove();
}

/**
 * Write a single head tag. Prefers updating a tag this hook already owns, then a
 * pre-existing default from index.html, and only then creates a fresh owned tag.
 * Fresh tags (and, when `adoptExisting` is set, reused defaults) are tracked in
 * `created` so the effect's cleanup removes exactly what this hook touched.
 */
function applyTag(
  tag: 'meta' | 'link',
  attrs: Readonly<Record<string, string>>,
  key: string,
  findDefault: () => Element | null,
  created: Set<string>,
  adoptExisting = false,
): void {
  const owned = document.head.querySelector<Element>(ownedSelector(key));
  const existing = owned ?? findDefault();
  if (existing) {
    for (const [name, value] of Object.entries(attrs)) {
      existing.setAttribute(name, value);
    }
    if (owned !== null || adoptExisting) {
      existing.setAttribute(META_DATA_KEY, key);
      created.add(key);
    }
    return;
  }
  const el = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    el.setAttribute(name, value);
  }
  el.setAttribute(META_DATA_KEY, key);
  document.head.appendChild(el);
  created.add(key);
}

/**
 * Sets the complete `<head>` for a marketing route: title, description, robots
 * (only when a route opts in), an absolute canonical, and Open Graph + Twitter
 * tags. Canonical defaults to `OLYMPUS_SITE_URL + pathname`; pass `canonical`
 * to override. Tags this hook creates carry `data-olympus-meta` so route
 * changes update in place and unmounting removes exactly what this hook added.
 * Safe under jsdom (no matchMedia, no layout dependencies).
 */
export function usePageMeta(meta: PageMeta): void {
  const { pathname } = useLocation();

  useEffect(() => {
    // Clear anything a previous route's instance of this hook created so SPA
    // navigation never stacks duplicate tags. Static index.html defaults are
    // reused in place and are not removed.
    for (const key of SLOT_KEYS) {
      removeOwned(key);
    }

    const canonical = meta.canonical ?? defaultCanonical(pathname);
    const description = meta.description ?? meta.title;
    const created = new Set<string>();

    document.title = meta.title;

    if (meta.description !== undefined) {
      applyTag(
        'meta',
        { name: 'description', content: meta.description },
        'description',
        () => document.head.querySelector('meta[name="description"]'),
        created,
      );
    }

    applyTag(
      'link',
      { rel: 'canonical', href: canonical },
      'canonical',
      () => document.head.querySelector('link[rel="canonical"]'),
      created,
    );

    // Robots is opt-in only: when a route does not declare one, remove any this
    // hook set on a previous route and leave the static default alone.
    if (meta.robots !== undefined) {
      applyTag(
        'meta',
        { name: 'robots', content: meta.robots },
        'robots',
        () => document.head.querySelector('meta[name="robots"]'),
        created,
        true,
      );
    }

    // Open Graph
    applyTag(
      'meta',
      { property: 'og:title', content: meta.title },
      'og:title',
      () => document.head.querySelector('meta[property="og:title"]'),
      created,
    );
    applyTag(
      'meta',
      { property: 'og:description', content: description },
      'og:description',
      () => document.head.querySelector('meta[property="og:description"]'),
      created,
    );
    applyTag(
      'meta',
      { property: 'og:url', content: canonical },
      'og:url',
      () => document.head.querySelector('meta[property="og:url"]'),
      created,
    );
    applyTag(
      'meta',
      { property: 'og:type', content: 'website' },
      'og:type',
      () => document.head.querySelector('meta[property="og:type"]'),
      created,
    );
    applyTag(
      'meta',
      { property: 'og:site_name', content: SITE_NAME },
      'og:site_name',
      () => document.head.querySelector('meta[property="og:site_name"]'),
      created,
    );

    // Twitter
    applyTag(
      'meta',
      { name: 'twitter:card', content: 'summary' },
      'twitter:card',
      () => document.head.querySelector('meta[name="twitter:card"]'),
      created,
    );
    applyTag(
      'meta',
      { name: 'twitter:title', content: meta.title },
      'twitter:title',
      () => document.head.querySelector('meta[name="twitter:title"]'),
      created,
    );
    applyTag(
      'meta',
      { name: 'twitter:description', content: description },
      'twitter:description',
      () => document.head.querySelector('meta[name="twitter:description"]'),
      created,
    );

    return () => {
      for (const key of created) {
        removeOwned(key);
      }
    };
  }, [meta.title, meta.description, meta.robots, meta.canonical, pathname]);
}
