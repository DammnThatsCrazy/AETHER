import { describe, expect, it } from 'vitest';
import { SECTIONS } from '../content/sections';
import seoData from '../../seo-data.json';

/**
 * Keeps the prerender manifest (seo-data.json) in bijective parity with the
 * editorial section copy that actually renders each route. The title suffix here
 * must equal the composite document title the section page renders
 * (`src/pages/section-page.tsx` uses `\`${section.title} — Olympus Labs\``).
 */
const SUFFIX = 'Olympus Labs';

interface SeoRoute {
  readonly path: string;
  readonly title: string;
  readonly description: string;
}

interface SeoData {
  readonly host: string;
  readonly robotsDisallow: string[];
  readonly routes: SeoRoute[];
}

const SEO = seoData as unknown as SeoData;

describe('seo-data.json parity with the content model', () => {
  it('hosts an absolute origin with no trailing slash', () => {
    expect(SEO.host.startsWith('https://')).toBe(true);
    expect(SEO.host.endsWith('/')).toBe(false);
  });

  it('carries one route per section slug and nothing else', () => {
    expect(SEO.routes).toHaveLength(SECTIONS.length);
    const routePaths = SEO.routes.map((route) => route.path);
    expect(new Set(routePaths).size).toBe(SECTIONS.length);
    for (const section of SECTIONS) {
      expect(routePaths).toContain(section.slug);
    }
  });

  it('matches each route head to the exact title and description its section renders', () => {
    for (const section of SECTIONS) {
      const route = SEO.routes.find((candidate) => candidate.path === section.slug);
      expect(route, `no seo-data route for ${section.slug}`).toBeDefined();
      if (route === undefined) continue;
      expect(route.title).toBe(`${section.title} — ${SUFFIX}`);
      expect(route.description).toBe(section.description);
    }
  });

  it('excludes the home route and any robots-disallowed (auth) route from prerendering', () => {
    for (const route of SEO.routes) {
      expect(route.path).not.toBe('/');
      expect(SEO.robotsDisallow).not.toContain(route.path);
    }
  });
});
