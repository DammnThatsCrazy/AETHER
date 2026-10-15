import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { AETHER_MARKETING_URL } from '@aether-marketing/lib/env';

export interface PageMeta {
  readonly title: string;
  readonly description?: string;
  readonly robots?: 'index,follow' | 'noindex,nofollow';
  readonly canonical?: string;
}

/** The marketing site manages one robots directive per route; index routes get
 * the standard default and only the quiet authentication threshold routes opt
 * out. Keeping the directive reconciled (rather than leave-whatever-was-there)
 * is what guarantees a `noindex` never lingers into an indexable route. */
export const DEFAULT_ROBOTS = 'index,follow';

/** Absolute default canonical for a route, derived from the marketing origin. */
export function defaultCanonical(pathname: string): string {
  const origin = AETHER_MARKETING_URL.replace(/\/$/, '');
  return pathname === '/' || pathname === '' ? `${origin}/` : `${origin}${pathname}`;
}

type MetaAttrs = Record<string, string>;

/**
 * Adopt an existing head element (static index.html tags or a tag an earlier
 * route created) or create one. Every managed element carries a stable
 * `data-meta-key` so route changes update in place instead of duplicating.
 */
function upsertMetaElement(options: {
  readonly key: string;
  readonly selector: string;
  readonly tag?: 'meta' | 'link';
  readonly attributes: MetaAttrs;
  readonly created: Set<Element>;
}): void {
  const apply = (element: HTMLMetaElement | HTMLLinkElement): void => {
    element.setAttribute('data-meta-key', options.key);
    for (const [name, value] of Object.entries(options.attributes)) {
      element.setAttribute(name, value);
    }
  };

  const existing = document.head.querySelector<HTMLMetaElement | HTMLLinkElement>(options.selector);
  if (existing !== null) {
    apply(existing);
    return;
  }

  const element = document.createElement(options.tag ?? 'meta') as HTMLMetaElement | HTMLLinkElement;
  apply(element);
  document.head.appendChild(element);
  options.created.add(element);
}

/**
 * Sets the complete, honest <head> for a marketing route: document title,
 * description, canonical, robots, and Open Graph + Twitter card tags. Tags the
 * hook creates are removed on unmount; tags it merely adopted (the static
 * index.html defaults) are updated in place and left for the next route.
 */
export function usePageMeta(meta: PageMeta): void {
  const { pathname } = useLocation();
  const { title, description, robots, canonical } = meta;

  useEffect(() => {
    const created = new Set<Element>();
    document.title = title;

    if (description !== undefined) {
      upsertMetaElement({
        key: 'description',
        selector: 'meta[name="description"]',
        attributes: { name: 'description', content: description },
        created,
      });
    }

    const canonicalUrl = canonical ?? defaultCanonical(pathname);
    upsertMetaElement({
      key: 'canonical',
      selector: 'link[rel="canonical"]',
      tag: 'link',
      attributes: { rel: 'canonical', href: canonicalUrl },
      created,
    });

    const robotsContent = robots ?? DEFAULT_ROBOTS;
    upsertMetaElement({
      key: 'robots',
      selector: 'meta[name="robots"]',
      attributes: { name: 'robots', content: robotsContent },
      created,
    });

    const socialDescription = description ?? title;
    const social: readonly { readonly key: string; readonly name: string; readonly content: string }[] = [
      { key: 'og:title', name: 'og:title', content: title },
      { key: 'og:description', name: 'og:description', content: socialDescription },
      { key: 'og:url', name: 'og:url', content: canonicalUrl },
      { key: 'og:type', name: 'og:type', content: 'website' },
      { key: 'og:site_name', name: 'og:site_name', content: 'Aether by Olympus Labs' },
      { key: 'twitter:card', name: 'twitter:card', content: 'summary' },
      { key: 'twitter:title', name: 'twitter:title', content: title },
      { key: 'twitter:description', name: 'twitter:description', content: socialDescription },
    ];

    for (const item of social) {
      const isOg = item.key.startsWith('og:');
      upsertMetaElement({
        key: item.key,
        selector: isOg ? `meta[property="${item.name}"]` : `meta[name="${item.name}"]`,
        attributes: isOg
          ? { property: item.name, content: item.content }
          : { name: item.name, content: item.content },
        created,
      });
    }

    return () => {
      created.forEach((element) => element.remove());
    };
  }, [title, description, robots, canonical, pathname]);
}
