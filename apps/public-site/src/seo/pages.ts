/**
 * Every page a site build prerenders, with its search and link-preview
 * metadata (design/designs helmets via PAGE_META; templated pages from their
 * content). scripts/prerender.mjs writes one HTML file per entry and lists the
 * indexable ones in sitemap.xml.
 */
import { PAGE_META, type PageMeta, type PageSlug } from '@site/design/page-meta';
import { FEATURES } from '@site/pages/aether/aether-feature-page';
import { CONNECT_TOPICS, DETAILS, TRUST_TOPICS } from '@site/pages/aether/aether-detail-page';
import { DOCS_ORDER, DOCS_PAGES, DOCS_SECTIONS } from '@site/pages/docs/docs-model';
import { LEGAL_DOCS } from '@site/pages/legal-page';
import { LEGACY_AETHER_REDIRECTS } from '@site/app/legacy-routes';
import { pathOffered } from '@site/site/access';
import type { SiteId } from '@site/site/site';

export type JsonLdKind = 'organization' | 'website' | 'product' | 'article' | 'page';

export interface PrerenderPage extends PageMeta {
  /** Site path, e.g. `/platform/graph`. */
  path: string;
  /** Listed in sitemap.xml and open to indexing. */
  index: boolean;
  jsonLd: JsonLdKind;
}

export interface RedirectStub {
  path: string;
  /** Same-site path, or an absolute URL on the other site. */
  to: string;
  olympus: boolean;
}

const fromSlug = (path: string, slug: PageSlug, jsonLd: JsonLdKind = 'page', over: Partial<PageMeta> = {}): PrerenderPage => ({
  path,
  ...PAGE_META[slug],
  ...over,
  index: true,
  jsonLd,
});

function shared(site: SiteId): PrerenderPage[] {
  const brand = site === 'olympus' ? 'Olympus Labs' : 'Aether';
  return [
    fromSlug('/contact', 'contact', 'page', { title: `Contact — ${brand}` }),
    ...(['privacy', 'terms'] as const).map((doc) =>
      fromSlug(`/legal/${doc}`, 'legal', 'page', { title: `${LEGAL_DOCS[doc].title} — Olympus Labs`, description: LEGAL_DOCS[doc].lead }),
    ),
  ];
}

export function prerenderPages(site: SiteId): PrerenderPage[] {
  if (site === 'olympus') {
    return [
      fromSlug('/', 'olympus-home', 'website'),
      fromSlug('/technology', 'olympus-technology'),
      fromSlug('/applications', 'olympus-applications'),
      fromSlug('/company', 'olympus-company', 'organization'),
      fromSlug('/principles', 'olympus-principles'),
      fromSlug('/research', 'olympus-research'),
      fromSlug('/stories', 'olympus-stories'),
      ...shared(site),
    ];
  }
  const pages: PrerenderPage[] = [
    fromSlug('/', 'aether-home', 'product'),
    fromSlug('/platform', 'aether-platform'),
    ...Object.entries(FEATURES).map(([id, f]) => fromSlug(`/platform/${id}`, 'aether-feature', 'page', { title: `${f.name} — Aether`, description: f.lead })),
    fromSlug('/platform/lenses', 'aether-lenses'),
    fromSlug('/platform/agents', 'aether-agents'),
    fromSlug('/how-it-works', 'aether-how-it-works'),
    fromSlug('/applications', 'aether-applications'),
    fromSlug('/applications/customer-intelligence', 'aether-customer-intelligence'),
    fromSlug('/connect', 'aether-connect'),
    ...CONNECT_TOPICS.map((t) => fromSlug(`/connect/${t}`, 'aether-detail', 'page', { title: `${DETAILS[t]!.name} — Aether`, description: DETAILS[t]!.lead })),
    fromSlug('/trust', 'aether-trust'),
    ...TRUST_TOPICS.map((t) => fromSlug(`/trust/${t}`, 'aether-detail', 'page', { title: `${DETAILS[t]!.name} — Aether`, description: DETAILS[t]!.lead })),
    fromSlug('/security', 'aether-security'),
    fromSlug('/procurement', 'aether-procurement'),
    fromSlug('/pricing', 'aether-pricing'),
    fromSlug('/docs', 'docs'),
    ...DOCS_SECTIONS.map((s) => fromSlug(`/docs/section/${s.id}`, 'docs', 'page', { title: `${s.label} — Aether docs` })),
    ...DOCS_ORDER.map((id) => fromSlug(`/docs/${id}`, 'docs', 'article', { title: `${DOCS_PAGES[id]!.title} — Aether docs`, description: DOCS_PAGES[id]!.lead })),
    fromSlug('/docs/glossary', 'glossary'),
    fromSlug('/docs/symbol-key', 'symbol-key'),
    fromSlug('/status', 'status'),
    ...shared(site),
  ];
  // Pilot-only builds keep /status (it says status is shared with pilot partners) but do not list it.
  return pages.map((p) => (pathOffered(p.path) ? p : { ...p, index: false }));
}

/** Old Aether marketing URLs, prerendered as redirect pages so links and crawlers land on the new pages. */
export function redirectStubs(site: SiteId): RedirectStub[] {
  if (site !== 'aether') return [];
  const pages = new Set(prerenderPages(site).map((p) => p.path));
  return LEGACY_AETHER_REDIRECTS.filter((r) => !r.from.includes('*') && !pages.has(r.from)).map((r) => ({ path: r.from, to: r.to, olympus: !!r.olympus }));
}
